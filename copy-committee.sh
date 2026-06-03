#!/bin/bash
#
# launch the validator node inside a docker container
#
# this is the last script to run after building the
# committee
#
# this script copies the local files into the correct dir
# with the correct permissions for `validator` and starts a docker
# container running the Telcoin Network binary.

# publicly available testnet image in Google Artifacts Registry
# defined in "genesis.sh"
echo "using docker image from: ${DOCKER_IMAGE}"

# copy genesis
sudo -u validator mkdir -p /home/validator/telcoin/genesis
sudo -u validator cp /home/share/genesis.yaml /home/validator/telcoin/genesis/genesis.yaml
# Check for exit status of previous command
if [ $? -eq 1 ]; then
    echo "Error: gcloud compute scp command failed to copy genesis.yaml." >&2
    exit 1
fi

# copy committee
sudo -u validator cp /home/share/committee.yaml /home/validator/telcoin/genesis/
# Check for exit status of previous command
if [ $? -eq 1 ]; then
    echo "Error: gcloud compute scp command failed to copy committee.yaml." >&2
    exit 1
fi

# copy parameters
sudo -u validator cp /home/share/parameters.yaml /home/validator/telcoin/
# Check for exit status of previous command
if [ $? -eq 1 ]; then
    echo "Error: gcloud compute scp command failed to copy parameters.yaml." >&2
    exit 1
fi
