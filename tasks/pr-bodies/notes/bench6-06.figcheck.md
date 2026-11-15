# Figure-check FC-06: tasks/pr-bodies/bench6-06-digest-order-hold.md (not posted)

FIX

## Counts

Items checked: 93 (every figure, id, subject, link, issue, test name, `path:line`, quoted line and gate claim; the 17 commits counted one by one).
Match: 89. Wrong: 0. Untraceable: 0. Weak: 4.
Rule breaches: none (no private path, no unit name, no tool or assistant attribution, no "removed / fixed / eliminated" about #1807's losses, no significance claim, `Refs` and not `Fixes`).

## Errors (wrong)

None.

## Weak

1. l.55, the model test `canceled_story_overtakes_only_without_the_hold` is listed under "with it off".
   Source: the test runs both ways and asserts the overtake only without the hold: `crates/consensus/primary/src/tests/order_hold_model.rs:1277-1296` at 500e21afa (`for hold in [false, true]`, `assert_eq!(model.overtakes.is_empty(), hold, …)`).
   Replacement for l.55: "In `crates/consensus/primary/src/tests/order_hold_model.rs`, the model drives the real `OwnChainOrder`: with the hold on, `p1_each_lane_executes_in_order`, `p2_no_digest_executes_twice`, `p3_every_digest_is_accounted_for`, `p4_healthy_rounds_release_every_lane`, `p5_an_intact_chain_costs_nothing` and `gc_cut_is_the_only_overtake`; with it off, `hold_off_model_finds_the_overtake`; and both ways, `canceled_story_overtakes_only_without_the_hold` (a canceled header's digest overtakes without the hold and not with it)."
2. l.68, "against bench 6's 29,449 and 104,168 resends, 0 and 9,290 unlanded and 13,036 and 52,588 skips in the same cells".
   Source: the unlanded and skip cells are the same definition and window, but the resend cells are not: "definitions differ in window and source … bench 6's figure is its loss analysis's count with generator 05 left out (warm-up start to cool-down end); bench 7's is the attempted resends of generators other than 05" (`benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json` `q3_hold.pairs.7a_vs_b6run2.rows["gap resends, 05 apart"].definition`; `q2_senders.window`); the report's row carries the same caveat (report l.30: "bench 6's resends and skips: its warm-up start to its cool-down end").
   Replacement for l.68: "In the load blast, outside generator 05, neither run had a gap resend, an unlanded transaction after the 180-s tail scan or a `nonce_too_high` skip, against bench 6's 29,449 and 104,168 resends (counted from the load blast's warm-up start to its cool-down end), 0 and 9,290 unlanded and 13,036 and 52,588 skips."
3. l.83 with l.90, the "Longest held run, headers" row sets r20261115-1131's 21 (before the kill) beside r20261115-1653's 113 (after validator-05's start), and l.90 says only that run 7a's pair comes from two windows.
   Source: "The longest held runs are compared only within the same named window; the windows' bounds and lengths differ between the runs" (`benchmark/private/bench7-r20261115-1653/A9/comparison.json` `q3_hold.reading[2]`); windows `q3_hold.windows`: before the kill 817 s (r20261115-1131) and 1,121 s (r20261115-1653), after validator-05's start 1,308 s and 990 s (report l.427).
   Replacement for l.90: "Each longest run is validator-06's maximum in the window named; r20261115-1131's two come from different windows, and the windows differ in length (before the kill 817 s and 1,121 s, after validator-05's start 1,308 s and 990 s), so a row compares two runs only where its windows match."
4. l.107, "so a held backlog of at least `header_num_of_batches_threshold` builds the next header without the min delay, and that header carries none of it."
   Source: "that header can carry none of it" (`crates/consensus/primary/src/proposer.rs:1708-1710` at 500e21afa); "that header can carry none of the held digests" (`crates/consensus/primary/src/order_hold.rs:92-94`); `crates/config/src/node.rs:506-508` ("can carry none of them"): the plan is made again at the build, so the lane may be released by then.
   Replacement for l.107: "- Held digests count toward the digest trigger (`pending_digests_len`, `proposer.rs:1224-1226`, `:1715`), so a held backlog of at least `header_num_of_batches_threshold` builds the next header without the min delay, and that header can carry none of it."

## Not traceable

None.

## The four statements the writer narrowed

- The two fleet-check cells (l.112): supported as written.
  r20261115-1131: validator-06 in validator-05's outage, blockers_created 1, `tn_primary_headers_held_total` increase 0, held headers 0 (`benchmark/private/bench7-r20261115-1653/A9/comparison.json` `q3_hold.fleet_checks[n=5].a7a`; `benchmark/private/bench7-r20261115-1131/A7/losses.json` `fleet_checks`).
  r20261115-1653: validator-05 in blast 0, 18 blockers created, 26 headers with blockers, `pending_before` > 0 on 0, `num_batches` > 0 on 0, `held` > 0 on 0 (same key, `.b7b`).
  The run 7a files hold two more facts but no `pending_before` for that cell, so "nothing was queued" cannot be said for run 7a: `hold_cost.by_window.B2-outage.06` has `headers_with_blockers_gt0` 2, `held_max` 0, `digests_held_max_prom` 0.
  Optional sentence for the run 7a cell: "r20261115-1131's validator-06 during validator-05's outage (1 blocker created, 2 headers with blockers, 0 held headers, and `tn_primary_digests_held` never above 0)".
- Validator-06 instead of "the slowest validator" (l.85): supported as written: `comparison.json` row Q3.43, label "`blocker_created_pct`, validator-06 (far)", key `blocker_creation.by_window.B2.06.blocker_created_pct` = 6.9 / 15.6; run 7a's 06 is 252 of 3,672 pairs (`losses.json` `blocker_creation.by_window.B2.06`).
  No source checked names a slowest validator; keep validator-06.
- Run 7a's lost-header counts with or without validator-05 (l.69): the sources hold the fact.
  `benchmark/private/bench7-r20261115-1131/A7/losses.json` `lost_kinds.by_window.B2.05`: `loss_not_certified_with_batches` 0, `loss_certified_not_committed_with_batches` 0; `vs-bench6.json` `q3_hold.pairs.7a_vs_b6run2.rows["lost own headers"].bench7`: `not_certified` all 981 / 05_apart 981, `certified_not_committed` all 293 / 05_apart 293.
  (Run 7b checked the same way: `…-1653/A7/losses.json` `lost_kinds.by_window.B2.05` 139 and 18, so 1,127 − 139 = 988 and 356 − 18 = 338.)
  Replacement for l.69: "Lost own headers carrying batches still occurred on all nine validators other than 05 (r20261115-1131: 981 not certified and 293 certified but never committed, none of them validator-05's; r20261115-1653 without validator-05's own: 988 and 338), and no gap resend followed any of them."
- The hold's metrics with the switch off (l.49): supported as written; the text says only that they move with it on.
  Both handles are resolved when the proposer is built, switch on or off: `proposer.rs:410` (`order_hold_metrics: OrderHoldHandles::new()`), `crates/consensus/primary/src/metrics.rs:665-668` (`metrics::counter!("tn_primary.headers_held_total")`, `metrics::gauge!("tn_primary.digests_held")`); they change only in `drain_held` (`proposer.rs:1298-1301`, reached only with a plan, `:1419-1420`) and at stop with the hold on (`:1601-1602`).
  Whether an untouched series is served by the exporter is the recorder's behaviour and is not in the allowed sources; the e2e reader requires the series only with the hold on (`crates/e2e-tests/tests/it/digest_order_hold.rs:891-897`).
  Optional replacement for l.49, if the writer wants the fact: "Both of the hold's metrics exist with it off (`proposer.rs:410`); only with it on do `tn_primary_headers_held_total` and `tn_primary_digests_held` move, does an out-of-order re-queue log a warning, and is a committed header that returns after its own commit notice left untracked (`proposer.rs:1511`)."

## What matched (summary)

- Summary l.3-10: switch name and default `false` (`node.rs:521`, `:630`); rule and its release (`node.rs:501-505`, `order_hold.rs:19-20`, `:103-104`); validity and votes (`order_hold.rs:85-86`; the diff 38f00e88e..500e21afa touches no message type); trigger (`order_hold.rs:90-97`); PR 8 of 8 and merge order (gate brief l.19-24); compare link 38f00e88ea178f56cfcf5cba3e7495e339ce06ae...500e21afa6205b3b9cb39a05e5dc1fefc145747e; 17 commits (`git rev-list --count`).
- Problem l.14-17: main at 33b727fce `proposer.rs:974` (`drain_digests_for_header`), `:902` (`process_uncertified_header`), `:823` (`process_committed_headers`), `:849` (`take_while`), front of the queue (`:881`, `prepend_requeued`); 29,449 / 104,168, 13,036 / 52,588 (bench 6: any full node, blast 2), 280-345 s, 31 of 31 and 124 of 124 (`vs-bench6.json` `q3_hold.pairs`, `q2_senders.pairs`; report l.30, l.387, l.396).
- Change l.21-43: all 17 ids and exact subjects, in `git log --reverse` order, each an ancestor of 500e21afa; env names, metric names, label values, log lines and fields all present in the diff; `order_hold.rs:10-37`, `:14-18`, `:26-27`, `:51-60`, `:78-81`; `proposer.rs:1404-1428`, `:1290`.
- With the switch off l.47-51: `order_hold.rs:46-47`; `proposer.rs:409`, `:1237-1239`, `:1425` (own parent with the rest at default), `:1185`, `:1511`; five counters; `node switches` logs every switch whether or not the file names it (`node.rs:808-820`).
- Testing l.55-65: every test name at its file (order_hold_model.rs :1120-1281, proposer_tests.rs :3426-4432, digest_order_hold.rs :161-195); e2e assertions (`digest_order_hold.rs:1253-1274`); per-commit check 17 of 17 EXIT=0, warnings 0, nextest 1,452 passed / 8 skipped, clippy clean, commands as the logs' first lines.
- Bench figures l.67-91: Q2.01, Q2.06 (run 7a's 22: blast 0 0, blast 1 22, blast 2 0), Q2.08, Q2.14, Q2.15, Q3.36, Q3.37, Q3.39 (who 06), Q3.40 (9.083 / 55.273, who 06), Q3.41 (2.4600 / 3.1333), Q3.43, Q3.49, Q3.50, Q3.53, Q3.61 (49.84 / 60.51), Q3.62 (97.27 / 97.36); attribution (`q3_hold.attribution`); association (report l.428).
- Stack-wide gates l.93-102: equal to the brief's block line for line, character for character; per-commit file 103 OK, 0 FAIL; hunt line l.103 equals `orch-top-e2e-500e21afa.log` l.8 (cases=100000, seed=1223617546).
- Limits l.107-117: Q3.58 152 / 183 of 1,110 / 2,056, inferred (report l.429); threshold 5 and 350 ms (run 7a `early_trigger.fleet_parameters`); far validators Q3F.07 / Q3F.17 (50-61 rounds), Q3F.08 / Q3F.18 (21.03-21.39 s, run 7b only), Q3F.10 / Q3F.20 (held 0), 46-76 % (report l.507; `q3_far_validators.summary_rows` bh_cnc_share); `order_hold.rs:105-115`.
- Related: #1807 "A sealed transaction leaves the pool and the RPC, so a skipped one waits 5 minutes for a resend and a resend runs twice" (open): the hold removes one cause of the skip and the switch defaults off, so `Refs` fits; #1794 "Worker: a committee peer can fill the batch store of each peer with distinct valid batches" (open): the per-key bound of uncommitted stored batches is that issue's subject (`node.rs:512-513`), so `Refs` fits.
