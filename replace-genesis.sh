#!/bin/bash
#
# Replace genesis.yaml on all remote nodes.
#
# This script SCPs the local genesis file to each validator
# and observer node, replacing the existing file.
#
source ./config.sh

REMOTE_GENESIS_PATH="/home/validator/telcoin/genesis/genesis.yaml"

# Verify local genesis file exists
if [ ! -f "${GENESIS_FILE}" ]; then
    echo "Error: Local genesis file not found at ${GENESIS_FILE}"
    exit 1
fi

echo "Replacing genesis.yaml on all remote nodes..."
echo "Source: ${GENESIS_FILE}"
echo "Destination: ${REMOTE_GENESIS_PATH}"
echo ""

# Arrays to store process IDs
pids=()
exit_statuses=()

# SCP genesis file to each node and copy to validator path in parallel
for i in "${!INSTANCE_NAMES[@]}"; do
    (
        gcloud compute scp "${GENESIS_FILE}" "${INSTANCE_NAMES[$i]}:${REMOTE_SHARE_PATH}" --zone "${ZONES[$i]}" 2>&1 && \
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="sudo cp ${REMOTE_SHARE_PATH}genesis.yaml ${REMOTE_GENESIS_PATH}" 2>&1
    ) &

    pids+=($!)
    echo "Started SCP to ${INSTANCE_NAMES[$i]} (PID: ${pids[-1]})"
done

echo ""
echo "Waiting for all transfers to complete..."
echo ""

# Wait for all processes
deploy_success=true
for i in "${!pids[@]}"; do
    wait ${pids[$i]}
    exit_status=$?
    exit_statuses+=($exit_status)

    if [ $exit_status -ne 0 ]; then
        echo "Failed: ${INSTANCE_NAMES[$i]}"
        deploy_success=false
    else
        echo "Success: ${INSTANCE_NAMES[$i]}"
    fi
done

# Summary
echo ""
echo "========================================="
echo "Summary"
echo "========================================="

success_count=0
failed=()
for i in "${!exit_statuses[@]}"; do
    if [ ${exit_statuses[$i]} -eq 0 ]; then
        ((success_count++))
    else
        failed+=("${INSTANCE_NAMES[$i]}")
    fi
done

echo "Total: ${#INSTANCE_NAMES[@]} | Success: $success_count | Failed: ${#failed[@]}"

if [ ${#failed[@]} -gt 0 ]; then
    echo ""
    echo "Failed instances:"
    for instance in "${failed[@]}"; do
        echo "  - $instance"
    done
    exit 1
fi

echo ""
echo "Genesis file replaced on all nodes."
