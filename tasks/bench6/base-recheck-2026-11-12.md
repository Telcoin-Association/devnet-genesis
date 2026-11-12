# Bench 6 base re-check: what moved on `origin/main`, and what it means for the image and for upstreaming

Unit B1, written 2026-11-12 (UTC) from `/home/drtnarg/coding/telcoin/telcoin-network-b6` (read-only).
Revisions: integration head `80a0c76c0` (`bench/bench6-2026-11`), base `165e3fe01`, staging `514bf6687`, `origin/main` `6167184c0`, `origin/sls_storage_v2` `040a41b9f`, held stack `b6/pipe-stack-2` `d30bb1809`.
Main's last commit inside the base is `9aa1d6139`.

## 1. What moved

`git log 9aa1d6139..origin/main` holds six commits.
Two topics arrived: a primary-sync admission fix (a GitHub security advisory, merged from a private fork) plus a separate connection-reserve fix, and the tn-lmdb storage engine (#1759).

| commit | parents | what it does | crates touched |
|---|---|---|---|
| `dc9ae2c23` fix(primary): budget public-tier sync holds | `0ec59a363` | Ports the worker's per-key hold budgets to the primary sync responder (GHSA-jr9x-f54c-2qh5). A public (non-committee) key now pays for the opening read and for every serve class; missing-certificates and consensus-output serves get a 60 s public bound; the public epoch-pack bound becomes a fixed reservation unit. Committee keys keep their reserve and take no budget. | `consensus/primary` (network/mod.rs, sync_codec.rs), `consensus/worker` (network/handle.rs), `network-libp2p` (stream, sync/frame.rs, error.rs), `node` (manager) |
| `63b4e5f76` merge origin/main into the fix branch | `dc9ae2c23`, `9aa1d6139` | Brings main `9aa1d6139` into the fix branch; one doc conflict (`docs/src/network/sync-streams.md`). No new code of its own beyond the resolution. | (resolution only) |
| `b447d2291` Primary sync: lazy open, Deny(Busy), per-node hold books | `63b4e5f76` | Round-2 review of the same advisory. The outbound sync open becomes lazy (no zero-length confirmation read; the request frame travels with the protocol proposal). New wire reason `DenyReason::Busy` for per-peer cap and hold-budget refusals; requesters skip a Busy responder without a failure mark. `OpeningAdmission`/`SyncServePools` are built once per node (`PrimarySyncLedgers`, held by `EpochManager`) so an epoch start no longer refills budgets. | `consensus/primary`, `consensus/worker`, `network-libp2p` (stream/upgrade.rs, sync/frame.rs), `node` (manager/node.rs, start_epoch.rs), docs |
| `b14a2d4a4` Merge commit from fork | `9aa1d6139`, `b447d2291` | Lands the three commits above on main. Net vs `9aa1d6139`: 16 files, +2,053 / −399, about 1,880 of them in `crates/consensus/primary/src/network/mod.rs`. | as above |
| `967bbf959` Merge commit from fork | `b14a2d4a4` (single parent: a squash) | A different advisory (GHSA-8fvc-c993-83jq), not part of the primary-sync fix: peers without privilege share only `total - total*50/128` of the swarm's established-connection cap (78 of 128 by default) and at most 2 connections each; committee and admission-privileged peers never consume that share. New `peers/public_share.rs`, a labelled `PeerAdmissionDenied::PublicShare` denial, and network-budget tool updates. | `network-libp2p` (peers/*, consensus.rs, metrics.rs), `config` (network.rs), `tools/network-budget`, docs |
| `6167184c0` TN-owned storage engine for the reth execution database (#1759) | `967bbf959` | Adds the tn-lmdb engine (`crates/tn-lmdb`), reth's db-api on it (`crates/tn-lmdb-reth`), a bench crate, an MDBX-to-tn-lmdb migration, the execution bench (`crates/engine/tests/exec_bench`), CI lanes, and six per-block timing histograms in `tn-reth`. 158 files, +106,916 / −215; most of it is the two new crates and tests. | new `tn-lmdb`, `tn-lmdb-reth`, `tn-lmdb-bench`; `tn-reth`, `types` (task_manager.rs), `storage` (lib.rs, data_file.rs, tndb), `tn-metrics`, `node` (one doc line), `consensus/primary` and `network-libp2p` (clippy and doc touch-ups on the sync fix), `telcoin-network-cli`, `engine` (dev-deps and a test bench), CI |

The brief's list calls `967bbf959` part of the primary-sync fix; it is a separate fix (connection-slot reserve), merged the same way.
The PR title and body of #1759 still say `tndb-b`; the merged code names the feature, crates and file `tn-lmdb` (`tn-lmdb`, `tn-lmdb-reth`, `tn-lmdb.dat`).
`git grep tndb-b origin/main` finds no manifest or code use of that name.

### Which features a deployed image builds

On `origin/main`, `etc/Dockerfile` is unchanged by these commits: `ARG CARGO_FEATURES=` (empty) and `cargo build -p telcoin-network --bin telcoin-network --release --locked ${CARGO_FEATURES:+--features ${CARGO_FEATURES}}`.
`make docker-devnet` passes `CARGO_FEATURES=faucet`, `make docker-adiri` passes `adiri`.
The new `tn-lmdb` feature is in no default set: `bin/telcoin-network`, `tn-node` and `telcoin-network-cli` have no `default` key, `tn-reth` has `default = []`, and `tn-storage` keeps `default = ["reth-libmdbx"]` (unchanged).
So every image built as `etc/Dockerfile` builds it runs reth on MDBX, through the same libmdbx; `vendor/` is untouched by all six commits.
The PR body says the same: "The default build is unchanged and still runs MDBX."

### #1759 on the default build, hunk by hunk

Only the files the brief names, plus the other non-test files #1759 touches outside the new crates.

| file | hunk outside a feature gate | behaviour / timing / persist path on the default build |
|---|---|---|
| `tn-reth/src/env/execution.rs` | `Instant::now()` at four stage boundaries of `build_block_from_batch_payload` and five `RETH_METRICS.block_*_seconds.record(...)` calls (execute, signer recovery, finish, overlay extend); a `#[cfg(test)]` test. | Timing only: about five clock reads and five cached-handle histogram records per block. No change to block contents or to the persist function. New series `tn_reth.block_{execute,signer_recovery,finish,hashed_state,state_root,overlay_extend}_seconds`. This file conflicts with bench-6 (section 3). |
| `tn-reth/src/env/output_overlay.rs` | `hashed_post_state` and `state_root_with_updates` of `OverlayRootStateProvider` are wrapped in a timer; the read-only provider is now dropped inside an inner block before the histogram record. | Timing only; same calls in the same order. The staging tree already times the same spans per output (`135e2cae0`, `Topic: exec-split`: `tn_engine_{recover,evm,root,finish}_seconds`, bucketed by bench-6's U8), see section 3. |
| `tn-reth/src/env/mod.rs` | `new_database` calls `database::open_rw` instead of `init_db(...).with_metrics()`; log line gains `backend = "MDBX"`; `init_provider_factory` takes `RethDb` (the same `Arc<DatabaseEnv>` on this build); `#[cfg(test)] mod persist_bench`. | `open_rw` (MDBX build, `database.rs:119-126`) first runs `check_backend` (three `symlink_metadata` stats: refuse `tn-lmdb.dat`, refuse the `mdbx-migrated` marker, warn on a `tn-lmdb-migrating/` directory), then calls the same `reth_db::init_db(path, args)?.with_metrics()`, except that the page size is now passed explicitly as `--db.page-size` or `default_page_size()` = OS page clamped to 4 KiB..64 KiB. On x86-64 Linux that is 4 KiB, reth's own default, and an existing file keeps its creation page size. No change for a fresh or existing devnet datadir. |
| `tn-reth/src/env/genesis.rs` | Temp-chain MDBX geometry moved into `database::temp_chain_db_args()` (same 2 GiB / 4 MiB). | Temp chains only (tests, genesis tooling). No change. |
| `tn-reth/src/env/rpc.rs` | The eth state cache is spawned by TN (`EthStateCache::spawn_with`) on `task_spawner.non_critical()` and passed to `EthApi::builder(...).task_spawner(rpc_tasks).eth_cache(...)`. | Behaviour: reth's RPC "critical" tasks (state cache, fee-history, tx batcher) are now tracked by TN's task manager as non-critical, so they end at node shutdown and their panic no longer goes unnoticed or ends the node. Same cache config. RPC-only; no effect on consensus, execution or persist. |
| `tn-reth/src/snapshot.rs` | Docs; the pinned tx type is `<RethDbEnv as Database>::TX` (MDBX's `Tx<RO>` on this build). | No change. |
| `tn-reth/src/metrics.rs` | Six `Histogram` fields on `RethEnvMetrics`; docs. | New series only; registered at `init()` like the counters. |
| `tn-reth/src/traits.rs`, `types.rs` | `NodeTypesWithDB::DB` and `RethDb` now alias `env::database::RethDb` (= `Arc<reth_db::DatabaseEnv>` without `tn-lmdb`). | No change. |
| `tn-reth/src/lib.rs` | Re-exports: drops `mdbx::{open_db_read_only, DatabaseArguments, Error}`, `DatabaseEnv`, `Tables`; adds `database::{db_check, db_table_stats, ...}`, `BlobSidecars`. | Compile surface only; any bench-6 code naming `tn_reth::DatabaseEnv` or `tn_reth::RethMdbxError` would stop compiling after a rebase (not checked beyond the conflict list). |
| `tn-reth/src/dirs.rs` | Doc line. | No change. |
| `types/src/task_manager.rs` | New `TaskManager::signal_shutdown()`, new `NonCriticalTaskSpawner` and `TaskSpawner::non_critical()`; tests. | Additive; the only production user is the rpc.rs hunk above. |
| `storage/src/lib.rs` | New `pub mod disk` re-exporting `fsync_file`, `fsync_directory`, `drop_cached_pages`, `available_bytes`. | Visibility only (`data_file.rs` and `tndb/layout.rs` make those `pub`). No change. This file conflicts with bench-6 (section 3). |
| `node/src/manager/node.rs` | One doc line ("Reth (MDBX) database handle" becomes "Reth database handle"). | No change. The node.rs conflict comes from the sync fix's `primary_sync_ledgers` field (`b447d2291`), not from #1759. |
| `consensus/primary/src/network/mod.rs` | `OpeningDecision::Admit(Box<SyncAdmission>)` and a clippy allow, on code the sync fix added. | No change in behaviour. |
| `network-libp2p/src/{consensus.rs,stream/mod.rs}` | Doc rewrap. | No change. |
| `tn-metrics/src/{lib.rs,recorder.rs}` | `install_recorder` now goes through a new `build_recorder()`; `PrometheusHandle` re-exported. | Same recorder, same prefix rule, same buckets. No change. |

Verdict for section 1: on the default build, #1759 changes no block, no consensus message and no persist step.
What it adds on that build is six per-block histograms (a few clock reads per block), a three-stat backend guard at database open, an explicit page size equal to the old default on x86-64, and RPC cache tasks moved onto TN's task manager.
None of that can move a bench-6 throughput or persist number by a measurable amount; the new histograms time, per block, the spans the staging tree's exec-split already times per output.

## 2. The primary-sync fix

Sources: the messages of `dc9ae2c23` and `b447d2291`, `git diff 80a0c76c0 origin/main` on `crates/network-libp2p/src/stream/upgrade.rs` and `crates/consensus/worker/src/network/handle.rs`, and `docs/src/network/sync-streams.md` on `origin/main` (lines 49-60, 127-210, 232).
The sync streams carry three primary serve classes (epoch pack, missing certificates, consensus output) and the worker batch exchange.
Votes, headers and certificate broadcast go over request-response and gossip, which these commits do not touch.

What changes, split by who it reaches:

- Public-tier only (a peer whose BLS key is in neither the current nor the next committee, `sync-streams.md:148`): the opening-read hold budget (10 s per 300 s), one serve per key per primary across the three classes, per-class serve hold budgets (200 s per 1000 s for packs, 60 s per 300 s for certificates and output), the 60 s bound on certificate and output serves, ledgers that survive an epoch change, and no same-walk re-probe of a cut peer. The docs say it twice: "A committee key takes no serve cap and no hold budget" (`:154`) and "Committee peers are not charged by admission" (`:181`). `dc9ae2c23`'s message: "validator catch-up is unchanged".
- Every requester, committee included: the lazy outbound open (`b447d2291`). On the bench-6 head `upgrade_outbound` does a zero-length `stream.read(&mut [])` that waits for the listener to confirm the protocol, so every sync stream open costs one round trip before the request frame leaves; on main the stream is returned at once and the request travels with the protocol proposal. Main saves one RTT per sync stream open.
- Every requester: the per-peer cap of two in-flight streams (which also binds committee keys) now answers `Deny(Busy)` on a primary instead of `Deny(AtCapacity)`, and a requester skips a Busy responder for the rest of the walk without a failure mark; on the bench-6 head the same refusal is `AtCapacity` (`80a0c76c0:crates/consensus/primary/src/network/mod.rs:732`, `:2746`). This changes which peer the next attempt goes to, not whether it fails.
- `967bbf959` (the connection reserve): peers without privilege share 78 of 128 established connections and hold at most two each. In a ten-validator fleet with a few non-committee nodes that bound is far from binding, and committee peers never consume the share. One subtlety from its message: "A peer counts as public until its record is known"; a restarted validator whose record a peer does not yet hold is public for that window, capped at two connections to that peer, which is what a validator uses anyway.

A healthy ten-validator fleet under load: the budgets never fire (all requesters are committee).
The lazy open matters only where a validator opens sync streams during steady state: worker batch fetches for batches that did not arrive by broadcast, and primary missing-certificate or consensus-output fetches by a validator that fell behind.
Bench 5's far validators (Sydney-class RTT) are the ones that fetch, so on main their fetches would finish about one RTT sooner each.
I cannot count how many stream opens a bench-5 validator made per minute from the code; the bench-5 logs would say (`primary::network` / worker fetch lines), and that is outside this unit's read list.

The validator that run 2 kills and restarts: it is a committee key, so the budgets and caps do not reach it, and committee requesters keep the same-walk re-probe.
What reaches it is the lazy open (one RTT less per epoch-pack, consensus-output, certificate or batch stream it opens while catching up) and the Busy handling at the per-peer cap.
The catch-up time measured in run 2 could therefore be shorter on main by roughly (number of sync stream opens during catch-up) × (RTT to the chosen peer); for a short outage within one epoch that is a handful to a few dozen opens, so seconds at most, against a catch-up that is dominated by fetching and executing the missed outputs.

Non-committee nodes in the fleet (an observer or RPC node that syncs over the primary streams, if bench 6 runs one) are the only ones the budgets would meter.
Following the chain by gossip uses no serve permit; a long catch-up of such a node over consensus-output streams would be cut at 60 s per serve and 60 s per 300 s per class on main, and is not on the bench-6 image.

Verdict for section 2: the fix is a defence against hostile public peers; for committee traffic it changes one thing that can move a number, the lazy open, worth one RTT per sync stream open.
Its absence from the bench-6 image keeps bench 6 on the same open as its base: `git diff 9aa1d6139 80a0c76c0 -- crates/network-libp2p/src/stream/upgrade.rs` is empty, and the zero-length read dates from #1783 (`7527b15c0`, V1Lazy), which bench 4 and bench 5 already ran; I did not diff bench 5's image sha itself.
It cannot change throughput, commit latency or persist numbers of a healthy fleet; it can shave seconds off run 2's catch-up and a fraction of a second off each far-validator fetch.

## 3. The conflicts

`git merge-tree --write-tree 80a0c76c0 origin/main` (tree `61c720291`, exit 1) reports six conflicted files, not five: `.config/nextest.toml` is the sixth.
Everything else auto-merges, including `Cargo.lock`, `crates/tn-reth/src/env/{mod.rs,rpc.rs,lib.rs,metrics.rs}`, `crates/types/src/task_manager.rs`, `crates/consensus/worker/src/network/handle.rs` and `crates/node/src/manager/node/start_epoch.rs`.
The same trial on the two base PRs shows where each conflict comes from:

- `git merge-tree --name-only 514bf6687 origin/main` (staging, #1826): `storage/src/lib.rs`, `tn-reth/src/env/execution.rs`, `tn-reth/src/env/output_overlay.rs`.
- `git merge-tree --name-only 165e3fe01 origin/main` (the bench-6 base, #1827): the same three plus `.config/nextest.toml`.

So four of the six belong to the base PRs, which the other session is resolving now; only `crates/engine/Cargo.toml` and `crates/node/src/manager/node.rs` are new with bench-6, plus one extra line inside execution.rs's second region and about 145 extra lines inside its third.

| file | regions | bench-6 / base side (sha, `Topic:`) | main side | resolution |
|---|---|---|---|---|
| `.config/nextest.toml` | 1 (12 lines) | `0325b2a25` "test(nextest): end a hung tn-node test after five minutes" (base #1827, no Topic): a `ci` profile override for `package(tn-node)` | `6167184c0` (#1759): a `ci` override `package(tn-lmdb) \| package(tn-lmdb-reth)` with `retries = 0` | Mechanical: keep both blocks. |
| `crates/engine/Cargo.toml` | 1 (10 lines) | `5da405afa` "build(engine): add rayon, proptest and an engine_contention bench target" (`Topic: recovery-pool`): `proptest` dev-dep | `6167184c0`: dev-deps `serde`, `serde_json`, `tn-metrics`, `tn-storage`, `jsonrpsee`, `libc` for `tests/exec_bench` | Mechanical: union. `Cargo.lock` auto-merged textually; whether it passes `--locked` needs a cargo run, which this unit may not do. |
| `crates/storage/src/lib.rs` | 1 (16 lines) | `76724d72f` "fix(storage): keep the certificate rounds a rejoining validator rebuilds from" (staging #1826, no Topic): `pub use tn_types::{error::StoreError, ROUNDS_TO_KEEP};` | `6167184c0`: new `pub mod disk { ... }` above `pub use tn_types::error::StoreError;` | Mechanical: keep `pub mod disk` and the staging re-export line. |
| `crates/node/src/manager/node.rs` | 1 (10 lines, imports only) | `f22362090` "feat(reth): hand the mdbx_random_advice switch to RethEnv" (`Topic: mdbx-advice`): imports `RethSwitches` | `b447d2291` (sync fix): imports `PrimarySyncLedgers` | Mechanical: union of imports. The rest of bench-6's 245 added lines and main's `primary_sync_ledgers` field and `PrimaryNetwork::new` argument auto-merge. |
| `crates/tn-reth/src/env/output_overlay.rs` | 2 (25 lines) | `135e2cae0` "feat(engine): split execute_ms into recover/evm/root/finish per output" (staging, `Topic: exec-split`): `Cell`/`Duration` imports; the state root time added into `self.root_elapsed` (a per-output sum, recorded on error too) | `6167184c0`: the same span recorded per block into `RETH_METRICS.block_state_root_seconds`, success only, with the RO provider dropped in an inner block | Needs thought, small: one `Instant`, feed both sinks or drop one. Two timers on one span is a naming decision for upstream, not a code clash. |
| `crates/tn-reth/src/env/execution.rs` | 3 (865 lines) | Region 1 (imports) and region 2 (the transaction loop): `135e2cae0` exec-split moved signer recovery out of the block build into a per-output `recover_output_signers` and `build_block_from_recovered_payload`; bench-6's `8bc341967` "log the sender of a skipped invalid transaction" (`Topic: digest-dedupe`) adds the `sender` line inside that loop. Region 3 (end of file, ours 685 lines): the staging `OutputBuildScope`, `BlockBuildTimings`, `PersistedCounts` and tests, plus bench-6's `dddccd4a6` (`Topic: mdbx-advice`, per-persist storage counters, lines 831-874 and 1272-1344 of the head file) and `acd609838`/`082179d4d` (`Topic: pipelined-persist`, `OutputBuildScope::seeded`, lines 721-741 and 1235-1261). | Region 2: main keeps per-block recovery inside `build_block_from_batch_payload` and times it (`block_signer_recovery_seconds`), plus the five other stage timers. Region 3: main's 114-line test module asserting one sample per block in each of the six histograms. | Needs thought (staging-level, not a design clash). The code shapes are compatible: take the staging structure, then re-home main's six histograms. `block_signer_recovery_seconds` has no per-block home once recovery is per output (in production the engine recovers in `crates/engine/src/recovery.rs`, bench-6 `recovery-pool`), so it either becomes per-output or is dropped, and main's test changes with it. Bench-6's own lines in regions 2 and 3 are mechanical once the staging resolution exists. |

Conflicts that `merge-tree` cannot show (compile or CI, after a textual merge):

- `crates/tn-reth/src/env/mdbx_advice.rs` (bench-6, `Topic: mdbx-advice`) calls `RethDb::info()` / `stat()` and names `reth_db::mdbx::Info`. On main `RethDb` is `Arc<RethDbEnv>`, which is MDBX's `DatabaseEnv` only without `tn-lmdb`. The default build compiles; `--all-features` (bench-6's own clippy gate, main's `clippy`) and main's `tn-lmdb-test` CI lane (`.github/workflows/pr.yaml:494`, `etc/ci-lanes.sh test-tn-lmdb`) would not, unless the module, its `persisted output` fields and the `tn_reth_mdbx_*` gauges are gated `cfg(not(feature = "tn-lmdb"))` or moved behind `env/database.rs`, which #1759 makes the single home of backend differences. That is a design question for the upstream port.
- The held stack's pinned per-output read snapshot (`5472d5ee1`) is typed `<<TelcoinNode as NodeTypesWithDB>::DB as Database>::TX` (`d30bb1809:crates/tn-reth/src/env/output_overlay.rs:436`), so it is backend-neutral and survives `tn-lmdb` without change.

### The held stack

`git merge-tree --write-tree --name-only d30bb1809 origin/main` conflicts in the same six files.
`d30bb1809` is built on `d91d65d3e` (ledger row 73), not on `80a0c76c0`: 19 commits, 12 files, +7,099 / −115, mostly `crates/engine/src/{lib.rs,persister.rs,payload_builder.rs}` and its tests.

| file | regions | stack side (sha, `Topic:`) | resolution |
|---|---|---|---|
| `.config/nextest.toml`, `crates/engine/Cargo.toml`, `crates/storage/src/lib.rs`, `crates/node/src/manager/node.rs` | 1 each | the same base and bench-6 commits as above | Mechanical, as above. |
| `crates/tn-reth/src/env/execution.rs` | 2 (imports, the loop) | `135e2cae0` exec-split, `8bc341967` digest-dedupe; the end-of-file region auto-merges here | Needs thought, the same staging-level decision as above. |
| `crates/tn-reth/src/env/output_overlay.rs` | 5 | `135e2cae0` exec-split (imports) and `5472d5ee1` "feat(tn-reth): pin one read snapshot per output for the layered state root" (`Topic: pipelined-persist`): imports, two doc blocks, and the root call, which becomes `self.overlay.root_with_updates(self.blockchain_provider, hashed_state)` over the overlay's anchor (its pinned snapshot, or a fresh RO transaction) | Needs thought, small: keep the stack's call and wrap main's timer around it. Main's doc for `block_state_root_seconds` says it includes "opening and closing the read-only database transaction"; with a pinned snapshot there is no open per block, so the doc and the meaning of that histogram shift. |

No conflict on either branch is a design clash between a bench-6 topic and main.
The one real decision (the two timing designs for block build) belongs to the staging PR #1826 and is being made by the other session's merge now.

## 4. Storage direction

### The PR-level picture

PR states read with `gh pr view` at about 02:47Z:

| PR | state | mergeable | review | head |
|---|---|---|---|---|
| #1826 staging | open | CONFLICTING | APPROVED | `514bf6687` |
| #1827 review follow-ups | open | CONFLICTING | APPROVED | `165e3fe01` |
| #1829 vendored reth fixes | open, draft | CONFLICTING | REVIEW_REQUIRED | `91cb033bd` |
| #1834 storage v2 | open, draft | MERGEABLE | REVIEW_REQUIRED | `040a41b9f` |

`git merge-base origin/main origin/sls_storage_v2` is `6167184c0`, main's tip: storage v2 already sits on #1759 and merges cleanly.
Against main it is 183 files, +23,867 / −1,923 (the PR body: vendored reth 46 files +7,209 / −690; `crates/` 118 files +15,719 / −945, more than half tests, fixtures and benches).
The body calls it a "DRAFT for review before the 2026-11-16 code freeze".
What it does, from the body:

- tn-lmdb becomes the default reth backend; MDBX becomes an opt-in `mdbx` feature kept for one release (testnet migration, the previous binary in e2e), with no CI job (its `test-mdbx` lane runs by hand), and `etc/backend-gate.sh` keeps `mdbx` out of release graphs.
- New datadirs use reth's storage layout v2: change sets and senders go to static files, plain state is not written ("about 24% of commit pages"), tx hashes and history stay tables written inside the DB commit. Migrated datadirs keep v1.
- A cross-block execution cache (about 160 MiB), parallel storage roots (one rayon task per account with changed storage, each on its own read-only transaction), static-file checksums, gap fill (`--db.gap-fill`, default `auto` on Linux), and a boot record that keeps the page cache across a clean restart.
- Measured on "devbox-fleet: GCP c3-highcpu-8, 16 GB (the network benchmark's nodes), Hyperdisk Balanced 250 GB, 20,000 IOPS / 800 MiB/s": tn-lmdb v1 / MDBX v1 = 1.04 peak, 0.99 busy; tn-lmdb v2 / MDBX v1 = 0.81 peak, 0.77 busy (exec bench, mean ms per output); "On the fleet disk both engines write 85-89 MiB/s, and the disk is saturated during commits."

The sources below are `crates/tn-lmdb/README.md` at `origin/sls_storage_v2` (grepped, not read whole; copy in scratch), `crates/tn-reth/src/env/output_overlay/parallel.rs:3-64` there, and `git grep` for counters; nothing else of the 24k lines was read.

### What happens to each bench-6 storage topic if tn-lmdb becomes the default

The `mdbx_random_advice` switch (whole-map `MADV_RANDOM`, `Topic: mdbx-advice`):

- tn-lmdb still writes through a memory map and the kernel's page cache. "The file is mapped inside a reserved address range ... The OS page cache is the cache" (README:77-79). A commit dirties pages through the shared mapping and syncs them with one `msync(MS_SYNC)` or one `fdatasync` (README:536, step 4).
- So the whole-folio write amplification still applies to the engine class. The README describes that mechanism itself: "a page dirtied through a shared mapping writes back its whole folio. Measured on Linux 7.1, ext4, NVMe, as disk KiB written per 4 KiB page dirtied ... 439 for a file written by `write(2)` and still cached (what a copy leaves), 115 after a cold full sequential read with the default readahead, 4.2 after cold random reads with it, 4.0 with `MADV_RANDOM`" (README:2432-2445).
- The advice fix is already built in: on Linux tn-lmdb advises every mapping of the file `MADV_RANDOM` unless `EnvOptions::readahead` is set, which defaults to `false` on Linux (README:1299, 2092, 2432), and a writer open evicts a file that buffered writes left in large folios (README:2445).
- So on tn-lmdb the bench-6 switch, `MdbxAdvice` and the `tn_reth_mdbx_random_advice_bytes` gauge have no role. Upstream they matter only for MDBX's one remaining release, as an opt-in feature outside release graphs.
- What I cannot tell from the stat and the README grep: whether tn-lmdb has anything like MDBX's prefault writes and the lock-file bit that turns them off (the README grep finds no "prefault"); file growth is "each step preallocated" (README:2092).

The per-persist storage log fields (`persisted output` gains `page_newly` ... `gc_large_pages`, gauges `tn_reth_mdbx_used_bytes`, `tn_reth_mdbx_page_ops_total{op}`):

- Their source is libmdbx's environment info (`RethDb::info()` / `stat()`, `reth_db::mdbx::Info`, `80a0c76c0:crates/tn-reth/src/env/mdbx_advice.rs:56,114-221`). That source does not exist on tn-lmdb.
- tn-lmdb has its own: `TnLmdbEnv::io_stats()` returning `IoStats`, which `crates/tn-lmdb-reth/src/lib.rs:16` (v2) maps as the counterpart of "MDBX's `page_ops` in its environment info". Per commit step it counts `pages_synced`, `sync_runs` ("about the writes Linux sends the disk"), `msync_syncs`, `fdatasync_syncs`, `msync_span_pages` and the gap-fill counters (README:2165).
- On `sls_storage_v2` only the test-only `crates/tn-reth/src/env/persist_bench.rs` reads `IoStats`; the node path exports none of it per persist. v2 adds `take_static_file_sync_stats()` in `execution.rs` for the static-file syncs that layout v2 moves into the persist.
- Mapping: `page_newly + page_cow` roughly becomes `pages_synced`; `page_spill`, `page_unspill` and `page_prefault` have no counterpart that I found; `mdbx_used_bytes`, `mdbx_last_pgno` and `gc_*` would need the engine's catalog or free-list stats, which I did not look for. The fields would need re-sourcing and some renaming, and the amplification formula (device bytes ÷ dirtied pages × 4096) still has both inputs.

The pipelined persist stack (held, `b6/pipe-stack-2` `d30bb1809`):

- The split point still exists in v2. `parallel.rs:36-39`: "`execute_consensus_output` builds every block of an output before it persists them in line (`RethEnv::persist_executed_output`), so an output's persist ends before the next output's first root". v2 also adds a `persist_blocks` function and static-file syncs inside `save_blocks`.
- But two v2 features rely on persist never overlapping the next build. Parallel storage roots: "What would break it: persisting an output while the next one builds (a pipelined persist) ... Each task therefore checks its transaction's tip against the walk's ... On a mismatch the task fails and the walk computes that root on its own transaction" (`parallel.rs:45-49`). Under pipelining each task opens a fresh read-only transaction at the database tip while the stack's root reads a pinned snapshot plus the unpersisted outputs, so the tip check would fail on blocks where a commit lands mid-output and the parallel gain would be lost, or the tasks need to share the pinned snapshot.
- The execution cache is "anchored at the last built block's hash, refreshed from each block's bundle, and dropped on any failure" (#1834 body). The stack's rollback of unpersisted outputs would have to drop it too; I did not check whether the stack's failure path reaches the v2 drop.
- The output overlay's anchor ("its anchor is the database tip", `parallel.rs:43`) is exactly what `5472d5ee1` changes to a pinned snapshot, so that part composes.
- So the stack would port onto v2 only with a design for the parallel roots and the cache; onto main as of today (MDBX default, no parallel roots) it ports with the mechanical and staging-level conflicts of section 3.

What I could not determine: tn-lmdb's write amplification on the bench fleet's Hyperdisk under the real node load (only the README's NVMe probe and #1834's exec-bench numbers exist); whether #1834 lands before the 2026-11-16 freeze; and #1829's interaction with the bench-6 topics (it touches vendored reth's RPC, pool and trie read paths; the body says the execution-path features are unchanged).

## 5. Verdict for gate G2

1. Do not rebase the bench-6 image; the working position holds.
2. On the default build (what `etc/Dockerfile` builds, with or without `faucet`), #1759 changes no block, consensus message or persist step: still MDBX through the same libmdbx at the same page size on x86-64, plus six per-block timing histograms and RPC cache tasks tracked by TN's task manager.
3. The sync fix exempts committee keys from every new budget; the one change a validator sees is the lazy open, one RTT less per sync stream open (far-validator fetches, run 2's catch-up), and leaving it out keeps bench 6 on bench 5's behaviour.
4. Four of the six conflicts are the base PRs' own (#1826, #1827), being resolved in another session now; a rebase would wait on that and void the reviews and e2e runs on `80a0c76c0` for no measured gain.
5. Before choosing run 1's arms: upstream is leaving MDBX. #1834 (draft, aimed at the 2026-11-16 freeze, merges cleanly on main) makes tn-lmdb the default and keeps MDBX for one release as an opt-in feature outside release graphs.
6. tn-lmdb still writes through a shared mmap and the page cache, so the folio-writeback amplification bench 6 measures applies to it too, but it already advises `MADV_RANDOM` on every mapping by default: the `mdbx_random_advice` arm is worth running as the MDBX baseline and as evidence of the mechanism, not as a change upstream will need for long.
7. The per-persist fields have a tn-lmdb counterpart (`IoStats`) that the node does not export yet; the method carries over, the field names do not.
8. Pipelined persist is the arm whose upstream value depends on #1834: v2's parallel storage roots and execution cache assume no persist overlaps the next build (`parallel.rs:45-49` names "a pipelined persist"), so a win measured on MDBX v1 does not carry over to v2 without a design.
9. A tn-lmdb arm is not possible on this base; it needs #1759 (and #1834 for v2), that is, a different image.
10. Port after the run: the text conflicts are mechanical except the staging-level timing decision in `execution.rs` and `output_overlay.rs`; `mdbx_advice.rs` and its fields must be gated `cfg(not(feature = "tn-lmdb"))` or moved behind `env/database.rs`, or `--all-features` clippy and main's tn-lmdb CI lane fail; the held stack needs a v2 design if #1834 has landed by then.
