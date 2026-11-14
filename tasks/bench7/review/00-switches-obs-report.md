# Review R-00: head 00 `feat/bench6-switches-obs` (unit PT-0)

Worktree `/home/drtnarg/coding/telcoin/tn-b7-pt0`, branch `b7/pt0`, diff `45dce8947..d8273bbe3` (9 commits, 9 files, +1098/−32).
Code review only (`tn-review`), no security evaluation, as the scope file asks.
Line numbers are at the tip d8273bbe3.
All four findings were checked independently against the code by a separate read-only verifier: 3 confirmed, 1 plausible, 0 refuted.

## Verdict: APPROVE WITH FOLLOW-UPS

Nothing in this head changes what a node sends, accepts, decides or stores.
With zero switches defined, `Parameters` is the same struct as on main (the only edits inside it are comments), so every existing `parameters.yaml` reads and writes as before.
The new runtime work is one info line, an empty gauge loop, one gauge kept under a process-wide lock, a stamp map in the proposer that feeds only a histogram and a log field, and a bucket layout for ten histograms.
The findings are one Low (a test that is flaky outside nextest) and three Info items; none blocks the benchmark image.

| # | Title | Severity | Status | Before image | Before upstream PR |
|---|---|---|---|---|---|
| F1 | The epoch-entry gauge test shares a process-wide static and does not skip itself outside nextest | Low | CONFIRMED | no | yes |
| F2 | The gauge doc says recording stops at the first round past the window; concurrent certificates can record more | Info | PLAUSIBLE | no | optional |
| F3 | The machinery lands with zero switches: a bare `node switches` line and an unused predicate upstream | Info | CONFIRMED | no | decide |
| F4 | The switch-list guard cannot catch a switch filed under `NON_SWITCH_KEYS` | Info | CONFIRMED | no | optional |

Known residuals not re-reported, none worse than stated: unknown keys in `parameters.yaml` are ignored without a warning (pre-existing, pinned by `unknown_keys_are_ignored`, `crates/config/src/node.rs:1410`); `tn_primary_digest_wait_seconds` changed meaning without a rename (documented at `crates/consensus/primary/src/metrics.rs:109-113`); a digest reported twice shares one stamp (now in the field doc, `proposer.rs:161-168`).

## Findings

### F1. The epoch-entry gauge test shares a process-wide static and does not skip itself outside nextest (Low, CONFIRMED)
- Where: `crates/consensus/primary/src/metrics.rs:35` (`EPOCH_ENTRY_ROUNDS_BEHIND`, never reset, only raised by `start_` at `:185-191` and `record_` at `:199-205`); the test `epoch_entry_gauge_records_rounds_behind` at `crates/consensus/primary/src/tests/network_tests.rs:5522`.
- Sequence under a single-process `cargo test` (the Makefile's `test-cargo` target):
  1. `test_consensus_result_*` (`network_tests.rs:3680`, `:3706`, `:3758`) build a `RequestHandler` at epoch 2, which sets the static to `(2, 0)`; or `rejoin_grace_does_not_hold_epoch_behind` calls `behind_consensus(1, 60, None)` on an active node (`:5355`), which records `(1, 60)`.
  2. The new test then calls `behind_consensus(1, 5, None)`. `(1, 5)` is below the recorded value, so `record_` sets nothing.
  3. `assert_eq!(gauge(), Some(5.0))` (`:5553`) fails.
- This happens whenever one of those tests ran earlier in the same process, so `--test-threads=1` does not help. Under nextest (the `make test` target and the unit's gates) each test has its own process and the test passes.
- Impact: test only. The crate's fork-pin tests already fail under `cargo test` (`proposer_tests.rs:486`, `network_tests.rs:2509`), so `test-cargo` was not green for tn-primary before this head. The Makefile note at `:186-191` says some tests "skip themselves" outside nextest, but no such guard exists in the Rust code (a grep for `NEXTEST` finds only the port-slot helpers in `crates/types/src/helpers.rs`), and the note does not name this test.
- Fix: at the top of the test, `if std::env::var_os("NEXTEST_RUN_ID").is_none() { eprintln!("skipped: needs nextest's process-per-test model"); return Ok(()); }`, and name the test in the Makefile note. The cleaner fix is to keep the `(epoch, round)` state on the app-lifetime bus next to the gauge instead of in a static; the unit kept it out of `consensus_bus.rs` because no unit owns that file.
- Before the image: no. Before the upstream PR: yes, at least the skip.

### F2. The gauge doc says recording stops at the first round past the window (Info, PLAUSIBLE)
- Where: `crates/consensus/primary/src/metrics.rs:163-164`; `crates/consensus/primary/src/network/handler.rs:301`, `:306-311`, `:364`, `:451`.
- `behind_consensus` checks `is_active_cvv` (`:301`), awaits the last executed block (`:306-311`), records (`:364`), and switches the mode to `CvvInactive` only at `:451`. Two certificates checked at the same time can both pass the check and both record a round past the window, so the gauge can end a few rounds above `window + 1`. The static's own doc (`metrics.rs:33-34`) already expects certificates "checked side by side". The verifier could not confirm that the gossip loop runs the handler in separate tasks (outside its read list), so this stays plausible.
- Impact: the gauge reads a little high on the demoting epoch only; no behaviour depends on it.
- Fix: reword to "recording stops once the demotion fires; certificates already being checked can still raise it a few rounds past the window".
- Before the image: no. Before the upstream PR: optional.

### F3. The machinery lands with zero switches (Info, CONFIRMED)
- Where: `crates/config/src/node.rs:628-632` (empty `runtime_switches!`), `:605-607`, `:617-623`, `:581`; `crates/node/src/manager/node.rs:771-773`; `crates/node/src/metrics.rs:65-69`.
- At this tip `switches()` is an empty `vec![]`, every start logs the field-less INFO event `node switches`, `record_node_switches` registers nothing, and `switch_at_default` has no non-test caller. This is the intended state of PR 00 in the stack (the doc at `node.rs:615-616` says so) and it is inert.
- Fix: none inside the stack. If PR 00 goes upstream on its own, say in its body that the first switch arrives with PR 01 and later, or merge it with the first switch's PR.
- Before the image: no. Before the upstream PR: decide.

### F4. The switch-list guard cannot catch a switch filed under `NON_SWITCH_KEYS` (Info, CONFIRMED)
- Where: `crates/config/src/node.rs:1150` (`NON_SWITCH_KEYS`), `:1233-1265` (`switches_list_every_switch_field`).
- Sequence: a later topic adds `pub my_switch: bool` with `#[serde(default)]` and no `skip_serializing_if`, and names it in `NON_SWITCH_KEYS` instead of `runtime_switches!`. It drops out of the switch comparison (`:1249-1252`), it is written by default and is also in the plain set (`:1264`), and no other test iterates anything but `switches()`. Every test passes, the switch is missing from the `node switches` line and the gauge, and the genesis ceremony now writes its key.
- Every structural mistake does fail (see 2g question 5). Whether a field is a behaviour switch is a matter of meaning, which no structural test can decide.
- Fix: a comment on `NON_SWITCH_KEYS` saying behaviour switches never go there, and a review rule for every topic that touches `Parameters`: a new key in `NON_SWITCH_KEYS` needs a reason. Upstream will also see every new plain `Parameters` field fail this test until it is added to the list; that is the guard working, but say so in the PR body.
- Before the image: no. Before the upstream PR: optional.

## Answers to 2a-2g

### 2a. Switch off = before (here: what changed for every node)
There is no switch, so every line below runs on every node.
None of them changes a header, vote, certificate, batch, the database or a decision.
- `crates/config/src/node.rs:324-329` and `:431-432`: comment lines inside `pub struct Parameters` and `impl Default for Parameters`. No field, attribute or derive changed, so serde reads and writes `Parameters` exactly as on main.
- `crates/node/src/manager/node.rs:771-773`, once per process in `EpochManager::new`: `log_switches()` emits one INFO event on target `node::switches` whose message is `node switches` and which has no fields; `record_node_switches(&[])` loops over nothing and registers no series. The recorder is installed before this (`crates/telcoin-network-cli/src/node.rs:280`, then `crates/node/src/lib.rs:84`), so later switches' gauges will not be lost.
- `crates/consensus/primary/src/network/handler.rs:248-250`: every `RequestHandler::new` (once per epoch and per mode change) takes the `EPOCH_ENTRY_ROUNDS_BEHIND` lock and may set the new gauge to zero.
- `handler.rs:364`: in `behind_consensus`, on the branch for a verified certificate of the epoch after the executed one (`number == None`, `exec_epoch + 1 == epoch`), the lock is taken and the gauge may be raised. The return value `round > gc_depth.max(6)` on the next line is unchanged.
- `crates/consensus/primary/src/metrics.rs:166`: the `#[derive(Metrics)]` struct registers `tn_primary_epoch_entry_rounds_behind`.
- `crates/consensus/primary/src/proposer.rs`: `first_received` is set beside `received` (`:66-73`); `drain_digests_for_header` inserts one stamp per drained digest (`:1053-1058`) after the digests are chosen, so the order and set it returns are the same; the commit path removes stamps (`:866-869`); `push_payload` takes them back (`:1459`); `propose_header` reads one `Instant::now()` (`:414`), records the histogram from the first receipt (`:420-423`) and adds the log field `oldest_requeue_wait_ms` (`:444`). The header payload is still `digests.iter().map(|m| (m.digest, m.worker_id))` (`:404`).
- `crates/tn-metrics/src/recorder.rs:51-62`, `:234-236`: ten `Matcher::Full` bucket overrides. Exposition only.

### 2b. Mixed fleet
Nothing here can split the fleet.
`Parameters` is read from YAML and never sent, hashed or binary-encoded (grep for `Parameters` with encode, bcs, bincode, to_bytes or hash outside tests finds nothing), and its serde form is unchanged.
The proposer change never reaches the header (`proposer.rs:404`); the gauges and the log line are local.
A node running this head and a node running main exchange identical messages.

### 2c. Liveness
Nothing waits on the new state.
The stamp map is written and read only for the histogram and the log line; `drain_digests_for_header` returns the same digests in the same order as before.
The epoch-entry lock is held for a compare and a gauge set, never across an `.await`, and it is a `parking_lot` mutex, so it cannot poison.

### 2d. Byzantine or slow peers
No new exposure.
`proposed_first_received` is filled only from this node's own worker digests (`OurDigestMessage::process`, `proposer.rs:63-75`), so a peer cannot grow it; it holds at most the payloads of the headers already tracked in `proposed_headers` plus the one being built.
The epoch-entry gauge is fed only after `cert.verify_cert(&committee)` succeeds (`handler.rs:624-635`), so its round is quorum-certified; one faulty validator cannot push it.
At worst a peer that makes this node hit `behind_consensus` more often adds one uncontended lock per verified certificate.

### 2e. Restart and epoch boundary
- The stamp map lives in the `Proposer`, which `Primary` builds once per epoch (`crates/consensus/primary/src/primary.rs:109`), so it drops at every epoch change and on restart. A stored header re-proposed after a restart has no stamps; its re-queue falls back to `requeued_at`, as the doc at `proposer.rs:1445-1447` says.
- `EPOCH_ENTRY_ROUNDS_BEHIND` starts at `None` in each process. A handler for a later epoch than the recorded one resets it to `(epoch, 0)`; a handler rebuilt by a mode change in the same epoch keeps it (`metrics.rs:185-191`); the first handler of an epoch whose certificates the previous handler already saw keeps them. The max is over `(epoch, round)`, so an older epoch never overwrites a newer one (`:199-205`). This matches the doc and the test at `network_tests.rs:5522`.
- The `node switches` line and the switch gauges are set once per process; a switch can change only at restart.

### 2f. Determinism
None.
`Instant::now()` in the proposer feeds only the histogram and the log line; `created_at` still comes from `now_ms()`.
No new iteration order is observed: the stamp map is a `BTreeMap` read by key.

### 2g. The scope's questions
1. Yes. With zero switches the struct, its serde attributes and `Default` are main's (only comments changed, `node.rs:324-329`, `:431-432`), so a written `parameters.yaml` is byte-identical to main's and every existing file parses to the same value. Outside `Parameters`, the differences from main are exactly the bare `node switches` line, `tn_primary_epoch_entry_rounds_behind`, the bucket layout, the meaning of `tn_primary_digest_wait_seconds` and the new `oldest_requeue_wait_ms` field on the `header proposed` line. `reserializing_keeps_the_existing_keys` (`node.rs:1377`) runs a bench-5 file and the mainnet and adiri presets through a round trip.
2. It cannot poison: `parking_lot::Mutex` has no poisoning. It is not on a hot path: it is locked in `RequestHandler::new` and, per verified certificate, only on the next-epoch branch of `behind_consensus`, for a compare and a gauge set. Across an epoch change and a mode change it behaves as documented (2e). The one weak point is test isolation, F1. In-process multi-node tests share it, as they already share `MAX_CONSENSUS_OUTPUT_BYTES`; that affects only the gauge's value in such tests.
3. No leak across an epoch: the map dies with the per-epoch proposer. Inside an epoch a stamp leaves on commit (`:866-869`) or re-queue (`:1459`), and every path that removes a header from `proposed_headers` (`:865`, `:914`, `:971`) goes through one of them. A failed proposal ends `run()` with the drained stamps still in the map, but the task is gone with it. Nothing it stores is read on the path that decides a header's contents: `first_received` is read only at `:420` and `:428`.
4. No metric name and no label key changes. The `_bucket` series of the ten histograms gain five `le` values (0.0001, 0.00025, 0.0005, 0.001, 0.0025) and keep every old bound, so a query pinned to an old `le` still matches. All ten names exist on main (`crates/engine/src/metrics.rs` scope `tn_engine`, `crates/tn-reth/src/metrics.rs` scope `tn_reth`), and the per-output totals and persist laps keep the old layout (test at `recorder.rs` `test_engine_stage_histograms_render_sub_ms_buckets`). New names: `tn_primary_epoch_entry_rounds_behind`, and `tn_node_switch{name}` with no series yet.
5. It is enough for the mechanical mistakes: a field in neither list, a switch that forgets `skip_serializing_if` (the default would be written), a renamed or doubly listed switch, a list entry that names the wrong or a plain field, a missing serde `default` (an absent key would fail to parse in `absent_switch_keys_load_the_defaults`, `:1334`), and a `flatten` (the probe gets no field names and the `NON_SWITCH_KEYS` check fails). It cannot catch a behaviour switch that a later topic files under `NON_SWITCH_KEYS` instead of `runtime_switches!` (F4); that needs the topic's reviewer.

## What I did not examine
- Builds and tests: no cargo was run. I relied on the code and the unit's own gates on d8273bbe3 (check, fmt, clippy, nextest 1207 passed, listed in `tasks/checkpoint-bench7-PT-0.md`).
- The harness side: the parsers in `benchmark/` that read the `header proposed` line (it gains `oldest_requeue_wait_ms` between `requeued` and `pending_before`) and the `node switches` line, and whether the fleet's log filter lets INFO on target `node::switches` through.
- Dashboards that read the ten histograms across the bucket change; a `rate()` window spanning the restart sees the five new `le` series start from zero.
- Whether the gossip loop runs certificate checks in separate tasks (the open half of F2).
- Whether serde's generated field list includes `#[serde(alias)]` names; no switch uses an alias, and the API note forbids renames.
- Other topics of the stack and the security evaluation (not asked for).
