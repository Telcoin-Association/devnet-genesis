#!/usr/bin/env bash
# w0-archive.sh — bench 6 W0: copy results/<run>/ of the given runs to the canonical archive bucket
# (runs/<run>/results/), then verify every archived file by size and MD5. Never deletes on either side.
# The exclude rule is the archive's old one (genesis*/ holds node keys, tunnel.pid, dot-files). It must
# NOT start with '^': gcloud reads a list-flag value that starts with '^' as a delimiter spec and the
# rule is then silently ignored (checked by a dry run on 2026-11-10: 24 genesis files leaked).
# Usage: tasks/bench6/w0-archive.sh <run>...     (run detached; the last line is "== w0-archive rc=<n> verify=<n>")
set -uo pipefail
cd /home/drtnarg/coding/telcoin/devnet-genesis || exit 2
export CLOUDSDK_STORAGE_PARALLEL_COMPOSITE_UPLOAD_ENABLED=False
PROJECT=tn-devnet
BUCKET=tn-devnet-benchmark-archive
EXC='genesis[^/]*/.*|(.*/)?tunnel\.pid|(.*/)?\..*'
rc_all=0
for run in "$@"; do
    src="benchmark/results/${run}"
    dst="gs://${BUCKET}/runs/${run}/results"
    [ -d "${src}" ] || { echo "MISSING ${src}"; rc_all=1; continue; }
    echo "== rsync ${run} start $(date -u +%FT%TZ)"
    leak="$(timeout 900 gcloud storage rsync -r --dry-run --exclude="${EXC}" --project="${PROJECT}" "${src}" "${dst}" </dev/null 2>&1 \
        | grep 'Would copy' | grep -c -E '/results/genesis[^/]*/|tunnel\.pid|/\.[^/]*')"
    if [ "${leak}" != "0" ]; then echo "== rsync ${run} REFUSED: exclude rule leaks ${leak} files"; rc_all=1; continue; fi
    timeout 8h gcloud storage rsync -r --exclude="${EXC}" --project="${PROJECT}" "${src}" "${dst}" </dev/null 2>&1 | grep -v '^Copying \|^\s*$' | tail -n 40
    rc=${PIPESTATUS[0]}
    echo "== rsync ${run} rc=${rc} $(date -u +%FT%TZ)"
    [ "${rc}" -eq 0 ] || rc_all=1
done
echo "== verify start $(date -u +%FT%TZ)"
python3 -I tasks/bench6/w0-archive-verify.py "$@"
vrc=$?
echo "== w0-archive rc=${rc_all} verify=${vrc} $(date -u +%FT%TZ)"
