# TODO — ConsensusRegistry fork rehearsal attempt 3: F=740 CROSSED LIVE, all gates green — 2026-07-22

The fork executed on devnet at 2026-07-22T21:23:57.9Z (epoch-closing block of 739) and the
fleet has been healthy through TWO post-fork boundaries. Image `adiri:v0.12.1-devnet-fork740`
(index sha256:032085fe…, tn-5 commit `2c0cea0d` on temp branch `devnet-registry-fork-rehearsal`)
now soaks fleet-wide until the operator's devnet reset. Attempt 2 (F=738) was cut short by
timing math; the 83-min COLD rebuild (buildkit cargo cache evicted) nearly killed F=740 too —
operator chose to keep 740 with ~80 min and the compressed window fit.

## Boundary evidence (the adiri go/no-go core)

- [x] G2 20:47Z: 5/5 byte-uniform on fork740 (image ID, FORKLIT, epoch 739, pack 445446 identical)
- [x] Quarantine: v2 (not in 739 committee) stopped 21:14:13Z after epoch pre-check
- [x] **G4-A**: `consensus registry fork applied` EXACTLY once on v1/v3/v4/obs5 with IDENTICAL
      tuple — code_hash=0xab86d348…d9b4 (== post-fork pin), eligible=Some(5),
      consensus_number=1482655, consensus_hash=0xbcc8f2a4…; zero fail-closed/migration/missing-
      record literals; epoch 740 everywhere; epochRecord[739] served; post-fork registry
      eth_getCode sha256 identical ×4; pack 445446→446077 uniform
- [x] G4-B + corrected liveness: 0 new errors; consensus +5/10s (log method — the RPC header
      "number" field is EXECUTION height, flat on idle devnet between boundaries)
- [x] **Quarantine-replay**: v2 started 21:39:06, replayed the fork block at 21:39:21 from cold
      catch-up with the IDENTICAL tuple; boot probe literals 0/0; rejoined 740's committee
- [x] **G5 (close of 740, 22:23Z)**: epoch 741 ×5; record published by exactly 740's committee
      (v2/v3/v4/obs5 =1, v1 =0 non-member); epochRecord[740] served ×5; 0 error literals since
      T0 ×5; pack 446707 byte-identical ×5; trigger did NOT re-fire (one-shot proven both sides)
- [x] **Committee-member restart**: v4 (in 740 AND 741 committees) restarted 22:29:22Z; probe
      0/0; epoch 741; rejoined +6/10s; registry code byte-identical (id-echo artifact resolved:
      comparator hashes must cover the JSON `result` only, or pin the request id — result-only
      sha256 a4a117b82195d516e3ad89872fb5f66f1459c208a182c048845667afd5b22153)
- [x] Fail-closed: positive leg = unit test under shipped faucet shape; live leg = zero
      "failing closed" literals fleet-wide through both boundaries

## Proves for adiri / does NOT prove

PROVES: live swap+migration inside a certified close (before applyIncentives/concludeEpoch,
eligible-count guard fed by migration in the same block); determinism (identical tuple on 4
live executors + 1 cold replayer); one-shot trigger both sides; post-fork boot probe; two
post-fork closes incl. committee attribution; down-node-at-boundary catch-up; committee-member
restart/rejoin; fleet byte-uniformity; forward+reverse operator update runbook (reverse
exercised in attempt 1).
DOES NOT PROVE: adiri-shape build (same arm, different cfg combo — needs adiri build + its own
image verify); migration gas at adiri's real validator/NFT count vs 30M syscall cap
(forks.rs checklist: archive-resync dry-run measures it); adiri live registry hash == pin
(eth_getCode adiri BEFORE deploy); multi-operator convergence; legacy-getValidators RPC
consumers breaking at the fork (comms task).

## Standing items

- [ ] **NEVER deploy fork722** (boundary passed unforked 07-22 03:23Z; replay across 721
      diverges). fork740 is the LIVE fleet image — fine until the planned devnet genesis reset;
      after reset, delete both tags from the registry (operator call).
- [ ] tn-5 temp branch `devnet-registry-fork-rehearsal` (0cb56cda, 6a56c344, dc7e093a stale-722,
      2c0cea0d) stays LOCAL, no push; the adiri-gated production patch is a separate cut from
      the permanent diff + adiri-checklist items above.
- [ ] `make test-faucet` rot (bin lost tests/): retarget to `-p e2e-tests --features faucet`.
- [ ] Cold-build hazard: buildkit cargo cache eviction turned the 9-min devnet build into 83
      min mid-window. Before any future timed rollout: warm/verify the cache (or budget cold).
# TODO — ConsensusRegistry fork rehearsal attempt 1: staged to canary, ABORTED at fleet gate (no operator for stagger) — 2026-07-22

Goal: watch the ConsensusRegistry fork execute live on devnet before the adiri deploy.
Temp branch `devnet-registry-fork-rehearsal` (tn-5, off `3539f1b5`): fork machinery gate
widened `adiri` → `any(adiri, faucet)` (7 sites), ungated POST_FORK code-hash pin + pin
test, two-close fork-test extension. F=722 (boundary 2026-07-22T03:23:49Z). Everything
gated green through canary; the fleet stagger is an operator step and no operator action
arrived within the T0−30 window → clean abort at 02:25Z, fleet restored byte-uniform on
v0.12.1-devnet before the boundary. The 721 close then executed LEGACY, fleet-wide, by
design. All prep is preserved and re-cuttable.

## What passed (all reusable for attempt 2)

- [x] Stage 1 prep commit tn-5 `0cb56cda` + review-fix `6a56c344` (comment-only): the
      permanent part of the diff — REVIEW-CLEARED, matrix-green; only the 1-line F commit
      (`dc7e093a`, F=722, now stale) needs replacing with F′ at next cut
- [x] Scoped review (agent + traced verify): CLEARED, 0 Critical/High; 3 doc-rot findings
      fixed; key holds: swap-arm reachability closed under gated trigger; mainnet default
      build fork-free; adiri build byte-unchanged (tn-types faucet flag is empty); no
      unchecked epoch+1 in close path (second close concludes u32::MAX under overflow
      checks, passes); two-close test proven non-vacuous; pin test hashes the exact bytes
      runtime hash_slow commits (alloy const-hex handles 0x; revm 8.0 hash_slow =
      keccak(original bytes))
- [x] Matrix: 3 bin shapes check-clean; tn-types faucet 104/104; tn-reth fork tests 7/7
      under BOTH faucet and adiri; tn-reth faucet 104/104; workspace 1074/1074.
      `make test-faucet` is ROTTED AT BASE (targets --package telcoin-network --test it;
      bin has no tests/ dir) — substitute `cargo nextest run -p e2e-tests --features
      faucet`: 3/4, the 1 fail (faucet drip, local-testnet connection-refused) reproduces
      byte-identical at base in a clean worktree → environmental, diff-neutral
- [x] Step-0 pin check on LIVE devnet: eth_getCode(0x07E1…17e1) keccak ==
      0x5318ebc5cd8123cfb0808fac0f3c0b95ed6f45f67c0853fea0766b52035fea53 (positive check)
- [x] Image `adiri:v0.12.1-devnet-fork722` from `dc7e093a` built+pushed, VERIFIED both
      platforms (SHA match; fork literal 2 vs baseline 0; artifact snip present); index
      digest sha256:79e81488dcfc85018af13f88ba1edfed76106f882fe5c7248c7927533c04c29d
      (amd64 0c64e59c…, arm64 7deb1aaf…)
- [x] Canary validator-1 on fork722: apply ok, 2 gates 5 min apart ALL GREEN (0 probe/
      panic literals, epoch fleet-locked, consensus advancing on a MIXED committee) —
      live proof the fork build is behaviorally identical pre-boundary + the operator
      update runbook round-tripped (forward AND reverse)
- [x] Committee reads via `tn_getCommitteeValidators [epoch]` (ring buffer serves
      current+1/+2): 721 = {v3, v2, obs5, v4} → quarantine would have been v1;
      722 = {v3, v1, v2, obs5}. observer-5 is STAKED + committee-active (activation 94)

## Abort record (02:25Z)

- [x] Deadline protocol: fleet-stagger launch needed by ~02:20Z for G2-by-02:53:49Z
      (T0−30); v2 checks 02:05/02:13:30/02:25 all showed old image + fork722-not-pulled;
      3 escalating operator prompts (terminal active, no action)
- [x] Abort executed: config.sh:23 reverted; validator-1 reverse-updated (image on disk,
      ~1 min); verified back on fleet ID sha256:4f0af5f1… with FORKLIT 0, consensus
      advancing, epoch 721 — fleet byte-uniform pre-boundary; 721 closed legacy
- [x] Why mandatory: a lone fork-build node at the 721 close re-executes the certified
      legacy block, fires the swap locally, and diverges (state-root mismatch)

## ⚠ Standing hazards

- [ ] **NEVER deploy `v0.12.1-devnet-fork722`** now that epoch 721 closed unforked: any
      replay across the 721 boundary (resync/onboarding) fires the swap against
      legacy-certified history and diverges. Registry-side delete is the clean fix —
      operator call. (config.sh carries the warning comment.)
- [ ] `make test-faucet` rot (tn-5 mainline): retarget to e2e-tests faucet run

## Attempt 2 quickstart (~45 min lead time from "go", operator PRESENT for stagger)

1. tn-5 branch: replace `dc7e093a` with new 1-line F′ commit (F′ = current epoch + 2/+3
   per the 105-min rule; const at crates/types/src/forks.rs:101)
2. Phase B: faucet check + fork tests + grep const; re-verify artifact keccak ==
   0xab86d3482b618e6b1d1ba9b610f1f87d1a1a7ec1d935212978908a56f2d9d9b4
3. `make docker-devnet TAG=v0.12.1-devnet-fork<F′>` (~9 min warm) + image-verify battery
   (NOTE: `Build Features:` is EMPTY in ALL fleet images incl. baseline — feature-shape
   proof = fork-literal grep + build log + chain-id boot guard; do NOT assert on it)
4. config.sh flip → canary v1 (forward runbook proven) → OPERATOR stagger → G2 sweep →
   committees at F′−2 → quarantine the non-member → G3/G4/G5 gates as planned
# TODO — v0.12.1-devnet epoch-691 wedge recovery: review-gated fix + rollout — 2026-07-20

Devnet died at epoch-691 close: v0.12.0-devnet (CARGO_FEATURES=faucet) compiled out the
adiri-gated legacy-ABI ConsensusRegistry routing → every epoch-close reverted
(gas_used: 21510) → no epoch record → fatal "Missing previous epoch record" on restart,
fleet-wide. Fix branch `fix/devnet-prefork-registry-v0.12.1` (tn-5 commit `151b40f0`,
LOCAL — push at operator's discretion): code-hash-keyed legacy routing (no cfg gates),
epoch-record writes on all 3 close arms, persist-after-save fsync barrier, startup
registry-ABI probe (fail-fast), deterministic fleet-crash e2e (runtime env hook
TN_TEST_EXIT_AFTER_BOUNDARY_PERSIST), CI feature-shape matrix.

## Review gate (multi-agent, PASSED)

- [x] Wave 1: tn-pr-reviewer pipeline + 4 hypothesis panels (H1-H8) — 0 Critical,
      0 diff-introduced High; 1 pre-existing High (M1⊕V1 composed crash window
      [closing-block executed → record fsync-durable], diff narrows it)
- [x] Wave 2: findings-verifier over 9 panel survivors — all confirmed; V1 narrowed to
      hard-kill-only (SIGTERM persists via Drop)
- [x] Wave 3 verdict: PASS (APPROVE_WITH_FIXES); M2 doc fix + V1 persist() designated
      pre-build; M1 full re-derivation fix FLAGGED FOR HUMAN (not shipped)
- [x] Tests: workspace 1100/1100; restart e2e 5/5 (fleet-crash test 322.7s flaky-FAIL →
      34.2s deterministic PASS after hook); scoped re-review R1+R2 CLEAN

## Rollout (COMPLETE — two clean epoch crossings)

- [x] Image adiri:v0.12.1-devnet built+pushed from 151b40f0; verified (SHA + legacy
      literal present in binary)
- [x] Canary validator-1: replay-closed 691, published record, entered 692, all 5 gates
      green
- [x] Fleet ./devnet-update-all.sh (operator-run): v2/v3/v4/obs updated, v1 skipped
- [x] Crossing 1 (692→693, stale-anchored → immediate live close): all 5 nodes, 0 errors
- [x] Crossing 2 (693→694, fully live): all 5 nodes epoch=694, missrec=0, revert=0,
      uptimes continuous, epochs.pack byte-identical 418314 on all 5, consensus headers
      advancing (~1.389M)

## Follow-up tickets (from review + rollout; tn-5 side unless noted)

- [ ] P1: reth hard-kill torn-write boot panic — SIGKILL mid-block-execution →
      "the hash for the latest block is missing, database is corrupt"
      (reth node_config.rs:420, checkout d6324d6); PERMANENT until manual repair.
      Evidence: tn-5/crates/e2e-tests/test_logs/restart_boundary_replay (2026-07-20 run 1)
- [ ] M1 local record re-derivation in open_epoch_pack missing branch (FLAG FOR HUMAN;
      design in review pipeline report) + W2-window e2e kill case
- [ ] Record store: byte-compare on save + divergence alarm; fix false "Over wrote" log +
      got_epoch_record masking (epoch_votes.rs)
- [ ] Stale chain-configs/mainnet/genesis.yaml (chain-487, dead third registry) —
      regenerate with identity check before any mainnet planning
- [ ] final_state decoupling: derive from closing output or assert number equality
      (close_epoch.rs:230; invariant now relied on at 3 sites)
- [ ] Adiri fork-readiness PR: real CONSENSUS_REGISTRY_FORK_EPOCH + post-fork code-hash
      pin + cfg-not-adiri fail-closed swap arm + const-assert + adiri-shape CI RUN job +
      test-and-attest.sh feature-shape checks + maintainer-PR skip fix
- [ ] e2e hardening: legacy-genesis (pre-fork registry) e2e variant; leftover-drain
      full-run_epoch drive; direct 4-way record-digest assert; find_in_node_run_logs
      mid-file-error fail-open; per-arm audit logs (M7)
- [ ] BLS keyfile weak-KDF re-wrap (1 PBKDF2 round; warning on every node start)
- [ ] Probe diagnostics: route through classified_registry_read (infra fault ≠ build
      mismatch); optional full post-fork selector mirror
- [ ] update-node.sh detector labels validators "observer" (cosmetic)
- [x] devnet-genesis: regenerate devnet with NEW registry in genesis after the adiri
      fork test validates (retires the legacy path on devnet) — DONE 2026-09-17, see
      "Devnet full wipe + redeploy on v0.1.0-devnet" at the end of this file



Plan: make `devnet-update.sh`'s default a SAFE image-only update (the old default wiped
chain data unless `--no-wipe` was remembered), and add `devnet-update-all.sh` for
wire-protocol-breaking upgrades (v0.12.0's chain-id-namespaced gossip topics fragment a
staggered rollout). Both drive the SAME on-node `tn-node-deployment/update-node.sh --json`
that individual operators use — which required fixing its wrapper-blindness first.
No network-config migration (verified unnecessary; operator opted to skip).

## Repo 1: tn-node-deployment (pushed to GitHub main: 7b10e97)

- [x] `SCRIPT_VERSION` 1.1.55 → 1.1.56 in update-node.sh
- [x] `VERIFY_TIMEOUT_SECONDS` env-overridable via `TN_UPDATE_VERIFY_TIMEOUT` (numeric guard, 45 fallback)
- [x] New `docker_launch_file()` — resolves wrapper vs legacy unit via `tn_node_launch_target`
- [x] `detect_current_docker_image` greps the resolved launch file (+ 2 error strings)
- [x] `apply_docker_update` + `json_apply_docker` patch the launch file (backup/sha/perl/grep/restore/rollback)
- [x] `backup_unit_file`: info line → stderr (was corrupting the `$(...)`-captured backup path)
- [x] update-scripts.sh 1.1.61 → 1.1.62 (re-bootstrap trigger); `tools/gen-checksums.sh` sidecars fresh
- [x] README Changelog entry (`### update-node v1.1.56`)
- [x] `bash -n` + `shellcheck -x --severity=error` clean; advisory warning count unchanged (12 pre-existing)
- [x] Pushed to origin/main; raw.githubusercontent serves v1.1.56 with the marker

## Repo 2: devnet-genesis

- [x] devnet-lib.sh: `tn_cmd_refresh_scripts` / `tn_cmd_update_check` / `tn_cmd_update_prepare` / `tn_cmd_update_apply <secs>`
- [x] devnet-lib.sh: jq-free parsers `tn_json_done_line` / `tn_json_check_line` / `tn_json_str` / `tn_json_true` (BSD-sed safe)
- [x] devnet-update.sh: `MODE=image` default; `--wipe` / `--finalize` explicit; `--no-wipe` deprecated alias → image mode; conflicts error
- [x] devnet-update.sh: phase 0 refresh clones (marker-gated, aborts before any downtime)
- [x] devnet-update.sh: `update_one_image` (check → skip-if-current → prepare → apply @120s verify → stagger + wait_healthy; abort on first failure)
- [x] devnet-update-all.sh: NEW parallel script — phases 0-3, CONFIRM gate, marker files, per-node verdicts, idempotent re-run, exit 0 only if all UPDATED/SKIPPED+healthy
- [x] Lint: `bash -n` (5.x + macOS 3.2) + `shellcheck -x` clean on all three
- [x] Submodule pointer bump + commit

## Rollout — DONE (2026-07-18)

1. [x] Single-node smoke on observer-5-devnet: fixed refresh chain exits 0 ("Already up to
   date" + privileged marker grep OK).
2. [x] `./devnet-update-all.sh --yes` → all phases green, summary: all 5 nodes UPDATED +
   healthy, exit 0 (logs/20260718_162345-update-all).
3. [x] Post-checks: `docker ps` shows adiri:v0.12.0-devnet on all 5; wrapper carries the
   new ref; consensus ADVANCING on all 5 (consensus_number +6 and committed_round +12 per
   10s window). NOTE: liveness = consensus_number/committed_round in the telcoin logs —
   `eth_blockNumber` stays flat on idle devnet (empty non-epoch-closing outputs skip
   execution). Also: on v0.12.0 the observer binds RPC at :8545/:8546, NOT the old
   instance-adjusted :8541/:8554.
   Rollback (if needed): revert config.sh:22 to the old tag, re-run devnet-update-all.sh.

## Review (2026-07-18)

**tn-node-deployment (7b10e97):** update-node.sh's docker path read/edited only the systemd
unit, but current installs carry the image in the root-owned wrapper
`/opt/telcoin/start-telcoin.sh` — so `--check` returned an empty `current_ref` and
prepare/apply hard-failed fleet-wide. Fixed via `docker_launch_file()` (delegating to the
existing `tn_node_launch_target`); every guard and the JSON event contract kept
byte-compatible. Rode along: `TN_UPDATE_VERIFY_TIMEOUT` override (fleet restarts re-form
quorum slower than the 45s window → spurious auto-rollback), and the `backup_unit_file`
stdout-capture fix.

**devnet-genesis:** default `devnet-update.sh` can no longer wipe the chain by omission —
wipe/finalize are explicit flags, and the new default is check→prepare→apply→health-gate
per node through the operator tooling. `devnet-update-all.sh` handles protocol-breaking
cuts: barriers before downtime (refresh + prepare abort with the fleet untouched), apply
runs all-at-once to a terminal state per node, and the summary classifies
UPDATED/SKIPPED/ROLLED BACK/APPLY FAILED/UNKNOWN/UNHEALTHY with re-run guidance.

**Verification (all green):**
- `shellcheck -x` clean (devnet scripts); tn-node CI blocking gate clean, advisory count unchanged.
- 16-assertion parser/builder harness under macOS `/bin/bash` 3.2 with `set -euo pipefail`.
- 10 offline end-to-end dry-run scenarios against a fake `gcloud` emulating the `--json`
  contract: fresh-fleet update, idempotent re-run (all SKIP, phase 2 skipped), ROLLED
  BACK + UNKNOWN verdicts (exit 1), convergence re-run, prepare-failure abort BEFORE
  downtime, refresh-failure abort with nothing touched, staggered default flow,
  `--no-wipe` deprecation → image mode, conflicting-flags error, staggered
  abort-on-rollback (later nodes untouched).
- Checksum sidecars verified fresh; raw.githubusercontent.com serves v1.1.56.

**Could not run live (needs the real fleet):** observer-5 smoke + the actual v0.12.0-devnet
cut — listed under Rollout above.

## Fix (2026-07-18, later): phase-0 false failure — unprivileged marker grep

The live all-at-once run aborted in phase 0 on ALL 5 nodes even though GitHub main was
current. Per-node logs showed the pull as `telcoin` succeeded ("Already up to date") and
then `grep: /home/telcoin/telcoin-node-scripts/update-node.sh: Permission denied` —
`tn_cmd_refresh_scripts` ran both git commands via `sudo -u telcoin` but the trailing
marker grep unprivileged, and the SSH login user can't read under /home/telcoin (0750).

- [x] devnet-lib.sh: marker grep now `sudo -u ${SERVICE_USER}` (fixes BOTH drivers; comment
      states the every-command-privileged rule)
- [x] devnet-update-all.sh `run_phase`: failure branch prints the last 5 log lines indented
      (tail -1 only showed the job's own summary echo, hiding the real error)
- [x] Hints broadened (phase0_one echo + devnet-update.sh phase-0 abort): name both common
      causes — main not pushed, or the node-side command errored (read the log)
- [x] Verified: bash -n (5.x + 3.2) + shellcheck -x clean; 16-assertion harness green under
      /bin/bash 3.2 (refresh expectation updated); offline fake-gcloud fresh-fleet run all
      UPDATED exit 0; refresh-fail run shows the raw remote error on console and aborts
      with nothing touched

# TODO — Make `tn-node-deployment` operator-self-sufficient — 2026-06-30

Boundary rule: **no operator-facing script may reference a `common/` script as a runtime step.**
Each agent bumps the version header of every *tracked* file it edits but does NOT run
`gen-checksums.sh` (orchestrator runs it once, last). README.md edits owned by orchestrator.

- [x] **Track A**: D1 `migrate-node-naming.sh` (1.0.4→1.1.0; config-caddy.sh dropped from operator guidance, only the maintainer-only provenance comment remains; `restart_ui_if_present` non-fatal at step 11.5) + D2 new `AGENTS.md`.
- [x] **Track D**: firewall audited (all 6 properties confirmed, no change); WG re-vendored (body byte-identical to canonical, picked up H1 `WG_NODE_FIREWALL` hardening, header sha→b2928a23/date→2026-06-30, docs sync note 14→16 lines); `setup-vpn.sh` 1.2.0→1.3.0; observability audited (no change).
- [x] **install-caddy.sh** (1.1.4→1.2.0): two-vhost fence manager + node-info.yaml worker-rpc writer + brick guard + ufw. JSON contract `rpc-status|rpc-check-dns|rpc-enable|rpc-disable` + `--rpc-domain` locked & consumed by the UI helper.
- [x] **Track B+C**: D3 UI parity (instance control 100% removed; `log_file`→/var/log/telcoin/telcoin.log, `wrapper_path`→/opt/telcoin/start-telcoin.sh; 5 cosmetic labels → API `service`) + D4-0 `install-ui.sh` ships `fallback.sh` + D4-6 RPC UI (4 routes, helper wrappers, 4 sudoers, `#rpcCard`+consent). `server.py` UI_VERSION 1.7.67→1.8.0, `install-ui.sh` 1.2.9→1.3.0.
- [x] **Final**: README pointer + metrics 9000→9101; 34 sidecars regenerated (8 edited tracked files fresh, zero drift); full lint sweep + version audit + maintainer regression — all green.

## Review (2026-06-30)

Implemented across 1 orchestrator-authored file + 3 parallel subagents (Track A migrate+docs, Track D add-ons, Track B+C UI). **12 tracked/doc files changed** (8 tracked → 8 fresh `.sha256`; README/docs/test untracked; new `AGENTS.md`).

**Operator self-sufficiency achieved:** an operator with only `tn-node-deployment/` can migrate a legacy node (no `config-caddy.sh` dead-end — only a clearly-marked maintainer provenance comment remains), expose `https://rpc.nodeN…/`+`wss://` via `install-caddy.sh` (advertised in `node-info.yaml` worker.rpc), and drive it all from CLI **or** UI. `AGENTS.md` records the boundary so future agents don't reintroduce a `common/` runtime dependency.

**Verification (all green):**
- `bash -n` 5.x **and** `/bin/bash -n` 3.2 + `shellcheck --severity=error` on all 6 edited shell files.
- `caddy validate` PASS on the generated dual-vhost Caddyfile; `caddy fmt`-clean.
- node-info writer: **43 assertions** across `rpc: ~` / `null` / absent / multiline + worker-at-EOF + primary-has-block (worker-only, primary/execution untouched, idempotent set+clear).
- block-fence round-trip preserves the dashboard bcrypt `$`-hash verbatim (L411).
- URL brick-guard validator: 9 assertions (rejects wrong-scheme/space/path/oversize).
- `test_public_readonly` **7/7** in a Flask venv: RPC write routes 403 on the public path, status READ allowed.
- `py_compile` server.py + test; 34 sidecars fresh (zero drift); 5 versioned files bumped; fleet driver verified unaffected (reads migrate version dynamically — no pin to break).

**Could not run live (no test node):** full operator migration sim, RPC E2E restart/advertise, and the 4-0 `fallback.sh` runtime source-check — all verified structurally instead (static script review + the install-ui.sh ship edit). Flagged for on-node confirmation before deploy.

**Not pushed/committed** — working tree only, awaiting operator review.

---

# TODO — Collapse observer/validator node distinction in tn-node-deployment — 2026-06-26

Target: submodule `tn-node-deployment` on `main`. One node identity; no `--observer` emitted;
every node provisioned validator-capable; UI auto-selects view from on-chain `tn_isValidator`.
Commit in submodule → (await go-ahead) push origin/main → bump devnet-genesis pointer.

## Phase 1 — Decouple from the flag (resolver + firewall) [me] ✅ DONE & VERIFIED
- [ ] `lib/fallback.sh`: delete `_tn_wrapper_has_observer()` + now-unused `_tn_install()`; `tn_resolve_node_type` last-resort default → `observer`
- [ ] `lib/common.sh`: `check_hardware()` gates on baseline OBSERVER_MIN_*; prints VALIDATOR_MIN_* as info note
- [ ] `firewall-setup.sh`: open+expect 49590/49594 UDP for ALL installed nodes; drop validator-only gates, observer "close P2P" branches, and the non-validator drift finding

## Phase 2 — Mgmt scripts gate on runtime on-chain status [subagent] ✅ DONE & VERIFIED
> + 2 follow-up fixes I applied (completing the plan's intent, flagged by the agent):
>   - `update-node.sh` JSON `--yes` gate re-gated on `node_is_onchain_validator_or_unknown` (was static NODE_TYPE==validator)
>   - `check-node.sh` local-RPC default: same observer⇒8541 latent bug fixed → derive from .node-meta RPC_PORT (8545)
> + cosmetic hints in update-node.sh / edit-config.sh → setup-node.sh.
> (setup-observability.sh / setup-vpn.sh hints left as-is — shims keep them valid, avoid unrelated bumps.)
- [ ] `check-node.sh`: derive is_validator from registry; absent-from-headers = ERROR only if registered validator; always attempt on-chain when VALIDATOR_ADDRESS set; keep --observer/--validator as manual overrides only
- [ ] `update-node.sh`: fix RPC_URL to derive from .node-meta RPC_PORT (default 8545); gate committee-window warning on tn_isValidator not NODE_TYPE
- [ ] `edit-config.sh`: drop NODE_TYPE requirement; operate on single resolved unit

## Phase 3 — Unified setup [me] ✅ DONE & VERIFIED (wrapper-diff = 0)
> DISCOVERY: `ui/install-ui.sh` copies setup scripts to `/opt/telcoin-ui-update/` for the
> UI dispatch — added `setup-node.sh` there too (shims exec it). Rides on UI_VERSION bump.
- [ ] New `setup-node.sh` from setup-validator.sh superset; NODE_TYPE=observer + always VALIDATOR_ADDRESS; no --observer in wrapper; role-neutral framing
- [ ] `setup-observer.sh` / `setup-validator.sh` → 2-line exec shims
- [ ] `install.sh`: next-steps → setup-node.sh (keep chmod of shims)

## Phase 4 — Migration (migrate-node-naming.sh) [subagent] ✅ DONE & VERIFIED
- [ ] Remove incorrect staking warning; update_meta writes NODE_TYPE=observer; rewrite_wrapper keeps --observer strip + reword; rewrite_unit role-neutral Description; NEW step opens 49590/49594 UDP; reword report epilogue; preserve snapshot/rollback

## Phase 5 — UI collapse [subagent] ✅ DONE & VERIFIED (shape test: validator/observer/hint all correct)
- [ ] `ui/server.py`: bidirectional remap in detect_nodes; drop --observer probe in resolve_node_type (default observer); /api/nodes adds top-level `role` + `node` summary
- [ ] `ui/static/index.html`: remove two tab buttons; drive state.node=d.role w/ installedType() fallback; view switch flips on on-chain role; setup wizard unified; cosmetic relabels

## Phase 6 — Docs [subagent] ✅ DONE (review diff at integration)
- [ ] `README.md`: collapse Node Types/hardware/firewall/onboarding into "Run a node" + "Become a validator (optional)"
- [ ] `CHANGELOG.md`: add Unreleased entry

## Verification (final)
- [ ] bash -n + shellcheck every changed .sh
- [ ] py_compile ui/server.py; run ui/test_public_readonly.py
- [ ] extract JS from index.html → node --check
- [ ] Wrapper diff proof: setup-node.sh wrapper == setup-validator.sh wrapper, zero diff, no --observer
- [ ] Resolver unit test (TN_ROOT_PREFIX temp tree): default observer, honors explicit NODE_TYPE
- [ ] Migration dry-run: source migrate-node-naming.sh, test rewrite_wrapper sed on fixtures
- [ ] /api/nodes shape test: mock onchain_is_validator → role validator/observer/hint

## Review — 2026-06-26 (all phases complete, verified, committed locally; NOT pushed)

**Outcome achieved.** One node identity. `setup-node.sh` is the canonical installer (built from
setup-validator.sh, the de-gated superset); `setup-observer.sh`/`setup-validator.sh` are 17-line
`exec` shims forwarding to it. No `--observer` is emitted into any launch wrapper anywhere — it
survives ONLY as (a) manual diagnostic overrides on check/update/edit scripts, (b) the token the
migration STRIPS from legacy wrappers, (c) docs. Firewall opens UDP 49590/49594 on every installed
node. UI auto-selects validator vs full-node view from on-chain `tn_isValidator` (bidirectional).

**Execution.** Phases 1 & 3 done directly by me; Phases 2/4/5/6 by 4 parallel background subagents,
each diff-reviewed. I caught + completed two in-scope items the Phase-2 agent flagged (JSON `--yes`
gate + check-node local-RPC bug) and one plan gap (install-ui.sh must copy setup-node.sh to
/opt/telcoin-ui-update for the UI-path shims). See [[two deploy paths]] lesson.

**Verification (all green, runnable-here):**
- `bash -n` on all 13 changed .sh → PASS. `shellcheck -S error` → only 1 finding (update-node.sh
  SC2259) confirmed PRE-EXISTING in HEAD (untouched line).
- `py_compile ui/server.py` → PASS. `test_public_readonly.py` → 7/7 PASS (isolated venv).
- Extracted UI JS → `node --check` PASS.
- **Wrapper-diff proof**: setup-node.sh's 4 generated wrappers == original setup-validator.sh's,
  byte-for-byte (modulo attribution comment); zero `--observer`.
- **Resolver unit test** (TN_ROOT_PREFIX temp tree): default→observer, honors explicit NODE_TYPE,
  legacy role dirs still resolve, no `--observer` probe fn. 6/6 PASS.
- **Migration**: rewrite_wrapper `--observer` strip + guard verified (GNU sed); rewrite_unit
  Description sed proven role-neutral for both legacy forms.
- **/api/nodes shape test**: role = validator(True)/observer(False)/hint(None), demotion works.
- **Version-bump audit**: all 12 gated files bumped (caught 3 I'd missed — see [[Version-bump blind spot]]).

**Self-caught issues fixed:** 3 missed version bumps (firewall/common/fallback); install-ui.sh copy
gap; 2 Phase-2 follow-ups; stale UI setup-wizard intro note.

**Operator-only (cannot verify here):** ufw shows 49590/49594 open post setup/migrate; fresh public
install → plain dashboard no warnings; stake+activate → dashboard auto-flips; migrate a real legacy
observer + induced-failure rollback.

**Remaining (awaiting go-ahead):** push submodule `main` → origin/main; bump devnet-genesis pointer.
Lower-priority follow-ups noted by agents (NOT done, out of scope): unused selector CSS in
index.html; the `_docker_node_type` PoP heuristic relaxation.

---

# TODO — Migrate legacy `telcoin-observer` node5 → unified `telcoin` + fix UI validator detection — 2026-06-25

Two pieces in the `tn-node-deployment` submodule (node-side scripts are a git clone gated by
`update-scripts.sh`, [[bump-version-on-gated-file-edit]]):

## Part A — `migrate-node-naming.sh` (new on-node script)
- [x] Header `readonly SCRIPT_VERSION="1.0.0"`; source `lib/common.sh` (resolvers + print helpers).
- [x] Detect legacy unit/role/dirs (scan `telcoin-{validator,observer}.service` directly); idempotent guard + custom-layout guards.
- [x] Snapshot unit+wrapper+.node-meta to `*.bak.<ts>`; ERR-trap rollback (mv dirs back, restore baks, restart legacy). **Needs `set -E`.**
- [x] Stop+disable legacy; `docker rm -f` lingering container.
- [x] Relocate `/etc/telcoin/<role>`→`/etc/telcoin` and `/var/lib/telcoin/<role>`→`/var/lib/telcoin` (collision-guarded, dotglob).
- [x] Rewrite unit → `telcoin.service` (path subs + Description); rewrite wrapper → `start-telcoin.sh` (path subs + DELETE `--observer`).
- [x] `.node-meta`: `NODE_TYPE=validator`, `DATA_DIR=/var/lib/telcoin`, optional `VALIDATOR_ADDRESS`; ports unchanged.
- [x] rm legacy unit+wrapper; daemon-reload; enable+start `telcoin`; verify active + `eth_chainId`; report.

## Part B — UI: detect staked validator via `tn_isValidator`, auto-select validator tab
- [x] `server.py`: `_b58decode` + `bls_pubkey_to_hex` (base58→0x 96-byte hex; stdlib only).
- [x] `server.py`: `onchain_is_validator(t,det)` cached ~30s — synced AND `tn_isValidator(hexkey)`==true.
- [x] `server.py`: `detect_nodes()` remap observer→validator slot (after docker detect; `staked` marker).
- [x] `server.py`: `/api/nodes` `staked`; `/api/status` `is_validator_onchain`; bump `UI_VERSION` 1.7.65→1.7.66.
- [x] `static/index.html`: poll-time tab auto-switch when current tab uninstalled; small `staked` badge.

## Version gating + verification
- [x] `update-scripts.sh`: add `migrate-node-naming.sh` to SCRIPTS; bump its own `SCRIPT_VERSION` (1.1.57→1.1.58).
- [x] Static: `bash -n`; dry-run sed against node5 fixtures (docker + binary): unified paths, `--name telcoin`, no `--observer`.
- [x] Static: `py_compile`; unit-test b58 against node5 key (→96-byte hex); `test_public_readonly.py` 7/7.
- [x] Extra: real `relocate_dir`/`meta_set`/rollback FS tests; `onchain_is_validator`+remap (12 tests); ERR-trap fires rollback.

## Review
Both pieces landed in the `tn-node-deployment` submodule; all static verification green. Files:
- **NEW** `migrate-node-naming.sh` (+~430): idempotent, collision-guarded, self-rolling-back migration. **Key
  fix found in review:** the ERR-trap rollback needs `set -E` (errtrace) — without it the trap is NOT inherited
  by functions, so a mid-migration failure would exit WITHOUT rolling back. Proven with a focused test.
  Also added guards that abort (no mutation) on a custom data dir (avoids a slow/dangerous cross-fs db copy)
  or a non-standard config layout. Made source-safe (`BASH_SOURCE==$0`) so the real functions are unit-testable.
- `ui/server.py` (+~95): base58→hex, `onchain_is_validator`, `detect_nodes` remap, `/api/nodes` staked,
  `/api/status` is_validator_onchain, `UI_VERSION`→1.7.66. The remap runs AFTER docker detection so
  `managed_names` still shields the legacy container from being re-detected as an external node.
- `ui/static/index.html` (+~10): poll-time auto-switch (only when current tab uninstalled) + staked badge.
- `update-scripts.sh` (+1, version bump): ships `migrate-node-naming.sh`; self-bootstrap bump ships the new list.
- `CHANGELOG.md`: two Unreleased entries (migration tool + UI on-chain detection).

Tests: migration sed (docker+binary forms), real `relocate_dir`/`meta_set`/rollback-reverse on a temp tree,
collision guard, `onchain_is_validator` gating (synced/registered/unsupported/cached), `detect_nodes` remap
(staked→validator, unstaked stays, real-validator-not-probed), base58 vs node5's real key, route tripwire 7/7.

NEXT (operator — not done here, no commit without ask; submodule deploy is operator-owned):
1. commit the submodule + bump the parent-repo pointer; 2. on node5: `update-scripts.sh` (pulls the script),
then `sudo bash migrate-node-naming.sh`; 3. confirm only `telcoin.service` remains, dirs unified, RPC up,
node rejoins consensus, dashboard validator tab auto-selects. Script is general — other legacy observers can
follow (node5 first).

---

# TODO — Restore admin dashboards on devnet (Node Manager UI at admin.node[1-5]) — 2026-06-25

Install the Telcoin Node Manager UI on all 5 nodes and front it at
`admin.nodeX.devnet.telcoin.network` via the devnet Caddy — read-only, basic_auth,
shared bcrypt credential in GCP Secret Manager. Additive + gated; zero RPC impact.
The public vhost stamps the unforgeable `X-TN-Dashboard-Public` header → server.py
refuses every write (read-only). Management stays on the SSH tunnel over the overlay.

## Implementation
- [x] 1. `common/config-caddy.sh` — ADMIN_BLOCK builder before the heredoc; splice
      `${ADMIN_BLOCK}` between the `${SITE_ADDR}` block and the `:80` comment. Inert when off.
- [x] 2. `common/dns.sh` — thread `TN_ADMIN_DASHBOARD/_AUTH_USER/_AUTH_HASH` into the
      per-node sudo call (`:-` defaults for `set -u`); Phase-4 admin probe (200/401 OK).
- [x] 3. `devnet-dashboards.sh` — NEW UI-rollout driver (mirrors `devnet-observability.sh`);
      ships pinned `tn-node-deployment/ui/` via tar → `/tmp` → `install-ui.sh --update`. +x set.
- [x] 4. `devnet-deploy.sh` — gated `step_13`; bump `LAST_STEP=12`→`13`; header step list.
- [x] 5. `config.sh` — `TN_ADMIN_DASHBOARD` / `TN_ADMIN_AUTH_USER` / `TN_ADMIN_HASH_SECRET` defaults.

## Verification (no node touched) — ALL PASS
- [x] 6. Pre-flight RPC-safety gate (render from the REAL files, no hand-copy):
      - GATE 1 (critical): flag OFF, old(HEAD) vs new → `diff` EMPTY, byte-identical = ZERO RPC regression.
      - GATE 2: flag ON+auth → well-formed admin vhost; bcrypt `$2a$14$…` inserted VERBATIM (no
        re-expansion); RPC `(rpc)`/`${SITE_ADDR}`/`:80` blocks all intact. Braces balanced.
      - GATE 3: flag ON, empty hash → no `basic_auth` (AUTH_BLOCK guard); step_13 refuses upstream.
      - GATE 4: multi-suffix → admin domains comma-joined into one block.
      - dns.sh threading: bcrypt hash with `$`/`.`/`/` single-quoted + carried VERBATIM (two-layer safe).
      - (caddy not installed locally → `caddy validate` runs on-node per config-caddy.sh L177+dns.sh.)
- [x] 7. `bash -n` clean on all 5 files. devnet-deploy.sh: LAST_STEP=13, step_13 present, 13 in-range.
      step_13 isolation (stubbed, no real deploy): C1 skip-when-off; C2 pre-set hash (no fetch);
      C3 fetch-from-SM; C4 fail-loud on fetch-fail; C5 refuse on empty-hash; dashboards-before-dns
      ordering confirmed. devnet-dashboards.sh bogus-subset → fail-fast, no node contact, no leftover tar.

## Review
DONE + verified, additive + gated, ZERO RPC-path regression (proven by byte-identical render with flag off).
Code committed: NO (per session scope — user asked to implement, not push/deploy). Pre-flight only; no node touched.

Justified deviation from the plan (hardening, supports the plan's own verification):
- step_13 resolves the hash explicitly (not the plan's `: "${VAR:=$(...)}"` one-liner) and FAILS LOUD
  if the Secret Manager fetch errors OR returns empty — refusing to expose an UNAUTHENTICATED public
  dashboard. The plan's `:=` form would silently swallow a failed fetch (set -e doesn't trip on a
  command-sub inside `${:=}`) → empty hash → `basic_auth` dropped → public unauth read-only dashboard
  leaking node health/logs/config. The plan's own verification expects 401 (auth on), so empty-hash is
  never the intended step_13 path. Uses `tn_secret` (devnet-lib.sh) for consistency with obs.

Pre-existing, NOT mine (leave for operator): `common` submodule also has uncommitted wgvpn/* edits;
`tn-node-deployment` has uncommitted setup-vpn.sh — both from prior session work. I touched ONLY
config-caddy.sh + dns.sh (common) and read/tarred ui/ read-only.

## REDESIGN (2026-06-25, per user): MANDATORY + zero-config — no env vars, scripts fetch the secret themselves
- `config.sh`: `TN_ADMIN_DASHBOARD` default flipped 0→**1** (removed the user's hand-added `TN_ADMIN_DASHBOARD=1` line).
- `common/dns.sh`: now AUTO-FETCHES the bcrypt hash from Secret Manager once (gcloud) and threads it; on
  fetch-failure → RPC-only + warn (never unauthenticated, RPC never blocked); pre-set hash honored; admin
  probe softened to WARN-ONLY (a not-yet-installed UI can't fail the RPC sweep).
- `devnet-deploy.sh step_13`: default-on (opt out TN_ADMIN_DASHBOARD=0); no secret logic (dns.sh owns it).
- NEW `devnet-admin-secret.sh`: idempotent one-time secret creation (caddy bcrypt → Secret Manager), prints
  the password once; `--rotate` adds a version. (The earlier paste failure was just terminal line-wrapping.)
- Re-verified: bash -n all; config default 1 / opt-out 0; dns.sh fetch success/fallback/override; secret
  helper exists-noop / absent-create; RPC-safety GATE 1 still byte-identical.

OPERATOR (recurring path is now ENV-VAR-FREE):
1. ONE-TIME: `./devnet-admin-secret.sh`  (creates the GCP secret + prints the password — store it; needs
   local `caddy`: `brew install caddy`). `--rotate` to change the password later.
2. EVERY TIME (no env vars): `./devnet-dashboards.sh && ./common/dns.sh`  (or `./devnet-deploy.sh`).
   Prefix `TN_SSH_TRANSPORT=overlay` only if IAP is broken.
3. Verify: `https://admin.node1.devnet.telcoin.network/` → 401; `-u admin:$PW` → 200; POST → 403.
4. Commit/push devnet-genesis + common, bump submodule pointers (operator owns push/deploy). Leave the
   unrelated pre-existing `common/wgvpn/*` + `tn-node-deployment/setup-vpn.sh` edits out of the commit.

---

# TODO — Devnet: restore SSH (grant2), deploy obs, secure BLS, bring RPC online — 2026-06-19

Closing the 4 loose ends after `devnet-deploy.sh` stopped before step 9. Execute in order; gate after each.
Reach nodes over the WireGuard overlay (`utun6`=10.100.9.6=hannibal/grant2); GCP REST/API works fine.

## Phase 1 — Restore SSH for grant2 (metadata break-glass)  [LOW RISK] ✅ DONE
- [x] Pre-flight: VPN up (hub+node1 ping ok); local tnvpn key pubkey == plan's grant2 key; all 5 nodes' `ssh-keys` metadata ABSENT (safe to set, no clobber); OS Login off (project+instance); baseline node1 probe = `Permission denied (publickey)` (node doesn't trust grant2; hub does).
- [x] 1. Injected `tnadmin:<grant2-pubkey>` into all 5 nodes' instance `ssh-keys` metadata (Updated x5).
- [x] 2. Cleared stale `known_hosts` for 10.100.2.1–.5.
- [x] 3. Verified all 5 return hostname over `tn_ssh` (5/5, attempt 1).
- [x] 4. Persisted into `.tnvpn` via `sync_keys_to_registry_nodes` — 6 key lines installed on all 5.
- [x] 5. Removed metadata break-glass (canary node1 first, verified .tnvpn path holds, then 2-5); trust now `.tnvpn`-only.
- [x] GATE PASSED: 5/5 hostname over tn_ssh AFTER metadata removal; `authorized_keys.tnvpn`=6 lines incl. tnvpn-grant@hannibal on all 5; sshd AuthorizedKeysFile honors `.ssh/authorized_keys.tnvpn`.

## Phase 2 — Step 9 per-node observability  [LOW RISK] ✅ LOGS DONE / metrics blocked server-side
- [x] Canaried node1 -> discovered Alloy was crash-looping fleet-wide (driver reported "running" falsely).
- [x] Root-caused + fixed TWO tn-node-deployment bugs (branch fix/obs-alloy-docker-storage-and-chain-label, commit d16bb34):
      (A) Alloy docker storage dir mounted under image's 473:473-owned /var/lib/alloy; --cap-drop=ALL strips
          CAP_DAC_OVERRIDE so container-root can't traverse it -> "mkdir /var/lib/alloy/data: permission denied".
          Fix: mount + --storage.path at ${OBS_DATA_DIR} (/var/lib/telcoin-alloy, parent /var/lib traversable),
          matching the native unit; all hardening flags kept. (B) TN_CHAIN hardcoded "adiri" -> map from NETWORK
          (testnet stays adiri byte-identical; devnet->devnet).
- [x] Pushed fixed lib/observability.sh to all 5 nodes (sha c4b2d66, verified); re-ran obs node-by-node
      (1 validator restart each, quorum 3/4 held; each rejoined consensus before next).
- [x] GATE (logs): all 5 Alloy active + shipping; Loki {job="telcoin-node"} shows all 5 with chain=devnet
      (28 streams/10m, zero adiri leakage). ✅
- [x] FOLLOW-UP #1 CODE DONE (live redeploy pending tunnel): metrics 401 root cause was NOT a missing Caddy
      route — the committed Caddyfile already has the token-gated /api/v1/write block. The LIVE Caddy was
      serving a STALE config: `docker compose up -d` doesn't recreate a container when only a bind-mounted
      file's CONTENTS change, so redeploys kept an old Caddyfile lacking the route -> Grafana catch-all ->
      "Invalid API key". FIX (common 8ef0e9d): bringup-remote.sh now reloads each config-bearing service
      after `up -d` (caddy reload / SIGHUP prometheus / restart loki). Also parameterized prometheus
      `monitor:` per-network (OBS_MONITOR=obs-devnet). LIVE: re-run create-obs-instance.sh -> verify
      /api/v1/write 204 + tn_info series.
- [x] FOLLOW-UP #2 CODE DONE (live redeploy pending): reth's ~1.1MB lines exceed Loki's per-line cap. The key
      is `max_line_size` (NOT `max_entry_size`); default 262144=256KB. FIX (common 8ef0e9d): loki-config.yaml
      max_line_size=2097152 (2MiB), lossless (no truncate). Documented in obs README for self-hosters.
      LIVE: redeploy obs -> force a >256KB line ingests (no 400).

## Phase 3 — BLS Docker LoadCredential fix upstream + re-finalize  ✅ DONE
- [x] tn-node-deployment branch `fix/tn-node-deployment-docker-fixes` (3 commits, LOCAL — operator pushes/PRs):
      d16bb34 (obs alloy storage+chain, Phase 2), a09fd68 (BLS Docker LoadCredential in setup-validator.sh +
      setup-observer.sh — wrapper reads $CREDENTIALS_DIRECTORY, `-e TN_BLS_PASSPHRASE` name-only, README updated),
      0154f38 (tn_node_launch_target → docker wrapper, so obs flag injection still works post-wrapper).
- [x] Render-validated the loadcredential wrapper+unit locally before any deploy (bash -n + 5 assertions PASS).
- [x] DISCOVERED + handled: (a) `--json --phase=finalize` can't emit obs reth flags (ENABLE_* are interactive-
      testnet-only) → re-finalize alone drops obs; (b) the wrapper moves `docker run` out of the unit, breaking
      obs_ensure_reth_flags injection → fixed via tn_node_launch_target. Method (user-chosen): finalize (writes
      LoadCredential unit; `start` is a no-op while running) THEN obs re-run (injects obs flags into the wrapper +
      ONE real `systemctl restart` that activates everything).
- [x] Rolled node-by-node over overlay (canary node1 → 2 → 3 → 4 → observer-5). Each: push setup script +
      lib/common.sh (sha-verified) → finalize → obs → verified consensus rejoin BEFORE next. genesis re-stage
      verified byte-identical (no-op). Passphrase read from each node's own file, never echoed.
- [x] GATE PASSED: all 5 units `LoadCredential=bls-passphrase:…`, ZERO embedded passphrase (was `=tornado`);
      chain advancing (epoch 7, all 5 in lockstep, restarts=0/oom=false per node); all 5 still ship to Loki
      (chain=devnet); obs flags present in every wrapper. A healthy rejoined node PROVES LoadCredential
      delivers the passphrase (else BLS decrypt fails). Branch is local — operator pushes + opens PR.

## Phase 4 — Public RPC edge (steps 10–12)  [RISKIEST: SSH-lockout + IAP dep — confirm first]
CODE DONE this session (2026-06-20); LIVE rollout is tunnel-gated (operator brings up WG, then driveable
over TN_SSH_TRANSPORT=overlay):
- [x] Step 10 CODE: firewall-setup.sh `--json --enable` (lockout-safe, tn-node-deployment bc44be9) +
      devnet-firewall.sh `--enable` mode (one node at a time, SSH re-verify, ABORT on loss). LIVE: run
      `./devnet-firewall.sh --enable` over overlay (observer canary first), `tn_ssh <n> true` after each.
- [x] Step 11 CODE: setup-firewall.sh drops public tcp:8545 from devnet-allow-web (reth binds loopback,
      Caddy fronts RPC). LIVE: re-run setup-firewall.sh to reconcile IPs + confirm 80/443.
- [x] Step 12 CODE: dns.sh overlay branch (common 9a0053c) + config-caddy.sh per-node port resolution
      (common f905061, observer wss -> :8554). LIVE: dns.sh over overlay (re)applies Caddy + verifies
      eth_blockNumber + WSS-101; setup-load-balancer.sh builds LB; create node{1..5} + rpc A-records.
- [x] LIVE DONE (2026-06-20, over overlay): Phase 2 obs redeployed (metrics /api/v1/write FIXED ->
      tn_info=5 all nodes, max_line_size 2MiB, logs flowing; prometheus data-dir crash-loop fixed).
      --ws LIVE on all 5 (loopback RPC+WS: val 8545/8546, obs 8541/8554; consensus never lost quorum,
      restarts clean). UFW active fleet-wide (lockout-safe, SSH re-verified each). VPC: public 8545 dropped.
      Caddy edge LIVE: https://node{N}.devnet.telcoin.network eth_blockNumber=200 + wss://node{N} 101 on all
      5 (LE certs issued). LB built: rpc IP 34.96.110.84, all 5 backends HEALTHY (health-check moved :43174
      -> :80 since reth's --healthcheck binds nothing). Surfaced+fixed 6 bugs (see lessons 2026-06-20).
- [ ] OPERATOR (only remaining step): create rpc.devnet.telcoin.network  A  ->  34.96.110.84 in the DNS
      provider for devnet.telcoin.network (not a Cloud-DNS zone reachable from this account). Then the LB's
      Google-managed cert auto-provisions (5-60m) and https://rpc.devnet.telcoin.network serves via the LB.
      Also flag: reth --healthcheck 43174 binds no listener (kuma uptime monitor probes a closed port).

## Review — Phase 2 follow-ups + Phase 4 code (2026-06-20)

ALL CODE for the remaining Phase 2 follow-ups + Phase 4 landed + statically/render-verified; committed on
`main` in all 3 repos (NOT pushed, no co-author). LIVE rollout is tunnel-gated (client IAP broken on this
Mac; operator brings up WG, then drive it over TN_SSH_TRANSPORT=overlay).

Commits:
- tn-node-deployment (main): fast-forwarded the 3 docker-fix commits (d16bb34/a09fd68/0154f38) onto main,
  then 7bd1351 (reth --ws + --http.addr/--ws.addr 127.0.0.1 in all 4 launch heredocs; WS_PORT derived +
  persisted to .node-meta), bc44be9 (firewall-setup.sh lockout-safe --json --enable).
- common (main): 8ef0e9d (Loki max_line_size 2MiB + bringup reloads config-bearing services + per-network
  prometheus monitor), f905061 (config-caddy.sh resolves RPC/WS ports from .node-meta), 9a0053c (dns.sh
  TN_SSH_TRANSPORT=overlay branch).
- devnet-genesis (main): submodule bumps (common 9a0053c, tn-node-deployment bc44be9) + config.sh
  OBS_MONITOR=obs-devnet + setup-firewall.sh (drop public tcp:8545) + devnet-firewall.sh --enable + tasks/*.

Plan corrections caught by verifying against source (not trusting the plan):
1. reth WS port = 8546 + instance*2-2 (observer 8554), NOT 8546+(instance-1) (=8550) — reth
   rpc_server.rs adjust_instance_ports.
2. Loki key is `max_line_size`, not `max_entry_size`.
3. metrics 401 = stale LIVE Caddyfile (bind-mount + `compose up -d` doesn't recreate), not a missing route.
4. reth already binds RPC/WS to loopback by default -> public 8545 was dead weight (safe drop); --ws was OFF.

Render/static verification (all PASS): 4-variant heredoc render (BLS LoadCredential intact, --ws/loopback,
.node-meta 8545/8546 + 8541/8554); config-caddy port-resolution precedence; dns.sh both transports;
firewall --json --enable lockout order (SSH+overlay+kuma before enable); devnet-firewall --enable
abort-on-SSH-loss. bash -n on every edited script; Loki + Prometheus YAML valid.

Docker+native parity: every tn-node-deployment change touched all four launch heredocs (docker+native ×
TPM+LoadCredential) and render-verified for both install methods; .node-meta write + port derivation are
install-method agnostic.

REMAINING (live, tunnel-gated — see Phase 2/4 LIVE notes above): operator `wg-quick up tn-wg0`; then
Phase 2 (redeploy obs; verify 204 + tn_info + big-line ingest); Phase 4 over overlay (--ws restart
node-by-node + ss -tlnp; UFW enable; VPC reconcile; Caddy/LB/DNS), each gated on consensus rejoin + restarts=0.

---

# TODO — Devnet deploy unblock: route per-node steps over the WireGuard overlay — 2026-06-19

IAP SSH is broken **client-side** (gcloud's new lightweight websocket drops instantly on this
macOS box; no env/property/flag override). Bypass it by reaching nodes over the existing
WireGuard overlay. Nodes were recreated 2026-06-19 → new WG pubkeys, so re-enroll them with the
hub first. Hub = `tnadmin@10.100.0.1` (project `tn-devops-sandbox`, instance `wg-hub`).

Division of labor:
- **Autonomous (no tunnel / no sudo):** Phase C code, Phase B serial reads + registry edits.
- **Operator (local sudo):** Phase A — bring the operator's WG tunnel up.
- **After tunnel up (driveable; ssh/scp + REST only, no local sudo):** Phase B hub redeploy +
  verify, Phase D drivers, Phase E verify/commit.

## Phase C — overlay transport toggle (code; safe, default=iap, behavior unchanged unless overlay) ✅ DONE
- [x] `devnet-lib.sh`: `TN_SSH_TRANSPORT` toggle (default `iap`); when `overlay`, source
      `wg-ssh-lib.sh` with the gcloud shim suppressed (`TN_USE_VPN=0` around the source);
      overlay branch in `tn_iap_ssh`, `tn_iap_ssh_stdin`, `tn_iap_scp`. Header comment updated.
- [x] `devnet-keygen.sh`: overlay branch in local `tn_iap_scp_down`.
- [x] Syntax-test both transports — PASS: iap leaves gcloud a file + tn_ssh undefined; overlay
      defines tn_ssh/tn_scp/tn_overlay_ip, keeps gcloud a FILE (shim suppressed), restores
      TN_USE_VPN=1, resolves 10.100.2.1/.4/.5 correctly.

## Phase B — re-enroll the 5 recreated nodes (serial → registry → hub)
- [x] Read `WG_NODE_PUBKEY=` from each node's serial console (REST) — all 5 captured (2 boots each,
      1 distinct value), validated 32-byte:
      v1 `lm4QOBnt…7Q0=` · v2 `fnt9MJi3…GEE=` · v3 `btL8ZlSC…O3Y=` · v4 `slFDkkkq…bE8=` · obs5 `H2Lgx2ed…9mI=`.
- [x] `common/wgvpn/peers/registry.csv`: replaced 5 pubkeys, bumped date 2026-06-19, renamed node-5
      `validator-5-devnet` → `observer-5-devnet`. Overlay IPs unchanged. Pre-flight: 17 valid peers render.
- [x] Wrote break-glass `tasks/hub-redeploy-overlay.sh` (hub_redeploy is IAP-hardcoded; this runs the
      same bringup-hub.sh over the overlay to `tnadmin@10.100.0.1`). Syntax + hub-constant resolution OK.
- [x] Ran `./tasks/hub-redeploy-overlay.sh` — 17 peers rendered, `wg syncconf` (no drop), operator
      peer kept handshake. All 5 devnet nodes handshaked the hub within ~18s (verified hub-side:
      endpoints + fresh handshakes + bidirectional transfer).
- [x] **(gate)** all 5 reachable via `tn_ssh` — BUT first had to clear stale `~/.ssh/known_hosts`
      entries for 10.100.2.1–.5 (recreated nodes → new SSH host keys; `accept-new` rejects a CHANGED
      key by design). `ssh-keygen -R` each, then 5/5 returned hostname. Lesson for Phase E.

## Phase A — operator brings the tunnel up (LOCAL SUDO — operator runs; runtime already installed)
- [ ] `sudo install -m 600 ~/.config/tnvpn/tn-wg0.conf /etc/wireguard/tn-wg0.conf`
- [ ] `sudo wg-quick up tn-wg0`
- [ ] verify: `sudo wg show` (handshake w/ hub `hqIDsk…`, nonzero rx/tx), `ping -c3 10.100.0.1`

## Phase B.5 — hub split-brain recovery (operator ran add-peer.sh + hub redeploy on 2nd machine `hannibal`)
- [x] That redeploy re-rendered wg0.conf from the OTHER machine's stale registry → reverted my devnet
      key fix → all 5 nodes unreachable again. Other machine had added `grant2` maintainer (10.100.9.6).
- [x] Read the hub's leftover `/tmp/wgvpn/peers/registry.csv` + grant2.pub; merged = my devnet fix +
      grant2 row + grant2.pub. Diff vs hub = ONLY the 5 devnet rows. Operator re-ran redeploy → nodes back.
- [ ] FOLLOW-UP: commit merged registry + grant2.pub in `common` so both machines converge via git;
      operator must NOT run hub ops from `hannibal` until then (re-clobber risk).

## Phase D — run gated steps over the overlay (`export TN_SSH_TRANSPORT=overlay`; run drivers via bash 5.x)
- NOTE: drivers have `#!/bin/bash` but use mapfile (bash4+); macOS /bin/bash is 3.2 → run as `bash driver.sh`.
- [x] **Step 5 keygen** — all 5 keyed + node-info collected. REQUIRED a tn-node-deployment fix: the
      keygen `docker run` in setup-validator.sh:742 / setup-observer.sh:785 lacked `--user` (ran as image
      nonroot 1101; DATA_DIR owned by host telcoin 1002 → "Permission denied"). Added
      `--user ${docker_uid}:${docker_gid}` + `-e HOME=/home/nonroot` (numeric --user has no passwd entry
      → $HOME=/ → reth log dir unwritable). Pushed patched scripts to all 5 nodes (sha-verified).
- [x] **Step 6 genesis-build** (local) — needed (a) local Docker Desktop running, (b) a `common`
      submodule fix: `common/genesis.sh:164` passed `--chainid` but v0.11.0 binary wants `--chain-id`
      (value 32285 unchanged → hash-safe; adiri leaves CHAIN_ID empty so unaffected). committee+genesis built.
- [x] **Step 7 finalize** — all 5 nodes' services started. Needed TWO fixes:
      (a) tn-node-deployment runtime `ExecStart` had the SAME `--user`/HOME bug as keygen → added
      `-e HOME=/home/nonroot` to setup-validator.sh:925 + setup-observer.sh ExecStart (re-pushed to nodes);
      (b) `devnet-finalize.sh` didn't pass `--listener-primary/--listener-worker` → node built a bare
      `/p2p/<id>` multiaddr ("Multiaddr is not supported") → added them from intIP (in-scope driver fix).
      Validators' finalize reports rc=1 (premature health check pre-quorum) but services run; observer ok:true.
- [x] **GCP consensus firewall** — `devnet-allow-consensus`(+egress) had STALE node IPs (recreated nodes
      → new static IPs). Ran sanctioned `setup-firewall.sh` (REST) → reconciled to current internal+external
      /32s. **Result: 4 validators reached quorum, consensus advancing (round ~190, voting_power 3/3);
      observer executing consensus output.** ✅ DEVNET IS LIVE.
- [ ] Step 8 obs VM (local/REST — obs-devnet already RUNNING).
- [ ] **Step 9 observability** (`./devnet-observability.sh`, overlay) — needs OBS_INGEST_TOKEN
      (Secret Manager `obs-ingest-token` in tn-devnet — fetchable via gcloud REST). NOT yet run.
- [ ] **Step 10 firewall** (CAUTION: host UFW currently INACTIVE; this activates it. Confirm ruleset
      keeps :22 from 10.100.0.0/16; apply per-node; re-test `tn_ssh <node> true` after each). NOT yet run.

## Cross-repo changes to COMMIT (3 repos) + node-side drift to reconcile
- `devnet-genesis`: devnet-lib.sh + devnet-keygen.sh (TN_SSH_TRANSPORT toggle), devnet-finalize.sh
  (listener fix), tasks/hub-redeploy-overlay.sh (new break-glass), tasks/todo.md.
- `common`: peers/registry.csv (5 devnet keys + observer-5 rename + grant2 merge) + peers/ssh/grant2.pub;
  genesis.sh (--chain-id). NOTE: hannibal divergence — commit so both machines converge via git.
- `tn-node-deployment`: setup-validator.sh + setup-observer.sh (keygen+runtime --user/HOME fixes).
  Also pushed directly to the 5 nodes (sha-verified) — node copies match local until next boot re-clone.

## Phase E — verify, clean up, commit
- [ ] End-to-end: nodes healthy (`tn_ssh <node> 'docker ps'`), consensus advancing, RPC up.
- [ ] Commit registry fix in the `common` submodule (real correctness fix).
- [ ] Optionally commit the `TN_SSH_TRANSPORT` toggle + tasks/lessons.md note.

## Review (this task)
(filled in as phases complete)

---

# TODO — Devnet migration to `tn-node-deployment` (v0.11.0-devnet, Ubuntu) — 2026-06-19

Three repos, clear ownership (all siblings under `/Users/grant/coding/telcoin/`):
- `tn-node-deployment` — Association per-node tooling. Remote `…/tn-node-deployment.git`, branch `main`, clean. (Workstream A.)
- `common` submodule = repo `deploy-networks-common-` (trailing dash; remote of devnet's submodule). Shared/parameterized. (Workstream B.) Checked out @48cbfdb; adiri also pins 48cbfdb.
- `devnet-genesis` (this repo) — fleet/GCP orchestration + new per-node driver scripts. (Workstream C.)
- `adiri-genesis` — frozen testnet; absorbs 6 moved scripts (B1 Commit B). Pins common@48cbfdb; do NOT bump its pointer.

SCOPE (this session): author + commit scripts/config on branches. No mutating gcloud, no live deploy, no PR merges (operator does those). The end-to-end runbook is operator-run. [confirm via questions]

## Workstream A — tn-node-deployment ✅ DONE — commits 72b3923 (PR1), 5cbed98 (PR2), f50d08b (PR3) on `main`; bash -n clean, additive-only, effective-URL reaches config.alloy, all lib fns verified.
### PR1 — devnet network profile + genesis injection
- [ ] A1 `lib/common.sh`: add `DEVNET_CHAIN_ID="32285"`, `DEVNET_CHAIN_NAME="devnet"` (+ RPC/EXPLORER empty defaults) near consts (lines 12–21).
- [ ] A2 `setup-validator.sh` + `setup-observer.sh`: add `devnet)` arm to `json_set_network()` before `*)` reject (val 1208–1215 / obs 1290–1297).
- [ ] A3 both: `step_write_config()` — change `chain_subdir` to handle `devnet` (val 797–845 / obs 832–890).
- [ ] A4 both: `step_write_config()` `search_paths` — prepend `${TN_GENESIS_DIR:+"$TN_GENESIS_DIR"}`; add `--genesis-dir <path>` flag to `main()` parser (sets `TN_GENESIS_DIR`).
- [ ] A5 `lib/common.sh`: add `is_testnet_like()` (testnet OR devnet); make `require_testnet` accept testnet-like (used by setup-observability.sh). Leave soft `is_testnet` prompts testnet-only.
- [ ] A6 `lib/testnet-addons.env` + `lib/observability.sh`: add overridable `OBS_PUSH_URL_DEVNET`/`OBS_METRICS_PUSH_URL_DEVNET` (default empty, fail-closed); select when `NETWORK=devnet`. Adiri `_TESTNET` defaults untouched.
### PR2 — scriptable `setup-observability.sh`
- [ ] A7 add `--json` non-interactive block (interactive menu stays default): `--enable-logs/--enable-metrics/--enable-health`, `--disable-*`, `--region`, `--token`/`TN_OBS_TOKEN`, `--push-url`/`--metrics-push-url` (or `OBS_PUSH_URL`/`OBS_METRICS_PUSH_URL` env). Add json_event/json_done helpers (copy per-script pattern).
### PR3 — `install.sh --yes`
- [ ] A8 honor `--yes/-y/--force` + `TN_ASSUME_YES` to skip overwrite prompt (lines 64–80). Default unchanged.
### PR4 — DEFERRED (firewall-setup.sh --json already supports 49590/49594/udp + 43174/tcp, SSH-safe).
- [ ] A-verify: interactive testnet flow byte-identical (pick network 1); devnet keygen emits node-info.yaml; finalize loads custom `--genesis-dir` (chainid 32285); obs --json brings up telcoin-alloy; install.sh --yes non-interactive.

## Workstream B — common/ ✅ DONE — commits: 4189fb7 (B1 move), 089e2d3 (B2 genesis lib), 0220774 (B3 obs-wipe), b8d89d5 (B4 wgvpn), 42c58aa (B5 static-IP) on common `main`; adiri 1ac4bdb (Commit B). NOTE: B4 plan-deviation — `WG_NODE_ENFORCE` already exists (gates activation, default 0); devnet must set the NEW `WG_NODE_FIREWALL=0` (not WG_NODE_ENFORCE) — adjust C2.
- [ ] B1 move 6 adiri-only scripts → adiri root (start-validator-node.sh, start-observer-node.sh, update.sh, update-staggered.sh, startup.sh, config-apache.sh). Commit B in adiri (copy + repoint config.sh L58/124/127/129 to `${REPO_ROOT}/…` + README note); Commit A in common (`git rm` the 6 + README). Verify shared orchestrators only reference start scripts via config.sh env vars.
- [ ] B2 `common/genesis.sh` sourceable: extract `tn_genesis_pull_validator_info` / `tn_genesis_build_committee` / `tn_genesis_distribute_and_start`; direct exec runs all three (adiri byte-identical); add `GENESIS_LIB_ONLY=1` early-return guard.
- [ ] B3 add `common/observability/wipe-obs-data.sh` (params OBS_INSTANCE_NAME/OBS_ZONE/PROJECT_ID): ssh → `docker compose down` → wipe loki/prometheus dirs → `up -d`; `--yes`/`FORCE=true` guard; print OBS_HOSTNAME. Add `--wipe-data` to `create-obs-instance.sh`.
- [ ] B4 `common/wgvpn/node/wg-node-bootstrap.sh`: `WG_NODE_ENFORCE` (default 1=adiri enforcing; 0=overlay-only, no policy-drop nftables → UFW authoritative).
- [ ] B5 `common/create-instances.sh`: static external IPs via `--address`, gated by `USE_STATIC_IPS` + `STATIC_IP_NAMES[]`; add `reserve-static-ips.sh` (idempotent `gcloud compute addresses create`). Reuse any existing adiri static path.

## Workstream C — devnet-genesis ✅ DONE (except C1, deferred) — commits 32247bd (C2 config), de3076c (lib+gitignore), 612ae13 (9 drivers), 5662c18 (C4 reset-network), 76179c6 (Commit C common bump). C1 (submodule add) deferred until Workstream A is merged upstream so the pin references a real commit.

## Workstream C — devnet-genesis root (new scripts + config)
- [ ] C1 add `tn-node-deployment` submodule (pin to commit containing Workstream A) — AFTER A merges.
- [ ] C2 `config.sh` additions: NODE_DEPLOY_MODE, TN_* dirs, genesis dirs, Ubuntu IMAGE/OBS_IMAGE, STARTUP_SCRIPT_PATH→devnet-startup.sh, USE_STATIC_IPS + STATIC_IP_NAMES, WG_NODE_ENFORCE=0, TN_KUMA_SRC, TN_OBS_ENABLE_* (default-on), OBS_METRICS_PUSH_URL fix.
- [ ] C3 new root scripts: devnet-startup.sh, devnet-keygen.sh, devnet-genesis-build.sh, devnet-finalize.sh, devnet-observability.sh, devnet-firewall.sh, devnet-update.sh, devnet-wipe.sh, devnet-deploy.sh.
- [ ] C4 repoint `reset-network.sh` → devnet-wipe.sh + devnet-finalize.sh.
- [ ] C5 BLS passphrase via `TN_BLS_PASSPHRASE` env (untracked/Secret Manager), persisted to `/etc/telcoin/<type>/bls-passphrase` 600; never committed/echoed.

## Cross-cutting
- [ ] Firewall: single port manifest (config.sh ⇄ testnet-addons.env); GCP source-of-truth + UFW safety-net; nftables overlay-only (WG_NODE_ENFORCE=0).
- [ ] Verification: genesis-hash equivalence before/after B2 refactor (adiri inputs); shellcheck new scripts; adiri config.sh paths still resolve after Commit B.

## Decisions / open
- [ ] Branch/commit structure across the 3 upstream repos (see questions).
- [ ] BLS passphrase source path / Secret Manager secret name.

---
---

## Review — what landed + what the operator must do next

ALL CODE AUTHORED + COMMITTED (no pushes, no PR merges, no mutating gcloud — per session scope).

Commits by repo:
- tn-node-deployment `main`: 72b3923 (PR1 devnet profile+genesis injection), 5cbed98 (PR2 setup-observability --json), f50d08b (PR3 install.sh --yes). Additive-only; interactive testnet UX byte-identical; effective-URL reaches config.alloy; all lib fns verified.
- deploy-networks-common- `main`: 4189fb7 (B1 move 6 scripts out), 089e2d3 (B2 genesis sourceable, 17 ins/0 del = behavior-identical), 0220774 (B3 obs-wipe), b8d89d5 (B4 WG_NODE_FIREWALL), 42c58aa (B5 static IPs).
- adiri-genesis `main`: 1ac4bdb (B1 Commit B: absorb 6 scripts + repoint config.sh). Its `common` pointer deliberately NOT bumped (still @48cbfdb, which still carries the scripts) — adiri unaffected.
- devnet-genesis `main`: 32247bd, de3076c, 612ae13, 5662c18, 76179c6 (see headers above).

Key plan deviations (justified, evidence-backed):
1. WG_NODE_FIREWALL (new) instead of reusing WG_NODE_ENFORCE — the latter already exists (gates *activation*, default 0) and adiri's lockdown depends on it; reusing it as the plan said would break adiri's lockdown. Devnet sets WG_NODE_FIREWALL=0.
2. OBS_IMAGE stays Debian (NOT Ubuntu) — obs-vm/startup-obs.sh hardcodes the Debian docker apt repo; Ubuntu would fail docker-ce install. Only the validator IMAGE moved to Ubuntu.
3. keygen/finalize use `sudo env TN_BLS_PASSPHRASE=...` (not bare `sudo VAR=`) — env-only secret, no flag fallback; bare form isn't guaranteed past sudoers env_reset.
4. devnet-genesis-build relaxes set -e/-u/pipefail around the genesis build to match adiri's (unset-state) env exactly.

Verified statically: node-info.yaml schema IDENTICAL between keygen output and the genesis build input (same NodeInfo struct) — only a filename rename. All scripts bash -n + shellcheck clean.

OPERATOR HANDOFF (cannot be done autonomously):
- [ ] Push tn-node-deployment + open PR1/PR2/PR3; merge to main. Confirm repo is PUBLIC (devnet-startup.sh https-clones it) or bake a deploy key.
- [ ] C1: after A merges, `git submodule add` tn-node-deployment pinned to the merged commit.
- [ ] Push common (deploy-networks-common-), adiri-genesis, devnet-genesis commits.
- [ ] Provide BLS passphrase: `export TN_BLS_PASSPHRASE=...` or put it in `.secrets/bls-passphrase` (gitignored).
- [ ] Ensure Secret Manager `obs-ingest-token` exists in tn-devnet (devnet-observability.sh fetches it).
- [ ] Run the one-time migration: `./devnet-deploy.sh --yes` (reserves IPs, recreates VMs on Ubuntu, keygen→build→finalize→obs→firewall→LB). DESTRUCTIVE VM recreate.
- [ ] Scratch-VM verify the upstream A changes (keygen emits node-info; finalize loads --genesis-dir chainid 32285; obs --json brings up telcoin-alloy; install.sh --yes) and genesis-hash equivalence for adiri before adiri bumps its common pointer.

---
---

# ARCHIVE — prior completed runbooks (kept for reference)

# TODO — Recover obs-devnet observer (https://obs.devnet.telcoin.network/) — 2026-06-18

Stack: Loki + Grafana + Caddy on VM `obs-devnet`, zone `us-west2-a`, project `tn-devnet`, reserved IP 34.20.241.60.
Symptom: endpoint times out (packets dropped). Every node ships reth logs to `/loki/api/v1/push` → obs down = no central logs.

## Root cause (CONFIRMED — guest OS network stack dead; GCP edge healthy)
- client `curl https://obs.devnet.telcoin.network/` → `(28) Connection timed out after 15002ms` (drop, not refuse).
- IAP SSH → `Connection timed out during banner exchange` (tunnel reaches :22, sshd can't handshake → guest wedged).
- serial console: `23:40 ens4: Could not set DHCPv4 address: Connection timed out` → `23:45 ens4: Failed`;
  `169.254.169.254:80 i/o timeout` (metadata dead, still failing 2026-06-18T11:36); martian source 172.18.0.4;
  dockerd/containerd "Waiting for containerd to be ready" churn. Onset ~2026-06-16 23:40 UTC.
- Diagnosis: guest lost DHCP lease + metadata connectivity + Docker-bridge/iptables corruption. NOT a Caddy/app
  or firewall bug. GCP control plane still reports RUNNING; inbound packets reach edge, find no guest net → dropped.

## Fix: reboot (idempotent startup-obs.sh remounts /mnt/obs-data; services restart: unless-stopped; reserved IP
## persists so DNS+cert stay valid; fresh boot forces clean DHCP + rebuilds Docker iptables).

## Execution
- [x] Step 1 — read-only triage + forensics: SSH banner-timeout (confirms diagnosis); serial console captured;
      forensic boot-disk snapshot `obs-devnet-netfail-20260618` = READY (30 GB).
- [x] Step 2 — graceful stop (exit 0, no reset needed) → start (exit 0); RUNNING; IP unchanged
      34.20.241.60 ext / 10.168.0.3 int (reserved IP persisted → DNS + rendered .env stay valid).
- [x] Step 3 — verify recovery: network FIXED (clean DHCP, metadata reachable, no martians; Caddy UP).
      BUT endpoint = 502: **/mnt/obs-data (obs-devnet-data, 100GB pd-ssd) is 100% FULL** → loki + grafana
      crash-loop (loki: "no space left on device"; grafana: "database or disk is full"). 2nd root cause,
      independent of the network wedge, NOT fixable by reboot. loki/chunks=97G. Retention IS set
      (336h/14d, compactor retention_enabled) but disk fills in ~8d (~12GB/day) → fills before 14d
      retention deletes anything; compactor can't run on a full disk (deadlock). ⇒ need to free space.
      DECISION (user-approved): expand to 200 GB, keep 14d retention (preserve data, match validators).
      DONE: gcloud disks resize obs-devnet-data 100->200 GB (READY) + on-box `resize2fs /dev/sdb` (whole-disk,
      no growpart) → /mnt/obs-data now 197G, 99G free, 50% used. `docker compose restart loki grafana` →
      caddy/grafana/loki all Up; grafana healthy (dashboards provisioned); loki up (ring warming, transient
      "empty ring" 500s on first pushes — nodes already pushing again from node IPs). E2E verified below.
- [x] Step 4 — bring-up path used: `docker compose restart loki grafana` after the resize; stack
      auto-restarts via restart:unless-stopped. All 3 containers Up; loki ingester auto-joined ring at
      19:17:12 (~33s), /ready=ready, "empty ring" cleared.
- [~] Step 5 — root-cause + prevention (see Review). FOLLOW-UPS: (a) add obs to uptime-kuma; (b) investigate
      validator-3-devnet log gap; (c) watch disk plateau (~14d × ~12GB/day ≈ ≤170GB on the 200GB disk).

## Verification (from this laptop unless noted)
- [x] 1. TCP/HTTP reachable: GET / -> HTTP/2 302 -> /login (was: connection timeout). NOT a timeout.
- [x] 2. Grafana served: 302 -> /login; container healthy (dashboards provisioned; no "disk full").
- [x] 3. Loki route + token gate: GET /loki/api/v1/push (no token) -> 401 (Caddy bearer gate).
- [x] 4. Cert valid: Let's Encrypt issuer, CN=obs.devnet.telcoin.network, Jun 10 -> Sep 8 2026 (reused
        existing cert from /mnt/obs-data/caddy/data; no new ACME challenge).
- [x] 5. Guest healthy: post-19:07 serial console has NO martian / metadata-timeout / DHCP-failed lines.
- [~] 6. Logs flowing: loki /ready=ready; fresh ingest last 2m — val-1 18650, val-2 18730, val-4 10781,
        obs-5 8439 lines. ⚠️ validator-3-devnet SILENT ~30m (node-side, NOT obs) — FLAGGED for follow-up.

## Review
obs.devnet.telcoin.network RESTORED. TWO independent root causes (the plan anticipated only the 1st):
  (1) Guest network-stack wedge (DHCP lease lost + metadata 169.254.169.254 i/o timeout + Docker-bridge
      martian-source corruption) since 2026-06-16 23:40 → inbound packets dropped → client TIMEOUT.
      Fixed by graceful stop/start: clean DHCP, metadata reachable, Docker iptables rebuilt, Caddy up;
      reserved IP 34.20.241.60 preserved so DNS + LE cert stayed valid.
  (2) /mnt/obs-data 100% full (loki/chunks = 97G of node logs) → loki ("no space left on device") + grafana
      ("database or disk is full") crash-loop → 502. Reboot CANNOT fix this. Fixed by online-expanding
      obs-devnet-data 100->200GB (pd-ssd) + `resize2fs /dev/sdb` → 197G / 50% used, all data preserved.
Loki retention (336h/14d, compactor retention_enabled) WAS set, but the disk filled in ~8d (< 14d) so
retention never triggered, and the compactor can't run on a full disk (deadlock). With 200GB, usage will
plateau ≤~170GB once data ages past 14d and the compactor (starts ~10m post-boot) begins deleting — OK
headroom; monitor. Forensic boot-disk snapshot obs-devnet-netfail-20260618 retained for offline analysis
of the network wedge trigger (likely the recent caddy-migration / wg work disturbing Docker iptables).

---

# TODO — Devnet disk: diagnosis + recovery (corrected from original plan)

Nodes (`config.sh`): validator-1..4-devnet + observer-5-devnet (node1–node5), project `tn-devnet`.
Reach: `--tunnel-through-iap` (public :22 removed at 2026-06-15 lockdown; `wg-allow-iap-ssh` is the open door;
VPN `tn-wg0` down + no passwordless sudo). Do NOT source `wg-ssh-lib.sh`. Always `--project=tn-devnet`.

## CORRECTED DIAGNOSIS (Phase 1 overturned the plan's hypotheses)
- **Active outage**: chain HALTED at block 265 (0x109), epoch 235, since ~13:12 UTC (~2h). Both up nodes frozen at 265.
- **3 of 4 validators CRASHED** on `No space left on device (os error 28)`:
  - val-4 died first (~10:12), then val-2 + val-3 within 3s of each other (~13:12) → quorum (3/4) lost.
  - val-1 still up but **isolated** (1/4, DialFailure to peers) and itself at **100% disk (165M free)** — about to crash too.
  - observer-5 up, 68% disk, just following (not in quorum).
- **Root cause = legitimate chain data, NOT logs/images.** `consensus-db/epochs` = **88–89 GB/validator** (~94% of disk).
  - Logs bounded everywhere (OBS token SET on all 5; LogConfig max-size:100m/max-file:5; biggest json-log 87M).
  - Images ~1 GB total, ~0 reclaimable. kad = 56K. → Phase 2 cleanup reclaims ~nothing → **SKIPPED**.
- ⚠️ Recurrence risk: epochs/ grows unbounded on 1h-epoch devnet; 200 GB buys time but will refill. Durable fix =
  epoch retention/pruning in telcoin-network (code change, out of scope here). FLAG to team.

## Decision (user-approved): Expand all 5 → 200 GB online + restart the 3 crashed validators + verify.

## Execution
- [x] Phase 0 — IAP reach confirmed (val-1 probe)
- [x] Phase 1 — assess all 5 (read-only) → diagnosis above
- [x] ~~Phase 2 cleanup~~ — SKIPPED (logs/images/kad reclaim ~nothing; OBS token already seeded fleet-wide)
- [x] Phase 3 + recovery (online resize 100→200 GB; growpart + resize2fs; restart crashed):
  - [x] 1. val-1 — resized 200 GB → 197G/50%. (NO restart; protected last validator.)
  - [x] 2. val-4 — resized 200 GB → 197G/50%; telcoin restarted (Exit 0).
  - [x] 3. val-2 — resized 200 GB → 197G/51%; telcoin restarted (Exit 0).
  - [x] 4. val-3 — resized 200 GB → 197G/51%; telcoin restarted (Exit 0).
  - [x] 5. node5 — resized 200 GB → 197G/34%. (NO restart.)
  - NOTE: this Debian image had NO partition tools (no growpart/parted/sfdisk); installed
    cloud-guest-utils via apt (egress to deb.debian.org works). resize2fs/partx/e2fsck were present.

## Verification
- [x] All 5 `df -h /` = 197G total; `disks list` sizeGb=200. Used: validators ~51%, observer 34%.
- [x] Logging still bounded (LogConfig max-size:100m/max-file:5 on all 5; alloy running).
- [x] Quorum restored: val-1/2/3 + observer-5 HEALTHY at epoch 236, consensus advancing (quorum reached
      every round, rounds/consensus_number climbing). Chain is LIVE at 3/4 + observer.
  - EVM block flat at 266 = NORMAL: outputs are empty (batches=0, no txs) + non-epoch-closing → execution
    skipped. Block advances on next tx or epoch close.
- [ ] ⚠️ val-4 NOT fully recovered: stuck at epoch 233 (3 behind), rejecting epoch-236 certs
      (`InvalidEpoch {theirs:236, ours:233}`), can't retrieve newer epoch records. A clean restart did
      NOT fix it → consensus-layer epoch-catchup wedge, separate from the disk crash. DECISION PENDING.

## Review
**Disk emergency RESOLVED.** Root cause was NOT the plan's hypotheses (logs/images bounded fleet-wide).
It was legitimate `consensus-db/epochs` growth (~89 GB/validator) filling the 100 GB disks → all 4
validators hit `No space left on device` and crashed (val-4 ~10:12, val-2/3 ~13:12 UTC), halting the
chain at block 265 (~2h). Fixed by expanding every boot disk 100→200 GB online (no resync) and
restarting the crashed validators → 3/4 validators + observer healthy and live at epoch 236.

OPEN: val-4 epoch-catchup wedge (awaiting user decision: escalate/preserve vs resync).

⚠️ RECURRENCE (~2 weeks): epochs/ grew ~6.8 GB/day (89 GB in 13 days since 2026-06-05 provisioning).
200 GB has ~100 GB headroom → refills ~early July unless epoch retention/pruning is addressed in
telcoin-network. Also: parameterize create-instances.sh:119 disk size via config.sh for re-provisions.

Reusable ops scripts created in tasks/ (IAP-based): run-on-all.sh, resize-disk.sh, recover-down-node.sh,
verify-all.sh, check-progress.sh, diag-epoch.sh, assess.sh, diagnose-health.sh.

---

# Fix devnet healthcheck endpoint + staggered health-gated rollout — 2026-06-20

Root cause: node never opened the :43174 listener on devnet → Kuma TCP monitors + GCP LB health
check all failed. `--healthcheck 43174` IS the right flag (telcoin-network node CLI), but
`tn_node_launch_flags()` dropped it on devnet via the strict `is_testnet` gate + no opt-in in the
json/finalize flow. (Corrects the earlier "flag is broken" misdiagnosis — see lessons.md.)

## Changes (code complete + statically verified; rollout = operator step)
### §1 Emit the flag on devnet — tn-node-deployment SUBMODULE
- [x] `lib/common.sh` `tn_node_launch_flags()`: `is_testnet` → `is_testnet_like` (devnet now reaches
      the per-feature opt-ins; each stays individually `ENABLE_*`-gated, default off).
- [x] `setup-validator.sh` + `setup-observer.sh` main() parsers: add
      `--enable-healthcheck-monitor) ENABLE_HEALTHCHECK_MONITOR=true; shift ;;` (overrides the
      line-43/44 default; env var would NOT work — that default is `=`, not `:=`).
### §2 Staggered health-gated rollout — devnet-genesis
- [x] `devnet-lib.sh`: new reusable `wait_healthy <inst> <zone> <svc>` — on-node `systemctl is-active`
      == active AND `curl -fsS --max-time 3 http://127.0.0.1:43174` (loopback; firewall blocks external).
- [x] `devnet-update.sh`: `--no-wipe` (skip wipe → staggered RE-FINALIZE, chain preserved); replaced
      `wait_active` with `wait_healthy`. **Rollout cmd: `./devnet-update.sh --no-wipe`.**
- [x] `devnet-finalize.sh`: add `--enable-healthcheck-monitor` to `finalize_args` (both roles).
- [x] `reset-network.sh` (secondary): source devnet-lib.sh; replace bulk finalize with
      validators-first/observer-last finalize+`wait_healthy` loop.
### §3 Firewall
- [x] VPC Step 5 (Google HC) + Step 5b (Kuma) — already in working tree, kept.
- [x] Host ufw: VERIFIED `apply_kuma_rule` admits ONLY the Kuma VM, NOT the Google HC ranges → LB would
      stay unhealthy. Added `apply_lb_hc_rule` (submodule `lib/common.sh` + wired into
      `apply_recommended_firewall`), driven by `TN_LB_HC_RANGES`; `devnet-firewall.sh --enable` passes
      `GOOGLE_HC_RANGES` (now a single-source constant in config.sh; setup-firewall.sh consumes it).
### §4 LB — no change (existing 43174 TCP check is correct once the listener is up).
### §5 health.rs:27 doc comment — OUT OF SCOPE (telcoin-network source not in this repo).

## Verification done (static — no live infra touched)
- [x] `bash -n` clean on all 11 edited files.
- [x] Render test vs REAL `lib/common.sh` (10/10): devnet+opt-in→`--healthcheck 43174`;
      devnet default/unset→empty; testnet unaffected; mainnet still gated; `apply_lb_hc_rule`
      comma-splits → one `ufw allow … port 43174 proto tcp` per CIDR, no-op on empty, spacing tolerated.
- [x] Parser arms present, after default, before catch-all (reachable); precedence proven.
- [x] `wait_healthy` remote cmd well-formed (parses as bash; node-side branches emit HEALTHY /
      INACTIVE:<state> / NOLISTEN); rc 0 only on HEALTHY; rc 1 on inactive/nolisten/ssh-fail.
- [x] reset-network ordering: validators-first, observer-last, subset honored.

## Review / rollout prerequisites (OPERATOR)
- **Push submodule first.** Nodes run a clone of the tn-node-deployment GitHub repo (refreshed via
  `git pull`/`update-scripts.sh`). The §1/§3 edits must be committed+pushed to that repo's `main` AND
  pulled onto each node BEFORE `devnet-update.sh --no-wipe`, or finalize re-bakes with STALE scripts (no
  flag) and silently no-ops the fix.
- **PREFLIGHT (critical):** `docker run --rm $DOCKER_IMAGE node --help | grep -- --healthcheck`
  (image = `adiri:v0.11.0-devnet`). An image too old to know the flag would crash-loop; the staggered
  abort-on-first-failure is the safety net.
- After 1st validator: on-node `ss -ltnp | grep 43174` + `curl -s http://127.0.0.1:43174` → OK.
- End-to-end: 5 Kuma monitors green + `gcloud compute backend-services get-health devnet-rpc-backend
  --global`. If LB stays unhealthy while Kuma is green → host ufw lacks the Google ranges → re-run
  `./devnet-firewall.sh --enable` (now passes them).

## ✅ ROLLOUT COMPLETE — 2026-06-20 (healthcheck endpoint live on all 5 + portability hardened)

VERIFIED end state (image bumped to adiri:v0.11.1-devnet-pop; preflight-confirmed --healthcheck support):
- All 5 nodes: service active, :43174 listening, curl OK, new image. (independent on-node sweep)
- GCP LB `devnet-rpc-backend`: all 5 backends HEALTHY.
- Host ufw admits Kuma VM + Google HC ranges on :43174 (config-caddy already added the LB ranges;
  apply_lb_hc_rule is now a fresh-enable safety net). Kuma monitors green (same external path as LB).

Two live-exposed rollout bugs FIXED in devnet-update.sh + reset-network.sh:
1. `--no-wipe` finalize writes the wrapper but `systemctl start` is a no-op on a running svc → OLD
   container persisted. Fix: pre-pull + `systemctl restart` under --no-wipe to apply the new wrapper.
2. Benign validator finalize rc=1 (on-chain address check) aborted the run → gate on wait_healthy, not rc.

Bash portability (separate ask): macOS /bin/bash=3.2 broke `mapfile`. Fixed 3 operator scripts
(env-bash + read-loop), normalized driver shebangs, added tasks/check-bash-portability.sh lint.
See tasks/bash-portability-audit.md for the node-script latent findings (decision pending).

OPEN (operator): (a) commit the devnet-genesis parent-repo changes — submodule ff6aee2 already pushed;
(b) confirm Kuma UI shows 5 green; (c) decide on hardening tn-node-deployment + common/ node scripts.

---

# Hardening — Admin Dashboard Public/Management Boundary — 2026-06-25

Defense-in-depth for the public read-only boundary in `tn-node-deployment/ui/server.py`.
Security eval verdict was **sound** (public visitor cannot edit configs); these changes only
stop a *future* edit from silently regressing the boundary. No runtime behavior change on the
existing SSH or public paths.

## Plan
- [x] **R2 — regression test (highest value).** New `ui/test_public_readonly.py` (stdlib
      `unittest`; only existing dep is Flask). Walks `app.url_map` and: (1) asserts every route is
      explicitly classified read/write — a tripwire that fails the moment someone adds a route;
      (2) asserts every write route is refused 403 on the public path; (3) asserts every read route
      is NOT refused; (4) asserts the SSH path is never refused. Chosen over the `@management`
      decorator refactor: same R2 protection with zero runtime change / no churn across ~18 route
      defs (Simplicity + Minimal Impact).
- [x] **R1 — loopback trust assertion.** `server.py` main block: named `BIND_HOST`/`BIND_PORT`,
      comment block stating that exposing 8080 by any means grants unauthenticated full control, and
      a startup guard that refuses to run unless `BIND_HOST` is loopback (127.0.0.1 / ::1).
- [x] **R2 cross-ref.** One-line pointer from `_is_write_request` to the new test.
- [x] **R3 — operator docs.** README "External dashboard access": rotate the basic_auth credential;
      treat it as read-only-grade.

## Verification
- [x] `python3 -m unittest test_public_readonly` in a flask venv → 7/7 pass.
- [x] Sanity: injected fake GET write route → completeness assert fails (unclassified) AND
      writes-refused assert fails (GET not blocked). Both fired as designed.
- [x] Sanity: `BIND_HOST="0.0.0.0"` → guard logs the refusal and exits 1 (never binds).
- [x] `python3 -m py_compile server.py` clean.

## Review
All three recommendations landed; zero runtime behavior change on the existing SSH and public paths
(verified: SSH path never refused, public reads never refused, public writes still 403). Files
changed (in the `tn-node-deployment` submodule):
- `ui/server.py` (+30/-3): R1 guard + comment, R2 docstring cross-ref.
- `ui/test_public_readonly.py` (new): R2 tripwire, 7 tests, stdlib-only.
- `README.md` (+1): R3 operator note.

Deliberately did NOT do the `@management` decorator refactor — it would touch ~18 route definitions
and change request handling for marginal gain over the tripwire test (per Simplicity / Minimal Impact).

Version bump (so update-scripts.sh ships it): `UI_VERSION` 1.7.55 → 1.7.56 in server.py. Verified the
updater's exact grep extracts 1.7.56. README is not version-gated/shipped (docs); the new test file is
a dev/CI guard, intentionally left out of UI_BUNDLE so it stays off prod nodes.

NEXT (operator, not done here — no commit without ask): these live in the `tn-node-deployment`
submodule. To take effect on nodes, commit there, bump the parent-repo submodule pointer, and ship via
the normal update path. The test file ships harmlessly with `ui/` but is never imported by the service.


# Devnet full wipe + redeploy on `v0.1.0-devnet` + permanent tx generator — 2026-09-17

Fresh genesis with the NEW ConsensusRegistry, retiring the legacy path on devnet. The old
chain (fork740 soak, execution height 0x1f737) was destroyed, not migrated. Image
`adiri:v0.1.0-devnet` (sha256:f6fcef5d…, pushed 2026-09-17T17:32Z) is a version RE-CUT for a
fresh chain, not a downgrade from v0.12.1 despite sorting lower.

## Outcome

- [x] 5 node VMs destroyed + recreated; all five kept their reserved static IPs, so DNS was
      untouched and deploy step 4 was a genuine no-op
- [x] Brand-new BLS/network/execution keys on all five (verified: every `bls_public_key`
      differs from the pre-reset committed value)
- [x] New genesis: chainId 32285, ConsensusRegistry bytecode 70498 chars / sha256
      876efa3c518f207e (pre-reset was 56764 / 42d0d5a76344def0), governance Safe threshold
      forced to 1 signer, txgen master + contracts admin funded at 1e12 TEL each
- [x] Consensus live: validators proposing, quorum 3/3 (2f+1 of a 4-validator committee);
      observer-5 following via state-sync
- [x] Obs redeployed with `--wipe-data`; Loki has all 6 hosts, Prometheus has job=telcoin-node
      ×5 + job=txgen ×1
- [x] Host UFW enabled fleet-wide with ZERO manual steps (the step-10 rewrite); VPC rules
      re-keyed; Caddy/TLS + LB green on all five backends; admin dashboards 401 + write-guarded
- [x] App-contract stack redeployed: 23 eXYZ, StablecoinManager, GitAttestationRegistry,
      Uniswap V2/V3/V4. 22 of 45 V2 pools seeded
- [x] `tn-transaction-generator` permanent on `txgen-devnet`: active, enabled, 0 restarts,
      12 distinct tx types landing (uniswap_v2_swap, uniswap_v4_swap, wtel_wrap/unwrap,
      stablecoin_transfer/approve, contract_deploy, batched_self_send, faucet_drip,
      native_transfer, master_funding), epoch monitor already tracked a boundary
- [x] **The point of the whole exercise:** `eth_blockNumber` went from flat at 0x0 to
      +51 blocks / 20s with real txs in blocks. The chain no longer looks wedged when idle.

## Five defects the plan did not anticipate (each would have shipped broken)

1. **Every node was `disabled` for boot.** `setup-node.sh:1221` ran the informational
   `check_validator_onchain_status` bare under `set -e`; it returns 1 on an empty address and
   aborted finalize AFTER the service started but BEFORE `systemctl enable`. Nodes ran fine
   and would not have survived a reboot. Fixed with `|| true` (the repo's two other callers
   already guarded it) + `devnet-finalize.sh` now passes `--address`.
2. **`v0.1.0-devnet` made `--bls-passphrase-source stdin` mandatory** for the genesis build
   ("Error passphrase is required"); every earlier image ignored stdin. `common/genesis.sh`
   now pipes the passphrase into `docker run -i`, backward-compatibly.
3. **The generator's own sops recipe is wrong.** `--encrypt x.key > x.sops.yaml` round-trips
   to `data: 0x…` because sops picks its store from the extension. Ship `.sops` instead.
4. **`create-obs-instance.sh` still dialled public `:22`**, removed by the WG lockdown —
   10 minutes of polling a healthy VM. Now tunnels through IAP.
5. **`enroll-node.sh` was hijacked by the `TN_USE_VPN=1` gcloud shim**, which ignores
   `--tunnel-through-iap` and routes over the overlay — structurally impossible for
   enrollment. All five nodes were misreported as un-bootstrapped.

Plus one smaller one: `.WTEL` had to be repointed to the genesis vanity address `0x…37E1`
or step 4 would have deployed a duplicate WTEL and wired every Uniswap router to it.

**CORRECTION (2026-09-18):** mid-run I "fixed" the observer inheriting open consensus P2P
from the role-blind `--enable` path by making devnet-firewall.sh actively CLOSE 49590/49594
on observers. That was wrong and has been reverted. An observer is not a permanent category
-- node-5 is staked into the committee post-genesis by design -- and once staked it must
accept inbound consensus traffic. The damage would also have been delayed and misattributed:
the ports would have been re-closed by the NEXT routine run of devnet-firewall.sh, long after
the staking change that needed them, presenting as a consensus bug. devnet-firewall.sh now has
NO role branch for consensus ports; every node gets them opened and asserted. This is not a
wide exposure -- the VPC rule devnet-allow-consensus already restricts those ports to the
fleet's own /32s behind the `validator` tag, which every node carries.

## Decisions taken during the run

- Contracts admin is `0xAee2797478Cb5EfaF1869A2e33e369421EBf520f` — the only admin key we
  hold. `.admin` was repointed at it and it is funded at genesis. Deploying with a key that
  is not `.admin` reverts `TestnetGrantRole.s.sol:88` and breaks `SeedTestnetLPs`.
- Deployed from `deploy/devnet-relaunch` (d95fea88), matching the generator's submodule pin.
  tn-contracts HEAD carries different CREATE2 salts and a wholly different address book.
- There is **no FAUCET role** in tn-contracts (the plan's step-14 grant does not exist).
  `dripTo`/`drip` are permissionless, so `enable_stablecoin_funding` needs no grant at all.

## Advertised RPC in genesis/ (2026-09-18)

`genesis/validators/node{1..4}.yaml` and `genesis/observers/node5.yaml` now carry the node's
public JSON-RPC endpoints, and `devnet-keygen.sh` passes `--rpc-http` / `--rpc-ws` so a full
redeploy REGENERATES them with the same values. That wiring is the part that matters: every
file under `genesis/` is rewritten by the deploy (node-info by keygen at step 5, committee +
genesis by the build at step 6), so hand-editing them alone would have been undone by the
next run.

Shape notes, all taken from telcoin-network rather than guessed:
- `RpcInfo` is attached to the **worker** P2pNode only. Primaries keep `rpc: ~`
  (`crates/types/src/committee.rs:93-99`).
- `http` is required and must be http/https; `ws` is optional and must be ws/wss; clap makes
  `--rpc-ws` require `--rpc-http`.
- URLs serialize with a trailing slash and quoted, matching the serializer's own output, so a
  regeneration produces no spurious diff.
- These are application-layer URLs published through the kademlia node record for wallets and
  dapps. They are never dialed by the libp2p swarm, and they point at Caddy on :443 -- not
  reth's loopback 8545/8546.

Verified by running the real `telcoin genesis` build against these files in a scratch dir:
the binary accepts them and the worker RPC propagates into `committee.yaml` for all four
validators, with the four primaries still `~`.

`genesis/committee.yaml` and `genesis/genesis.yaml` were deliberately NOT regenerated. They
are the record of the LIVE chain, and rebuilding them would make the repo disagree with what
is staged on the fleet -- a later step-7-only run would then push a changed committee at a
running chain. They pick this up naturally at the next full rebuild (step 6).

APPLIED TO THE LIVE FLEET 2026-09-18. All five nodes had `telcoin keytool set-rpc --http URL
--ws URL` run against their datadir and were then restarted, because the runtime reads the
endpoint at STARTUP and signs it into the kademlia node record there -- set-rpc alone only
edits the config field (`set_rpc.rs:1-13`). It needs no BLS passphrase and regenerates no keys.

Restarts were strictly ONE NODE AT A TIME. The committee is 4 validators with
`quorum_threshold=3`, so exactly one may be down; the helper gated each node on a witness
node still logging `quorum reached` both before and after, and would have stopped the run
rather than touch a second node. The observer went first as a zero-risk canary. Every node
rejoined within 10s and quorum never dropped below 3/3.

Proven functionally, not just by reading the file back: a 0-value tx submitted ONLY to
node5 -- a NON-COMMITTEE observer that cannot produce blocks -- was mined in 5s. The only
path there is the worker forwarding it to the owning validator's JSON-RPC endpoint discovered
over kademlia (`start_epoch.rs`, issue #804). That also confirms the endpoints satisfy
`ForwardTargetPolicy`, which refuses non-public hosts unless the operator opts in.

## Still open

- [x] **WireGuard lockdown — RESOLVED 2026-09-18: not applicable to devnet, and its goal is
      already met.** With the operator's tunnel up, the overlay pre-flight passed 5/5 and
      Phase A ran, reconciling `wg-allow-iap-ssh` down to IAP-only (`35.235.240.0/20`) and
      dropping a stray `153.53.208.55/32`. Phase B then aborted cleanly, removing nothing:
      `could not enable tn-nftables`.
      That abort is CORRECT, not a bug. `devnet-startup.sh:199` boots every node with
      `WG_NODE_FIREWALL=0`, and the node logs `overlay only; NOT installing policy-drop nft
      table (UFW authoritative)`. Devnet deliberately runs UFW as the SINGLE authoritative
      host firewall -- wg-node-bootstrap.sh:34-41 says a second policy-drop table "would
      create an intersection trap". lockdown-firewall-gcp.sh's Phase B is written for adiri's
      nft model and cannot apply here.
      The posture it targets is already in place: the ONLY tcp:22 ingress rule in tn-devnet
      is `wg-allow-iap-ssh` (IAP only), `default-allow-ssh` is absent (Phase C satisfied), and
      `nc :22` from off-net is refused/filtered on every node. Verified.
      OPTIONAL residual, devnet-native: host UFW still allows `22/tcp from Anywhere`. Behind
      the VPC gate that is a no-op, but narrowing it to the IAP range + the 10.100.0.0/16
      overlay would be the UFW equivalent of Phase B. Not done -- it changes SSH reachability
      and wants a deliberate call.
- [ ] Push the four repos (see below) — everything is committed locally, nothing pushed.
- [ ] Delete `v0.12.1-devnet-fork722` + `-fork740` from the registry now the reset has landed.
- [ ] 2 wTEL V2 pools are empty (admin holds native TEL, not wrapped), so TEL-denominated
      swap paths have no liquidity. 22 eXYZ pools are seeded and the generator is happy.
- [ ] Re-run `setup-firewall.sh` after ANY future instance stop/start — VPC consensus rules
      are keyed to node IPs.
- [ ] Optional: `common/observability/setup-obs-firewall.sh`, `setup-obs-disk-alert.sh`,
      and the two Grafana alerts (txgen submit-rate zero; master balance < 50 TEL).

## Review: r20261006-0053 stall → certifier fix → r20261006-0458 (2026-10-06)

Done:
- Root cause (tasks/stall/ROOT-CAUSE.md): Certifier::run cancelled and restarted vote collection on
  every identical 500 ms re-proposal, so validators whose vote round trips exceed one window never
  certified (v03/v04 in Australia: 0% in fast rounds). The committee ran on 8 certifying validators;
  killing v05 left 7 = quorum; v10 (next leader, 250 ms window) failed at round 1787 → 6 certs < 7 → 301 s stall.
- Fix: telcoin-network fix/certifier-keep-inflight-on-repropose (9b4bca750 + 963b59980; 3 tests; 290/290 crate
  tests; clippy/fmt clean), merged into devnet-bench-10-5-2026 = ba43a1f0e; both pushed.
- Image adiri:mmap-subsecond-certfix-10-6-2026 @ sha256:caeb6be2… (docker-devnet target; docker-adiri gives adiri-schedule).
- Re-run r20261006-0458 (blast index 2, n2 blasters after an e2 stockout): NO stall through a 300 s outage 59 s
  before the boundary; all-gen 3,889.6 tx/s (3,319.6 with the stall; 4,177 on 29 Sep); Canceled -81%; v03/v04
  under load 24% → 60-68% certification; 1/10 generators hit the preamble limit (was 8/10).
- Harness (bench/preserve-logs-and-harness-fixes): 14141d0 archive gate + IAP retry; 3a31603 staged chaos +
  boundary verdict + stall note; f89823d exclude `^` fix; eef693a stall needs flat rounds. Live: chaos late ≤0.18 s,
  archive gate verified 60 files before deletes, 319 objects in gs://tn-devnet-benchmark-archive/runs/r20261006-0458/.
- txgen: fix/preamble-gap-repair 9f61303 (unpushed, not built).

Open:
- Far validators certify 0% in fast rounds and ~1/3 of their certificates are orphaned → 372 s inclusion gap when
  only they carry load (upstream question; not reachable by the certifier fix).
- v05 recovery 12.5 min when the epoch closed during the outage (execution-bound catch-up).
- Operator: archive the OLD run's logs (`benchmark/benchmark-teardown.sh --run r20261006-0053 --yes`, fleet already
  gone; blocked for the agent by the permission mode); publish 0458 if wanted (backfill draft has 8 placeholders).
- Harness: automatic machine-family fallback on stockout; blaster machine type into the manifest.

## Review: devnet full reset onto tn-node-deployment v2 + v0.2.0-devnet (2026-10-30)

Code-complete, reviewed and rehearsed locally; NOTHING has run against GCP (gcloud auth was
expired for the whole session). Operator steps: tasks/runbook-reset-2026-10-30.md. Unit map and
evidence: tasks/plan.md + tasks/checkpoint-reset-*.md.

Done:
- tn-node-deployment PR #52 (`devnet-docker-images`, base `mainnet-hardening` @ 8175a88, head
  d9446f720026fa5ce8b64fce9074e56b05b3f4eb): devnet Docker installs pinned by digest from
  {tn-public/adiri, ghcr}; `-devnet` tag grammar (final=false); `--release-tag` refused on devnet;
  `_tn_guard_network` on the image-change paths; devnet rc 3 in release fetch/checkout; chain-id
  check after a devnet apply; versions 2.0.1; 3697 shell checks / 258 pytest / 494 helper checks
  green, bash 3.2 run green; independently reviewed (R4: testnet/mainnet identical over 3,783
  vectors × 3 registry modes, except the whitespace-repo tightening).
- telcoin-network `devnet/v0.2.0-devnet` = main 8aedf72e + PR 1715 (3f9b0709c, pushed); amd64 image
  built and loaded locally in 8 min; all CLI probes green. Registry push + digest pin pending auth.
- deploy-networks-common `devnet/genesis-knobs` (pushed; PR to open by hand): env-driven header
  delays, optional `--max-batch-delay-ms` / `--worker-fee-config`, `tn-scripts-ref` metadata, gated
  `--user` for the nonroot genesis image; byte-identical argv when unset (author + independent R5).
- devnet-genesis: config.sh (digest image, /opt scripts dir + 40-hex ref pin, root parameters.yaml,
  knobs 350/1000/250 + 0:0:10000000, SAFE_EXTRA_OWNER, node-5 secret name, GENESIS_DOCKER_USER);
  devnet-startup.sh (fetch by `tn-scripts-ref`, no useradd, no install.sh, reboot keeps the checkout);
  devnet-lib.sh (setup-node.sh, tn_iap_ssh_cmd_stdin with -T, tn_secret_set, tn_node_meta_get,
  refresh by sha, passphrase never exported); devnet-keygen.sh / devnet-finalize.sh /
  devnet-observability.sh / devnet-dashboards.sh on v2 (secrets on stdin only; finalize has a
  readiness gate + 5 post-checks incl. network-config validated byte-for-byte and post-gate log scan);
  devnet-genesis-build.sh (knob banner, node-5 funding check, parameters.yaml asserts, step 6 Safe
  owner patch via devnet-genesis-safe-owner.py — anvil: 8 owners, admin first, patch bytes equal
  addOwnerWithThreshold); NEW devnet-network-config.{sh,py} (closed admission; strict validator
  cross-checked against a serde_yaml-0.8 mirror); NEW devnet-stake-node5.{sh,py} (Safe-exec mint,
  stake, activate, watch; keys via pty keystore import; anvil rehearsal end to end); NEW
  devnet-basefee-check.{sh,py} (formula verified on the live chain); devnet-deploy.sh 16 steps with
  placeholder + sha gate; README/INSTRUCTIONS rewritten for v2.
- Reviews: R1 Safe patch, R2 network-config/finalize, R3 secrets (strace + /proc sampler), R4 PR
  #52, R5 common gate, R6 integration — every High/Medium/Low closed in-tree (see plan.md).

Open (operator):
- `gcloud auth login` → push image, pin digest, node-5 key (Secret Manager), fund it, teardown,
  deploy, stake, verify (runbook steps 0-7).
- Open the deploy-networks-common PR by hand (tasks/pr-common-genesis-knobs.md); after merges move
  `TN_NODE_SCRIPTS_REF` and the `common` gitlink to the merge commits.
- Live chain today: txgen idle since ~block 1238764; WorkerConfigs(0) target is 1,000,000 (fee
  ~6e12 wei). Both go away with the reset.

Follow-ups (not in this reset):
- devnet-update.sh / devnet-update-all.sh: `TARGET_TAG="${DOCKER_IMAGE##*:}"` is the digest hex now;
  compare `.node-meta` DOCKER_IMAGE_DIGEST with `${DOCKER_IMAGE##*@}` and use `update-node.sh --json
  --prepare --ref <digest>` / `--apply --yes` (now possible on devnet via PR #52); reset-network.sh and
  `devnet-update.sh --finalize` re-run finalize, which v2 refuses.
- benchmark/config.sh inherits devnet's digest DOCKER_IMAGE, the four genesis knobs, SAFE_EXTRA_OWNER
  and the root PARAMETERS_FILE (finalize would ship devnet's parameters.yaml from a benchmark
  workspace) — benchmark owner's call before the next bench run.
- Pre-existing secrets hygiene in the contracts path: devnet-contracts.sh:186 puts the admin key on
  `cast wallet address --private-key` argv and leaves ADMIN_PK in the tn-contracts `.env`; the
  tn-contracts bash scripts pass `--private-key` on argv. Needs a change in tn-contracts' scripts.
- Devnet admission monitoring: nothing reads `tn_network_admission_mode` yet (R2 I4) — add a Grafana
  panel / check after the first live run.
- After node 5 joins the committee: add it to every node's `committee_peers` in one coordinated
  network-config update + restart (until then restarts log a coverage warning).
- tn-node-deployment tasks/ckpt-*.md carry Mac scratchpad paths and are cloned onto every node at
  /opt/telcoin-node-scripts (harmless; tidy in a later PR).
- WireGuard lockdown, PR 1716 chain-487 guards, moving devnet images to ghcr: unchanged from before.
- (2026-11-02, launch 1) devnet-finalize.sh: retry a read-only post-check once on ssh rc 255 and add
  an assert-only `--verify nodeN` mode; a single transient IAP drop on node 4's A3 check ended the
  D3 run after all five nodes were already started (recovered with
  `devnet-network-config.sh --verify node4` + `--from 9`). See tasks/lessons.md.
- (2026-11-02, launch 1) R1 MINORs on the new tooling (tasks/checkpoint-l1-R1.md): key.sh A2 (temp+mv
  instead of in-place copy), A4 (match NOT_FOUND on describe), A5 (`python3 -I` for the read-back,
  together with devnet-stake-node5.sh); sign.sh B3 (check the key dir before reporting PENDING), B4
  (snapshot SHA256SUMS/IMAGE_DIGEST into TMP_DIR), B5 (assert GENESIS_FILE == workspace path); deploy
  C1 (conditional rc-1 hint). None affects correctness on this launch.
- (2026-11-02, launch 2 prep) tn-cli-dev: moving to telcoin-network 3f9b0709c needs three
  [patch.crates-io] entries (libp2p-quic, quinn-proto, libp2p-connection-limits → the TN rev) plus
  `cargo update -p quinn-proto`; proven in scratch, not applied. Needed once sentries make
  `tn node record` usable (c07d6d6a rejects records with >1 multiaddr).
- (2026-11-02, launch 1) common/dns.sh Phase 4 verifies the public endpoint ~1 s after the Caddy reload
  with no retry, so a node whose Let's Encrypt certificate is still being issued fails the step and
  stops the sweep (node 1 lost by one second; the cert arrived at 15:59:45Z, the probe ran 15:59:46Z).
  Add a bounded retry (e.g. 6 × 10 s) around the eth_blockNumber + WSS probes in the common repo and
  bump the gitlink. Worked around here by re-running `--only 13` until it passes.
- (2026-11-02, launch 1, F1) devnet-finalize.sh starts nodes sequentially ~80 s apart; with the 350 ms
  cadence the 4th validator came up >50 rounds late and sat out epoch 1 (CvvInactive until the
  boundary). Add a two-phase finalize (stage + enable everywhere, then start all units within a few
  seconds) or a `--no-start` + parallel `systemctl start`; until then, expect the straggler to rejoin
  at the next boundary and run the restart-free steps (12-14) first. Mainnet launch-day hazard; see
  tasks/lessons.md.
- (2026-11-02, launch 1, F2) devnet-observability.sh: after a restart the "after" probe accepts
  tn_nodeMode=CvvActive at 0 s, but the member is absent from commits for ~30-60 s, so the NEXT
  node's tn_committee_down_guard counts it as down and refuses (validator-3 after validator-2).
  Make the after-wait require the node's authority in the reference node's recent commits (or
  a fixed ≥60 s settle) before moving on. Worked around with scratchpad/recover-obs.sh.
- (2026-11-02, launch 1) txgen secrets live only on the Mac and, sops-encrypted, on the txgen VM:
  step 16 from xerxes failed on a missing tn-transaction-generator/secrets/master.key (the master
  wallet 0x46c26b4f… is genesis-funded, so it cannot be re-minted). Recovered by decrypting the VM's
  master.sops/children.sops with the age identity (.secrets/txgen-age-key.txt = Secret Manager
  devnet-txgen-age-key). Mirror master.key + children.seed to Secret Manager
  (devnet-txgen-master-key / devnet-txgen-children-seed, like the bench ones) and make
  devnet-txgen.sh's preflight restore them (or say where they come from); also step 2 silently
  mints a NEW age identity when the local file is missing instead of restoring the Secret
  Manager copy.
- (2026-11-02, launch 1) Native TEL faucet drips revert: the StablecoinManager/TNFaucet proxy
  0xf09a4e512cf87ecac839d732681959cefd83ecb9 has no mint role on the TEL precompile 0x…07e1
  (hasMintRole = false; the Safe has it). One governance Safe tx fixes it:
  to 0x00000000000000000000000000000000000007e1, calldata
  0xc2e3273d000000000000000000000000f09a4e512cf87ecac839d732681959cefd83ecb9 (grantMintRole),
  executed through 0x…07a0 (threshold 1; the contracts admin is an owner). Stablecoin drips
  already work. tn-cli has no subcommand for it (README notes the calldata).
- (2026-11-02, launch 1) devnet-stake-node5.sh `revert_selector` fixed for cast 1.8's resolved-error
  output; R1's MINOR A5 (`python3 -I`) still open there.

## Review: launch 1 — devnet reset onto tn-node-deployment v2 + v0.2.0-devnet (2026-10-31 / 2026-11-02)

Outcome: the devnet (chain 32285) was torn down 2026-10-31 10:58Z and relaunched on the v2 node
model with image adiri@sha256:5257e768…a610 (telcoin-network 3f9b0709c), a GPG-signed release
manifest verified with gpgv before any node started, node 2 moved from Sydney to Dallas
(34.174.181.214), closed admission on all five nodes, and node 5 minted, staked and activated
after genesis. The chain started 2026-11-02 15:33:56Z (the operator pauses for DNS and the YubiKey
signature spanned two days); all 16 deploy steps completed by 17:38Z. Verification with numbers:
tasks/verification-l1-2026-10-31.md (12/12 pass at 17:58Z). Commits: devnet-genesis b1b49be, ee6078a,
6807ece, 50c920a (+ c4); tn-cli-dev 8462884, a9a9e10, 6962def. Launch-2 design: docs/mainnet-simulation-plan.md.

What went to plan: Wave 1's nine units and both reviews (R1 fixed a `set -x` key-leak path and
tightened the gpg verdict; R2 caught a hot-key fallback in tn-cli's new-validator.sh); the key
provisioning script; prepare/verify with the laptop one-liner; D1b (VPC rules before any node start);
the stake script's Safe-exec mint, stake and activate (blocks 5025-5027, Active in epoch 3, drawn
into committee(5)).

What did not, and what it cost:
- F1 (protocol, mainnet-relevant): finalize starts nodes ~80 s apart; validator-4 came up 36 s into
  epoch 1, >50 rounds behind, and sat out the whole epoch as CvvInactive (rejoined at the 16:34Z
  boundary). Cost: ~1 h, and the observability quorum guard refused every restart meanwhile.
- F2 (tooling): devnet-observability.sh moves to the next node as soon as the restarted one reports
  CvvActive, but it is absent from commits for ~30-60 s, so the next node's guard refused. Recovered
  with a serialized driver gated on 4 distinct authors in a reference node's last 24 commits.
- A single transient IAP ssh rc 255 in a finalize post-check (node 4, A3) ended the step-8 run after
  all nodes were already started; finalize cannot be re-run on a node with a unit.
- dns.sh Phase 4 lost a ~1 s race against first-time Let's Encrypt issuance on three nodes (4 runs).
- Step 16 needed sops/age on xerxes and the txgen master key, which lived only on the Mac and
  (sops-encrypted) on the VM; recovered with the Secret Manager age identity.
- The gcloud token expired during the two-day pause; the old txgen kept running through the
  teardown and hit the new chain from 16:13Z (52M gas in epoch 1); its Prometheus series stopped
  at 17:39Z (V1-b, monitoring gap only).
- tn-cli could not move to 3f9b0709c (needs TN's [patch.crates-io] QUIC crates); stays on c07d6d6a.

Open follow-ups: see the dated items above (faucet grantMintRole Safe tx, txgen secrets and
service handling in teardown/step 16, dns.sh retry, finalize two-phase start + assert-only mode,
obs after-wait, Alloy `network` label overwrite (V1-a), txgen Loki job label (V1-c), R1 MINORs,
tn-cli re-pin for launch 2). V2 (node 5 seated at epoch 5 from 19:33:56Z, membership over 3 epochs,
base fee after more boundaries) is appended to the verification file when the watch ends.
