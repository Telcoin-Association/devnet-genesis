#!/usr/bin/env bash
#
# check-bash-portability.sh — guardrail lint so the macOS-bash-3.2 / GNU-vs-BSD class of
# bug (e.g. `mapfile` under a #!/bin/bash shebang) can't silently regress.
#
# macOS /bin/bash is 3.2.57 (no bash-4 builtins); macOS ships BSD coreutils. Linux is
# bash 4+/5 + GNU. An OPERATOR script (runs on the dev's Mac) that uses a bash-4 feature
# under #!/bin/bash, or a GNU-only tool, breaks on macOS. NODE scripts (run on the Ubuntu
# nodes) may legitimately use GNU tools — so GNU-tool hits are WARN, not ERROR.
#
# Checks (per script):
#   ERROR  — #!/bin/bash shebang AND a bash-4 feature  (this is the exact mapfile regression)
#   WARN   — bash-4 feature under any shebang (breaks on a stock 3.2 Mac w/o Homebrew bash)
#   WARN   — GNU-only tool invocation (fine on Linux nodes; breaks if run locally on macOS)
#
# Usage:
#   tasks/check-bash-portability.sh                 # lint the devnet-genesis operator scripts
#   tasks/check-bash-portability.sh --all           # also lint tn-node-deployment/ (node scripts)
#   tasks/check-bash-portability.sh file1 file2 ...  # lint specific files
# Exit: non-zero if any ERROR is found (suitable for CI / pre-commit).
#
# This script is itself portable (POSIX grep/awk only; no sed -i / bash-4 features), so it
# runs under macOS bash 3.2 AND Linux bash 5.
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# --- collect target files --------------------------------------------------------
INCLUDE_NODE=0
FILES=()
for a in "$@"; do
    case "$a" in
        --all) INCLUDE_NODE=1 ;;
        *) FILES+=("$a") ;;
    esac
done
if [ "${#FILES[@]}" -eq 0 ]; then
    # default: devnet-genesis's own operator scripts (root + tasks/)
    for f in "${REPO_ROOT}"/*.sh "${REPO_ROOT}"/tasks/*.sh; do [ -f "$f" ] && FILES+=("$f"); done
    if [ "${INCLUDE_NODE}" -eq 1 ]; then
        while IFS= read -r f; do FILES+=("$f"); done < <(find "${REPO_ROOT}/tn-node-deployment" -name '*.sh' 2>/dev/null)
    fi
fi

# --- patterns --------------------------------------------------------------------
# bash-4 features absent from macOS /bin/bash 3.2 (ERE). Anchored to reduce comment hits.
BASH4_ERE='(^|[;&|[:space:](])(mapfile|readarray|coproc)[[:space:]]|declare[[:space:]]+-[A-Za-z]*[Ag]|[$]\{[A-Za-z_][A-Za-z0-9_]*(\^\^|,,|\^|,)\}|[$]\{[A-Za-z_][A-Za-z0-9_]*\[-[0-9]|;;&|wait[[:space:]]+-n([[:space:]]|$)'
# GNU-only tool invocations that differ/fail on BSD/macOS (ERE).
GNU_ERE='sed[[:space:]]+-i([[:space:]]|$)|grep[[:space:]]+-[a-zA-Z]*P|readlink[[:space:]]+-f|[[:space:]]realpath[[:space:]]|date[[:space:]]+-d|date[[:space:]]+--date|stat[[:space:]]+-c|stat[[:space:]]+--format|df[[:space:]]+--output|df[[:space:]]+-[a-zA-Z]*B|hostname[[:space:]]+-I|[[:space:]]nproc([[:space:]]|$|\))|[[:space:]]timeout[[:space:]]|sha256sum|[[:space:]]getent[[:space:]]|[[:space:]]lsblk([[:space:]]|$)|[[:space:]]truncate[[:space:]]|xargs[[:space:]]+-r'

errors=0; warns=0; scanned=0
# strip_comments: drop full-line comments + the shebang so we don't match commentary.
# (inline trailing comments may still match — acceptable for a guardrail.)
scan_one() {
    local f="$1" shebang body b4 gnu
    # Skip self: this linter's pattern/message strings literally contain "mapfile", "sed -i",
    # etc., which would self-match. (It's the detector, not a violator.)
    case "$f" in */check-bash-portability.sh) return 0 ;; esac
    scanned=$((scanned + 1))
    shebang="$(head -1 "$f")"
    body="$(grep -nvE '^[[:space:]]*#' "$f")"   # numbered lines, full-line comments removed

    b4="$(printf '%s\n' "$body" | grep -nE "$BASH4_ERE" || true)"
    gnu="$(printf '%s\n' "$body" | grep -nE "$GNU_ERE" || true)"

    [ -n "$b4" ] || [ -n "$gnu" ] || return 0
    echo "── ${f#"${REPO_ROOT}/"}  (shebang: ${shebang:-none})"

    if [ -n "$b4" ]; then
        if [ "$shebang" = "#!/bin/bash" ]; then
            printf '%s\n' "$b4" | while IFS= read -r l; do echo "   ERROR bash-4 feature under #!/bin/bash (dies on macOS 3.2): $l"; done
            errors=$((errors + 1))
        else
            printf '%s\n' "$b4" | while IFS= read -r l; do echo "   WARN  bash-4 feature (needs bash 4+; breaks on a stock 3.2 Mac): $l"; done
            warns=$((warns + 1))
        fi
    fi
    [ -n "$gnu" ] && { printf '%s\n' "$gnu" | while IFS= read -r l; do echo "   WARN  GNU-only tool (ok on Linux nodes; breaks if run locally on macOS): $l"; done; warns=$((warns + 1)); }
}

# NOTE: the while-pipe subshell would lose the counters, so iterate without a pipe.
echo "bash portability lint — ${#FILES[@]} file(s)"
echo "================================================================"
tmperr=0
for f in "${FILES[@]}"; do
    [ -f "$f" ] || continue
    out="$(scan_one "$f")"
    if [ -n "$out" ]; then
        echo "$out"
        printf '%s' "$out" | grep -q ' ERROR ' && tmperr=$((tmperr + 1))
    fi
done
echo "================================================================"
if [ "$tmperr" -gt 0 ]; then
    echo "FAIL: ${tmperr} file(s) have ERROR-level portability defects (bash-4 under #!/bin/bash)."
    echo "Fix: use '#!/usr/bin/env bash' AND/OR rewrite portably (e.g. mapfile -> while-read loop)."
    exit 1
fi
echo "OK: no ERROR-level defects. (Review any WARN lines: fine for Linux-node scripts, fix for operator-Mac scripts.)"
exit 0
