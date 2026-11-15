# Sources: tasks/pr-bodies/bench6-05-quorum-exec-block.md (not for posting)

Worktree `/home/drtnarg/coding/telcoin/tn-b7-p2` (git read only). Head `fix/1804-quorum-exec-block` = `b7/n2-05` = 38f00e88ea178f56cfcf5cba3e7495e339ce06ae; head below `fix/epoch-loop-output-drop` (#1867) = f5f7589f52fff080fe909354b9a5086a73a3762f; main 33b727fce.
Report = `tasks/bench7-report-r20261115-1131.md`. C = `benchmark/private/bench7-r20261115-1653/A9/comparison.json` (rows are list entries with `id`, `a7a`, `b7b`, `spread`, `verdict`; `q1_table`, `q4_per_header`, `q5_per_validator`, `q7_recommendation`). V = `benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json`. 7a/7b A3 = per-run files under `benchmark/private/bench7-r20261115-1131/A3/` and `…-1653/A3/`.

## Stack, commits, compare link
- 18 commits, ids and subjects: `git log --reverse --format='%h %s' f5f7589f5..38f00e88e`; `git rev-list --count` = 18.
- "seventh pull request ... after #1862-#1867", stacked on #1867: `tasks/bench7/briefs/gate.md` l.19, l.23-26.
- Commit explanations: each commit's body (`git log -1 --format=%b <sha>`), checked against the code below.

## Code statements (38f00e88e unless named)
- Defaults `false` / `0`: `crates/config/src/node.rs:599-600`; fields `:398-399`, `:415-416`; listed in `runtime_switches!` `:803-804`.
- The rule (2f+1 weight, own tip + same-epoch parents, capped at tip, 8 ring entries floor, opening block): `node.rs:384-397`; `proposer.rs:1944-1963` (choose_exec_block doc), fn `:1967`; floor const `proposer.rs:1545` (doc `:1530-1544`).
- Count 0 = rule on every header: `node.rs:403`; `ExecPolicy::Always` doc `proposer.rs:1595-1596`.
- Adaptive: next K headers after a cancel, doubling, cap 128, reset after 64 certified tip headers, counts headers: `node.rs:403-412`; `proposer.rs:1573` (cap), `:1587` (streak), `:1648-1676` (policy doc).
- Cap lowered + warning once per epoch, count with switch off no effect: `node.rs:411-414`; `proposer.rs:305-318`, `:1708`, `:1723-1738`.
- Own ring entry, never a parent's hash: `proposer.rs:1947-1948`. Opening-block bound and the export assumption: `:1949-1957`; final bound `exec_basis=floor`, debug assertion: `:1958-1963`.
- Faulty high parents cost the gain only: `proposer.rs:~1938-1943` (doc) and test `test_quorum_exec_block_faulty_high_parents_cost_the_gain_only`.
- Floor not bound in time, fork noticed up to eight outputs later: `proposer.rs:1536-1544`.
- Log fields `exec_block`, `exec_tip`, `exec_basis`, `exec_policy` on `header proposed`: `proposer.rs:478-482`; `exec_policy` value `off`: `:1608`; basis names `:1641-1643`.
- Switch off: `proposer.rs:1908` `consensus_bus.app().latest_execution_block_num_hash()`; policy Off for every header `:1648-1650`. "Per header, policy bookkeeping that returns at once": review `tasks/bench7/review/05-quorum-exec-block-report.md` §2a (lines at its older tip 2b6a01022: `:1189-1194`, `:992`), node logic unchanged since apart from the window counting (94d0c84d6). `parameters.yaml` unchanged at defaults: `skip_serializing_if = "Parameters::switch_at_default"` `node.rs:398`, `:415`. Two fields on `node switches`: via `runtime_switches!` `node.rs:803-804` (review §2a).
- Mixed fleet (only `latest_execution_block` changes; voter never reads the switch; switch-off voter answers as for an older tip): review §2b; voter files not in this topic's diff (`git diff --stat f5f7589f5 38f00e88e`: config/node.rs, proposer.rs, recent_blocks.rs, two test files, e2e files only).
- Main at 33b727fce: `crates/consensus/primary/src/proposer.rs:379-385` (`Header::new(` … `consensus_bus.app().latest_execution_block_num_hash()`); voter wait `crates/consensus/primary/src/network/handler.rs:1462-1507` (`VoteStage::ExecWait`, `tokio::time::timeout`), the same range the posted vote-queue text cites; refusal after 1 s as execution-behind: review §2b.
- Bench 7 ran this head's node logic on 45dce8947 (`bench/bench7-2026-11`, 91a15e223): gate.md l.14; `tasks/checkpoint-bench7-BF-E05.md` item 5 (non-e2e +/- lines identical to the old head, 2,883 lines).

## Test names (file at 38f00e88e; `git diff f5f7589f5 38f00e88e -- <file>`)
- `crates/consensus/primary/src/tests/proposer_tests.rs`: 15 `test_quorum_exec_block_*`, the eight named in the text among them.
- `crates/consensus/primary/src/tests/network_tests.rs`: 14 `quorum_exec_block_voter_*` (`votes_block_in_ring_at_once`, `votes_block_out_of_ring_from_database`, `refuses_old_number_with_another_hash`, `votes_previous_epoch_blocks_in_ring`, `answers_previous_epoch_blocks_out_of_ring`, `waits_for_block_above_tip`, `votes_author_stepping_back`, each `_switch_off` / `_switch_on`); `vote_queue_fix` off/on: commit 1f8f9c076 body.
- `crates/e2e-tests/tests/it/exec_block.rs`: `test_fast_executor_is_certified` (`:180`), `test_mixed_switch_fleet_is_one_chain`; thresholds `MAX_CONTROL_SHARE` 0.85 `:117`, `MIN_CERTIFIED_SHARE` 0.93 `:121`, `MIN_ADAPTIVE_SHARE` 0.88 `:134`; arms `:61-63`, `:83-88`, doc `:152-170`; asserts `:250`, `:272`.
- `crates/e2e-tests/tests/it/epoch_close_forms.rs`: `test_held_member_two_closes_always`, `_adaptive`, `test_missed_record_round_always`, `_adaptive`.

## Gates
- 86 commits N..38f00e88e each compile alone: `tasks/bench6/per-commit-check-38f00e88e.txt` (86 `OK` lines, no other line); command form: `tasks/checkpoint-bench7-orch.md` l.1088 ("workspace, -D warnings").
- 1,392 passed / 7 skipped (tn-config, tn-types, tn-primary, tn-node, state-sync), clippy nightly-2026-03-20 (tn-config, tn-primary, tn-node, e2e-tests) 0 warnings, fmt EXIT=0: `tasks/checkpoint-bench7-BF-E05.md` items 7 (tip 287ba24b4 on 15f60ff82). Tree 287ba24b4 vs 38f00e88e differs only in `crates/state-sync/src/epoch.rs`, `metrics.rs` (`git diff --stat 287ba24b4 38f00e88e`); topic +/- lines identical (`cmp` of the two diffs). Package name `state-sync`: `crates/state-sync/Cargo.toml`.
- Stack-wide paragraph: verbatim from gate.md l.30-39.

## Benchmark figures
- Bench 6 pages and forms: gate.md l.13; u-common.md l.8.
- 99.94 % (r20261113-1351) / 99.56 % (r20261113-2118), before the kill: report l.446 [V q3_certification_rounds a, b]; windows l.441.
- 50,000 IOPS: adaptive ahead on certification, behind on senders' cost: report l.374 [C q7_recommendation].
- Table: report l.334 (Q1.01: 9,289 / 9,337, spread 8,344.6-10,544.9), l.335 (Q1.09: 95.59 / 95.00, 93.37-97.29), l.337 (Q1.24: 2.32 / 2.22, 1.99-2.73), l.338 (Q1.06: 17.33 / 24.18, 14.27-18.78), l.339 (Q1.04: 698.3 / 680.0, 688.2-722.8); verdicts as in C `q1_table[id].verdict`; spread definition l.330; no significance test l.370.
- 41 rows, 28 lower, 13 higher: report l.360 [C q5_per_validator.outside_7a_bucket_range].
- validator-01 100.0 → 89.2, validator-08 86.4 → 99.2: report l.340 [C Q1.11], l.344 [C Q1.15]; window lengths 817 / 1,121 s l.346 [C q3_hold.windows]; "does not separate the form from which validators lagged" l.363.
- 61.5 % inside the window, logged policy: report l.350-351 [C Q4.26].
- Replay 99.875 %, 56.3 % / 89.1 % at the 128 cap: report l.352 [C Q4.29] [C Q4.30].
- 1.66 headers, 64.0 %: report l.353 [C Q4.27] [C Q4.28].
- 7.57 → 4.83 outputs: report l.355 [C Q4.21]; value not measured: l.367, l.375.
- Bench 6 vs bench 7 before the kill: tx/s 5,322 / 9,289 and 5,395 / 9,337 l.445 [V q2_rows a.01, b.01]; certification 99.94 / 94.0 and 99.56 / 94.95 l.446 [V q3_certification_rounds a, b]; changes not separable l.461-462 [V q3_certification_rounds.attribution].
- Under-held 10.31 % / 12.55 %, "at most five other voters": l.455 [7a A3 q4u B2.fleet] [7b A3 q4u B2.fleet]; certified 61.25 / 66.70, rest 99.53 / 99.06: l.456.
- Floor 16 arithmetic: 0.00 % under-held, 14.71 / 13.81 vs 7.57 / 4.83 outputs, "arithmetic, not a result", floor kept at 8: l.458-460 [7a A3 perheader §8] [7b A3 perheader §8].
- No 50,000 IOPS run in bench 7: l.374.
- The adaptive form's added code: l.367, l.377.

## Left out (no source in the allowed record)
- Bench 5's per-validator certification figures (only in commit bodies, not in bench 7's report): the text says qualitatively what bench 5 showed and refers to #1804.

## Added after the figure-check (tasks/pr-bodies/notes/bench6-05.figcheck.md: five replacements applied verbatim)

- "Nothing that should be fixed before merge is open." Source: `tasks/bench7/review/05-quorum-exec-block-report.md` l.6-10 (verdict "APPROVE WITH FOLLOW-UPS"; "Nothing is Critical, High or Medium"; three Low findings V1, V2, V3) and the commits of this head that answer them: V1 (the adaptive window counted in rounds) `94d0c84d6` "fix(primary): count the adaptive exec-block window in headers built"; V2 (what the floor does not bound) `aae70e162` "docs(primary): say what the exec-block floor does not bound, and the upstream refusal"; V3 (faulty high parents) `8b673c528` "test(primary): pin what faulty high parents cost the quorum exec-block rule". Kept as written.
