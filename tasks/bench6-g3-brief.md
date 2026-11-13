# Bench 6 — gate G3: what run 1 showed, and the choice for run 2 (written 2026-11-13 ≈ 01:15Z)

Run 1 (r20261112-1520) is walked, torn down, archived and analysed.
Its main result is not about any one fix: at full load every validator ran at its disk's provisioned write limit, so the fleet's rate is 20,000 divided by the disk writes per transaction.
The vote fixes are confirmed.
The other fixes work as built, but each has an open cost or changes what a headline would measure.
Nothing is launched; run 2 waits for your answers in §2.

Evidence behind every line: `benchmark/private/bench6-r20261112-1520/` (`A7/verdicts.md`, `A7/final-arm-options.md`, `A7/candidates.md`, `cross-unit-notes.md`, and the eight units' folders), and `tasks/checkpoint-bench6-run1.md`.

## 1. What run 1 showed

### The limit at full load is the disk

- Every warm full-load minute sat at 19,900-20,100 device writes per second per validator, the provisioned 20,000 IOPS, in writes of about 5 KiB (`A4p/cache.md` §3).
  Cloud Monitoring agrees (each validator's ten highest minutes lie between 19,976 and 20,344), and so does the harness's own arm summary ("the disk's IOPS cap bounds this arm").
- At that limit the rate is 20,000 over the writes per transaction.
  The opening control made 3.1 writes per transaction and landed 6,165 tx/s; the closing control made 5.1 and landed 2,852.
- Writes per transaction follow three things, and no switch moves them by itself (`A8/writes-model.md`): the database's size (more as it grows), the transactions per consensus output (fewer writes per transaction in a larger output) and how many distinct accounts an output touches.
- Bench 5 was at a different limit: about 2,380 writes per second of 227 KB each, at the disk's byte limit during every commit.
  The validators of run 1 made no such whole-block writes in any arm, the control included; only the observer did, in the opening control.
- So "against bench 5's 3,449 tx/s" compares a run bound by write count with one bound by bytes.
  For a 40-minute full-load blast on this disk the model gives about 5,200 to 5,700 tx/s on average, falling by about a third from start to end as the database grows (an extrapolation, ±7 % inside the measured range).
- This machine shape allows 50,000 IOPS on the same disk type (Google's documentation, found by search; I could not open the page itself), the project's quota for it is unlimited (read 2026-11-13), and the harness has the knob (`BENCH_NODE_DISK_IOPS`).
  At 50,000 the model says execution binds before the disk, at about 8,600 to 10,300 tx/s.

### The switches

| switch group | what run 1 shows | how solid |
|---|---|---|
| vote fix (`quorum_exec_block`, `vote_queue_fix`) | own-header certification of the three worst validators at full load 93-95 % → 98.5 % (adaptive form) or 99.9 % (always-on form); refused votes 2,398 → 126 or 0; vote-lock wait p95 3.6-7.9 s → 0 | confirmed; the two forms ran at different cache states |
| `mdbx_random_advice` | nothing to fix on the validators; the observer's whole-block writes (10.9 times) went to 1.06 times in the step that applied it with an eviction and a restart | no effect measured on validators; observer not attributable |
| pool group (`sealed_tx_keep`, `digest_dedupe`, `recovery_threads`, `epoch_close_task_drain`) | no gap resends and nothing left unlanded; but outputs touch 1.5 times as many distinct accounts per transaction (about 1.2 times the writes), 19 % of one blast's output transactions did not execute, and the generators saw duplicate batch digests | benefit confirmed; side effects measured, not attributed to a switch |
| `pipelined_persist` | meets its design gate (cycle 1.01 times the longer of build and commit); no gain while the disk binds; alone it had the smallest outputs and the slowest full-load blast (2,562 tx/s, 36.7 s seen p50) | mechanism confirmed; no throughput case on this disk |
| admission bound | 4,093 tx/s and 10.2 s seen p50 by refusing 42 % of send calls and dropping 2,336 transactions; the gain runs through outputs 2.8 times larger | measured only with the pipeline on |
| `parent_grace=150ms` | the two far validators go from 2 % to 10 % of committed certificates and their users from 13-16 s to 2.5 s at light load; rounds 28 % longer, floor seen p50 1.51 → 1.77 s, and one validator's leader share went from 13 % to 0, unexplained | confirmed at idle and light load; not measured under sustained load |
| `epoch_record_state_check`, `epoch_close_task_drain`, `digest_dedupe` | never exercised: no halt, no task overflow on a validator with or without the drain, dedupe counters 0 | no evidence either way |

No arm showed a final-state halt, a fatal database error or a panic.

### What I told you earlier that was wrong

- "Mostly the cold cache" for the fall between the two controls: the cold cache is 7-27 % of it; the rest is writes per transaction at the disk limit.
- "Every blast rc 0": two funds timed out and still reported success, so the `p1` and closing-control blasts ran with 3,800 and 4,400 of 6,000 senders. The harness now fails such a fund.
- The second stop cost about 20 minutes of fleet time, not 40 seconds; my wait for your word on the calibration arm cost another 24.

## 2. Decisions

**D1. Which runs.**

| plan | what it is | fleet time | what it gives |
|---|---|---|---|
| P1 (recommended) | run 2 on bench 5's disk, then run 2b: the same configuration at 50,000 IOPS | about 2 h 45 min each | the headline that compares with bench 5, and what the node does when the disk is not the limit |
| P2 | run 2 only | about 2 h 45 min | the comparable headline; the report says the disk bounds it |
| P3 | one run at 50,000 IOPS | about 2 h 45 min | the node's own ceiling; the disk differs from bench 5's |
| P4 | a second, shorter arm walk first (the pool group split, the bound without the pipeline, the grace under load), then the headline | about 4 h 30 min more, plus four harness fixes for the walk | more switches settled before anything is published |

Why P1: bench 6 set out to recover the execution ceiling, and on bench 5's disk the ceiling is the disk.
Run 2b costs one more deployment and one knob, with no new harness path.
P4 is better decided after run 2 and the three investigations now running (§3): they may settle the pool question without a fleet.

**D2. The configuration (`final.arm`), for every run of the plan.**

| option | switches on | what the headline then means |
|---|---|---|
| F (recommended) | the vote fix, `vote_queue_fix`, `epoch_record_state_check`, `mdbx_random_advice` | the same kind of blast as bench 5 with the confirmed fixes; gap resends and unlanded transactions stay, as in bench 5 |
| F + pool group | F and the four pool switches | no resends; a rate lower by about the 1.2 if the account-density shift recurs; "0 duplicate digests" likely fails as the generator counts it |
| F + pool + pipeline + bound | as run 1's `bound` arm | an admitted rate: refusals and drops must be published beside it, and seen p50 no longer means what bench 5's did |

Why F: it is everything run 1 confirmed without an open side effect.
The advice is in it because it is the only switch that may act on the observer's whole-block writes, and run 2's nodes start fresh as run 1's observer did.

**D3. The vote fix's form.**
Always-on (recommended): 99.9 % and no refused vote at full load, one rule instead of two; its headers always name a block eight outputs back.
Adaptive: 98.5 % and 126 refusals at full load, a fresher block in each header; better in the first two minutes of a blast (96.3 % against 84.6 %), where the always-on arm started from a colder cache.
Run 1 cannot rank them at equal conditions.
The acceptance line is 98 % on every validator, and always-on has the margin.

**D4. Parent grace 150 ms in the headline.**
Off (recommended for the headline): the far validators stay at 2 % of committed certificates, as in bench 5; the floor latency keeps its 1.5 s.
On: the far validators and their users are served; every round is 28 % longer, the floor seen p50 lands at the acceptance line's edge (1.68 to 1.77 s by method), and its behaviour under a 40-minute load would be measured for the first time in the headline itself.
My reason for off is the unexplained loss of one validator's leader rounds, not the cost in round time, which is yours to weigh.

## 3. State

- Run 1: archive verified twice (2,875 files, 8.5 GB), reindexed, arm summary written; the fleet is gone (12 instances deleted, nothing left, devnet untouched). Fleet time 530 minutes.
- Harness, committed after run 1: a fund that stays short now fails (`aa3d661`), the walk's health check reads the real console line (`03342ce`), the stage tool reads the new node's fields (`ab5df82`), 498 mutation cases (`4175a1e`). The full gate is running alone on the host.
- Node image: unchanged (`adiri@sha256:874537ff…`, 2df831e3c). Run 2 needs no new build.
- Three investigations are running offline: which pool switch causes the account-density shift and the non-executed transactions (I-7), what sets the transactions per output (I-8), why the observer alone wrote whole blocks (I-9).
  They do not block run 2 under option F.

## 4. After your go

1. `gcloud auth login` from you, right before the launch.
2. I fill `final.arm` and the run-2 env file (same image, a new run id), commit, wait for the gate, and dry-run the deploy.
3. Per the launch README: `deploy12` → the idle window → `blast15` → `teardown-dry` → `teardown` → `reindex` → `archive`; then run 2b the same way if P1; then the analysis units and gate G4 before anything is published.

Two things I will do unless you say otherwise:
- Loosen run 2's start criterion from `late_secs < 5` to at most 10: in run 1 five of twelve full-size blasts had a generator starting 5 to 6 s late, and the value is in whole seconds.
- Report three acceptance lines as expected failures on this disk whatever the configuration: commit time per transaction at or under 45 µs, execution lag at or under 8 outputs at saturation, and 98 % certification in a blast's first two minutes.

## 5. Owed, not blocking

- Four walk-only harness fixes (an ssh retry, a second eviction try, the switch-line fallback, the epoch-aligned start's slack): needed only before another arm walk (P4).
- Validator-02 lags at every loaded epoch close, and one close reached its record quorum with exactly seven signers; run 2 kills validator-05 during the blast, so I will watch the first close after the kill.
- The upstream port and the issues wait for run 2, as planned.
