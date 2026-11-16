## Summary

Adds the list the later PRs of this stack put their runtime switches into, a `node switches` log line and `tn_node_switch` gauge that show them, and three measurements the benchmark reads.
A switch is a top-level `parameters.yaml` key whose default is main's behaviour; at its default it is not written, so written files stay as on main.
No switch is defined here, and nothing a node sends, accepts, decides or stores changes.

PR 1 of 8 in the stack #1862 to #1869; this PR targets `main` (its base is main at 33b727fce), and each later PR targets the branch of the one before it, so every Files tab shows one change alone (12 commits here).
The stack will be collapsed into #1862 (each PR merged into the branch below it); `main` is then merged into that branch and `make attest` runs on the result.

## Problem

Four benchmark runs of the node (bench 6: [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/), [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/), [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/)) tested fixes behind runtime switches.
This stack carries what carries to main: each behaviour change behind a switch whose default is main's behaviour, except the closing-block check, the epoch-loop fix and one eviction rule of the collector hardening, which have none; the vote fix and the order hold wait for the next benchmark.

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
- At start: the bare `node switches` line; `tn_node_switch` has no series yet.
- Each `RequestHandler::new`, and `behind_consensus` for a verified next-epoch certificate only, take a `parking_lot` mutex for a compare and a gauge set, never across an `.await`.
- The proposer reads one `Instant::now()` per header and keeps a stamp map filled only from its own worker's digests, dropped with the proposer at each epoch.
  `header proposed` gains `oldest_requeue_wait_ms` between `requeued` and `pending_before`.
- `tn_primary_digest_wait_seconds` keeps its name and measures from the first receipt.
- The ten histograms gain `le` 0.0001, 0.00025, 0.0005, 0.001 and 0.0025; no metric name or label changes.

A mixed fleet is one chain: `Parameters` is never sent, hashed or encoded, and the stamps never reach a header, so a node on this head and one on main exchange identical messages.

## Testing

Pinned by `switch_at_default_is_not_written`, `reserializing_keeps_the_existing_keys` (the mainnet and adiri presets round-trip), `node_switches_line_renders_yaml_tokens`, `test_engine_stage_histograms_render_sub_ms_buckets`, `epoch_entry_gauge_records_rounds_behind` and `test_requeued_digest_reports_its_wait_from_first_receipt`.

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

- No switch yet: the line is bare.
  The first switch comes with `fix/1804-vote-queue`.
- Every new `Parameters` field fails `switches_list_every_switch_field` until it is listed; the test cannot tell a behaviour switch filed under `NON_SWITCH_KEYS`, so a reviewer of any addition there has to.
- An unknown key is still ignored without a warning, as on main (now pinned by `unknown_keys_are_ignored`).
- `tn_primary_digest_wait_seconds` changed meaning without a rename; on the ten stage histograms a `rate()` window spanning the upgrade sees the five new `le` series start at zero.
- The epoch-entry gauge can read a few rounds high on a demoting epoch; nothing depends on it.

No fix is pending before merge.

## Related

Refs #1806: the epoch-entry gauge measures how late a member enters an epoch.
Refs #1819: its digest-wait histogram now counts across re-queues.
Stacked on this: #1863 (`test/bench6-e2e-scaffold`), #1864 (`fix/1804-vote-queue`, `vote_queue_fix`), #1865 (`fix/epoch-record-closing-block-check`, no switch), #1866 (`fix/epoch-record-collector-hardening`, two switches), #1867 (`fix/epoch-loop-output-drop`, no switch), #1868 (`fix/1804-quorum-exec-block`) and #1869 (`fix/1807-digest-order-hold`).

## What bench 6 measured that is not in this stack

Bench 6's build (`bench/bench6-2026-11` at `2df831e3c`) predates #1834; three of its switches do not carry to main and are not sent as pull requests.
Each configuration ran once.

- `mdbx_random_advice` (#1802) advised the MDBX mapping `MADV_RANDOM`; with it on, every node of r20261113-1351 and r20261113-1630 wrote single pages (1.156 to 1.193 device bytes per page byte on the validators at full load).
  Main runs MDBX only under the off-by-default `mdbx` feature, and tn-lmdb already advises `MADV_RANDOM` on Linux (`crates/tn-lmdb/src/env.rs:309-317`).
  What survives: at 20,000 IOPS the write count bound the rate (19,967 writes per second, 3.74 per executed transaction, r20261113-1351's load blast); tn-lmdb's writes per transaction are not measured yet.
- `epoch_record_state_check` compared a stored record's `final_state` with the node's closing block.
  Since #1834 main runs that check unconditionally (`crates/node/src/manager/node/close_epoch.rs:718-755`); a narrower gap remains: #1851.
- `pipelined_persist` (#1800, closed) overlapped a persist with the next build, which #1834's parallel storage roots and output overlay rule out (`crates/tn-reth/src/env/output_overlay/parallel.rs:70-90`).
  What survives is #1853; the reference implementation stays on `bench/bench6-2026-11`.
