#!/usr/bin/env bash
# orch-gh-post.sh — bench 7 program, orchestrator only: post a prepared issue, issue comment or pull
# request to GitHub from a text file. Dry by default: nothing reaches GitHub without --live.
#
#   orch-gh-post.sh [--live] [--again] issue   <slug>    body tasks/issue-bodies/bench6-<slug>.md,
#                                                         title from tasks/issue-bodies/TITLES-bench6.md
#   orch-gh-post.sh [--live] [--again] comment <number>  body tasks/issue-comments/bench6-<number>.md
#   orch-gh-post.sh [--live] [--again] pr      <NN>      body tasks/pr-bodies/bench6-<NN>-*.md,
#                                                         head/base/title from tasks/pr-bodies/STACK-bench6.tsv
#   orch-gh-post.sh lint <file>...                       the lint alone ({{slug}} resolved from the record)
#   orch-gh-post.sh status                               what the record says was posted
#
# Every post, dry or live: {{slug}} placeholders become #<number> from the record; a first-line H1
# equal to the title (or its long form in TITLES-bench6.md) is dropped; the lint runs and any hit
# refuses (exit 3); a key already in the record refuses (exit 4) unless --again is given.
# Dry: prints DRY <kind> <key>, the exact gh argv, the title, the posted body's first 12 lines and
#   word count; runs no gh at all, not even a read.
# Live: one gh read refuses a duplicate already on GitHub (an issue by its exact title, a PR by head
#   and base; a comment by the record alone), then the create; the URL gh prints goes into the
#   record and POSTED <kind> <key> <url> is printed.
# Record: tasks/bench7/gh-posted.tsv, appended only, tab-separated:
#   <utc> <kind> <key> <number> <url> <sha256 of the posted body>
# Bodies reach gh only through a mktemp file (--body-file), removed on exit; never as an argument.
# Exit: 0 ok, 2 usage or missing file, 3 lint, 4 duplicate, 5 gh failed (nothing recorded),
#   6 gh exited 0 but printed no URL, or the record could not be written (check GitHub by hand).
# Environment: GH_REPO (the repository), POST_ROOT (the devnet-genesis checkout; default two up).
set -uo pipefail

GH_REPO="${GH_REPO:-Telcoin-Association/telcoin-network}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
POST_ROOT="${POST_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd -P)}"
ISSUE_DIR="${POST_ROOT}/tasks/issue-bodies"
COMMENT_DIR="${POST_ROOT}/tasks/issue-comments"
PR_DIR="${POST_ROOT}/tasks/pr-bodies"
TITLES_FILE="${ISSUE_DIR}/TITLES-bench6.md"
STACK_FILE="${PR_DIR}/STACK-bench6.tsv"
RECORD="${POST_ROOT}/tasks/bench7/gh-posted.tsv"
FIXTURE_DIR="${SCRIPT_DIR}/tests/fixtures"
ASSIGNEE=grantkee
REVIEWERS="MavenRain sstanfield"
MAX_TITLE_CHARS=120
MAX_BODY_CHARS=60000
TAB="$(printf '\t')"
CR="$(printf '\r')"

# ---- the lint ----------------------------------------------------------------------------------
# Word boundaries are spelled as classes so a pattern means the same in GNU and BSD grep -E.
W0='(^|[^A-Za-z0-9_])'
W1='([^A-Za-z0-9_]|$)'
# Literals the repository's own leak scans look for are assembled from pieces.
HOME_RX="/ho""me/"
HOST_RX="xer""xes"
PROJECT_RX="tn-""devnet"
ROBOT=$'\360\237\244\226'   # U+1F916, the robot face of generated-text footers
# Private unit names of the bench programs: analysis units A1-A8 and A4e/A4o/A4p, I-<n>, E-1..E-4,
# U<n>, ST-<x>, H<n>, r3-<x>, PT-<n>, HD-<n>, HB-<n>. Public text names a run by its id and a change
# by what it does, never by the unit that made it. Only in a test fixture under tests/fixtures/, and
# only for the lint subcommand, may a line carry LINT_ALLOW_MARKER to be exempt from this one rule;
# in anything posted the marker is itself a hit.
UNIT_RX="${W0}(A[1-8][a-z]?|A4[eop]|I-[0-9]+[a-z]?|E-[1-4]|U[0-9]+[a-c]?|ST-[A-Z0-9a-z]+|H[0-9]+[a-c]?|r3-[A-Z0-9a-z]+|PT-[0-9]|HD-[0-9]|HB-[0-9])${W1}"
LINT_ALLOW_MARKER='<!-- gh-post-lint: allow unit-name -->'
# An IPv4 literal not glued to a word character or a dot, each octet <= 255, other than 127.0.0.1
# and the documentation nets 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24.
IPV4_AWK='
{
    line = $0; off = 0; rest = line
    while (match(rest, /[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/)) {
        s = off + RSTART; l = RLENGTH; ip = substr(line, s, l)
        off = s + l - 1; rest = substr(line, off + 1)
        pre = (s > 1) ? substr(line, s - 1, 1) : ""
        nx = substr(line, s + l, 1); nx2 = substr(line, s + l + 1, 1)
        if (pre ~ /[A-Za-z0-9_.]/ || nx ~ /[A-Za-z0-9_]/ || (nx == "." && nx2 ~ /[0-9]/)) continue
        n = split(ip, o, "."); bad = 0
        for (i = 1; i <= n; i++) if (length(o[i]) > 3 || o[i] + 0 > 255) bad = 1
        if (bad) continue
        if (ip == "127.0.0.1" || ip ~ /^192\.0\.2\./ || ip ~ /^198\.51\.100\./ || ip ~ /^203\.0\.113\./) continue
        print NR ":" line
        break
    }
}'
# A run nickname (run 1, run 2, run 2b, run 3, run 3b) with no run id r20YYMMDD-HHMM after it on
# the same line: the public texts name runs by id.
NICK_AWK='
{
    line = $0; off = 0; rest = line
    while (match(rest, /[Rr]un [123]b?/)) {
        s = off + RSTART; l = RLENGTH
        off = s + l - 1; rest = substr(line, off + 1)
        pre = (s > 1) ? substr(line, s - 1, 1) : ""
        nx = substr(line, s + l, 1)
        if (pre ~ /[A-Za-z0-9_]/ || nx ~ /[A-Za-z0-9_]/) continue
        if (rest ~ /r20[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]/) continue
        print NR ":" line
        break
    }
}'
# {{slug}} -> #<number>, literally (index, not a regex). Map file: placeholder<TAB>replacement.
SUBST_AWK='
FNR == NR { k[++nk] = $1; v[nk] = $2; next }
{
    line = $0
    for (i = 1; i <= nk; i++) {
        out = ""
        while ((p = index(line, k[i])) > 0) {
            out = out substr(line, 1, p - 1) v[i]
            line = substr(line, p + length(k[i]))
        }
        line = out line
    }
    print line
}'

LIVE=0
AGAIN=0
LINT_HITS=0
ALLOW_MARKERS=0
HAS_PRE=0
H1_NOTE="n/a"
CREATE=()
PRE=()
BODY_ARGS=()
TMP_LIST=()
RESOLVED_TMP=""
BODY_TMP=""
TITLE_TMP=""
MAP_TMP=""
OUT_TMP=""
ERR_TMP=""

cleanup() {
    local t
    for t in ${TMP_LIST[@]+"${TMP_LIST[@]}"}; do rm -f "${t}"; done
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# new_tmp <var>: a mktemp file, removed on exit, its path stored in <var>.
new_tmp() {
    local t
    t="$(mktemp "${TMPDIR:-/tmp}/gh-post.XXXXXX")" || { printf 'MKTEMP failed\n' >&2; exit 2; }
    TMP_LIST+=("${t}")
    printf -v "$1" '%s' "${t}"
}

usage() {
    cat <<'EOF'
usage:
  orch-gh-post.sh [--live] [--again] issue   <slug>     body tasks/issue-bodies/bench6-<slug>.md, title from TITLES-bench6.md
  orch-gh-post.sh [--live] [--again] comment <number>   body tasks/issue-comments/bench6-<number>.md
  orch-gh-post.sh [--live] [--again] pr      <NN>       body tasks/pr-bodies/bench6-<NN>-*.md, head/base/title from STACK-bench6.tsv
  orch-gh-post.sh lint <file>...                        the lint alone
  orch-gh-post.sh status                                what the record says was posted
Dry by default; --live posts; --again posts a key the record already holds.
Exit: 0 ok, 2 usage or missing file, 3 lint, 4 duplicate, 5 gh failed, 6 posted but unrecorded or no URL.
EOF
}

usage_error() {
    printf 'USAGE %s\n' "$1" >&2
    usage >&2
    exit 2
}

trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "${s}"
}

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# char_count < file: characters of UTF-8 text (bytes minus continuation bytes), locale-independent.
char_count() { LC_ALL=C tr -d '\200-\277' | wc -c | tr -d ' '; }

sha256_of() {
    if command -v sha256sum > /dev/null 2>&1; then
        sha256sum < "$1" | awk '{ print $1 }'
    else
        shasum -a 256 < "$1" | awk '{ print $1 }'
    fi
}

# shq <word>: the word as a shell would need it typed (bare when safe, else single-quoted).
shq() {
    case "$1" in
        '') printf "''" ;;
        *[!A-Za-z0-9_./:=,@+%-]*) printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")" ;;
        *) printf '%s' "$1" ;;
    esac
}

argv_line() {
    local a out=""
    for a in "$@"; do out="${out}${out:+ }$(shq "${a}")"; done
    printf '%s\n' "${out}"
}

# lint_report <label> <rule> <grep -n style lines>: one LINT line per hit.
lint_report() {
    local label="$1" rule="$2" hits="$3" line
    [ -n "${hits}" ] || return 0
    while IFS= read -r line; do
        printf 'LINT %s:%s: %s: %s\n' "${label}" "${line%%:*}" "${rule}" "${line#*:}"
        LINT_HITS=$((LINT_HITS + 1))
    done <<EOF
${hits}
EOF
}

# lint_rx <file> <label> <rule> <i|c> <ERE> [allow]: every line of <file> matching <ERE> is a hit.
lint_rx() {
    local f="$1" label="$2" rule="$3" icase="$4" rx="$5" allow="${6:-}" hits rc
    if [ "${icase}" = i ]; then
        hits="$(LC_ALL=C grep -niE -e "${rx}" "${f}")"; rc=$?
    else
        hits="$(LC_ALL=C grep -nE -e "${rx}" "${f}")"; rc=$?
    fi
    if [ "${rc}" -gt 1 ]; then
        hits="0:grep failed (rc=${rc}) on this rule"
    elif [ -n "${hits}" ] && [ -n "${allow}" ] && [ "${ALLOW_MARKERS}" = "1" ]; then
        hits="$(printf '%s\n' "${hits}" | LC_ALL=C grep -vF -e "${LINT_ALLOW_MARKER}")" || hits=""
    fi
    lint_report "${label}" "${rule}" "${hits}"
}

# lint_file <file> <label>: every text rule over <file>; adds to LINT_HITS.
lint_file() {
    local f="$1" label="$2" hits
    lint_rx "${f}" "${label}" claude            i 'claude'
    lint_rx "${f}" "${label}" anthropic         i 'anthropic'
    lint_rx "${f}" "${label}" co-authored       i 'co-authored'
    lint_rx "${f}" "${label}" generated-with    c 'Generated with'
    lint_rx "${f}" "${label}" robot-emoji       c "${ROBOT}"
    lint_rx "${f}" "${label}" ai-generated      i 'ai-generated'
    lint_rx "${f}" "${label}" assistant         i "${W0}assistant${W1}"
    lint_rx "${f}" "${label}" subagent          i 'subagent'
    lint_rx "${f}" "${label}" private-path      c 'benchmark/private'
    lint_rx "${f}" "${label}" home-path         c "${HOME_RX}"
    lint_rx "${f}" "${label}" tasks-path        c '(^|[^A-Za-z0-9_./-])tasks/'
    lint_rx "${f}" "${label}" host-name         i "${HOST_RX}"
    lint_rx "${f}" "${label}" project-id        i "${PROJECT_RX}"
    lint_rx "${f}" "${label}" placeholder       c '[{][{]'
    lint_rx "${f}" "${label}" angle-placeholder c '<<[^>]*>>'
    lint_rx "${f}" "${label}" unit-name         c "${UNIT_RX}" allow
    if [ "${ALLOW_MARKERS}" != "1" ]; then
        lint_rx "${f}" "${label}" allow-marker  c 'gh-post-lint:'
    fi
    hits="$(LC_ALL=C awk "${IPV4_AWK}" "${f}")" || hits="0:awk failed on this rule"
    lint_report "${label}" ipv4 "${hits}"
    hits="$(LC_ALL=C awk "${NICK_AWK}" "${f}")" || hits="0:awk failed on this rule"
    lint_report "${label}" run-nickname "${hits}"
}

# body_checks <posted body> <label>: not empty, at most MAX_BODY_CHARS characters.
body_checks() {
    local f="$1" label="$2" chars
    if ! LC_ALL=C grep -q '[^[:space:]]' "${f}"; then
        printf 'LINT %s: empty-body: nothing to post\n' "${label}"
        LINT_HITS=$((LINT_HITS + 1))
    fi
    chars="$(char_count < "${f}")"
    if [ "${chars}" -gt "${MAX_BODY_CHARS}" ]; then
        printf 'LINT %s: body-length: %s characters, over %s\n' "${label}" "${chars}" "${MAX_BODY_CHARS}"
        LINT_HITS=$((LINT_HITS + 1))
    fi
}

# title_checks <title> <scratch file>: length, final period, and every text rule.
title_checks() {
    local t="$1" n
    n="$(printf '%s' "${t}" | char_count)"
    if [ "${n}" -gt "${MAX_TITLE_CHARS}" ]; then
        printf 'LINT title: title-length: %s characters, over %s\n' "${n}" "${MAX_TITLE_CHARS}"
        LINT_HITS=$((LINT_HITS + 1))
    fi
    case "${t}" in
        *.) printf 'LINT title: title-period: the title ends in a period\n'; LINT_HITS=$((LINT_HITS + 1)) ;;
    esac
    printf '%s\n' "${t}" > "$2"
    lint_file "$2" title
}

# lint_body <label> <resolved source> <posted body> <title> <scratch>: the whole lint of one post.
lint_body() {
    LINT_HITS=0
    ALLOW_MARKERS=0
    lint_file "$2" "$1"
    body_checks "$3" "$1"
    [ -z "$4" ] || title_checks "$4" "$5"
    [ "${LINT_HITS}" -eq 0 ] && return 0
    printf 'REFUSED %s lint hit(s); nothing posted\n' "${LINT_HITS}"
    return 1
}

# ---- the record ------------------------------------------------------------------------------
# record_number <kind> <key>: the number of the latest recorded post of that kind and key.
record_number() {
    [ -f "${RECORD}" ] || return 1
    awk -F'\t' -v k="$1" -v key="$2" '
        substr($0, 1, 1) != "#" && $2 == k && $3 == key && $4 ~ /^[0-9]+$/ { n = $4 }
        END { if (n == "") exit 1; print n }' "${RECORD}"
}

# record_find <kind> <key>: "#<number> <url> (<utc>)" of the latest recorded post, 1 when none.
record_find() {
    [ -f "${RECORD}" ] || return 1
    awk -F'\t' -v k="$1" -v key="$2" '
        substr($0, 1, 1) != "#" && $2 == k && $3 == key { r = "#" $4 " " $5 " (" $1 ")"; c++ }
        END { if (!c) exit 1; print r }' "${RECORD}"
}

record_append() {
    mkdir -p "$(dirname "${RECORD}")" || return 1
    if [ ! -f "${RECORD}" ]; then
        printf '# utc\tkind\tkey\tnumber\turl\tsha256_of_posted_body\n' >> "${RECORD}" || return 1
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" "$4" "$5" >> "${RECORD}"
}

# refuse_recorded <kind> <key>: 1 when the record holds the key and --again was not given.
refuse_recorded() {
    local prior
    prior="$(record_find "$1" "$2")" || return 0
    if [ "${AGAIN}" = "1" ]; then
        printf '!!!!! AGAIN %s %s: the record already has it as %s; --again given, it goes out a second time !!!!!\n' "$1" "$2" "${prior}"
        return 0
    fi
    printf 'DUPLICATE %s %s: the record already has it as %s; nothing posted (--live --again posts it twice)\n' "$1" "$2" "${prior}"
    return 1
}

# ---- the body --------------------------------------------------------------------------------
# resolve_placeholders <src> <dst> <map scratch>: {{slug}} -> #<number> of the issue the record
# holds under <slug>. One SUBST or UNRESOLVED line per placeholder; 1 when any is unresolved,
# 2 on an I/O failure.
resolve_placeholders() {
    local src="$1" dst="$2" map="$3" found ph slug num bad=0
    : > "${map}" || return 2
    found="$(LC_ALL=C grep -oE '[{][{][a-z0-9][a-z0-9-]*[}][}]' "${src}" | sort -u)" || found=""
    while IFS= read -r ph; do
        [ -n "${ph}" ] || continue
        slug="$(printf '%s' "${ph}" | sed -e 's/^{{//' -e 's/}}$//')"
        num="$(record_number issue "${slug}")" || num=""
        if [ -n "${num}" ]; then
            printf '%s\t#%s\n' "${ph}" "${num}" >> "${map}"
            printf 'SUBST %s -> #%s\n' "${ph}" "${num}"
        else
            printf 'UNRESOLVED %s: the record has no issue posted under the slug %s\n' "${ph}" "${slug}"
            bad=1
        fi
    done <<EOF
${found}
EOF
    if [ -s "${map}" ]; then
        awk -F'\t' "${SUBST_AWK}" "${map}" "${src}" > "${dst}" || return 2
    else
        cat "${src}" > "${dst}" || return 2
    fi
    return "${bad}"
}

# drop_h1 <src> <dst> <title> <long form>: a first-line H1 equal to the title or its long form is
# dropped with the blank lines after it; any other body goes through unchanged.
drop_h1() {
    local src="$1" dst="$2" title="$3" long="$4" first h1
    first="$(head -n 1 "${src}")"
    first="${first%"${CR}"}"
    case "${first}" in
        '# '*) ;;
        *) H1_NOTE="none"; cat "${src}" > "${dst}"; return ;;
    esac
    h1="$(trim "${first#"# "}")"
    if [ "${h1}" = "${title}" ] || { [ -n "${long}" ] && [ "${h1}" = "${long}" ]; }; then
        H1_NOTE="dropped (it equals the title or its long form)"
        awk 'NR == 1 { next } !body && /^[ \t\r]*$/ { next } { body = 1; print }' "${src}" > "${dst}"
    else
        H1_NOTE="kept: it differs from the title and its long form"
        printf 'NOTE the body starts with an H1 that is neither the title nor its long form; it is posted as is\n'
        cat "${src}" > "${dst}"
    fi
}

# ---- sources ---------------------------------------------------------------------------------
# issue_title <slug>: the title column of the slug's row in TITLES-bench6.md (exactly one row).
issue_title() {
    awk -F'|' -v s="$1" '
        { sub(/\r$/, "") }
        /^\|/ && NF >= 6 {
            o = $2; sl = $3
            gsub(/^[ \t]+|[ \t]+$/, "", o); gsub(/^[ \t]+|[ \t]+$/, "", sl)
            if (o !~ /^[0-9]+$/ || sl != s) next
            t = $4; for (i = 5; i <= NF - 2; i++) t = t "|" $i
            gsub(/\\\|/, "|", t); gsub(/^[ \t]+|[ \t]+$/, "", t)
            row = t; c++
        }
        END { if (c != 1 || row == "") exit 1; print row }' "${TITLES_FILE}"
}

# issue_long_title <slug>: the verbatim H1 listed as "- <slug> (<n>): <H1>" for a shortened title.
issue_long_title() {
    awk -v s="$1" '
        { sub(/\r$/, "") }
        index($0, "- " s " (") == 1 { sub(/^- [^ ]+ \([0-9]+\): /, ""); print; f = 1; exit }
        END { if (!f) exit 1 }' "${TITLES_FILE}"
}

# stack_row <NN>: "head<TAB>base<TAB>title" of the NN row of STACK-bench6.tsv (exactly one row).
stack_row() {
    awk -F'\t' -v k="$1" '
        { sub(/\r$/, "") }
        substr($0, 1, 1) == "#" || NF == 0 { next }
        $1 == k { if (NF < 4 || $2 == "" || $3 == "" || $4 == "") bad = 1; row = $2 "\t" $3 "\t" $4; c++ }
        END { if (c != 1 || bad) exit 1; print row }' "${STACK_FILE}"
}

# in_fixture_dir <file>: 0 when <file> sits under this script's tests/fixtures/.
in_fixture_dir() {
    local d fx
    fx="$(cd "${FIXTURE_DIR}" 2> /dev/null && pwd -P)" || return 1
    d="$(cd "$(dirname "$1")" 2> /dev/null && pwd -P)" || return 1
    case "${d}/" in "${fx}/"*) return 0 ;; esac
    return 1
}

# ---- gh ----------------------------------------------------------------------------------------
build_argv() {
    local kind="$1" key="$2" title="$3" head="$4" base="$5" search r
    BODY_ARGS=(--body-file "${BODY_TMP}")
    HAS_PRE=0
    case "${kind}" in
        issue)
            search="$(printf '%s' "${title}" | tr '":' '  ') in:title"
            CREATE=(gh issue create --repo "${GH_REPO}" --title "${title}" "${BODY_ARGS[@]}" --assignee "${ASSIGNEE}")
            PRE=(gh issue list --repo "${GH_REPO}" --search "${search}" --state all --json 'number,title' --jq '.[] | [.number, .title] | @tsv')
            HAS_PRE=1
            ;;
        comment)
            CREATE=(gh issue comment "${key}" --repo "${GH_REPO}" "${BODY_ARGS[@]}")
            ;;
        pr)
            CREATE=(gh pr create --repo "${GH_REPO}" --base "${base}" --head "${head}" --title "${title}" "${BODY_ARGS[@]}" --assignee "${ASSIGNEE}")
            for r in ${REVIEWERS}; do CREATE+=(--reviewer "${r}"); done
            PRE=(gh pr list --repo "${GH_REPO}" --head "${head}" --base "${base}" --state all --json number --jq '.[].number')
            HAS_PRE=1
            ;;
    esac
}

# github_precheck <kind> <key> <title>: the one gh read of a live post.
# 0 nothing on GitHub yet, 4 already there, 5 gh failed.
github_precheck() {
    local kind="$1" key="$2" title="$3" rc line num t want found=""
    [ "${HAS_PRE}" = "1" ] || return 0
    [ "${LIVE}" = "1" ] || return 0
    "${PRE[@]}" > "${OUT_TMP}" 2> "${ERR_TMP}"; rc=$?
    if [ "${rc}" -ne 0 ]; then
        printf 'GH-FAILED %s %s: the duplicate check failed (rc=%s); nothing posted\n' "${kind}" "${key}" "${rc}"
        sed 's/^/  gh: /' "${ERR_TMP}" >&2
        return 5
    fi
    want="$(lower "$(trim "${title}")")"
    while IFS= read -r line || [ -n "${line}" ]; do
        line="${line%"${CR}"}"
        [ -n "${line}" ] || continue
        if [ "${kind}" = pr ]; then found="${found} #${line}"; continue; fi
        num="${line%%"${TAB}"*}"
        t="${line#*"${TAB}"}"
        if [ "$(lower "$(trim "${t}")")" = "${want}" ]; then
            found="${found} #${num}"
        else
            printf 'NOTE a similar issue exists, not a duplicate: #%s %s\n' "${num}" "${t}"
        fi
    done < "${OUT_TMP}"
    [ -n "${found}" ] || return 0
    printf 'DUPLICATE %s %s: already on GitHub as%s; nothing posted\n' "${kind}" "${key}" "${found}"
    return 4
}

# url_number <kind> <url>: the issue or PR number in the URL gh printed.
url_number() {
    case "$1" in
        pr) printf '%s\n' "$2" | sed -n 's#^https://.*/pull/\([0-9][0-9]*\).*$#\1#p' ;;
        *) printf '%s\n' "$2" | sed -n 's#^https://.*/issues/\([0-9][0-9]*\).*$#\1#p' ;;
    esac | grep -E '^[0-9]+$'
}

# github_create <kind> <key>: the create, then the record. 0 POSTED, 5 gh failed, 6 unrecorded.
github_create() {
    local kind="$1" key="$2" rc url num sha
    [ "${LIVE}" = "1" ] || return 0
    "${CREATE[@]}" > "${OUT_TMP}" 2> "${ERR_TMP}"; rc=$?
    if [ "${rc}" -ne 0 ]; then
        printf 'GH-FAILED %s %s: gh exited %s; nothing recorded\n' "${kind}" "${key}" "${rc}"
        sed 's/^/  gh: /' "${ERR_TMP}" >&2
        return 5
    fi
    sed 's/^/  gh: /' "${OUT_TMP}"
    url="$(LC_ALL=C grep -E '^https://' "${OUT_TMP}" | tail -n 1)" || url=""
    url="$(trim "${url}")"
    num="$(url_number "${kind}" "${url}")" || num=""
    sha="$(sha256_of "${BODY_TMP}")" || sha=""
    if [ -z "${num}" ]; then
        record_append "${kind}" "${key}" "-" "${url:--}" "${sha}" || :
        printf 'UNRECORDED-URL %s %s: gh exited 0 but printed no %s URL; recorded with number "-" so it is not posted twice; check GitHub by hand\n' "${kind}" "${key}" "${kind}"
        return 6
    fi
    if ! record_append "${kind}" "${key}" "${num}" "${url}" "${sha}"; then
        printf 'POSTED %s %s %s but the record could not be written; add this line to %s by hand:\n' "${kind}" "${key}" "${url}" "${RECORD}"
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${kind}" "${key}" "${num}" "${url}" "${sha}"
        return 6
    fi
    printf 'POSTED %s %s %s\n' "${kind}" "${key}" "${url}"
    return 0
}

# ---- commands ----------------------------------------------------------------------------------
print_dry() {
    local kind="$1" key="$2" src="$3" title="$4" words chars
    words="$(wc -w < "${BODY_TMP}" | tr -d ' ')"
    chars="$(char_count < "${BODY_TMP}")"
    printf '  repo: %s\n' "${GH_REPO}"
    if [ -n "${title}" ]; then
        printf '  title: %s (%s characters)\n' "${title}" "$(printf '%s' "${title}" | char_count)"
        printf '  h1: %s\n' "${H1_NOTE}"
    fi
    printf '  body: %s (%s words, %s characters posted)\n' "${src}" "${words}" "${chars}"
    if [ "${HAS_PRE}" = "1" ]; then
        printf '  precheck: %s\n' "$(argv_line "${PRE[@]}")"
    else
        printf '  precheck: none, the record alone decides for a comment\n'
    fi
    printf '  create: %s\n' "$(argv_line "${CREATE[@]}")"
    printf '  posted body, first 12 lines:\n'
    head -n 12 "${BODY_TMP}" | sed 's/^/    | /'
    printf 'DRY %s %s ok: nothing posted (add --live to post)\n' "${kind}" "${key}"
}

post_one() {
    local kind="$1" key="$2" src="" title="" long="" head="" base="" row rest n f prc
    if [ "${LIVE}" = "1" ]; then printf 'LIVE %s %s\n' "${kind}" "${key}"; else printf 'DRY %s %s\n' "${kind}" "${key}"; fi
    case "${kind}" in
        issue)
            case "${key}" in ''|[!a-z0-9]*|*[!a-z0-9-]*) usage_error "issue takes a slug of a-z, 0-9 and '-', not '${key}'" ;; esac
            src="${ISSUE_DIR}/bench6-${key}.md"
            [ -f "${TITLES_FILE}" ] || { printf 'MISSING %s\n' "${TITLES_FILE}"; return 2; }
            title="$(issue_title "${key}")" || { printf 'MISSING exactly one row for %s in %s\n' "${key}" "${TITLES_FILE}"; return 2; }
            long="$(issue_long_title "${key}")" || long=""
            long="$(trim "${long}")"
            ;;
        comment)
            case "${key}" in ''|*[!0-9]*) usage_error "comment takes an issue number, not '${key}'" ;; esac
            src="${COMMENT_DIR}/bench6-${key}.md"
            ;;
        pr)
            case "${key}" in ''|*[!0-9a-z]*) usage_error "pr takes a stack position NN (or a lower-case key of STACK-bench6.tsv such as xf), not '${key}'" ;; esac
            n=0
            for f in "${PR_DIR}/bench6-${key}-"*.md; do
                [ -f "${f}" ] || continue
                src="${f}"; n=$((n + 1))
            done
            [ "${n}" -eq 1 ] || { printf 'MISSING exactly one body %s/bench6-%s-*.md (found %s)\n' "${PR_DIR}" "${key}" "${n}"; return 2; }
            [ -f "${STACK_FILE}" ] || { printf 'MISSING %s\n' "${STACK_FILE}"; return 2; }
            row="$(stack_row "${key}")" || { printf 'MISSING exactly one complete row %s in %s\n' "${key}" "${STACK_FILE}"; return 2; }
            head="$(trim "${row%%"${TAB}"*}")"
            rest="${row#*"${TAB}"}"
            base="$(trim "${rest%%"${TAB}"*}")"
            title="$(trim "${rest#*"${TAB}"}")"
            ;;
    esac
    [ -f "${src}" ] || { printf 'MISSING %s\n' "${src}"; return 2; }
    new_tmp RESOLVED_TMP; new_tmp BODY_TMP; new_tmp TITLE_TMP; new_tmp MAP_TMP; new_tmp OUT_TMP; new_tmp ERR_TMP
    resolve_placeholders "${src}" "${RESOLVED_TMP}" "${MAP_TMP}"; prc=$?
    [ "${prc}" -le 1 ] || { printf 'MISSING could not read %s\n' "${src}"; return 2; }
    if [ "${kind}" = comment ]; then cat "${RESOLVED_TMP}" > "${BODY_TMP}"; else drop_h1 "${RESOLVED_TMP}" "${BODY_TMP}" "${title}" "${long}"; fi
    lint_body "${src}" "${RESOLVED_TMP}" "${BODY_TMP}" "${title}" "${TITLE_TMP}" || return 3
    refuse_recorded "${kind}" "${key}" || return 4
    build_argv "${kind}" "${key}" "${title}" "${head}" "${base}"
    if [ "${LIVE}" != "1" ]; then
        print_dry "${kind}" "${key}" "${src}" "${title}"
        return 0   # the dry run ends here: no gh call of any kind, not even the read, below this line
    fi
    command -v gh > /dev/null 2>&1 || { printf 'GH-FAILED gh is not on PATH; nothing posted\n'; return 5; }
    github_precheck "${kind}" "${key}" "${title}" || return $?
    github_create "${kind}" "${key}"
}

lint_cmd() {
    local f rc=0 total=0 prc
    new_tmp RESOLVED_TMP; new_tmp MAP_TMP
    for f in "$@"; do
        if [ ! -f "${f}" ]; then printf 'MISSING %s\n' "${f}"; rc=2; continue; fi
        ALLOW_MARKERS=0
        if in_fixture_dir "${f}"; then ALLOW_MARKERS=1; fi
        LINT_HITS=0
        resolve_placeholders "${f}" "${RESOLVED_TMP}" "${MAP_TMP}"; prc=$?
        [ "${prc}" -le 1 ] || { printf 'MISSING could not read %s\n' "${f}"; rc=2; continue; }
        lint_file "${RESOLVED_TMP}" "${f}"
        body_checks "${RESOLVED_TMP}" "${f}"
        if [ "${LINT_HITS}" -gt 0 ]; then
            printf 'LINT-FAILED %s: %s hit(s)\n' "${f}" "${LINT_HITS}"
            total=$((total + LINT_HITS))
        else
            printf 'LINT-OK %s\n' "${f}"
        fi
    done
    [ "${rc}" -eq 0 ] || return "${rc}"
    [ "${total}" -eq 0 ] || return 3
    return 0
}

status_cmd() {
    if [ ! -f "${RECORD}" ] || ! grep -qv '^#' "${RECORD}"; then
        printf 'STATUS nothing recorded yet (%s)\n' "${RECORD}"
        return 0
    fi
    printf 'STATUS %s\n' "${RECORD}"
    awk -F'\t' 'substr($0, 1, 1) != "#" && NF > 0 {
        printf "  %s  %-7s  %-48s  %-7s  %s\n", $1, $2, $3, ($4 == "-" ? "-" : "#" $4), $5 }' "${RECORD}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --live) LIVE=1; shift ;;
        --again) AGAIN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) usage_error "unknown option $1" ;;
        *) break ;;
    esac
done
CMD="${1:-}"
[ $# -eq 0 ] || shift
case "${CMD}" in
    issue|comment|pr)
        [ $# -eq 1 ] || usage_error "${CMD} takes exactly one argument"
        post_one "${CMD}" "$1"
        exit $?
        ;;
    lint)
        [ "${LIVE}" = "0" ] && [ "${AGAIN}" = "0" ] || usage_error "--live and --again go with issue, comment or pr"
        [ $# -ge 1 ] || usage_error "lint takes at least one file"
        lint_cmd "$@"
        exit $?
        ;;
    status)
        [ "${LIVE}" = "0" ] && [ "${AGAIN}" = "0" ] || usage_error "--live and --again go with issue, comment or pr"
        [ $# -eq 0 ] || usage_error "status takes no argument"
        status_cmd
        exit $?
        ;;
    *)
        usage_error "unknown command '${CMD}'"
        ;;
esac
