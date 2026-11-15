# Figure-check FC-N34: PR texts 03 and 04 on main at 33b727fce (not posted)

Checked 2026-11-15 (UTC) against the code in `/home/drtnarg/coding/telcoin/tn-b7-p2` (git object reads only), the gate logs under `tn-b7-n03/target/tmp/bf03-*`, `tn-b7-n04/target/tmp/bf04a*-*`, `tn-b7-n04b/target/tmp/bf04b-*`, and `gh` reads of #1834, #1849, #1850, #1851, #1852, #1860.
Revisions: N = 33b727fcea4f6004d4b0cd2bd7923258e081e94f; head 02 = 17327280d; head 03 = c2f266b9c; head 04 = ff877fb0e; the stack is linear 33b727fce → n2-00 → n2-01 → n2-02 → n2-03 → n2-04 → n2-xf (f5f7589f5) → n2-05 → n2-06.
The writers' source notes were used only to find lines; every line below was opened at the stated revision.

## Verdicts

- `bench6-03-closing-block-check.md`: FIX (one wrong quoted command; four weak statements; nothing changes a conclusion).
- `bench6-04-collector-hardening.md`: FIX (two errors: the cause named for the cited pass-end lines, and the count of corrected commits; one weak statement; nothing changes a conclusion).

## Errors

1. Text 03, "Testing", second bullet, the phrase "`cargo clippy --locked --all-targets -p tn-node -- -D warnings` clean at `c2f266b9c`".
   The log shows the command ran on the pinned nightly: `tn-b7-n03/target/tmp/bf03-clippy.log:1` `cmd: cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-node -- -D warnings`, EXIT=0; `bf03-clippy-adiri.log:1` the same with `--features adiri`, EXIT=0.
   The fmt line of the same section already names the toolchain, so the two quoted commands read inconsistently.
   Replacement: "- `cargo +nightly-2026-03-20 clippy --locked --all-targets -p tn-node -- -D warnings` clean at `c2f266b9c`, also with `--features adiri`, where the 51 tests of the `close_epoch` and `metrics` modules, the entry test and the identity counter test passed."

2. Text 04, "Problem", first sentence, the phrase "the collector ends each pass at the first record it cannot store (`crates/state-sync/src/epoch.rs:372-374`)".
   At 33b727fce, `crates/state-sync/src/epoch.rs:372-374` is `if result_epoch != epoch { break; }`, reached when `request_epoch_cert` fails, i.e. no peer serves the epoch (the `Err(err)` arm, `:360-370`, "failed to retrieve epoch from a peer"); a store refusal returns earlier, at `:308-313`.
   The uncertified-epoch stop the paragraph describes is the fetch case, as #1850's comment of 2026-11-15 says: "The pass still ends at the first epoch no peer serves (`crates/state-sync/src/epoch.rs:372-374`)".
   Replacement: "On main at 33b727fce the collector ends each pass at the first epoch no peer serves (`crates/state-sync/src/epoch.rs:372-374`) and peers serve a record only with its certificate (`crates/consensus/primary/src/network/handler.rs:1909-1919`): an epoch K the network leaves uncertified stops every collector at K, across restarts."

3. Text 04, "Limits", last bullet, the phrase "Five commits are corrected by later commits of this head rather than squashed".
   At least seven are: besides the five pairs of the earlier review (df0075d98 by 3805eab5b, 0a7c8f21c by 8038aa198, 8b3109ddb by 64a6de4b5, f2f3de1bd by 3143a099d, 9e97158b9 by ba73ee5f9), `4c63328ca` counts the conflict before the evidence read's await (`git show 4c63328ca:crates/state-sync/src/epoch.rs:208-209`), which `d6992db59` corrects (its body: "The collection counted a conflicting certified record … before it awaited the read of the conflict's evidence"), and `80e1672a8`'s kept quorum is corrected by `8c76745f2` (its body: "The kept quorum had two loose ends").
   `b7f008dc9` also rewrites docs of earlier commits of this head, so seven is a floor.
   Replacement: "- Some commits are corrected by later commits of this head rather than squashed (seven at least; `d6992db59`, for one, moves the conflict count of `4c63328ca` after its evidence read), and an e2e error message names `STACK_SWITCHES_ON`, which a later head adds."

## Not traceable

- Text 04, "Testing": "`state-sync` and `tn-config` 228 passed and clippy clean at `d6992db59`, `state-sync` 78 passed at `b7f008dc9`".
  The counts match the logs (`tn-b7-n04/target/tmp/bf04a3-nextest.log` "228 tests run: 228 passed, 0 skipped", EXIT=0; `bf04a3-clippy.log` EXIT=0; `bf04a4-nextest.log` "78 tests run: 78 passed, 0 skipped", EXIT=0), but these logs carry no HEAD line: the commit at which they ran comes only from the writer's checkpoint (`tasks/checkpoint-bench7-BF-04a.md:119`, `:137`).
- Text 04, "Testing": "fmt clean" for d6992db59 and b7f008dc9: `bf04a3-fmt.log` and `bf04a4-fmt.log` hold only `EXIT=0`, with no command or HEAD line (`bf04b-fmt.log` likewise).
- Text 04, "Problem": "all 37 closes … certified with at least 7 of 10 validators" is a bench-6 figure kept from the earlier text (out of this check's scope); #1850's body gives the cells (403 of 407), not the 7-of-10 floor; the 37 closes and the three runs agree with text 03 and #1851.
- Text 03, "Limits": "False positives, traced in the code with none failing … the rule matches every engine branch that writes a marker" restates earlier code reviews; not re-derived here.

## Weak

- Text 03, "Summary", first sentence: "the 32-byte closing seed in `extra_data`" is stronger than the code: the seed is compared only when the node holds the boundary header the record commits (`c2f266b9c:crates/node/src/manager/node/close_epoch.rs:1521`, `closing_seed_for` `:850-857`), and the entry compares the length only (`:664-673`, seed `None`).
  The "Change" section says so; a Summary that matches it: "… the record's epoch in the nonce, and a 32-byte `extra_data`, the closing seed where the node holds it."
- Text 03, "Problem": "Only the restart re-derive path reads any of the block's markers, the beacon root and the nonce's epoch, to find the boundary header" — at 33b727fce the startup restore-consistency guard also reads the executed tip's beacon root and nonce epoch (`crates/node/src/manager/node.rs:1945-1964`, via `last_executed_consensus_block`), though not to build or compare a record.
  Suggested: "Among the record paths, only the restart re-derive path reads any of the block's markers …" (#1851 itself says "Among the record paths only `boundary_consensus_digest` … reads any").
- Text 03, "Testing": "`a_closing_block_the_engine_builds_passes_the_check` (an earlier block of the same output fails)" holds for the default build only: under `--features adiri` epoch 0 skips comparison (c), and the test expects `Ok` for that block (`marker_result`, `close_epoch.rs:2780-2786`, used at `:3063-3066`).
- Text 03, "What changes for every node": "Per live close, `tn_epoch_epoch_close_identity_check_total{result}`" — not counted when the epoch-info read behind it fails (`c2f266b9c:crates/node/src/metrics.rs:79`; `run_epoch.rs:915-933` return before `:937`).
- Text 04, "Testing": "`cargo nextest run --locked` of `tn-config`, `state-sync`, `tn-node`, `tn-primary`, `tn-types` and `tn-network-libp2p` 1,952 passed, 9 skipped, and clippy clean, at `8c76745f2`" reads as clippy over the six packages; clippy ran on four (`scratchpad/BF-04a-2/gates.sh:32`: `-p tn-config -p state-sync -p tn-node -p tn-primary`; `bf04a2-clippy-tip-r2.log` EXIT=0).
  Replacement: "… 1,952 passed, 9 skipped, and clippy of the first four clean, at `8c76745f2`; …"

## Rule breaches

- None in either text: no unit name, private path, host or person name, run nickname, or attribution (scan of both files); the stack-wide-gates placeholder line was ignored as instructed.

## Checked and matched (summary)

- Text 03 commits: 7e67af7d7, 128f4a5d4, c2f266b9c exist, are `b7/n2-02..b7/n2-03` (3 commits), subjects exact; compare link 17327280d54590d74581fc1abc40d03dd2961c3d...c2f266b9c458cad9f238a5ff1100f280e38da9f8 right; "PR 4 of 6", merge order 00, 01, 02, 03, 04, epoch-loop (brief `w-n.md:12-20`); `fix/1804-quorum-exec-block` (n2-05) is a later head stacked on the epoch-loop head.
- Text 03 main lines at 33b727fce: `close_epoch.rs:1274` (guard), `:1280` (`<` floor), `:431` (record-0 arm, added by d4d53c115 = #1849; at 45dce8947 the floor was `<=`), `:438`, `:596`, `:411`, `:520`, `:525`, `:1303-1325`; `final_state` logged only in the mismatch error (`:741-751`).
- Text 03 head claims at c2f266b9c: check order (a)(b)(c) `:1502-1525`; build path before committee reads and save (`:505-512` before `:553`, `:587`); stored paths after the `final_state` compare (`:803-815`), seed by `closing_seed_for` at `:465`, `:481`; entry length-only `:664-673`; adiri skip at epoch ≤ 160 (`:1534-1544`, `forks.rs:71`); floor rule `:1382` with the Restored arm unchecked; record bytes unchanged (same ring value, same `final_consensus`); commit 2 at `run_epoch.rs:936-938`; commit 3 (at 128f4a5d4 the re-derive passed `Built` and an empty ring failed as `beacon_root`; now `Rederived`, `NoBlock`, `halt_reason`); main's guard tests rebuilt with markers; `replay_guard_stops_on_an_uncertified_epoch0_record_that_does_not_match` byte-identical (N `:2222-2251` = head `:2630-2659`).
- Text 03 names: counter `tn_epoch.epoch_record_closing_block_check_total` with the six labels (`metrics.rs:70-72`, `close_epoch.rs:1459-1467`); `tn_epoch.epoch_close_identity_check_total` `ok`/`mismatch` (`metrics.rs:80-84`); info line `epoch record published` with its seven fields and three branches (`:1643-1655`, `:486-490`, `:592`); halt line, target, four paths, error tail (`:1570-1587`, `:1414-1420`, `:1620-1632`); all 18 test names exist at the head.
- Text 03 figures: check EXIT=0 at 128f4a5d4 and c2f266b9c (`bf03-check-c2.log`, `-c3.log`); nextest 236 passed, 1 skipped (`bf03-nextest.log`); fmt clean (`bf03-fmt-check.log`); adiri 51 passed (`bf03-nextest-adiri.log`, filter as described); 37 closes over r20261113-1351, r20261113-1630, r20261112-1520 and "final_state not measured" (#1851 body).
- Text 03 upstream: #1851 OPEN (Refs, fix sketch implemented incl. the info line and counter; e2e half in n2-05's `epoch_close_forms.rs:1190-1267`, `:921-975`); #1860 OPEN, "found while reviewing a change to the epoch-close path"; benchmark image 91a15e223 carries the check (0238163c2) and the earlier form of head 04.
- Text 04 commits: all 27 short ids are in `c2f266b9c..ff877fb0e` and every commit of the range is named; link and count 27 right; "PR 5 of 6"; stacked on 03.
- Text 04 main lines at 33b727fce: `handler.rs:1909-1919`, `epoch_votes.rs:483-502`, `:279-289`, `:231-237`, `:403-404`, `state-sync/src/epoch.rs:228-245` (introduced by #1849, absent at 45dce8947), `crates/storage/README.md:427-429`, `crates/tn-reth/README.md:1270-1278` (neither changed by head 04).
- Text 04 head claims at ff877fb0e: switches and defaults (`node.rs:408`, `:439`, `:565-566`, `:767-768`); peer/signers on both `retrieved cert` lines (`epoch_votes.rs:413-418`, `state-sync/src/epoch.rs:742-747`); gauge semantics (`state-sync/src/metrics.rs`); held-cert round (`epoch_votes.rs:328-347`, alarm `:443-444`); re-certify pick N-16..N-2, round-robin, members only (`:846-891`), startup re-arm (`:821-827`); `round` label (`:1186-1202`); kept quorum not for a conflict (`:446-503`); re-certify conflict = main's `we have forked!` + shutdown (`:400-411`, test cases `:4496-4500`); walk, 16 gaps, 5 s deadline and retry (`state-sync/src/epoch.rs:30`, `:62`, `:73`, `:164-190`); main's stop byte-identical (`:534-552` vs N `:228-246`); evidence line text and its 11 fields, read-then-count-then-line-then-stop (`:236-271`), `committee=0` on a failed read (`:296-313`); dropped switch, threshold and counters absent at the tip, present on the old branch; eviction rule (`epoch_votes.rs:526-531`, `:604-621`); hook variables, default 1, `test-utils` only, release `-p telcoin-network` build (`test_hooks.rs:187-211`, N `etc/Dockerfile:51`, N `crates/e2e-tests/Cargo.toml:21`); e2e files; `STACK_SWITCHES_ON` defined only at n2-05 (`fleet.rs:91`).
- Text 04 figures: 1,952 passed, 9 skipped over the six packages at 8c76745f2 (`bf04a2-nextest-tip-r2.log`, gates run r2 ending at 8c76745f2 with no tip warning); 24 per-commit checks by final id with `-D warnings` (`bf04a-per-commit-summary.log` 01-10, `-2.log` 11-18, `bf04a2-…-r1.log` 21, `-r2.log` 22-26; RUSTFLAGS in both gates scripts); d6992db59 check `-p tn-config -p state-sync -p tn-node -p e2e-tests`, b7f008dc9 check `-p state-sync` (doc comments only); e2e at d1da5db0b (parent 8c76745f2; `git diff d1da5db0b ff877fb0e` = `git diff 8c76745f2 b7f008dc9`), 3 of 3 passed (`bf04b-walk.log`), e2e check and clippy EXIT=0; K = 1, two of four withhold, two rounds, no conflict line or counter (`epoch_record_walk.rs:36-57`, `:499-510`); 10/7/5 and "more than f" (N `types/src/primary/epoch.rs:96-111`, `:145-162`); 16 gaps, 17 kept records.
- Text 04 upstream: #1850 OPEN, comment 2026-11-15 "#1849 fixed G2, and G1 is unchanged" and the 7-of-10 question; #1852 OPEN, 11 times in the three runs, its sketch (check `cert_by_digest`, info + count, gauge question) matches `Fixes`; #1849 MERGED (d4d53c115), #1834 MERGED.

## Between the two texts

- Same base and order line, same 37 closes over the same three runs, same neighbours (03's "Next" is 04; 04's "Stacked on" is 03; both place `fix/1804-quorum-exec-block` after them): consistent.
- Nit, not an error: 03 says "a benchmark of the stack's earlier cut on main at 45dce8947 … is under way", 04 "a benchmark of this stack's earlier form on main at 45dce8947 is running"; the brief's wording is "earlier cut", so 04 could read "a benchmark of the stack's earlier cut on main at 45dce8947 is under way, and this text reports none of its results."

## Counts

- Text 03: 70 figures and statements checked; 65 matched; 1 wrong; 4 weak; 0 untraceable (1 restated review claim not re-derived).
- Text 04: 124 checked; 118 matched; 2 wrong; 1 weak; 3 not traceable from the logs alone or out of scope (the two commit-less logs and the 7-of-10 bench-6 figure).
- Rule breaches: 0 and 0.
