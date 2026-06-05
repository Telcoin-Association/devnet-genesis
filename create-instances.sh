#!/bin/bash
#
# Google Cloud Compute - Parallel Instance Creation
#
# load vars
source ./config.sh

# Warm gcloud's token cache serially. Parallel gcloud invocations race on
# one-time SQLite schema migrations after an SDK update (e.g. "duplicate
# column name: regional_access_boundary"); one serial call completes the
# migration before the parallel jobs start.
gcloud auth print-access-token >/dev/null || { echo "❌ gcloud auth failed — run 'gcloud auth login' and retry"; exit 1; }

# Create logs directory if it doesn't exist
LOGS_DIR="./logs"
timestamp=$(date +"%Y%m%d_%H%M%S")
OUTPUT_PATH="${LOGS_DIR}/instance-creation/${timestamp}"
mkdir -p "${OUTPUT_PATH}"

# Arrays tracking launched background jobs. Indexed together — populated only
# for instances that actually launch (existing instances are skipped), so they
# may be shorter than INSTANCE_NAMES.
pids=()
exit_statuses=()
launched_names=()
launched_logs=()
skipped_count=0

echo "Starting parallel instance creation for ${#INSTANCE_NAMES[@]} instances..."
echo "Logs will be saved to: ${OUTPUT_PATH}"

# Loop through each node and launch instance creation in background
for i in "${!INSTANCE_NAMES[@]}"; do
    # Skip instances that already exist (makes re-runs safe after a partial failure)
    if gcloud compute instances describe "${INSTANCE_NAMES[$i]}" \
        --project="${PROJECT_ID}" --zone="${ZONES[$i]}" \
        --format='value(name)' >/dev/null 2>&1; then
        echo "Instance ${INSTANCE_NAMES[$i]} already exists in ${ZONES[$i]} — skipping."
        ((skipped_count++))
        continue
    fi

    # Create log file for this instance
    LOG_FILE="${OUTPUT_PATH}/${INSTANCE_NAMES[$i]}_creation_${timestamp}.log"

    # IPs are NOT assigned here. GCP hands out an ephemeral external IP + auto
    # internal IP at boot; the node self-discovers them from the metadata
    # service (startup.sh builds external multiaddrs, start-*-node.sh builds
    # listener multiaddrs). Only the ports travel as instance attributes.

    # Launch instance creation in background
    (
        echo "=== Starting instance creation for ${INSTANCE_NAMES[$i]} at $(date) ==="
        echo "Creating instance for ${INSTANCE_NAMES[$i]} in ${ZONES[$i]}"
        echo "  - Role: ${NODE_ROLES[$i]}"
        echo "  - Node Name: ${NODE_NAMES[$i]}"
        echo "  - Zone: ${ZONES[$i]}"
        echo "  - IPs: ephemeral (assigned at boot, self-discovered)"
        echo ""

        # Create the instance
        gcloud beta compute instances create ${INSTANCE_NAMES[$i]}  \
            --project=$PROJECT_ID \
            --zone=${ZONES[$i]} \
            --description="devnet ${NODE_ROLES[$i]} node $((i+1))" \
            --machine-type=$MACHINE_TYPE \
            --network-interface="network-tier=PREMIUM,subnet=default,nic-type=GVNIC,stack-type=IPV4_ONLY" \
            --metadata=EXECUTION_ADDRESS=${EXECUTION_ADDRESSES[$i]},NODE_NAME=${NODE_NAMES[$i]},DOCKER_IMAGE=${DOCKER_IMAGE},PROJECT_ID=${PROJECT_ID},PRIMARY_UDP_PORT=${DEFAULT_PRIMARY_UDP_PORT},WORKER_UDP_PORT=${DEFAULT_WORKER_UDP_PORT},HEALTHCHECK_TCP_PORT=${DEFAULT_HEALTHCHECK_TCP_PORT} \
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

    # Store the process ID and bookkeeping for this launched job
    pids+=($!)
    launched_names+=("${INSTANCE_NAMES[$i]}")
    launched_logs+=("$LOG_FILE")

    # Get the index of the last element
    last_index=$((${#pids[@]} - 1))

    echo "Started creation of ${INSTANCE_NAMES[$i]} (PID: ${pids[$last_index]}, Log: $LOG_FILE)"
done

echo ""
echo "All instance creation jobs launched (${#pids[@]} launched, ${skipped_count} skipped). Waiting for completion..."
echo ""

# Track overall success
overall_success=true

# Wait for all background processes to complete and capture exit statuses
for i in "${!pids[@]}"; do
    wait ${pids[$i]}
    exit_statuses+=($?)

    if [ ${exit_statuses[$i]} -ne 0 ]; then
        echo "❌ Error: Failed to create instance ${launched_names[$i]} - See ${launched_logs[$i]} for details"
        # Show the last few lines of the log to help with immediate troubleshooting
        echo "   Last 10 lines of log:"
        tail -10 "${launched_logs[$i]}" | sed 's/^/   /'
        echo ""
        overall_success=false
    else
        echo "Successfully created instance ${launched_names[$i]}"
    fi
done

echo ""
echo "========================================="
echo "Instance Creation Summary:"
echo "========================================="
echo "Total instances: ${#INSTANCE_NAMES[@]}"
echo "Skipped (already exist): ${skipped_count}"
echo "Launched: ${#pids[@]}"

# Count successes and failures among launched jobs
success_count=0
failed_instances=()
for i in "${!exit_statuses[@]}"; do
    if [ ${exit_statuses[$i]} -eq 0 ]; then
        ((success_count++))
    else
        failed_instances+=("${launched_names[$i]}")
    fi
done

echo "Successful: $success_count"
echo "Failed: $((${#pids[@]} - success_count))"

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

# =========================================
# Assigned external IPs (for manual DNS)
# =========================================
# Query each instance's ephemeral external IP and print a node→IP table so the
# operator can create the A records (node{N}.${BASE_DOMAIN}) by hand before
# running genesis.sh / certbot.
echo ""
echo "========================================="
echo "Assigned external IPs — create these A records:"
echo "========================================="
for i in "${!INSTANCE_NAMES[@]}"; do
    natIP=$(gcloud compute instances describe "${INSTANCE_NAMES[$i]}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONES[$i]}" \
        --format='get(networkInterfaces[0].accessConfigs[0].natIP)' 2>/dev/null)
    if [ -z "${natIP}" ]; then
        natIP="(unavailable — instance may have failed to create)"
    fi
    printf '  %s.%s\t→  %s\n' "${NODE_NAMES[$i]}" "${BASE_DOMAIN}" "${natIP}"
done
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
