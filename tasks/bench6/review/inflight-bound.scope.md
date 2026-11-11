# Review scope — inflight-bound

Upstream issue: none (a bench-6 measure against the execution queue seen in bench 5). Switch: `rpc_admission_backlog_outputs` (count; default 0 = no bound; the benchmark uses 2, or 3 with pipelined persist).
Where: the checked-out branch `bench/bench6-2026-11`, head dc7855cc6. Size: 7 commits, +1193 lines (tests included).

## Commits (the diff under review, in branch order)
- `639817091` feat(config): add rpc_admission_backlog_outputs and tn_types::ExecutionBacklog
- `5ef5152a9` fix(types): read the execution backlog from output numbers once both are known
- `74ac00a81` feat(engine): share one execution backlog between the node, the engine and the RPC guard
- `998f84a26` fix(engine): start the engine on its reth env's execution backlog
- `f792ef186` feat(node): record forwarded outputs in the execution backlog
- `256422898` feat(rpc): refuse raw submissions while execution trails consensus
- `74662a889` docs(config): say who the admission bound gates and which bounds can close

## Files touched
- `crates/config/src/node.rs`
- `crates/engine/src/lib.rs`
- `crates/node/src/engine/inner.rs`
- `crates/node/src/manager/node.rs`
- `crates/node/src/manager/node/run_epoch.rs`
- `crates/tn-reth/src/env/mod.rs`
- `crates/tn-reth/src/env/rpc.rs`
- `crates/tn-reth/src/rpc_fee_cap.rs`
- `crates/types/src/execution_backlog.rs`
- `crates/types/src/lib.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the switch table row and the row `inflight-bound` under "Node log lines and metrics" (who is gated, the JSON-RPC error a refused client gets, close and reopen rule, what the counter counts).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, section "From U11" (as built; D47-D50: what the arm looks like under saturation, gates closing together, limits above 73 never close, observers not gated) and D9/D52 in "From U12b".
- Unit checkpoint `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u11.md`; the types under review: `crates/types/src/execution_backlog.rs` (`ExecutionBacklog`, `AdmissionGate`).

## Questions specific to this topic (2g)
1. The gate reads three relaxed atomics that the node's forwarder and the engine write from other threads. Find an interleaving in which the gate stays closed forever although the engine is idle (for example: forwarded recorded, the engine crashes or the epoch ends before `record_executed`; a restart; replayed outputs after a restart whose numbers are below the last recorded one).
2. The gate state changes only when an active validator's RPC receives a submission. Is there any state in which no submission can arrive to reopen it, or in which it reopens while execution is still far behind?
3. A client refused with -32003: TN's own observer forwarder treats it as try-next and requeues. Can a refused transaction be lost, duplicated, or make the forwarder spin (cost per refused hop; all validators closed at once)?
4. RPC abuse: does the refusal path do any work before the check that an attacker could make expensive? Is the check before decoding and signature recovery on both methods (`eth_sendRawTransaction`, `eth_sendRawTransactionSync`)? Any method that reaches the pool without the gate that a client can call?
5. Epoch boundary: what do `last_forwarded` and `last_executed` read across an epoch close and the next epoch's first outputs; can the backlog read huge or wrap?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/inflight-bound-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-inflight-bound.md`
