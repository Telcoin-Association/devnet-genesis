# R4b — finish unit R4: four proposer tests that ran without the hold

You continue unit R4. Read `tasks/bench8-agent-rules.md` ("Removal units (R1-R5)"; budget 35 tool calls, about 120 printed lines per call), the brief `tasks/bench8/briefs/r4.md`, and R4's checkpoint `tasks/checkpoint-bench8-R4.md` (site map, resume point). Your checkpoint: `tasks/checkpoint-bench8-R4b.md`.
Skills: `tn-rust-skills`, `tn-domain-consensus`, `tn-domain-worker`.
Worktree `/home/drtnarg/coding/telcoin/tn-b8-uc`, branch `refactor/remove-bench-switches`, tip dd21a50ef (R4's commit: `digest_order_hold` is gone, the hold is the proposer's only behaviour; fmt, check, clippy clean; nextest `-p tn-primary -p tn-config`: 759 passed, 4 failed).

## The four failing tests (`crates/consensus/primary/src/tests/proposer_tests.rs`; line numbers at dd21a50ef)

| test | line | got | expected by the test |
|---|---|---|---|
| `test_canceled_header_digests_ride_the_next_header` | `:1654` | `[]` | `[d3]` |
| `test_lane_sequence_survives_requeues` | about `:2678` | `[]` | `[digest 4]` |
| `test_proposer_stopped_reports_what_it_leaves` | about `:2984` | `[0,3,3,2,3,0]` | `[0,3,2,2,3,1]` |
| `test_requeues_that_keep_lane_order_count_nothing` | about `:2815` | second payload `[]` | `[digest 3]` |

They used the default proposer, which had no hold. Their scripts leave an own header uncertified or uncommitted and then build a newer header; without the hold the newer header carried a newer digest of the same worker lane, with the hold it carries none of that lane until the older header is committed or given up. That is the hold's rule (`crates/consensus/primary/src/order_hold.rs`, the module doc), and it is the node's behaviour now.

## The orchestrator's ruling

The proposer and the hold do not change. For EACH test, read its doc and its script and decide what it was written to pin:
1. **The chain break is incidental** (the test is about something else: the lane sequence numbers, the stop report's counts, the out-of-order counter staying at zero on an orderly re-queue): keep the subject and every assertion, and give the script an intact own chain so that nothing is held: build each header on its own previous certificate with the fixture helpers the order-hold tests use (`hold_parents`, `build_on`, `hold_fixture()`), as R4 suggests. Say which helper you used.
2. **The break is the subject** (what happens to a cancelled header's digests): then the hold's behaviour is what the test must pin. Assert it in full, in order: what the header built while the older one is pending carries (nothing of the held lane), what the cancel report does (the lane's digests come back in their original order, the lane is released), what the next header carries (the cancelled header's digests AND the newer one, in order). The test's name must stay true or be changed to say what it now pins.
3. Do not move a digest to another worker just to make a test pass, unless neither 1 nor 2 can express the test's subject; if you do, say why.
For every test write, in the checkpoint as you go and in the hand-back: which case it is, what changed, and one sentence a pull-request reader can use ("on `main` a header built while an own header was still uncertified carried newer digests of the same worker; now it carries none of that worker's digests until the older header is committed or given up").

Also, small, same commit or a second one:
- `crates/consensus/primary/src/order_hold.rs` near `:46-47` (invariant I3: "with the hold switched off, the drain is the base's…") and `:94-95` ("With the switch off, timing is the base's. With it on…"): the module doc still speaks of the switch. Rewrite those sentences to describe the behaviour (doc only; R4 left them because its brief said the file stays whole).
- `test_order_hold_holds_nothing_on_an_intact_own_chain`: R4 replaced its comparison with the no-hold drain by a list of the eight headers' payloads "derived by hand". Check the list against what the test's script submits (which digests, which lanes, the header size limits) and say in the hand-back how each of the eight follows from the script; if the list was copied from the test's own output, say so plainly.

## Commit, gates, hand back

One commit `test(primary): …` (the doc edit of `order_hold.rs` may ride in it or be a second `docs(primary): …`), compiling alone; body: per test, what it pins now; `Refs #1807`; last line `Topic: remove-bench-switches`.
Gates: check, fmt, clippy for `tn-primary`, `tn-config` and `e2e-tests` (check and clippy only); `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-config` must be green.
Hand back as the rules file says, plus the per-test table (case 1 / 2 / 3, what changed, the sentence for the pull request).
