# Bench 6: summary for the telcoin-network maintainers

## What ran

Every run used one node build (commit 2df831e3c, branch `bench/bench6-2026-11`): twelve fixes, each behind a node switch that is off by default.
Ten validators and one observer ran bench 5's load shape: two light blasts, then a load blast with a 40-minute mixed phase in which validator-05 was killed and restarted.
Four headline runs crossed the two forms of the vote fix (`quorum_exec_block`) with two node disks, 20,000 provisioned IOPS and 50,000.
The always-on form names in every header the author's executed tip minus 8 outputs (the floor); the adaptive form names the author's own tip until an own header is cancelled, then uses the always-on rule inside a starved window.
An earlier arm walk (`r20261112-1520`, nine switch sets by rolling restart) showed that at 20,000 IOPS the disk's write count bounds the fleet.

## The headline table

| run | vote form | node disk, IOPS | throughput, tx/s | own-header certification: fleet (lowest validator) | gap resends | unlanded | landed over accepted |
|---|---|---:|---:|---|---:|---:|---:|
| bench 5 [r20261107-1504](https://benchmark.telcoin.network/runs/r20261107-1504/) | none | 20,000 | 3,448.7 | no fleet figure; 0.0 % (validator-08) before the kill | not recorded | not recorded | 99.629 % |
| [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) | always-on | 20,000 | 5,322.1 | 99.94 % (99.7 %, validator-06) | 29,546 | 183 | 99.9987 % |
| [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) | adaptive | 20,000 | 5,394.6 | 99.64 % (99.0 %, validator-02) | 104,280 | 10,767 | 99.9267 % |
| [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) | always-on | 50,000 | 7,329.0 | 88.26 % (44.5 %, validator-06) | 133,975 | 14,928 | 99.9232 % |
| [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/) | adaptive | 50,000 | 7,286.1 | 94.82 % (84.1 %, validator-06) | 255,453 | 20,768 | 99.8591 % |

Throughput is bench 5's headline figure: chain transactions per second over bench 5's all-generators window of the load blast, the outage included.
Generator 05 was silent for 65 % of bench 5's window against 40 % and 38 % in r20261113-1351 and r20261113-1630, and bench 5 was bound by the disk's bytes where bench 6 at 20,000 IOPS was bound by its write count.
Certification is the share of own headers certified over the load blast's mixed phase, the outage included (bench 5: before the kill, the only window the sources give for it).
Gap resends are transactions the generators sent again over the whole load blast after a 300-s gap check found the sender's head transaction unknown; unlanded are accepted transactions not on chain after the 180-s tail scan.
Landed over accepted is the share of the transactions the RPC accepted that landed on chain, over the whole load blast; bench 5's figure was recomputed from its raw generator records with the same code, but its generator recorded no gap resends and no tail scan.

## What is confirmed

The vote fix holds while the disk binds, and only then: in r20261113-1351 the disk gave every engine the same cost, 187.0-187.3 µs/tx.

`vote_queue_fix` took `lock_ms` p95 from 3,597-7,892 ms to 0 in every arm-walk window with it on.

Bench 5's write amplification is the write pattern of a node's first process after genesis.
With `mdbx_random_advice` on from the first start every node of r20261113-1351 and r20261113-1630 wrote 1.06-1.19 times its page bytes, against 10-13 times (modelled) for bench 5, whose own first process was not checked.

Every epoch close certified one record hash and one closing block on every node, with at least 7 of 10 signers.

The form changed neither throughput, the closes nor the rejoin, and no node in the four runs logged a halt, a fork, an `unexpected execution result`, fatal database text or a panic.

## What is open

The form of the vote fix.
At 20,000 IOPS the always-on form certified a little more and cost senders less, while the adaptive form named a block about 0.9 s old against 5.5 s.
At 50,000 IOPS the adaptive form certified more, though with one run per form the gap is not settled against run-to-run noise, and inside its starved windows its fast proposers named the same floor-8 block.
On both disks the whole difference in the senders' cost sits in #1807.

The floor at 50,000 IOPS.
In r20261113-1630 execution spread to 18-45 outputs across the engines, so tip minus 8 named blocks that four or five voters had not executed.

Issue #1807: accepted transactions that land late or never.
With `sealed_tx_keep` off, a batch's transactions leave the worker pool when the worker quorum acks it.
When a newer own header cancels an older one's vote collection or commits ahead of it, the proposer puts the older header's digests back at the front of its queue, after the newer header has already taken that worker's next digests.
A sender's later transactions then execute first, are skipped as `nonce_too_high` and sit in no pool.
On the bench-6 branch at 2df831e3c this is `crates/consensus/primary/src/proposer.rs` lines 910-974, 1004-1071 and 1090; on `main`, whose proposer.rs is byte-identical to the bench-6 base and not its tip, the same code sits at other lines.
The sender gets no error; its generator resends the window after a 300-s gap check.
A transaction never lands when its skip falls in the last ~345 s of load, or when its re-queued batch never executes.

Recovery of a killed validator under sustained load.
State sync feeds a follower no faster than it executes, so under load it fell further behind (1.332 against the fleet's 1.409 outputs/s in r20261113-1351) while its RPC refused every transaction.

The untested epoch-record paths.
No test crosses a close with the always-on form or fires the state check on a diverged closing block.

## Why bench 7 is a new number, not a continuation

`main` (45dce8947) changed after bench 6's base: #1834 made tn-lmdb the default execution store, and #1822, #1839, #1842, #1844 and #1846 reworked `RequestHandler::vote` and the per-author lock.
Bench 7 runs both forms on it at 20,000 IOPS, floor 8, with #1807 addressed by an own-chain hold in the proposer (switch `digest_order_hold`), the collector hardening switched on, and the epoch-record closing-block check, which extends `main`'s own unconditional stored-record guard (#1834) and has no switch.
With the node underneath and the #1807 path both changed, bench 7 compares the two forms with each other, and only partly with bench 6.

## What goes upstream now, and what waits

PRs now, into one staging branch off `main`:
- the switch machinery and bench-6 observability;
- the e2e scaffold;
- `vote_queue_fix`: the per-author lock wait is still on `main` after the vote-handler rework (a unit test on `main` shows six queued requests of one author answered one second apart), so the fix is ported;
- the epoch-record closing-block check and the collector hardening, once their tests and reviews pass.

After bench 7: the vote forms and the #1807 hold, which replaces `sealed_tx_keep` and `digest_dedupe`.
Measurements go on issues for the recovery pool, the tracker drain, the parent grace and the in-flight bound, which are not ported.

## Links

- https://benchmark.telcoin.network/runs/r20261113-1351/ (always-on, 20,000 IOPS)
- https://benchmark.telcoin.network/runs/r20261113-1630/ (always-on, 50,000 IOPS)
- https://benchmark.telcoin.network/runs/r20261113-2118/ (adaptive, 20,000 IOPS)
- https://benchmark.telcoin.network/runs/r20261114-0000/ (adaptive, 50,000 IOPS)
- https://benchmark.telcoin.network/runs/r20261107-1504/ (bench 5)
