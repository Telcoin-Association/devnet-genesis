# Telcoin Devnet

Telcoin Devnet is deployed to Google Cloud Compute VMs running Debian 11.

The current docker image is publicly available at `us-docker.pkg.dev/telcoin-network/tn-public/adiri`.

MC is the "Master of Ceremony". MC is required until decentralized discovery is supported.

MC can use a VCS for nodes to commit validator information or `ssh` if managing nodes. The network needs `committee.yaml` in the `genesis` directory of the `datadir` to start the network.

## Shared deploy scripts (`common/` submodule)

Most deploy and operations scripts are shared with the other Telcoin networks and live in
[`deploy-networks-common`](https://github.com/Telcoin-Association/deploy-networks-common-),
mounted here as the **`common/`** git submodule. Only this repo's `config.sh` (per-network
settings) and `genesis/` state are unique to devnet.

Clone with the submodule, or fetch it after cloning:

```bash
git clone --recurse-submodules <repo-url>
# or, if you already cloned without it:
git submodule update --init
```

`config.sh` is the single indirection point: it computes `REPO_ROOT` and exports every
script and file path as an absolute path (`START_VALIDATOR_NODE_SCRIPT`, `CONFIG_APACHE_SCRIPT`,
`PARAMETERS_FILE`, … → `common/…`), so the shared scripts resolve their inputs from any
working directory. Run shared scripts as `./common/<name>.sh` (e.g. `./common/genesis.sh`,
`./common/update.sh`).

To pull shared-script updates into this repo:

```bash
cd common && git pull origin main && cd ..
git add common && git commit -m "bump deploy-networks-common"
```

## Steps to deploy the network on Google Cloud Compute

1. Update the latest image or update script to use a specific tag in `config.sh`
1. Deploy 4 nodes on GCP by running `create-instances.sh`
   - Must ensure A records are set before running next step for certbot
1. MC runs `genesis.sh` to create the committee files
   - this step requires all validators to share their public information
   - uses the cli command to create committee, worker cache, and genesis files
   - alternative approaches to this step are possible, such as using GitHub to exchange information
   - `committee.yaml`, and `genesis.yaml` needed to start the node
     - must include all validators
   - `genesis.sh` pulls validator info from remote hosts, creates the committee / worker cache files,
     copies them back to remote hosts, and executes `launch-node.sh` on the remote host to start the node

### Additional notes for GCP Deployment:

- Certbot script is run on startup using instance templates. Static IPs are reserved for external addresses so DNS records don't have to be updated every deployment. Internal addresses are not static because startup script uses internal IP for committee, and it's unknown how to assign static IPs before VM starts.
- Dev needs to update HOSTNAME under `network` on GCP every deployment to: nodeX.telcoin.network - `echo $HOSTNAME` will still return "nodeX". Confusing google rule.
- The startup script that creates issues the letsencrypt certificates assumes ${HOSTNAME} is set in the instance template. This value does not copy when a new template is created from an existing one.
- Add node instances to adiri instance group after depolyment
- Must assign external ip addresses before running ./genesis.sh
- Current deployment of adiri is built using [this pr](https://github.com/Telcoin-Association/telcoin-network/pull/95)
  - problem with adiri:latest
- Use `gcloud compute instances get-serial-port-output INSTANCE_NAME --zone ZONE` to debug GCP startup scripts.

### WARNING

For future fresh deployments, be sure to update `startup.sh` on the GCP side.
Grant copied/pasted the new startup script that waits for docker info before calling `genesis init` since this was mysteriously not working in the last deployment 9/20/2024.

### Validator Execution Addresses

node1: `0x3518b301b86ceb53b5a3dff62e55cd43ef59d024`
node2: `0x7489025dfbaad94f2366d88a62989147d9c8b5d3`
node3: `0x0033a370616805b1fd275b7ffab83fc41d665ccb`
node4: `0xefaacf04b92298a88200aa50aa6bb7bfce587b17`
