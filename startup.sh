#!/bin/bash
#
# Google Cloud Compute
#
# os: Debian 11
#
# this script is used in the instance template under `startup script` section
# to install docker, pull the latest telcoin-protocol image, create a validator
# user with permissions on the host, and create the validator keys / config.
#
# Update the system and install dependencies
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg jq apache2 -y
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository to Apt sources:
echo "adding gpg key for docker"
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install Docker Engine
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

# pull protocol image
sudo docker pull ${DOCKER_IMAGE}:latest

# Set permissions for container
#
# The UID/GID should match the docker container's `nonroot` user
USERNAME=validator

# TODO: should these be between 5000-60000
USER_UID=1101
USER_GID=1101
HOME_DIR="/home/${USERNAME}"

# Create a group with GID=1101 if it doesn't exist
if ! getent group $USER_GID &>/dev/null; then
    echo "Creating group '${USERNAME}' with GID: $USER_GID"
    sudo groupadd -g ${USER_GID} ${USERNAME}
fi

# Create a user with UID=1101 and GID=1101 if it doesn't exist
if ! id -u ${USERNAME} &>/dev/null; then
    echo "Creating user '${USERNAME}' with UID: $USER_UID"
    sudo useradd -m -d ${HOME_DIR} -s /bin/bash -u ${USER_UID} -g ${USER_GID} ${USERNAME}
else
    echo "User '${USERNAME}' already exists"
fi

# Fetch NODE_NAME and DOCKER_IMAGE from metadata
NODE_NAME=$(curl -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/NODE_NAME")
DOCKER_IMAGE=$(curl -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/DOCKER_IMAGE")
export TN_BLS_PASSPHRASE="turtle"

# Set both the VM's internal hostname and the HOSTNAME environment variable
HOSTNAME="${NODE_NAME}"
sudo hostnamectl set-hostname "${HOSTNAME}"

# Add to /etc/environment so other scripts can use it
echo "HOSTNAME=${HOSTNAME}" | sudo tee -a /etc/environment
echo "DOCKER_IMAGE=${DOCKER_IMAGE}" | sudo tee -a /etc/environment

# Ensure the hostname is in /etc/hosts
grep -q "${HOSTNAME}" /etc/hosts || echo "127.0.1.1 ${HOSTNAME} ${HOSTNAME}.devnet.telcoin.network" | sudo tee -a /etc/hosts

# The rest of your existing startup script follows...

DATADIR="${HOME_DIR}/telcoin"
SHAREDIR="/home/share"

# create datadir if it doesn't exist
echo "checking for datadir..."
if [ ! -d "${DATADIR}" ]; then
    echo "creating datadir: ${DATADIR}"
    sudo mkdir $DATADIR
    # TODO: remove .env approach
    touch ${DATADIR}/.env
    # ensure file permissions match for container
    sudo chown -R ${USERNAME}:${USERNAME} ${DATADIR}
else
    echo "${DATADIR} already present"
fi

# for some reason this isn't working
# Wait for Docker to be ready
echo "Waiting for Docker to start..."
until sudo docker info >/dev/null 2>&1; do
    echo "docker info unavailable. sleeping..."
    sleep 1
done
echo "Docker is now ready."

# Fetch custom metadata 'EXECUTION_ADDRESS'
EXECUTION_ADDRESS=$(curl -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/EXECUTION_ADDRESS")

# Self-discover this instance's assigned external IP from the metadata service.
# GCP hands out an ephemeral external IP at boot; retry briefly in case the
# network-interface metadata is not yet populated when startup.sh runs.
EXTERNAL_IP=""
for attempt in $(seq 1 10); do
    EXTERNAL_IP=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip")
    if [ -n "${EXTERNAL_IP}" ]; then
        break
    fi
    echo "external IP not yet available (attempt ${attempt}/10); sleeping..."
    sleep 2
done

if [ -z "${EXTERNAL_IP}" ]; then
    echo "ERROR: could not determine external IP from metadata service — aborting keygen" >&2
    exit 1
fi
echo "discovered external IP: ${EXTERNAL_IP}"

# UDP ports travel as instance attributes (set in create-instances.sh)
PRIMARY_UDP_PORT=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/PRIMARY_UDP_PORT")
WORKER_UDP_PORT=$(curl -s -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/attributes/WORKER_UDP_PORT")

# Build the external (peer-facing) multiaddrs baked into node-info.yaml. These
# are advertised to the committee; the listener addrs (internal IP) are derived
# live at start time by start-*-node.sh.
TN_PRIMARY_EXTERNAL_ADDR="/ip4/${EXTERNAL_IP}/udp/${PRIMARY_UDP_PORT}/quic-v1"
TN_WORKER_EXTERNAL_ADDR="/ip4/${EXTERNAL_IP}/udp/${WORKER_UDP_PORT}/quic-v1"

# Check if the fetched address is empty
if [ -z "${EXECUTION_ADDRESS}" ]; then
    echo "EXECUTION_ADDRESS is not set in metadata. Setting value to 0."
    EXECUTION_ADDRESS="0"
else
    echo "EXECUTION_ADDRESS fetched from metadata: ${EXECUTION_ADDRESS}"
fi

# create validator credentials - pass in worker and primary multiaddrs
# and write to file
echo "creating validator keys"
# use external multiaddr to generate public committee.yaml
sudo docker run --name keygen --platform linux/amd64 -v ${DATADIR}:${DATADIR} --workdir ${DATADIR} -e TN_BLS_PASSPHRASE=${TN_BLS_PASSPHRASE} ${DOCKER_IMAGE} /usr/local/bin/telcoin keytool generate validator --datadir ${DATADIR} --address ${EXECUTION_ADDRESS} --external-primary-addr ${TN_PRIMARY_EXTERNAL_ADDR} --external-worker-addrs ${TN_WORKER_EXTERNAL_ADDR} ;

# move public information to shared folder
if [ ! -d "${SHAREDIR}" ]; then
    echo "creating share dir: ${SHAREDIR}"
    sudo mkdir ${SHAREDIR}
else
    echo "${SHAREDIR} already present"
fi

# copy node config and update SHAREDIR dir
sudo cp -r ${DATADIR}/node-info.yaml ${SHAREDIR}/${HOSTNAME}.yaml
sudo chmod -R 1777 ${SHAREDIR}

echo "startup complete"
