# RPC admission ignores the execution backlog, so under load transactions queue behind the engine, not at the sender

## Problem

On main at 45dce8947 an active validator's RPC admits a raw transaction however far its execution is behind.
The submission guard checks worker admission and membership, node mode and the fee cap (`crates/tn-reth/src/rpc_fee_cap.rs:216-225`) and reads no backlog.
The engine holds at most 8 outputs (`crates/engine/src/lib.rs:61`) behind a 64-output channel (`crates/node/src/manager/node.rs:91`) and pushes back to the epoch manager's forwarder, never to the RPC.
Under load the wait then sits in the engine queue (table below, on bench 6's build); #1805 named a node-side bound on in-flight transactions (its option E) as the latency fix.

Bench 6 built and measured one form of that bound, `rpc_admission_backlog_outputs` (on `bench/bench6-2026-11` at `2df831e3c`).
An active validator answers `eth_sendRawTransaction` with −32003 "txpool is full" while its execution is K outputs behind and admits again below K − 1; observers, `--forward-txs` and re-pooled transactions are not gated.
This issue carries its measurements and what an implementation on main would meet; it is not a pull request now.

## Evidence

Arm walk r20261112-1520 (one fleet stepped through nine switch sets by rolling restart; no run page): ten validators, 20,000 provisioned IOPS, ten closed-loop generators of 600 senders each; a blast is named by senders per generator × the window each sender keeps in flight (600 × 16, 600 × 4).
The `bound` arm (K = 3) is read against the arm before it, `pipe`, whose switches differ only by the bound.
Both ran with pipelined persist and the earlier arms' changes on, among them the pool changes for #1807 and the recovery pool for #1805; one run.
`pipe` was the walk's slowest 600 × 16, its outputs small through page cost, so the gain is measured from a low base.

| 600 × 16 | `pipe`, no bound | `bound`, K = 3 |
|---|---:|---:|
| landed tx/s | 2,562 | 4,093 |
| seen p50 / p95, s | 36.66 / 63.90 | 10.19 / 25.09 |
| send calls refused, mixed phase | 0 | 42.3 % of 3.37 M |
| transactions the senders gave up | 0 | 2,336 |
| median sender's share of time at its window | 98.6 % | 27.5 % |
| execution lag, rounds | 81-84 | 20-24 |
| engine channel and queue wait p50, ms | 34,624 | 4,268 |
| pool wait p50 / RPC accept p95, ms | 129 / 37 | 1,900 / 3,198 |

At 600 × 4 the bound landed 2,590 tx/s against 2,127, seen p50 3.43 s against 10.11, with 57.6 % of 2.30 M calls refused and 10,110 transactions given up.

What it protected: execution lag and the engine queue, and seen latency through fewer transactions in flight (44.5 % of senders × window against 102.0 %; Little's law held).

What it cost the senders: a refused generator resends the same bytes with backoff, then gives up without advancing its nonce (1.42 M retries in the 600 × 16 mixed phase); the time spent in that backoff was not recorded.
It also refused 467,765 calls in the 600 × 16 warm-up.
A sender cannot tell this refusal from a full pool: code and message are the same.

Where the throughput came from: the gate cycled, about 6 committed outputs of up to 15,000 transactions while open, then about 8 empty ones while the engine caught up.
57 % of outputs were empty, and at the disk's write limit writes per transaction fell 33 % (7.00 to 4.71), which accounts for the whole gain.
That is an unplanned group commit, not the bound's purpose; the cycle is read from the gate rule in the code and from the outputs in sequence, but the timing of each opening against the senders' retries was not joined, since the node logs no gate transition.
Against `pipe` the cache was colder (171 against 27 faults per second), which works against the gain, and the database 22 % larger.

## What an implementation on main would meet

The review of the bench-6 code found these.
The first three rest on forwarding code that is unchanged on main at 45dce8947; the fourth holds for any refusal gate.
- Medium: an observer's forward walk holds a first rejection and keeps asking; a rejection unconfirmed at the end of the chain stands (`crates/tn-reth/src/forward.rs:1112-1126`), and −32003 means "try the next" (`:155-162`).
  With every honest gate closed, one validator's −32000 decides, whether a byzantine owner's or an honest one's with an inactive worker (`crates/tn-reth/src/worker.rs:168-172`), and the observer drops a transaction it had accepted, without a requeue (`forward.rs:808-811`).
  Fix: if any hop answered "try the next", an unconfirmed rejection is no verdict; requeue.
- Low: a requeue the observer's own pool refuses is lost and not counted (`forward.rs:939-960`), and closed gates make that path run on every pass.
- Low: a `--forward-txs` node relays a target's −32003 and tries no other target (`crates/tn-reth/src/rpc_tx_forward/client.rs:4-5`, `:218-229`).
- Low: while closed, admission ignores fees, and after reopening the window goes to whoever polls first.

## Why not a pull request now

- It is not confirmed as a net gain in the headline configuration: it was off in all four headline runs, it ran only with pipelined persist, which does not carry to main ({{execute-and-persist-in-series}}), and its gain came through output size at the disk limit.
- The forward path's medium finding comes first.
- On #1807: the bound lost nothing it admitted (with bench 6's #1807 change on), but its refusals and give-ups add to the senders' cost beside #1807's resends.

## How to verify

- On main, one configuration with the bound on and off: landed rate, seen p50 and p95, refused share, give-ups, the time senders spend refused (the generator must time its backoff), execution lag and transactions per output.
- A forward test with every honest gate closed and one validator answering −32000: the transaction is requeued, not dropped.
- A refusal counter separate from the pool's, and a message a sender can tell from a full pool.
