# Bench 6 — handoff 2 (written 2026-11-13 ≈ 20:30Z for a new session)

The session that ran bench 6's three fleet runs is near its limit.
Nothing is running on the fleet and nothing bench-related exists in the cloud project.
The next session's first job is the two adaptive-form benches the user asked for (§4); the rest of what is owed is in §5 and §6.

## 0. Read in this order

1. This file.
2. `tasks/bench6-handoff.md` §2 "Standing rules" (binding, unchanged) and `tasks/lessons.md` (the 2026-11-12 and 2026-11-13 entries).
3. `tasks/bench6-report-r20261113-1351.md` §1 (the summary of all three runs; 638 lines in all).
4. `tasks/bench6-g3-brief.md` (what the user decided at G3 and what the investigations found after it).
5. `tasks/checkpoint-bench6-orch.md` (the running log, newest at the bottom; gitignored) and `tasks/checkpoint-bench6-run2.md` (how runs 2 and 2b were actually driven, segment by segment: the model for §4).
6. `benchmark/launch/README.md`, "Run 2: the headline" (the segment order).

## 1. Where bench 6 stands

Three fleet runs are done, torn down, archived and analysed. Node image for all of them: `adiri@sha256:874537ff1cd8d496140154837e7a36524978bdbf3b0440e48972b073d9852745`, built from `bench/bench6-2026-11` = 2df831e3c; generator 62bbd5f.

| run | id | what | result (bench 5's definitions) |
|---|---|---|---|
| run 1 | `r20261112-1520` | nine arms by rolling restart, 16 blasts | private; found that at full load every validator sits at the disk's provisioned 20,000 write IOPS |
| run 2 | `r20261113-1351` | the headline: bench 5's shape, `benchmark/arms/final.arm` (vote fix ALWAYS-ON, `vote_queue_fix`, `epoch_record_state_check`, `mdbx_random_advice`) | 5,322.1 tx/s (bench 5: 3,448.7); seen p50 12.99 s; certification at least 99.1 % everywhere; write amplification gone |
| run 2b | `r20261113-1630` | run 2 with the node disk at 50,000 IOPS | 7,329.0 tx/s; the disk no longer binds; own-header certification BROKE on four validators in the 40-minute blast (06 44.5 %, 10 68.2 %, 02 78.6 %, 09 95.8 %) |

Why run 2b lost certification (`benchmark/private/bench6-r20261113-1351/I-10/findings.md`): the always-on form names its author's own tip minus 8 outputs; once the disk stopped holding every engine at one pace the execution spread exceeded that floor, slow voters had not executed the block a fast author named, and the author's next header overtook their vote. Replayed on the measured data (arithmetic, not a run): floor 16 → validator-06 at 90 %, floor 32 → every validator at 99.7 % or more, fix off → 2.7 %.

Epoch records (`…/E-1/findings.md`, `…/E-2/findings.md`, `…/A3a/closes.md`): every close of all three runs certified with at least 7 of 10 validators on one hash and one closing block; the thinnest had exactly 7 voters (run 2b, inside the outage). The vote fix does not reach the record path. The killed validator stayed a follower about 16 minutes after its restart (the rejoin rule as written) and missed signing two records each time.

Everything else: the report, and `benchmark/private/bench6-r20261113-1351/cross-unit-notes.md` and `benchmark/private/bench6-r20261112-1520/cross-unit-notes.md` (pointers to every unit's file).

## 2. The user's latest instructions (2026-11-13, verbatim)

> ensure that the closing epoch vote records include the correct state info that contains the closing epoch block info - the record must match the execution data where the closing epoch calls were executed - I also want to know if validator-05 still recovered the closing epoch records that it wasn't able to sign on or if that is a bug we need to harden (since every node should have every closing epoch record at quorum - even if it didn't sign) - finally, I'm not sure about the always-on form vs the adaptive - I want to run another bench with the adaptive form to fully compare these two - depending on the solution, include an end-to-end test that crosses two epoch closes with the always-on/adaptive vote form and validators held behind, before the upstream PRs

Then, on the disk for the adaptive bench: first "20,000 IOPS only" (question dialog), then typed: "actually run it on both 20k and 50k".
Then: "continue background agents - the limit is close, so do not start the adaptive-form benches yet - instead, write a detailed plan and summary so another session can run those benches".

So: the adaptive form runs on BOTH disks (two deployments), and the user has not yet said "go" for a launch in the new session. Ask once before the first fleet action (one line: "launching the adaptive-form bench at 20,000 IOPS now, then 50,000: go?"), and ask for `! gcloud auth login` at the same time.

## 3. State of the machine and the cloud at handoff

- Cloud: no `bench-*` instance, disk, firewall rule or bucket (teardown dry run of `r20261113-2022`: 0 candidates). The devnet instances are untouched.
- A deploy for the adaptive form at 20,000 IOPS (`r20261113-2022`) was launched at 20:22:50Z, seconds before the user said not to start, and stopped at 20:24:22Z in step 0 (checks only; `== deploy12 rc=143`). It created nothing. Do NOT reuse that run id: `benchmark/results/r20261113-2022/` holds only its step-0 manifest. Leave it; nothing old is deleted without the user's word.
- gcloud login: 2026-11-13T13:26:38Z. A login has held at least 13.7 hours here; its real lifetime is unknown. Get a fresh login before each deployment.
- devnet-genesis `main`: about 175 commits ahead of origin, NOT pushed (push only at wrap-up, with the user's word). Harness head for the fleet = whatever `git rev-parse HEAD` is; `benchmark/` must be clean before a launch (only `benchmark/launch/bench5/` may be untracked).
- Harness gates: full gate green on 4175a1e; the arm-file modules green on 6f3e88a (`final.arm` filled, its tests updated). No harness file changed since.
- Parked processes of an older session, not ours to stop: pids 84214 / 84216 (an e2e queue on the first lane, deadlocked on its own wait pattern). Another session's `cargo-nextest` may be running; the second e2e lane waits for it by itself.

## 4. The adaptive-form benches: the plan

Two deployments, each identical to its always-on twin except `quorum_exec_block_starved_rounds` 4 instead of 0:

| run | disk | twin | arm file |
|---|---|---|---|
| run 3 | 20,000 IOPS (bench 5's) | run 2 `r20261113-1351` | `tasks/bench6/arms/final-adaptive.arm` |
| run 3b | 50,000 IOPS | run 2b `r20261113-1630` | the same |

The arm file is committed (b76ba87, sha256 `77a3dfaa8d4638383e8d7719312ab33f265c6d4f90370112c45d7271f5416bfa`): `mdbx_random_advice`, `quorum_exec_block`, `quorum_exec_block_starved_rounds 4`, `vote_queue_fix`, `epoch_record_state_check`; no host step. It lives outside `benchmark/arms/` on purpose: the harness tree and its tests stay exactly as they were for runs 2 and 2b. Checked already: `params-apply.sh --arm-file … --print-state` rc 0, and the deploy's `--print-prestart` writes the five switches (`NOV=5`).

### 4.1 Before each deployment
1. The user's go and a fresh `! gcloud auth login`.
2. `gcloud compute instances list --project tn-devnet --format='value(name)' | grep -c '^bench-'` → 0.
3. `git status --porcelain -- benchmark/` shows only `benchmark/launch/bench5/`; no driver running (`ps -eo args | grep -E '[b]enchmark-(deploy|blast|teardown)\.sh|[r]un-arms\.sh|[p]arams-apply\.sh'`).
4. Trap: never put a driver's file name (`benchmark-deploy.sh`, `params-apply.sh`, …) in the same shell call as a `launch.sh` call: the launcher's `pgrep -f` matches the calling shell's own command line and refuses.

### 4.2 Fill the env file, commit, launch (run 3; for run 3b add the IOPS line)
```
cd /home/drtnarg/coding/telcoin/devnet-genesis
RUN="r$(date -u +%Y%m%d-%H%M)"; D=tasks/bench6/$RUN; mkdir -p $D
sed -e "s|<run-id>|$RUN|" \
    -e 's|<image-digest>|874537ff1cd8d496140154837e7a36524978bdbf3b0440e48972b073d9852745|g' \
    -e 's|<node-sha>|2df831e3ca34c06a361a7acca10397787e7b332e|' -e 's|<txgen-sha>|62bbd5f|' \
    -e 's|^BENCH_ARM_FILE=.*|BENCH_ARM_FILE=tasks/bench6/arms/final-adaptive.arm|' \
    benchmark/launch/bench6-run2.env > $D/bench6-run3.env
# run 3b only:  printf '\nBENCH_NODE_DISK_IOPS=50000\n' >> $D/bench6-run3.env
git add $D/bench6-run3.env && git commit -q -m "tasks: bench 6 run 3 — env of $RUN"
bash benchmark/launch/launch.sh $D/bench6-run3.env deploy12
```
(`tasks/bench6/r20261113-2022/bench6-run3.env` is the stopped attempt's copy: a model, not to be launched.)
Each segment is its own call: `launch.sh <env> <segment>`; wait for `^== <segment> rc=` in the log it names; one segment at a time. Wait with a background until-loop that has a deadline (see the waiters in `tasks/checkpoint-bench6-run2.md`'s history; never poll in the foreground).

### 4.3 Segment order and what to read after each
| # | segment | about | read |
|---|---|---|---|
| 1 | `deploy12` | 43 min | `BENCH_DEPLOY_RESULT rc=0 last_step=12`; `manifest.param_arms: final-adaptive via prestart` with the sha above; `HOST_PROBE_SUMMARY … uniform=yes`; the fsync probe's slow list (a note, not a stop) |
| 2 | idle-window checks (4.4) | 2 min | before `blast15` |
| 3 | `blast15` | 95 min | `LIGHT_LOAD_DONE` twice rc 0, the chaos lines (validator-05 killed, started 300 s later, observer restart), `BENCH_BLAST_DONE` × 10, `BENCH_DEPLOY_RESULT rc=0 last_step=15`; beside it `bash tasks/bench6/orch-fleet-health.sh <run> --watch 300 --disk-max 80 --until-file <blast15 log>` in the background |
| 4 | preliminary read + metric export (4.5) | 4 min | while the fleet is still up |
| 5 | `teardown-dry` | 1 min | this run's 12 instances, 13 disks, 2 firewall rules, 1 bucket only |
| 6 | `teardown` | 10-15 min | `TEARDOWN_DONE … deleted=12 left=0`, "left nothing behind", devnet untouched |
| 7 | `reindex`, then `archive` | 8 min | `ARCHIVE_VERIFY ok=1 … problems=0` |

Run 3b additionally, after `deploy12`: `gcloud compute disks list --project tn-devnet --format=json | jq '[.[]|select(.name|test("^bench-(validator|observer)"))|.provisionedIops]|unique'` → `["50000"]`.

### 4.4 Idle-window checks (the bench Prometheus is forwarded to localhost:19090 after `deploy12`)
```
q(){ curl -s --max-time 20 --data-urlencode "query=$1" http://localhost:19090/api/v1/query; }
q 'count by (name) (tn_node_switch == 1)' | jq -r '.data.result[]|"\(.metric.name)=\(.value[1])"'        # the four bool switches on 11 nodes
q 'count_values("v", max by (node) (tn_node_switch{name="quorum_exec_block_starved_rounds"}))' | jq -c '.data.result'   # expect value 4 on 11 nodes (check how the gauge exposes an integer switch; the node's own `node switches` log line is the fallback)
q 'count_values("bytes", max by (node) (tn_reth_mdbx_random_advice_bytes))' | jq -c '.data.result'       # 8796093022208 x 11
q 'sum by (node) (tn_reth_mdbx_page_ops_total{op="prefault"}) / sum by (node) (tn_reth_mdbx_page_ops_total{op="newly"})' | jq -r '.data.result[]|"\(.metric.node) \(.value[1])"'   # about 0.8 idle, 1.1-1.2 under load; 0.25 would be run 1's skipped-prefault state: stop and ask
q 'count(tn_node_mode{network="bench"} == 1) by (mode)' | jq -c '.data.result'                            # cvv_active 10, observer 1
```
Confirm in the deploy log or the manifest that the adaptive value reached the nodes: `jq '.param_arms[0].switches.quorum_exec_block_starved_rounds' benchmark/results/<run>/manifest.json` → `"4"`.

### 4.5 Before the teardown, while the fleet is up
```
S=<scratchpad>; : > $S/empty.txt
python3 tasks/bench6/orch-prom-read.py benchmark/results/$RUN/manifest.json $S/empty.txt > tasks/bench6/$RUN/prelim-prom-read.txt
python3 tasks/bench6/orch-prom-export.py benchmark/private/bench6-$RUN/prom-export <deploy start + 15 min, RFC3339> "$(date -u +%FT%TZ)"
```
The export (382 metrics, about 22,000 series, 3 minutes) is what the analysis units read; without it they need a Prometheus replay.

### 4.6 If something goes wrong
- Key generation fails on a node (it happened: an IAP drop mid-setup, `tasks/checkpoint-bench6-run2.md`): step 5 cannot be resumed (the keygen driver's reuse check does not match what the node setup writes). Tear the fleet down and deploy fresh under a NEW run id. A fleet whose nodes never started has no logs, so its teardown needs a copy of the env file with `BENCH_TEARDOWN_SKIP_LOGS=1` and `BENCH_TEARDOWN_SKIP_LOCAL_GATE=1` appended (model: `tasks/bench6/r20261113-1327/bench6-run2-teardown.env`).
- A segment must be stopped: only on the user's word. `kill <pid of the launcher's wrapper>` (the pid `launch.sh` prints) passes TERM to the driver; the permission system has refused `kill` before, and then the user runs it with `!`.
- The token expires: nothing can be torn down until the user logs in; say so at once.
- Anything outside this plan on a live fleet (an extra blast, an extra arm) is refused by the permission system and is the user's decision: put options to the user BEFORE a run, not during.

### 4.7 What the comparison must answer (the analysis after both runs)
Reuse the run-2 units' scripts under `benchmark/private/bench6-r20261113-1351/<unit>/scripts/` (each takes a run id) and the brief `tasks/bench6-run2-analysis-brief.md` as the model; outputs under `benchmark/private/bench6-<run 3 id>/`. One writer per file, opus agents, each under 200k tokens with a checkpoint (`tasks/bench6-agent-rules.md`); agents cannot write `findings.md`-style files reliably (the Write is refused to sub-agents for some names): have them return the text between `===== BEGIN … =====` / `===== END … =====` and save it from their transcript.
Per disk, always-on (run 2 / 2b) against adaptive (run 3 / 3b), same rows:
1. Throughput by bench 5's definition and its five-minute buckets; seen p50 / p95 / mean; the floor (A1's reader).
2. Own-header certification per validator per window, refused-behind votes, `superseded` answers, `lock_ms`, execution lag per node, round time (A2's scripts).
3. Per header: which basis named the block (own tip, quorum value, floor), how many voters held it, and for the adaptive form how often each proposer sat inside its starved window (`I-10/scripts/perheader.py`, `q2.py`, `q4.py`; they take a run and a window). This is the heart of the comparison.
4. Engine split, device writes against the limit, what binds (A4e, A4p).
5. Epoch closes and the kill (E-1's scripts via `A3a/scripts/`): signers, one hash, recovery time.
What run 1 and I-10 lead one to expect, to be TESTED, not assumed: at 20,000 IOPS both forms hold (run 1: adaptive 98.5 %, 126 refusals at full load; always-on 99.9 %, 0); at 50,000 IOPS the adaptive form names the own tip until starved and then behaves like the floor-8 rule inside its window, so it may lose as much or more than the always-on form. If neither form holds at 50,000 IOPS the question becomes the floor's depth (16, 32), which needs a node change, a new image and the user's decision.
Then: an addendum to the report (`tasks/bench6-report-r20261113-1351.md`, a new section, the existing text unchanged except where a statement becomes wrong), and the result to the user with a recommendation on the form.

## 5. Other work the user asked for, and its state

Three agents were launched at about 20:10-20:20Z, stopped by an interrupt minutes later, and started again at about 20:40Z from the same briefs (the user said to continue them).
They save as they go: each rewrites its checkpoint after every section, E-3 and E-4 also write their full findings text to `tasks/checkpoint-bench6-E-3-findings.md` and `tasks/checkpoint-bench6-E-4-findings.md` (a sub-agent's Write of `findings.md` under `benchmark/private/` has been refused before; copy the text from there to the output path), and ST-E commits on its branch after every step.
If the new session finds them unfinished, start them again from the briefs (each brief is complete; each agent reads its own checkpoint first):

| unit | brief | checkpoint | output | answers |
|---|---|---|---|---|
| E-3 | `tasks/bench6/briefs/e-3.md` (+ `e-common.md`) | `tasks/checkpoint-bench6-E-3.md` | `benchmark/private/bench6-r20261113-1351/E-3/findings.md` | is a record's `final_state` always the block where the epoch-closing calls executed (code), was it at every close of the three runs (logs), what check or assertion is missing |
| E-4 | `tasks/bench6/briefs/e-4.md` | `tasks/checkpoint-bench6-E-4.md` | `…/E-4/findings.md` | did every node end up holding every certified record, validator-05 included; is that guaranteed or timing; a bug to harden or not |
| ST-E | `tasks/bench6/briefs/st-e.md` | `tasks/checkpoint-bench6-ST-E.md` | new module `crates/e2e-tests/tests/it/epoch_close_forms.rs` in worktree `/home/drtnarg/coding/telcoin/tn-b6-u2`, branch `b6/st-epoch-close-forms` (created at 2df831e3c) | the end-to-end test across two closes with each vote form and validators held behind; it asserts E-3's and E-4's properties and the missed-window re-vote path |

**E-3 and E-4 finished at about 20:43Z** (findings saved at their output paths; summaries in `tasks/checkpoint-bench6-orch.md`, the last entries):
- E-3: a record's `final_state` is the block where the epoch-closing calls ran, by construction (the calls run in the last block of the closing output; the record reads that ring tip after waiting for that output), and it held at all 37 closes of the three runs on every node, the observer and validator-05's replays included. But nothing in `write_epoch_record` checks it (the block's closing `extraData`, `parentBeaconBlockRoot == final_consensus`, the registry's `blockHeight − 1`), `final_state` is never logged, a node with the state check off or after a restart can carry a certified record that is not its own closing block without the record path noticing, and no test asserts the property. Its options: an explicit check that halts on a mismatch (build path and stored-record path), an info line with the record's fields, the three assertions in the e2e helper, a unit test.
- E-4: validator-05 holds every closed epoch's certified record in both headline runs (the outage close through the startup sync about 8 s after it started; the follower close through the background collector within 4 s of the fleet's quorum); 403 of 407 node-epoch cells over the three runs hold the certified record on one hash (the other 4 are nodes stopped before run 1's last close); the longest a running node lacked a certificate the network had was 5.5 s. No bug showed. One gap in the code is worth hardening (never reached in the runs): an epoch the WHOLE network leaves uncertified stops the record collector and the startup sync at that epoch on every node (`state-sync/src/epoch.rs:343-345`), and a restart does not help; a second, smaller one: a conflicting certified record on the collector path is only logged.
These two results are NOT yet reported to the user in full if this session ended first: give them the two answers above, and ask whether the explicit `final_state` check (E-3 option 1-3) and the collector hardening (E-4's G1) should be built now (a node change: new image, behind a switch like the others, and the e2e test covering them) or filed as issues.

What was known on E-4's question before it ran (from `E-1/findings.md`): in run 2 validator-05 fetched the certified record of the epoch that closed during its outage at startup (15:46:07Z, the state-sync path), replayed that close onto the fleet's block with the state check passing, and fetched the next record 6 s after its close; no node logged `Failed to retrieve an epoch record`.
ST-E's test is wanted "before the upstream PRs" and "depending on the solution": write it for both forms now; if the form or the floor changes after run 3 / 3b, the test follows.

## 6. Still owed after that (unchanged plan, in order)

1. Gate G4: nothing is published and nothing goes upstream before the user says so. The G4 brief is not written yet; it should put to the user: what to publish (run 2 as the bench-6 page; run 2b, 3, 3b as sections or pages), the vote fix's form and floor, which fixes go upstream now.
2. P: the bundle's backfill file (`benchmark/report/backfill/<date>-<slug>.json`, schema of `2026-11-07-main-fixes.json`: title, summary, methodology, caveats, fleet, recovery, compare_to) = the public page's text; then `launch.sh <run 2 env> bundle --compare r20261107-1504 --backfill <file>`. Publishing recipe: memory note "devnet benchmark site publishing".
3. Upstream (after G4; rules in `tasks/bench6-handoff.md` §2: issues and PRs only after the benchmark confirms a fix; assignee grantkee, reviewers MavenRain and sstanfield; one staging branch; no attribution anywhere): confirmed so far are `vote_queue_fix` and the write-pattern fix (`mdbx_random_advice` from the first process; note upstream is moving to tn-lmdb, PR #1834); `quorum_exec_block` is confirmed on bench 5's disk and open on its form and floor; the pool group is open (`sealed_tx_keep` causes the side effects, `…/bench6-r20261112-1520/I-7/findings.md`); new issue candidates: rejoin under sustained load, the false `failed to reach quorum on epoch close` error, the record's untested paths (E-2 §4).
4. Harness defects still open (needed only before another arm walk, or as wrap-up): run 1's R1-D2, D3, D4, D7, D8, D9 (`…/bench6-r20261112-1520/A4o/defects.md`); run 2's two: the keygen driver's reuse check (`devnet-keygen.sh:135-143` wants `VALIDATOR_ADDRESS` in `.node-meta`, which the keygen phase does not write) and the transport retry that re-runs a setup whose first attempt is still alive.
5. Wrap-up: ledger verdicts (`tasks/bench6-cherrypick-ledger.md`), `tasks/todo.md` review section, lessons, memory, the launch README, push devnet-genesis (the user's word first).

## 7. Files

- Runs' results (gitignored, also in the archive bucket under `runs/<id>/results/`): `benchmark/results/{r20261112-1520,r20261113-1351,r20261113-1630}/`.
- Analysis (gitignored, private): `benchmark/private/bench6-r20261112-1520/` (run 1: A1-A8, A4o, I-7, I-8, I-9) and `benchmark/private/bench6-r20261113-1351/` (runs 2 and 2b: A1, A2, A3a, A3b, A4e, A4p, A6, A7, E-1, E-2, I-10, `cross-unit-notes.md`); metric exports `benchmark/private/bench6-<run>/prom-export/`.
- Orchestrator scripts: `tasks/bench6/orch-fleet-health.sh`, `orch-prom-read.py`, `orch-prom-export.py`, `orch-harness-gate.sh` (start with `setsid`, never `nohup`), `e2e-lane2.sh`, `cargo-slot.sh`.
- Briefs: `tasks/bench6/briefs/` (this round: `e-common.md`, `e-1.md` … `e-4.md`, `i-10.md`, `st-e.md`, `r-common.md`, `r1.md` … `r3.md`); analysis briefs `tasks/bench6-run1-analysis-brief.md`, `tasks/bench6-run2-analysis-brief.md`.
- Saving a sub-agent's refused `findings.md` from its transcript: the small Python snippets in `tasks/checkpoint-bench6-orch.md`'s history (search the session transcript for "BEGIN findings.md").
