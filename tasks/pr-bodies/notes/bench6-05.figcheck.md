# Figure-check FC-05: tasks/pr-bodies/bench6-05-quorum-exec-block.md (116 lines)

FIX
Two wrong items, three weak, one untraceable; none changes a conclusion of the text.

## Counts

- Items checked: 81 (Summary 10, Problem 20, Change 18, With the switch off 9, Testing 9, Limits 12, Related 2, rules sweep 1).
- match 75, wrong 2, weak 3, untraceable 1.
- Unchecked lines: none.

## Wrong

1. Line 100, "In the load blast before the kill, chain tx/s in the headline window went from 5,322 (r20261113-1351) to 9,289 (r20261115-1131) and from 5,395 to 9,337, while fleet certification went from 99.94 % to 94.0 % and from 99.56 % to 94.95 %."
   The values match, the window of the throughput figures does not: the headline window is blast 2's all-generators window with the kill and the outage inside, and only the certification row is "before the kill".
   Source: report l.441 ("the throughput row: bench 5's headline window, blast 2's all-generators window with the kill inside"); A9/comparison.json `q1_table` Q1.01 label "B2 chain tx/s, bench 5's headline window (all-generators window; outage and generator 05 i[nside])"; A10/vs-bench6.json `q2_rows.pairs.7a_vs_b6run2` Q2.a.01 and `7b_vs_b6run3` Q2.b.01, key `.blasts[2].bench5_defs.kpis.avg_chain_tps_all_generators` (5,322.07 / 9,288.60; 5,394.65 / 9,337.15).
   Replacement: "- Certification fell against bench 6 while throughput rose. Over the load blast's headline window (all generators, the kill inside), chain tx/s went from 5,322 (r20261113-1351) to 9,289 (r20261115-1131) and from 5,395 (r20261113-2118) to 9,337 (r20261115-1653); in the mixed phase before the kill, fleet certification went from 99.94 % to 94.0 % and from 99.56 % to 94.95 %."
   (This also gives r20261113-2118 and r20261115-1653 their ids in the second pair, which line 100 leaves out.)

2. Line 103, "at the cost of a named block about twice as old (14.71 and 13.81 block-bearing outputs from the tip, against the measured 7.57 and 4.83)".
   The ratio holds for r20261115-1131 only: 14.71 / 7.57 = 1.94, but 13.81 / 4.83 = 2.86 for r20261115-1653 (in seconds, 13.16 / 6.77 = 1.94 and 12.72 / 4.45 = 2.86).
   Source: report l.460; per-run perheader.md §8 rows "B2 | measured" and "B2 | floor 16" (r20261115-1131: 7.57, 6.77 s / 14.71, 13.16 s; r20261115-1653: 4.83, 4.45 s / 13.81, 12.72 s). "About twice" comes from the gate brief, not from a source.
   Replacement: "Arithmetic on these two runs, holding the rest fixed, says a floor of 16 entries leaves none under-held, at the cost of an older named block (14.71 and 13.81 block-bearing outputs from the tip, against the measured 7.57 and 4.83: about twice as far in r20261115-1131 and almost three times in r20261115-1653); that is arithmetic, not a result, and the floor stays at 8."

## Weak

3. Line 69, "Every choice is the proposer's own executed ring entry, at or below its tip and at or above the epoch's opening block, which a voter with the switch off answers as it would answer an older tip."
   The code doc names an exception: a proposer that starts the epoch before executing the previous epoch's closing block has no such block in its ring, and the rule names its own tip, as the switch-off form does (`crates/consensus/primary/src/proposer.rs:1960-1963` at 38f00e88e). The rest holds: own ring entry, never a parent's hash (`:1947-1948`); the voter never reads the switch (the only non-test readers are `proposer.rs:305-306` and `crates/config/src/node.rs`).
   Replacement: "Every choice is the proposer's own executed ring entry, at or below its tip and, once the proposer has executed the block the epoch opened on, at or above that block (before then it names its own tip, as the switch-off form does); a voter with the switch off answers it as it would answer an older tip."

4. Line 81, "This topic's 18 commits on an earlier tip of `fix/epoch-loop-output-drop` (15f60ff82), whose tree differs from this head's only in `crates/state-sync/src/epoch.rs` and `crates/state-sync/src/metrics.rs`:"
   As written, "whose" refers to 15f60ff82, whose tree differs from 38f00e88e in the whole topic too. The tree that differs only in those two files is the topic applied on 15f60ff82 (287ba24b4): `git diff --stat 287ba24b4 38f00e88e` shows only those two files (18 insertions, 12 deletions); the two topic diffs are byte-identical (`cmp` of `diff 15f60ff82 287ba24b4` and `diff f5f7589f5 38f00e88e`).
   Replacement: "This topic's 18 commits applied on an earlier tip of `fix/epoch-loop-output-drop` (15f60ff82); that tree differs from this head's only in `crates/state-sync/src/epoch.rs` and `crates/state-sync/src/metrics.rs`:"

5. Line 101, "The storage engine, main's vote-handler rework, the order hold, the voters' execution lag and the run's shape changed together, and no counter separates them."
   The source's list has one more item for the adaptive pair: "the adaptive rule change (7b/run 3 only)" (A10/vs-bench6.json `q3_certification_rounds.attribution`; report l.462). The window's rule itself changed between bench 6 and bench 7 (rounds to headers built: `94d0c84d6`), so the second pair compares two different adaptive rules.
   Replacement: "The storage engine, main's vote-handler rework, the order hold, the voters' execution lag and the run's shape changed together, and for the adaptive pair the window's rule too (it now counts headers built, not rounds); no counter separates them."

## Untraceable

6. Line 111, "Nothing that should be fixed before merge is open."
   The sources note gives no source; the sentence is copied from the posted model text (`tasks/pr-bodies/bench6-02-vote-queue.md:82`), and the topic review `tasks/bench7/review/05-quorum-exec-block-report.md` does not contain it.
   Replacement: keep it only if the orchestrator confirms the topic review has no open item; otherwise delete the line.

## Notes (no change to the text needed)

- Posting step: in `/home/drtnarg/coding/telcoin/tn-b7-p2` the local branch `fix/1804-quorum-exec-block` points at 63516124a and `fix/epoch-loop-output-drop` at b69e9c1a9, not at 38f00e88e / f5f7589f5; the mark `b7/n2-05` is at 38f00e88e. Push the head from the mark, or the compare link and the Files tab will not match the text.
- Lines 21 and 100, bench 6 against bench 7 certification: the report's row (l.446) and V (`q3_certification_rounds.pairs.*` row "certified pre-kill, rounds unit (%)") say bench 6's figure is its rounds analysis's and bench 7's the certification analysis's count, "different units' figures for the same window". The same-tool counts in V give bench 6 40,957 / 40,975 = 99.96 % and 38,108 / 38,275 = 99.56 %, bench 7 19,513 / 20,758 = 94.00 % and 26,179 / 27,571 = 94.95 %, so the comparison holds within 0.02 points.
- Line 65, the three statements resting on the older review, checked in the code at 38f00e88e: with the switch off `ExecBlockPolicy::for_round` returns `ExecPolicy::Off` first (`proposer.rs:1765`), `on_certified` (`:1821`) and `on_cancelled` return at once when the policy is not adaptive, `ExecBlockInputs::new` builds no parent list for `Off`, and `choose` returns the tip read before touching the ring (`:1906-1909`); the voter never reads the switch (only `proposer.rs:305-349` and the config read it outside tests); the topic's diff touches no voter, certifier or worker file. All three hold as written.
- Line 79: 86 `OK` lines, 0 `FAIL`, all 18 topic commits among them (`tasks/bench6/per-commit-check-38f00e88e.txt`); `rev-list --count 33b727fce..38f00e88e` = 86. The command's `--all-targets` is not visible in the per-commit log or the orchestrator's line 1088 ("workspace, -D warnings"); the gate brief's block states the same command for the same check.
- Lines 82-83: the nextest log at 287ba24b4 reads "1392 tests run: 1392 passed, 7 skipped" for `-p tn-config -p tn-types -p tn-primary -p tn-node -p state-sync`; clippy ran `cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-config -p tn-primary -p tn-node -p e2e-tests -- -D warnings`, EXIT=0; fmt EXIT=0.
- Lines 87-96: identical, character for character, to the brief's block (gate.md l.30-39), first sentence included.
- Rules: no private path, unit name, host, tool or assistant attribution; no "run 7a/7b" nickname; no significance claim (l.24 says so); the replayed figures are marked (l.37); `Refs #1804`, not `Fixes`.

## Matched items, by section (for the record)

- Summary l.3-10: switch names and defaults (`node.rs:399`, `:416`, `:599-600`), the rule (`node.rs:387-390`), count 0 on every header (`node.rs:403`, `proposer.rs:1595-1596`), the adaptive form (`node.rs:404-414`, cap `proposer.rs:1573`, streak `:1587`), four log fields (`proposer.rs:478-481`), "seventh … after #1862-#1867" (gate.md l.19, l.26), compare link's two full shas, 18 commits.
- Problem l.15-39: main `proposer.rs:379-385` (`Header::new` at 379, the call at 385), `handler.rs:1462-1507` (1 s: `crates/config/src/consensus.rs:459` at 33b727fce, `ExecutionBehind` on timeout), e2e test (four nodes, `SLOW_NODES` three, 0.85 at `exec_block.rs:117`), bench 6 runs and forms, 99.94 / 99.56, 50,000 IOPS sentence (report l.374), bench 7 build and runs, spread definition (report l.330), the five table rows (C Q1.01 9,288.6 / 9,337.2, 8,344.6-10,544.9; Q1.09 95.59 / 95.0, 93.37-97.29; Q1.24 2.321 / 2.216, 1.993-2.733; Q1.06 17.33 / 24.18, 14.265-18.779; Q1.04 698.25 / 679.97, 688.2-722.8; verdicts as in C), 41 / 28 / 13 (recounted from `q5_per_validator.rows`), validator-01 and validator-08 (Q1.11, Q1.15), 817 / 1,121 s (`q3_hold.windows.B2-prekill`), 61.5 % (Q4.26 61.52), 99.875 % / 56.3 % / 89.1 % (Q4.29 note, 56.35, 89.13), 1.66 / 64.0 % (Q4.27 1.658, Q4.28), 7.57 → 4.83 (Q4.21 7.573 / 4.832).
- Change l.43-60: all 18 ids and subjects equal `git log --reverse --format='%h %s' f5f7589f5..38f00e88e`, in order; the descriptions agree with the code and commit bodies (`proposer.rs:1947-1948`, `:1958-1960`, `on_cancelled` resets the streak on every report, warnings in `starved_rounds_warning`, `1f8f9c076`'s body; no voter file in the topic's diff).
- With the switch off l.64-70: `proposer.rs:1908`, `:305-318`, `:478-481` with `off` at `:1608`, `runtime_switches!` `node.rs:803-804`, `skip_serializing_if = "Parameters::switch_at_default"` `node.rs:398`, `:415`, `test_mixed_switch_fleet_is_one_chain` at `exec_block.rs:579`.
- Testing l.74-76: 15 `test_quorum_exec_block_*` in proposer_tests.rs with the eight named; 14 `quorum_exec_block_voter_*` (seven cases × `_switch_off` / `_switch_on`) in network_tests.rs; `test_fast_executor_is_certified` (`exec_block.rs:180`), thresholds 0.85 / 0.88 / 0.93 (`:117`, `:134`, `:121`), the always arm runs with `vote_queue_fix` (`:63`, `:86-89`); the four `epoch_close_forms.rs` tests (`:320`, `:328`, `:336`, `:344`).
- Limits l.102-109: under-held 10.31 / 12.55 %, 61.25 / 66.70 %, 99.53 / 99.06 % (A3 `q4u-*-B2.json` fleet); floor-16 figures (perheader.md §8, B2 rows); `proposer.rs:1530-1545`, `:1938-1943`, `:1949-1957` at 38f00e88e; no 50,000 IOPS run; the adaptive form's added code (report l.377 and `proposer.rs:1587`).
- Related l.115-116: `Refs #1804`, `fix/1804-vote-queue` (#1864) (gate.md l.19); 38f00e88e is an ancestor of 500e21afa (`fix/1807-digest-order-hold`).
