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
# "# bench-pull: rotated".
# Files: <dest>/<inst>.logspan, <dest>/<inst>-unit-<stream>.rotated-<N>.log.gz (name taken:
# <dest>/<inst>-unit-<stream>-<UTC stamp>.rotated-<N>.log.gz).
# Knobs: BENCH_IAP_RETRIES (attempts per stream, default 3), BENCH_PULL_STOP_FILE (touched when
# gcloud needs re-authentication; while it exists no pull starts).

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
exit 0
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
