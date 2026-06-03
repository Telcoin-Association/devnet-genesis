#!/bin/bash
#
# this script stops the telcoin container, wipes ONLY the libp2p Kademlia DHT
# store, then restarts the container in place on all instances in parallel.
#
# directory removed (under /home/validator/telcoin/):
#   - consensus-db/kad
#
# everything else (blobstore, consensus-db tables outside kad, db, static_files,
# keys, genesis config, etc.) is preserved. because consensus and execution
# data are intact, no ./update.sh re-bootstrap is required — the container is
# simply started again on the same node.
#

# load variables
source ./config.sh

# Create logs directory if it doesn't exist
LOGS_DIR="./logs"
timestamp=$(date +"%Y%m%d_%H%M%S")
OUTPUT_PATH="${LOGS_DIR}/${timestamp}"
mkdir -p "${OUTPUT_PATH}"

# Array to store process IDs
pids=()
exit_statuses=()

# Remote command to stop container, wipe kad store, and restart container
REMOTE_CMD='
echo "=== Stopping telcoin container ==="
sudo docker stop telcoin 2>/dev/null

# wait for the container to stop
while [ "$(sudo docker inspect -f '"'"'{{.State.Running}}'"'"' telcoin 2>/dev/null)" = "true" ]; do
    sleep 1
done

sudo docker wait telcoin 2>/dev/null
sleep 1

echo "=== Wiping kad directory ==="
TARGET="/home/validator/telcoin/consensus-db/kad"
if [ -d "$TARGET" ]; then
    sudo rm -rf "$TARGET"
    echo "Deleted: $TARGET"
else
    echo "Not found (skipped): $TARGET"
fi

echo "=== Remaining contents of /home/validator/telcoin/consensus-db/ ==="
ls -la /home/validator/telcoin/consensus-db/

echo "=== Starting telcoin container ==="
sudo docker start telcoin

# wait briefly for the container to transition back to running
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if [ "$(sudo docker inspect -f '"'"'{{.State.Running}}'"'"' telcoin 2>/dev/null)" = "true" ]; then
        break
    fi
    sleep 1
done

running_state="$(sudo docker inspect -f '"'"'{{.State.Running}}'"'"' telcoin 2>/dev/null)"
if [ "$running_state" = "true" ]; then
    echo "Container running: telcoin"
else
    echo "ERROR: telcoin container did not return to running state (Running=$running_state)"
    exit 1
fi

echo "=== Done ==="
'

# Loop through each server and launch commands in background
for i in "${!INSTANCE_NAMES[@]}"; do
    # Create log file for this instance
    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"

    NODE_TYPE="VALIDATOR"

    # Log the start time
    echo "Starting wipe on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] (PID: pending...)"

    # Execute wipe command in background and redirect output to log file
    (
        echo "=== Starting kad wipe on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        echo "Zone: ${ZONES[$i]}"
        echo ""

        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="${REMOTE_CMD}" 2>&1

        # Capture exit status
        exit_code=$?

        # Log the completion status
        if [ $exit_code -eq 0 ]; then
            echo ""
            echo "=== Kad wipe + restart completed successfully on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        else
            echo ""
            echo "=== Kad wipe FAILED on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] with exit code $exit_code at $(date) ==="
        fi

        exit $exit_code
    ) > "$LOG_FILE" 2>&1 &

    # Store the process ID of the background task
    pids+=($!)

    last_index=$((${#pids[@]} - 1))
    echo "Started wipe on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] (PID: ${pids[$last_index]}, Log: $LOG_FILE)"
done

echo ""
echo "All wipe jobs launched. Waiting for completion..."
echo ""

# Wait for all background processes to complete and capture exit statuses
for i in "${!pids[@]}"; do
    wait ${pids[$i]}
    exit_statuses+=($?)

    NODE_TYPE="VALIDATOR"

    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"

    if [ ${exit_statuses[$i]} -ne 0 ]; then
        echo "❌ Error: kad wipe failed on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] - See $LOG_FILE for details"
        echo "   Last 10 lines of log:"
        tail -10 "$LOG_FILE" | sed 's/^/   /'
    else
        echo "✅ Successfully wiped kad and restarted container on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}]"
    fi
done

# Combine all logs for easy review
echo ""
echo "Combining all logs to $OUTPUT_PATH/combined_$timestamp.log"
cat $OUTPUT_PATH/*_$timestamp.log > "$OUTPUT_PATH/combined_$timestamp.log"

# Summary statistics
echo ""
echo "========================================="
echo "Kad Wipe Execution Summary"
echo "========================================="

# Count successes and failures
success_count=0
failed_instances=()
validator_count=0

for i in "${!exit_statuses[@]}"; do
    ((validator_count++))

    if [ ${exit_statuses[$i]} -eq 0 ]; then
        ((success_count++))
    else
        failed_instances+=("${INSTANCE_NAMES[$i]}")
    fi
done

echo "Total instances: ${#INSTANCE_NAMES[@]}"
echo "  - Validators: $validator_count"
echo ""
echo "Successful: $success_count"
echo "Failed: $((${#INSTANCE_NAMES[@]} - success_count))"

if [ ${#failed_instances[@]} -gt 0 ]; then
    echo ""
    echo "Failed instances:"
    for instance in "${failed_instances[@]}"; do
        echo "  - $instance"
    done
fi

echo ""
echo "Logs directory: $OUTPUT_PATH"
echo "========================================="

# Check if any job failed
if [[ " ${exit_statuses[@]} " =~ " 1 " ]]; then
    echo ""
    echo "⚠️  One or more kad wipe jobs failed. See logs in $OUTPUT_PATH for details."
    exit 1
else
    echo ""
    echo "🎉 Kad wiped and telcoin container restarted on every instance."
fi

echo ""
echo "Complete"
