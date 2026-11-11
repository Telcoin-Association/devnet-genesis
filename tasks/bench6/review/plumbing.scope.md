# Review scope — plumbing

Upstream issue: none (#1819 review note for the digest wait). Switch: all twelve (the plumbing that carries them; no fix here).
Where: the checked-out branch `bench/bench6-2026-11`, head d91d65d3e. Size: 15 commits, +1901 lines (tests included). This group gets the code review only: skip the security evaluation unless the review turns up something that calls for it.

## Commits (the diff under review, in branch order)
- `bfc5611ab` fix(metrics): give the engine stage histograms sub-millisecond buckets
- `3696d49f3` feat(config): list the runtime switches in Parameters
- `8ab9e89e4` feat(config): add the pipelined_persist switch
- `5b9f13b25` feat(config): leave switches at their default out of a written parameters.yaml
- `38b65ff7b` test(e2e): start chosen nodes with their own parameters and environment
- `4c7e5f032` test(e2e): move the node log helpers from restarts to common
- `d1b6b0ac3` test(e2e): add empty modules for the bench 6 e2e tests
- `b09d65945` test(e2e): key fleet overrides by datadir and rebuild parameters per start
- `9c91263e7` feat(node): log the node switches line and export tn_node_switch gauges
- `d789015b0` feat(engine): hand the pipelined_persist switch to the executor engine
- `8d363e368` feat(engine): add an empty public persister module for pipelined persist
- `acd609838` feat(reth): add OutputBuildScope::seeded for building on an unpersisted output
- `082179d4d` docs(reth): state what OutputBuildScope::seeded's caller vouches for
- `c8e5ae7be` fix(primary): keep a digest's first receipt across a re-queue
- `d91d65d3e` test(e2e): fleet-wide parameters.yaml entries from TN_E2E_PARAMETERS

## Files touched
- `crates/config/src/node.rs`
- `crates/consensus/primary/src/metrics.rs`
- `crates/consensus/primary/src/proposer.rs`
- `crates/consensus/primary/src/tests/proposer_tests.rs`
- `crates/e2e-tests/src/lib.rs`
- `crates/e2e-tests/tests/it/admission.rs`
- `crates/e2e-tests/tests/it/common.rs`
- `crates/e2e-tests/tests/it/epoch_drain.rs`
- `crates/e2e-tests/tests/it/exec_block.rs`
- `crates/e2e-tests/tests/it/main.rs`
- `crates/e2e-tests/tests/it/persist_pipeline.rs`
- `crates/e2e-tests/tests/it/restarts.rs`
- `crates/e2e-tests/tests/it/sealed_txs.rs`
- `crates/engine/src/lib.rs`
- `crates/engine/src/persister.rs`
- `crates/node/src/engine/inner.rs`
- `crates/node/src/manager/node.rs`
- `crates/node/src/metrics.rs`
- `crates/tn-metrics/src/recorder.rs`
- `crates/tn-reth/src/env/execution.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the switch table, the `switches` row (`node switches` line, `tn_node_switch` gauge) and the obs rows.
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/briefs/u0c-api.md` (what the plumbing landed).

## Questions specific to this topic (2g)
1. A switch at its default must not be written to a `parameters.yaml` (a genesis ceremony's file must hold the same keys as before): verify the serde attributes for every field and the guard test.
2. An unknown or mistyped key in `parameters.yaml`: is it rejected or silently ignored? A benchmark arm that misspells a switch must not run as a control arm unnoticed.

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/plumbing-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-plumbing.md`
