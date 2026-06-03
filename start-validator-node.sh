#!/bin/bash
#
# launch the validator node inside a docker container
#
# this is the last script to run after building the
# committee.
#
# this script pulls the latest docker image,
# stops any containers that are already running TN binary,
# then starts the docker container to run the TN binary.
#
# this script is useful for either starting a new network
# OR updating an existing network after deploying a new docker image.
#
# when starting a new network, docker will through non-fatal errors
# that "telcoin" container is not found.

# publicly available testnet image in Google Artifacts Registry
# defined in "genesis.sh" and "update.sh"
echo "using docker image from: ${DOCKER_IMAGE}"

# pull image
sudo docker image pull "${DOCKER_IMAGE}"

# stop the current container
sudo docker stop telcoin

# wait for the container to stop
while [ "$(sudo docker inspect -f '{{.State.Running}}' telcoin)" = "true" ]; do
    sleep 1
done

# wait for telcoin container to stop
sudo docker wait telcoin

# sleep again to make sure - previous two approaches don't ensure
# the container name is available again
sleep 1

# do not use `--rm` in docker run to prevent lost data if the node
# unexpectedly shutsdown
sudo docker rm telcoin

TN_PRIMARY_LISTENER_ADDR=$(curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/TN_PRIMARY_LISTENER_ADDR)
TN_WORKER_LISTENER_ADDR=$(curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/TN_WORKER_LISTENER_ADDR)
HEALTHCHECK_TCP_PORT=$(curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/attributes/HEALTHCHECK_TCP_PORT)

echo "overwriting external config multiaddr to use  primary addr: ${TN_PRIMARY_LISTENER_ADDR}"
echo "overwriting external config multiaddr to use  worker addr: ${TN_WORKER_LISTENER_ADDR}"

# start node:
# primary: 49590
# worker: 49594
# rpc: port 8545
#
# NOTE: node config was created with external address to share with peers
# this overwrites the network's listener to the server's internal IP for GCP
# - PRIMARY_MULTIADDR
# - WORKER_MULTIADDR
sudo docker run -d --name telcoin \
    --network=host \
    -v /home/validator/telcoin:/code \
    --workdir /code \
    -e TN_BLS_PASSPHRASE="turtle" \
    -e PRIMARY_LISTENER_MULTIADDR="${TN_PRIMARY_LISTENER_ADDR}" \
    -e WORKER_LISTENER_MULTIADDR="${TN_WORKER_LISTENER_ADDR}" \
    -e HEALTHCHECK_TCP_PORT="${HEALTHCHECK_TCP_PORT}" \
    ${DOCKER_IMAGE} /usr/local/bin/telcoin node \
    --datadir . \
    --http \
    --http.addr 0.0.0.0 \
    --http.port 8545 \
    --ws \
    --ws.addr 0.0.0.0 \
    --ws.port 8546

# Check for exit status of previous command
if [ $? -eq 1 ]; then
    echo "Error: docker run node command failed."
    exit 1
fi

echo "docker run okay"
