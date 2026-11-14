# Sources: tasks/issue-bodies/bench6-inflight-bound-measurements.md (not for posting)

Slug: inflight-bound-measurements. Written 2026-11-14 by U-I3W. "M" = 45dce8947 (telcoin-network-b7). "B6" = bench/bench6-2026-11 at 2df831e3c (telcoin-network-b6).
Abbreviations: BF = benchmark/private/bench6-r20261112-1520/A1/bound-fields.md; V = benchmark/private/bench6-r20261112-1520/A7/verdicts.md; ST = benchmark/private/bench6-r20261112-1520/A6/stages.md; I8 = benchmark/private/bench6-r20261112-1520/I-8/findings.md; RV = tasks/bench6/review/inflight-bound-report.md; R = tasks/bench6-report-r20261113-1351.md.

## Problem (M checks)
- no backlog gate on the submit path: M crates/tn-reth/src/rpc_fee_cap.rs:216-225 (`admission.ensure_active`, `ensure_active_worker`, `ensure_can_submit(node_mode)`, `cap.enforce`, then reth). grep on M: no "txpool is full" or -32003 producer in crates/ except the forwarder's classification (forward.rs:155-162, tests) and reth's vendored error (vendor/reth/crates/rpc/rpc-eth-types/src/error/mod.rs:975).
- engine queue 8: M crates/engine/src/lib.rs:61 (doc :52-60: backpressure into the to_engine channel and the forwarder); channel 64: M crates/node/src/manager/node.rs:83-91.
- #1805 option E: `gh issue view 1805` body, "(E) Bound in-flight transactions at the node ... it is the right latency fix".
- B6 switch semantics (K outputs behind, -32003 "txpool is full", reopen below K-1, only an active validator's own RPC gated; observers, --forward-txs, re-pooled not): B6 crates/config/src/node.rs doc above `pub rpc_admission_backlog_outputs` (:449-460).

## Evidence
- arm walk, ten validators, 20,000 IOPS: R §2 :89, :130-140. 6,000 senders: V :305 ("senders funded 6,000").
- `bound` K=3 vs `pipe`, cumulative switches: R §2 table :137-138; V :296-299 ("beside everything `pipe` had"; "only ever ran with the pipelined persist on").
- earlier arms' changes include sealed_tx_keep / digest_dedupe (#1807), recovery_threads=3 (#1805): R :136.
- table rows (600 x 16 = blast 12 vs blast 10): landed 2,562 / 4,093, seen 36.66/63.90 vs 10.19/25.09, refused 42.3 % of 3.37 M, given up 2,336, sender window share 98.6 % vs 27.5 %: BF table :15, :17. Execution lag 81-84 vs 20-24: V :284, :321. S10 34,624 -> 4,268 ms p50, S1 129 -> 1,900 ms p50, accept p95 37 -> 3,198 ms: ST :221; V :319.
- 600 x 4 (blast 11 vs 9): 2,590 vs 2,127; seen p50 3.43 vs 10.11; 57.6 % of 2.30 M; 10,110 given up: BF :14, :16, :33.
- in flight 44.5 % vs 102.0 %, Little's law holds: BF :15, :17 (column "in flight / (senders x window)"), :38.
- retries 1,423,641 in mixed: BF :17; backoff 50 ms doubling to 2 s, 20 tries, two slow resends, drop without nonce advance; backoff time not recorded: BF :27-29, :51.
- warm-up refusals 467,765 (blast 12): BF :17, :41; one generator's 280 preamble steps refused (blast 11): BF :41.
- refusal = full pool code and text: BF :47.
- engine busy 957 vs 995 ms/s, queue at cap 59 % vs 97 %: V :320.
- gate cycles ~6 full (up to 15,000 tx) then ~8 empty, 57 % empty: I8 :17, :144. Writes/tx 7.00 -> 4.71 (-33 %), quotient = measured rate: V :316, :325-326.
- colder cache 171 vs 27 faults/s (works against the gain), DB +22 % (6.07 vs 4.96 GiB): V :303-304, :314, :428.
- nothing admitted went unlanded (blasts 11-14): BF :34; V :318.
- off in all four headline runs: R :145 (runs 2, 2b: the other eight switches at defaults), R §8.2 :669 (runs 3, 3b: every other switch at its default).

## Review findings, re-checked on M
- M1 (Medium): RV :46-78. On M: walk rule forward.rs:1112-1126 (held rejection; "A rejection that reaches the end of the chain unconfirmed stands"); -32003 transient forward.rs:155-162; Rejected -> pending_forwards().remove, no requeue forward.rs:808-811; honest trigger -32000 "worker is inactive" worker.rs:168-172; observer accepted first: forward.rs:1 ("Forward transactions accepted by a non-committee ("observer") worker").
- L1 (Low): RV :80-99. On M: requeue_one forward.rs:939-960 counts only `added` (record_txns_requeued).
- L3 (Low): RV :130-145. On M: crates/tn-reth/src/rpc_tx_forward/client.rs:4-5 (module doc: an error reply is the verdict and ends the walk), :218-229 (`ClientError::Call` -> return Err).
- L4 (Low): RV :147-156 (property of the bench-6 gate; not a main-code item).
- L2 (backlog blind to the channel before the first finished output) left out: implementation detail of the bench-6 code, not of main.

## Why not a PR
- not confirmed as a net gain in the headline configuration; pipeline only: brief u-i3w.md:18; bench6-r20261112-1520/A7/final-arm-options.md:77, :79-89; R §4.7 :483.
- forward path first: brief u-i3w.md:18; tasks/bench6-upstream-followups.md:25-30.
- #1807: change on in the arm (R :136); resends mechanism #1807: R §8.4.3 :790.

## Title
- 114 characters. "ignores the execution backlog" read from M's code; "queue behind the engine" measured on bench 6's build (S10), not on M.

## Revision 2 (2026-11-14, figure-check tasks/bench7/figcheck-UI3W.md applied)
Changed sentences and their sources:
- Problem, "On main at 45dce8947 an active validator's RPC admits ...": figcheck Weak, line 5 (a CvvInactive validator refuses with -32603, crates/tn-reth/src/rpc_fee_cap.rs:57-78).
- Problem, "... and pushes back to the epoch manager's forwarder, never to the RPC.": figcheck Weak, line 7 (crates/engine/src/lib.rs:57-59; crates/node/src/manager/node.rs:89-90).
- Evidence, "Arm walk r20261112-1520 (one fleet stepped through nine switch sets by rolling restart; no run page): ten validators, 20,000 provisioned IOPS, ten closed-loop generators of 600 senders each; a blast is named by senders per generator × the window each sender keeps in flight (600 × 16, 600 × 4).": figcheck error 4 replacement, verbatim (report :171; A7/verdicts.md:305).
- Evidence, new sentence "`pipe` was the walk's slowest 600 × 16, its outputs small through page cost, so the gain is measured from a low base.": figcheck Weak, control arm (A7/final-arm-options.md:71; A1/bound-fields.md:15), verbatim.
- Table header cell "| 600 × 16 |" (was "600 × 16 senders"): figcheck error 4.
- Evidence, "It also refused 467,765 calls in the 600 × 16 warm-up." (dropped "and during one generator's account setup", which was the 600 × 4 blast): cut for length; BF :17, :41.
- Evidence, removed "The engine stopped saturating: busy 957 ms/s against 995, queue at its cap in 59 % of samples against 97 %." : cut for length (V :320 unchanged).
- Evidence, "That is an unplanned group commit, not the bound's purpose; the cycle is read from the gate rule in the code and from the outputs in sequence, but the timing of each opening against the senders' retries was not joined, since the node logs no gate transition.": figcheck error 3 replacement, verbatim (I-8/findings.md:147; report :493).
