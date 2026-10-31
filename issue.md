# Devnet deploy blocked: IAP SSH tunneling broken on the operator machine

## Summary

`devnet-deploy.sh` (GCP project `tn-devnet`) cannot run to completion because every
per-node action it performs over **IAP SSH** (`gcloud compute ssh --tunnel-through-iap`)
hangs. The failure is in the local `gcloud` IAP tunnel (its websocket client), **not** on
the nodes — the nodes are healthy and fully bootstrapped. Any GCP REST-API call (serial
console, `instances describe`) works fine; anything that needs an IAP tunnel does not.

## Environment

- Machine: macOS (darwin 25.5), zsh. Repo: `/Users/grant/coding/telcoin/devnet-genesis`.
- gcloud: Google Cloud SDK **571.0.0** (core 2026.05.29).
- gcloud runs in a managed venv at `~/.config/gcloud/virtenv` pinned to **Python 3.13.7**
  (`CLOUDSDK_PYTHON` is unset and the venv overrides it). `python3.11` and `python3.12`
  are also installed locally.
- GCP project: `tn-devnet`.

## Current infrastructure state (healthy — not the problem)

- 5 nodes, all **recreated 2026-06-19** on Ubuntu 24.04 via `devnet-startup.sh`; first-boot
  bootstrap **completed** on every one (serial marker `devnet-startup.sh complete` present,
  docker installed, `tn-node-deployment` scripts cloned, `telcoin` user created):
  - `validator-1-devnet` (us-west2-a)
  - `validator-2-devnet` (australia-southeast1-c)
  - `validator-3-devnet` (northamerica-northeast1-b)
  - `validator-4-devnet` (europe-west4-a)
  - `observer-5-devnet` (europe-west2-b)
- Each node has its **reserved static IP attached**, matching the existing DNS
  `node1..node5.devnet.telcoin.network` A-records (DNS already in place).
- `obs-devnet` VM exists (created 2026-06-10), running.
- Background: the original stale pre-migration nodes (Debian 11, created 2026-06-05) were
  deleted and replaced with the nodes above. Recreation is done; this is the current state.

## Symptom

- `./devnet-deploy.sh --yes` hangs at `>>> Step 3: wait for first-boot bootstrap`, printing
  `…validator-1-devnet not ready yet (Ns/600s)` indefinitely.
- The deploy probes each node over IAP SSH and wraps it in `2>/dev/null || true`, so the
  underlying SSH error is swallowed — it just polls forever with no error surfaced.
- Key tell that localized the bug: GCP REST-API checks (serial console / `describe`)
  succeed, while the IAP SSH probe hangs. Same machine, same nodes, different transport.

## Root cause (what is actually failing)

IAP tunnel setup fails inside gcloud's bundled "new" websocket client. Running the tunnel
directly reproduces it:

```
gcloud compute start-iap-tunnel <inst> 22 --local-host-port=localhost:8722 \
  --zone=<zone> --project=tn-devnet --verbosity=info
```

Output:

```
Testing if tunnel connection works.
INFO: Connecting with URL ['wss://tunnel.cloudproxy.app/v4/connect?...&port=22&...&interface=nic0']
INFO: Error while receiving from WebSocket.
  File ".../googlecloudsdk/api_lib/compute/iap_tunnel_lightweight_websocket.py", line 343,
      in _wait_for_socket_to_ready
    _ = select.select([self.sock], (), (), timeout)
OSError: [Errno 9] Bad file descriptor
...
websocket._exceptions.WebSocketConnectionClosedException: Connection closed while sending data.
```

The websocket to `tunnel.cloudproxy.app` closes the instant it connects; the
`Bad file descriptor` is a secondary crash in the close/retry path. gcloud hardcodes
`should_use_new_websocket=True` (`iap_tunnel_websocket.py:278/282/294`) — there is no
documented env var / property to fall back to the legacy websocket.

## What was tried (investigation only)

- **Nodes confirmed up** via serial console (no IAP): all 5 show the completion marker.
  These reads succeed every time.
- **Reproduced against a second, unrelated, long-running VM** (`obs-devnet`): identical
  traceback → the failure is client-side, not specific to the new validator nodes.
- **Reproduced under two Python versions**: default venv 3.13.7, and
  `CLOUDSDK_PYTHON=python3.12` (confirmed honored — `gcloud info` reported 3.12.2). Same
  crash both ways → not a Python-3.13-only issue.
- **Local egress ruled out**: `curl -I https://tunnel.cloudproxy.app/` → HTTP 404 in
  ~0.19s, so the endpoint is reachable.
- **Proxy/VPN ruled out**: no `*_proxy` env vars, no gcloud proxy config; `utun0–3` have no
  addresses; the route to the IAP endpoint goes out `en1` (home router), not a tunnel; no
  VPN client processes running.
- **Node-side reachability ruled out**: firewall rule `wg-allow-iap-ssh` allows
  `35.235.240.0/20 → tcp:22` on the `default` network with no target tags; the node's sshd
  binds all interfaces (the WireGuard sshd drop-in deliberately omits `ListenAddress`/
  `AllowUsers`); no host firewall (`WG_NODE_FIREWALL=0`, so no nft drop table installed).
- **Installed numpy 2.4.6** into gcloud's venv (gcloud prints a "consider installing NumPy"
  hint for IAP): did **not** fix it — same traceback.

## Scope — what this blocks

The deploy's per-node steps execute commands ON the nodes over IAP SSH (via
`devnet-lib.sh` → `tn_iap_ssh`, which uses `gcloud compute ssh --tunnel-through-iap`):
keygen (Step 5, `devnet-keygen.sh`), finalize (Step 7, `devnet-finalize.sh`), observability
(Step 11, `devnet-observability.sh`), and host-firewall rules (Step 10, `devnet-firewall.sh`).
Genesis build (Step 6) consumes keygen output, so it is gated too. None of these can run
until IAP SSH works.

Note: direct (non-IAP) SSH is not a drop-in alternative — the VPC firewall only allows
`:22` from the IAP range `35.235.240.0/20`; there is no public `:22` rule.

## Quick reproduce / contrast

```
# FAILS (IAP tunnel):
gcloud compute start-iap-tunnel validator-1-devnet 22 --local-host-port=localhost:8722 \
  --zone=us-west2-a --project=tn-devnet --verbosity=info

# WORKS (GCP REST API, no IAP):
gcloud compute instances get-serial-port-output validator-1-devnet \
  --zone=us-west2-a --project=tn-devnet | grep "devnet-startup.sh complete"
```

## Working-tree note (state, not a fix for the above)

This session left uncommitted local changes that do **not** resolve the IAP failure: an edit
to `devnet-deploy.sh` Step 3's readiness check, and `numpy` added to gcloud's venv. The core
blocker — IAP SSH for the command-executing steps — is unresolved.
