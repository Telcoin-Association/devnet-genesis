#!/bin/bash
#
# This script pulls from remote hosts, creates the committee,
# and transfers the committee back to remote hosts in parallel.
#
# NOTE: Must assign External IP addresses first!
#
# Then, it starts the network.
#
# use global vars
source ./config.sh

# Observer node-info is pulled here, NOT into genesis/validators/. `telcoin
# genesis` builds the committee from EVERY file in genesis/validators/, so the
# observer's key must be kept out of that dir to keep the committee at 4. Kept
# aside so it can later be staked into a future committee via ConsensusRegistry.
OBSERVER_LOCAL_PATH="./genesis/observers/"

# Create logs directory if it doesn't exist
LOGS_DIR="./logs"
timestamp=$(date +"%Y%m%d_%H%M%S")
OUTPUT_PATH="${LOGS_DIR}/genesis-deployment/${timestamp}"
mkdir -p "${OUTPUT_PATH}"

echo "Starting genesis and deployment process..."
echo "Logs will be saved to: ${OUTPUT_PATH}"

# =========================================
# PHASE 1: Pull files from remote hosts
# =========================================
echo ""
echo "========================================="
echo "PHASE 1: Pulling validator files from remote hosts"
echo "========================================="

# Prepare local dirs. Validators' node-info land in genesis/validators/ (the
# committee source); the observer's lands in genesis/observers/.
for d in "${GENESISDIR}" "${OBSERVER_LOCAL_PATH}"; do
    if [ ! -d "${d}" ]; then
        echo "creating dir: ${d}"
        mkdir -p "${d}"
    else
        echo "${d} already present"
    fi
done

# set permissions for docker container
chmod -R 777 $(dirname ${GENESISDIR})

# Arrays for parallel pulling. pull_instances tracks which instance each pid
# belongs to so the wait loop can report correctly even though only a subset
# of instances may be pulled into each dir.
pull_pids=()
pull_instances=()
pull_exit_statuses=()

# Pull node-info from each server, routed by role:
#   validator → genesis/validators/ (committee is built from this dir)
#   observer  → genesis/observers/  (kept out of the committee)
for i in "${!INSTANCE_NAMES[@]}"; do
    instance="${INSTANCE_NAMES[$i]}"
    role="${NODE_ROLES[$i]}"

    if [ "${role}" = "observer" ]; then
        dest="${OBSERVER_LOCAL_PATH}"
    else
        dest="${LOCAL_PATH}"
    fi

    LOG_FILE="${OUTPUT_PATH}/pull_${instance}_${timestamp}.log"

    # Pull files in background (optional parallelization)
    (
        echo "=== Pulling files from ${instance} [${role}] at $(date) ==="
        echo "Zone: ${ZONES[$i]}"
        echo "Dest: ${dest}"

        # Retry transient failures: parallel first-time SSH connections race on
        # gcloud's key-propagation metadata update, and the loser can hit
        # "Permission denied (publickey)" (exit 255) until the key lands.
        max_attempts=3
        for attempt in $(seq 1 $max_attempts); do
            gcloud compute scp "${instance}:${REMOTE_VALIDATORS_PATH}/*" "${dest}" --zone "${ZONES[$i]}" 2>&1
            exit_code=$?
            [ $exit_code -eq 0 ] && break
            if [ $attempt -lt $max_attempts ]; then
                echo "Attempt ${attempt}/${max_attempts} failed (exit ${exit_code}); retrying in 10s..."
                sleep 10
            fi
        done

        if [ $exit_code -eq 0 ]; then
            echo "=== Successfully pulled files from ${instance} at $(date) ==="
        else
            echo "=== FAILED to pull files from ${instance} with exit code $exit_code at $(date) ==="
        fi
        exit $exit_code
    ) > "$LOG_FILE" 2>&1 &

    pull_pids+=($!)
    pull_instances+=("${instance}")
    echo "Started pulling from ${instance} [${role}] → ${dest} (PID: ${pull_pids[-1]})"
done

# Wait for all pulls to complete
echo "Waiting for all file pulls to complete..."
pull_failed=false
for i in "${!pull_pids[@]}"; do
    wait ${pull_pids[$i]}
    exit_status=$?
    pull_exit_statuses+=($exit_status)

    if [ $exit_status -ne 0 ]; then
        echo "❌ Failed to pull from ${pull_instances[$i]}"
        pull_failed=true
    else
        echo "Successfully pulled from ${pull_instances[$i]}"
    fi
done

if [ "$pull_failed" = true ]; then
    echo "Error: Failed to pull validator files. Check logs in ${OUTPUT_PATH}"
    exit 1
fi

echo "Successfully pulled all validator information from servers"

# =========================================
# PHASE 2: Create committee (sequential)
# =========================================
echo ""
echo "========================================="
echo "PHASE 2: Creating committee and genesis"
echo "========================================="

COMMITTEE_LOG="${OUTPUT_PATH}/committee_creation_${timestamp}.log"

(
    echo "=== Starting committee creation at $(date) ==="
    echo "Using Docker image: ${DOCKER_IMAGE}"
    echo ""

    # 1hr epochs so the observer can be tested rotating into the committee fast.
    # --platform linux/amd64: the image is amd64; pin it for Apple-silicon hosts.
    # Committee = 4 (only the 4 validators' node-info are in genesis/validators/).
    docker run --platform linux/amd64 -v ./:/code --workdir /code ${DOCKER_IMAGE} \
        /usr/local/bin/telcoin genesis \
        --datadir ./ \
        --bls-passphrase-source stdin \
        --accounts /code/testnet_accounts.yaml \
        --epoch-duration-in-secs 3600 \
        --min-header-delay-ms 1000 \
        --max-header-delay-ms 3000 2>&1

    exit_code=$?
    if [ $exit_code -eq 0 ]; then
        echo ""
        echo "=== Committee created successfully at $(date) ==="
    else
        echo ""
        echo "=== FAILED to create committee with exit code $exit_code at $(date) ==="
    fi
    exit $exit_code
) > "$COMMITTEE_LOG" 2>&1

if [ $? -ne 0 ]; then
    echo "❌ Error: Failed to create committee"
    echo "Check log: $COMMITTEE_LOG"
    tail -20 "$COMMITTEE_LOG"
    exit 1
fi

echo "Successfully created committee and genesis files"

# =========================================
# PHASE 3: Deploy to remote hosts (parallel)
# =========================================
echo ""
echo "========================================="
echo "PHASE 3: Deploying to remote hosts in parallel"
echo "========================================="

# Ensure the local directory exists
if [ ! -d "${GENESISDIR}" ]; then
    echo "Local directory ${GENESISDIR} does not exist."
    exit 1
else
    echo "Local directory ${GENESISDIR} present, proceeding with deployment..."
fi

# Arrays to store process IDs for deployment
deploy_pids=()
deploy_exit_statuses=()

# Loop through each server and deploy in background
for i in "${!INSTANCE_NAMES[@]}"; do
    LOG_FILE="${OUTPUT_PATH}/deploy_${INSTANCE_NAMES[$i]}_${timestamp}.log"

    role="${NODE_ROLES[$i]}"
    NODE_TYPE=$(echo "${role}" | tr '[:lower:]' '[:upper:]')
    # Pick the start script by role. All 5 receive genesis/committee/parameters
    # (the observer needs them to sync); only the start command differs.
    if [ "${role}" = "observer" ]; then
        START_SCRIPT="${START_OBSERVER_NODE_SCRIPT}"
    else
        START_SCRIPT="${START_VALIDATOR_NODE_SCRIPT}"
    fi

    # Deploy to instance in background
    (
        echo "=== Starting deployment to ${INSTANCE_NAMES[$i]} ($NODE_TYPE) at $(date) ==="
        echo "Zone: ${ZONES[$i]}"
        echo ""

        # Copy genesis file
        echo "Copying genesis file..."
        gcloud compute scp "${GENESIS_FILE}" "${INSTANCE_NAMES[$i]}:${REMOTE_SHARE_PATH}" --zone "${ZONES[$i]}" 2>&1
        if [ $? -ne 0 ]; then
            echo "Failed to copy genesis file"
            exit 1
        fi
        echo "Genesis file copied"

        # Copy parameters file
        echo "Copying parameters file..."
        gcloud compute scp "${PARAMETERS_FILE}" "${INSTANCE_NAMES[$i]}:${REMOTE_SHARE_PATH}" --zone "${ZONES[$i]}" 2>&1
        if [ $? -ne 0 ]; then
            echo "Failed to copy parameters file"
            exit 1
        fi
        echo "Parameters file copied"

        # Copy committee file
        echo "Copying committee file..."
        gcloud compute scp "${COMMITTEE_FILE}" "${INSTANCE_NAMES[$i]}:${REMOTE_SHARE_PATH}" --zone "${ZONES[$i]}" 2>&1
        if [ $? -ne 0 ]; then
            echo "Failed to copy committee file"
            exit 1
        fi
        echo "Committee file copied"

        # Upload committee script
        echo "Executing upload committee script..."
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="export DOCKER_IMAGE='${DOCKER_IMAGE}'; bash -s" < "${UPLOAD_COMMITTEE_SCRIPT}" 2>&1
        if [ $? -ne 0 ]; then
            echo "Failed to execute upload committee script"
            exit 1
        fi
        echo "Upload committee script executed"

        # Start node (validator or observer per role)
        echo "Starting ${NODE_TYPE} node..."
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="export DOCKER_IMAGE='${DOCKER_IMAGE}'; bash -s" < "${START_SCRIPT}" 2>&1

        if [ $? -ne 0 ]; then
            echo "Failed to start node"
            exit 1
        fi
        echo "Node started"

        # Configure Apache + certbot. NON-FATAL: certbot's HTTP-01 challenge
        # fails until the operator points node{N}.${BASE_DOMAIN} at this IP, so
        # a failure here is expected on first deploy. Run ./dns.sh to finalize
        # certs once DNS resolves.
        echo "Configuring Apache server..."
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="export BASE_DOMAIN='${BASE_DOMAIN}' LETSENCRYPT_EMAIL='${LETSENCRYPT_EMAIL}'; bash -s" < "${CONFIG_APACHE_SCRIPT}" 2>&1
        if [ $? -ne 0 ]; then
            echo "WARNING: Apache/certbot did not complete (DNS may not resolve yet). Continuing; run ./dns.sh after DNS is set."
        else
            echo "Apache configured"
        fi

        echo ""
        echo "=== Deployment to ${INSTANCE_NAMES[$i]} ($NODE_TYPE) completed successfully at $(date) ==="
        exit 0
    ) > "$LOG_FILE" 2>&1 &

    # Store the process ID
    deploy_pids+=($!)

    echo "Started deployment to ${INSTANCE_NAMES[$i]} [$NODE_TYPE] (PID: ${deploy_pids[-1]})"
done

echo ""
echo "All deployment jobs launched. Waiting for completion..."
echo ""

# Track overall deployment success
deployment_success=true

# Wait for all deployment processes to complete
for i in "${!deploy_pids[@]}"; do
    wait ${deploy_pids[$i]}
    exit_status=$?
    deploy_exit_statuses+=($exit_status)

    NODE_TYPE=$(echo "${NODE_ROLES[$i]}" | tr '[:lower:]' '[:upper:]')

    LOG_FILE="${OUTPUT_PATH}/deploy_${INSTANCE_NAMES[$i]}_${timestamp}.log"

    if [ $exit_status -ne 0 ]; then
        echo "❌ Failed to deploy to ${INSTANCE_NAMES[$i]} [$NODE_TYPE] - See $LOG_FILE"
        echo "   Last 15 lines of log:"
        tail -15 "$LOG_FILE" | sed 's/^/   /'
        echo ""
        deployment_success=false
    else
        echo "Successfully deployed to ${INSTANCE_NAMES[$i]} [$NODE_TYPE]"
    fi
done

# =========================================
# SUMMARY
# =========================================
echo ""
echo "========================================="
echo "Deployment Summary"
echo "========================================="
echo "Total instances: ${#INSTANCE_NAMES[@]}"

# Count successes and failures
success_count=0
failed_deployments=()
for i in "${!deploy_exit_statuses[@]}"; do
    if [ ${deploy_exit_statuses[$i]} -eq 0 ]; then
        ((success_count++))
    else
        failed_deployments+=("${INSTANCE_NAMES[$i]}")
    fi
done

echo "Successful deployments: $success_count"
echo "Failed deployments: $((${#INSTANCE_NAMES[@]} - success_count))"

if [ ${#failed_deployments[@]} -gt 0 ]; then
    echo ""
    echo "Failed instances:"
    for instance in "${failed_deployments[@]}"; do
        echo "  - $instance"
    done
fi

validator_count=0
observer_count=0
for role in "${NODE_ROLES[@]}"; do
    if [ "${role}" = "observer" ]; then
        ((observer_count++))
    else
        ((validator_count++))
    fi
done

echo ""
echo "Node types deployed:"
echo "  - Validators: $validator_count"
echo "  - Observers:  $observer_count"

echo ""
echo "Logs saved to: ${OUTPUT_PATH}"
echo "========================================="

# Final status
if [ "$deployment_success" = false ]; then
    echo ""
    echo "Some deployments failed. Please check the logs for details."
    exit 1
else
    echo ""
    echo "Genesis complete - network should be running!"
    echo ""
    echo "You can check the status of nodes with:"
    echo "  ./download-logs.sh"
fi
