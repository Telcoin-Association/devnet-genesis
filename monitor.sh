#!/bin/bash
#
# this script installs the Google Cloud Ops Agent (metrics + logging collector)
# on all instances in parallel.
#
# on each instance it:
#   1. downloads add-google-cloud-ops-agent-repo.sh from dl.google.com
#   2. runs it with --also-install to add the repo and install the agent
#   3. reports the resulting google-cloud-ops-agent systemd unit status
#
# the install script is idempotent, so re-runs are safe.
#

# load variables
source ./config.sh

# Create logs directory if it doesn't exist
LOGS_DIR="./logs/monitoring"
timestamp=$(date +"%Y%m%d_%H%M%S")
OUTPUT_PATH="${LOGS_DIR}/${timestamp}"
mkdir -p "${OUTPUT_PATH}"

# Array to store process IDs
pids=()
exit_statuses=()

# Remote command to install the Google Cloud Ops Agent
REMOTE_CMD='
set -e
cd /tmp

echo "=== Downloading add-google-cloud-ops-agent-repo.sh ==="
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh

echo "=== Running installer with --also-install ==="
sudo bash add-google-cloud-ops-agent-repo.sh --also-install

echo "=== google-cloud-ops-agent status ==="
sudo systemctl status google-cloud-ops-agent --no-pager || true

echo "=== Done ==="
'

# Loop through each server and launch commands in background
for i in "${!INSTANCE_NAMES[@]}"; do
    # Create log file for this instance
    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"

    NODE_TYPE="VALIDATOR"

    # Log the start time
    echo "Starting ops-agent install on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] (PID: pending...)"

    # Execute install command in background and redirect output to log file
    (
        echo "=== Starting ops-agent install on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        echo "Zone: ${ZONES[$i]}"
        echo ""

        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="${REMOTE_CMD}" 2>&1

        # Capture exit status
        exit_code=$?

        # Log the completion status
        if [ $exit_code -eq 0 ]; then
            echo ""
            echo "=== Install completed successfully on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] at $(date) ==="
        else
            echo ""
            echo "=== Install FAILED on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] with exit code $exit_code at $(date) ==="
        fi

        exit $exit_code
    ) > "$LOG_FILE" 2>&1 &

    # Store the process ID of the background task
    pids+=($!)

    last_index=$((${#pids[@]} - 1))
    echo "Started ops-agent install on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] (PID: ${pids[$last_index]}, Log: $LOG_FILE)"
done

echo ""
echo "All install jobs launched. Waiting for completion..."
echo ""

# Wait for all background processes to complete and capture exit statuses
for i in "${!pids[@]}"; do
    wait ${pids[$i]}
    exit_statuses+=($?)

    NODE_TYPE="VALIDATOR"

    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_$timestamp.log"

    if [ ${exit_statuses[$i]} -ne 0 ]; then
        echo "❌ Error: ops-agent install failed on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}] - See $LOG_FILE for details"
        echo "   Last 10 lines of log:"
        tail -10 "$LOG_FILE" | sed 's/^/   /'
    else
        echo "✅ Successfully installed ops-agent on ${INSTANCE_NAMES[$i]} [${NODE_TYPE}]"
    fi
done

# Combine all logs for easy review
echo ""
echo "Combining all logs to $OUTPUT_PATH/combined_$timestamp.log"
cat $OUTPUT_PATH/*_$timestamp.log > "$OUTPUT_PATH/combined_$timestamp.log"

# Summary statistics
echo ""
echo "========================================="
echo "Ops-Agent Install Summary"
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
    echo "⚠️  One or more install jobs failed. See logs in $OUTPUT_PATH for details."
    exit 1
else
    echo ""
    echo "🎉 Google Cloud Ops Agent installed on all instances."
fi

echo ""
echo "Complete"
