#!/bin/bash
#
# Google Cloud Compute - Parallel Instance Creation
#
# load vars
source ./config.sh

# Create logs directory if it doesn't exist
LOGS_DIR="./logs"
timestamp=$(date +"%Y%m%d_%H%M%S")
OUTPUT_PATH="${LOGS_DIR}/instance-creation/${timestamp}"
mkdir -p "${OUTPUT_PATH}"

# Array to store process IDs
pids=()
exit_statuses=()

echo "Starting parallel instance creation for ${#INSTANCE_NAMES[@]} instances..."
echo "Logs will be saved to: ${OUTPUT_PATH}"

# Loop through each node and launch instance creation in background
for i in "${!INSTANCE_NAMES[@]}"; do
    # Create log file for this instance
    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_creation_${timestamp}.log"

    # Prepare instance-specific variables
    TN_PRIMARY_LISTENER_ADDR="/ip4/${INTERNAL_IPS[$i]}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
    TN_PRIMARY_EXTERNAL_ADDR="/ip4/${EXTERNAL_IPS[$i]}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
    TN_WORKER_LISTENER_ADDR="/ip4/${INTERNAL_IPS[$i]}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
    TN_WORKER_EXTERNAL_ADDR="/ip4/${EXTERNAL_IPS[$i]}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"

    # Launch instance creation in background
    (
        echo "=== Starting instance creation for ${INSTANCE_NAMES[$i]} at $(date) ==="
        echo "Creating instance for ${INSTANCE_NAMES[$i]} in ${ZONES[$i]}"
        echo "  - External IP: ${EXTERNAL_IPS[$i]}"
        echo "  - Internal IP: ${INTERNAL_IPS[$i]}"
        echo "  - Node Name: ${NODE_NAMES[$i]}"
        echo "  - Zone: ${ZONES[$i]}"
        echo ""

        # Create the instance
        gcloud beta compute instances create ${INSTANCE_NAMES[$i]}  \
            --project=$PROJECT_ID \
            --zone=${ZONES[$i]} \
            --description="devnet validator node ${i+1}" \
            --machine-type=$MACHINE_TYPE \
            --network-interface="address=${EXTERNAL_IPS[$i]},private-network-ip=${INTERNAL_IPS[$i]},network-tier=PREMIUM,subnet=default,nic-type=GVNIC,stack-type=IPV4_ONLY" \
            --metadata=EXECUTION_ADDRESS=${EXECUTION_ADDRESSES[$i]},NODE_NAME=${NODE_NAMES[$i]},DOCKER_IMAGE=${DOCKER_IMAGE},PROJECT_ID=${PROJECT_ID},TN_PRIMARY_LISTENER_ADDR=${TN_PRIMARY_LISTENER_ADDR},TN_WORKER_LISTENER_ADDR=${TN_WORKER_LISTENER_ADDR},TN_PRIMARY_EXTERNAL_ADDR=${TN_PRIMARY_EXTERNAL_ADDR},TN_WORKER_EXTERNAL_ADDR=${TN_WORKER_EXTERNAL_ADDR},HEALTHCHECK_TCP_PORT=${DEFAULT_HEALTHCHECK_TCP_PORT} \
            --metadata-from-file=startup-script=$STARTUP_SCRIPT_PATH \
            --maintenance-policy=MIGRATE \
            --provisioning-model=STANDARD \
            --service-account=$SERVICE_ACCOUNT \
            --scopes=https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write,https://www.googleapis.com/auth/service.management.readonly,https://www.googleapis.com/auth/servicecontrol,https://www.googleapis.com/auth/trace.append \
            --tags=validator,http-server,https-server,lb-health-check \
            --create-disk=auto-delete=yes,boot=yes,device-name=${INSTANCE_NAMES[$i]},image=${IMAGE},mode=rw,size=100,type=pd-ssd \
            --no-shielded-secure-boot \
            --shielded-vtpm \
            --shielded-integrity-monitoring \
            --reservation-affinity=any 2>&1

        # Capture exit status
        exit_code=$?

        # Log the completion status
        if [ $exit_code -eq 0 ]; then
            echo ""
            echo "=== Instance ${INSTANCE_NAMES[$i]} created successfully at $(date) ==="
        else
            echo ""
            echo "=== FAILED to create instance ${INSTANCE_NAMES[$i]} with exit code $exit_code at $(date) ==="
        fi

        # Return the exit code so the parent process can capture it
        exit $exit_code
    ) > "$LOG_FILE" 2>&1 &

    # Store the process ID of the background task
    pids+=($!)

    # Get the index of the last element
    last_index=$((${#pids[@]} - 1))

    echo "Started creation of ${INSTANCE_NAMES[$i]} (PID: ${pids[$last_index]}, Log: $LOG_FILE)"
done

echo ""
echo "All instance creation jobs launched. Waiting for completion..."
echo ""

# Track overall success
overall_success=true

# Wait for all background processes to complete and capture exit statuses
for i in "${!pids[@]}"; do
    wait ${pids[$i]}
    exit_statuses+=($?)

    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_creation_${timestamp}.log"

    if [ ${exit_statuses[$i]} -ne 0 ]; then
        echo "❌ Error: Failed to create instance ${INSTANCE_NAMES[$i]} - See $LOG_FILE for details"
        # Show the last few lines of the log to help with immediate troubleshooting
        echo "   Last 10 lines of log:"
        tail -10 "$LOG_FILE" | sed 's/^/   /'
        echo ""
        overall_success=false
    else
        echo "Successfully created instance ${INSTANCE_NAMES[$i]}"
    fi
done

echo ""
echo "========================================="
echo "Instance Creation Summary:"
echo "========================================="
echo "Total instances: ${#INSTANCE_NAMES[@]}"

# Count successes and failures
success_count=0
failed_instances=()
for i in "${!exit_statuses[@]}"; do
    if [ ${exit_statuses[$i]} -eq 0 ]; then
        ((success_count++))
    else
        failed_instances+=("${INSTANCE_NAMES[$i]}")
    fi
done

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
echo "Logs saved to: ${OUTPUT_PATH}"
echo "========================================="

# Exit with error if any instance failed
if [ "$overall_success" = false ]; then
    echo ""
    echo "Some instances failed to create. Please check the logs for details."
    exit 1
else
    echo ""
    echo "All instances created successfully!"
fi
