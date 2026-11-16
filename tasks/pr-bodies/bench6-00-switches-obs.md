## Summary

Adds three measurements the benchmark reads, and the list the later PRs of this stack put their runtime switches into, with a `node switches` log line and a `tn_node_switch` gauge that show them.
{{pr-09}}, the last PR of the stack, removes the switch list, the line and the gauge again, together with the six switches the later PRs add, and makes each change behind those switches the node's behaviour.
So once the stack is collapsed into #1862, `main` receives the three measurements and the stack's fixes, and none of the switch machinery.
In this PR's diff a switch is a top-level `parameters.yaml` key whose default is main's behaviour; at its default it is not written, so written files stay as on main.
This PR alone defines no switch and changes nothing a node sends, accepts, decides or stores; the collapsed #1862 carries the later PRs' behaviour changes to `main`.

PR 1 of 9 in the stack #1862 to {{pr-09}}; this PR targets `main` (its base is main at 33b727fce), and each later PR targets the branch of the one before it, so every Files tab shows one change alone (12 commits here).
The stack will be collapsed into #1862 (each PR merged into the branch below it); `main` is then merged into that branch and `make attest` runs on the result.

## Problem

Four benchmark runs of the node (bench 6: [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/), [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/), [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/)) tested fixes behind runtime switches.
This stack carries what carries to main.
In the PRs' own diffs each behaviour change sits behind a switch whose default is main's behaviour, except the closing-block check, the epoch-loop fix and one eviction rule of the collector hardening, which have none.
Bench 7 ran the node logic of the author-side vote fix (#1868) and the order hold (#1869) on the stack's earlier cut on main at 45dce8947, once per form of the vote fix: always-on in [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/), adaptive in [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/); #1868 and #1869 report the results.
{{pr-09}} then removes the six switches, so each fix is the node's behaviour, and of the two forms of #1868's fix it keeps only always-on.

On main at 33b727fce, `Parameters` (`crates/config/src/node.rs:273-274`) does not deny unknown fields, so a mistyped switch key is ignored without an error and nothing shows which arm a node runs.
A plain new field would also be written into every ceremony's `parameters.yaml` and the next regenerated mainnet preset.

Three measurements were missing on main:
- The engine's stage histograms (`tn_engine_{recover,evm,root,finish}_seconds`, #1813) and #1834's per-block ones use the `_seconds` layout, whose first bound is 5 ms (`crates/tn-metrics/src/recorder.rs:18-19`, `:170`).
  Bench 5 ([r20261107-1504](https://benchmark.telcoin.network/runs/r20261107-1504/)) measured evm 26.5, root 49.2 and finish 11.4 µs per transaction at saturation, so at light load every lap lands in the first bucket.
- A re-queued digest's wait restarts at the re-queue (`crates/consensus/primary/src/proposer.rs:842`, `:1384-1385`), so `tn_primary_digest_wait_seconds` under-reports the digests that waited longest.
  A review note on #1819 raised it.
- `behind_consensus` (`crates/consensus/primary/src/network/handler.rs:353-358`) demotes a node still executing the previous epoch once a new-epoch certificate passes the activity window (40 rounds at a `gc_depth` of 50), and nothing exports how close a node came.
  In r20261107-1504 one validator entered an epoch about one round inside it.

## Change

Four of the twelve commits build the switch list, the `node switches` line and the `tn_node_switch` gauge (`8bbc4a009`, `d1cd20992`, `8093e1030`, `676692c6c`); {{pr-09}} removes what they add, with their tests, except two tests of `8bbc4a009` that pin main's parsing and stay: `reserializing_keeps_the_existing_keys` and `unknown_keys_are_ignored`.
The other eight, the observability, stay.

- `8bbc4a009` feat(config): list the runtime switches in Parameters.
  `runtime_switches!` generates `Parameters::switches()` from one list of field names; a topic adds its field, default and entry between marker lines.
  `switches_list_every_switch_field` fails while a field is in neither the list nor `NON_SWITCH_KEYS`.
- `d1cd20992` feat(config): leave switches at their default out of a written parameters.yaml.
  `Parameters::switch_at_default` is every switch's `skip_serializing_if`; an absent key reads as the default.
- `8093e1030` feat(node): log the node switches line and export tn_node_switch gauges.
  `EpochManager::new` logs one INFO event (target `node::switches`, a `key=value` field per switch) and sets `tn_node_switch{name}` (0/1, a count, a duration in ms).
- `341747929` feat(primary): gauge how far behind a node enters an epoch.
  `tn_primary_epoch_entry_rounds_behind` is the highest round of a verified certificate from the epoch after the executed one; `behind_consensus` decides as before.
- `42655214d` fix(metrics): give the execution stage histograms sub-millisecond buckets.
  Ten histograms take `SUB_MS_SECONDS_BUCKETS`, keeping every old bound.
- `dffa19ccd` fix(primary): keep a digest's first receipt across a re-queue.
  The proposer holds each drained digest's `first_received` stamp and hands it back on a re-queue; `header proposed` gains `oldest_requeue_wait_ms`.
  Header payload and digest order are unchanged.
- `59d5db11a` fix(primary): keep the epoch-entry gauge across a mode change.
  A mode change rebuilds the request handler, which zeroed the gauge; the running max over `(epoch, round)` now sits in a process-wide static, so a rebuilt handler of the same epoch keeps it and a later epoch replaces it.
- `26319d169` docs(primary): say what a digest reported twice does to its first receipt.
  Both copies share one stamp; the first header to commit or re-queue takes it.
- `4917efaae` test(primary): pin the epoch-entry gauge's max over epoch and round.
- `3fbfa7428` docs(primary): say the epoch-entry gauge can pass the window by a few rounds.
  Certificates checked side by side can raise it a few rounds past the window before the demotion takes effect.
- `676692c6c` test(config): say behaviour switches never go into NON_SWITCH_KEYS.
  The list's doc says so, since the test cannot tell a behaviour switch from a plain parameter.
- `b29d59bef` fix(primary): keep the epoch-entry gauge's max on the bus, not in a static.
  The max moves from the process-wide static to a `#[metric(skip)]` field of `PrimaryMetrics`, one per bus, so tests sharing a process no longer share it.

## What changes for every node

There is no switch, so all of this runs everywhere; none of it touches a header, vote, certificate, batch, database write or decision.
- `Parameters` keeps main's fields, serde attributes and `Default` (only comments added): every existing `parameters.yaml` reads the same, and a written one is byte-identical.
- At start, in this PR's diff: the bare `node switches` line, and `tn_node_switch` has no series yet; after {{pr-09}} neither exists.
- Each `RequestHandler::new`, and `behind_consensus` for a verified next-epoch certificate only, take a `parking_lot` mutex for a compare and a gauge set, never across an `.await`.
- The proposer reads one `Instant::now()` per header and keeps a stamp map filled only from its own worker's digests, dropped with the proposer at each epoch.
  `header proposed` gains `oldest_requeue_wait_ms` between `requeued` and `pending_before`.
- `tn_primary_digest_wait_seconds` keeps its name and measures from the first receipt.
- The ten histograms gain `le` 0.0001, 0.00025, 0.0005, 0.001 and 0.0025; no metric name or label changes.

A mixed fleet is one chain: `Parameters` is never sent, hashed or encoded, and the stamps never reach a header, so a node on this head and one on main exchange identical messages.
The collapsed stack does change what a node sends and decides, and no switch turns that off after {{pr-09}}: a reviewer checks the later PRs' changes as unconditional.
For a fleet of old and new binaries the evidence is the rolling-upgrade test with main as the previous binary, which ran on the full stack with every switch off and with the six on (below), the author's rule there in its adaptive form, which {{pr-09}} deletes; #1868's limits say what that test does not cover; no test of it is added (see the limits of {{pr-09}}).

## Testing

Pinned by `switch_at_default_is_not_written`, `reserializing_keeps_the_existing_keys` (the mainnet and adiri presets round-trip), `node_switches_line_renders_yaml_tokens`, `test_engine_stage_histograms_render_sub_ms_buckets`, `epoch_entry_gauge_records_rounds_behind` and `test_requeued_digest_reports_its_wait_from_first_receipt`.
{{pr-09}} deletes `switch_at_default_is_not_written` and `node_switches_line_renders_yaml_tokens` with the code they pin; the other four stay.

On main at 33b727fce, at `17327280d` (the tip of `fix/1804-vote-queue`, #1864, which contains this head's twelve commits):
- `cargo check --locked --workspace --all-targets`, warnings denied: clean.
- `cargo nextest run --locked --no-fail-fast -p tn-config -p tn-types -p tn-node -p tn-primary -p tn-network-libp2p`: 1,825 passed, 9 skipped.

On the stack's earlier cut on main at 45dce8947 (the same twelve commits before the move; only the context of one test-module hunk differs):
- `cargo +nightly-2026-03-20 fmt --all -- --check` and clippy with `-D warnings` over tn-config, tn-types, tn-node and tn-primary: clean.
- `cargo test --locked -p tn-primary --no-fail-fast`, three times: the epoch-entry test passed each run; the same 25 fork-pin tests failed each run, as the Makefile's `test-cargo` note says they do outside nextest.
- On its first nine commits, `cargo nextest run --locked --no-fail-fast -p tn-config -p tn-types -p tn-node -p tn-primary -p tn-metrics`: 1,207 passed.

Not run: e2e tests (none added) and a fleet.
Bench 6 ran its own versions of these commits on a base older than #1834; this form has not run on a fleet.

Stack-wide gates ran before these PRs were opened, on the top of the full stack: `fix/1807-digest-order-hold` at `500e21afa`, 103 commits on main at 33b727fce, carries the code of all eight pull requests (#1862 to #1869).
- `cargo +nightly-2026-03-20 fmt --all -- --check`: clean.
- `./etc/ci-lanes.sh clippy`: passed.
- `cargo nextest run --locked --workspace`: 5,624 passed, 149 skipped.
- Every one of the 103 commits compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied).
- `make test-restarts` 11/11, `make test-epochs` 11/11, `make test-sigkill` 12/12 and `make test-e2e-resync` 1/1, once with every switch off and once with the full stack's six switches on.
- `make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time): passed with every switch off and with the six on.
- The 13 e2e tests the full stack adds, three runs each: all passed.
- The three `state_export_import` tests, which restore a node from an exported state: passed.
- Against a later main, c1b1eb9fe (#1859): the top merges without conflict, and the merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-storage` (1,764 passed, 21 skipped).
- Against the main of 2026-11-16, 0554efd4f (#1861): one file conflicts, `crates/node/src/manager/epoch_votes.rs`. #1861 renamed the collector's failure channel and ends a vote round on a forked record with an error; #1866 added the kept signatures to the same functions. In a local trial merge both changes are kept, the drop of a forked record's kept signatures moves in front of #1861's early return, and one test of #1866 expects the fork as an error. The merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-types -p tn-reth -p telcoin-network-cli` (2,175 passed, 17 skipped). The merge itself is made after the stack is collapsed.

## Limits and what a reviewer should look at

- In this PR's diff no switch is defined, so the line is bare; the first switch comes with `fix/1804-vote-queue`.
  {{pr-09}} removes the list, the line and the gauge with the six switches, so the collapsed #1862 brings none of them to `main`.
- Every new `Parameters` field fails `switches_list_every_switch_field` until it is listed; the test cannot tell a behaviour switch filed under `NON_SWITCH_KEYS`, so a reviewer of any addition there has to.
  This holds only inside the stack: {{pr-09}} deletes the test with the list.
- An unknown key is still ignored without a warning, as on main (now pinned by `unknown_keys_are_ignored`).
  After {{pr-09}} this covers the six removed keys: a `parameters.yaml` that still names one loads, and the key is ignored.
- After {{pr-09}}, `Parameters` has the same fields and `Default` values as `main` at 0554efd4f, so the collapsed stack adds no parameter.
- `tn_primary_digest_wait_seconds` changed meaning without a rename; on the ten stage histograms a `rate()` window spanning the upgrade sees the five new `le` series start at zero.
- The epoch-entry gauge can read a few rounds high on a demoting epoch; nothing depends on it.

No fix is pending before merge.

## Related

Only this PR of the stack merges into `main`, so this list closes the stack's issues.
Fixes #1851: the closing-block check (#1865); its e2e verification, the markers checked on chain, is in the epoch-close tests #1868 adds.
Fixes #1852: every point of its sketch, including its open question: the gauge reports the held certificate's signers (#1866).
Fixes #1860: both parts of its proposed fix, and its reproducing test passes (#1867).
Refs #1804: both sides are the node's behaviour after {{pr-09}}, the voter's (#1864) and the author's in its always-on form (#1868); left open: the depth of the floor of 8, which the executors' spread outgrew at 50,000 IOPS in bench 6, and the wait for a pending parent that #1842 put under the vote lock, which #1864 does not move.
Refs #1807: the own-chain order hold (#1869) is the node's behaviour after {{pr-09}}; left open: the issue's second defect, a resend that executes beside the original because a sealed transaction is invisible to the pool and the RPC, which the hold does not touch, and why some re-queued batches never executed.
Refs #1850: the walk past an uncertified epoch and the re-certify round (#1866) are the node's behaviour after {{pr-09}}, and its conflicting-record case was fixed on main by #1849; left open: the question in its comment, whether that stop should need a super-quorum of the full committee; a node without its own record of the epoch still needs re-certification, and no fleet run of either change is reported (#1866).
Refs #1806: the epoch-entry gauge measures how late a member enters an epoch (this PR).
Refs #1819: its digest-wait histogram now counts across re-queues (this PR).
Refs #1782: the bounded execution wait, which #1864 moves in front of the author's vote lock.
Refs #1794: a held digest keeps its slot in #1794's bound until it commits (#1869).
Stacked on this: #1863 (`test/bench6-e2e-scaffold`), #1864 (`fix/1804-vote-queue`), #1865 (`fix/epoch-record-closing-block-check`), #1866 (`fix/epoch-record-collector-hardening`), #1867 (`fix/epoch-loop-output-drop`), #1868 (`fix/1804-quorum-exec-block`), #1869 (`fix/1807-digest-order-hold`) and {{pr-09}} (`refactor/remove-bench-switches`), which removes the six switches of #1864, #1866, #1868 and #1869 and the switch list this PR adds.

## What bench 6 measured that is not in this stack

Bench 6's build (`bench/bench6-2026-11` at `2df831e3c`) predates #1834; three of its switches do not carry to main and are not sent as pull requests.
Each configuration ran once.

- `mdbx_random_advice` (#1802) advised the MDBX mapping `MADV_RANDOM`; with it on, every node of r20261113-1351 and r20261113-1630 wrote single pages (1.156 to 1.193 device bytes per page byte on the validators at full load).
  Main runs MDBX only under the off-by-default `mdbx` feature, and tn-lmdb already advises `MADV_RANDOM` on Linux (`crates/tn-lmdb/src/env.rs:309-317`).
  What survives: at 20,000 IOPS the write count bound the rate (19,967 writes per second, 3.74 per executed transaction, r20261113-1351's load blast); tn-lmdb's writes per transaction are not measured yet.
- `epoch_record_state_check` compared a stored record's `final_state` with the node's closing block.
  Since #1834 main runs that check unconditionally (`crates/node/src/manager/node/close_epoch.rs:718-755`); a narrower gap remains: {{epoch-record-closing-block-check}}.
- `pipelined_persist` (#1800, closed) overlapped a persist with the next build, which #1834's parallel storage roots and output overlay rule out (`crates/tn-reth/src/env/output_overlay/parallel.rs:70-90`).
  What survives is {{execute-and-persist-in-series}}; the reference implementation stays on `bench/bench6-2026-11`.
