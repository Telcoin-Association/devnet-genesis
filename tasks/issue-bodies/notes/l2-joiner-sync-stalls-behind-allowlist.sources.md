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
