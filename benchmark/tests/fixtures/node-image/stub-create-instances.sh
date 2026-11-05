#!/usr/bin/env bash
# common/create-instances.sh stand-in, copied over the repo's in a test tree (test_node_image.py
# ZoneFallbackTests). Like the real one it warms the gcloud token, sources CONFIG_FILE (benchmark/config.sh,
# so ZONES honours results/<run>/zones.env), skips the instances that exist and creates the rest; a
# "created" instance is $STUB_SPOOL/instances/<inst> holding its zone (the fake gcloud's instances
# describe answers from there). Each call logs `create-instances.sh <inst>@<zone> ...` (the instances it
# tried) to $STUB_LOG.
#   STUB_STOCKOUT=<inst>          the first call fails <inst> with gcloud's ZONE_RESOURCE_POOL_EXHAUSTED text
#   STUB_STOCKOUT_ZONES="<zone>…" every create in one of these zones fails the same way
#   STUB_CREATE_FAIL=<inst>       every create of <inst> fails on a quota error (not a stockout)
#   STUB_LOSE_LOG=<inst>          <inst>'s own log is gone by the time the deploy reads it
# A failure is reported the way the real script does: it runs in REPO_ROOT (cd), the instance's own log
# is ./logs/instance-creation/<inst>_creation_<n>.log there and is named by that relative path on
# "❌ Error: Failed to create instance <inst> - See <log> for details", followed by its last lines, the
# summary's "Failed instances:" list, exit 1.
set -eo pipefail
gcloud auth print-access-token >/dev/null || { echo "❌ gcloud auth failed — run 'gcloud auth login' and retry"; exit 1; }
# shellcheck source=/dev/null
. "${CONFIG_FILE:?}"
cd "${REPO_ROOT:?}"
mkdir -p ./logs/instance-creation
fix="$(dirname "$0")/stub-create-stockout.txt"
spool="${STUB_SPOOL:?}"
mkdir -p "${spool}/instances"
n=$(( $(cat "${spool}/create-calls" 2>/dev/null || echo 0) + 1 )); echo "${n}" > "${spool}/create-calls"
tried=""; failed=()
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
    if [ -f "${spool}/instances/${inst}" ]; then
        echo "Instance ${inst} already exists in $(cat "${spool}/instances/${inst}") — skipping."
        continue
    fi
    tried="${tried} ${inst}@${zone}"
    log="./logs/instance-creation/${inst}_creation_${n}.log"
    { echo "=== Starting instance creation for ${inst} ==="; echo "  - Zone: ${zone}"; } > "${log}"
    if { [ "${n}" = 1 ] && [ "${STUB_STOCKOUT:-}" = "${inst}" ]; } || case " ${STUB_STOCKOUT_ZONES:-} " in *" ${zone} "*) true ;; *) false ;; esac; then
        sed -e "s/@ZONE@/${zone}/g" "${fix}" >> "${log}"
    elif [ "${STUB_CREATE_FAIL:-}" = "${inst}" ]; then
        printf "ERROR: (gcloud.beta.compute.instances.create) Could not fetch resource:\n - Quota 'C3_CPUS' exceeded.  Limit: 8.0 in region %s.\n" "${zone%-*}" >> "${log}"
    else
        echo "${zone}" > "${spool}/instances/${inst}"
        echo "Successfully created instance ${inst}"
        continue
    fi
    echo "=== FAILED to create instance ${inst} with exit code 1 ===" >> "${log}"
    echo "❌ Error: Failed to create instance ${inst} - See ${log} for details"
    echo "   Last 10 lines of log:"
    tail -10 "${log}" | sed 's/^/   /'
    [ "${STUB_LOSE_LOG:-}" != "${inst}" ] || rm -f "${log}"
    failed+=("${inst}")
done
printf 'create-instances.sh%s CONFIG_FILE=%s\n' "${tried}" "${CONFIG_FILE}" >> "${STUB_LOG:?}"
if [ "${#failed[@]}" -gt 0 ]; then
    echo "Failed instances:"
    printf '  - %s\n' "${failed[@]}"
    echo "Some instances failed to create. Please check the logs for details."
    exit 1
fi
echo "All instances created successfully!"
