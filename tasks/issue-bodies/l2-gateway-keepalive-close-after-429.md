# After a 429 the worker gateway closes keep-alive connections without Connection: close, so Caddy answers 502.

After a 429 the gateway closes the kept-alive connection without announcing it, and the next request sent on that connection fails; behind Caddy, which fronts every mainnet gateway, that request comes back to the client as a 502.
A client over the rate limit meets it first. Caddy pools its connections to the gateway across clients, so another client or the RPC node's forwarder could draw the 502 too (inferred, not seen).

## What happens

- Without a proxy, one client, against the gateway image built from 5533ff73a: after a 429, the next request on the same connection fails with `BrokenPipe`.
- With Caddy in front, on a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), on 2026-11-18 at 03:01 UTC: one client with 24 persistent HTTPS connections sent 6,000 requests in 11.28 s to validator 1's public gateway address.
  ```
  total {200: 1283, 429: 4360, 502: 357} in 11.28 s
  ```
  The 502s are 6 % of all requests. Each second of the burst had about 100 answers of 200, 430 to 455 of 429, and 25 to 46 of 502.
- The gateway counted `tn_worker_gateway_rejections_total{reason="rate_limited"} 4360`, matching the 429s. Caddy's journal on `validator-1-devnet` (the validator's host) has 357 `http: server closed idle connection`, one per 502.
- In the same window a second client sent 6 requests, one a second, and got 6 answers of 200. The RPC node forwarded 4 transactions through that gateway and logged no demotion. A 502 to another client was therefore not seen.
- A 502 to the RPC node's forwarder would count as a failure and set that validator's gateway aside for 30 s (from the forwarder's behaviour in {{forwarder-one-client-per-rpc-node}}; not seen here).

## Evidence

- Burst counts per second and in total: devnet-genesis `tasks/l2/w3/v/r8b-burst.txt`. The client is `tasks/l2/w3/v/r8b-burst.py`: Python `http.client`, one `HTTPSConnection` per thread kept across requests and replaced only after an exception, 24 threads of 250 requests.
- Gateway counters before (03:01:18 UTC) and after (03:01:34 UTC): `tasks/l2/w3/v/r8b-metrics.txt`. The worker route's `forwarded` count rose by 4 in the window.
- Second client: `tasks/l2/w3/v/r8b-txgen.txt`, 6 lines of `200`, 03:01:28 to 03:01:33 UTC.
- Caddy journal count and the RPC node's lack of a demotion: from the run's notes (devnet-genesis `tasks/challenges-l2.md` row 75); the journal itself is not in the repository.
- The `BrokenPipe` without a proxy: a single-client test on 2026-11-17, from the run's notes (row 35); its log was not re-read for this draft.

## What is not known

- Where the gateway closes the connection. The 429 comes from `GatewayError::RateLimited` (`bin/worker-gateway/src/error.rs:205` at 5533ff73a, raised at `bin/worker-gateway/src/ratelimit.rs:793`); the connection handling after it was not read.
- Whether every 429 ends its connection. There were 357 502s against 4,360 429s; the ratio depends on how Caddy reuses its pool, which was not examined.
- Whether another client's request can draw the 502. Inferred from Caddy's shared upstream connections; not seen in 6 requests of a second client and 4 forwards of the RPC node.

## What could be done (suggestions, none tried)

- Send `Connection: close` on a 429 that ends the connection, so a client or proxy does not reuse it; or keep the connection open after a 429.
- On the deployment side (tn-node-deployment's Caddy block for the gateway): retrying a request whose idle upstream connection was closed, or no keep-alive to the gateway, would hide it.

## Related

- {{forwarder-one-client-per-rpc-node}}: the RPC node is one client to every gateway, so its forwards meet the same limit, and a 502 demotes the gateway.
- {{publish-worker-gateway-image}}: the gateway image this was seen with.
