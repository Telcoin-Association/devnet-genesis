# Sources: tasks/pr-bodies/bench6-06-digest-order-hold.md (not posted)

Code worktree: /home/drtnarg/coding/telcoin/tn-b7-p2 (git read only). Tip T = 500e21afa6205b3b9cb39a05e5dc1fefc145747e; head below = 38f00e88ea178f56cfcf5cba3e7495e339ce06ae (fix/1804-quorum-exec-block); main M = 33b727fce.
Report R = tasks/bench7-report-r20261115-1131.md. [C Qx] = benchmark/private/bench7-r20261115-1653/A9/comparison.json, row id Qx (keys a7a/b7b name the per-run file and key); [V k] = benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json key k; [7a A7 k] / [7b A7 k] = benchmark/private/bench7-r20261115-1131/A7/ and …-1653/A7/ (Q3 rows cite A7/losses.json).

## Stack, commits, link
- 17 commits, ids and subjects: `git log --reverse --format='%h %s' 38f00e88e..500e21afa`; count `git rev-list --count` = 17.
- PR 8 of 8, after #1862-#1867, {{pr-05}} = PR of fix/1804-quorum-exec-block: tasks/bench7/briefs/gate.md l.19-24.
- Commit descriptions: each commit's body (`git log --format=%b`), checked against T below.

## Code at T
- Rule, own parent, blockers, held lanes, "tracked": crates/consensus/primary/src/order_hold.rs:10-37 (own parent :14-15, blockers :16-18, drain none of a blocker's workers :19-20, tracked :26-27).
- Why the hold is enough (older before newer or never; re-queue is the only reorder; hold until commit notice or cancel): order_hold.rs:51-60. GC cut residual, counted not prevented: :78-81.
- Switch off = base drain, proposer does not consult the module (I3): order_hold.rs:46-47; proposer.rs:409 (`order_hold: config.parameters().digest_order_hold.then(OwnChainOrder::default)`); proposer.rs:1237-1239 (`drain_digests_for_header` = `drain_digests_except(&BTreeSet::new())`), doc :1241-1244 ("an empty `held` is exactly that drain"); call site :1402-1428 (parents taken :1404, pending_before :1406, plan+record :1409-1418, drain_held or base drain :1419-1427); drain_held :1290-1309.
- Validity / votes unchanged: order_hold.rs:85-86 ("It does not decide when a header is built, what makes a header valid, or what peers vote for"). "the messages ... do not change": `git diff --stat 38f00e88e 500e21afa` touches no message type or network crate (18 files: config, primary, worker docs, e2e, node close_epoch, tn-reth re-export, types test_hooks).
- Trigger counts held digests: order_hold.rs:90-99; proposer.rs:1224-1226 (`pending_digests_len` sums every lane), :1708-1715 (comment + `enough_digests`), :1718-1720 (formula); switch doc crates/config/src/node.rs:497-519; field :521; default false :630.
- Narrower trigger not built: order_hold.rs:97-99; proposer.rs:1712-1714.
- Release / two cases waiting for the next own commit: order_hold.rs:101-115 (cases :105-115, "On the base its digests wait just as long" :115).
- Out-of-order counter and `out_of_order` field always; warning only with hold: proposer.rs:1145-1157 (doc), :1185 (`if self.order_hold.is_some() && order.out_of_order > 0`).
- headers_held / digests_held move only via drain_held (hold on): proposer.rs:1298-1301; set 0 only with hold :1601-1602.
- Committed header returning after its notice not tracked again (hold on): proposer.rs:1511 and comment :1500-1510.
- Re-queue paths at T: committed proposer.rs:959 (take_while :999), cancel :1081 (prepend :1125).
- Metric names (code strings with dots; Prometheus names with underscores as e2e uses, digest_order_hold.rs:134): tn_primary.uncertified_report_dropped_total, tn_node.orphan_txs_total, tn_node.orphan_batches_total, tn_primary.requeued_out_of_order_total, tn_primary.requeued_order_unknown_total, tn_primary.headers_held_total, tn_primary.digests_held (`git diff 38f00e88e 500e21afa` strings). Reasons shutdown/full/unsubscribed: bd655ff17 body. Result kinds already_pooled/refused_nonce_too_low/refused_other: f5ad6de5a body. Header proposed fields own_parent/held/held_lanes/blockers: e546b2d7b body; proposer.rs:265-275 (HoldReport).
- `node switches` line shows given switches: e2e check_form doc digest_order_hold.rs:1255-1256.
- Over-quota counter name tn_worker.batch_reports_over_quota_total and #1794 bound: node.rs:511-514 (switch doc); 6f43811fb body.
- Test hook: crates/types/src/test_hooks.rs:195-226 (`own_cert_delay`; "Unset or zero means no" hold :195); fa48e098d body (before_store / after_store).

## Main at M (33b727fce), crates/consensus/primary/src/proposer.rs
- drain_digests_for_header :974; process_uncertified_header (cancel re-queue) :902; process_committed_headers :823, walk (take_while) :849; pending_digests_len :961; pending_before on `header proposed` :409-410; enough_digests :1288.
- Mechanism (later nonces run first, skipped as nonce too high): order_hold.rs:3-8 at T; e2e module doc digest_order_hold.rs:4-9 at T; 9235cd25f body.

## Tests (file at T)
- Model: crates/consensus/primary/src/tests/order_hold_model.rs: p1..p5, gc_cut_is_the_only_overtake :1120-1161, hold_off_model_finds_the_overtake :1170, long_hunt_order_hold :1231, canceled_story_overtakes_only_without_the_hold :1281. Module path `order_hold::model` (order_hold.rs:932 `mod model;`).
- crates/consensus/primary/src/tests/proposer_tests.rs (added in 38f00e88e..500e21afa): test_digest_order_bookkeeping_keeps_payloads_golden (2a63f2f67; body: cancel, two commit re-queues, lane rotation, header cap), test_canceled_requeue_behind_a_newer_digest_counts_out_of_order, test_committed_requeue_behind_a_committed_digest_counts_out_of_order, test_order_hold_keeps_a_canceled_headers_lane_in_order, test_order_hold_holds_nothing_on_an_intact_own_chain, test_order_hold_replays_the_model_counterexample.
- e2e crates/e2e-tests/tests/it/digest_order_hold.rs: tests :160-161, :169-170, :184-185, :194-195; module doc :1-18; assertions check_form doc :1253-1274 (hold on: exactly once, no resend, OUT_OF_ORDER 0, nonce_too_high 0, HEADERS_HELD > 0; control: OUT_OF_ORDER > 0, HEADERS_HELD = 0, losses reported).
- Head gates: tasks/checkpoint-bench7-BF-E06.md l.13-14; logs /home/drtnarg/coding/telcoin/tn-b7-n06/target/tmp/bfe06-summary.log (check-01..17 EXIT=0 warnings=0; nextest "1452 tests run: 1452 passed, 8 skipped"; clippy EXIT=0 warnings=0), commands from first lines of bfe06-check-01.log, bfe06-nextest.log, bfe06-clippy.log.
- Stack-wide paragraph: gate.md l.29-40 verbatim; hunt line gate.md l.41 and tasks/bench7/orch-top-e2e-500e21afa.log l.8 ("order hold long hunt: cases=100000 seed=1223617546: no schedule breaks the rule").

## Figures
- Bench 6 run ids: run 2 = r20261113-1351 always-on, run 3 = r20261113-2118 adaptive: R l.141, l.23; gate.md l.13.
- Bench 6 gap resends outside 05: 29,449 / 104,168: R l.387, l.30 [V q2_senders a, b] [C Q2.01].
- Bench 6 nonce_too_high skips 13,036 / 52,588; bench 7 0 / 0: R l.30 [C Q2.06] (bench 6 cells are the comparison's, R l.19).
- Unlanded after tail scan outside 05: bench 6 0 / 9,290, bench 7 0 / 0: R l.388 [C Q2.08] [C Q2.09]; R l.30.
- 280-345 s, 31 of 31 (r20261113-1351), 124 of 124 (r20261113-2118): R l.396 [V q3_hold a, b].
- Bench 7: no gap resend / unlanded outside 05 in blast 2: R l.391 [C Q2.01] [C Q2.08] [C Q2.10].
- Lost own headers on all nine others: R l.392 [V q2_senders a, b]. 981 not certified / 293 certified never committed (7a): R l.393-394 [7a A7 lost_kinds.by_window.B2.fleet]; 7b without 05: 988 / 338: R l.395 [V q3_hold b]. "No gap resend followed": R l.396.
- Exception, blast 1 of 7a: 4 tx on generator 06, resend second 280-345 s after lost own header of validator-06: R l.402-403 [C Q2.14] [C Q2.15] [V q3_hold a]; 22 skips 2 per node on 11 nodes, 7b none: R l.404 [C Q2.06].
- Not separable, the quoted causes: R l.400 [V q3_hold.attribution]; R l.22.
- Out-of-order counter 0 both runs, no bench 6 twin: R l.398-399 [C Q3.49] [C Q3.50] [V q3_hold.attribution].
- Run facts (ten validators + observer, 20,000 IOPS, validator-05 killed by design, one run each; build 45dce8947, same node logic): gate.md l.13-14; R l.19.
- Cost table: headers held 1,866 / 3,259 [C Q3.36] R l.415; carried a batch 0 / 0 [C Q3.37] l.416; longest run 21 (before the kill) / 113 (after 05's start) [C Q3.39] l.417; 9.1 s / 55.3 s (after 05's start) [C Q3.40] l.418; blocker created fleet 2.46 / 3.13 % [C Q3.41] l.419 (a7a 2.4599..., b7b 3.1333..., key blocker_creation.by_window.B2.<NN>); validator-06 6.9 / 15.6 % [C Q3.43] l.420 (label "validator-06 (far)", key blocker_creation.by_window.B2.06.blocker_created_pct); certified share held 49.8 / 60.5 % [C Q3.61] l.421; rest 97.3 / 97.4 % [C Q3.62] l.422; over-quota 0 / 0 [C Q3.53] l.424 (sum over 11 nodes).
- Longest runs are validator-06's, 7a's two in different windows: R l.426 [C q3_hold.reading]. Association sentence: R l.428.
- One worker per validator, held header empty: tasks/bench7/review/06-digest-order-hold-report.md l.277.
- Early-trigger candidates 152 / 183 of 1,110 / 2,056 held headers on the digest trigger, inferred: R l.423, l.429 [C Q3.58]. Threshold 5, min header delay 350 ms: R l.430 [7a A7 early_trigger.fleet_parameters] [7b A7 early_trigger.read].
- Fleet-check cells: R l.432-435 [C q3_hold.fleet_checks] (7a validator-06 during 05's outage, 1 blocker, 0 held; 7b validator-05 blast 0, 18 blockers, 26 headers with blockers, nothing queued).
- Far validators 02 / 06: R l.503; all batch-carrying headers certified, 46-76 % never committed: R l.507 [V q3_far_validators B0/B1.bh_not_certified, bh_cnc_share]; median 50-61 rounds, 21.0-21.4 s in 7b: R l.508 [C Q3F.07, Q3F.08, Q3F.17, Q3F.18]; hold held none in light blasts: R l.536 [C Q3F.10, Q3F.20]; bench 6 same pattern blast 0: R l.505, l.536 [V q3_far_validators B0.bh_cnc_share].

## Added after the figure-check (tasks/pr-bodies/notes/bench6-06.figcheck.md: 93 items, 0 wrong, 4 weak; its four replacements applied verbatim)

- Run 7a's lost own headers carrying batches (981 not certified, 293 certified but never committed) include none of validator-05's: both runs' `A7/losses.json` `lost_kinds.by_window.B2.05` is 0 and 0 in r20261115-1131; `benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json` gives the same totals with or without validator-05.
