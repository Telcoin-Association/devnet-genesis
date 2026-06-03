#!/bin/bash
#
# this script launches commands on all instances sequentially with a 10s pause
# between nodes so a BFT network stays above quorum during a rolling update
#
# load variables
source ./config.sh

# Create logs directory if it doesn't exist
LOGS_DIR="./logs"
timestamp=$(date +"%Y%m%d_%H%M%S")
OUTPUT_PATH="${LOGS_DIR}/${timestamp}"
mkdir -p "${OUTPUT_PATH}"

# Array to store exit statuses
exit_statuses=()

last_idx=$((${#INSTANCE_NAMES[@]} - 1))

# Loop through each server and run sequentially
for i in "${!INSTANCE_NAMES[@]}"; do
    # Create log file for this instance
    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"

    UPDATE_SCRIPT_PATH="${START_VALIDATOR_NODE_SCRIPT}"
    NODE_TYPE="VALIDATOR"

    # Log the start time, instance type, and script being used
    echo "Starting job on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] using script: ${UPDATE_SCRIPT_PATH}"

    # Execute relaunch script in foreground and redirect output to log file
    (
        echo "=== Starting job on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        echo "Using script: ${UPDATE_SCRIPT_PATH}"
        echo "Zone: ${ZONES[$i]}"
        echo ""

        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="export DOCKER_IMAGE=${DOCKER_IMAGE}; bash -s" < "${UPDATE_SCRIPT_PATH}" 2>&1
        exit_code=$?

        if [ $exit_code -eq 0 ]; then
            echo ""
            echo "=== Job completed successfully on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        else
            echo ""
            echo "=== Job FAILED on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] with exit code $exit_code at $(date) ==="
        fi

        exit $exit_code
    ) > "$LOG_FILE" 2>&1
    status=$?
    exit_statuses+=($status)

    if [ $status -ne 0 ]; then
        echo "❌ Error: relaunch failed on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] - See $LOG_FILE for details"
        echo "   Last 10 lines of log:"
        tail -10 "$LOG_FILE" | sed 's/^/   /'
    else
        echo "✅ Successfully completed job on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] (Log: $LOG_FILE)"
    fi

    # Pause between validators to keep the network above quorum
    if [ $i -lt $last_idx ]; then
        echo "Sleeping 10s before next validator..."
        sleep 10
    fi
done

# Combine all logs for easy review
echo ""
echo "Combining all logs to $OUTPUT_PATH/combined_$timestamp.log"
cat $OUTPUT_PATH/*_$timestamp.log > "$OUTPUT_PATH/combined_$timestamp.log"

# Summary statistics
echo ""
echo "========================================="
echo "Job Execution Summary"
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
if [ ${#failed_instances[@]} -gt 0 ]; then
    echo ""
    echo "⚠️  One or more jobs failed. See logs in $OUTPUT_PATH for details."
    exit 1
else
    echo ""
    echo "🎉 All jobs completed successfully!"
fi

echo ""
echo "Complete"
