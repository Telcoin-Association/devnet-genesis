# Figure-check of the PR texts bench6-04 and bench6-xf, and of their commit bodies (not posted)

Checked against: the commits in `/home/drtnarg/coding/telcoin/telcoin-network` (read-only: `git show`, `git log`, `git diff`, a scratch-index `git apply --check`), upstream main 45dce8947, the gate logs under `tn-b7-stack`, `tn-b7-gate` and `tn-b7-p2` `target/tmp/`, the ledger, the contract, the unit notes (E5b, ECF, E2E-R, XF-1, XF-1b), the topic reviews 04 and 07, the orchestrator's log (facts only), and issues #1850, #1852, #1860, #1575, #1618 on GitHub (read-only, none has a comment).
The code is an allowed source for these texts (deviation from item 5 of the method, per the launch prompt).
No cargo command was run.

Stack as checked: 04 = 1e38f1882..065ee9e5a (28 commits), xf = 065ee9e5a..be483a955 (9 commits); full shas 1e38f1882fdb7d96c85db6294b4080ad9d14302e, 065ee9e5a920f0e6b6d54a23cf4c1fa6cbbb78d4, be483a955ea6a3a141066c5572766083d5c32ab7.
`git diff --stat 91a15e223 b93a8e682 -- . ':!crates/e2e-tests/tests/it'` is empty: verified.

## bench6-04-collector-hardening.md

Verdict: FIX

### Errors

1. Problem, line 15: "Inferred from code, not observed: all 37 closes of [r20261113-1351](…), [r20261113-1630](…) and r20261112-1520 (no public page) certified with at least 7 of 10 validators."
   The 37 closes are measured, not inferred; what is inferred is the uncertified epoch of the paragraph above (issue #1850 "What happens": "two paths the runs never reached, read from code … not observed"; 403 of 407 node-epoch cells = 37 closes × 11 nodes; closest call exactly 7 votes).
   As written, the label attaches to the measured figure.
   Replace with: "No run reached this state, so it is inferred from code, not observed: all 37 closes of [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) and r20261112-1520 (no public page) certified with at least 7 of 10 validators."
2. With every switch off, line 51: "re-certifying needs a super-quorum of switch-on members."
   Stronger than the code: a round keeps every counted member's verified vote (`065ee9e5a:crates/node/src/manager/epoch_votes.rs` round loop, `retained.keep(…)` for any committee member's vote, and the seeding at the round's start), so a switch-on node can certify an old record from votes switch-off members cast in its original round and failsafe plus the switch-on members' re-votes.
   What is true (review 2b, and the code): a switch-off member adds no new vote of its own for an older record.
   Replace with: "Nodes differ only in which records they hold certified and who halts; a switch-off member adds no new vote for an older record, so a re-certify round needs a switch-on node to hold a super-quorum from the votes it kept from earlier rounds (any member's) and the switch-on members' re-votes."
3. Testing, line 57: "On e5121e7e1 (this head but for doc comments, README text and e2e files): …"
   The gate is real (`tn-b7-stack/target/tmp/head04node-e5121e7e1.log`: CHECK EXIT=0, "1340 tests run: 1340 passed, 7 skipped", TEST EXIT=0, both commands with `-p tn-node -p state-sync -p tn-config -p tn-types -p tn-primary`), and the description of the difference is exact (`git diff e5121e7e1 065ee9e5a`: `crates/config/src/node.rs` and `crates/e2e-tests/src/lib.rs` comment lines only, the CLI README, the three e2e test files).
   But e5121e7e1 is not in this PR (not an ancestor of 065ee9e5a) and is reachable only from the local branch `b7/stack`: a reader cannot open it.
   Replace with (unless that branch is pushed): "On an earlier, unpublished cut of this head (the same code but for doc comments, README text and the e2e files): `cargo check --locked --all-targets` exit 0 and `cargo nextest run --locked --no-fail-fast` 1,340 passed, 7 skipped, both with `-p tn-node -p state-sync -p tn-config -p tn-types -p tn-primary`."
4. Testing, line 60: "A later head's test (`fix/1804-quorum-exec-block`) certified a missed record from kept votes 7.7-8.5 s after its members returned."
   The figure is the ECF unit's run 1 on its own branch (4f6eb9f5e) before the stack was assembled (ECF note, "C finding"); the text does not say it ran on an earlier cut.
   The same tests (`epoch_close_forms::test_missed_record_round_{adaptive,always}`) passed again on the assembled top (`tn-b7-p2/target/tmp/e2er-lane-06.log`, 04bc4f239, tree = b93a8e682's).
   Replace with: "A later head's test (`fix/1804-quorum-exec-block`), in a run on that change's own branch before this stack was assembled, certified a missed record from kept votes 7.7-8.5 s after its members returned; it passes on the assembled top of the stack too."
5. Related, line 75: "Refs #1850: every point of its fix sketch, behind default-off switches; …"
   The sketch's fourth point (the gauge and the serving peer on the `retrieved cert` lines) is "Always on" in the issue and has no switch here (this text's own Summary line 4).
   Replace with: "- Refs #1850: every point of its fix sketch, the first three behind default-off switches and the gauge and the serving peer always on, as the sketch asks; not `Fixes`: by default nodes still stop at an uncertified epoch, a node without the record needs re-certification, and its benchmark check has not run."

### Matched (what was re-derived)

- Stack paragraph: compare 1e38f1882fdb…...065ee9e5a920… = (previous head, head), 28 commits, "PR 5 of 5", merge order, branch name.
- All 28 short ids of 1e38f1882..065ee9e5a appear in Change, none from outside the range; groups checked against each commit's `--stat` and diff (observability 3, re-certify 7, walk 10, halt 4, eviction 1, hook 2, e2e 1).
- Main at 45dce8947: `crates/state-sync/src/epoch.rs:343-345` (`if result_epoch != epoch { break; }`), `:279` (`save` → `stop_on_local_failure`, which only logs `ConflictingRecord`, `crates/storage/src/epoch_records.rs:2707-2727`), `crates/consensus/primary/src/network/handler.rs:1909-1919` (`get_epoch_by_number` → `UnavailableEpoch` without a certificate), `crates/node/src/manager/epoch_votes.rs:483-502` (failsafe for N-1), `:279-289` (validate, "we have forked!", `node_shutdown.notify()` at :289), `:231-237` (the error with no store check).
- 11 false quorum errors in r20261112-1520, r20261113-1351, r20261113-1630, each with the certificate already stored: issue #1852 Evidence.
- Code at 065ee9e5a: three switches default `false` (`crates/config/src/node.rs:533-535`); held-certificate branch (`cert_by_digest`, info line verbatim, `tn_node.epoch_record_round_ended_certified_total`, gauge from `cert.signed_authorities` for current rounds, alarm gated on `!already_certified`, recovery after both branches); `MAX_RECERTIFY_LOOKBACK = 16`, pick `epoch % count` over `N-16 ..= N-2`, signing only as a committee member, startup re-arm behind a certified latest record; `RoundKind` (`Recertify` for `epoch <= latest - 2`, always `Current` with the switch off); `older_record_conflict_stops` (`halt && signers >= anchor*2/3+1`, the re-certify line verbatim); `MAX_RETAINED_RECORDS = 17`; `MAX_UNCERTIFIED_GAPS = 16`; `GAP_RETRY_DEADLINE` = 5 s; `may_walk_past` (switch, unlanded-walk interval, gap cap, own uncertified record, not the epoch-0 dummy; called only on a definitive "not held"); `retry_gaps` once per interval after a pass a peer answered; the halt line verbatim, its 13 fields in the text's order, `epoch_record_conflicts_total` always, `…_below_halt_threshold_total` below `committee*2/3+1`; the non-halting line verbatim ("… this node keeps its own record"); the pre-flight in the halt switch's doc; the hook's `#[cfg(feature = "test-utils")]` / `not(…)` arms, default 1 round.
- Eviction vs main: main pops the front at `len() >= 5` (live or ended); head retains open senders, then at `len() >= 5` removes the lowest epoch; a vote for an epoch whose entry ended starts a new round on both sides, so the two differ only when a round is queued while five are: the text's "Behaviour" line is exact.
- With every switch off: four state-sync counters (gap walks, parent mismatches, conflicts, below-threshold), the gauge, two `tn_node` counters (`…_round_ended_certified_total`, `…_round_conflicts_total`, both touched with every switch off), `round="current"` on missed signers; one committee read per conflict (`ConflictEvidence::read`); `tn_node.epoch_record_recertify_rounds_total` and the retained-votes gauge only with the switch on.
- Unit test names: all eight exist at 065ee9e5a and PASS in the e5121e7e1 log; e2e names exist in `crates/e2e-tests/tests/it/epoch_record_walk.rs`.
- "On this head: e2e crate check, fmt, clippy clean; `epoch_record_walk.rs` 3 of 3": ran on c32a58efc, whose tree is 065ee9e5a's (f6721a7f7…): `e2er-{check,fmt,clippy}-04.log` EXIT=0, `e2er-lane-04.log` "3 tests run: 3 passed" (224.9, 228.0, 261.6 s); honest.
- What the three e2e tests assert (K = 1, validators 1 and 2 withhold with ROUNDS = 2, the close of K + 2 = epoch 3 re-votes and certifies epoch 1, both observers then collect every record): the test file's docs and the lane log's summary lines; the orchestrator's E5b record agrees.
- Release build lacks `test-utils`: `etc/Dockerfile:51` builds `-p telcoin-network`; only `crates/e2e-tests` enables `tn-types/test-utils` in normal dependencies (but see Weak 2).
- Names: every log line, metric, label, field and switch matches the contract (§2.4, §3.4, §4, §5) and the code.
- #1852 "Fixes": the sketch's check, info line, count, unchanged error and recovery, and the open gauge question are all in 1f04e4025; its unit test exists.
- Placeholder sentence `Stack-wide gates: …` ends Testing (not an error).

### Not traceable

- Testing, line 61, "the next benchmark runs all three switches on eleven nodes": all switches on is in the orchestrator's image trial; the fleet size of the next run is in none of the allowed sources (bench 6's was ten validators and one observer).
- Limits, line 70, "for under a millisecond": a bound by code reading (no await between the `epoch record re-certify round` line and `mark_recertify`; the orchestrator's note says "sub-millisecond"), not a measurement; acceptable if read as such.

### Weak

1. Change, line 28: "… else logs `own epoch record differs from a certified record in a re-certify round`, counting `tn_node.epoch_record_round_conflicts_total{round}` (`76d5ea885`)" reads as if only that branch counts; the code counts every vote round's conflict, current rounds included and with every switch off (contract §3.4: "a round's recovery fetched a different certified record").
   Suggested: "… else logs `own epoch record differs from a certified record in a re-certify round`; every vote round's conflict, of any record and with any switch, counts in `tn_node.epoch_record_round_conflicts_total{round}` (`76d5ea885`); the newest two records keep main's stop."
2. Change, line 42: "off without `tn-types`' `test-utils`, which release builds lack": the hook's doc says "a node-scoped release build lacks the hook and a workspace-root build without `-p` has it".
   Suggested: "off without `tn-types`' `test-utils`, which the release image's `-p telcoin-network` build lacks (a workspace-root build without `-p` has it, as with the existing fork-epoch hooks)".
3. Testing, line 59: "closes no epoch": the test asserts "it closes no epoch after it came back" (it closed epochs 0 and 1 before).
   Suggested: "… collects nothing past it and closes no epoch after it comes back …".
4. Change grouping: `7673797b0` and `e28c5ee1b` also document the halt (threshold, pre-flight, counters) but sit under Walk only; `5c9803f16` is named twice (bullet and the "first in" cross-reference).
   Suggested: "docs `7673797b0`, `e28c5ee1b` (both also the halt's threshold and counters)."

### Rule breaches

- Two sentences on one line: line 67 ("… reaches it. Not examined: …") and line 69 ("… hence the pre-flight. Open: …"); split each at the full stop.
- 1,300 words by `wc -w` (limit 1,100): known open point, not an error.
- No unit names, private paths, host or person names, tool attribution; every run id at first mention is linked or marked "no public page".

### Counts

Figures and claims checked: 96; matched: 87; wrong: 5 (errors 1-5); weak: 4; untraceable: 2 (one of them acceptable as a code bound).

## bench6-xf-epoch-loop-output-drop.md

Verdict: FIX

### Errors

1. Stack paragraph, line 9: "It needs nothing from the stack below: everything it calls is on main at 45dce8947, and its diff applies there with fuzz (checked, not built)."
   The ninth commit, be483a955, edits `crates/e2e-tests/tests/it/fleet.rs`, which main does not have (065ee9e5a of `fix/epoch-record-collector-hardening` creates it): `git apply --check` of `065ee9e5a..be483a955` on main's tree fails with "fleet.rs: does not exist in index".
   The first eight commits' diff (`065ee9e5a..8e60bdc9a`) applies on main only with zero context (`git apply -C0`; the sources note's `patch -F3` is the same result), and every symbol and dependency it uses is on main (`check_output_continuity`, `OutputContinuity`, the test fixtures, `futures`, `metrics`, `metrics-util`; the stack below changes only comments in `crates/node/Cargo.toml`).
   Replace with: "Its node change needs nothing from the stack below: everything its first eight commits call is on main at 45dce8947, and their diff applies there with fuzz (checked, not built); the ninth adds the stop to `crates/e2e-tests/tests/it/fleet.rs`, which `fix/epoch-record-collector-hardening` creates."
2. Testing, line 65: "On this head's first eight commits (the ninth changes one e2e test list): `cargo check …` exit 0; `cargo nextest …` 276 passed, 1 skipped, these 11 among them; `cargo +nightly-2026-03-20 clippy …` exit 0."
   The figures are right (`tn-b7-gate/target/tmp/headXF-a2c4dfae9.log`: CHECK EXIT=0, "276 tests run: 276 passed, 1 skipped", TEST EXIT=0, CLIPPY EXIT=0, all eleven tests PASS), but they ran on a2c4dfae9, an earlier cut: its tree is 8e60bdc9a's minus the three e2e files of `fix/epoch-record-collector-hardening` (`git diff --stat 8e60bdc9a a2c4dfae9`: 3 files, 1,355 deletions), which these `-p tn-node` gates do not build.
   a2c4dfae9 is public (an ancestor of the pushed `bench/bench7-2026-11`).
   Replace with: "- On a2c4dfae9 (an earlier cut of the first eight commits, on `bench/bench7-2026-11`: the same node code, without the stack's e2e test files, which these gates do not build): `cargo check --locked --all-targets -p tn-node` exit 0; `cargo nextest run --locked --no-fail-fast -p tn-node` 276 passed, 1 skipped, these 11 among them; `cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-node -- -D warnings` exit 0."

### Matched (what was re-derived)

- Stack paragraph: compare 065ee9e5a920…...be483a955ea6… = (previous head, head), 9 commits; Change lists the 9 in `git log --reverse` order, each subject verbatim.
- Main at 45dce8947: `crates/node/src/manager/node/run_epoch.rs:749` (`while let Some(mut output) = consensus_output.recv().await`), `:730` (`to_engine.send(output).await?`), `close_epoch.rs:320` (Phase 1 `try_recv`, no continuity check); `crates/engine/src/metrics.rs:81` unchanged at the head and still says "stamped just before its send".
- `[1, 3]` not `[1, 2, 3]` on main's code: issue #1860 Evidence; XF-1 A2 (EXIT=100 on base code equal to main's for these lines).
- Trigger in r20261113-1630, symptom not seen in bench 6's four runs: issue #1860 Evidence.
- Code at be483a955: `process_output` = `reserve().await` + `forward_output` (no await, `permit.send`); live loop reserve → one poll of `recv` (`now_or_never().flatten()`) or await → `to_engine.is_closed()` check → continuity → forward; `forwarded_at` = `waiting_since` or arrival; Phase 1 applies `check_output_continuity`: Stale → counter `tn_node.leftover_outputs_skipped_total` + warn with `number`, `last_forwarded`, `digest`, `path = "leftover_queue"`; Gap → counter `tn_node.leftover_output_gaps_total`, the error line verbatim (target `epoch-manager`, fields `number`, `last_forwarded`) and the returned error verbatim; the live skip warn gains `digest` and `path="live"`; the drain still stashes the boundary header before its send.
- Clean shutdown: the engine runs on `node_shutdown.subscribe()` (`node.rs`); `failed to reach epoch boundary` (`run_epoch.rs:494`, same line on main) and `error sending leftover consensus output to engine` (both drain phases, as on main).
- Restart: `replay_missed_consensus` is unchanged from main and replays from the last executed block; `finish_epoch` persists the pack (`persist_current`) before the drain.
- Counter priming from the store (`last_consensus_parent`) at startup; main's live forward already returns an error on a gap.
- `LineCapture` (420268325) is used by a later head: 947a34863 of `fix/1807-digest-order-hold`.
- Test names: all eleven exist at be483a955 and PASS in the gate log.
- Related: #1860 "What a fix could look like" items 1 and 2 are 7bb575c62 (+ c7474572f, f75e7e024) and 05c6f3d67, its "How to verify" test passes: `Fixes` is justified; #1575 (merged PR) lists this case under "Pre-existing and left alone"; #1618 (open) is the subscriber's teardown, untouched here.
- "no fleet has run this head yet": true (only a local trial of the image's binary ran, two e2e tests).
- Names against the contract §2.5, §3.5, the fatal list.
- Placeholder sentence `Stack-wide gates: …` ends Testing (not an error).

### Not traceable

None.

### Weak

1. Change, line 26 (`44e6c29f0`): "it passes on main too": the review says "passes on base too (`recv` was already cancel safe)", a reading; no unit note records a run of this test on main's or the base's code.
   Suggested: "the second cancel point; main's `recv` was already cancel safe there, so it would pass on main too and guards the held permit."
2. What changes for every node, line 38: "both `skipping already-forwarded consensus output` warnings gain `digest` and `path`": the drain's warning is new (main's queue phase had no skip; contract §2.5 "all new on this path").
   Suggested: "New counters `tn_node_leftover_output_gaps_total` and `tn_node_leftover_outputs_skipped_total`; the live `skipping already-forwarded consensus output` warning gains `digest` and `path` (`live`), and the drain's new one carries them (`leftover_queue`)."

### Rule breaches

- 1,152 words by `wc -w` (limit 1,100): known open point, not an error.
- One sentence per line throughout; no unit names, private paths, host or person names, tool attribution; the run id is linked at first mention.

### Counts

Figures and claims checked: 64; matched: 60; wrong: 2 (errors 1-2); weak: 2; untraceable: 0.

## Commit bodies

Read: `git log --format='%h %s%n%b'` of 1e38f1882..065ee9e5a (28) and 065ee9e5a..be483a955 (9).
No body says that a benchmark run left an epoch uncertified: f04b6bad9, 818de6da4, ea95ad288 and 5c9803f16 all say no run reached it, as issue #1850 does.

### Wrong or untraceable

1. 7bb575c62: "Bench 6 run r20261113-1630 had a validator change mode four times under load, the trigger this needs besides a full channel."
   Issue #1860 Evidence: the validator logged the mode-change line four times, three at 18:02 UTC under load and once at 18:42 UTC rejoining after the run killed and restarted it, and each time it was at most 21 outputs behind, so the engine channel was not full.
   Corrected: "In bench 6 run r20261113-1630 one validator changed mode four times, three of them under load, the trigger this needs besides a full channel; its engine channel was not full then."
2. 38d9ab151: "Log fields only: with every switch off the extra work is two read-only store reads on a conflict."
   The code at 38d9ab151 (and at the head) makes one read per conflict: `record_by_epoch(epoch - 1)`, or `get_committee_keys(0)` for epoch 0 (`ConflictEvidence::read`); the PR text says "a committee read".
   Corrected: "Log fields only: with every switch off the extra work is one read-only store read on a conflict, the committee the record before it names."
3. f41df0b3b: "In bench 6 (r20261113-1351) which node served a certificate could only be told by joining log lines across nodes."
   Not in any posted issue (issue #1850 says only that no metric reports which certificates a node holds and asks for the serving peer on the lines); not checkable as worded.
   Corrected (code-only): "On main the line does not say which peer served the certificate."

### Consistent with their sources

- 9bf27f194: "Bench 6 (r20261113-1351) could tell whether every node holds every closed epoch's certified record only by joining logs.": issue #1850 ("No metric reports which certificates a node holds").
- 1f04e4025: "Three bench 6 runs had eleven such errors (three of them in r20261113-1351), each 64.5-65.0 s after the certificate was stored (issue #1852).": issue #1852 (7 + 3 + 1); the issue's "64.5-65.0 s after that" is ambiguous between the store and the first quorum line, and the body reads it as the issue's title does.
- 91ed3b450: the existing hook `TN_TEST_EXIT_BEFORE_EPOCH_RECORD` is on main (`crates/types/src/test_hooks.rs:30`); "about ten minutes and two restarts per attempt" is the hook design's own estimate (not a run); "two votes of three" = 2 of `4*2/3+1`.
- 655f2cd1d "about 65 s" (26 × 2.5 s), d557046a9 "up to about 480 s for 16 gaps" (16 × 3 peers × 10 s), 028d4a4d0 "7 of 10, 3 of 4" and "5 signers of an anchor committee of 10", 9f20217e6 "6 and 7 signers of an anchor committee of 10" (the test's cases), c7474572f "three tests", 04ace8cd3 "while five are already queued", 065ee9e5a "about four minutes" (224.9-261.6 s in the lane run) and "the three record switches and vote_queue_fix".

### Private labels

- "The domain review of the withhold hook found three places where the text said more than the code does." (ba28cb582) names the program's internal review.
  Corrected: "The withhold hook's docs said more than the code does in three places."
- "(domain review of the collector follow-ups)" (9f20217e6): delete the parenthesis.
- "The domain review of the epoch vote follow-ups found two loose ends of the kept quorum." (56ccf9920).
  Corrected: "The kept quorum had two loose ends."
- Every one of the 37 bodies ends with `Topic: <slug>` (`epoch-record-collector-hardening`, `epoch-loop-output-drop`): an internal bookkeeping trailer, not a finding id, unit name or path; harmless, keep or drop consistently across the stack.
- No finding ids (V…, I…, F…, L…), unit names, or paths under `tasks/` or `private/` in any body.

## Cross-text

- The two texts agree on the stack: PR 04's head is xf's previous head, both name the same next branches, both end Testing with the agreed placeholder.
- Metric names: PR 04 writes recorder names (`tn_node.…`, `tn_state_sync.…`), PR xf the Prometheus form (`tn_node_leftover_…_total`, as issue #1860 does); both are right (contract), one form across the stack would read better.
- `Fixes #1852` and `Fixes #1860` are justified on content, but GitHub closes an issue by keyword only on a merge into the default branch, not into `staging/benchmark-bench6-2026-11`: the issues will need closing by hand (procedure, not a text error).
- Both texts exceed 1,100 words.
