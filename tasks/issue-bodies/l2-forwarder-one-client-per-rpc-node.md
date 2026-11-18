# An RPC node is one client IP to every worker gateway, so one busy sender drew a 429 and a 30 s demotion.

The public RPC node forwards every user's transaction to the validators' gateways from its own address, so each gateway's per-client limits apply to all its users together, and a 429 or a 503 sets that gateway aside for 30 s under a warning that does not name it.
The RPC operator and the launch team meet this on launch day; nothing was lost in the test, but load concentrates and the cause is hard to find.

## What happens

In a local rehearsal of the transaction path (four validators, each behind a worker gateway in standalone mode with no proxy in front, and one RPC node forwarding to the gateway URLs in the validators' records):

- Each gateway allows one client IP 100 requests a second, a burst of 200, and 32 connections. Every forward from the RPC node counts against the RPC node's address.
- All transfers of one sender went to one validator's gateway first (gateway 1 here), so a busy sender's whole load lands on one gateway.
- 400 presigned transfers from one sender, posted to the RPC node with 8 threads in 0.07 s (HTTP 200 x 400): about 210 forwards reached gateway 1 within a second and drew one 429 (`rejections_total{reason="rate_limited"} 1`).
  The RPC node set gateway 1 aside for 30 s, requeued 61 transfers (`requeued_total 61`) and sent the rest to validator 4. All 400 confirmed with status 1: first receipt 1.09 s, median 3.12 s, last 4.65 s.
- The gateway logs no warning for the 429. The RPC node logs:
  ```
  level=warn target=worker::forward message="demoting unreachable validator RPC endpoints from forward admission" demoted=1 cooldown_secs=30
  ```
  It names neither the endpoint nor the validator. Finding which one took `tn_worker_submit_usable_members` (3 instead of 4) and each gateway's `tn_worker_gateway_rejections_total`.
- A gateway that is starting answers 503 until its worker is ready, 11 s after the gateway's start (11.8 s on a restart), and the RPC node sets it aside for 30 s for that too. A rolling restart of the gateways therefore concentrates forwards on the others for a while.

## Evidence

- devnet-genesis `tasks/l2/rh5-report.md`: local docker run, 2026-11-17 21:05-21:14 UTC, node and gateway images built from 5533ff73a. The 400-transfer burst is its question Q7 (demotion line at 21:13:01.647 UTC); the 503 and restart timings are Q6 (`/ready` 200 at 21:06:35 on first start, 21:12:18.16 on restart). Counters are the gateway's and RPC node's Prometheus metrics before and after.
- One run, one sender, 400 transfers. Higher sustained rates were not tried.
- The one-sender-one-gateway pattern is from the run's logs and counters; the code that picks the first validator was not read.

## Where in the code

At 5533ff73a, read from code, not run:

- `crates/tn-reth/src/forward.rs:183`: `UNREACHABLE_COOLDOWN = 30 s`. `:885-900`: once a task ends, the endpoints it demoted are counted and logged with `demoted` and `cooldown_secs` only; the endpoint list is at hand but not logged.
- `bin/worker-gateway/src/cli.rs:480-486`: `--rate-limit-per-ip`, default 100. The client IP is the TCP peer, or the client a peer listed in `--trusted-proxies` forwarded for. `:491`: the burst, default 0, meaning twice the rate. The test at `:2812` asserts `max_connections_per_ip` defaults to 32.
- `git grep` finds no `X-Forwarded-For` or PROXY header in `crates/tn-reth/src/forward.rs`, so the forwarder appears not to present the original client (the request construction was not read in full).

## What is not known

- The sustained rate one RPC node can carry before 429s repeat.
- Why gateway 2 received 41 forwards that no block of validator 2 holds; the run's reading is re-sends of requeued transfers mined elsewhere.
- The 30 s cooldown seemed to reset at an epoch change. Inferred from timing only.
- What happens when a proxy sits in front of the gateway, as on mainnet: see {{gateway-keepalive-close-after-429}}.

## What could be done (suggestions, none tried)

- Name each demoted endpoint and its validator in the warning.
- Have the forwarder present the original client, so a gateway that lists the RPC node in `--trusted-proxies` meters each user rather than the RPC node.
- Treat a 429 and a not-ready 503 apart from an unreachable endpoint, for example with a shorter cooldown for them.
- Document raising `--rate-limit-per-ip` for a known RPC node. The tn-node-deployment installer (PR #68's `gw_render_args`, `lib/gateway.sh:543`) renders no limit flag, so the default applies.

## Related

- {{gateway-keepalive-close-after-429}}: with a proxy in front, a 429 can become a 502, which also demotes.
- {{forwarder-rejected-warning-for-included-txs}}: another forwarder warning that overstates trouble.
- {{publish-worker-gateway-image}}: the gateway image used here.
