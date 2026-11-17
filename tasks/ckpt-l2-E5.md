status: done
updated: 2026-11-17T20:15:06Z
completed sections:
- read: rules, contract 1/3.3/7/12, units E5+gates, facts gateway-binary 2-6, image-probes
- wrote TND tools/tests/gateway_smoke.sh (321 lines) + tools/tests/gateway_smoke_stubs.py (280 lines)
- run 1: 41/43 (stub Nagle delay, client did not reopen closed conns) -> fixed in stub/client only
- run 2 rc=0 43/43; run 3 rc=0 43/43; --keep run rc=0 (40 ok, 1 skip), its removal verified
- gates: bash -n 0, shellcheck error 0 / warning 0 / all 0, check-bash32 0, check-perl-interp 0, check-network-hits 0, py_compile 0
- run.sh (no args): 78 files, none named *smoke*; exit 1 from host_baseline_test.sh (install-caddy check; file modified by another unit), not E5
- finding: 429 has no Connection: close but the gateway closes the keep-alive connection (next request BrokenPipe)

## run 3 output (full)
```
info: ports worker=19077 health=18779 query=18139 listen=19637 probe=19922 metrics=18079
info: gw_render_args: --listen-addr 127.0.0.1:19637 --probe-addr 127.0.0.1:19922 --metrics 127.0.0.1:18079 --upstream-rpc-url http://127.0.0.1:19077 --upstream-readiness-url http://127.0.0.1:18779/health/workers --worker-id 0 --redirect-queries http://127.0.0.1:18139 --trusted-proxies 127.0.0.1/32
ok    gw_render_args: the contract 3.3 line for same-host, front caddy
ok    smoke docker run options = gw_unit_text ExecStart (name and -d aside)
ok    docker run -d starts the gateway
ok    container running after 3 s
ok    /health 200 on the probe listener
ok    /health 200 on the main listener
ok    the gateway polls the health stub
ok    /ready 503 while the worker is not accepting
ok    submission while not ready: HTTP 503, JSON-RPC -32000
ok    submission while not ready reaches neither stub
ok    eth_blockNumber while not ready: answered by the query stub
ok    eth_blockNumber while not ready: query stub logged it, worker did not
info: /ready answered 200 after 7s
ok    /ready 200 within 15 s of the worker accepting
ok    /ready/any 200
ok    submission when ready: HTTP 200
ok    submission reaches the worker stub, not the query stub
info: worker stub saw: id=sub-ready method=eth_sendRawTransaction batch=0 xff=203.0.113.9,127.0.0.1 xfp=http xtg=1 xtgr=-
ok    the submission carries X-Forwarded-For with the client 203.0.113.9
ok    eth_blockNumber: answered by the query stub
ok    eth_blockNumber: never reaches the worker stub
ok    tn_nodeMode: answered by the query stub
ok    tn_nodeMode: never reaches the worker stub
ok    the query stub sees X-TN-Gateway-Redirect: 1
ok    eth_getTransactionCount pending: answered by the worker stub
ok    eth_getTransactionCount pending: worker stub only
ok    GET / answers 405
ok    a WebSocket upgrade answers 405
ok    a body over 1 MiB answers 413
ok    the oversized body reaches neither stub
ok    a batch mixing a submission and a read: HTTP 200
ok    the mixed batch goes whole to the query stub
info: burst: a200=211 a429=389 aother=0 b200=50 b429=0 bother=0 t_a=0.121 t_b=0.074 bound=213 certain=1 same_second=1 acodes=200:211,429:389,reconnects:346 bcodes=200:50
ok    burst: 600 calls outrun a 200-token, 100/s bucket (certain)
ok    burst: 198.51.100.7 gets 429 answers
ok    burst: 198.51.100.7 admitted no more than the bucket allows
ok    burst: 198.51.100.7 got only 200 or 429
ok    198.51.100.8 in the same second: never throttled
ok    the metrics listener answers 200
ok    tn_worker_gateway_upstream_ready is 1
ok    tn_worker_gateway_routed_requests_total route=worker is non-zero
ok    tn_worker_gateway_routed_requests_total route=query is non-zero
ok    tn_worker_gateway_rejections_total reason=rate_limited is non-zero
info: metrics: tn_worker_gateway_routed_requests_total{route="query",result="forwarded"} 265 tn_worker_gateway_routed_requests_total{route="worker",result="forwarded"} 2 tn_worker_gateway_mixed_batches_total 1 tn_worker_gateway_rejections_total{reason="method_not_post"} 2 tn_worker_gateway_rejections_total{reason="no_upstream_ready"} 1 tn_worker_gateway_rejections_total{reason="rate_limited"} 389 tn_worker_gateway_rejections_total{reason="request_too_large"} 1 tn_worker_gateway_upstream_ready{worker_id="0",upstream="http://127.0.0.1:19077"} 1 
info: docker stop took 0s
ok    docker stop -t 60 succeeds
ok    docker stop returns before the 60 s kill
ok    the container exits with status 0
info: gateway WARN/ERROR lines: 3

43 checks, 0 failures, 0 skipped
```
