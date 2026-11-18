# Sources: l2-joiner-sync-stalls-behind-allowlist

| Item in the draft | Source | Status |
|---|---|---|
| Title, "every validator that joins after genesis … until the epoch after its `activate()`" | `tasks/challenges-l2-report.md` section 2.3 and section 4; row 67 | checked |
| Run window 2026-11-18 02:05-02:38 UTC | row 67 (02:05-02:38Z); date from `tasks/l2/w3/s1/node5-view-0235Z.txt` (`ts=2026-11-18T02:35…`) and `date -u -d @1794969315` = 2026-11-18T02:35:15Z | checked |
| About 97 catch-ups a minute, never more than 3 outputs behind; handshakes and record publication every few minutes | row 67 | taken from the row, source not re-read (node 5's log is not in devnet-genesis) |
| 02:28Z max 25; 02:31-02:38Z maxima 14, 17, 21, 40, 37, 38, 36, 48 | row 67 | taken from the row, source not re-read |
| Stalls up to 48 outputs, about 30 s; up to 476 blocks at 7 blocks/s | row 67; report 2.3 | taken from the row, source not re-read |
| `Stream(NotConnected)` against all four, up to 39 a minute | row 67; `tasks/ckpt-l2-orch.md` entry 02:38Z (line 186) | checked (orchestrator log) |
| Lags 262, 51, 208, 366, 476, 0, -1, 0, 2, 4, 17; RPC node within 6 | row 67; `tasks/ckpt-l2-orch.md:186` | taken from the row; raw files re-read (see next line) |
| Raw pairs 230, 22, 179, 335, 458, 0, -1, 0, 2, 1, 15, 17; node 5 read ~1.9 s after validator 1 | `paste lagprobe2-0.txt lagprobe2-4.txt` (validator-1-devnet vs observer-5-devnet), column differences; timestamps 1794969315.065 vs 1794969316.942 | checked. The row's same-instant figures are about 30 blocks higher on the first five samples, consistent with validator 1's ~17 blocks/s times 1.9 s (inferred; how the row adjusted was not re-derived) |
| Probe window 02:35:15-02:37:05 UTC, every 10 s | `lagprobe2-0.txt` first/last timestamps, `date -u -d @…` | checked |
| File roles: -0 validator 1, -4 node 5, -5 RPC node | first column of each file | checked |
| Log excerpt lines (exchange failed x4 same peer, no peer served, catchup 9 and 17, heartbeat connected_count=1 connected_or_dialing=4) | `tasks/l2/w3/s1/node5-view-0235Z.txt` lines 7-21 | checked (peer id shortened, timestamps shortened to time of day) |
| Rate 2.5 -> 7 blocks/s together with the firewall; "cause not separated" | `tasks/ckpt-l2-orch.md:186` | checked |
| `Unavailable` from the RPC node 30-60 a minute since 02:12Z; 2,752 | `tasks/ckpt-l2-orch.md:186` | checked |
| Record reaches validators only through the hub; backoff up to 30 min | row 11; report 2.3 ("the plan says … row 11 has no run evidence") | taken from the row, source not re-read; not verifiable here |
| `crates/consensus/primary/src/network/mod.rs:2388`, `:2279`, `:2771`; `crates/state-sync/src/lib.rs:575` | `git -C telcoin-network grep -nE '"(catching up consensus blocks\|consensus output sync exchange failed; trying next peer\|no peer served …\|peer denied …)' 5533ff73a -- crates` | checked |
| Mechanism inferred, not read in code | row 67 status column | checked |
| (added 2026-11-18T03:42Z by the orchestrator) Epoch start 03:24:45 UTC; `scheduled, eligible`, `admitted: false` on all four validators 30 s later; in the firewall sets of two validators by 03:27:15 and of all four by 03:29:15 | `tasks/l2/w3/s1/allowlist-watch.log` (blocks labelled n1-032515, n1-032715, n1-032915) | checked |
| 03:28-03:40 UTC: 94 to 99 catch-ups a minute, never more than 4 outputs behind; 03:20-03:27 maxima 19 to 100 | `tasks/l2/w3/s1/node5-sync-after-allowlist-0341Z.txt` lines 1-7 (per-minute `n=` and `max=` from node 5's log) | checked |
| `Stream(NotConnected)` 18-41 a minute before, none after | same file, "notconnected per minute" line (03:22-03:27: 25, 26, 41, 25, 30, 18; then one at 03:39) | checked ("none" = none from 03:28 to 03:38, one at 03:39) |
| 389 `new connection established` in 15 minutes; `connected_count=1` | same file, "connections since 03:26" (389; heartbeat lines of 03:40:47) | checked |
| Block rate by minute: 8 to 10 blocks/s at 03:28, 03:31, 03:32, 03:35; 1 block/s at 03:23; between 1 and 17 a second overall | `tasks/l2/w3/s1/blockrate-0316-0342Z.txt` (03:28=8.7, 03:31=9.3, 03:32=7.8, 03:35=9.8, 03:23=1.0, 03:25=17.1) against `node5-sync-after-allowlist-0341Z.txt` (03:23 max=37; 03:28 max=3, 03:31 max=2, 03:32 max=3, 03:35 max=3) | checked. An earlier wording of the draft said "block rate unchanged": that was not measured and is replaced |
| Consensus outputs at a steady 1.6 a second | 94-99 catch-ups a minute at distance 1 when node 5 keeps up (same file); 97 a minute before the firewall (row 67) | checked |
