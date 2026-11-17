# Devnet launch 2: worker gateways, committee firewall, public RPC node (mainnet rehearsal)

Date: 2026-11-17. Operator grant@telcoin.org on xerxes; repos under /home/drtnarg/coding/telcoin/.
Supersedes the 2026-10-31 plan (launch 1 is complete, verified and pushed; the sentry design in
docs/mainnet-simulation-plan.md is replaced by this one). Mainnet launches in about two weeks; this
rehearsal exists to surface deployment-script problems before then.

## Context

The user wants the devnet redeployed in the shape mainnet will have: validators in a closed network,
a `worker-gateway` process in front of each validator's JSON-RPC, node records in the Kademlia DHT
advertising the gateway URL, the `tn-p2p-allow-sync` release refreshing each node's P2P firewall
allowlist periodically, an image built from the latest telcoin-network `main`, and a 5th node that
stakes after genesis and rotates into later committees. Everything is to be deployed with
tn-node-deployment, and every friction met while using those scripts is to be flagged.

## Decisions (user, 2026-11-17)

1. **Gateway installer lives in tn-node-deployment**: new script on a PR branch against `main`,
   standalone-host mode (mainnet) and same-host mode (devnet). Devnet pins the PR head.
2. **One public RPC node** (`rpc-6-devnet`): non-validator, Open admission, trusted by the
   validators. Gateways `--redirect-queries` to it; it forwards transactions to the committee
   through the gateway URLs in the node records; node 5 syncs from it before staking.
3. **Image** from telcoin-network `origin/main`, mainnet-shaped (no `faucet` feature).
4. **Teardown and fresh genesis** (DESTRUCTIVE: chain 32285 at epoch 362 and its five VMs). Four
   genesis validators; node 5 stakes afterwards. Subagents do all the work.
5. **One validator standalone**: validator-4's gateway runs on its own VM (`gateway-4-devnet`);
   `node4.devnet` points at that VM. Validators 1-3 and node 5 are same-host.
6. **RPC edge is native**: `rpc.devnet.telcoin.network` becomes an A record to rpc-6, served by
   tn-node-deployment's own public-RPC option. The Google load balancer is deleted.
7. **VPC opens P2P UDP 49590/49594 to any source**: the host allowlist is the real filter.

Approving this plan approves: the teardown, deleting the Google LB stack, two new VMs with static
IPs, a new branch + PR on tn-node-deployment, pushes to devnet-genesis `main`, and two new images
in Artifact Registry. Nothing is posted as a GitHub issue without a separate word from the user.

## Target topology

| VM | Role | Admission | Web edge | Gateway | P2P firewall |
|---|---|---|---|---|---|
| validator-1..3-devnet | genesis validators | Closed, trusts rpc-6 | Caddy (install-caddy.sh gateway block), `nodeN.devnet` | same host, loopback 8655 → node 127.0.0.1:8545 | committee allowlist, 5-min timer |
| validator-4-devnet | genesis validator | Closed, trusts rpc-6 | none (no public HTTP) | on gateway-4; node RPC + health listener admit only gateway-4 | committee allowlist |
| gateway-4-devnet (new) | gateway only | n/a | Caddy, `node4.devnet` | standalone → validator-4 private IP | no P2P |
| observer-5-devnet | joins after genesis | Closed, trusts rpc-6 | Caddy, `node5.devnet` | same host | committee allowlist (attempt before staking, see D4) |
| rpc-6-devnet (new) | public RPC, never stakes | Open | native public RPC, `rpc.devnet` (https + wss) | none | open (`--p2p-anywhere`) |

obs and txgen VMs stay. txgen posts to `https://rpc.devnet.telcoin.network`. Records advertise
`https://nodeN.devnet.telcoin.network/` with no WebSocket. rpc-6 runs default record-based
forwarding (not `--forward-txs`, which bypasses records; flagged below).

## Facts the design rests on ([I] = inferred)

- **Live**: chain 32285, epoch 362; image v0.2.0-devnet (3f9b0709c); scripts at d9446f7. gcloud
  credentials expired. telcoin-network `origin/main` = 5533ff73a (local checkout on `mainnet`,
  dirty). tn-node-deployment `origin/main` = b89ada4 = `scripts-v2.1.0` (local checkout on a docs
  branch, dirty). Both are worked on in separate git worktrees. The benchmark fleet sources the
  root `config.sh` and would inherit a moved `TN_NODE_SCRIPTS_REF`.
- **Gateway** (`bin/worker-gateway`): HTTP/1 POST proxy; no WebSocket, no TLS, no auth. Own image
  (`bin/worker-gateway/Dockerfile`, uid 1101); no CI build or release artifact. Default listen
  0.0.0.0:8545 collides with the node. Readiness = node `GET /health/workers` on `--healthcheck`.
  Without `--redirect-queries` it forwards all but `tn_/debug_/trace_/admin_`; with it only
  submissions and a few follow-ups reach the worker. Limits 32 connections and 100 rps per client
  IP: behind a proxy it needs `--trusted-proxies` or every client shares one bucket.
- **Node on main**: bare `--healthcheck <port>` binds 127.0.0.1; `tn_admissionSnapshot` is new;
  records gained a network-key co-signature; execution DB migrates one-way; admission keys and
  genesis/keytool flags unchanged. At epoch 0 a non-empty `committee_peers` must list every
  committee member or the node refuses to start. A non-committee node forwards submissions to
  current-committee record URLs by default (`worker.rs` `disburse_txns`, `tn-reth/src/forward.rs`:
  64 tasks, a non-2xx demotes that endpoint 30 s, public targets only). `bin/node-record-api`
  (`GET /v1/rpcs`) reads advertised URLs from the DHT.
- **tn-node-deployment**: no gateway support. `install-caddy.sh` owns the Caddyfile, hard-codes the
  node as upstream, dies on a host with no node. RPC bind limited to 127.0.0.1/0.0.0.0, no ufw rule
  for 8545, local readers hard-code loopback. Native now: `setup-node.sh --admission … --trusted-nodes
  <file>`, `firewall-setup.sh --p2p-committee on|off|sync|status` (pins tn-p2p-allow-sync v0.1.1,
  gpgv-checked; needs ufw, nft and an authoritative snapshot; no `--json`). The native renderer
  uses one map for bootstrap and committee peers and drops `committee_peers` when run without it.
- **tn-p2p-allow-sync**: reads `tn_admissionSnapshot` on loopback; set = eligible pool + committees
  E-1..E+2 + trusted/bootstrap peers + a floor from committee.yaml; nftables table
  `inet tn_p2p_allow`; keeps the last good set; skips `dns*` multiaddrs. A snapshot is
  authoritative seconds after a node enters epoch 0. A joiner becomes `eligible` at the first epoch
  start after `activate()`; its record then has to be fetched (lookups back off up to 30 min).
- **devnet-genesis**: `devnet-network-config.sh` renders admission itself; keygen advertises https
  and wss; Caddy and the LB come from `common/`; step 8 starts nodes one by one; open follow-ups at
  `devnet-stake-node5.sh:510`, `devnet-txgen.sh:473`. Behind a gateway `https://node5` answers
  reads from rpc-6 and `tn_nodeMode` with 403, so the stake script must read node 5 over IAP.

## Part A: tn-node-deployment PR (branch `worker-gateway`, scripts 2.2.0)

Worktree off `origin/main`. Template: `setup-alerts.sh` / `lib/alerts.sh`. Contract frozen in W0.

- **`setup-gateway.sh` + `lib/gateway.sh`** (unit A). Actions `--enable|--status|--refresh|--remove`,
  `--yes`, `--json` (events on fd 3, last line `{"event":"done","ok",…}`), exit 0/1/2/3 as
  setup-alerts. Flags: `--mode same-host|standalone`, `--network`, `--image <repo>@sha256:…`
  (tags refused), `--domain`, `--front caddy|none`, `--upstream <private-ip>` `--rpc-port`
  `--health-port` (standalone), `--redirect-queries <url>` (required), `--listen-port 8655`,
  `--probe-port 8656`, `--metrics-port 9655`, `--trusted-proxies` (set to 127.0.0.1/32 with Caddy).
  State in `/etc/telcoin/gateway/gateway.meta`. Unit `telcoin-gateway.service` running
  `docker run --network=host --user 1101:1101 --read-only --cap-drop ALL --pull=never <digest>`
  with the rendered arguments; never restarts the node; re-run with unchanged inputs is a no-op;
  a failed change restores the backup. Image trust: devnet = digest from an allow-list that
  includes `us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway`, plus a `--help` probe for
  every flag the script emits; mainnet = a digest pinned in the signed scripts release (empty
  today, so mainnet refuses until a release pins it). Reuse `tn_write_root_file`, `meta_set`,
  `tn_backup_file`/`tn_restore_backup`, `tn_launch_flag_get`, `tn_docker_holds_digest`,
  `validate_port`, `rpc_url_is_private` (lib/common.sh).
- **`install-caddy.sh`** (unit B): third fenced block `tn-gateway` (reverse_proxy to the gateway,
  X-Forwarded-For, 405 for WebSocket and browser GET, probe paths passed through), phases
  `gateway-enable`/`gateway-disable`, a gate that works on a host with no node, and
  `rpc-advertise`/`rpc-unadvertise` (https only, no Caddy change) that `rpc-disable` must not undo.
- **Validator side for standalone** (unit C): `firewall-setup.sh --gateway-from <ips>|none`
  (persisted, survives `--reset`), `edit-config.sh --set gateway_upstream=<ips>|off` (binds
  `--http.addr 0.0.0.0` and `--healthcheck 0.0.0.0:<port>`, refuses unless ufw is active and the
  rule exists), helpers in `lib/common.sh`.
- **`check-node.sh` / `remove-node.sh`** (unit D): gateway section, validator section (rules,
  binds, advertised URL = gateway, no ws).
- **Tests** (unit E): fixture tests in `tools/tests/` (expected unit text per mode, refusals leave
  the tree unchanged, idempotent re-run, rollback), a local Docker smoke test against stub worker,
  health and redirect servers, shellcheck and the repo's bash-3.2 and lint gates.
- **Docs and release files** (unit F, last): OPERATOR.md, README, CHANGELOG, `update-scripts.sh`
  script list, version bumps, checksum sidecars.

## Part B: devnet-genesis changes

- **`config.sh`, `devnet-lib.sh`, `benchmark/config.sh`**: append `rpc-6-devnet` (role `rpc`,
  us-west2-b) and `gateway-4-devnet` (role `gateway`, europe-west4-a) after index 4 so node 5 keeps
  its index; per-node gateway mode (same-host ×4, standalone for node 4, none for rpc-6);
  `GATEWAY_IMAGE`, `GATEWAY_REDIRECT_URL=${RPC_URL}`, `RELEASE_TAG=v0.3.0-devnet`, new
  `DOCKER_IMAGE` digest, `TN_NODE_SCRIPTS_REF` = PR head; LB variables kept as `LEGACY_LB_*` for
  teardown only; a knob `TN_ADMISSION_VIA=native|devnet`; helpers `tn_fleet_check` (array lengths,
  roles), `tn_indices_by_role`, `tn_internal_ip`; bench config re-pins its own scripts ref, sets
  the admission knob to `devnet` and switches the gateway off.
- **Keygen / genesis** (`devnet-keygen.sh`, `devnet-genesis-build.sh`): `--rpc-http` only; rpc-6 is
  generated as an observer and kept out of the validator count; gateway-4 has no keys.
- **Admission** (`devnet-network-config.{sh,py}`, `devnet-finalize.sh`): devnet renders only the
  input maps; installation goes through native `setup-node.sh --admission closed|open
  --trusted-nodes <file> --bootstrap-peers <file>`. Validators and node 5 trust rpc-6 (`/ip4`
  addresses); every bootstrap map lists all four genesis validators. Node 5 uses the native path
  only (trusted rpc-6 + committee map); a devnet-written `bootstrap_peers` fragment is the fallback
  if the local rehearsal shows it cannot sync that way. The strict validator switches to
  parse-and-compare of the natively written file.
- **Start** (`devnet-finalize.sh`, `devnet-deploy.sh`): stage all six nodes, then one coordinated
  start. New post-checks: admission file and `.node-meta` keys; on gateway hosts
  `setup-gateway.sh --status --json` ok, 8545 on loopback only (validator-4: reachable from
  gateway-4 only), `tn_nodeMode` over `https://nodeN` refused.
- **New drivers**: `devnet-gateway.sh` (runs `setup-gateway.sh` on nodes 1, 2, 3, 5 and on
  gateway-4, plus `firewall-setup.sh --gateway-from` and `edit-config.sh --set gateway_upstream`
  on validator-4 while it is still staged; the contract requires that setter to leave a stopped
  node stopped and the installer to work with the node down and the redirect URL unreachable; if
  the setter cannot do that, validator-4 is rebound after the coordinated start with one restart),
  `devnet-postcheck.sh` (gateway and edge checks, run after the start) and
  `devnet-p2p-committee.sh` (polls
  `tn_admissionSnapshot`, then `firewall-setup.sh --p2p-committee on`, one validator at a time,
  asserting `tn-p2p-allow-sync check` and block advance between nodes).
- **Firewalls** (`devnet-firewall.sh`, `setup-firewall.sh`, `devnet-startup.sh`): native ufw
  `--enable`; VPC allows UDP 49590/49594 from anywhere to nodes, tcp 80/443 to the Caddy hosts,
  tcp 8545 + 43174 from gateway-4's internal IP to validator-4 only; consensus /32 rules and LB
  and Kuma health rules deleted; startup installs `nftables`.
- **Edges**: validators' Caddy comes from `install-caddy.sh` (gateway block + its native UI block
  for `admin.nodeN`); rpc-6 uses the native public-RPC option. `common/dns.sh`,
  `common/config-caddy.sh` and `common/setup-load-balancer.sh` are no longer called for the devnet
  fleet (`common/` itself is not edited).
- **Teardown** (`devnet-teardown.sh`): also deletes the LB stack by its `LEGACY_LB_*` names
  (forwarding rules, proxies, URL map, backend service, instance groups, health check,
  certificate, LB address), stops the txgen unit, and skips instances that do not exist yet.
- **Other**: `devnet-release-sign.sh` adds `GATEWAY_IMAGE_DIGEST`; `devnet-stake-node5.sh` fixes
  the empty-epoch guard (:510, :319) and reads node 5 and the reference head over IAP;
  `devnet-txgen.sh` uses enable + restart; `devnet-observability.sh` gains a staged mode and a
  scrape of the gateway metrics port where the native Alloy config allows a fragment;
  `devnet-dashboards.sh` moves to the native UI block.
- **Deploy steps**: 1 IPs · 2 VMs · 3 boot wait · 4 DNS pause · 5 keygen (all five advertise at
  keygen) · 6 genesis + manifest · 7 admission maps · 8 VPC rules · 9 obs VM · 10 finalize
  stage-only (the signature gate fires before anything is staged) · 11 host ufw · 12 observability
  staged · 13 gateway installs (no readiness assertion) · 14 coordinated start · 15 rpc-6 public
  edge · 16 post-checks (gateway ready, binds, `tn_*` refused, certificates, gateway metrics
  scrape) · 17 dashboards · 18 contracts · 19 txgen · 20 committee firewall.
- **Docs**: `tasks/runbook-l2-2026-11-17.md` (skeleton in W1, as-run in W3), rewrite of
  docs/mainnet-simulation-plan.md, the §7 wording fix in tasks/runbook-reset-2026-10-30.md,
  `tasks/challenges-l2.md` (see Part D).

## Part C: orchestration

Conventions: opus general-purpose agents for every unit and review (never fable); one deliverable,
explicit read/write paths, one writer per file, checkpoint `tasks/ckpt-l2-<unit>.md` (status header
+ completed sections, rewritten per section; "on start, read your own checkpoint and continue"),
summaries back. Gates on every edited script: `bash -n`, shellcheck, the repo's portability checks.
Commits by explicit pathspec, no attribution. Secrets never on argv, env or logs.
`TN_SKIP_RELEASE_SIG=1` is the user's only. Every gcloud call carries `--project tn-devnet`; fleet
drivers run detached with a recorded pid; nobody edits a driver that is running.

- **W0 (orchestrator)**: `project-context` for devnet-genesis and tn-node-deployment; confirm no
  bench run is in flight; `git ls-remote` both upstreams (if telcoin-network main moved, build the
  new tip and record the delta); create the two worktrees; seed `tasks/challenges-l2.md`; update
  the memory status line; write the frozen interface contract `tasks/l2-contract.md`:
  - gateway CLI, defaults 8655/8656/9655, exit codes, JSON event schema, `--status` fields,
    `gateway.meta` keys, unit path, `gw_*` signatures, exact gateway flag names from
    `bin/worker-gateway/src/cli.rs`, image allow-list and mainnet pin variable, who pulls the
    image (the unit runs `--pull=never`), `--enable` works with the node down;
  - Caddy block markers, phases and flags, probe paths;
  - validator side: what `--gateway-from` covers and where it persists, `gateway_upstream`
    rendering and behaviour on a stopped node, which code renders `--healthcheck`;
  - devnet names: array order (0-3 validators, 4 node 5, 5 rpc-6, 6 gateway-4), gateway modes,
    `GATEWAY_*`, `LEGACY_LB_*`, `TN_ADMISSION_VIA`, admission-map staging paths, helper names,
    the new drivers' CLIs and exit codes, steps 1-20 with the command each runs.
- **W1 (parallel after the contract; the orchestrator makes every commit)**:

  | Unit | Repo | Writes (one owner per file) |
  |---|---|---|
  | A1 / A2 | TND | `lib/gateway.sh` / `setup-gateway.sh` (both new) |
  | B | TND | `install-caddy.sh` |
  | C1 / C2 / C3 | TND | `lib/common.sh` (sole writer) / `firewall-setup.sh` / `edit-config.sh` |
  | D1 / D2 | TND | `check-node.sh` / `remove-node.sh` |
  | E1-E4 | TND | new `tools/tests/*gateway*_test.sh`, one per code unit, plus any existing test it breaks |
  | E5 | TND | gateway Docker smoke test (needs IMG) |
  | F1, then F2 | TND | OPERATOR.md, README, CHANGELOG · script list, version bumps, checksum sidecars (last) |
  | IMG | telcoin-network worktree | both images with `--load`, `CARGO_FEATURES=` empty, `node-record-api`; probes: commit sha, no faucet string, `tn_admissionSnapshot` present, gateway uid 1101 and `--help` flags |
  | RH0 | local | as soon as IMG has the node image: a short local run proving the epoch-0 `committee_peers` rule and node 5's native join config; its result amends the contract before Z1/N1/N2 finish |
  | G1 | DG | `config.sh`, `devnet-lib.sh`, `benchmark/config.sh` (lands first) |
  | G2 | DG | `devnet-keygen.sh`, `devnet-genesis-build.sh` |
  | N1 / N2 | DG | `devnet-network-config.py` + its bench test / `devnet-network-config.sh` |
  | Z1 / Z2 | DG | `devnet-finalize.sh` / `devnet-postcheck.sh` (new) |
  | GW / PC | DG | `devnet-gateway.sh` / `devnet-p2p-committee.sh` (both new) |
  | FW / SU | DG | `setup-firewall.sh`, `devnet-firewall.sh` / `devnet-startup.sh` |
  | SK / TX / TD / RS | DG | `devnet-stake-node5.sh` / `devnet-txgen.sh` / `devnet-teardown.sh` / `devnet-release-sign.sh` |
  | OB | DG | `devnet-observability.sh`, `devnet-dashboards.sh` |
  | SH | DG | shim harness for gcloud, ssh and scp (new) |
  | DP, DOC | DG | `devnet-deploy.sh` · docs and runbook skeleton (finish last) |

  TND = tn-node-deployment, DG = devnet-genesis. Large files are read by line range only.
  Critical path: contract → (IMG ∥ A1, A2, B) → E5 → F1 → F2 → reviews → push the PR → pin.
- **W2**: reviews R1a (TND binds and ufw), R1b (TND image trust, rollback, gateway and Caddy), R2a
  (DG config, keygen, admission, finalize, bench regression tests), R2b (DG drivers), in parallel
  across repos; fixes go back to the owning unit. Rehearsals: RH1 TND fixture suite and lint
  gates · RH2 the E5 smoke test with the real gateway image · RH3 a throwaway 6-key genesis run
  with the new node image and the files `setup-node.sh` writes for each role · RH4
  `devnet-deploy.sh` through step 20 on the shim harness with the PR head pinned. Then push the
  tn-node-deployment branch, open the PR, pin its head in config.sh, commit and push
  devnet-genesis.
- **W3 (GCP, operator present; each segment a fresh agent with `tasks/ckpt-l2-deploy.md`)**:
  1. **P1** operator: `gcloud auth login` (+ docker credential helper). Push both images, compare
     the digest three ways, re-run the probes by digest, pin, commit.
  2. Teardown: show the dry-run list, then `--yes`.
  3. **D1** steps 1-3; returns the static IPs of rpc-6 and gateway-4.
  4. **P2** operator DNS (TTL 60): `rpc.devnet` → rpc-6 IP (replaces the LB IP), `node4.devnet` →
     gateway-4 IP, delete `admin.node4.devnet`, add `admin.node6.devnet` → rpc-6 IP.
  5. **D2** steps 5-10; stops with `RELEASE_SIG_PENDING`. **P3** operator signs the manifest on the
     laptop (YubiKey), as in launch 1.
  6. **D3** steps 10-19 (one-node canary for the staged observability and gateway installs first).
  7. **D4** step 20 on validators 1-4; then try it on node 5 before staking and record the result.
  8. **S1** stake node 5 once it is synced from rpc-6; `activate()` in epoch N; watch for the
     allowlist entry (N+1), the admission window (N+2) and the first seat (N+3 or later).
  9. **V** verification (below), then close-out: challenges report, local issue drafts,
     tasks/todo.md review section, tasks/lessons.md, plan ticks, memory, commit and push.
  **P4** operator, non-blocking: point Kuma monitors at `https://nodeN.devnet…/ready/any`.

## Part D: challenges to flag (seed list for `tasks/challenges-l2.md`)

Each entry gets a status (fixed in the PR / worked around / reported) and evidence from the run.
1. No gateway support in tn-node-deployment (this PR).
2. telcoin-network publishes no gateway image or binary; CI never builds it; `--version` has no
   commit. Mainnet needs a pinned digest in a signed scripts release before launch.
3. Bare `--healthcheck <port>` now binds loopback; `setup-observability.sh` still emits the bare
   port, so health monitors and LB checks fail silently on any main-based release.
4. Validator RPC cannot bind a private address only (local readers hard-code loopback), so
   standalone mode uses a wildcard bind guarded by ufw.
5. No ufw rule for the RPC port, and `--reset` drops hand-added rules (fixed by `--gateway-from`).
6. `install-caddy.sh` dies on a node-less host and has no load-balancer backend mode.
7. `--p2p-committee` has no `--json`, no wait for an authoritative snapshot, and is a separate
   manual step per host.
8. The native admission renderer cannot express "bootstrap from a hub, committee peers = genesis
   set" for a joiner.
9. Upstream's public-RPC guidance (`--forward-txs`, `--sanitize-txs`) bypasses node records and
   has no script support; record forwarding leaves the gateway as the only pre-check.
10. One RPC node is one client IP to each gateway: 100 rps and 32 connections per validator, and
    a 429 demotes that gateway for 30 s.
11. A joiner's record lives only on the hub until a committee node fetches it; lookup backoff can
    delay its allowlist entry by up to 30 min.
12. `tn_*` (including the admission snapshot) is public on a native public-RPC node.
13. No native scrape for gateway metrics, nftables counters or the sync timer.
14. `install.sh` / `update-scripts.sh` cannot install a PR head; the devnet fetches by sha and
    bypasses MANIFEST verification. `MIN_ADMISSION_VERSION` is still a TODO.
15. No finalize `--no-start`; devnet stages by start-then-stop.

## Verification (numbers into `tasks/verification-l2-2026-11-17.md`)

`snap` = `tn_admissionSnapshot` on 127.0.0.1:8545 over IAP; `pas` = the installed tn-p2p-allow-sync.

| Property | Check | Expected |
|---|---|---|
| Admission | `snap` on six nodes; `tn_network_admission_mode` | five `effective: Closed`, `fallback: null`; rpc-6 Open; rpc-6 listed `trusted`, `admitted: true` on every validator |
| Firewall drops / accepts | UDP probe to a validator's 49590 from txgen (unlisted) and from a validator; `pas status` | drop counter rises for txgen, accept counter for the validator |
| Allowlist follows the chain | after `activate()` + one epoch + one timer run: `snap`, `pas check`, `nft list set` | node 5 `eligible`, its IP in the set, `check` exits 0 |
| Gateway is the only path | external `curl <ip>:8545`; `ss -ltn`; validator-4 probed from txgen and from gateway-4 | refused except gateway-4 → validator-4; `wss://nodeN` fails |
| `tn_*` blocked on validators | `tn_nodeMode` via `https://nodeN` without redirect semantics | 403, or answered by rpc-6 (its BLS key) when redirected |
| Record URL = gateway | `node-record-api /v1/rpcs` bootstrapped at rpc-6 | `https://nodeN.devnet…/`, no ws, for 4 validators, then 5 |
| Transaction path | `cast send` to `rpc.devnet`; rpc-6 `tn_reth_forwarded_txns_queued_total`; gateways `tn_worker_gateway_routed_requests_total{route="worker"}` | receipt status 1; counters rise on committee gateways only |
| Gateway limits | 300-request burst through one gateway; `…rejections_total{reason="rate_limited"}` | throttled per real client IP, not per Caddy |
| Join | `devnet-stake-node5.sh` watch; `tn_nodeMode` on node 5 over IAP | Active, then `CvvActive` in its first drawn epoch |
| Base fee | `devnet-basefee-check.sh --last 2` | PASS on every loaded boundary |
| Restarts | restart one gateway; restart one validator | `/ready` 503 → 200; node returns to `CvvActive`; nft table stays loaded |
| Sync with node down | stop a node, run the sync unit | result stale, set unchanged |
| Standalone parity | `check-node.sh` on validator-4 and gateway-4 | no errors; advertised URL equals the gateway URL |
| Release | `devnet-release-sign.sh verify` | VALIDSIG 4E36…7573 over both digests and the chain configs |

Before GCP: both repos' test suites and lint gates green; the local 6-key rehearsal starts all
roles; the shimmed deploy reaches step 20 without calling a real binary. Optional last check:
`install-caddy.sh` `rpc-unadvertise` then `rpc-advertise` on validator-4 with a restart each,
confirming the record clears and returns.
