# RH0: local admission rehearsal (devnet launch 2)

Run 2026-11-17 19:42-19:54 UTC on local docker. Image `us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.3.0-devnet`
(id `sha256:0aec3e7c…`, no entrypoint, cmd `telcoin node`, user `nonroot` 1101). Scratch dir
`/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/RH0/` (`$S`):
scripts in `$S/bin/`, logs in `$S/logs/`, rendered configs in `$S/data/<node>/network-config`. All containers and the
network were removed at the end; passphrase file and `node-keys/` deleted.

## What the deploy drivers must do (contract §9)
1. Keep the §9 admission table as written: all three rows started, synced and showed the expected snapshot.
2. Node 5 (closed, trusted = rpc-6) gets ALL its sync from rpc-6, because the validators drop it. So start rpc-6 before node 5. If rpc-6 shows up later, node 5 catches up only after its trusted-dial backoff (45 s here, after 108 s without rpc-6).
3. N1's map writer must emit each BLS key as a plain `key:` line. PyYAML's `safe_dump` writes keys longer than 128 characters as `? key`, and the TND renderer refuses that file.

## Harness (what was built, deviations from a real install)
- Network `l2rh0-net` 172.30.99.0/24; v1-v4 .11-.14, rpc .15, join .16; primary udp 9000, worker udp 9001; no host ports.
- Keys: `docker run --rm -i --user 1000:1000 -e HOME=/tmp -v $S/data/<n>:/home/nonroot <img> telcoin keytool generate
  validator --datadir /home/nonroot --address 0x… --external-primary-addr /ip4/<ip>/udp/9000/quic-v1
  --external-worker-addrs /ip4/<ip>/udp/9001/quic-v1 --bls-passphrase-source stdin < $S/secret/pass` (rpc: `generate
  observer`; join: `generate validator`, not in genesis). Passphrase: 32 random bytes, file mode 600, stdin only.
- Genesis (v1-v4 node-info in `genesis/validators/`): `telcoin genesis --datadir /code --bls-passphrase-source stdin
  --chain-id 0x1e7 --dev-funded-account 0x1111… --consensus-registry-owner 0x1111… --epoch-duration-in-secs 90
  --min-header-delay-ms 1000 --max-header-delay-ms 3000`; genesis.yaml, committee.yaml, parameters.yaml copied to each datadir.
- Maps (`$S/bin/maps.py`, from node-info.yaml): `validators.bootstrap-peers.yaml` (BLS -> `{primary, workers: [..]}`,
  checked equal to committee.yaml `bootstrap_servers`), `rpc.trusted-nodes.yaml` (BLS -> `{primary, workers: {0: ..}}`).
- `network-config` written by **TND's own renderer**: `$S/bin/render.sh` sources `tnd-l2-gateway/lib/common.sh`
  (`TN_ROOT_PREFIX=$S/tnroot`, `tn_as_service_user` overridden to run as the invoking user) and calls
  `tn_network_config_render <datadir> <closed|open> <trusted|none> <committee>`. Output: `admission: {mode}`,
  `trusted_nodes:`, `committee_peers:`, nothing else. The node did not rewrite it (40 lines before and after a run).
- Launch (`$S/bin/start.sh`), node args exactly as setup-node.sh renders the docker form:
  `docker run -d --name l2rh0-<n> --network l2rh0-net --ip <ip> --user 1000:1000 -e HOME=/tmp
  -e PRIMARY_LISTENER_MULTIADDR=/ip4/<ip>/udp/9000/quic-v1 -e WORKER_LISTENER_MULTIADDR=/ip4/<ip>/udp/9001/quic-v1
  -v $S/data/<n>:/home/nonroot -v $S/secret/pass:/run/l2rh0/pass:ro --entrypoint /bin/sh <img>
  -c 'exec telcoin node --bls-passphrase-source stdin "$@" < /run/l2rh0/pass' sh --datadir /home/nonroot
  --log.stdout.format log-fmt -vvv --http --http.addr 127.0.0.1 --ws --ws.addr 127.0.0.1 --healthcheck 43174
  --bootstrap-peers "$(cat <map>)"`.
  Deviations (harness only): bridge network + fixed IP instead of `--network=host`; invoking uid instead of the image
  user; passphrase file redirected to the node's stdin inside the container instead of `docker run -i` fed by the
  systemd credential.
- Queries: the image has bash but no curl, so `$S/bin/rpc.sh` runs `docker exec l2rh0-<n> bash -c` with a raw
  HTTP POST over `/dev/tcp/127.0.0.1/8545` (methods `tn_nodeMode`, `eth_blockNumber`, `tn_admissionSnapshot`).
  `/health/network` is fetched the same way on `127.0.0.1:43174`. `$S/bin/snap.py` condenses snapshots and names
  entries by peer id.

## Q1: epoch-0 rule. Verdict: yes (both halves)
- Negative: `l2rh0-v4bad` = v4's datadir with `committee_peers` lacking v1 (the launch flag still had all four).
  Exited with code 1, 0.6 s after start (`$S/logs/q1neg-v4bad.log`):
  `level=error target=tn_node message="Error running node: committee_peers: missing validator v1ksvWHrNNrsBhcru9c5CsjTSb2xkmH37L9K16DPAWW5yzCowbq57VLgiacKBZHXqTtqm4BbUvGmsXhVESxmYpKH7Abmpskh7A6BcYBf1izBQhVDahgnNbsHajqVy4k48SX"`
  and on stderr `Error: committee_peers: missing validator v1ksvW…`.
- Positive: v1-v4 (Closed, `trusted_nodes` = rpc, `committee_peers` = all four) started 19:44:12. At 19:44:48 all four
  answered `tn_nodeMode` = `CvvActive`. Consensus advanced (v1 log `"output saved" number=187` by 19:49). Blocks 1, 2, 3
  and 4 were produced at the epoch closes (v1 `closing epoch emitted` at 19:44:17, 19:45:47, 19:47:19, 19:48:50).
  An idle chain makes no other blocks: `"skipping execution for empty non-epoch-closing output"`.
- v1 snapshot: `primary: available=True tracked_epoch=1 configured=Closed effective=Closed fallback=None
  resolved/required/connected=4/3/3`; v2-v4 `slots=previous,current,next,scheduled,eligible,bootstrap admitted=True
  source=stub`; worker-0 the same.

## Q2: public RPC node. Verdict: yes
- `l2rh0-rpc`: Open, no `trusted_nodes`, `committee_peers` = four validators, `--bootstrap-peers` = four validators.
  Started 19:45:16; 40 s later `tn_nodeMode` = `Observer`, head 2 = validators' head 2. It followed every later epoch
  (head 4 = v1 at 19:49:10). On the second chain it synced block 1 within 1.3 s of start.
- rpc snapshot: `primary: available=True tracked_epoch=2 configured=Open effective=Open fallback=None
  resolved/required/connected=4/3/4` (worker-0 same); v1-v4 `admitted=True`.
- v1 snapshot: `effective=Closed fallback=None`, entry `rpc: slots=trusted admitted=True source=record` (it read
  `source=config` before the rpc node was up), and `rpc/w0: slots=trusted admitted=True` on worker-0.
- `/health/network` established peers: rpc 5 (four validators + joiner), v1 4 (three validators + rpc).

## Q3: the joiner (node 5 before it stakes). Verdict: config A (exactly §9's row) syncs, only through the RPC node
- Config A: Closed, `trusted_nodes` = rpc, `committee_peers` = four validators, `--bootstrap-peers` = four validators.
  - Run 1 (rpc already up): started 19:46:15.4. `"retrieved cert for epoch 0 … from a peer" peer=p75f2fjd…` (the rpc
    node's BLS key) at 19:46:16.6. It executed the epoch-0 close at 19:46:16.7 and block 2 (the tip) at 19:46:20.1:
    **in sync 4.7 s after start**. Then it followed live: epoch closes at 19:47:19.516 (v1 19:47:19.511) and 19:48:51.3
    (v1 19:48:50.3). Watched 3 min: head 4 = v1, `tn_nodeMode` = `Observer`.
    Snapshot: `effective=Closed fallback=None resolved/required/connected=4/3/0`. `/health/network`: primary and
    worker `established_peers: 1` (the rpc node); zero committee connections.
  - Run 2 (second chain, rpc NOT started): joiner started 19:50:47. After 100 s it was at head 0 while v1 was at 1;
    `/health/network` 503 `disconnected`; heartbeat `connected_count=0`. Snapshot: `effective=Grace
    fallback=Unresolved resolved/required/connected=0/3/0`. The joiner kept getting QUIC handshakes with every
    validator (`"new connection established"` 9-27 times to each primary/worker address). The validators always
    dropped it again, and their logs at -vvv have no line naming the joiner's peer id.
    rpc started 19:52:35.7 and synced block 1 by 19:52:37.0. The joiner first connected to it at 19:53:20 (dial backoff)
    and executed block 1 at 19:53:26 and block 2 live at 19:53:30.6 (rpc 19:53:30.6).
    Snapshot after: `effective=Closed fallback=None`, rpc `source=record`.
- Configs B (plus `bootstrap_peers:` for rpc in network-config) and C (`--bootstrap-peers` = rpc only): **not run**,
  because A synced. Per the node's `--help`, `--bootstrap-peers` "Replaces network-config bootstrap_peers for this
  process only", so B as specified would behave like A (help text only, not verified by a run).

## Q4: time to an authoritative snapshot on a validator. Verdict: measured
- Poller `$S/bin/q4poll.sh` (1 s interval, seconds from the container's `StartedAt`):
  - Fresh chain (re-genesis, empty DBs), v1 (`$S/logs/q4-v1.txt`): 0.6 s RPC not up; 1.6 s `available=True
    tracked_epoch=None effective=Open fallback=Missing`; **3.7 s `tracked_epoch=0 effective=Closed fallback=None`**.
  - Restart (v4 container re-created on its datadir mid-epoch 4, `$S/logs/q4-v4.txt`): first RPC answer at **1.2 s**,
    already `tracked_epoch=4 effective=Closed fallback=None`.
- The poller's first attempt on the first chain had a script bug and recorded nothing. The 3.7 s figure comes from the second chain.

## Findings for the drivers and operators (friction)
- PyYAML `safe_dump` writes the 147-character base58 BLS keys as `? <key>` explicit keys. The TND renderer refuses
  that: `does not start with a map keyed by BLS public key` (tnd-l2-gateway/lib/common.sh, renderer ~2882-2908).
  Write the top-level keys by hand (as `$S/bin/maps.py` does).
- Node 5 depends on rpc-6 alone until it enters the committee window. While rpc-6 is down its snapshot is
  `Grace/Unresolved`, not authoritative, so `firewall-setup.sh --p2p-committee on` would refuse on node 5 then
  (inference from the snapshot rule, not run).
- An idle chain's head moves only at epoch closes, so a "blocks are produced" gate must wait one epoch duration or
  send load. `tn_nodeMode` plus a moving consensus output number is the faster signal.
- Validators log nothing at -vvv when they refuse a non-admitted peer: an operator cannot see from a validator's log
  why node 5 is not connected.
- The image has no curl. On a docker install an in-container probe needs bash `/dev/tcp`; host-side probes of
  127.0.0.1 work only with `--network=host`.

## Not verified
- Node 5 after staking (entering the window through the `next` slot): no funded key on this chain.
- Configs B and C (see Q3). Behaviour with `--network=host`, the image user, and systemd credentials.
- Multi-worker committees (this run: one worker per node).
