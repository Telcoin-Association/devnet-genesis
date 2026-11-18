# Sources: l2-forwarder-rejected-warning-for-included-txs

| Item in the draft | Source | Status |
|---|---|---|
| Scope row 76 (added by the coordinator) | `tasks/challenges-l2.md` row 76 | checked |
| Warning text `the forwarded transaction was rejected; no validator accepted it` | row 76; `crates/tn-reth/src/forward.rs:816` (`git grep` at 5533ff73a) | checked |
| Twelve lines 03:01:10-03:01:13 UTC, `nonce too low`, transactions already included | row 76 | taken from the row, source not re-read (RPC node log not in devnet-genesis) |
| Date 2026-11-18 | same live run as `tasks/l2/w3/v/r8b-metrics.txt` (2026-11-18T03:01Z) | checked (inferred same day from the shared 03:01Z window) |
| rejected 930 -> 959; queued 12,369 -> 12,864 (+495); requeued 727 -> 770 (+43) | `tasks/l2/w3/v/r7-t0-rpc6.txt:4,9,11`; `r7-t1-rpc6.txt:4,6,11` | checked |
| 68 s between scrapes | row 76 | taken from the row, source not re-read (files carry no timestamp) |
| 29 / 495 = 5.9 % ("about 6 %") in the window; 959 / 12,864 = 7.5 % cumulative | computed from the scrapes. Row 76 says "959 in the first 75 min, about 6 % of what it queued": the 6 % matches the window, not the cumulative figure | checked; row wording differs |
| "first 75 minutes" | row 76 | taken from the row, source not re-read |
| `crates/tn-reth/src/forward.rs:808-818` Rejected arm; `:802-806` deferred arm | `git show 5533ff73a:crates/tn-reth/src/forward.rs \| sed -n '802,818p'` | checked |
| Re-send after slow answer vs generator sending twice: not verified | row 76 | taken from the row |
