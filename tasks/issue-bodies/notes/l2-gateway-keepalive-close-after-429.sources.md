# Sources: l2-gateway-keepalive-close-after-429

| Item in the draft | Source | Status |
|---|---|---|
| Scope rows 35 and 75 (75 added by the coordinator) | `tasks/challenges-l2.md` rows 35, 75; report 2.6 and section 4 | checked |
| BrokenPipe without a proxy, one client, real image, 2026-11-17 | row 35 ("unit E5, real image, 2026-11-17: BrokenPipe reproduced with one client") | taken from the row, source not re-read (the only BrokenPipe found under `tasks/l2`, `tnd-final-6361c9c/caddy-smoke-2.log:51`, is a 413 case, not this one) |
| 2026-11-18 03:01 UTC; one client, 24 connections, 6,000 requests, 11.28 s, validator 1 | row 75; `tasks/l2/w3/v/r8b-burst.txt:13`; date from `r8b-metrics.txt` (`== before 2026-11-18T03:01:18Z`) | checked |
| `total {200: 1283, 429: 4360, 502: 357} in 11.28 s` | `tasks/l2/w3/v/r8b-burst.txt:13` | checked |
| 6 % (357 / 6,000 = 5.95 %) | computed from the line above; row 75 says "about 6 %" | checked |
| Per second ~100 x 200, 430-455 x 429, 25-46 x 502 | `r8b-burst.txt:2-10` (seconds 1-9; seconds 0 and 10 are partial) | checked |
| `rejections_total{reason="rate_limited"} 4360` | `tasks/l2/w3/v/r8b-metrics.txt:14` (absent before) | checked |
| Worker `forwarded` +4 (4527 -> 4531) | `r8b-metrics.txt:4,9` | checked |
| Caddy journal: 357 `http: server closed idle connection` on validator-1-devnet | row 75 | taken from the row, source not re-read |
| Second client 6 of 6 x 200, 03:01:28-03:01:33 | `tasks/l2/w3/v/r8b-txgen.txt` | checked |
| RPC node logged no demotion | coordinator message; row 75 ("4 forwards of the RPC node in the window") | taken from the row, source not re-read |
| Client: `http.client.HTTPSConnection` per thread, replaced only after an exception | `tasks/l2/w3/v/r8b-burst.py:8-19` | checked |
| 24 threads x 250 requests | row 75 (24 connections) and 6,000 total | taken from the row (invocation args not re-read) |
| 502 to forwarder demotes for 30 s | row 75; `tasks/l2/rh5-report.md:31` ("Caddy's 502 = non-2xx = demotion [not tested]") | taken from the row (inferred in source) |
| `bin/worker-gateway/src/error.rs:205` (`RateLimited => StatusCode::TOO_MANY_REQUESTS`), `ratelimit.rs:793` | `git -C telcoin-network grep -nE 'RateLimited\|rate_limited' 5533ff73a -- bin/worker-gateway/src` | checked |
| Close site not located | greps for `Connection: close`, `header::CONNECTION`, `keep_alive` in `bin/worker-gateway/src` found none relevant | checked (not located) |
