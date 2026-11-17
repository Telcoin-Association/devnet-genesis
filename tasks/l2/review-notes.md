# Launch 2: points for the integration tests and the reviews (orchestrator's running list)

Each line: where it came from, what to check, who gets it. Newest at the bottom.

## tn-node-deployment
- C3 (edit-config): `gateway_upstream=off` always sets `--http.addr 127.0.0.1`; a node whose RPC was made public
  through the menu loses that bind (previous `--http.addr` is not recorded). -> R1a: accept, or refuse the key
  when the bind is already wildcard without `GATEWAY_UPSTREAM`.
- C2/C3: the RPC port. C3 takes it from `tn_local_rpc_url` (.node-meta `RPC_PORT`, then the `RPC_PORT` env, then
  8545); C2's rules from .node-meta `RPC_PORT`, then 8545. An `RPC_PORT` in the operator's shell could make the
  two differ. -> R1a.
- C3: the stopped-node guard treats `failed` and `activating` as stopped. -> R1a.
- C3 not exercised: the restart-failure rollback for the new key (generic `run_set` path). -> E3.
- D2 (remove-node): after a service-scope or data-scope removal on a same-host gateway, the kept `.node-meta`
  still has `RPC_ADVERTISED_VIA=gateway`. -> R1b.
- D2: an OLDER remove-node.sh on a same-host gateway shreds `gateway.meta` and leaves the gateway unit running. -> F1 (OPERATOR.md: update the scripts before removing).
- D1 (check-node) assumes `gw_status` prints and counts unit state, image held, `/health`, the Caddy block, and
  does NOT print `/ready` or check listeners; D1 adds `/ready` (information) and the three listeners itself. If
  A1's `gw_status` does either, one of the two must go. -> E4 with the real library.
- D1: a wildcard `--healthcheck` without `GATEWAY_UPSTREAM` is counted as an issue; its hint
  `edit-config.sh --set gateway_upstream=off` does nothing when the key is unset (C3: "no change"). -> E4 / R1a:
  fix the hint (the bind came from the interactive RPC menu).
- D1: `ss` matching accepts `0.0.0.0:P` and `*:P`, not `[::]:P`. -> E4.
- D1: its new functions call `advertised_rpc` / `read_advertised_rpc` (check-node.sh ~1066-1146), outside the
  region the existing tests cut out; a fixture test must cut those too. -> E4.
- A2 (setup-gateway): `--help --json` prints usage and no done line (as the template); `--refresh` accepts
  `--yes` and asks nothing; `--remove` asks only when something is installed. -> R1b: fine unless it disagrees.
- A2 untested: `tn_gateway_meta_get` on an unreadable `gateway.meta` (non-root `--status`); real bash 3.2. -> E1.
- C1: real ufw's display of `allow from 10.0.0.5/24` (network address?) and of a `/32` (bare host?) is from
  memory; the reader accepts both forms. -> RH (a real ufw on a VM) or E3 with a real `ufw` if the host has one.

## devnet-genesis
- TX: `--since @<epoch>` verified on systemd 259 (this host), not on the VMs' systemd 255. -> W3 step 19.
- TX: capturing `tx_ssh` stdout assumes `tn_iap_ssh` passes remote stdout through cleanly. -> SH shim / W3.
- SU: on the gateway VM the startup script writes `devnet-ips.env` with node ports and logs node wording; the
  metadata `tn-scripts-ref` must be set there too (it is, by the shared instance script). -> DOC (runbook note).
- SU: Ubuntu's stock `/etc/nftables.conf` begins with `flush ruleset`: no driver may start `nftables.service`. -> PC, FW, R2b.
- C2 (firewall): a node-less MAINNET gateway host cannot store `SSH_ALLOW_FROM` (`fw_wants_meta_write` needs
  `.node-meta`), so every `--enable` there needs `--ssh-from` or `--ssh-anywhere` again. Standalone is the
  mainnet mode. -> R1a: store the SSH list in `gateway.meta` on such a host, or document it (F1).
- C2: stale gateway rules are deleted on the CURRENT RPC port; after `RPC_PORT` changes, rules on the old port
  stay until `--reset`. -> R1a.
- C2: `--json --status` `"kuma"` says `restricted` on mainnet when only gateway rules hold the health port. -> R1a.
- C2: `gateway_from` is emitted BEFORE `p2p_committee` (an existing test helper assumes `p2p_committee` is last);
  expected-rules rows for the gateway have spec `"<port>/tcp from <src>"`: check every consumer of
  `desired[].spec` (the Node Manager UI?). -> R1a / E3.
- C2 not run: `--json --enable --gateway-from`; `--p2p-committee` together with `--gateway-from` (must be refused). -> E3.
- E4: on a gateway-only host that still has an empty `/var/lib/telcoin` or `/usr/local/libexec/telcoin`, those
  count as node leftovers, and `remove-node.sh --json --remove` then removes the standalone gateway with them
  instead of printing the pointer. -> R1b.
- E4: `scan_custom_installs` (remove-node.sh ~1774) greps the real `/etc/systemd/system`, ignoring
  `TN_ROOT_PREFIX`: the unit side of the scan cannot be fixture-tested. -> R1b (note only).
- E4: stale comments say a bare `--healthcheck <port>` binds every interface (`lib/common.sh:11179`,
  `setup-observability.sh:147`); on telcoin-network main it binds loopback (challenge 3). -> F1 / challenges.
- B broke `tools/tests/host_baseline_test.sh` (1 check: refresh call sites in install-caddy.sh, expected 2, got 4).
  Sent to E2 (2026-11-17T20:10Z). LESSON for RH1: units ran only their named tests; the WHOLE suite runs before the push.
- E1: `setup-gateway.sh:65` usage text contains a literal `{"event":"done",...}`; a caller grepping `--json --help`
  output for a done line would count one. -> R1b (reword the usage line, or leave: `--help` is not a JSON action).
- E1: with an old `lib/common.sh`, the skew message says both libraries are older even when `lib/gateway.sh` is
  current but not sourced. The remedy text is still right. -> R1b (note only).
- E1 not covered: "docker not installed" refusal; signals INT/HUP; macOS /bin/bash. -> RH1 (macOS is CI's job).
- E3: `edit-config.sh --set gateway_upstream=10.0.0.7` is refused when `GATEWAY_ALLOW_FROM` holds a CIDR that
  covers it (`tn_gateway_from_rules_ok` matches sources literally). -> R1a: accept a covering rule, or keep and document.
- E3: `--enable --gateway-from` with no value (or `=` empty) quietly becomes a plain `--enable`; `--json --status
  --gateway-from X` ignores the flag. Same as the other source flags today. -> R1a (note; challenge 17 family).
- E3 (again, sharper): node-less MAINNET gateway host: a plain `--enable` after a successful `--enable --ssh-from`
  is REFUSED (rc 1), because the list was not stored. -> R1a must decide (store in gateway.meta).
- GW: the lib's `tn_iap_ssh` re-sends EVERY command, changing ones included, on an ssh transport fault
  (`devnet-lib.sh:96-124`, `TN_IAP_RETRIES=2`). The gateway installs are idempotent; check the same for every
  changing remote command the new drivers send. -> R2b.
- GW: `install-caddy.sh rpc-enable` restarts the node with `systemctl restart`, which also STARTS a stopped node:
  `devnet-gateway.sh --rpc-edge` before the coordinated start would start rpc-6 alone. The driver has no
  running-node check. -> R2b (add a guard: refuse while the node unit is inactive).
- GW runs `setup-gateway.sh --status` with sudo (not needed by the script). -> note only.
- FW: `setup-firewall.sh` parses `gcloud compute firewall-rules list --format='value[separator="|"](…allowed[].map().firewall_rule().list()…)'`;
  the expression was not run against real gcloud. -> W3 (run `--status` and the dry run on the live project BEFORE
  step 8; read-only) and R2b.
- FW: a rule that differs in direction/action is deleted and re-created (a brief gap). Today's rules never take
  that path. -> R2b (note).
- FW: on the bare gateway VM at step 11 `firewall-setup.sh --enable` opens SSH only (NETWORK unknown); 80/443 are
  opened by `install-caddy.sh` itself at step 13. Confirm on the VM. -> W3 canary.
- FW: `TN_KUMA_SRC` is exported locally but never reaches the remote sudo command. -> note only.
- SK: `tn_nodeMode` over the node's own loopback assumed to be the plain string `Observer` / `CvvActive` (quoted
  JSON string result). -> W3 (first IAP read) / R2b.
- SK: the watch prints node 5's status from the last `getValidator` read (no new chain call per epoch). -> R2b (note).
- SK: an IAP read can be tried up to 6 times (the lib retries transport faults, the script retries once more). -> note.
- G2: `devnet-genesis-build.sh:323` hard-codes the Safe address and overrides config's `SAFE_ADDR`. -> R2a (note).
- G2: `config.sh` exports `TN_GATEWAY_ENABLE=1` unconditionally (an environment override has no effect). -> R2a (decide: `${TN_GATEWAY_ENABLE:-1}` or leave).
- G2: `--pull-only` with a bad target exits 1 (a bench test asserts it), plain keygen exits 2. -> accepted.
- G2: genesis Safe post-processing (steps 5-6) assumes the Safe at 0x…07a0 with owners at slot 2, count at 3,
  threshold at 4. telcoin-network main moved to the canonical Safe v1.4.1 suite. -> RH3 runs the real build.
- PC: not verified on a host: what plain `tn-p2p-allow-sync status` prints (the driver also reads the status
  file), and the streams/prefix of `firewall-setup.sh --p2p-committee status`. -> W3 step 20 canary (first validator).
- PC: `config.sh` assigns `P2P_COMMITTEE_WAIT_SECS=300` unconditionally (the driver saves and restores an
  operator's environment value). Same pattern as `TN_GATEWAY_ENABLE`. -> R2a.
- PC: `--off --yes` stops at the first host after which the committee is not whole. -> R2b (judgement call; fine).
- TD: not verified on GCP: deleting an unmanaged instance group while its VMs exist (`--lb-only` before a VM
  teardown); `gcloud compute ssh` without `--quiet` for the txgen stop (stdin is /dev/null). -> W3 (the dry run
  first; the apply is watched).
- TD: `common/setup-load-balancer.sh` still reads `LB_*` (now `LEGACY_LB_*`): it must never be called again;
  the new deploy does not call it. -> R2b (confirm no caller is left).
- RS: tn-node-deployment's host-side `_tn_release_fetch` was not read; no DG driver ships the devnet manifest to
  a host, so nothing on a host should parse it. -> R2a (confirm with a grep of TND for the devnet manifest path).
