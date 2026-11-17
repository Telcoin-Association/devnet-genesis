status: done
updated: 2026-11-17T20:15Z

## Completed sections
- part 2 smoke tools/tests/caddy_gateway_smoke.sh: caddy:2.8.4 47/47, caddy:2 (v2.11.9) 47/47; validate both
  combinations "Valid configuration"; XFF '127.0.0.2' (client 203.0.113.9 dropped); 3 MB POST -> 413.
- part 1 fixture tools/tests/caddy_gateway_test.sh: 213 checks, 0 failures (bash 5 and bash:3.2); 3 mutants caught.
- orchestrator note: host_baseline_test.sh refresh-count case rewritten to list the calling functions
  (do_rpc_enable do_rpc_disable do_rpc_advertise do_rpc_unadvertise); new call sites kept (they write
  .node-meta + node-info.yaml and restart the node). install-caddy.sh: comment of caddy_baseline_refresh only.
- gates clean on all four files; run.sh trio (gateway 213, caddy 161, host_baseline 223/3 skipped) rc 0;
  run.sh no-args: 78 files, no smoke script listed; its one failure was the old host_baseline case (run began before the fix).
