status: in-progress (partial: steps 1..13 run; 14 blocked on a shim gap; tool budget reached)
updated: 2026-11-17T21:10Z

# unit SH2 checkpoint (shim steps 9..14, dg-l2/tasks/l2-shim/)

## Completed sections
- fresh run steps 1..8 CLEAN (state /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/SH2/state, rc 0, 0 findings, 0 sentinel)
- step 9 CLEAN (class a, fixed in fakes.py): why the stack script made no docker call = SHIM bug: gc_ssh read stdin
  only with --ssh-flag=-T, so common/create-obs-instance.sh:188 (`sudo VARS bash -s < bringup-remote.sh`, no -T;
  real ssh forwards stdin anyway) ran an empty script, rc 0. Now stdin is read for -T or `bash -s`, else inherited.
  Added remote curl (metadata token, Secret Manager REST access, loopback health hook) and `docker compose`
  (up -d/ps/down/restart/kill/exec, per-host compose.json). /opt/obs now comes from the real bring-up's cp.

- step 10 CLEAN (class a, added): setup-node.sh --json --phase=finalize (maps installed root 0644, network-config by
  the REAL tn_network_config_render with TN_ROOT_PREFIX=<host root>, node.env, tn-start-docker = LC:3760 line, unit
  with append: log targets, service .node-meta keys + ADMISSION_MODE/BOOTSTRAP_PEERS_FILE/TRUSTED_NODES_FILE, unit
  started+enabled); node runtime model (MainPID 4242 + /proc/<pid>/{cmdline,environ} in the fake root, container
  telcoin in containers.json, journal.json, telcoin.log); systemctl show/cat/reset-failed; journalctl (-n, -u,
  --after-cursor, --show-cursor); docker inspect -f; pgrep -f; ss -ltn; health curl :43174 (active + healthcheck
  monitor). cksum added to the sandbox tools; /proc (not /proc/self) rewritten into the fake root.
  Driver argv matched contract 9/Z1 (ws url only on rpc-6, no trusted map for rpc-6); 6 nodes STAGED inactive+enabled.

- step 11 CLEAN (class a, added): firewall-setup.sh --json --enable|--status|--port (rule set of fact sheet 2 +
  contract 5 incl. GATEWAY_ALLOW_FROM, --p2p-anywhere unsets P2P_ALLOW_FROM, NETWORK from .node-meta or
  gateway.meta, per-host ufw.json); gc_ssh now refuses (255) when ufw is active without 22/tcp from any or IAP.
  Driver: --p2p-anywhere on rpc-6 only; bare gateway VM gets plain --enable (no node: SSH rules only) and a note
  to re-run after step 13 for 80/443 (watch in step 13 whether anything re-runs it).

- step 12 CLEAN (class a, added): setup-observability.sh --json (log/metrics/health flags into tn-start-docker,
  alloy config + telcoin-alloy unit active, health ufw rule, .node-meta keys, token read from stdin only);
  odd host numbers' installer restarts the node, even ones warn "Not restarting": driver ran both paths
  (stop-again on 1,3,5; no-stop on 2,4,6), all OBS_STAGED inactive+enabled, flags=ok. systemctl show gained
  ActiveEnterTimestampMonotonic. Gateway VM not visited (correct). Run with OBS_POLL_SECS=1.

- step 13 RAN (deploy rc 0; report NOT CLEAN only because of finding F1): added setup-gateway.sh --enable/--status
  (contract 3.2 fields, gateway.meta, telcoin-gateway unit, Caddy tn-gateway block + ufw 80/443 as install-caddy's
  gateway-enable does, ready = upstream node active), edit-config.sh --json --set gateway_upstream (refuses without
  the --gateway-from ufw rules; stopped node stays stopped), probe :8656, ss gateway/caddy sockets. Order seen:
  same-host on 1,2,3,5; for node4: firewall --gateway-from <gw4 int IP> -> edit-config gateway_upstream -> standalone
  gateway-4 --upstream <validator-4 int IP>; rpc-6 untouched; every node still stopped after the step;
  every gateway installed/active/health=true/ready=false. run.sh: MODE findings + opt-in L2_SHIM_CHMOD_DRIVERS=1.
- step 14 NOT clean (class a, open): coordinated start-at script answers start_rc=unknown, began= (empty) on all six;
  no finding logged, so a tool inside the start-at snippet (devnet-finalize.sh ~655-690) fails silently in the
  sandbox (stderr to /dev/null). Next: run step 14 again, read remote-detail.log + the snippet, add what it needs.

## Findings (class b)
- F1 (step 13, also 15+ and 20): devnet-gateway.sh, devnet-postcheck.sh, devnet-p2p-committee.sh are committed as
  git mode 100644 (dg-l2 index), while devnet-deploy.sh:368/377 ("${REPO_DIR}/devnet-gateway.sh"), :382
  (devnet-postcheck.sh) and :404 (devnet-p2p-committee.sh) execute them directly -> exit 126 "Permission denied" at
  step 13. Fix: git update-index --chmod=+x (or call them with bash). Not a shim artefact: rsync -a keeps modes.
- (not a finding) step 11's note about 80/443 on the bare gateway VM: install-caddy.sh opens 80/443 itself
  (install-caddy.sh:737-738, gateway-enable path ~3053), so no re-run of devnet-firewall.sh is needed.

## Next
- resume: cd /home/drtnarg/coding/telcoin/dg-l2 && tasks/l2-shim/run.sh --state /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/SH2/state --from 14 --to 14 --sig ok   (env: L2_SHIM_CHMOD_DRIVERS=1 FINALIZE_START_LEAD_SECS=4 FINALIZE_START_LAUNCH_GAP_SECS=0 HEALTH_POLL_SECS=1 FINALIZE_STABLE_POLL_SECS=1; steps 9..13 state is in place)
- 21:19Z step 14 re-run after adding /run to the fake VM (boot_host): rc logged in /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/SH2/run-14.out; 0 red lines; non-MODE findings: none
