# Fact sheet: worker-gateway + node-record-api binaries (TN 5533ff73a)
status: done
completed: 1, 2, 3, 4, 5, 6, 7, 8
Unit F-GW1, read-only. Paths relative to `tn-l2-img/`. `[I]` = inferred, not read. `cli.rs` = `bin/worker-gateway/src/cli.rs`.
## 1. CLI (`cli.rs:62-681`, binary name `worker-gateway`, `bin/worker-gateway/Cargo.toml:12-13`)
clap derive, `#[command(author, version, about, long_about = None)]` (cli.rs:62). Every flag is `long`
only (no short forms); long name = kebab-case field name except `--metrics`. Durations use
`humantime::parse_duration` (`500ms`, `5s`, `10m`, `1h`). CIDR lists are comma-separated, bare IP = /32|/128.
No flag is required by clap; at startup one upstream source is required (see rules below).

| Flag | Env var | Type / default | Meaning (cli.rs line) |
|---|---|---|---|
| `--listen-addr` | `WORKER_GATEWAY_LISTEN_ADDR` | SocketAddr, `0.0.0.0:8545` | client JSON-RPC + `/health` + `/ready` (66); same port as the worker RPC default, so set it on a shared host (RM:97-101) |
| `--probe-addr` | `WORKER_GATEWAY_PROBE_ADDR` | SocketAddr, unset = no listener | second listener, probes only, no conn cap, no rate limit (76) |
| `--config` | `WORKER_GATEWAY_CONFIG` | path to YAML | upstream list; conflicts with `--upstream-rpc-url`, `--upstream-readiness-url`, `--worker-id` (81-86) |
| `--upstream-rpc-url` | `WORKER_GATEWAY_UPSTREAM_RPC_URL` | http(s) URL | worker JSON-RPC base URL, e.g. `http://127.0.0.1:8545` (90) |
| `--upstream-readiness-url` | `WORKER_GATEWAY_UPSTREAM_READINESS_URL` | http(s) URL | node readiness URL, e.g. `http://127.0.0.1:8551/health/workers` (95) |
| `--worker-id` | `WORKER_GATEWAY_WORKER_ID` | u16, `0` | worker id looked up in the readiness answer (99) |
| `--redirect-queries` | `WORKER_GATEWAY_REDIRECT_QUERIES` | http(s) URL, unset | endpoint for every non-submission call (115) |
| `--redirect-queries-header` | `WORKER_GATEWAY_REDIRECT_QUERIES_HEADER` | one `Name: value` line | header sent only to the redirect endpoint; never logged (130) |
| `--redirect-queries-header-file` | `WORKER_GATEWAY_REDIRECT_QUERIES_HEADER_FILE` | path | same line read from file, whitespace trimmed (138) |
| `--recent-submission-ttl` | `WORKER_GATEWAY_RECENT_SUBMISSION_TTL` | duration, `60s`; `0` off | remember accepted tx hashes (max 10,000) for by-hash lookups (149-155) |
| `--denied-method-prefixes` | `WORKER_GATEWAY_DENIED_METHOD_PREFIXES` | comma list, `tn_,debug_,trace_,admin_` (30) | refused prefixes, only WITHOUT `--redirect-queries`; empty = allow all (165-171) |
| `--readiness-poll-interval` / `--readiness-poll-timeout` | `WORKER_GATEWAY_READINESS_POLL_INTERVAL` / `WORKER_GATEWAY_READINESS_POLL_TIMEOUT` | duration, `5s`; duration, `2s` | readiness poll cadence (175-181); per-poll timeout (also redirect probe) (186-192) |
| `--readiness-failure-threshold` / `--readiness-success-threshold` | `WORKER_GATEWAY_READINESS_FAILURE_THRESHOLD` / `WORKER_GATEWAY_READINESS_SUCCESS_THRESHOLD` | NonZeroU32, `3`; NonZeroU32, `2` | consecutive fails -> not-ready (197); consecutive passes -> ready (203) |
| `--upstream-failure-threshold` | `WORKER_GATEWAY_UPSTREAM_FAILURE_THRESHOLD` | u32, `3` | consecutive failed forwards that mark the worker down (215) |
| `--upstream-connect-timeout` / `--upstream-request-timeout` | `WORKER_GATEWAY_UPSTREAM_CONNECT_TIMEOUT` / `WORKER_GATEWAY_UPSTREAM_REQUEST_TIMEOUT` | duration, `2s`; duration, `35s` | connect timeout to an upstream (220-226); deadline for upstream response head (238-244) |
| `--query-request-timeout` | `WORKER_GATEWAY_QUERY_REQUEST_TIMEOUT` | duration, default `10s` (1393) | deadline for the redirect endpoint (254-259) |
| `--upstream-ca-cert` | `WORKER_GATEWAY_UPSTREAM_CA_CERT` | PEM path | extra CAs for `https` upstreams (265) |
| `--upstream-client-cert` / `--upstream-client-key` | `WORKER_GATEWAY_UPSTREAM_CLIENT_CERT` / `WORKER_GATEWAY_UPSTREAM_CLIENT_KEY` | PEM paths | mTLS to upstream; each requires the other (273-280, 1666) |
| `--dns-cache-ttl` / `--max-concurrent-dns-lookups` | `WORKER_GATEWAY_DNS_CACHE_TTL` / `WORKER_GATEWAY_MAX_CONCURRENT_DNS_LOOKUPS` | duration, `30s`; NonZeroUsize, `8` | cache for resolved upstream names (286-292); (301) |
| `--header-read-timeout` | `WORKER_GATEWAY_HEADER_READ_TIMEOUT` | duration, `10s` | time for request headers (x2 with PROXY) (309-315) |
| `--max-connections` | `WORKER_GATEWAY_MAX_CONNECTIONS` | NonZeroUsize, `500` | open inbound conns; extra ones wait (319) |
| `--max-connections-per-ip` | `WORKER_GATEWAY_MAX_CONNECTIONS_PER_IP` | usize, `32` (server.rs:138) | per-client conns (338-343) |
| `--max-inflight-submissions` | `WORKER_GATEWAY_MAX_INFLIGHT_SUBMISSIONS` | usize, `256` | in-flight submission-only requests (349) |
| `--max-inflight-queries` | `WORKER_GATEWAY_MAX_INFLIGHT_QUERIES` | usize, `256` (1405); `0` unlimited | other requests; over cap -> `503`; w/o redirect lowered to `max-upstream-inflight` minus 1/5 (351-364) |
| `--max-upstream-inflight` | `WORKER_GATEWAY_MAX_UPSTREAM_INFLIGHT` | usize, `100` | concurrent forwards to the worker (381) |
| `--tcp-user-timeout` | `WORKER_GATEWAY_TCP_USER_TIMEOUT` | duration, `30s` | `TCP_USER_TIMEOUT` on inbound sockets (393-399) |
| `--max-connection-duration` | `WORKER_GATEWAY_MAX_CONNECTION_DURATION` | duration, `10m` | total lifetime cap per inbound conn (415-421) |
| `--max-request-bytes` | `WORKER_GATEWAY_MAX_REQUEST_BYTES` | NonZeroUsize, 1 MiB | body cap (431-436); below 263,168 B (48) only warns |
| `--max-batch-len` | `WORKER_GATEWAY_MAX_BATCH_LEN` | usize, `50` (proxy.rs:116); `0` = no limit [I from doc cut] | calls per batch (445-450) |
| `--max-inflight-request-bytes` | `WORKER_GATEWAY_MAX_INFLIGHT_REQUEST_BYTES` | u32, 536870912 (server.rs:119) | body bytes held across in-flight requests (459-464) |
| `--http1-max-buf-size` | `WORKER_GATEWAY_HTTP1_MAX_BUF_SIZE` | usize, 65536 (server.rs:123) | per-conn read buffer (473-478) |
| `--rate-limit-per-ip` / `--rate-limit-per-ip-burst` | `WORKER_GATEWAY_RATE_LIMIT_PER_IP` / `WORKER_GATEWAY_RATE_LIMIT_PER_IP_BURST` | u32 req/s `100` (`0` off) / u32 `0` (= 2x rate) | per client prefix (486); (491) |
| `--rate-limit-per-ip-v6-prefix` / `--rate-limit-per-ip-v4-prefix` | `WORKER_GATEWAY_RATE_LIMIT_PER_IP_V6_PREFIX` / `WORKER_GATEWAY_RATE_LIMIT_PER_IP_V4_PREFIX` | u8, `64` (ratelimit.rs:313); u8, `32` (ratelimit.rs:320) | IPv6 key mask (503-508); IPv4 key mask (519-524) |
| `--rate-limit-global` / `--rate-limit-global-burst` | `WORKER_GATEWAY_RATE_LIMIT_GLOBAL` / `WORKER_GATEWAY_RATE_LIMIT_GLOBAL_BURST` | u32 req/s `3000` (`0` off) / u32 `0` (= 2x rate) | gateway-wide (529); (534) |
| `--rate-limit-submissions` | `WORKER_GATEWAY_RATE_LIMIT_SUBMISSIONS` | u32 req/s, `0` off | separate global budget for submission-only requests (536-547) |
| `--rate-limit-per-ip-max-entries` | `WORKER_GATEWAY_RATE_LIMIT_PER_IP_MAX_ENTRIES` | NonZeroUsize, `100000` (ratelimit.rs:117) | per-IP table size (557-562) |
| `--trusted-proxies` | `WORKER_GATEWAY_TRUSTED_PROXIES` | CIDR list, unset = trust none | see section 5 (563-577) |
| `--proxy-protocol` / `--proxy-protocol-from` | `WORKER_GATEWAY_PROXY_PROTOCOL` / `WORKER_GATEWAY_PROXY_PROTOCOL_FROM` | bool switch, off; CIDR list, default = trusted-proxies | expect PROXY v2 (binary) header from listed peers (579-591); peers that must send PROXY v2 (593-603) |
| `--shutdown-delay` | `WORKER_GATEWAY_SHUTDOWN_DELAY` | duration, `0s`, max `60s` (35) | keep serving after SIGTERM with `/ready` = 503 (605-619) |
| `--graceful-shutdown-timeout` | `WORKER_GATEWAY_GRACEFUL_SHUTDOWN_TIMEOUT` | duration, default request+header timeout (45s) | in-flight drain (621-633) |
| `--metrics` | `WORKER_GATEWAY_METRICS_ADDR` | SocketAddr, unset = no metrics | `GET /metrics` listener (635-640) |
| `--cors-allowed-origins` | `WORKER_GATEWAY_CORS_ALLOWED_ORIGINS` | `scheme://host[:port]` list or `*` | CORS off when unset (642-649) |
| `--access-log-sample` / `--access-log-max-lines-per-second` | `WORKER_GATEWAY_ACCESS_LOG_SAMPLE` / `WORKER_GATEWAY_ACCESS_LOG_MAX_LINES_PER_SECOND` | f64 0..=1 `0` / u32 `1000` (`0` unlimited) | access log (target `gateway::access`) (651-659); (661-670) |
| `--log-filter` | `RUST_LOG` | string, `info` | tracing filter (673-674) |
| `--log-format` | `WORKER_GATEWAY_LOG_FORMAT` | `text` or `json`, `text` | colour only on a TTY with `NO_COLOR` empty (676-681) |

Startup rules (all exit 1 with `Error: ...` on stderr, main.rs:34-38):
- Upstream source: `--config` OR both `--upstream-rpc-url` and `--upstream-readiness-url`, else
  `"provide --config, or both --upstream-rpc-url and --upstream-readiness-url"` (cli.rs:1251).
  YAML: top key `upstreams:` list of `{worker_id, rpc_url, readiness_url}` (config.rs:14-23,47-49);
  duplicate ids fail (cli.rs:1366); empty list `"no upstream workers configured"` (896).
- `--readiness-poll-timeout` must be <= `--readiness-poll-interval` (875); `--upstream-request-timeout`
  must be > `--upstream-connect-timeout` (887); query timeout <= upstream request timeout (934).
- `--redirect-queries-header[-file]` require `--redirect-queries` (1286) and exclude each other (1274).
- `--proxy-protocol-from` requires `--proxy-protocol` (1062); `--proxy-protocol` requires a non-empty
  `--proxy-protocol-from` or `--trusted-proxies` (1076). `--shutdown-delay` max 60s (1158).
- `--redirect-queries` must not hit the gateway itself or a worker's RPC/readiness host:port (1809-1860,
  1963-1976); `--probe-addr` must not overlap `--listen-addr` on the same port (1994-2010).
- Parse errors exit with clap's status (2 for usage, main.rs:46-52,232), redacted. fd limit raised at start (main.rs:59).
- `--version`: clap `version` = crate version (`version.workspace = true`, Cargo.toml:3); no build.rs
  and no git hash wiring found in the crate -> no commit hash [I]; printed name is the clap default
  (package `tn-worker-gateway`) [I]. Workspace version value not read (outside read list).
## 2. Listeners and HTTP surface (`bin/worker-gateway/README.md` = `RM`)
Sockets: (a) client `--listen-addr` (default `0.0.0.0:8545`, cli.rs:66); (b) optional probe listener
`--probe-addr` (cli.rs:76); (c) optional metrics listener `--metrics` (cli.rs:639). Nothing else listens [I].
Main listener (RM:741-756, 758):
- `POST` to ANY path except the probe paths = JSON-RPC; path and query string are NOT forwarded
  (`POST /` == `POST /anything`) (RM:751-752, RM:32).
- `GET /health` liveness, always `200 OK` while the process runs (RM:743).
- `GET /ready` `200` when >= 1 upstream ready, else `503` `{"ready": false}`; shutdown delay:
  `503` `{"ready": false, "draining": true}` (RM:744-746).
- `GET /ready/any` `200` when `/ready` would be, or `--redirect-queries` is set and its probe finds the
  query URL up; body `{"ready": bool, "submissions": bool, "queries": bool}`; without
  `--redirect-queries` it is exactly `/ready` (RM:747-750). No `/live` path exists [I: not in RM:741-764].
- Probes on main listener: exempt from rate limits but INSIDE the connection cap (RM:758). Non GET/HEAD
  there -> `405`, message "only GET and HEAD are accepted on this path", `Allow: GET,HEAD` (RM:755).
- `GET` (or any non-`POST`) on any other path -> `405`, JSON-RPC `-32600`, reason `method_not_post`
  (RM:754, RM:796), id `null` (RM:773). `OPTIONS` answered locally only with `--cors-allowed-origins` (RM:753).
- WebSocket: out of scope, "HTTP-only. WebSocket (`eth_subscribe`) pass-through is deliberately out of
  scope" (RM:16-19); an upgrade `GET` therefore gets the `405` above [I]; `Upgrade` is a stripped
  hop-by-hop header (proxy.rs:1675).
- Oversized body -> `413`, `-32003`, `request_too_large`; batch over `--max-batch-len` -> `413`,
  `-32003`, `batch_too_long` (RM:786-787). Unparseable head -> hyper's bare `400`/`414`/`431` (RM:778).
- Batch (JSON array): forwarded as one request; a gateway error on a batch is ONE error object, id
  `null`; refused only as a whole, never split; upstream batch answer returned as sent (RM:824-828).
- Every response carries `X-Content-Type-Options: nosniff` (RM:30). Upstream gets `POST` + body +
  `Content-Type` + `X-Forwarded-For`/`X-Forwarded-Proto` + `X-TN-Gateway` (redirect hop:
  `X-TN-Gateway-Redirect`); other headers dropped both ways (RM:26-29). Loop -> `508` `-32004` (RM:788-789).
Probe listener (`--probe-addr`, RM:759-763): serves only `/health`, `/ready`, `/ready/any`; other paths
`404`; non GET/HEAD -> bare `405` `Allow: GET,HEAD`; no conn cap, no rate limit, one request per
connection, head <= 8 KiB else `431`. Must not collide with `--listen-addr` (RM:764).
Error table (RM:780-800): `503 -32000 no_upstream_ready`; `502 -32001 upstream_unreachable`;
`504 -32002 upstream_timeout`; `502 -32013 upstream_answer_lost`; `408/504 -32005 request_timeout`;
`429 -32006 rate_limited`; `400 -32007 invalid_transaction`; `400 -32008 unsupported_transaction_type`;
`400 -32600 unreadable_body`; `503 -32009 overloaded` and `503 -32010 inflight_bytes_exhausted` (both
`Retry-After: 1`, RM:802); `403 -32011 method_not_allowed`; upstream non-JSON error -> `-32012 upstream_error`.
SIGTERM/ctrl-c: shutdown delay then drain (RM:838-853); delay+drain+~2s must fit the stop timeout
(RM:852) -> systemd `TimeoutStopSec` >= 45s+2s at defaults [I].
## 3. Routing (`RM` = worker-gateway README; `proxy.rs` = `bin/worker-gateway/src/proxy.rs`)
The gateway PROXIES; it never answers 3xx. Two routes, `Route::Worker` (label `worker`) and
`Route::Query` (label `query`) (proxy.rs:1808-1822); request class `submission` | `query` (proxy.rs:1884-1897).
Method names match exactly, case-sensitively, after unicode-escape decoding (RM:640).
Names: `eth_sendRawTransaction` (proxy.rs:120), `eth_sendRawTransactionSync` (123),
`eth_getTransactionCount` (135), `["eth_getTransactionByHash", "eth_getTransactionReceipt"]` (139), `"pending"` (146).
WITHOUT `--redirect-queries` (RM:613-634):
- (a) forwarded: every call not denied, to the first ready worker in config order, no load balancing (RM:20).
- (c) refused: `method` starting with a `--denied-method-prefixes` entry (default `tn_,debug_,trace_,admin_`;
  case-sensitive, anchored): `403`, JSON-RPC `-32011`, message `"method not allowed through this gateway"`
  (error.rs:285), with the request `id` (RM:616). So `tn_nodeMode` -> `403`/`-32011` [I from prefix `tn_`].
  A batch holding one refused call is refused whole, one error object, `id` `null` (RM:618).
  Counted as `tn_worker_gateway_rejections_total{reason="method_not_allowed"}`, logged at debug only (RM:634).
- (b) none redirected.
WITH `--redirect-queries <URL>` (RM:636-714): deny list NOT applied (RM:632).
- To worker: `eth_sendRawTransaction`, `eth_sendRawTransactionSync`, a batch made ONLY of those (RM:639,650);
  single `eth_getTransactionCount` with 2nd param string `"pending"` (any ASCII case); single
  `eth_getTransactionByHash`/`eth_getTransactionReceipt` for a hash this gateway forwarded and the worker
  accepted within `--recent-submission-ttl` (RM:691-708). Worker-route reads are readiness-gated:
  no worker ready -> `503`/`-32000`, never sent to the query URL (RM:710).
- To query URL (proxied by the gateway itself, with `X-TN-Gateway-Redirect: 1`, `X-Forwarded-For`,
  `X-Forwarded-Proto`, optional header; no `X-TN-Gateway`) (RM:656): everything else, incl. `tn_*`,
  `debug_*`, `eth_sendTransaction`, non-JSON bodies, empty batches, and any batch mixing submissions with
  other calls (whole batch, counted in `tn_worker_gateway_mixed_batches_total`) (RM:641,651-653).
  No readiness gate, no fallback to the worker: failure -> `502`/`-32001` or `504`/`-32002` (RM:667,673-678).
- `3xx` from either upstream is passed through WITHOUT `Location` (body -> `-32012` unless JSON) (RM:661).
- Redirecting gateway refuses inbound `X-TN-Gateway-Redirect` (`508`/`-32004`), so never chain two (RM:657-659); UA `tn-worker-gateway/<version>` (RM:664).
- Startup chain-id check: one background `eth_chainId` to first worker and query URL; mismatch -> warning
  only, failure -> info, serves anyway, runs once (RM:735-739).
Batches: K calls cost K rate-limit tokens (RM:582-587); submission-only batches are screened per element
(`400` `-32007`/`-32008`; EIP-4844/EIP-7702/unknown types refused, RM:601) (RM:588-589); never split (RM:825).
## 4. Readiness and start-up (`app.rs` = `bin/worker-gateway/src/app.rs`)
- Poll target = the FULL URL in `--upstream-readiness-url` (or YAML `readiness_url`); there is no separate
  host/port flag. Documented node path `GET /health/workers`, e.g. `http://127.0.0.1:8551/health/workers`
  (cli.rs:93-95, RM:35-36,93). Expected body `{"version": 1, "workers": [{"worker_id": 0,
  "accepting_transactions": true}]}`; a poll passes only if the entry for `--worker-id` has
  `accepting_transactions: true`; unknown fields / newer versions tolerated; body cap 64 KiB (RM:38-58).
- Cadence `--readiness-poll-interval` `5s`, timeout `--readiness-poll-timeout` `2s`, not-ready after 3 fails,
  ready after 2 passes, AT STARTUP TOO: every upstream starts not-ready; at defaults the first worker call
  can be served one interval (~5s) after start (RM:51-55). A `3xx` from the readiness URL = failed poll;
  `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY` are ignored (RM:109-110).
- Passive health: `--upstream-failure-threshold` (3) failed CONNECTS on forwards mark the worker not-ready
  until 2 good polls; `0` disables; query-URL forwards not counted (RM:62-72).
- While not ready: worker-route calls -> `503` / `-32000` `no_upstream_ready` (RM:782); `/ready` `503`;
  `/health` still `200` (RM:743-746). With `--redirect-queries`, non-worker calls still go to the query URL
  and `/ready/any` can be `200` (RM:673-678).
- Node down at start: the process starts and stays up, failing closed [I: RM:51 + poller is a background
  task, app.rs:329-340; nothing at startup contacts the node except the background chain-id check].
- Redirect URL unreachable at start: starts; probe (`eth_chainId` each interval) only drives `/ready/any`;
  chain-id check failure logs at info and "serves anyway" (RM:668, RM:738; app.rs:325-327).
- DNS at start: none found; host names are resolved lazily per request through a caching resolver
  (`--dns-cache-ttl`, dns.rs:14-25), and the self-loop check only knows IP literals and `localhost` (RM:104)
  [I: no startup lookup seen in app.rs:54-420].
- Things that DO exit the process at start (exit 1): any validation in section 1; bind failure of
  `--listen-addr` (server.rs:1161), `--probe-addr` (server.rs:1565) or `--metrics`
  (crates/tn-metrics/src/server.rs:98); an `https` upstream or redirect URL with an empty system CA store and
  no `--upstream-ca-cert`: `"an https upstream is configured but the system root store holds no CA
  certificates, ..."` (app.rs:467-486); TLS client build failure, hint `"cannot build the upstream
  clients; check --upstream-ca-cert, ..."` (app.rs:38,66).
- `readiness-poller`, `rate-limit-gc`, `warning-summaries` are `spawn_critical_task` (app.rs:329-397) [I: ending one ends the process].
## 5. Client identity and limits
- Limits/defaults: section 1 (`--rate-limit-per-ip` 100/s, burst 2x; `--rate-limit-global` 3000/s; key =
  client masked to /32 v4, /64 v6; `--max-connections-per-ip` 32; `--max-connections` 500). Per-IP checked
  first, then global; `0` rate disables a limiter (RM:309-321). A batch of K calls costs K tokens (RM:582).
- `--trusted-proxies`: comma-separated IPv4/IPv6 CIDRs, bare address = one host (cli.rs:563-564). Only a
  request whose TCP peer is inside a range has `X-Forwarded-For` read: every XFF line is one comma chain,
  walked from the RIGHT, listed addresses skipped, first unlisted entry = client; unparsable entry reached
  first, missing/empty header, or all-listed chain -> the peer (RM:418-424). Untrusted peer: attributed to
  the peer "whatever headers it carries"; unset = trust none (cli.rs:565-569). That proxy's
  `X-Forwarded-Proto` is passed on (cli.rs:566). Listed proxies are exempt from the per-IP conn cap (cli.rs:568).
- PROXY v2 (binary) only with `--proxy-protocol`; from `--proxy-protocol-from` peers a missing/malformed/late
  header closes the connection (cli.rs:579-591).
- Over a rate limit: `429`, `-32006`, reason `rate_limited` (RM:792), id `null` at the edge (RM:773);
  counted `tn_worker_gateway_requests_total{outcome="rejected"}` + `tn_worker_gateway_rejections_total{reason=...}`
  (telemetry.rs:312-313). Over the per-IP conn cap: closed before any request is read, counted
  `tn_worker_gateway_connections_refused_total{reason="per_ip_cap"}` (RM:856-917 table).
## 6. Metrics (`--metrics <addr>`, default off; names: telemetry.rs:93-175, labels: telemetry.rs:197-384)
Served by `tn_metrics::start_metrics_server` (app.rs:274-287), which "responds unconditionally, without
parsing the request" (any path) (crates/tn-metrics/src/server.rs:84-85), plus `tn_info{version}` (server.rs:103).
Counters: `tn_worker_gateway_requests_total{outcome=forwarded|rejected|upstream_error|cancelled}`,
`tn_worker_gateway_rejections_total{reason}` (reasons = RM:780-800 column), `tn_worker_gateway_routed_requests_total{route=worker|query,result}`
(results seen: `forwarded`, `body_failed`, `rejected`), `tn_worker_gateway_mixed_batches_total`,
`tn_worker_gateway_connections_refused_total{reason=per_ip_cap|proxy_header}`, `tn_worker_gateway_access_log_suppressed_total`,
`tn_worker_gateway_accept_errors_total{listener,kind}`, `tn_worker_gateway_rate_limit_overflow_total`,
`tn_worker_gateway_dns_lookups_total{result}`. Gauges: `tn_worker_gateway_inflight_requests`,
`tn_worker_gateway_route_inflight{route=submission|query}`, `tn_worker_gateway_upstream_inflight`,
`tn_worker_gateway_inflight_request_bytes`, `tn_worker_gateway_open_connections`,
`tn_worker_gateway_upstream_ready{worker_id,upstream}` (1/0; upstream = RPC origin). Histogram:
`tn_worker_gateway_request_duration_seconds`.
## 7. Image (`bin/worker-gateway/Dockerfile` = `DF`)
- Build from the REPO ROOT: `docker build -f bin/worker-gateway/Dockerfile -t telcoin-worker-gateway:<tag> .`
  (DF:7-10). Context needs `Cargo*`, `bin/`, `crates/`, `chain-configs/`, `tn-contracts/`, `examples/`,
  `patches/`, `vendor/` (DF:54-64). No `ARG`s, no `GIT_SHA` (unlike `etc/Dockerfile`, Makefile:553).
- Builder `rust:1.94-slim-bookworm@sha256:cf9dd0ec...` (DF:30); runtime `debian:bookworm-slim@sha256:7c7b2c96...`
  (DF:77) + `ca-certificates` (DF:84-88). `cargo build --locked -p tn-worker-gateway --bin worker-gateway --release` (DF:73).
- Binary `/usr/local/bin/worker-gateway` (DF:98); `USER 1101:1101` numeric (DF:91-96); `EXPOSE 8545` and
  `8546` (DF:106-107); `ENTRYPOINT ["worker-gateway"]`, no `CMD`, no `HEALTHCHECK` (DF:112).
- No writable path, volume or capability needed [I: no file writes in the read code; logs go to stdout].
- Stop timeout: docker's 10s is too short; DF suggests `docker run --stop-timeout 60` (DF:12-18).
- No Makefile target and no CI: none of the 17 files in `.github/workflows` mentions `worker-gateway`.
## 8. node-record-api (`bin/node-record-api`, README = `NR`, `src/cli.rs` = `NC`)
What: HTTP/JSON daemon that reads BLS-signed `NodeRecord`s from a worker kademlia DHT (via `tn-kad-client`,
QUIC, one `GET_VALUE` per tracked BLS key), verifies each copy, caches in memory and serves them; worker
records carry `RpcInfo { http, ws }`; never runs a node and puts no load on validator RPC (NR:2-24).
Flags (env `NODE_RECORD_API_*`, NC:35-245): `--listen-addr` `0.0.0.0:8080`; `--metrics`; `--chain-id`
(required, no default; wrong value -> empty directory, not an error, NC:43-46); `--worker-id` `0`;
`--bootstrap` multiaddr `/ip4/../udp/../quic-v1/p2p/<peer-id>`, repeatable, comma-separated in env;
`--bootstrap-servers-file`; `--committee-file`; `--keys-file`; `--rpc-url` (live committee via
`tn_getCurrentEpochInfo` + `tn_getCommitteeBlsPubkeys`); `--refresh-interval` `5m`; `--rpc-timeout` `10s`;
`--epoch-grace` `30s`; `--query-timeout` `15s`; `--record-ttl` `24h`; rate limits as gateway (100/s, 3000/s);
`--log-filter` env `NODE_RECORD_API_LOG_FILTER` `info`. No `--trusted-proxies` flag.
Endpoints (NR:128-178, api.rs:212-216): `GET /healthz`|`/health` `200 {"status":"ok"}`; `GET /readyz`|`/ready`
`200` after first cycle with >=1 fresh record else `503 {"error":"not_ready",...}`; `GET /v1/records`,
`GET /v1/records/{key}` (base58 or `0x`-hex; `400 invalid_key`, `404 not_found`); `GET /v1/rpcs` = envelope
`{chain_id, network, generated_at, last_refresh_at, keys_tracked, records:[{bls_pubkey{base58,hex},
network_pubkey, peer_id, multiaddrs, rpc{http,ws}, record_timestamp, ..., stale, copies_seen, verification}]}`
filtered to `rpc != null`. CORS `*` GET/HEAD/OPTIONS; `Cache-Control: public, max-age=30`.
Image: `docker build -f bin/node-record-api/Dockerfile -t telcoin-node-record-api:latest .` (Dockerfile:9);
bases NOT digest-pinned (10, 52); `USER nonroot` (uid 1101, 63-66, by NAME); `EXPOSE 8080` (73);
`ENTRYPOINT ["node-record-api"]` (79).
