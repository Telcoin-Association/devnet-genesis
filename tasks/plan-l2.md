# Plan tick list: devnet launch 2 (worker gateways, committee firewall, public RPC node)

Written 2026-11-17 (xerxes). The approved plan text is the brief of this session (copied in
`tasks/l2/plan-approved-2026-11-17.md`). This file is its tick list; it is separate from `tasks/plan.md`
because the bench 8 program is live in this working tree and owns that file.
Agent rules: `tasks/l2/agent-rules.md`. Contract: `tasks/l2-contract.md`. Orchestrator log:
`tasks/ckpt-l2-orch.md` (newest at the bottom). Fact sheets: `tasks/l2/facts/`. Briefs: `tasks/l2/briefs/`.

Standing rules: no attribution anywhere; opus agents for every unit and review, no fable agents; one
deliverable, explicit read/write paths, one writer per file, checkpoint per unit; the orchestrator alone
commits, pushes, runs `gh` writes and drives the fleet; no rebase, force, stash or reset; commits by
explicit pathspec (`git commit -m … -- <paths>`), `git diff --cached --stat | tail -1` before each;
every gcloud call carries `--project tn-devnet`; secrets never on argv, env or logs;
`TN_SKIP_RELEASE_SIG=1` is the user's only.

Approval covers (user, 2026-11-17): the teardown of chain 32285 and its five VMs; deleting the Google LB
stack; two new VMs with static IPs; a new branch + PR on tn-node-deployment; pushes to devnet-genesis
`main`; two new images in Artifact Registry. Not covered: posting any GitHub issue.

## Changes to the plan's premises, found at the start (2026-11-17T19:12Z-19:25Z)
- tn-node-deployment `origin/main` is 2813343, not b89ada4: two commits on top of `scripts-v2.1.0`
  (#67 node-requirements one-pagers, #63 `click` bump in `ui/requirements.txt`); no script changed. The
  `worker-gateway` branch is based on 2813343.
- The gcloud login is valid (the plan said expired). `gcloud config` project is `telcoin-network`; every
  call names `--project tn-devnet`.
- **The bench 8 session is live in the main working tree** (user, 19:17Z: "there is a benchmark running,
  but I want you to continue with the new devnet deployment regardless"). Its harness calls the root
  drivers `config.sh`, `devnet-lib.sh`, `devnet-finalize.sh`, `devnet-network-config.sh`,
  `devnet-keygen.sh`, `devnet-genesis-build.sh`, and it has uncommitted edits in `benchmark/config.sh`.
  Consequence: every launch-2 code edit is made in the worktree `/home/drtnarg/coding/telcoin/dg-l2`
  (branch `l2/launch-2`, base 884b760); `main` gets it by a merge after W2, when no bench driver or gate
  is running and the bench's effective configuration is shown unchanged. `tasks/plan.md` is left alone.

## W0 (orchestrator)
- [x] lessons reviewed; starting state checked (no bench instance in tn-devnet at 19:14Z; a local harness gate of the bench session was running)
- [x] `git ls-remote`: telcoin-network main 5533ff73a (unchanged); tn-node-deployment main 2813343 (moved, see above); devnet-genesis main 7122061 → 884b760 (bench session's commit)
- [x] worktrees: `tnd-l2-gateway` (branch `worker-gateway`), `tn-l2-img` (detached 5533ff73a), `dg-l2` (branch `l2/launch-2`)
- [x] agent rules `tasks/l2/agent-rules.md`
- [x] project-context for devnet-genesis and tn-node-deployment
- [x] fact sheets F-GW1, F-GW2 (partial: keytool flags come from the image's `--help`), F-TND1..4, F-DG1, F-DG2 (`tasks/l2/facts/`)
- [x] `tasks/challenges-l2.md` seeded
- [x] memory status line
- [x] the frozen interface contract `tasks/l2-contract.md` (v1) and the unit table `tasks/l2/units.md`

## W1 (units; the orchestrator commits)
tn-node-deployment (`tnd-l2-gateway`):
- [x] A1 `lib/gateway.sh` (912b9b1) · [x] A2 `setup-gateway.sh` (17e6776)
- [x] B `install-caddy.sh` (6b01c10; real-Caddy validation pending in E2)
- [x] C1 `lib/common.sh` (9d71e2f) · [x] C2 `firewall-setup.sh` (52e71ba) · [x] C3 `edit-config.sh` (684199e)
- [x] D1 `check-node.sh` (73c78a1) · [x] D2 `remove-node.sh` (a1e40d2)
- [x] E1-E4 fixture tests (e603fd5, e4d87e0, 405af9e, 36eedd6: 405 + 213 + 165 + 75 + 105 checks, bash 3.2 too) · [x] E5 gateway Docker smoke test (463e7d8: 43/43 on the real image) · real-Caddy smoke 47/47 on 2.8.4 and 2.11.9
- [x] F1 OPERATOR.md, README, CHANGELOG, AGENTS (10c2ddc; to re-check after the review fixes) · [x] F2 script list, version bumps, checksum sidecars (af0dc90, 3c9eb07; whole suite 79 files green under bash 5 and bash 3.2) · [x] F3 README changelog entries + release note `CHANGELOG/scripts-v2.2.0.md` (6361c9c)
telcoin-network (`tn-l2-img`):
- [x] IMG node image, gateway image, probes; both PUSHED 2026-11-17T19:48Z and verified by digest (`tasks/l2/image-digests.md`); node-record-api does not compile at 5533ff73a (challenge 28)
- [x] RH0 local run: contract §9 confirmed (`tasks/l2/rh0-report.md`; amendment A-5)
devnet-genesis (`dg-l2`):
- [x] G1 `config.sh`, `devnet-lib.sh`, `benchmark/config.sh` (7e63e54; bench effective configuration shown unchanged; image digests pinned) · [x] BT bench tests read the bench's own pins (contract A-8): whole bench suite at parity with main, module by module
- [x] G2 `devnet-keygen.sh`, `devnet-genesis-build.sh` (d503b47)
- [x] N1 `devnet-network-config.py` + its bench test (a401717) · [x] N2 `devnet-network-config.sh` (e714a72)
- [x] Z1 `devnet-finalize.sh` (771324c) · [x] Z2 `devnet-postcheck.sh` (3935d71)
- [x] GW `devnet-gateway.sh` (ad2f14e) · [x] PC `devnet-p2p-committee.sh` (d99dfb9, d7a83b0)
- [x] FW `setup-firewall.sh`, `devnet-firewall.sh` (9b1d25c) · [x] SU `devnet-startup.sh` (a9f1bb6)
- [x] SK `devnet-stake-node5.sh` (e74f81b) · [x] TX `devnet-txgen.sh` (1a3985a) · [x] TD `devnet-teardown.sh` (75bbc76) · [x] RS `devnet-release-sign.sh` (9c77db1)
- [x] OB `devnet-dashboards.sh` and the normal observability mode (2f40489) · [x] OB2 `devnet-observability.sh --staged` by start-then-stop (87ad798; challenge 37)
- [x] SH shim harness for gcloud, ssh and scp (`tasks/l2-shim/`, three units)
- [x] DP `devnet-deploy.sh` (0bc8056) · [x] DOC runbook skeleton (`tasks/runbook-l2-2026-11-17.md`), mainnet-simulation-plan rewrite, runbook-reset §7 fix (8331a0d)

## W2 (reviews, rehearsals, push)
- [x] R1a TND binds and ufw (3 High, 4 Medium, 12 Low: `tasks/l2/review-R1a.md`) · [x] R1b TND image trust, rollback, gateway and Caddy (4 Medium, 13 Low: `tasks/l2/review-R1b.md`) · [x] fixes FX-A1 (2329dfc), FX-A2 (ae6918a), FX-B (see the log; whole suite 79 files, 0 failed)
- [x] R2a DG config, keygen, admission, finalize, bench regression tests (0 High, 3 Medium, 6 Low) · [x] R2b DG drivers (1 High, 3 Medium, 8 Low) · [x] fixes FX-C (3682dc8), FX-D (e908c33), FX-D2 + two wording fixes by the orchestrator
- [x] RH1 TND fixture suite and lint gates (79 files, 0 failed, bash 5.3.9 and bash 3.2.57; lints clean) · [x] RH2 E5 smoke with the real gateway image (43/43) and a real Caddy (47/47 on 2.8.4 and 2.11.9)
- [x] RH3 throwaway 6-key genesis run with the new node image and the real launch-2 scripts (`tasks/l2/rh3-report.md`: nothing to change) · [x] RH4 shimmed `devnet-deploy.sh` through step 20: a fresh run of all twenty steps is clean (steps 18-19 stubbed at their invocation) · [x] RH5 local transaction path through real gateways (`tasks/l2/rh5-report.md`: works; 400/400 in a burst, one 429)
- [x] tn-node-deployment branch pushed, PR opened: **#68** (https://github.com/Telcoin-Association/tn-node-deployment/pull/68; body figure-checked, 113 items); CI: the macOS fixture job failed one check on the first head (a new test needed `timeout(1)`), fixed test-only in 79fb24e; all twelve checks pass on head 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (23 commits); that head pinned in `config.sh` (2689476) and fetched by sha from GitHub as a host does
- [x] `l2/launch-2` merged into devnet-genesis `main` (fast-forward to 2689476, 2026-11-17; no bench or fleet driver running; on the merged tree: bench suite 43 of 44 modules OK with `test_node_shapes` failing the same 4 cases as on `main` before the merge, the bench's effective configuration with no changed value, the shimmed deploy 1..20 clean), pushed

## W3 (GCP, operator present)
- [ ] P1 operator login; both images pushed, digests compared three ways, probes by digest, pinned, committed
- [ ] teardown: dry-run list shown, then `--yes`
- [ ] D1 steps 1-3 (static IPs of rpc-6 and gateway-4 returned)
- [ ] P2 operator DNS (TTL 60): `rpc.devnet` → rpc-6, `node4.devnet` → gateway-4, delete `admin.node4.devnet`, add `admin.node6.devnet`
- [ ] D2 steps 5-10 (stops `RELEASE_SIG_PENDING`) · [ ] P3 operator signs the manifest
- [ ] D3 steps 10-19 (canary first)
- [ ] D4 step 20 on validators 1-4, then tried on node 5 before staking
- [ ] S1 stake node 5; allowlist entry (N+1), admission window (N+2), first seat (N+3 or later)
- [ ] V verification table → `tasks/verification-l2-2026-11-17.md`
- [ ] close-out: challenges report, local issue drafts, tasks/todo.md review section, lessons, memory, commit and push
- [ ] P4 operator (non-blocking): Kuma monitors → `https://nodeN.devnet…/ready/any`
