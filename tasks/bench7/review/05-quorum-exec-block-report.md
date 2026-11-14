# Topic review 05: quorum-exec-block (#1804), unit R-05

Worktree `/home/drtnarg/coding/telcoin/tn-b7-pt3a` (branch `b7/pt3a`), range `90a47028f..2b6a01022`, eight commits.
Paths below are relative to the worktree; line numbers are at the tip 2b6a01022.

## Verdict: APPROVE WITH FOLLOW-UPS

Nothing is Critical, High or Medium.
Nothing has to change before the benchmark image.
Three Low findings were confirmed by independent verification, and there are eleven Info items.
The Low findings are about how well the rule works and how its cost is described, not about safety.

- Switch off: the header bytes come from the same call (`consensus_bus.app().latest_execution_block_num_hash()`) a few microseconds earlier on the same code path.
  What else runs with the switch off is pure reads, early returns, four log fields and a conditional startup warning (2a).
- Mixed fleet: one chain.
  The switch is read only in `Proposer::new`, the voter's check is unchanged and accepts any canonical block, and every choice is the proposer's own ring entry at or above the epoch's opening block (2b).
- The central safety question: naming an older block delays the detection of an honest node's divergence by up to 8 outputs that produced a block (V2: with no bound in time when traffic is light).
  A Byzantine author gains nothing, because main's voter already accepts any canonical block above its restore floor.
- The opening-block clamp (commit 06d1d1a76) holds in every case examined: a restored node, epoch 0, a wrapped ring, a closing output without a block.
  It is implicit and rests on three invariants that nothing in this change enforces (I1).

## How the review ran

- Code review: the `tn-review` skill, with my own reading of the diff and of the readers of a header's named block (voter, subscriber, state-sync).
- Security evaluation: the `tn-security-eval` skill with seven opus agents, each limited to a named list of files and line ranges: consensus safety, state transitions, determinism, denial of service, the nemesis logic audit (as a general-purpose agent, since no dedicated agent type exists), DREAD and STRIDE.
- Skipped, because their questions cannot apply to this diff:
  - contract safety: no Solidity changed;
  - dependency audit: no `Cargo.toml` or `Cargo.lock` changed;
  - cryptography: no signature, hash or key code changed (the named block enters the header digest through the unchanged `Header::new`).
- Verification: one `findings-verifier` run over the combined findings, opus, read-only.
  The three Low findings went to one batched verifier that saw only each claim and key question.
  All three were confirmed; two had their scope narrowed (V1's cost, V2's memory part).
  The Info items were not verified by that run, per the skills' tiering; I checked each one against the code myself.
- No cargo of any kind, no edits.
  The unit's own gates (fmt, check, clippy, nextest: 691 passed) are recorded in `tasks/checkpoint-bench7-PT-3a.md`; I did not re-run them.

## Findings (most severe first)

### V1. The adaptive window is counted in rounds, so a round jump can spend a window without one header built under the rule (Low, CONFIRMED)

- Where: `ExecBlockPolicy::on_cancelled` (`crates/consensus/primary/src/proposer.rs:1739-1761`, called at `:992` with `self.round`) opens the window `(round, round + next_window]` and doubles `next_window` at once (`:1756-1760`).
  `for_round` returns `Tip` once `in_window` is false (`:1714-1729`).
  The proposer's round can jump: `process_parents` sets `self.round = round` (`:810-820`) and `propose_next_header` raises it to `primary_round() + 1` (`:1117-1121`).
- Sequence (K = 4):
  1. A counted cancel arrives at proposer round p: the window is (p, p+4] and `next_window` becomes 8.
  2. Parents of round p+6 arrive, so the next own header is at p+7 and names the tip.
  3. If that header is cancelled too, the cancel opens (p+7, p+15] and doubles `next_window` to 16.
- Cost: the headers lost in such an episode name the own tip, so the switch-off form would lose them as well.
  What is lost is the window's gain, plus a larger next window (more headers at the older block) until 64 certified tip headers in a row reset it.
  It is bounded: at most log2(128/K) wasted doublings.
  It hits the nodes that jump rounds, which are the lagging ones the policy is meant to help.
- Not covered by a test: the policy tests and the model (`proposer_tests.rs` 2340-2420, 2726-2745) use consecutive rounds.
- Fix: open the window, and apply the doubling, at the first header proposed after the cancel instead of at the round the cancel arrived in (record a pending window in `on_cancelled`, start it in `for_round`).
  Add a policy test with a round jump.
- Gate: before the upstream PR.
  For the benchmark, read the adaptive arm's far validators with this in mind; no image change.

### V2. The 8-entry floor counts outputs that produced a block, so F7's "8 outputs" has no bound in rounds or time (Low, CONFIRMED; sharpens F7)

- Where: the floor is `nth_newest(QUORUM_EXEC_BLOCK_FLOOR_ENTRIES)` (`proposer.rs:1939-1943`); `push_latest` adds a ring entry only when an output produced a block (`crates/consensus/primary/src/recent_blocks.rs:49-60`), and an empty output produces none (`crates/state-sync/src/lib.rs:618-621`).
  Under the always form an in-step fleet settles on the floor entry (`proposer.rs:1531-1533`; `test_quorum_exec_block_self_feeding_fleet`).
- Sequence:
  1. An honest node's execution diverges at block N.
  2. Traffic goes quiet, outputs are empty, and no ring entry is added.
  3. The node keeps naming a block 8 entries back, below N.
     No voter (`crates/consensus/primary/src/network/handler.rs:1470-1513`), subscriber (`crates/consensus/executor/src/subscriber.rs:1223-1230`) or state-sync check (`crates/state-sync/src/lib.rs:616-624`) sees the fork until 8 more outputs produce blocks.
  4. With the switch off, the node's next header names its forked tip and voters answer `Fork` at once.
- What the verifier refuted: nothing grows with the empty outputs in between.
  The subscriber's wait floor is a running maximum of block numbers (`subscriber.rs:1384-1386`), empty outputs pass it at once, and the rule lowers it by about 8 block-producing outputs, inside the documented run-ahead bound of about 500 outputs (`subscriber.rs:1379-1383`).
  That is about 8-10 MB more assembled early at the average output size and 44 MB at the 5.5 MB maximum.
- Fix: state F7 and the `quorum_exec_block` doc (`crates/config/src/node.rs:329-341`) in outputs that produced a block, with no time bound.
  Optionally bound it in time: keep the round with each ring entry and name the tip once the floor entry is older than X rounds.
- Gate: before the upstream PR (PR text, optionally code).
  The benchmark runs continuous load, so the floor is a few seconds behind; it does not hurt a run.

### V3. f Byzantine parents naming high blocks, plus withheld votes, can cancel headers built under the rule; the loss is bounded by the switch-off form's (Low, CONFIRMED; D70 is inexact)

- Where: the weighted walk in `choose_exec_block` (`proposer.rs:1916-1937`) treats each counted parent's named number as evidence that its author holds the block.
- Sequence (n = 4, f = 1, equal stake, threshold 3):
  1. Own tip 100; parents name B (Byzantine) 100, H1 97, H2 90.
     The walk sorts 100, 100, 97, 90 and reaches 3 at 97.
     Without B's value it would reach 3 at 90.
  2. B withholds its vote; H2 is still below 97 after the 1 s `VOTE_EXECUTION_WAIT` and answers `ExecutionBehind`.
  3. The header gets 2 of 3 votes and is cancelled.
     Naming 90 it would have certified; with the switch off (naming 100) it would also have been cancelled.
- Bound: the pick is never above the own tip (`:1934`), and a voter that holds the tip holds the pick, so headers under the rule are lost no more often than switch-off headers.
  The one exception is a restored voter whose floor is above the pick (`handler.rs:1487-1501`); the opening-block bound excludes that while I1's invariants hold.
- Why it is reported: D70 says a vote-withholding minority costs "staleness only".
  With high parent values it can also cancel headers inside the window, and under the always form; the switch's gain is lost, not liveness below the switch-off baseline.
- Fix: amend the D70 and F2 wording in the PR text, and add a table or model case with a high Byzantine parent plus a withheld vote.
  A stronger fix (a lower order statistic) costs more staleness and needs a design decision.
- Gate: before the upstream PR (text and tests).
  The benchmark has no Byzantine member.

### Info items (checked against the code by me; not run through the verifier)

- I1 (code review CR-3; nemesis-2; consensus-safety-3; stride-2). "Never below the opening block" is implicit (`proposer.rs:1915-1949`, "no separate clamp is needed").
  It rests on three invariants nothing in this change enforces:
  - (i) the ring's block numbers rise in push order (`recent_blocks.rs:41-61` does not check);
  - (ii) a proposer of epoch E starts only after its execution reached E−1's closing block (main has the same dependency for the tip);
  - (iii) state exports are taken only at epoch-closing blocks (`crates/node/src/manager/export_exec.rs:225-241`, test at `:360`).
  The doc at `proposer.rs:1897-1899` names (iii).
  Suggest a `debug_assert!(lowest_usable <= choice.block.number && choice.block.number <= tip.number)` or an explicit final clamp, and a cross-reference from the export trigger to this bound.
  Before the upstream PR, optional.
- I2 (CR-2, the bench-6 I5 follow-up). `Parameters::validate` (`crates/config/src/node.rs:480-493`) does not refuse K above 128 or K > 0 with the switch off; `Proposer::new` warns (`proposer.rs:305-318`) and `ExecBlockPolicy::new` lowers K to 128 (`:1676-1686`).
  See question 8 below.
- I3 (stride-3). Turning on `quorum_exec_block` with K at its default 0 selects the always form without a startup warning; the only sign is `exec_policy=always` on each `header proposed` line.
  This is the documented default ("as first designed"); once bench 7 decides the form, the PR should say which K is recommended.
- I4 (CR-1). `test_quorum_exec_block_switch_off_keeps_header_bytes` (`proposer_tests.rs:2511-2571`) rebuilds the expected header with `Header::new` from the same tip call.
  That proves the header names exactly the tip call's value, but it is not a byte fixture against main.
  Because `Header::new` and its other arguments are untouched by this diff, that is enough.
- I5 (consensus-safety-2). An honest author's named block can now go down between its consecutive headers (a window opening, or the switch turned on across a restart).
  No reader relies on it rising: the voter checks a match, the subscriber keeps its own running maximum (`subscriber.rs:1384-1386`), state-sync checks each output alone.
- I6 (stride-1). A header naming a block up to 8 entries behind its author's tip is now normal honest behaviour, so staleness cannot be attributed to a Byzantine author.
  Nothing checks staleness today.
- I7 (state-transitions-2). The cancel report reaches the policy before its round and digest are checked (`proposer.rs:992-995`).
  A stale report from another epoch cannot arrive: each epoch builds a new `ConsensusBus` with a fresh epoch inner (`crates/node/src/manager/node/run_epoch.rs:148`, `crates/consensus/primary/src/consensus_bus.rs:2070-2072`), and the channel lives there (`:2133`).
- I8 (state-transitions-3). After a restart, the certificate of a header built under the rule before the restart counts toward the streak of certified tip headers.
  It has no effect: the streak only resets `next_window` to the base, which it already is after a restart.
- I9 (determinism-1). If an author appeared twice among the parents, its first usable certificate would count, by slice order (`proposer.rs:1916-1926`).
  Two certificates of one author in one round need 2f+1 votes on conflicting headers, so this cannot happen with at most f faulty nodes; voters never recompute the choice anyway.
- I10 (state-transitions, 2a). With the switch off, the tip read moved from the sixth argument of `Header::new` (after the digests and parents were collected) to `proposer.rs:430`, just before the call.
  Same source (`consensus_bus.rs:1354-1356`), same task, no await in between; the ring may advance in those microseconds exactly as it may between any two reads on main.
- I11 (dos, 2d). Per proposal the rule costs O(committee + ring) under the recent-blocks watch read guard (`proposer.rs:1853-1858`), which is dropped before any await; it holds up the engine's `send_modify` for microseconds at most.

## Answers to 2a-2g

### 2a. Switch off = before

Yes for every behaviour.
The header names `consensus_bus.app().latest_execution_block_num_hash()` (`proposer.rs:1853-1858`), the call main passed into `Header::new`, read at `:430` just before `Header::new` (I10).
Lines that run with the switch off and did not run before:
- `Proposer::new`: two config reads, and a `warn!` only when K > 0 (`proposer.rs:305-318`); `ExecBlockPolicy::new` (`:347-350`).
- `propose_next_header`: a read-only scan of the parents for an own certificate and an `on_certified` that returns at once (`:1189-1194`); `ExecBlockInputs::new` with pure committee reads and an empty vector (`:1195-1200`).
- `process_uncertified_header`: `on_cancelled` returns at once (`:992`).
- Log fields: `exec_block`, `exec_tip`, `exec_basis`, `exec_policy` on `header proposed` (`:478-481`), and two more fields on the `node switches` line through `runtime_switches!` (`crates/config/src/node.rs:656-661`).
- The serialized `parameters.yaml` is unchanged at the defaults (`skip_serializing_if = "Parameters::switch_at_default"`, `node.rs:340`, `:353`).

The three new ring helpers (`recent_blocks.rs:87-117`) are never called with the switch off.

### 2b. Mixed fleet

One chain; no honest validator rejects another's header, vote, certificate or batch because of the switch.
- The only message the switch changes is a header's `latest_execution_block` (and so its digest).
  Votes, certificates and batches are unchanged.
- The switch is read only in `Proposer::new` (`proposer.rs:305-306`); the voter's check (`handler.rs:1463-1514`, `consensus_bus.rs:1728-1757`) never reads it and has no recency or monotonicity test: it waits for a match, refuses `Fork`, `BelowRestoreFloor`, or `ExecutionBehind` after 1 s.
- Every choice is the proposer's own executed ring entry, at or below its tip and at or above the epoch's opening block, so an off voter answers `Match` where it would for an off author's tip header, and sooner, since the block is older.
- The named block feeds neither ordering nor execution: its only readers are the voter, the subscriber, state-sync and a log field at `crates/consensus/primary/src/consensus/state.rs:786`.
- A restart with the switch flipped re-sends a header already stored for the round unchanged (`proposer.rs:1131-1174`), so no equivocation.

### 2c. Liveness under the switch

Nothing that used to make progress is dropped.
Digest requeueing in `process_uncertified_header` is unchanged; the policy hook only reads the report.
The always form names blocks voters are more likely to hold; the only refusal that never clears, `BelowRestoreFloor`, is excluded by the opening-block bound while I1's invariants hold.
The adaptive form's windows always end by round number (`proposer.rs:1714-1719`); a cancel report dropped by the full 64-deep queue (`consensus_bus.rs:89-96`) just opens no window, which is the switch-off behaviour.
Costs that remain: V1 (wasted windows on nodes that jump rounds), V3 (Byzantine parents can cancel the gain), L2/D76 (the climb repeats each epoch).

### 2d. Byzantine or merely slow peers

- f Byzantine parents can move an honest proposer's choice within [max(opening block, floor entry), own tip] (F2): low values pin it to the floor in a minimal parent set; values below the opening block are not counted (`proposer.rs:1919-1921`); values above the tip are capped (`:1934`); high values with withheld votes cancel rule headers at no more than the switch-off rate (V3).
- A Byzantine author gains nothing: main's voter already accepts any canonical block above its restore floor.
- Withholding plus one slow honest voter keeps the adaptive window at 128 rounds (D70), and every cancel report restarts the 64-header streak.
  Remote peers cannot create cancel reports: the local certifier sends at most one per own header.
- Bounded cost: staleness of at most 8 block-producing outputs (V2), header loss at most the switch-off form's, CPU of O(committee + ring) per proposal (I11), and up to about 44 MB more of outputs assembled early by the subscriber (V2).

### 2e. Restart and epoch boundary

`ExecBlockPolicy` lives in memory in the `Proposer`, which is rebuilt at every epoch and every restart, so the window, the next window and the streak start over (L2/D76; I8 for the streak after a restart).
The cancel channel is per epoch (I7).
The recent-blocks ring is node-scoped and re-primed at start from the database with real nonces (`crates/node/src/manager/node.rs:1868-1892`), so `newest_before_epoch` works after a restart.
On a snapshot-restored node the ring holds imported headers in [B−255, B]; the newest one before the current epoch is B, so every choice is at or above B.

### 2f. Determinism

The choice is a pure function of the ring snapshot and the inputs fixed at spawn time: a `BTreeSet`, a vector, and a sort whose tie order cannot change the returned number (the walk returns the largest value whose holders reach the threshold).
No hash map, clock, randomness or floating point.
Peer numbers are only compared; power sums saturate; ring index arithmetic uses `checked_sub` and `saturating_sub`.
What depends on timing is when the ring is read and when cancel reports arrive, both local, as main's tip read is.
Voters never recompute the choice.

### 2g. The scope's eight questions

1. Safety.
   Fork detection through the named block (voter, subscriber, state-sync base-block check) is delayed by up to 8 block-producing outputs under the always form, and only inside windows under the adaptive form; V2 adds that the delay has no bound in time.
   A Byzantine author cannot hide a divergent execution longer than on main, because main already lets it name any old canonical block.
   State-sync runs the same check on an older block and throttles less; its `sync_output` queue remains the bound (`crates/state-sync/src/lib.rs:616-621`).
   Nothing else assumes the named block is recent (2b's list of readers).
2. Determinism and equivocation.
   The choice uses only what the proposer has seen (2f).
   Two honest nodes on different forms cannot disagree about a header's validity: validity is the voter's match against its own chain, and the voter never reads the switch (2b).
3. Byzantine parents.
   Pinning an honest proposer to the floor: yes, in a minimal parent set (F2, known), for staleness only.
   A block before the epoch's opening block: no.
   While the ring holds the opening block O, parents below O are not counted, so the quorum value is at least O and any floor entry below O is never taken (`proposer.rs:1915-1949`); once the ring holds only the epoch's blocks, every entry is above O.
   `test_quorum_exec_block_never_names_a_block_before_the_epoch_opened` (`proposer_tests.rs:2901-2971`) sweeps every low value.
   A window that never closes: a window always ends; only a stream of counted cancels keeps reopening it (D70; V3 adds header loss up to the switch-off rate).
4. The opening-block clamp is the epoch's opening block in every case examined:
   - restored node: B is the newest pre-epoch ring entry;
   - epoch 0: `newest_before_epoch(0)` is `None`, and no restored voter exists before the first epoch closes;
   - a ring with no previous-epoch entry: every entry, the floor included, is above the opening block;
   - a closing output without a block: the newest pre-epoch block is still the canonical tip at epoch entry, the same block the restore floor is taken at.
   It rests on I1's three invariants; none is enforced here.
5. Liveness at an epoch boundary and after a restart.
   A proposer never names a block no voter will accept: the block is one of its own ring entries at or above the opening block, so an honest voter either holds it or is behind and catches up.
   It never names a block its own engine has not produced, with one exception: a restored proposer's ring holds imported headers in [B−255, B]; they are canonical and at or above B whenever they are named.
   The climb of the window repeats each epoch (L2/D76), not worse than recorded.
6. Mixed fleet: one chain; an off node rejects no header from an always or adaptive author that it would accept from an off author (2b).
7. Switch off = main: the header contents are identical.
   The ported test checks it as a self-consistency check, not a byte fixture (I4).
   Additions with the switch off: the four `header proposed` fields, the startup warning (only with K > 0), two fields on `node switches`, and the pure reads listed in 2a.
8. Warn and cap instead of refusing.
   A silent no-op is not possible at the default log level: K > 0 with the switch off logs a warning at every epoch start (`proposer.rs:305-318`, text at `:1695-1706`), and K above 128 is lowered with a warning.
   For the benchmark this is the right choice, because a refusal would keep a node down in the middle of a rolling restart.
   For the upstream PR, refuse K above 128 in `Parameters::validate`, where the other ceilings are refused (`node.rs:480-493`); keep K > 0 with the switch off allowed with its warning, since setting the window before turning the switch on is a valid rollout step.

## Known residuals checked and not worse than stated

- F2: holds, with V3 as the one refinement.
- F7: holds in outputs that produced a block; V2 adds the time dimension.
  The memory part is within the run-ahead bound.
- D70: refined by V3.
- L2/D76: unchanged.
- D75 (bench 6's L1): fixed by 06d1d1a76 as far as I1's invariants hold.
- Bench 6 I1 (one low parent in a minimal set sets the value): unchanged and bounded by the floor and now by the opening block.
- Bench 6 I5 (unvalidated K): now warned and capped (I2).

## Not examined

- No build, test or clippy run; I relied on the unit's recorded gates.
- The test file: only the tests the questions needed (`test_quorum_exec_block_choice_table`, `_self_feeding_fleet`, `_switch_off_keeps_header_bytes`, `_never_names_a_block_before_the_epoch_opened`, by range).
  The voter-side tests and the e2e tests of the topic come in later units.
- Bench 6's original golden test was not diffed against the ported one.
- Fleet dynamics are not modelled; the sizes in V1 and V3 come from the code, not from runs.
- Other topics' code, including the voter-lock change, and the snapshot import path beyond the export trigger and the restore floor.
