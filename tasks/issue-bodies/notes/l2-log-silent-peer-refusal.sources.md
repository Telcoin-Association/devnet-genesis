# Sources: l2-log-silent-peer-refusal

| Item in the draft | Source | Status |
|---|---|---|
| Title, two-part scope | `tasks/challenges-l2-report.md` section 4 row `log-silent-peer-refusal`; sections 2.3 and 2.15 | checked |
| Local rehearsal, run 2, RPC node not started; 100 s; joiner at head 0, v1 at 1; `connected_count=0` | `tasks/l2/rh0-report.md:75-77` | checked |
| `"new connection established"` 9-27 times to each primary/worker address; validators drop it; no line naming the joiner at `-vvv` | `tasks/l2/rh0-report.md:77-79`, `:104-105`; row 33 | checked (report re-read; container logs not re-read) |
| Run 2026-11-17 19:50-19:54 UTC, local docker, image from 5533ff73a | `tasks/l2/rh0-report.md:3` (19:42-19:54 UTC, image adiri:v0.3.0-devnet), `:75` (joiner started 19:50:47), `:80` (rpc started 19:52:35.7); image commit from `tasks/l2/facts/image-probes.md:2-5` | checked |
| About 200 WARNs in 3 min on the RPC node, 47 on node 5, healthy chain | `tasks/l2/rh3-report.md:130-131`; row 39 | checked |
| RH3 on 2026-11-17, container logs | row 39 evidence column; `tasks/l2/rh3-report.md:122` (20:47 UTC during step 3) | taken from the row, source not re-read (exact window not read) |
| 4 WARNs in 0.4 ms against the same peer at 02:35:15 UTC on 2026-11-18; catch-up of 9 + 17 = 26 outputs at 02:35:17.4 | `tasks/l2/w3/s1/node5-view-0235Z.txt` lines 13-16, 22-23 | checked |
| `crates/network-libp2p/src/peers/behavior.rs:162-186`, `check_admission` at `:180` | `git -C telcoin-network show 5533ff73a:crates/network-libp2p/src/peers/behavior.rs \| sed -n '162,187p'` (LocalPeer at :173, BannedPeer at :177 per git grep) | checked |
| `crates/network-libp2p/src/peers/manager.rs:572-588`, `record_closed_admission_denied`, `ClosedAdmission`, no log | `git show 5533ff73a:…/peers/manager.rs \| sed -n '570,592p'` | checked |
| `crates/network-libp2p/src/consensus.rs:1463-1481`, WARN only for `InboundRejection::Limit` | `git show 5533ff73a:…/consensus.rs \| sed -n '1458,1490p'` | checked |
| `crates/consensus/primary/src/network/mod.rs:2378-2389`, `mark_sync_failed` then WARN | `git show 5533ff73a:…/network/mod.rs \| sed -n '2372,2394p'` | checked |
| `no peer served the consensus output over the sync protocol` logged by `tn::observer` | `node5-view-0235Z.txt` line 17; string at `crates/consensus/primary/src/network/mod.rs:2279` | checked |
| Firewall means a validator never sees the handshake | inference from row 67 ("dials hang") | not verifiable here (inferred) |
