#!/usr/bin/env bash
# orch-pr-body-edit.sh — bench 8 program, orchestrator only: replace the body of an OPEN pull request with
# its local text. Dry by default: nothing reaches GitHub without --live.
#
#   orch-pr-body-edit.sh [--live] <key>...        key = 00 01 02 03 04 xf 05 06 09 (rows of the map below)
#
# Per key: the text tasks/pr-bodies/bench6-<key>-*.md is rendered ({{slug}} -> #<number> of the issue the
# record holds under <slug>; {{pr-09}} -> the ninth pull request's number from its pr row) to
# tasks/pr-bodies/rendered/bench6-<key>.md; the posting script's lint runs
# on the rendered file and any hit refuses; the stale-phrase check refuses; then, live only,
# `gh pr edit <number> --body-file <rendered>`, the live body is read back and its sha256 must equal the
# rendered file's; one row goes to the record tasks/bench7/gh-posted.tsv:
#   <utc> pr-edit <key> <number> <url> <sha256 of the live body>
# Exit: 0 ok, 2 usage or missing file, 3 lint or stale phrase, 5 gh failed, 6 live body differs.
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
REPO=Telcoin-Association/telcoin-network
PR_DIR="${ROOT}/tasks/pr-bodies"
OUT_DIR="${PR_DIR}/rendered"
RECORD="${ROOT}/tasks/bench7/gh-posted.tsv"
POST="${ROOT}/tasks/bench7/orch-gh-post.sh"
STALE='staging|of 6|of 8 in the stack|not sent yet|until that PR merges|[{][{]'
pr_of() {
    case "$1" in
        00) echo 1862 ;; 01) echo 1863 ;; 02) echo 1864 ;; 03) echo 1865 ;; 04) echo 1866 ;;
        xf) echo 1867 ;; 05) echo 1868 ;; 06) echo 1869 ;;
        09) awk -F'\t' '$2 == "pr" && $3 == "09" && $4 ~ /^[0-9]+$/ { n = $4 } END { print n }' "${RECORD}" ;;
        *) echo "" ;;
    esac
}
LIVE=0
[ "${1:-}" = "--live" ] && { LIVE=1; shift; }
[ "$#" -gt 0 ] || { sed -n '2,14p' "$0"; exit 2; }
mkdir -p "${OUT_DIR}"
rc=0
for key in "$@"; do
    num="$(pr_of "${key}")"
    [ -n "${num}" ] || { echo "UNKNOWN key ${key}"; exit 2; }
    n=0; src=""
    for f in "${PR_DIR}/bench6-${key}-"*.md; do [ -f "${f}" ] && { src="${f}"; n=$((n + 1)); }; done
    [ "${n}" -eq 1 ] || { echo "MISSING exactly one body for ${key} (found ${n})"; exit 2; }
    out="${OUT_DIR}/bench6-${key}.md"
    python3 - "${src}" "${out}" "${RECORD}" <<'PY' || { echo "RENDER failed ${key}"; exit 3; }
import re, sys
src, out, record = sys.argv[1:4]
nums = {}
for line in open(record, encoding="utf-8"):
    c = line.rstrip("\n").split("\t")
    if len(c) >= 4 and c[1] == "issue":
        nums[c[2]] = c[3]
    elif len(c) >= 4 and c[1] == "pr" and c[3].isdigit():
        nums["pr-" + c[2]] = c[3]      # {{pr-09}}: a pull request of the stack by its key
text = open(src, encoding="utf-8").read()
bad = []
def sub(m):
    slug = m.group(1)
    if slug not in nums:
        bad.append(slug)
        return m.group(0)
    return "#" + nums[slug]
text = re.sub(r"\{\{([a-z0-9][a-z0-9-]*)\}\}", sub, text)
if bad:
    sys.exit("UNRESOLVED " + ", ".join(bad))
open(out, "w", encoding="utf-8").write(text)
PY
    if ! bash "${POST}" lint "${out}" > "${out}.lint" 2>&1; then
        echo "LINT ${key}:"; sed 's/^/  /' "${out}.lint" | head -20; rc=3; continue
    fi
    rm -f "${out}.lint"
    if grep -nE "${STALE}" "${out}" > /dev/null; then
        echo "STALE ${key}:"; grep -nE "${STALE}" "${out}" | cut -c1-200 | sed 's/^/  /'; rc=3; continue
    fi
    grep -q '^## Limits and what a reviewer should look at' "${out}" || { echo "NO-LIMITS-SECTION ${key}"; rc=3; continue; }
    want="$(sha256sum < "${out}" | cut -d' ' -f1)"
    if [ "${LIVE}" != "1" ]; then
        echo "DRY ${key} -> #${num}: $(wc -w < "${out}" | tr -d ' ') words, sha256 ${want}; nothing posted (add --live)"
        continue
    fi
    if ! gh pr edit "${num}" --repo "${REPO}" --body-file "${out}" > "${out}.gh" 2>&1; then
        echo "GH-FAILED ${key} #${num}:"; sed 's/^/  /' "${out}.gh" | head -10; rc=5; continue
    fi
    url="$(grep -oE 'https://github.com/[^ ]+/pull/[0-9]+' "${out}.gh" | head -1)"
    rm -f "${out}.gh"
    got="$(gh api "repos/${REPO}/pulls/${num}" | python3 -c 'import sys, json, hashlib; print(hashlib.sha256(json.load(sys.stdin)["body"].replace("\r\n", "\n").encode()).hexdigest())')"
    if [ "${got}" != "${want}" ]; then
        echo "DIFFERS ${key} #${num}: live ${got}, rendered ${want}"; rc=6; continue
    fi
    printf '%s\tpr-edit\t%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "${key}" "${num}" "${url:-https://github.com/${REPO}/pull/${num}}" "${got}" >> "${RECORD}"
    echo "EDITED ${key} #${num} live sha256 = rendered ${got}"
done
exit "${rc}"
