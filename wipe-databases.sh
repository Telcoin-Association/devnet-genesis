#!/bin/bash
#
# this script stops the telcoin container and wipes database/cache directories
# on all instances in parallel, preparing for a fresh network restart via ./update.sh
#
# directories removed (under /home/validator/telcoin/):
#   - blobstore
#   - consensus-db
#   - db
#   - static_files
#
# everything else (keys, genesis config, etc.) is preserved.
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

# Remote command to stop container and wipe databases
REMOTE_CMD='
echo "=== Stopping telcoin container ==="
sudo docker stop telcoin 2>/dev/null

# wait for the container to stop
while [ "$(sudo docker inspect -f '"'"'{{.State.Running}}'"'"' telcoin 2>/dev/null)" = "true" ]; do
    sleep 1
done

sudo docker wait telcoin 2>/dev/null
sleep 1
sudo docker rm telcoin 2>/dev/null

echo "=== Wiping database directories ==="
DIRS="blobstore consensus-db db static_files"
for dir in $DIRS; do
    TARGET="/home/validator/telcoin/${dir}"
    if [ -d "$TARGET" ]; then
        sudo rm -rf "$TARGET"
        echo "Deleted: $TARGET"
    else
        echo "Not found (skipped): $TARGET"
    fi
done

echo "=== Remaining contents of /home/validator/telcoin/ ==="
ls -la /home/validator/telcoin/
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
        echo "=== Starting wipe on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        echo "Zone: ${ZONES[$i]}"
        echo ""

        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="${REMOTE_CMD}" 2>&1

        # Capture exit status
        exit_code=$?

        # Log the completion status
        if [ $exit_code -eq 0 ]; then
            echo ""
            echo "=== Wipe completed successfully on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        else
            echo ""
            echo "=== Wipe FAILED on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] with exit code $exit_code at $(date) ==="
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
        echo "❌ Error: wipe failed on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] - See $LOG_FILE for details"
        echo "   Last 10 lines of log:"
        tail -10 "$LOG_FILE" | sed 's/^/   /'
    else
        echo "✅ Successfully wiped databases on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}]"
    fi
done

# Combine all logs for easy review
echo ""
echo "Combining all logs to $OUTPUT_PATH/combined_$timestamp.log"
cat $OUTPUT_PATH/*_$timestamp.log > "$OUTPUT_PATH/combined_$timestamp.log"

# Summary statistics
echo ""
echo "========================================="
echo "Wipe Execution Summary"
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
    echo "⚠️  One or more wipe jobs failed. See logs in $OUTPUT_PATH for details."
    exit 1
else
    echo ""
    echo "🎉 All databases wiped successfully! Run ./update.sh to restart the network."
fi

echo ""
echo "Complete"
