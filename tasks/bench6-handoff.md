# Bench 6 — handoff (written 2026-11-12 02:30Z for a new session)

This file is enough to take the program over. It says what is done, what the user has decided, what remains in order, and
where everything lives. Nothing has been launched on the fleet. The only cloud actions so far were three one-VM probes, each
deleted by its driver (`DOWN_OK`, and the project was listed afterwards: no `bench-probe-*` instance or disk is left).

## 0. Read in this order
1. This file.
2. `tasks/plan.md` — the tick list of the whole program (waves W0-W9, gates G1-G4).
3. `tasks/bench6-g1-brief.md` — the gate-1 decision list (27 items) with the orchestrator's addendum (§6), and the user's
   answers at the end of `tasks/bench6-g1-notes.md` (section "G1 — THE USER'S ANSWERS").
4. `tasks/checkpoint-bench6-orch.md` — the orchestrator's running log (newest at the bottom; the image-cut checklist is in it).
5. As needed: `tasks/bench6-contract.md` (every switch, log line and metric name), `tasks/bench6-cherrypick-ledger.md` (every
   commit on the node branch and where it came from), `tasks/bench6-upstream-followups.md` (what each topic owes before its
   upstream PR), `tasks/bench6-agent-rules.md` (rules every sub-agent gets), `tasks/bench6/briefs/` (every unit's brief),
   `tasks/bench6/quiet-host-runbook.md`, `tasks/lessons.md`.
The original plan the user approved: `/home/drtnarg/.claude/plans/i-want-to-run-groovy-grove.md`.

## 1. What bench 6 is
Recover the execution ceiling lost in bench 5 (3,449 tx/s against bench 4's 4,578), fix every bench-5 concern behind a
switch, measure the fixes on the ten-validator GCE fleet, publish, and upstream what the run confirms.
- Run 1: arms — one switch group at a time, by rolling restart, with blasts started by `run-arms.sh`.
- Run 2: the headline, on the configuration G3 chooses.
- Gates where the orchestrator stops and asks the user: G1 (done), **G2 before run 1**, G3 after run 1's analysis, G4 after
  run 2's analysis (then publish and upstream).

## 2. Standing rules (binding)
- No attribution to Claude or Anthropic on any commit, PR, issue or comment; no `Co-Authored-By`.
- The orchestrator alone pushes, runs `gh` writes, `gcloud` and fleet commands. Sub-agents never do. Opus agents implement
  and analyse; one writer per file; every agent gets a brief on disk, a checkpoint file and a budget (they overrun 250k
  tokens routinely: scope narrowly).
- `tn-node-deployment/` and `common/` are not edited.
- Fleet actions run detached through `benchmark/launch/launch.sh <env> <segment>`; nobody edits a driver while it runs; a
  creation script is shim-tested before it is ever run live; a dry run never shares a code path with the live call.
- Ad-hoc `gcloud` reads carry `--project tn-devnet`. A gcloud list-flag value never starts with `^`.
- Nothing but the node opens a live node's MDBX database.
- One e2e job on the machine at a time: `tasks/bench6/e2e-lane.sh <cmd>` (it also waits behind OTHER sessions' attest
  jobs in `tn-workspace`, up to 6 h). Every compiling cargo call goes through `tasks/bench6/cargo-slot.sh`.
- Push to telcoin-network with the explicit `git@github.com:` URL. Nothing old is deleted without the user's word.
- Issues and PRs only after the benchmark confirms a fix (assignee grantkee, reviewers MavenRain and sstanfield; all
  bench-6 PRs into one staging branch off main).
- The user's steer of 2026-11-11: on a cloud network disk the NUMBER of writes and syncs binds, on NVMe the bytes; every
  storage result reports write count, sync count, write size and commit time beside any byte ratio.

## 3. The user's decisions so far
From the plan: image base = the landed staging tree plus review follow-ups; everything switchable with defaults = bench-5
behaviour; two deployments (run 1 arms, run 2 headline); generator: measurements only.
**G1 (2026-11-12):**
1. Vote-starvation fix (#1804): run 1 measures BOTH forms — adaptive (`v-vote`, `quorum_exec_block_starved_rounds: 4`) and
   always-on (`v-vote-floor`, `0`). The headline's form is chosen at G3.
2. Pipelined persist: IN if its two open go/no-go gates pass (5: cycle bench on a quiet host; 6: switch-off e2e sets on
   the stack); otherwise CUT, with no further question (procedure in §6.4).
3. Disk comparison: ADD a short local-SSD deployment for the control and advice arms (the user chose this over the
   orchestrator's "none"). Needs harness work and a shape decision first (§6.3); goes to G2.
4. Bench-5 page: fix the trigger sentence and publish directly (authorised; §6.1).
Everything else per the brief's recommendations: the `read_ahead_kb` arm (P2) dropped; no-WRITEMAP (P3) not in run 1; no
prefault-off switch; no stage-step change; parent grace 150 ms with 100 ms as the fallback arm; nothing local pruned.

## 4. Where everything is
| what | where | state |
|---|---|---|
| Harness, plans, notes | `/home/drtnarg/coding/telcoin/devnet-genesis`, branch `main`, head 591f17b | 95 commits ahead of origin, NOT pushed; tree clean except `tn-node-deployment` pointer (not ours), `.claude/`, `benchmark/launch/bench5/`, task logs |
| Node integration branch | worktree `/home/drtnarg/coding/telcoin/telcoin-network-b6`, branch `bench/bench6-2026-11`, head **80a0c76c0** = base 165e3fe01 + 79 commits | NOT pushed. Every commit reviewed. Local `origin/main` reads 9aa1d6139: the base re-check is owed (§6.7) |
| Pipelined-persist stack (held) | branch `b6/pipe-stack-2` (checked out in worktree `tn-b6-u0c`), tip **d30bb1809** = d91d65d3e + 19 | must be re-stacked onto 80a0c76c0 if it goes in |
| Generator | `/home/drtnarg/coding/telcoin/tn-transaction-generator`, `main`, head **62bbd5f** | 4 commits ahead, NOT pushed; `BENCH_TXGEN_SHA` for the image = 62bbd5f |
| Site | `/home/drtnarg/coding/telcoin/tn-benchmarks`, head 31073aa | uncommitted `runs/r20261107-1504/{report.html,run.json}` (the corrected bench-5 page, one more fix owed: §6.1); never commit `.claude/` |
| Probe binary | `benchmark/work/probe-bin/mdbx-writeback-probe` (sha256 513f42ba…) ; crate `/home/drtnarg/coding/telcoin/mdbx-writeback-probe` | built |
| Probe results | `benchmark/results/r20261111-2310/probe/` (Hyperdisk, 20 arms), `…/r20261112-0024/probe/` (Hyperdisk + local NVMe); summaries copied to `benchmark/private/bench6-prep/probe/` | done |
| Spare node worktrees (all of `/home/drtnarg/coding/telcoin/telcoin-network`) | `tn-b6-u1` (gate runs, detached, warm for the whole workspace and the e2e binary), `tn-b6-u0a` (holds the pipelined cycle-bench release binary), `tn-b6-u7` (holds the contention-bench binary), `tn-b6-u0b`, `tn-b6-u2`, `tn-b6-u9`, `tn-b6-u8` | free |
| Archive | `gs://tn-devnet-benchmark-archive/runs/<run>/results/` holds benches 3, 4, 5 (verified size + MD5) | nothing local deleted |

Agents: every unit has handed back; no agent is running. Agent handles do not survive a new session — start fresh agents
from the briefs in `tasks/bench6/briefs/` (see `CONTINUE.md` there).

## 5. What is built and what was found (short)
- **Twelve switches** on the node (`tasks/bench6-contract.md`), default = bench-5 behaviour, logged once as `node switches …`
  and exported as `tn_node_switch{name}`. Eleven act on the integration branch; `pipelined_persist` is plumbed but inert
  there (its code is the held stack).
- **Verified on 80a0c76c0:** fmt, check, clippy, 4,351 workspace tests; the bench-6 e2e modules (sealed-keep and admission
  7 of 7, vote fix and drain 3 of 3). On d91d65d3e (six commits earlier): the repo's restarts / epochs / sigkill sets with
  all switches off 11/11, 11/11, 12/12 and with eleven on 11/11, 11/11, 12/12.
- **Reviews:** ten topic reviews plus a delta review; no Critical or High anywhere; parent grace needed fixes (done).
- **Local e2e findings:** with `sealed_tx_keep` off a four-node fleet loses accepted transactions in about half the runs
  with no client resend (#1807 reproduced); with it on, none. Vote fix: fast node's headers certified 0.63-0.73 off, 0.92-
  0.93 adaptive (0.985 modelled past its ramp), 0.99-1.00 always. Mixed-switch fleets stay one chain.
- **The probes** (details: `tasks/bench6-g1-notes.md`, the two "PROBE" sections):
  - GCE and Hyperdisk do not amplify by themselves (node-like arms 1.00-1.01×). A re-open alone does not either.
  - Bench 5's signature (222-228 KB writes, decimal: 217-223 KiB) is that of pages that sat in large page-cache folios before they were dirtied
    (11.9× in the read-through arms). WHAT did that on a real node is not identified; run 1's control arm must show it.
  - Whole-map `MADV_RANDOM` closes prefault-off (9.7× → 1.00×) and a foreign opener (1.8× → 1.00×), changes nothing when
    healthy, and does NOT repair a cache that already holds large folios — so the advice arm also evicts `mdbx.dat`, and
    the pair a0-control / a0-prime (defaults without / with eviction) is the first comparison to read.
  - No-WRITEMAP never amplifies (+23 % commit time when healthy). Not switchable in bench 6.
  - On GCE a local NVMe SSD made every MDBX commit 1.5-2.4× SLOWER than the fleet's Hyperdisk (one VM, both devices).
  - Bench 4's validators used about 45 % of their provisioned 20,000 IOPS; bench 5 was bound by the 800 MiB/s throughput.
- **Harness:** complete for run 1 except its README (wrap-up). `arms-summary.py` reads every new node field and reports
  write counts against the disk's caps; `test_run1_rehearsal.py` walks run 1's real data path in a sandbox; 407 mutation
  cases; `benchmark/tests/gate.sh` is the full local gate (must be alone on the host).

## 6. What remains before the fleet, in order
### 6.1 Bench-5 page: correct and publish (authorised by the user; do it first)
- Source of the page's text: `benchmark/report/backfill/2026-11-07-main-fixes.json` (`summary` and `caveats[2]`), mirrored in
  `tasks/bench5-report-r20261107-1504.md`.
- Wrong today: "The likely trigger … (about 60 %) … is a restart: … reopened for the run …". Both probes contradict it.
  Replace with: the trigger is not identified; reopening a database created during staging was the first suspect and did
  not reproduce the extra bytes (1.00× on the test machine and on a cloud VM of the validators' type and disk); in those
  tests the extra bytes appeared only when the file's pages had been read into the page cache before they were changed
  (11.9×, in writes of about 256 KiB = 262 KB; this run's were 222-228 KB, decimal), when the library's pre-write of new pages was off
  (9.7×), or when another process had opened the database (1.8×). Keep the page's plain voice; change nothing else.
- Re-bundle exactly as the last correction was bundled (`benchmark/private/bench6-prep/I-6b/corrections-2.md`, line 75, and
  `tasks/checkpoint-bench6-I-6b.md`): `make_bundle.py --run r20261107-1504 --compare r20261105-0803 --floor-blast-dir
  blast-0-20261107T163112Z --backfill benchmark/report/backfill/2026-11-07-main-fixes.json --txgen-bench <git archive of
  tn-transaction-generator 6dad96f>/bench --analysis-sha 6dad96f`, run from a worktree pinned at the harness commit that
  produced the published numbers (149f941, plus only the backfill text change) with `benchmark/results` symlinked — the
  harness has changed since, and the page's numbers must not. It took 719 s. Then the gates in `tn-benchmarks` named there
  (`build.py --check`, `scrub.py`). Check that the diff against the present uncommitted page is only the two text
  passages; commit the two files by path (never `.claude/`), push; the site deploys by Actions.
### 6.2 Run-1 plan: add the always-on vote arm
`benchmark/launch/bench6-run1.plan` has `v-vote` only; add `v-vote-floor` (arm file exists) after it with the same blast
types; re-run `test_launch` and the rehearsal. The final arm table is fixed at G2.
### 6.3 The local-SSD deployment (new at G1; the largest open item)
- Needs, in the harness (shim-tested, no cloud): the node's data directory on the local NVMe SSD (format + mount before the
  node's first start — the probe driver's `setup` in `benchmark/benchmark-probe.sh` shows the mkfs and mount options that
  were used), the `-lssd` machine type per node, the persist sampler and host probe pointed at that device, the manifest's
  `node_disk` saying local SSD with no provisioned caps, an env file and an arm plan (control with and without eviction,
  the advice arm), and the launch README. The teardown is unchanged (a local SSD goes with its VM).
- **No single local-SSD x86 shape exists in all ten of the fleet's zones** (checked 2026-11-12, read-only):

  | zone (validator) | `c3-standard-8-lssd` | `c4-standard-8-lssd` | note |
  |---|---|---|---|
  | us-west2-a (01) | no (nowhere in us-west2) | no | only `c4a-…-lssd` (Arm) |
  | europe-west2-b (02) | no (yes in europe-west2-a and -c) | yes | |
  | australia-southeast1-c (03) | yes | no | |
  | asia-northeast1-b (04) | yes | yes | |
  | us-east4-b (05) | yes | yes | |
  | europe-west4-a (06) | yes | yes | |
  | asia-southeast1-b (07) | yes | yes | |
  | asia-east2-a (08) | no | yes | |
  | asia-northeast3-a (09) | no | yes | |
  | asia-south1-c (10) | yes | yes | |

  So the user must choose at G2: a mixed C3/C4 local-SSD fleet; C4 in eight regions with two validators moved; a smaller
  fleet (the seven regions that have C3, moving validator 02 to europe-west2-a or -c); or other regions for this
  deployment. Each is a confound to state. The comparison arm on Hyperdisk should then use the same machine shape if
  possible (`c3-standard-8` instead of `c3-highcpu-8`: 32 GB against 16 GB of RAM matters for the page cache).
- Expected result, from the one-VM probe: slower commits on the local SSD. The deployment tests whether that holds under
  sustained load, where the Hyperdisk's 20,000-IOPS cap could bind and the local SSD's ≈ 90,000 write IOPS would not.
### 6.4 Pipelined persist: the two open gates, then in or out
- Gate 5: `tasks/bench6/quiet-host-runbook.md` §2 (the release binary is built in `tn-b6-u0a`). Needs a quiet host: other
  sessions' attest jobs are running on this machine now. PASS = `pass=true` in all four invocations and `overlapped` > 0.
- Gate 6: the repo's restarts / epochs / sigkill sets on the stack with the switch off — queued (§8). With the switch ON
  they already passed 11/11, 11/11, 12/12.
- **IN:** re-stack the 19 commits onto the integration head (new branch from `bench/bench6-2026-11`, cherry-pick
  `d91d65d3e..b6/pipe-stack-2`; expect one small conflict at most), run the workspace gates and the three
  `persist_pipeline` e2e tests on it, make it the integration head; change `rpc_admission_backlog_outputs` from 2 to 3 in
  the arm files `bound`, `gr150`, `gr100` (+ `benchmark/arms/switches.tsv`, the README table, the params-apply print-state
  golden).
- **OUT:** on the image branch revert the three plumbing commits 8ab9e89e4, d789015b0, 8d363e368 (so the image does not
  know the key and the arm tool refuses an arm that sets it), drop `pipelined_persist` from the arm files `pipe`, `bound`,
  `gr150`, `gr100` and the `pipe` arm from the run-1 plan.
### 6.5 e2e on the final head
Repeat on 80a0c76c0 (or the head after 6.4), then check a node log's `node switches` line (the override accepts a mistyped
key silently). A queued copy of this run exists (§8).
```
bash tasks/bench6/orch-e2e-sets.sh /home/drtnarg/coding/telcoin/tn-b6-u1 80a0c76c0 'allon=quorum_exec_block: true; quorum_exec_block_starved_rounds: 4; vote_queue_fix: true; mdbx_random_advice: true; sealed_tx_keep: true; digest_dedupe: true; recovery_threads: 3; epoch_close_task_drain: true; epoch_record_state_check: true; parent_grace: 150ms; rpc_admission_backlog_outputs: 2'
```
### 6.6 Quiet-host jobs (`tasks/bench6/quiet-host-runbook.md`)
The engine contention bench (U4b; feeds the I-3 verdict §3b), the pipelined cycle bench (gate 5), the full harness gate
`bash benchmark/tests/gate.sh --jobs 4`, and the per-commit strict check of the node branch (needed before upstream, not
before the image).
### 6.7 Image
- Base re-check: the branch's base is 165e3fe01; say what moved on `origin/main` since and whether a rebase is needed.
- Build exactly as `etc/Dockerfile` does (no test-utils features; `TN_TEST_*_DELAY_MS` unset). Push the node branch
  (explicit `git@github.com:` URL) and the generator (62bbd5f); build both images; record the digests;
  `benchmark/benchmark-deploy.sh --probe-node-image` by digest; pin `BENCH_TXGEN_SHA`.
- Dry runs: prestart per knob, `params-apply.sh` per arm file, the probe, the teardown.
### 6.8 G2 — ask the user before any fleet action
Bring: the final arm table for run 1 (with both vote arms, the pipelined arms in or out, the grace arms), its fleet time,
the local-SSD deployment's shape choice (6.3) and plan, the image digests, the dry-run results, what is still owed.

## 7. After G2 (unchanged from the plan)
Run 1 (deploy → arms → collect → teardown → archive; checkpoint `tasks/checkpoint-bench6-run1.md`; the runbook is
`benchmark/launch/README.md`) → the local-SSD deployment → analysis → **G3** → run 2 (headline) → report and bundle →
**G4** → publish, upstream (issues #1799-#1807 exist; `tasks/bench6-upstream-followups.md` lists what each PR owes) → wrap-up
(ledger verdicts, `tasks/todo.md` review section, lessons, memory note, README, archive both runs, push devnet-genesis).
For run 1's reading: judge storage arms on commit time and throughput with write counts beside bytes; read P1 against
a0-prime; label an arm by what the node measured (`mdbx_advised_bytes`, `keeps_sealed=true`, `pool=dedicated`), not by the
switch line; the admission-bound arm on landed tx/s AND refusals and drops; the grace arms on far-validator certification
AGAINST round time; stop an arm that shows the final-state halt line.

## 8. This session's background jobs at handoff time
Two e2e set runs are queued behind other sessions' attest jobs (the lane's 6-h deadline; they exit with rc 75 if it
passes) and will die if this session's shell goes away. Their logs say how far they got:
- stack, switch off (gate 6): `tn-b6-u0c/target/tmp/orch-e2e-d30bb1809-stackoff-{restarts,epochs,sigkill}.log`
  (re-run: `bash tasks/bench6/orch-e2e-sets.sh /home/drtnarg/coding/telcoin/tn-b6-u0c d30bb1809 'stackoff='`);
- final head, eleven switches on: `tn-b6-u1/target/tmp/orch-e2e-80a0c76c0-allon-*.log` (re-run as in 6.5).
A log that holds only "waiting for the lane lock" never ran.

## 9. Traps met on the way (all in `tasks/lessons.md`)
- A unit's own package gate is not the workspace's: after every batch of cherry-picks run
  `tasks/bench6/orch-gates.sh integ <spare worktree> <commit>`, more than once (a clock-dependent test passed twice).
- Two units handed back "needs a patch in a file I do not own" (`seals_via_quorum`, the pool limits): such a switch is logged
  but does nothing until the wiring commit and its test are in.
- A tool a script needs on a fresh VM is checked against the PINNED image (the first probe died on a missing `fincore`).
- `pkill -f <pattern>` from a shell whose own command line holds the pattern kills that shell; use `pgrep -f '[x]…'`.
- Chain a commit behind its format check with `&&`.
- `gcloud` credentials expire; a non-interactive session cannot renew them (`! gcloud auth login` in the prompt).
