#!/usr/bin/env bash
#
# benchmark/tools/archive-run.sh — copy results/<run>/ to the archive bucket and verify the copy.
#
# Since 2026-10-08 the archive bucket is the canonical copy of every finished run (runs/<run>/results/
# in it; benchmark/results/<run>/ is a transient working copy). This script:
#   1. lists what a `gcloud storage rsync --dry-run` of results/<run>/ to that prefix would copy, and
#      refuses to go on when any of it is a file the archive rule excludes (genesis*/ at the top: node
#      keys; tunnel*.pid; dot-files) or would land outside the prefix (tools/archive-verify.py
#      --check-dry-run, which reads the rule without the regex);
#   2. runs the same rsync for real, with composite uploads off (every object then has an MD5), under
#      an alarm of BENCH_ARCHIVE_TIMEOUT_SECS (default 28800 = 8 h). rsync only adds or replaces objects:
#      nothing is deleted on either side, and a re-run resumes where an interrupted one stopped;
#   3. runs tools/archive-verify.py --run <run>: size and MD5 of every file the rule takes.
# The rule, the bucket and the project come from tools/archive-verify.py --print-target (the project
# from the repo's config.sh; BENCH_ARCHIVE_BUCKET overrides the bucket). The exclude regex never
# starts with "^": gcloud reads such a list-flag value as a delimiter spec and drops the rule silently.
# Step 1's listing and step 2's full output are kept in benchmark/work/archive/<run>-rsync-<UTC>.log;
# the verify writes benchmark/work/archive/<run>-verify.md.
#
# Output: the plan, the tail of the rsync output, the verify's summary; on success the verify's
# `ARCHIVE_REMOTE {...}` line (benchmark-teardown.sh records it as manifest.archive.remote); the last
# line is `== archive-run run=<run> rc=<n>`. rc 0 = archived and verified; 1 = refused, upload failed
# or the verify found a problem; 2 = usage.
#
# Usage: benchmark/tools/archive-run.sh --run <id> [--dry-run]
#   --dry-run prints the commands and calls no gcloud at all.

set -euo pipefail
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
BENCH="$(cd "${TOOLS}/.." && pwd)"
RUN=""; DRY=0
die() { echo "❌ archive-run: $*" >&2; echo "== archive-run run=${RUN:-?} rc=2"; exit 2; }
while [ $# -gt 0 ]; do
    case "$1" in
        --run) RUN="${2:-}"; [ $# -ge 2 ] || die "--run needs an id"; shift ;;
        --run=*) RUN="${1#*=}" ;;
        --dry-run) DRY=1 ;;
        -h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
        *) die "unknown argument '$1' (supported: --run <id>, --dry-run)" ;;
    esac
    shift
done
case "${RUN}" in ''|*[!a-z0-9-]*|-*) die "--run <id> is required (a results/ directory name, e.g. r20261107-1504)" ;; esac
SRC="${BENCH}/results/${RUN}"
[ -d "${SRC}" ] || die "${SRC} is not a directory"
TIMEOUT="${BENCH_ARCHIVE_TIMEOUT_SECS:-28800}"
case "${TIMEOUT}" in [1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) die "BENCH_ARCHIVE_TIMEOUT_SECS must be a whole number of seconds, 1 to 999999 (got '${TIMEOUT}')" ;;
esac
DRYRUN_TIMEOUT=900

tgt="$(python3 -I "${TOOLS}/archive-verify.py" --run "${RUN}" --print-target)" || die "tools/archive-verify.py --print-target failed"
PROJECT="$(printf '%s\n' "${tgt}" | sed -n 's/^PROJECT=//p')"
URI="$(printf '%s\n' "${tgt}" | sed -n 's/^URI=//p')"
EXCLUDE="$(printf '%s\n' "${tgt}" | sed -n 's/^EXCLUDE=//p')"
[ -n "${PROJECT}" ] && [ -n "${URI}" ] && [ -n "${EXCLUDE}" ] || die "tools/archive-verify.py --print-target printed no PROJECT, URI or EXCLUDE"
case "${EXCLUDE}" in
    ^*) die "the exclude rule starts with '^': gcloud would read it as a delimiter spec and ignore it" ;;
    *,*) die "the exclude rule holds a comma: gcloud would split it into two rules" ;;
esac

# Composite (parallel) uploads leave an object with no MD5 (crc32c only): off, so the verify can check every one.
export CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_ENABLED=False
# The destination without its trailing slash, as the proven one-off of 2026-11-10 gave it.
RSYNC=(gcloud storage rsync -r "--exclude=${EXCLUDE}" "--project=${PROJECT}" "${SRC}" "${URI%/}")
VERIFY=(python3 -I "${TOOLS}/archive-verify.py" --run "${RUN}")
show() { printf ' +'; printf ' %q' "$@"; printf '\n'; }
echo ">>> archive ${SRC} -> ${URI}"
if [ "${DRY}" = "1" ]; then
    printf '  (alarm %s s)' "${DRYRUN_TIMEOUT}"; show "${RSYNC[@]:0:4}" --dry-run "${RSYNC[@]:4}"
    echo "    refused when a file it would copy is one the archive rule excludes (tools/archive-verify.py --check-dry-run)"
    printf '  (alarm %s s)' "${TIMEOUT}"; show "${RSYNC[@]}"
    printf ' '; show "${VERIFY[@]}"
    echo "  (dry run — no gcloud call was made)"
    echo "== archive-run run=${RUN} rc=0 dry_run=1"
    exit 0
fi
[ "${DRY}" = "0" ] || exit 0
mkdir -p "${BENCH}/work/archive" || die "could not create ${BENCH}/work/archive"
LOG="${BENCH}/work/archive/${RUN}-rsync-$(date -u +%Y%m%dT%H%M%SZ).log"

# 1. What would be copied: nothing the rule excludes, nothing outside the run's prefix.
rc=0
echo "  dry run: listing what rsync would copy (alarm ${DRYRUN_TIMEOUT} s) -> ${LOG}"
perl -e 'alarm shift; exec @ARGV' "${DRYRUN_TIMEOUT}" "${RSYNC[@]:0:4}" --dry-run "${RSYNC[@]:4}" </dev/null >"${LOG}.dry" 2>&1 || rc=$?
cat -- "${LOG}.dry" >> "${LOG}"
if [ "${rc}" -ne 0 ]; then
    tail -n 5 -- "${LOG}.dry" | sed 's/^/    /'
    rm -f -- "${LOG}.dry"
    echo "❌ archive-run: the rsync dry run failed (rc ${rc}) — nothing was uploaded" >&2
    echo "== archive-run run=${RUN} rc=1"
    exit 1
fi
rc=0
"${VERIFY[@]}" --check-dry-run "${LOG}.dry" | sed 's/^/    /' || rc=$?
rm -f -- "${LOG}.dry"
if [ "${rc}" -ne 0 ]; then
    echo "❌ archive-run: the rsync dry run would copy file(s) the archive rule excludes, or outside ${URI} (above) — nothing was uploaded" >&2
    echo "== archive-run run=${RUN} rc=1"
    exit 1
fi

# 2. The upload: adds or replaces objects, never deletes; a re-run resumes.
rc=0
echo "  upload (alarm ${TIMEOUT} s, BENCH_ARCHIVE_TIMEOUT_SECS) -> ${LOG}"
perl -e 'alarm shift; exec @ARGV' "${TIMEOUT}" "${RSYNC[@]}" </dev/null >"${LOG}.up" 2>&1 || rc=$?
cat -- "${LOG}.up" >> "${LOG}"
echo "    $(grep -c '^Copying ' "${LOG}.up" || true) file(s) copied; the last lines of gcloud's output:"
tr '\r' '\n' < "${LOG}.up" | grep -v -e '^Copying ' -e '^[[:space:]]*$' | tail -n 5 | sed 's/^/      /' || true
rm -f -- "${LOG}.up"
if [ "${rc}" -ne 0 ]; then
    echo "❌ archive-run: gcloud storage rsync exited ${rc}$([ "${rc}" -ne 142 ] || echo " (the ${TIMEOUT}-s alarm)") — re-run to resume; nothing was deleted" >&2
    echo "== archive-run run=${RUN} rc=1"
    exit 1
fi

# 3. Size and MD5 of every file the rule takes.
rc=0
"${VERIFY[@]}" || rc=$?
[ "${rc}" -eq 0 ] || echo "❌ archive-run: the verify found a problem (above) — re-run to upload what is missing or different" >&2
echo "== archive-run run=${RUN} rc=$([ "${rc}" -eq 0 ] && echo 0 || echo 1)"
[ "${rc}" -eq 0 ]
