#!/bin/bash
#
# this script launches commands on all instances in parallel and captures logs
#
# load variables
source ./config.sh

# Create logs directory if it doesn't exist
LOGS_DIR="./logs"
timestamp=$(date +"%Y%m%d_%H%M%S")
SUFFIX="${1:+-$1}"
OUTPUT_PATH="${LOGS_DIR}/docker/${timestamp}${SUFFIX}"
mkdir -p "${OUTPUT_PATH}"

# Array to store process IDs
pids=()
exit_statuses=()

# Loop through each server and launch commands in background
for i in "${!INSTANCE_NAMES[@]}"; do
    # Create log file for this instance
    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"
    INSTANCE_LOG="${INSTANCE_NAMES[$i]}-docker-logs-${timestamp}.log"
    CLEANED_LOG="${INSTANCE_NAMES[$i]}-clean.log"

    # Log the start time and command
    echo "Connecting to ${INSTANCE_NAMES[$i]} to collect Docker logs..."

    # Execute relaunch script in background and redirect output to log file
    (
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="sudo docker logs telcoin > /tmp/${INSTANCE_LOG} 2>&1" 2>&1

        # Check if the command succeeded
        if [ $? -ne 0 ]; then
            echo "Failed to connect to ${INSTANCE_NAMES[$i]} or collect Docker logs"
            exit 1
        fi


        echo "Logs collected on remote server. Copying back to local machine..."

        # Copy the log file from the remote server to local machine
        gcloud compute scp "${INSTANCE_NAMES[$i]}:/tmp/${INSTANCE_LOG}" "${OUTPUT_PATH}/" --zone="${ZONES[$i]}" 2>&1

        # Capture exit status
        exit_code=$?

        # Clean up the remote file
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="rm /tmp/${INSTANCE_LOG}" 2>/dev/null


        # Clean up ANSI escape sequences if the file was successfully copied
        if [ $exit_code -eq 0 ]; then
            echo "Cleaning up ANSI escape codes from log file..."
            # Use sed to remove ANSI escape sequences
            if sed -r "s/\x1B\[([0-9]{1,3}(;[0-9]{1,3})*)?[mGK]//g" "${OUTPUT_PATH}/${INSTANCE_LOG}" > "${OUTPUT_PATH}/${CLEANED_LOG}" \
                && [ -s "${OUTPUT_PATH}/${CLEANED_LOG}" ]; then
                echo "Created cleaned log file: ${CLEANED_LOG}"
                rm "${OUTPUT_PATH}/${INSTANCE_LOG}"
            else
                echo "Failed to clean log file; keeping raw log ${INSTANCE_LOG} for inspection"
            fi
        fi

        # Log the completion status
        if [ $exit_code -eq 0 ]; then
            echo "=== Job completed successfully on ${INSTANCE_NAMES[$i]} at $(date) ===" >> "$LOG_FILE"
        else
            echo "=== Job FAILED on ${INSTANCE_NAMES[$i]} with exit code $exit_code at $(date) ===" >> "$LOG_FILE"
        fi

        # Return the exit code so the parent process can capture it
        exit $exit_code
    ) > "$LOG_FILE" 2>&1 &

    # Store the process ID of the background task
    pids+=($!)

    # Get the index of the last element
    last_index=$((${#pids[@]} - 1))

    echo "Started job on ${INSTANCE_NAMES[$i]} (PID: ${pids[$last_index]}, Log: $LOG_FILE)"
done

# Wait for all background processes to complete and capture exit statuses
for i in "${!pids[@]}"; do
    wait ${pids[$i]}
    exit_statuses+=($?)

    LOG_FILE="${OUTPUT_PATH}/script_${INSTANCE_NAMES[$i]}_$timestamp.log"

    if [ ${exit_statuses[$i]} -ne 0 ]; then
        echo "Error: relaunch failed on ${INSTANCE_NAMES[$i]} - See $LOG_FILE for details"
        # Show the last few lines of the log to help with immediate troubleshooting
        echo "Last 10 lines of log:"
        tail -10 "$LOG_FILE"
    else
        echo "Successfully completed job on ${INSTANCE_NAMES[$i]}"
    fi
done

echo "Complete"
