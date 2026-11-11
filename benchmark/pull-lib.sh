#!/usr/bin/env bash
#
# benchmark/pull-lib.sh — pulling node logs over IAP without corrupting them, and proving that
# the pulled unit logs cover the run.
#
# Sourced by bench-lib.sh (after bench_manifest_note). It only defines functions: sourcing it runs
# nothing and sourcing it twice is harmless. It uses, at call time, devnet-lib.sh's tn_iap_ssh,
# tn_iap_ssh_stdin and tn_iap_fault_kind, and bench-lib.sh's BENCH_NODE_UNIT_LOGS
# ("<stream>:<node file> ...", the unit's append logs).
#
# Why a pull of its own: devnet-lib's _tn_iap_retry sends every attempt's stdout to the caller,
# so a retried streaming pull concatenates the cut-off bytes of a failed attempt with the
# retry's. Here every attempt writes its own temp file with devnet-lib's retry off, the bytes are
# checked whole before they are renamed into place, and the retry is this file's.
#
# Why the span: bench 3's teardown pulled only the live unit file while logrotate had moved the
# start of the run to telcoin.log.1 (followups D19). The span lists every generation of every
# unit log on the node with its first and last timestamp, the rotated generations are pulled
# too, and the coverage check refuses a node whose logs start after the coordinated start or
# end before the blast did.
#
# Marker lines (one per line on stdout):
#   LOGSPAN <inst> stream=<s> gen=<N> file=<node path> bytes=<n|-> first=<ISO|-> last=<ISO|->
#   LOGCOV <inst> gens=<n|-> first=<ISO|-> last=<ISO|-> due=<ISO|-> end=<ISO|-> ok=<0|1|->
# Remote session headers (the first line of the script on stdin): "# bench-pull: span",
# "# bench-pull: rotated", "# bench-pull: bucket" (the bucket transfer, at the end of this file).
# Files: <dest>/<inst>.logspan, <dest>/<inst>-unit-<stream>.rotated-<N>.log.gz (name taken:
# <dest>/<inst>-unit-<stream>-<UTC stamp>.rotated-<N>.log.gz).
# Knobs: BENCH_IAP_RETRIES (attempts per stream, default 3), BENCH_PULL_STOP_FILE (touched when
# gcloud needs re-authentication; while it exists no pull starts), BENCH_PULL_JOBS (the bucket
# transfer's nodes at a time, default 4).

# bench_pull_stream <inst> <zone> <gz|tar|txt> <out> <cmd|stdin> <text> — one stream from the
# node into <out>. <text> is the remote command (cmd: tn_iap_ssh) or a script for the node's
# `sudo bash -s` (stdin: tn_iap_ssh_stdin). Up to BENCH_IAP_RETRIES attempts (default 3); each
# writes a fresh temp file "<out>.a??????" with TN_IAP_RETRIES=0, so devnet-lib never retries
# inside the attempt, and the bytes are checked before the rename: gz must pass gzip -t and hold
# at least one byte, tar must list with tar -tf and end in its zero blocks, txt must be
# non-empty. A failed session is classed by tn_iap_fault_kind: transport and iap-refused are
# retried (10 s, 20 s, ... apart); reauth touches BENCH_PULL_STOP_FILE and stops; anything else
# fails. A session that exits 0 with bytes that do not check is a cut stream and is retried as a
# transport fault. Nothing is
# started while BENCH_PULL_STOP_FILE exists. <out> is replaced when it lands; it is never touched
# otherwise, and no temp file outlives the call. Quiet on success and on empty; retries and
# failures are reported on stderr, with each attempt's gcloud stderr.
# rc 0 landed; 1 empty (nothing on the node, normal); 2 failed; 3 stopped (re-authentication).
bench_pull_stream() {
    local inst="${1:-}" zone="${2:-}" kind="${3:-}" out="${4:-}" how="${5:-}" text="${6:-}"
    local tries="${BENCH_IAP_RETRIES:-3}" attempt=0 tmp errf rc fault what
    case "${kind}" in gz|tar|txt) ;; *) echo "❌ bench_pull_stream: kind '${kind}' is not gz, tar or txt" >&2; return 2 ;; esac
    case "${how}" in cmd|stdin) ;; *) echo "❌ bench_pull_stream: '${how}' is not cmd or stdin" >&2; return 2 ;; esac
    if [ -z "${inst}" ] || [ -z "${zone}" ] || [ -z "${out}" ] || [ -z "${text}" ]; then
        echo "❌ bench_pull_stream <inst> <zone> <gz|tar|txt> <out> <cmd|stdin> <text>: missing argument" >&2
        return 2
    fi
    case "${tries}" in ''|*[!0-9]*|0*) echo "⚠ BENCH_IAP_RETRIES='${tries}' is not a positive integer — using 3" >&2; tries=3 ;; esac
    while :; do
        if [ -n "${BENCH_PULL_STOP_FILE:-}" ] && [ -e "${BENCH_PULL_STOP_FILE}" ]; then
            echo "      - ${inst}: ${out##*/} not pulled: gcloud needs re-authentication (${BENCH_PULL_STOP_FILE} exists)" >&2
            return 3
        fi
        attempt=$((attempt + 1))
        tmp="$(mktemp "${out}.aXXXXXX")" || { echo "      ✗ ${inst}: no temp file beside ${out}" >&2; return 2; }
        errf="$(mktemp)" || { rm -f -- "${tmp}"; echo "      ✗ ${inst}: no temp file for gcloud's stderr" >&2; return 2; }
        rc=0
        if [ "${how}" = stdin ]; then
            printf '%s\n' "${text}" | TN_IAP_RETRIES=0 tn_iap_ssh_stdin "${inst}" "${zone}" > "${tmp}" 2> "${errf}" || rc=$?
        else
            TN_IAP_RETRIES=0 tn_iap_ssh "${inst}" "${zone}" "${text}" > "${tmp}" 2> "${errf}" || rc=$?
        fi
        cat -- "${errf}" >&2
        what=""
        if [ "${rc}" -eq 0 ]; then
            if [ ! -s "${tmp}" ]; then rm -f -- "${tmp}" "${errf}"; return 1; fi
            case "${kind}" in
                gz)
                    if ! gzip -t -- "${tmp}" 2>/dev/null; then
                        what="the gzip stream is not whole"
                    elif [ "$(gzip -cd -- "${tmp}" 2>/dev/null | head -c 1 | wc -c)" -ne 1 ]; then
                        # gzip of no input is still 20 bytes: nothing was there to copy.
                        rm -f -- "${tmp}" "${errf}"
                        return 1
                    fi ;;
                tar)
                    # A cut between two members still lists: the end-of-archive zero blocks tell.
                    if ! tar -tf "${tmp}" >/dev/null 2>&1 || [ "$(tail -c 1024 "${tmp}" | tr -d '\000' | wc -c)" -ne 0 ]; then
                        what="the tar archive is not whole"
                    fi ;;
            esac
            if [ -z "${what}" ]; then
                rm -f -- "${errf}"
                if ! mv -f -- "${tmp}" "${out}"; then
                    rm -f -- "${tmp}"
                    echo "      ✗ ${inst}: could not rename the pulled copy to ${out}" >&2
                    return 2
                fi
                return 0
            fi
            fault=transport
        else
            fault="$(tn_iap_fault_kind "${rc}" "${errf}")" || fault=other
            what="${fault} (rc ${rc})"
        fi
        rm -f -- "${tmp}" "${errf}"
        case "${fault}" in
            reauth)
                if [ -n "${BENCH_PULL_STOP_FILE:-}" ]; then touch -- "${BENCH_PULL_STOP_FILE}" 2>/dev/null || true; fi
                echo "      ✗ ${inst}: ${out##*/}: gcloud needs re-authentication (run: gcloud auth login) — not retried; the pull stops" >&2
                return 3 ;;
            transport|iap-refused)
                if [ "${attempt}" -lt "${tries}" ]; then
                    echo "      … ${inst}: ${out##*/}: ${what} (attempt ${attempt}/${tries}); retrying in $((attempt * 10)) s" >&2
                    sleep "$((attempt * 10))"
                    continue
                fi ;;
        esac
        echo "      ✗ ${inst}: ${out##*/}: ${what} after ${attempt} attempt(s) — not pulled" >&2
        return 2
    done
}

# _bench_pull_unit_pairs — BENCH_NODE_UNIT_LOGS as a bash array assignment for a remote script
# ("pairs=( stdout:/var/log/... ... )", each pair %q-quoted). Non-zero and nothing on stdout
# when it is empty or a pair is not <stream>:<absolute path> with a [a-z] stream name.
_bench_pull_unit_pairs() {
    local p s f text="pairs=("
    for p in ${BENCH_NODE_UNIT_LOGS:-}; do
        s="${p%%:*}"; f="${p#*:}"
        # Spelled out, not a-z: a range can match capitals under some locales.
        case "${s}" in ''|*[!abcdefghijklmnopqrstuvwxyz]*) echo "❌ BENCH_NODE_UNIT_LOGS: bad stream in '${p}'" >&2; return 1 ;; esac
        case "${f}" in /*) ;; *) echo "❌ BENCH_NODE_UNIT_LOGS: '${p}' does not name an absolute path" >&2; return 1 ;; esac
        text="${text} $(printf '%q' "${p}")"
    done
    [ "${text}" != "pairs=(" ] || { echo "❌ BENCH_NODE_UNIT_LOGS is empty" >&2; return 1; }
    printf '%s )\n' "${text}"
}

# bench_unit_log_span_script <inst> — the script (for the node's `sudo bash -s`) that prints one
# LOGSPAN line per unit log stream (BENCH_NODE_UNIT_LOGS) and generation: <f> is gen 0, printed
# with bytes=- when it is missing; <f>.N and <f>.N.gz are gen N (a rotated generation that is
# missing is not printed). first = the first timestamped line among the file's first 20 (head;
# zcat for .gz); last = the last timestamped line among its last 20, read only for plain gens 0
# and 1 (an older one would have to be decompressed whole). A timestamp is a line's leading
# "[ts=]YYYY-MM-DD[T ]HH:MM:SS", printed as YYYY-MM-DDTHH:MM:SSZ. It only reads.
bench_unit_log_span_script() {
    local inst="${1:-}" pairs
    case "${inst}" in ''|*[!A-Za-z0-9._-]*) echo "❌ bench_unit_log_span_script <inst>: bad instance name '${inst}'" >&2; return 1 ;; esac
    pairs="$(_bench_pull_unit_pairs)" || return 1
    printf '%s\n' '# bench-pull: span' "inst=${inst}" "${pairs}"
    _bench_span_body
    echo 'exit 0'
}

# _bench_span_body — the span script's body (bench_unit_log_span_script), for a script that has
# set inst= and pairs=( ... ) already: one LOGSPAN line per unit log stream and generation. The
# bucket transfer's node script (bench_bucket_logs_script) starts with it too.
_bench_span_body() {
    cat <<'EOS'
ts() { sed -n -E 's/^(ts=)?"?([0-9]{4}-[0-9]{2}-[0-9]{2})[T ]([0-9]{2}:[0-9]{2}:[0-9]{2}).*$/\2T\3Z/p'; }
gens() {
    for g in "$1".[0-9]*; do
        [ -f "$g" ] || continue
        n=${g#"$1".}; n=${n%.gz}
        case $n in ''|*[!0-9]*) continue ;; esac
        echo "$n $g"
    done | sort -n -k1,1
}
span() {
    first=""; last=""
    bytes=$(wc -c < "$3" | tr -d ' ')
    case $3 in
        *.gz) first=$(gzip -cd -- "$3" 2>/dev/null | head -n 20 | ts | head -n 1) ;;
        *) first=$(head -n 20 -- "$3" | ts | head -n 1)
           if [ "$2" -le 1 ]; then last=$(tail -n 20 -- "$3" | ts | tail -n 1); fi ;;
    esac
    echo "LOGSPAN $inst stream=$1 gen=$2 file=$3 bytes=${bytes:--} first=${first:--} last=${last:--}"
}
for p in "${pairs[@]}"; do
    s=${p%%:*}; f=${p#*:}
    if [ -f "$f" ]; then span "$s" 0 "$f"; else echo "LOGSPAN $inst stream=$s gen=0 file=$f bytes=- first=- last=-"; fi
    gens "$f" | while read -r n g; do span "$s" "$n" "$g"; done
done
EOS
}

# bench_pull_unit_span <inst> <zone> <dest> — the node's LOGSPAN lines into <dest>/<inst>.logspan
# (replaced each time: it describes the node as it is now). One ssh session. rc as
# bench_pull_stream.
bench_pull_unit_span() {
    local inst="${1:-}" zone="${2:-}" dest="${3:-}" script
    if [ -z "${inst}" ] || [ -z "${zone}" ] || [ -z "${dest}" ]; then
        echo "❌ bench_pull_unit_span <inst> <zone> <dest>: missing argument" >&2; return 2
    fi
    script="$(bench_unit_log_span_script "${inst}")" || return 2
    bench_pull_stream "${inst}" "${zone}" txt "${dest}/${inst}.logspan" stdin "${script}"
}

# _bench_pull_rotated_name <name> — 0 for a plain unit-<stream>.rotated-<N>.log.gz name.
_bench_pull_rotated_name() {
    local s="${1#unit-}" n="${1##*.rotated-}"
    case "$1" in unit-*.rotated-*.log.gz) ;; *) return 1 ;; esac
    s="${s%%.rotated-*}"; n="${n%.log.gz}"
    case "${s}" in ''|*[!abcdefghijklmnopqrstuvwxyz]*) return 1 ;; esac
    case "${n}" in ''|*[!0-9]*) return 1 ;; esac
    [ "$1" = "unit-${s}.rotated-${n}.log.gz" ]
}

# bench_rotated_logs_script [<skip name>...] — the script (for the node's `sudo bash -s`) that
# writes to stdout a tar of every rotated generation of the unit logs (BENCH_NODE_UNIT_LOGS),
# each named unit-<stream>.rotated-<N>.log.gz, minus the skip names (in that form; others are
# dropped). <f>.1, which delaycompress leaves plain, is gzipped with -1 -n (no name and a zero
# time in the header: gzip reading a redirected file would store its mtime, so -n makes the bytes
# depend on the content alone); <f>.N.gz is hard-linked (copied if the link fails). The work
# directory is made beside the log (same file system, so a link is free) and removed on exit.
# Nothing to send: no output, rc 0. It never changes a log.
bench_rotated_logs_script() {
    local pairs n skip=" "
    pairs="$(_bench_pull_unit_pairs)" || return 1
    for n in "$@"; do _bench_pull_rotated_name "${n}" && skip="${skip}${n} "; done
    printf '%s\n' '# bench-pull: rotated' "${pairs}" "skip='${skip}'"
    cat <<'EOS'
w=""
trap '[ -z "$w" ] || rm -rf -- "$w"' EXIT
for p in "${pairs[@]}"; do
    s=${p%%:*}; f=${p#*:}
    for g in "$f".[0-9]*; do
        [ -f "$g" ] || continue
        n=${g#"$f".}; n=${n%.gz}
        case $n in ''|*[!0-9]*) continue ;; esac
        name=unit-$s.rotated-$n.log.gz
        case $skip in *" $name "*) continue ;; esac
        if [ -z "$w" ]; then w=$(mktemp -d "${f%/*}/.bench-pull.XXXXXX") || exit 1; fi
        [ ! -e "$w/$name" ] || continue
        case $g in
            *.gz) ln -- "$g" "$w/$name" 2>/dev/null || cp -p -- "$g" "$w/$name" || exit 1 ;;
            *) gzip -1 -n < "$g" > "$w/$name" || exit 1 ;;
        esac
    done
done
[ -n "$w" ] || exit 0
cd "$w" || exit 1
tar -cf - -- unit-*.rotated-*.log.gz
EOS
}

# bench_pull_rotated_logs <inst> <zone> <dest> [<skip>...] — the node's rotated unit log
# generations (bench_rotated_logs_script, one ssh session, through bench_pull_stream) land as
# <dest>/<inst>-unit-<stream>.rotated-<N>.log.gz; a name already taken by a non-empty file gets
# <dest>/<inst>-unit-<stream>-<UTC stamp>.rotated-<N>.log.gz instead (nothing is replaced). A skip
# is a name the caller already holds for this instance (a marker vouches for it): unit-…,
# <inst>-unit-… or a stamped copy's name, any directory dropped; that generation is not sent. The
# archive is checked whole and its names checked before anything is unpacked; the work directory
# (a dot-named directory in <dest>) is removed on every path. One "✓ <inst> -> <file>" per file.
# rc as bench_pull_stream (1 = no rotated generation to send).
bench_pull_rotated_logs() {
    local inst="${1:-}" zone="${2:-}" dest="${3:-}" s b script work name stream gen out stamp rc=0 skip=()
    if [ -z "${inst}" ] || [ -z "${zone}" ] || [ -z "${dest}" ]; then
        echo "❌ bench_pull_rotated_logs <inst> <zone> <dest> [<skip>...]: missing argument" >&2; return 2
    fi
    shift 3
    [ -d "${dest}" ] || { echo "❌ bench_pull_rotated_logs: ${dest} is not a directory" >&2; return 2; }
    for s in "$@"; do
        s="${s##*/}"; s="${s#"${inst}"-}"
        case "${s}" in
            unit-*-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z.rotated-*)
                b="${s%%.rotated-*}"; s="${b%-*}.rotated-${s#*.rotated-}" ;;
        esac
        skip+=("${s}")
    done
    script="$(bench_rotated_logs_script "${skip[@]+"${skip[@]}"}")" || return 2
    work="$(mktemp -d "${dest}/.${inst}-rotated.XXXXXX")" || { echo "      ✗ ${inst}: no work directory in ${dest}" >&2; return 2; }
    bench_pull_stream "${inst}" "${zone}" tar "${work}/rotated.tar" stdin "${script}" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        rm -rf -- "${work}"
        [ "${rc}" -ne 1 ] || echo "      - ${inst}: no rotated unit log to pull"
        return "${rc}"
    fi
    if ! tar -tf "${work}/rotated.tar" > "${work}/names" 2>/dev/null || [ ! -s "${work}/names" ]; then
        rm -rf -- "${work}"; echo "      ✗ ${inst}: the rotated-log archive does not list" >&2; return 2
    fi
    while IFS= read -r name; do
        if ! _bench_pull_rotated_name "${name}"; then
            rm -rf -- "${work}"; echo "      ✗ ${inst}: unexpected name in the rotated-log archive — nothing unpacked" >&2; return 2
        fi
    done < "${work}/names"
    if ! mkdir -- "${work}/x" || ! tar -xf "${work}/rotated.tar" -C "${work}/x"; then
        rm -rf -- "${work}"; echo "      ✗ ${inst}: the rotated-log archive did not unpack" >&2; return 2
    fi
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    while IFS= read -r name; do
        stream="${name#unit-}"; stream="${stream%%.rotated-*}"
        gen="${name##*.rotated-}"; gen="${gen%.log.gz}"
        out="${dest}/${inst}-unit-${stream}.rotated-${gen}.log.gz"
        if [ -s "${out}" ]; then
            out="${dest}/${inst}-unit-${stream}-${stamp}.rotated-${gen}.log.gz"
            if [ -e "${out}" ]; then echo "      ✗ ${inst}: ${out} exists already — ${name} not landed" >&2; rc=2; continue; fi
        fi
        if ! mv -f -- "${work}/x/${name}" "${out}"; then
            echo "      ✗ ${inst}: could not land ${name} as ${out}" >&2; rc=2; continue
        fi
        echo "      ✓ ${inst} -> ${out}"
    done < "${work}/names"
    rm -rf -- "${work}"
    return "${rc}"
}

# _bench_pull_unix <time> — seconds since the epoch of a UTC time given as unix seconds or as
# YYYY-MM-DD[T ]HH:MM:SS[.fraction][Z|+00:00] (the fraction is dropped). Pure arithmetic, no
# date(1). Non-zero and no output for anything else ("-", "null", "").
_bench_pull_unix() {
    local t="${1:-}" rest y m d H M S era yoe doy doe
    case "${t}" in ''|*[!0-9]*) ;; *) printf '%s\n' "$((10#${t}))"; return 0 ;; esac
    case "${t}" in
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9][T\ ][0-9][0-9]:[0-9][0-9]:[0-9][0-9]*) ;;
        *) return 1 ;;
    esac
    rest="${t:19}"
    case "${rest}" in ''|Z|+00:00|.[0-9]*) ;; *) return 1 ;; esac
    case "${rest}" in .*) rest="${rest#.}"; rest="${rest##*[0-9]}"; case "${rest}" in ''|Z|+00:00) ;; *) return 1 ;; esac ;; esac
    y=$((10#${t:0:4})); m=$((10#${t:5:2})); d=$((10#${t:8:2}))
    H=$((10#${t:11:2})); M=$((10#${t:14:2})); S=$((10#${t:17:2}))
    if [ "${m}" -lt 1 ] || [ "${m}" -gt 12 ] || [ "${d}" -lt 1 ] || [ "${d}" -gt 31 ] \
        || [ "${H}" -gt 23 ] || [ "${M}" -gt 59 ] || [ "${S}" -gt 60 ]; then
        return 1
    fi
    # days_from_civil (proleptic Gregorian), years >= 0.
    [ "${m}" -gt 2 ] || y=$((y - 1))
    era=$((y / 400)); yoe=$((y - era * 400))
    doy=$(((153 * ((m + 9) % 12) + 2) / 5 + d - 1))
    doe=$((yoe * 365 + yoe / 4 - yoe / 100 + doy))
    printf '%s\n' "$(((era * 146097 + doe - 719468) * 86400 + H * 3600 + M * 60 + S))"
}

# _bench_pull_iso <unix seconds> — YYYY-MM-DDTHH:MM:SSZ (civil_from_days, no date(1)).
_bench_pull_iso() {
    local t="$1" z era doe yoe y doy mp d m
    z=$((t / 86400 + 719468)); era=$((z / 146097)); doe=$((z - era * 146097))
    yoe=$(((doe - doe / 1460 + doe / 36524 - doe / 146096) / 365))
    y=$((yoe + era * 400)); doy=$((doe - (365 * yoe + yoe / 4 - yoe / 100)))
    mp=$(((5 * doy + 2) / 153)); d=$((doy - (153 * mp + 2) / 5 + 1))
    if [ "${mp}" -lt 10 ]; then m=$((mp + 3)); else m=$((mp - 9)); fi
    [ "${m}" -gt 2 ] || y=$((y + 1))
    printf '%04d-%02d-%02dT%02d:%02d:%02dZ\n' "${y}" "${m}" "${d}" $((t % 86400 / 3600)) $((t % 3600 / 60)) $((t % 60))
}

# bench_log_coverage_check <dest> <inst> <due|-> <end|-> — do the unit logs of <inst> cover the run?
# Reads <dest>/<inst>.logspan (bench_pull_unit_span) only, stream stdout (the node's log; stderr
# is often empty): gens = its generations present on the node, first = the earliest first line
# over them, last = the latest last line. <due> (the coordinated start) and <end> (the blast's
# end) are unix seconds or ISO UTC, or - when unknown. ok=1 when first <= due and last >= end;
# ok=0 when either fails, or when a known side has no timestamp on the node to show for it (no
# log at all included); ok=- when the span file is missing, or every known side passed but one
# side is unknown. Prints one LOGCOV line; rc 1 only for ok=0 (2 for a usage error).
bench_log_coverage_check() {
    local dest="${1:-}" inst="${2:-}" due="${3:--}" end="${4:--}" span tag who stream gen file bytes f l v
    local gens=0 first="" last="" first_n="" last_n="" due_n="" end_n="" due_iso=- end_iso=- known=0 ok=-
    if [ -z "${dest}" ] || [ -z "${inst}" ]; then
        echo "❌ bench_log_coverage_check <dest> <inst> <due|-> <end|->: missing argument" >&2; return 2
    fi
    span="${dest}/${inst}.logspan"
    due_n="$(_bench_pull_unix "${due}")" || due_n=""
    end_n="$(_bench_pull_unix "${end}")" || end_n=""
    if [ -n "${due_n}" ]; then due_iso="$(_bench_pull_iso "${due_n}")"; known=$((known + 1)); fi
    if [ -n "${end_n}" ]; then end_iso="$(_bench_pull_iso "${end_n}")"; known=$((known + 1)); fi
    if [ ! -f "${span}" ]; then
        gens=-
    else
        while read -r tag who stream gen file bytes f l _; do
            [ "${tag}" = LOGSPAN ] && [ "${who}" = "${inst}" ] && [ "${stream}" = stream=stdout ] || continue
            case "${gen}/${file}/${bytes}/${f}/${l}" in gen=*/file=*/bytes=*/first=*/last=*) ;; *) continue ;; esac
            [ "${bytes}" != bytes=- ] || continue
            gens=$((gens + 1))
            if v="$(_bench_pull_unix "${f#first=}")" && { [ -z "${first_n}" ] || [ "${v}" -lt "${first_n}" ]; }; then
                first_n="${v}"; first="${f#first=}"
            fi
            if v="$(_bench_pull_unix "${l#last=}")" && { [ -z "${last_n}" ] || [ "${v}" -gt "${last_n}" ]; }; then
                last_n="${v}"; last="${l#last=}"
            fi
        done < "${span}"
        # An unknown reference leaves its side unchecked; a known one with no timestamp to show fails.
        if [ -z "${due_n}" ]; then due_n=0; first_n=0; elif [ -z "${first_n}" ]; then first_n=$((due_n + 1)); fi
        if [ -z "${end_n}" ]; then end_n=0; last_n=0; elif [ -z "${last_n}" ]; then last_n=$((end_n - 1)); fi
        ok=0
        [ "${first_n}" -le "${due_n}" ] && [ "${last_n}" -ge "${end_n}" ] && ok=1
        if [ "${ok}" = 1 ] && [ "${known}" -lt 2 ]; then ok=-; fi
    fi
    printf 'LOGCOV %s gens=%s first=%s last=%s due=%s end=%s ok=%s\n' \
        "${inst}" "${gens}" "${first:--}" "${last:--}" "${due_iso}" "${end_iso}" "${ok}"
    [ "${ok}" != 0 ]
}

# bench_logrotate_text <size> — the node-log rotation config the bench installs in place of v2's:
# tn-node-deployment's template (lib/common.sh _tn_logrotate_text) without `maxsize`, so the unit
# logs rotate only once they pass <size> (<digits>K|M|G, e.g. 20G), never at v2's 1G cap.
# Shape: the size is filled in here; the two node paths are left as placeholders for the node to
# fill from its own lib, on the node:
#   @LOGGLOB@ = "${DEFAULT_LOG_DIR}/*.log"   @GROUP@ = "${TN_LOG_GROUP}"
#   sed -e "s|@LOGGLOB@|${DEFAULT_LOG_DIR}/*.log|" -e "s|@GROUP@|${TN_LOG_GROUP}|"
# then written with `tn_write_root_file /etc/logrotate.d/telcoin 0644` and parsed with
# `logrotate -d`. v2's tn_install_logrotate keeps an existing file when called without a size,
# so a later v2 setup run leaves it alone. Nothing printed and rc 1 for a bad size.
bench_logrotate_text() {
    local size="${1:-}" n
    n="${size%[KMG]}"
    if [ "${n}" = "${size}" ]; then n=""; fi
    case "${n}" in ''|*[!0-9]*) echo "❌ bench_logrotate_text: size '${size}' is not <digits>K|M|G" >&2; return 1 ;; esac
    cat <<EOF
# Managed by benchmark (bench_logrotate_text): v2's node-log rotation with no upper size cap. Node logs rotate only past 'size'.
@LOGGLOB@ {
    su root @GROUP@
    size ${size}
    rotate 5
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
EOF
}

# bench_drop_if_identical <new> <existing> — remove <new> when it is byte-for-byte <existing>: a
# second pull of an unchanged log. An unchanged source pulls to identical bytes: gzip of a pipe
# writes a zero time, of a redirected file that file's mtime (unchanged with it), with -n a zero
# time; a linked .N.gz is the node's own bytes. rc 0 = dropped (one line says so); 1 = kept: they
# differ, either is missing or empty, or both name one file.
bench_drop_if_identical() {
    local new="${1:-}" old="${2:-}"
    [ -f "${new}" ] && [ -s "${new}" ] && [ -f "${old}" ] && [ -s "${old}" ] || return 1
    if [ "${new}" -ef "${old}" ]; then return 1; fi
    cmp -s -- "${new}" "${old}" || return 1
    rm -f -- "${new}" || return 1
    echo "      = ${new##*/} is identical to ${old##*/} — dropped"
}

# --- the bucket transfer (BENCH_LOG_TRANSFER=bucket) -----------------------------------------------
# The logs bench_pull_node_logs (bench-lib.sh) pulls, with the same names, bytes, spans and markers,
# but each node sends its own logs to the run bucket and the operator copies them down once. Bench 4's
# IAP pull took 4h19m at about 2 MB/s per session, and each dropped session restarted an 8-GB stream
# from byte 0 (A2, D25); the node's upload runs inside GCP, and the one download is gcloud storage's
# (parallel, retried and resumed inside gcloud).
# The node needs gcloud on root's PATH and a service account whose access scopes allow a GCS write
# (cloud-platform, devstorage.read_write or devstorage.full_control). Instances made by
# common/create-instances.sh get devstorage.read_only: the preflight refuses such a fleet before any
# session is opened, and the pull is run with BENCH_LOG_TRANSFER=iap.
# Lines on stdout: LOG_TRANSFER mode=bucket nodes=<n> first; LOG_TRANSFER_DONE mode=bucket bytes=<n>
# secs=<n> once the transfer has run (bytes the nodes sent, seconds since the first session).
# Node session header "# bench-pull: bucket". Objects: gs://<bucket>/logs/<inst>/<the local file
# name>, removed again once they are here, so the teardown's bucket backup does not copy them twice.
# Knob: BENCH_PULL_JOBS (nodes at a time, in the sessions and in the checks here; default 4).

# bench_bucket_write_scope <instance json> — the access scopes of the instance's service accounts,
# comma-joined without their URL prefix ("none" without any), on stdout; rc 0 when one allows a
# GCS write.
bench_bucket_write_scope() {
    local scopes
    scopes="$(printf '%s' "${1:-}" | jq -r '[.serviceAccounts[]?.scopes[]? | sub("^https://www.googleapis.com/auth/"; "")] | join(",")' 2>/dev/null)" || scopes=""
    printf '%s\n' "${scopes:-none}"
    case ",${scopes}," in *,cloud-platform,*|*,devstorage.read_write,*|*,devstorage.full_control,*) return 0 ;; esac
    return 1
}

# bench_bucket_logs_script <inst> <bucket> [<skip>...] — the script (for the node's `sudo bash -s`)
# of one node's bucket transfer. It prints the node's LOGSPAN lines (_bench_span_body), then sends
# each log the IAP pull would take to gs://<bucket>/logs/<inst>/<local name>, through the node's own
# gcloud, counting the bytes on the way: the current container's log (`docker logs telcoin 2>&1 |
# gzip -1`), the saved logs in BENCH_NODE_LOG_DIR as they are, the unit files (BENCH_NODE_UNIT_LOGS,
# `gzip -1 <`, skipped when missing or empty) and their rotated generations (<f>.N `gzip -1 -n <`,
# <f>.N.gz as it is): the bytes the IAP pull lands. A skip is a name a marker of the instance
# vouches for, in the node's form (<local name> minus "<inst>-"); the container's log is never
# skipped (a copy already here lands beside it). Per file one line: PULLED <name> bytes=<n> or
# FAILED <name> rc=<why> (the upload's stderr on the session's stderr). BUCKET_ERROR <inst> <why>
# when it cannot start, BUCKET_ALIVE <inst> every 60 s (so the session never sits silent through a
# long upload), BUCKET_END <inst> last. Always rc 0. It never changes a log.
bench_bucket_logs_script() {
    local inst="${1:-}" bucket="${2:-}" pairs n names=" "
    case "${inst}" in ''|*[!A-Za-z0-9._-]*) echo "❌ bench_bucket_logs_script <inst> <bucket>: bad instance name '${inst}'" >&2; return 1 ;; esac
    case "${bucket}" in ''|*[!a-z0-9._-]*) echo "❌ bench_bucket_logs_script <inst> <bucket>: bad bucket name '${bucket}'" >&2; return 1 ;; esac
    case "${BENCH_NODE_LOG_DIR:-}" in /*) ;; *) echo "❌ bench_bucket_logs_script: BENCH_NODE_LOG_DIR '${BENCH_NODE_LOG_DIR:-}' is not an absolute path" >&2; return 1 ;; esac
    pairs="$(_bench_pull_unit_pairs)" || return 1
    shift 2
    for n in "$@"; do
        case "${n}" in *[!A-Za-z0-9._-]*|'') ;; *.log.gz) names="${names}${n} " ;; esac
    done
    printf '%s\n' '# bench-pull: bucket' "inst=${inst}" "dst=gs://${bucket}/logs/${inst}" \
        "logdir=$(printf '%q' "${BENCH_NODE_LOG_DIR}")" "${pairs}" "skip='${names}'"
    _bench_span_body
    cat <<'EOS'
w=""; hb=""
trap '[ -z "$hb" ] || kill "$hb" 2>/dev/null; [ -z "$w" ] || rm -rf -- "$w"' EXIT
end() { echo "BUCKET_END $inst"; exit 0; }
command -v gcloud >/dev/null 2>&1 || { echo "BUCKET_ERROR $inst no gcloud on the node's PATH"; end; }
w=$(mktemp -d) || { w=""; echo "BUCKET_ERROR $inst no temp directory on the node"; end; }
( while sleep 60 </dev/null >/dev/null 2>&1; do echo "BUCKET_ALIVE $inst"; done ) &
hb=$!
set -o pipefail
seen=" "
send() {
    o=$1; shift
    case $seen in *" $o "*) return 0 ;; esac
    seen="$seen$o "
    rm -f -- "$w/f" "$w/n"
    mkfifo -- "$w/f" || { echo "FAILED $o rc=mkfifo"; return 0; }
    wc -c < "$w/f" > "$w/n" &
    c=$!
    r=0
    "$@" | tee -- "$w/f" | gcloud storage cp - "$dst/$o" 2> "$w/e" || r=$?
    wait "$c" 2>/dev/null || true
    n=$(tr -d ' ' < "$w/n" 2>/dev/null) || n=""
    case $r/$n in
        0/[0-9]*) echo "PULLED $o bytes=$n" ;;
        *) echo "FAILED $o rc=$r"; sed "s|^|      $inst: |" "$w/e" >&2 ;;
    esac
}
up() { case $skip in *" ${1#"$inst"-} "*) return 0 ;; esac; send "$@"; }
clog() { docker logs telcoin 2>&1 | gzip -1; }
gz1() { gzip -1 < "$1"; }
gzn() { gzip -1 -n < "$1"; }
if e=$(docker container inspect telcoin 2>&1 >/dev/null); then
    send "$inst-telcoin.log.gz" clog
else
    case $e in
        *"No such container"*) ;;
        *) echo "FAILED $inst-telcoin.log.gz rc=inspect"; echo "      $inst: docker container inspect failed: $e" >&2 ;;
    esac
fi
if [ -d "$logdir" ]; then
    for f in "$logdir"/*.log.gz; do
        [ -f "$f" ] || continue
        b=${f##*/}
        case $b in [A-Za-z0-9]*) ;; *) echo "FAILED $inst-saved-log rc=name"; continue ;; esac
        case $b in *[!A-Za-z0-9._-]*) echo "FAILED $inst-saved-log rc=name"; continue ;; esac
        up "$inst-$b" cat -- "$f"
    done
fi
for p in "${pairs[@]}"; do
    s=${p%%:*}; f=${p#*:}
    if [ -s "$f" ]; then up "$inst-unit-$s.log.gz" gz1 "$f"; fi
done
for p in "${pairs[@]}"; do
    s=${p%%:*}; f=${p#*:}
    for g in "$f".[0-9]*; do
        [ -f "$g" ] || continue
        n=${g#"$f".}; n=${n%.gz}
        case $n in ''|*[!0-9]*) continue ;; esac
        case $g in
            *.gz) up "$inst-unit-$s.rotated-$n.log.gz" cat -- "$g" ;;
            *) up "$inst-unit-$s.rotated-$n.log.gz" gzn "$g" ;;
        esac
    done
done
end
EOS
}

# _bench_bucket_send_node <inst> <zone> <dest> <work> <bucket> — the bucket transfer's first phase
# for one node, as _bench_pull_node starts: its instance id looked up now (<work>/<inst>.ident; the
# marker names it, and the landing checks it again), the names a marker of that instance vouches for
# (not sent again), then one session (bench_pull_stream: retries, the re-authentication stop) running
# bench_bucket_logs_script. Its LOGSPAN lines replace <dest>/<inst>.logspan; the whole answer stays
# in <work>/<inst>.session for the landing. A failed, empty or unfinished session, or one without a
# LOGSPAN line, fails the node and removes a <inst>.logspan an earlier pass left. A file the node
# could not send is reported here and marks the node (<work>/<inst>.xfer): what it did send still
# lands, and it gets no marker. rc 0 = the session ran; 1 = it failed; 3 = gcloud needs
# re-authentication.
_bench_bucket_send_node() {
    local inst="$1" zone="$2" dest="$3" work="$4" bucket="$5" ident vouched vbase n k=0 b=0 tag o v r=0 script skip=()
    local out="$4/$1.session" span="$3/$1.logspan"
    ident="$(_bench_instance_ident "${inst}" "${zone}")" || ident=""
    if [ -z "${ident}" ]; then
        echo "      ✗ ${inst}: its instance id could not be looked up — not pulled (the marker must name it)" >&2
        return 1
    fi
    printf '%s\n' "${ident}" > "${work}/${inst}.ident" || return 1
    vouched="$(bench_node_vouched_logs "${dest}" "${inst}" "${ident%% *}")"
    # shellcheck disable=SC2086  # plain file names
    vbase="$(_bench_unstamp_names ${vouched})"
    for n in ${vouched} ${vbase}; do skip+=("${n#"${inst}"-}"); done
    script="$(bench_bucket_logs_script "${inst}" "${bucket}" "${skip[@]+"${skip[@]}"}")" || return 1
    bench_pull_stream "${inst}" "${zone}" txt "${out}" stdin "${script}" || r=$?
    case "${r}" in
        0)  if ! grep -qx "BUCKET_END ${inst}" "${out}"; then
                echo "      ✗ ${inst}: the bucket session ended before its last line" >&2; r=2
            elif ! grep '^LOGSPAN ' "${out}" > "${work}/${inst}.logspan" || ! mv -f -- "${work}/${inst}.logspan" "${span}"; then
                echo "      ✗ ${inst}: the span of its unit logs was not recorded (no LOGSPAN line)" >&2; r=2
            fi ;;
        1) echo "      ✗ ${inst}: the bucket session answered nothing" >&2; r=2 ;;
        3) ;;
        *) echo "      ✗ ${inst}: the bucket session failed (rc ${r})" >&2 ;;
    esac
    if [ "${r}" -ne 0 ]; then
        if [ -e "${span}" ]; then
            rm -f -- "${span}" && echo "      - ${inst}: the ${inst}.logspan of an earlier pull is removed (it no longer describes the node)" >&2
        fi
        [ "${r}" -eq 3 ] && return 3
        return 1
    fi
    while read -r tag o v; do
        case "${tag}" in
            PULLED) case "${v#bytes=}" in ''|*[!0-9]*) ;; *) k=$((k + 1)); b=$((b + ${v#bytes=})) ;; esac ;;
            FAILED) echo "      ✗ ${inst}: ${o}: the node could not send it to the bucket (${v})" >&2; : > "${work}/${inst}.xfer" ;;
            BUCKET_ERROR) echo "      ✗ ${inst}: nothing sent: ${o} ${v}" >&2; : > "${work}/${inst}.xfer" ;;
        esac
    done < "${out}"
    echo "      ↑ ${inst}: ${k} log(s), ${b} bytes -> gs://${bucket}/logs/${inst}/"
}

# _bench_bucket_land_node <inst> <zone> <dest> <work> — the bucket transfer's last phase for one node:
# each file its session sent (PULLED <name> bytes=<n>), from the download in <work>/objects/<inst>/,
# checked (here, as many bytes as the node counted, gzip -t whole) and renamed into <dest> under the
# name the IAP pull gives it: <name> when that is free (or a zero-byte leftover), else the stamped
# name beside it (<base>-<UTC stamp>.log.gz, <base>-<UTC stamp>.rotated-<N>.log.gz), never over a
# file. A current-container log with no line in it (no container, or an empty log) is dropped, as
# the IAP pull drops it. Then _bench_pull_node's ending, the same rules: a stamped copy byte-identical
# to the file it stands beside is dropped; the node passes when no transfer failed and a log counts;
# the instance id must be the one looked up before the session; the marker (see "pull markers" in
# bench-lib.sh) is written and verified. rc 0 = marker written; 1 = failed.
_bench_bucket_land_node() {
    local inst="$1" zone="$2" dest="$3" work="$4" ident ident2 id tag o v sz src out stamp before after vouched n u new="" stale=0 got m xfer=0 nl=$'\n'
    ident="$(cat -- "${work}/${inst}.ident" 2>/dev/null)" || ident=""
    id="${ident%% *}"
    [ ! -e "${work}/${inst}.xfer" ] || xfer=1
    before="$(_bench_logs_here "${dest}" "${inst}")"
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    while read -r tag o v; do
        [ "${tag}" = PULLED ] || continue
        case "${o}" in
            *[!A-Za-z0-9._-]*) echo "      ✗ ${inst}: unexpected name '${o}' in its session — not landed" >&2; xfer=1; continue ;;
            "${inst}"-*.log.gz) ;;
            *) echo "      ✗ ${inst}: unexpected name '${o}' in its session — not landed" >&2; xfer=1; continue ;;
        esac
        src="${work}/objects/${inst}/${o}"
        [ -f "${src}" ] || src="${work}/objects/logs/${inst}/${o}"
        if [ ! -f "${src}" ]; then echo "      ✗ ${inst}: ${o} was not downloaded" >&2; xfer=1; continue; fi
        sz="$(wc -c < "${src}" | tr -d ' ')" || sz="?"
        if [ "${sz}" != "${v#bytes=}" ]; then echo "      ✗ ${inst}: ${o} is ${sz} bytes here; the node sent ${v#bytes=}" >&2; xfer=1; continue; fi
        if ! gzip -t -- "${src}" 2>/dev/null; then echo "      ✗ ${inst}: ${o}: the gzip stream is not whole" >&2; xfer=1; continue; fi
        if [ "${o}" = "${inst}-telcoin.log.gz" ] && [ "$(gzip -cd -- "${src}" 2>/dev/null | head -c 1 | wc -c)" -ne 1 ]; then
            rm -f -- "${src}"
            echo "      - ${inst}: no current-container log (no telcoin container, or its log is empty)"
            continue
        fi
        out="${dest}/${o}"
        if [ -s "${out}" ]; then
            case "${o}" in
                *.rotated-*.log.gz) out="${dest}/${o%%.rotated-*}-${stamp}.rotated-${o##*.rotated-}" ;;
                *) out="${dest}/${o%.log.gz}-${stamp}.log.gz" ;;
            esac
            if [ -e "${out}" ]; then echo "      ✗ ${inst}: ${out} exists already — ${o} not landed" >&2; xfer=1; continue; fi
            echo "      - ${inst}: ${dest}/${o} is here already — kept; this copy -> ${out}"
        fi
        if ! mv -f -- "${src}" "${out}"; then echo "      ✗ ${inst}: could not land ${o} as ${out}" >&2; xfer=1; continue; fi
        echo "      ✓ ${inst} -> ${out}"
    done < "${work}/${inst}.session"
    # _bench_pull_node's ending (bench-lib.sh), the same rules; keep the two in step.
    after="$(_bench_logs_here "${dest}" "${inst}")"
    for n in ${after}; do
        _bench_in_lines "${n}" "${before}" && continue
        u="$(_bench_unstamp_names "${n}")"
        if [ "${u}" != "${n}" ] && _bench_in_lines "${u}" "${before}"; then
            bench_drop_if_identical "${dest}/${n}" "${dest}/${u}" || true
            if [ ! -e "${dest}/${n}" ]; then
                echo "      - ${inst}: ${u} counts as this pull's (the copy just pulled was identical)"
                n="${u}"
            fi
        fi
        _bench_in_lines "${n}" "${new}" || new="${new}${new:+${nl}}${n}"
    done
    vouched="$(bench_node_vouched_logs "${dest}" "${inst}" "${id}")"   # re-read: still here, same sizes
    for n in ${vouched}; do _bench_in_lines "${n}" "${new}" || new="${new}${new:+${nl}}${n}"; done
    for n in ${before}; do _bench_in_lines "${n}" "${new}" || stale=$((stale + 1)); done
    # shellcheck disable=SC2086  # plain file names
    got="$(_bench_log_sources_of "${inst}" ${new})" || got=""
    if [ "${xfer}" -ne 0 ]; then
        echo "      ✗ ${inst}: a transfer failed (see above) — got so far: ${got:-nothing}" >&2
        return 1
    fi
    if [ -z "${got}" ]; then
        echo "      ✗ ${inst}: no log from any source (current container, saved logs, unit files)$([ "${stale}" -eq 0 ] || echo "; the ${stale} log(s) of this name already here are not vouched for by a marker of this instance and do not count")" >&2
        return 1
    fi
    ident2="$(_bench_instance_ident "${inst}" "${zone}")" || ident2=""
    if [ -z "${ident}" ] || [ "${ident2}" != "${ident}" ]; then
        echo "      ✗ ${inst}: the instance changed during the pull (${ident:-unknown} -> ${ident2:-not found}) — no marker" >&2
        return 1
    fi
    # shellcheck disable=SC2086  # plain file names
    m="$(_bench_write_marker "${dest}" "${inst}" "${id}" "${ident#* }" "${got}" ${new})" || return 1
    if ! _bench_marker_verdict "${m}" "${dest}" "${inst}" "${id}" > /dev/null; then
        echo "      ✗ ${inst}: its new marker ${m##*/} does not verify — not saved" >&2
        return 1
    fi
    echo "      ✓ ${inst}: ${got}"
}

# _bench_bucket_gcloud <errfile> <args>... — gcloud <args> with its stderr kept in <errfile> and
# shown; when it fails, its fault class (tn_iap_fault_kind) on stdout, and a re-authentication
# failure touches BENCH_PULL_STOP_FILE. rc = gcloud's.
_bench_bucket_gcloud() {
    local errf="$1" rc=0 fault
    shift
    gcloud "$@" < /dev/null 2> "${errf}" || rc=$?
    cat -- "${errf}" >&2
    [ "${rc}" -ne 0 ] || return 0
    fault="$(tn_iap_fault_kind "${rc}" "${errf}")" || fault=other
    if [ "${fault}" = reauth ] && [ -n "${BENCH_PULL_STOP_FILE:-}" ]; then touch -- "${BENCH_PULL_STOP_FILE}" 2>/dev/null || true; fi
    printf '%s\n' "${fault}"
    return "${rc}"
}

# bench_pull_node_logs_bucket <dest-dir> <bucket> — bench_pull_node_logs (bench-lib.sh) for every
# node in INSTANCE_NAMES/ZONES, through the run bucket <bucket> (see "the bucket transfer" above).
# First a preflight, reads only and in a dry run too: the bucket must exist (bench_bucket_names) and
# every node's service account must be able to write to it (bench_bucket_write_scope of its
# describe); a dry run reports a failure on a ✗ line, a real run stops there, rc 1, nothing sent.
# Then: (1) the sessions, BENCH_PULL_JOBS nodes at a time (_bench_bucket_send_node); (2) one
# `gcloud storage cp -r gs://<bucket>/logs/* <work>/objects/` into a dot-named work directory in
# <dest-dir> (same file system: the landing is a rename); (3) the landing and the marker of every
# node whose session ran (_bench_bucket_land_node), BENCH_PULL_JOBS at a time; then the objects are
# removed from the bucket (`gcloud storage rm gs://<bucket>/logs/** --project`; a failure is a
# warning: the teardown's bucket backup would then copy them into results/<run>/bucket/ as well).
# gcloud needing re-authentication anywhere touches BENCH_PULL_STOP_FILE (a temp file of this call
# when unset) and stops the transfer, as bench_pull_node_logs does. Non-zero, naming the nodes, if
# any node failed. Creates <dest-dir> but never its parent; the work directory is removed on every
# path. Dry run: the preflight, one line per session and per local call, nothing sent or created.
bench_pull_node_logs_bucket() {
    local dest="${1:-}" bucket="${2:-}" jobs="${BENCH_PULL_JOBS:-4}" i inst scopes json bad=0 work="" stopd="" errf
    local t0 bytes=0 files=0 tag o v failed="" pids=() names=() sent=() started=0 skipped=0 fault
    local BENCH_PULL_STOP_FILE="${BENCH_PULL_STOP_FILE:-}"
    if [ -z "${dest}" ] || [ -z "${bucket}" ]; then echo "❌ bench_pull_node_logs_bucket <dest-dir> <bucket>" >&2; return 1; fi
    case "${bucket}" in *[!a-z0-9._-]*) echo "❌ bench_pull_node_logs_bucket: bad bucket name '${bucket}'" >&2; return 1 ;; esac
    case "${jobs}" in ''|*[!0-9]*|0*) echo "⚠ BENCH_PULL_JOBS='${jobs}' is not a positive integer — using 4" >&2; jobs=4 ;; esac
    echo "LOG_TRANSFER mode=bucket nodes=${#INSTANCE_NAMES[@]}"
    json="$(bench_bucket_names < /dev/null)" || json=""
    if _bench_in_lines "${bucket}" "${json}"; then
        echo "    ✓ the run bucket gs://${bucket} exists"
    else
        echo "    ✗ the run bucket gs://${bucket} does not exist (or the bucket list failed)" >&2; bad=$((bad + 1))
    fi
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        json="$(bench_instance_json "${inst}" "${ZONES[$i]}" < /dev/null)" || json=""
        if ! scopes="$(bench_bucket_write_scope "${json}")"; then
            echo "    ✗ ${inst}: the access scopes of its service account (${scopes}) allow no GCS write" >&2; bad=$((bad + 1))
        fi
    done
    [ "${bad}" -gt 0 ] || echo "    ✓ every node's service account can write to the bucket"
    if [ "${bad}" -gt 0 ]; then
        if [ "${BENCH_APPLY}" = "1" ]; then
            echo "❌ BENCH_LOG_TRANSFER=bucket cannot run here (✗ above) — nothing was sent; run with BENCH_LOG_TRANSFER=iap" >&2
            return 1
        fi
        echo "    ✗ with --yes the bucket transfer stops here, before any session: run with BENCH_LOG_TRANSFER=iap"
    fi
    if [ "${BENCH_APPLY}" = "1" ]; then
        if [ ! -d "${dest}" ] && ! mkdir "${dest}"; then
            echo "❌ bench_pull_node_logs_bucket: could not create ${dest} (its parent must exist already)" >&2
            return 1
        fi
        if [ -z "${BENCH_PULL_STOP_FILE}" ]; then
            stopd="$(mktemp -d "${TMPDIR:-/tmp}/bench-pull-stop.XXXXXX")" || { echo "❌ bench_pull_node_logs_bucket: no temp directory" >&2; return 1; }
            BENCH_PULL_STOP_FILE="${stopd}/stop"
        fi
        if ! work="$(mktemp -d "${dest}/.bucket-pull.XXXXXX")"; then
            _bench_bucket_rm_dir "${stopd}"
            echo "❌ bench_pull_node_logs_bucket: no work directory in ${dest}" >&2
            return 1
        fi
    fi
    t0="$(date -u +%s)"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        printf '    + tn_iap_ssh_stdin %q %q <<< "$(bench_bucket_logs_script %q %q)"   # LOGSPAN -> %q; each log gzipped on the node -> %s\n' \
            "${inst}" "${ZONES[$i]}" "${inst}" "${bucket}" "${dest}/${inst}.logspan" "gs://${bucket}/logs/${inst}/"
        [ "${BENCH_APPLY}" = "1" ] || continue
        if [ "${#pids[@]}" -ge "${jobs}" ]; then
            if wait "${pids[0]}"; then sent+=("${names[0]}"); else failed="${failed} ${names[0]}"; fi
            pids=("${pids[@]:1}"); names=("${names[@]:1}")
        fi
        if [ -e "${BENCH_PULL_STOP_FILE}" ]; then skipped=$((skipped + 1)); continue; fi
        _bench_bucket_send_node "${inst}" "${ZONES[$i]}" "${dest}" "${work}" "${bucket}" &
        pids+=("$!"); names+=("${inst}"); started=$((started + 1))
    done
    printf '    + gcloud storage cp -r %q %q\n' "gs://${bucket}/logs/*" "${work:-${dest}/.bucket-pull.<tmp>}/objects/"
    printf '    + gcloud storage rm %q --project=%q   # once landed, so the bucket backup does not copy them again\n' \
        "gs://${bucket}/logs/**" "${PROJECT_ID}"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    for i in "${!pids[@]}"; do
        if wait "${pids[$i]}"; then sent+=("${names[$i]}"); else failed="${failed} ${names[$i]}"; fi
    done
    for inst in "${sent[@]+"${sent[@]}"}"; do
        while read -r tag o v; do
            [ "${tag}" = PULLED ] || continue
            case "${v#bytes=}" in ''|*[!0-9]*) ;; *) files=$((files + 1)); bytes=$((bytes + ${v#bytes=})) ;; esac
        done < "${work}/${inst}.session"
    done
    errf="${work}/gcloud.err"
    if [ "${files}" -gt 0 ] && [ ! -e "${BENCH_PULL_STOP_FILE}" ]; then
        echo "    ↓ gs://${bucket}/logs/ -> ${work}/objects/ (${files} log(s), ${bytes} bytes from ${#sent[@]} node(s))"
        mkdir -p -- "${work}/objects"
        if ! fault="$(_bench_bucket_gcloud "${errf}" storage cp -r "gs://${bucket}/logs/*" "${work}/objects/")"; then
            echo "      ✗ the download from gs://${bucket}/logs/ failed (${fault:-other}) — a node whose logs are not all here fails below" >&2
        fi
    fi
    if [ ! -e "${BENCH_PULL_STOP_FILE}" ]; then
        pids=(); names=()
        for inst in "${sent[@]+"${sent[@]}"}"; do
            if [ "${#pids[@]}" -ge "${jobs}" ]; then
                wait "${pids[0]}" || failed="${failed} ${names[0]}"
                pids=("${pids[@]:1}"); names=("${names[@]:1}")
            fi
            for i in "${!INSTANCE_NAMES[@]}"; do [ "${INSTANCE_NAMES[$i]}" = "${inst}" ] && break; done
            _bench_bucket_land_node "${inst}" "${ZONES[$i]}" "${dest}" "${work}" &
            pids+=("$!"); names+=("${inst}")
        done
        for i in "${!pids[@]}"; do wait "${pids[$i]}" || failed="${failed} ${names[$i]}"; done
    else
        for inst in "${sent[@]+"${sent[@]}"}"; do failed="${failed} ${inst}"; done
    fi
    # Every session started may have sent something, a failed one included.
    if [ "${started}" -gt 0 ] && [ -e "${BENCH_PULL_STOP_FILE}" ]; then
        echo "⚠ the objects under gs://${bucket}/logs/ are left (gcloud needs re-authentication): a re-run with BENCH_LOG_TRANSFER=bucket removes them; until then the teardown's bucket backup would copy them into results/${BENCH_RUN_ID:-<run>}/bucket/ as well" >&2
    elif [ "${started}" -gt 0 ] && ! fault="$(_bench_bucket_gcloud "${errf}" storage rm "gs://${bucket}/logs/**" --project="${PROJECT_ID}")" \
        && ! grep -q 'matched no objects' "${errf}"; then
        echo "⚠ the objects under gs://${bucket}/logs/ were not removed (${fault:-other}): the teardown's bucket backup copies them into results/${BENCH_RUN_ID:-<run>}/bucket/ as well" >&2
    fi
    _bench_bucket_rm_dir "${work}"
    echo "LOG_TRANSFER_DONE mode=bucket bytes=${bytes} secs=$(( $(date -u +%s) - t0 ))"
    if [ -e "${BENCH_PULL_STOP_FILE}" ]; then
        _bench_bucket_rm_dir "${stopd}"
        echo "❌ node logs: gcloud needs re-authentication; ${skipped} node(s) not attempted$([ -z "${failed}" ] || echo "; not pulled from:${failed}") — run: gcloud auth login, then run this again" >&2
        return 1
    fi
    _bench_bucket_rm_dir "${stopd}"
    if [ -n "${failed}" ]; then echo "❌ node logs not pulled from:${failed}" >&2; return 1; fi
    echo "    ✓ logs of ${#INSTANCE_NAMES[@]} nodes in ${dest}"
}

# _bench_bucket_rm_dir <dir> — remove a work or stop directory this transfer made with mktemp -d
# (a name with ".bucket-pull." or "bench-pull-stop." in it); anything else, or nothing, is left.
_bench_bucket_rm_dir() {
    case "${1:-}" in
        */.bucket-pull.?*|*/bench-pull-stop.?*) [ ! -d "$1" ] || rm -rf -- "$1" ;;
    esac
    return 0
}

# --- the log prefilter (D44) --------------------------------------------------------------------
# Three teardown readers look at a handful of line shapes in the pulled node logs: the certification
# record and cert-rate (tools/cert-rate.py's events), and the node startup provenance
# (report/provenance.py's _CANDIDATE_MARKERS). Bench 5 decompressed its 2 GB of logs once for each,
# one Python process at a time (D44: about 23 of the teardown's 35 min). One pass now keeps the lines
# that carry a shape, one job per log, and every reader reads that small copy instead.
#
# bench_logs_prefilter <logs dir> <out dir> [<shapes file>] — for every regular *.log.gz and *.log
# file in <logs dir> (dot-named files skipped), <out dir>/logs/<same name> holds the lines that
# contain any line of <shapes file> (default ${BENCH_DIR}/tools/log-shapes.txt: fixed strings, one
# per line, matched as bytes; lines starting with "#" are comments, kept out of the patterns in
# <out dir>/.shapes.txt): gzip -dcf <log> | LC_ALL=C grep -F -f <shapes>, then gzip -1 -n again
# when the name ends in .gz, so each reader opens the copy exactly as it opens the original and the
# file names, and so the instance and node grouping, stay the same. BENCH_PREFILTER_JOBS logs at a
# time (1-64, default 8). A log whose copy is newer than it is not read again (a second call after
# new snapshots reads only those) unless the shapes changed since the copies were made (then every log
# is read again); a copy whose log is gone is removed. One line per log read, then
#   PREFILTER logs=<n> read=<n> reused=<n> in_bytes=<b> out_bytes=<b> secs=<s> failed=<n>
# rc 0 when every log was read whole and every copy written; 1 otherwise (its copy is removed: a cut
# gzip, a grep error, a full disk): the caller then reads the full logs, as before. The one way a copy
# reads differently: a log whose last line has no newline gets one. Dry run (BENCH_APPLY != 1): says
# what it would do and writes nothing.
bench_logs_prefilter() {
    local logs="${1:-}" out="${2:-}" shapes="${3:-${BENCH_DIR:-.}/tools/log-shapes.txt}"
    local jobs="${BENCH_PREFILTER_JOBS:-8}" f name n=0 todo=0 reused=0 t0 res line failed=0 inb=0 outb=0
    local pats same=1
    local -a work
    if [ -z "${logs}" ] || [ -z "${out}" ]; then
        echo "❌ bench_logs_prefilter <logs dir> <out dir> [<shapes file>]: missing argument" >&2
        return 1
    fi
    case "${jobs}" in [1-9]|[1-5][0-9]|6[0-4]) ;; *) echo "⚠ BENCH_PREFILTER_JOBS='${jobs}' is not 1-64 — using 8" >&2; jobs=8 ;; esac
    if [ ! -d "${logs}" ]; then echo "    ✗ prefilter: ${logs} is not a directory" >&2; return 1; fi
    # An empty line in a grep -f file matches every line: the shapes must be non-empty lines, and
    # at least one must not be a comment.
    if [ ! -s "${shapes}" ] || grep -q '^$' "${shapes}" || ! grep -qv '^#' "${shapes}"; then
        echo "    ✗ prefilter: ${shapes} is missing, empty, all comments or has an empty line" >&2
        return 1
    fi
    pats="$(grep -v '^#' "${shapes}")"
    # Copies made with other shapes are not reused.
    [ -f "${out}/.shapes.txt" ] && [ "$(cat "${out}/.shapes.txt")" = "${pats}" ] || same=0
    work=()
    for f in "${logs}"/*.log.gz "${logs}"/*.log; do
        [ -f "${f}" ] || continue
        n=$((n + 1))
        if [ "${same}" = "1" ] && [ -e "${out}/logs/${f##*/}" ] && [ "${out}/logs/${f##*/}" -nt "${f}" ]; then
            reused=$((reused + 1))
        else
            work+=("${f}")
        fi
    done
    todo="${#work[@]}"
    if [ "${BENCH_APPLY:-0}" != "1" ]; then
        echo "    + prefilter ${n} log(s) of ${logs} -> ${out}/logs/ (${jobs} at a time): gzip -dcf <log> | LC_ALL=C grep -F -f <the non-comment lines of ${shapes}> | gzip -1 -n"
        echo "      (dry run — not executed)"
        return 0
    fi
    mkdir -p "${out}/logs" || { echo "    ✗ prefilter: could not create ${out}/logs" >&2; return 1; }
    # The patterns the jobs read; they become .shapes.txt (what the copies were made with) once the jobs
    # are done, so a pass cut short leaves copies the next pass does not trust.
    [ "${same}" = "1" ] || rm -f -- "${out}/.shapes.txt"
    printf '%s\n' "${pats}" > "${out}/.shapes.txt.new" || { echo "    ✗ prefilter: could not write ${out}/.shapes.txt.new" >&2; return 1; }
    # Temp files of an interrupted call, and copies whose log is gone.
    rm -f -- "${out}/logs"/.*.prefilter.?????? 2>/dev/null || true
    for f in "${out}/logs"/*; do
        [ -f "${f}" ] || continue
        [ -f "${logs}/${f##*/}" ] || rm -f -- "${f}"
    done
    t0="$(date -u +%s)"
    res=""
    # One bash per log: $1 the out dir, $2 the shapes, $3 the log. It prints
    # "PREFILTER_FILE <name> rc=<0|1> in=<bytes> out=<bytes>"; a copy that is not whole is removed.
    # shellcheck disable=SC2016  # expanded by the job's own bash
    [ "${todo}" -eq 0 ] || res="$(printf '%s\0' "${work[@]}" | LC_ALL=C xargs -0 -n 1 -P "${jobs}" bash -c '
        src="$3"; name="${src##*/}"; dst="$1/logs/${name}"
        tmp="$(mktemp "$1/logs/.${name}.prefilter.XXXXXX")" || { echo "PREFILTER_FILE ${name} rc=1 in=0 out=0"; exit 0; }
        case "${name}" in
            *.gz) gzip -dcf -- "${src}" | LC_ALL=C grep -F -f "$2" | gzip -1 -n > "${tmp}"; s=("${PIPESTATUS[@]}") ;;
            *) gzip -dcf -- "${src}" | LC_ALL=C grep -F -f "$2" > "${tmp}"; s=("${PIPESTATUS[@]}" 0) ;;
        esac
        rc=0
        [ "${s[0]}" -eq 0 ] && [ "${s[1]}" -le 1 ] && [ "${s[2]}" -eq 0 ] && mv -f -- "${tmp}" "${dst}" || rc=1
        [ "${rc}" -eq 0 ] || rm -f -- "${tmp}" "${dst}"
        i="$(wc -c < "${src}" | tr -d " ")"; o=0; [ ! -f "${dst}" ] || o="$(wc -c < "${dst}" | tr -d " ")"
        echo "PREFILTER_FILE ${name} rc=${rc} in=${i:-0} out=${o:-0}"
    ' _ "${out}" "${out}/.shapes.txt.new")" || true
    mv -f -- "${out}/.shapes.txt.new" "${out}/.shapes.txt" || failed=$((failed + 1))
    while IFS= read -r line; do
        case "${line}" in
            "PREFILTER_FILE "*" rc=0 "*)
                echo "      ${line#PREFILTER_FILE }" ;;
            "PREFILTER_FILE "*)
                failed=$((failed + 1)); echo "      ✗ ${line#PREFILTER_FILE } (not whole: its copy is not kept)" >&2 ;;
            *) continue ;;
        esac
        f="${line##* in=}"; inb=$((inb + ${f%% *}))
        outb=$((outb + ${line##* out=}))
    done <<< "${res}"
    # A job that printed no line (killed) counts as failed too.
    f="$(printf '%s\n' "${res}" | grep -c '^PREFILTER_FILE ')" || f=0
    [ "${f}" -ge "${todo}" ] || failed=$((failed + todo - f))
    echo "    PREFILTER logs=${n} read=${todo} reused=${reused} in_bytes=${inb} out_bytes=${outb} secs=$(( $(date -u +%s) - t0 )) failed=${failed}"
    [ "${failed}" -eq 0 ]
}

# --- persist sampler files (BENCH_PERSIST_SAMPLER=1) ----------------------------------------------
# The persist sampler (node-persist-sampler.sh) writes <host>.persist.csv and <host>.folios.txt beside
# the node sampler's files on each node; results/<run>/persist/ keeps them as <inst>.csv and
# <inst>.folios.txt (arms/MANIFEST-FIELDS.md "Persist files"). BENCH_PERSIST_REMOTE_DIR is that
# directory on the node (default /var/lib/bench-sampler, the node sampler's).
#
# bench_persist_script — the remote script (`# bench-pull: persist`, for `sudo bash -s`): a tar of
# persist.csv and folios.txt, each only when the node has it non-empty (an empty tar otherwise).
bench_persist_script() {
    printf '%s\n' "# bench-pull: persist" "set -e -o pipefail" \
        "d=$(printf '%q' "${BENCH_PERSIST_REMOTE_DIR:-/var/lib/bench-sampler}"); h=\$(hostname -s); t=\$(mktemp -d)" \
        "trap 'rm -rf \"\$t\"' EXIT" \
        "for k in persist.csv folios.txt; do [ ! -s \"\$d/\$h.\$k\" ] || cp \"\$d/\$h.\$k\" \"\$t/\$k\"; done" \
        "tar -cf - -C \"\$t\" ."
}

# bench_pull_persist_files <inst> <zone> <results dir> — one session (bench_pull_stream, tar) that
# lands <results dir>/persist/<inst>.csv and <inst>.folios.txt, each replaced only by a non-empty
# copy. rc 0 landed (or the node has neither file: a line says so); 1 not pulled (a line on stderr
# says why). Never deletes a local copy. Dry run: one plan line.
bench_pull_persist_files() {
    local inst="${1:-}" zone="${2:-}" dest="${3:-}" tar rc=0 k m got=""
    if [ -z "${inst}" ] || [ -z "${zone}" ] || [ -z "${dest}" ]; then
        echo "❌ bench_pull_persist_files <inst> <zone> <results dir>: missing argument" >&2
        return 1
    fi
    if [ "${BENCH_APPLY:-0}" != "1" ]; then
        echo "    + persist files: ${inst} ${BENCH_PERSIST_REMOTE_DIR:-/var/lib/bench-sampler}/<host>.{persist.csv,folios.txt} -> ${dest}/persist/${inst}.{csv,folios.txt}"
        return 0
    fi
    mkdir -p "${dest}/persist" || { echo "      ✗ ${inst}: could not create ${dest}/persist" >&2; return 1; }
    tar="$(mktemp "${dest}/persist/.${inst}.persist.XXXXXX")" || { echo "      ✗ ${inst}: no temp file in ${dest}/persist" >&2; return 1; }
    bench_pull_stream "${inst}" "${zone}" tar "${tar}" stdin "$(bench_persist_script)" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        rm -f -- "${tar}"
        echo "      ✗ ${inst}: persist files not pulled (bench_pull_stream rc ${rc})" >&2
        return 1
    fi
    for k in csv:persist.csv folios.txt:folios.txt; do
        m="${k#*:}"; k="${k%%:*}"
        if tar -xOf "${tar}" "./${m}" > "${dest}/persist/.${inst}.${k}.tmp" 2>/dev/null && [ -s "${dest}/persist/.${inst}.${k}.tmp" ]; then
            mv -f -- "${dest}/persist/.${inst}.${k}.tmp" "${dest}/persist/${inst}.${k}" && got="${got} ${inst}.${k}"
        fi
        rm -f -- "${dest}/persist/.${inst}.${k}.tmp"
    done
    rm -f -- "${tar}"
    if [ -n "${got}" ]; then echo "    ✓ persist files:${got}"; else echo "    - ${inst}: no persist sampler file on the node"; fi
}
