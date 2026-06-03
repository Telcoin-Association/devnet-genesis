#!/bin/bash
#
# this script launches commands on all instances in parallel and captures logs
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

# Loop through each server and launch commands in background
for i in "${!INSTANCE_NAMES[@]}"; do
    # Create log file for this instance
    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"

    UPDATE_SCRIPT_PATH="${START_VALIDATOR_NODE_SCRIPT}"
    NODE_TYPE="VALIDATOR"

    # Log the start time, instance type, and script being used
    echo "Starting job on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] using script: ${UPDATE_SCRIPT_PATH} (PID: pending...)"

    # Execute relaunch script in background and redirect output to log file
    (
        echo "=== Starting job on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        echo "Using script: ${UPDATE_SCRIPT_PATH}"
        echo "Zone: ${ZONES[$i]}"
        echo ""

        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="export DOCKER_IMAGE=${DOCKER_IMAGE}; bash -s" < "${UPDATE_SCRIPT_PATH}" 2>&1

        # Capture exit status
        exit_code=$?

        # Log the completion status
        if [ $exit_code -eq 0 ]; then
            echo ""
            echo "=== Job completed successfully on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        else
            echo ""
            echo "=== Job FAILED on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] with exit code $exit_code at $(date) ==="
        fi

        # Return the exit code so the parent process can capture it
        exit $exit_code
    ) > "$LOG_FILE" 2>&1 &

    # Store the process ID of the background task
    pids+=($!)

    # Get the index of the last element
    last_index=$((${#pids[@]} - 1))

    echo "Started job on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] (PID: ${pids[$last_index]}, Log: $LOG_FILE)"
done

echo ""
echo "All jobs launched. Waiting for completion..."
echo ""

# Wait for all background processes to complete and capture exit statuses
for i in "${!pids[@]}"; do
    wait ${pids[$i]}
    exit_statuses+=($?)

    NODE_TYPE="VALIDATOR"

    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"

    if [ ${exit_statuses[$i]} -ne 0 ]; then
        echo "❌ Error: relaunch failed on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] - See $LOG_FILE for details"
        # Show the last few lines of the log to help with immediate troubleshooting
        echo "   Last 10 lines of log:"
        tail -10 "$LOG_FILE" | sed 's/^/   /'
    else
        echo "✅ Successfully completed job on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}]"
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

    # Count successes/failures
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
    echo "⚠️  One or more jobs failed. See logs in $OUTPUT_PATH for details."
    exit 1
else
    echo ""
    echo "🎉 All jobs completed successfully!"
fi

echo ""
echo "Complete"
