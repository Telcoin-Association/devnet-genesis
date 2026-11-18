# Sources: l2-forwarder-one-client-per-rpc-node

| Item in the draft | Source | Status |
|---|---|---|
| Title, scope rows 10/42/43/44, who meets it | `tasks/challenges-l2-report.md` section 2.5 and section 4 | checked |
| Local rehearsal, 2026-11-17 21:05-21:14 UTC, images 0aec3e7c… / 8b887098… (built from 5533ff73a) | `tasks/l2/rh5-report.md:3-4`; `tasks/l2/facts/image-probes.md:2-6` | checked |
| Standalone gateways, no proxy in front | `tasks/l2/rh5-report.md:27-29` (`--mode standalone --front none`, no Caddy) | checked |
| 100 requests/s, burst 200, 32 connections per client IP | row 10; `rh5-report.md:19,115`; `bin/worker-gateway/src/cli.rs:486,491` (show 480-500), `:2812` (git grep) | checked |
| One sender's transfers go to one validator first (gateway 1) | `rh5-report.md:18-19`; row 10 | checked (report); selection code not read |
| 400 transfers, 8 threads, 0.07 s, HTTP 200 x400; ~210 forwards in a second; one 429 `rejections_total{reason="rate_limited"} 1`; requeued 61; rest to node4; 1.09 / 3.12 / 4.65 s | `rh5-report.md:19-21,110-113` | checked |
| Gateway logs no warning for the 429 | `rh5-report.md:114-115` | checked |
| Warning text `… demoted=1 cooldown_secs=30` names no endpoint | `rh5-report.md:96-97`; row 43; `crates/tn-reth/src/forward.rs:895-900` | checked |
| `tn_worker_submit_usable_members` 3 (of 4), `tn_worker_gateway_rejections_total` | `rh5-report.md:24-25,98,113` | checked |
| 503 until ready, 11 s after start; 11.8 s on restart; demoted 30 s | `rh5-report.md:26,56,105-106`; row 44 | checked |
| Demotion line 21:13:01.647; `/ready` 200 at 21:06:35 and 21:12:18.16 | `rh5-report.md:56,106,114` | checked |
| `crates/tn-reth/src/forward.rs:183` `UNREACHABLE_COOLDOWN = 30 s`; `:885-900` count and warn | `git grep -nE 'COOLDOWN' 5533ff73a -- crates/tn-reth/src/forward.rs`; `git show … \| sed -n '885,903p'` | checked. Row 43 names the log target `worker::forward`; the code is in `crates/tn-reth/src/forward.rs`, not a worker crate |
| `bin/worker-gateway/src/cli.rs:480-486`, `:491`, trusted-proxies doc | `git show 5533ff73a:bin/worker-gateway/src/cli.rs \| sed -n '480,500p'` | checked |
| No `X-Forwarded-For` / PROXY in forward.rs | `git grep -nE 'X-Forwarded-For\|"forwarded"\|PROXY' 5533ff73a -- crates/tn-reth/src/forward.rs` (no match) | checked (grep only; request construction not read) |
| Installer renders no limit flag; `gw_render_args` at `lib/gateway.sh:543` | `git -C tn-node-deployment grep -nE 'rate-limit\|gw_render_args\(\)' 79fb24e… -- lib/gateway.sh` (only :543); row 42 | checked |
| 41 forwards to gw2 not in a node2 block | `rh5-report.md:116` | checked |
| Cooldown reset at epoch change, timing only | `rh5-report.md:101-103,131` | checked (inferred in source) |
