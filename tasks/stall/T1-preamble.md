status: complete
completed sections: 1, 2, 3, 4, 5

## 1. Preamble code (tn-transaction-generator, src identical to 3644adc)
- mod.rs:396-412 drive(): Phase::Preamble -> prepare::run_preamble(timeout=args.preamble_timeout_secs, default 600, args.rs:64-66).
- prepare.rs:1876-1964 run_preamble: plan_preamble per sender (11 steps: 2 drips 200k gas, WTEL deposit, 6 approvals, addLiquidity 350k w/ deadline now+600s, LP approve); 64 senders concurrently (PREAMBLE_CONCURRENCY prepare.rs:71), each sends its steps sequentially with local nonces (preamble_sender prepare.rs:1781-1870), fee = 4*basefee+tip (shared.rs:229). Accept = node took it into pool. No resend on later loss.
- Wait loop prepare.rs:1940-1961: polls every 250ms shared.confirmed_nonce(i) >= last_accepted_nonce+1; confirmed is raised ONLY by the block scanner (scanner.rs:211-214, ledger join). Global deadline; on timeout just warns and proceeds. No per-tx retry, no gap detection.
- After: probe_impl re-reads PENDING nonce from pinned node (prepare.rs:1563-1582) + balances/allowances. Incomplete senders keep missing requirements -> sampler cannot build dependent types; preamble txs are NOT in the mixed-phase sender's inflight map, so sender.rs:465-476 'nonce stuck at a hole with no in-flight bytes; nothing to resend' -> a preamble nonce gap is never repaired.

## 2. Evidence (results/r20261006-0053/blasters)
- All 10: submitted=accepted=6600 in 1.0-2.3 s (01:48:07.8-01:48:11.5). Zero RPC errors in preamble.
- Start order / incomplete: 05(07.83)0, 06(08.27)0, 07(08.37)64, 02(08.46)24, 01(08.56)59, 08(08.98)128, 10(09.01)27, 09(09.17)64, 03(09.18)281, 04(09.20)600.
- Landing timeline (blocks table, own_tx per 30s from 01:48:08): 01,02,07,08,09,10 land 5657-6470 of 6600 in seconds 2-11, then ZERO until preamble ends. 03 lands 0 until +450s, then 4655 at +450..510. 04 lands 0 for whole window; first 2395 at +630s (94 reverted).
- Preamble unlanded at END OF RUN (never landed): 01:130 02:209 03:878 04:2264 07:500 08:943 09:465 10:206; 05/06: 0. Reverted preamble: 03:218, 04:426 (late landings; LP deadline 600s).
- Chain meanwhile: 05+06 landing ~2.2-3k tx/s each; chain ~3-6k tx/s. Scanner kept up (epoch change logged 01:50:41.8-42.0 on all 10).
- Mixed phase on 03: 'pinned node lost the head-of-line tx; resending' repeatedly (node drops pooled txs).
- Errors over run: known 9-24k all; conn 2158 only on 05.

## 3. Funding
- Funder: 6000/6000 topped up in 30 multicall txs, 01:42:09 -> 01:42:17 ('every topped-up sender reached the target'), still_short=0. Blasters started preamble 01:48:07.8+ (~6 min later); every blaster's probe reports funded=600. Funding is NOT a factor.

## 4. Hypotheses (ranked)
1. (b) CONFIRMED: txs accepted by the node are lost after acceptance (TN pool drops a tx when sealed into a batch; a sealed batch that never commits loses them - 3644adc commit msg). Preamble has no gap repair, so each lost step strands that sender's later steps forever. Evidence: healthy-region blasters landed 86-98% within 11 s then 0 for 590 s; unlanded at END of run 130-943 (never landed); incomplete counts 64/64/128/24(=600-9*64) match PREAMBLE_CONCURRENCY waves -> whole batches lost; mixed phase shows 1.4k-2.9k 'pinned node lost the head-of-line tx' per blaster (loss is chronic, fleet-wide).
2. (c') validator inclusion latency for 03/04 (australia-southeast1): preamble 0 landed for 450 s (03) / 630 s (04); native_transfer p50 90 s/77 s vs 2.5-3.6 s elsewhere; RPC send p50 12-13 ms (RPC not overloaded). Node/consensus-side; generator cannot fix, only stop it from poisoning the fleet window.
- Ruled out: (a) no receipt polling (block scanner, 0 RPC in wait loop; scanner saw epoch boundary within 0.3 s on all 10); (c) RPC overload (send p50 7-13 ms, zero errors); (d) base fee 7 wei constant all epochs, max_fee=4x+tip; (e) funding; (f) 66k preamble txs = ~16 s of chain at 4k tx/s, 05/06 done in 7-8 s.
- Secondary defects: LP_DEADLINE_SECS=600 (prepare.rs:90) == timeout -> late LP landings revert (03:218, 04:426); requirements only re-probed once (prepare.rs:1963) so late preamble landings never re-enable dependent types (04 mix had no stablecoin/uniswap/unwrap).

## 5. Fixes - see final report
status: complete
