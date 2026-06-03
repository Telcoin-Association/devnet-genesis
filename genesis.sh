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

# move public information to shared folder
if [ ! -d "${GENESISDIR}" ]; then
    echo "creating share dir: ${GENESISDIR}"
    mkdir -p ${GENESISDIR}
else
    echo "${GENESISDIR} already present"
fi

# set permissions for docker container
chmod -R 777 $(dirname ${GENESISDIR})

# Arrays for parallel pulling (optional - you could parallelize this too)
pull_pids=()
pull_exit_statuses=()

# Loop through each server and pull validator files
for i in "${!VALIDATOR_NAMES[@]}"; do
    LOG_FILE="${OUTPUT_PATH}/pull_${VALIDATOR_NAMES[$i]}_${timestamp}.log"

    # Pull files in background (optional parallelization)
    (
        echo "=== Pulling files from ${VALIDATOR_NAMES[$i]} at $(date) ==="
        echo "Zone: ${ZONES[$i]}"

        gcloud compute scp "${VALIDATOR_NAMES[$i]}:${REMOTE_VALIDATORS_PATH}/*" "${LOCAL_PATH}" --zone "${ZONES[$i]}" 2>&1

        exit_code=$?
        if [ $exit_code -eq 0 ]; then
            echo "=== Successfully pulled files from ${VALIDATOR_NAMES[$i]} at $(date) ==="
        else
            echo "=== FAILED to pull files from ${VALIDATOR_NAMES[$i]} with exit code $exit_code at $(date) ==="
        fi
        exit $exit_code
    ) > "$LOG_FILE" 2>&1 &

    pull_pids+=($!)
    echo "Started pulling from ${VALIDATOR_NAMES[$i]} (PID: ${pull_pids[-1]})"
done

# Wait for all pulls to complete
echo "Waiting for all file pulls to complete..."
pull_failed=false
for i in "${!pull_pids[@]}"; do
    wait ${pull_pids[$i]}
    exit_status=$?
    pull_exit_statuses+=($exit_status)

    if [ $exit_status -ne 0 ]; then
        echo "❌ Failed to pull from ${VALIDATOR_NAMES[$i]}"
        pull_failed=true
    else
        echo "Successfully pulled from ${VALIDATOR_NAMES[$i]}"
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

    # NOTE: this is 6hr epochs
    docker run -v ./:/code --workdir /code ${DOCKER_IMAGE} \
        /usr/local/bin/telcoin genesis \
        --datadir ./ \
        --bls-passphrase-source stdin \
        --accounts /code/testnet_accounts.yaml \
        --epoch-duration-in-secs 21600 \
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

    NODE_TYPE="VALIDATOR"

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

        # Start validator node
        echo "Starting VALIDATOR node..."
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="export DOCKER_IMAGE='${DOCKER_IMAGE}'; bash -s" < "${START_VALIDATOR_NODE_SCRIPT}" 2>&1

        if [ $? -ne 0 ]; then
            echo "Failed to start node"
            exit 1
        fi
        echo "Node started"

        # Configure Apache
        echo "Configuring Apache server..."
        gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" \
            --command="bash -s" < "${CONFIG_APACHE_SCRIPT}" 2>&1
        if [ $? -ne 0 ]; then
            echo "Failed to configure Apache"
            exit 1
        fi
        echo "Apache configured"

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

    NODE_TYPE="VALIDATOR"

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

validator_count=${#INSTANCE_NAMES[@]}

echo ""
echo "Node types deployed:"
echo "  - Validators: $validator_count"

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
