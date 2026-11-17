status: done
updated: 2026-11-17T20:11Z

## Completed sections
- step 1 (integration, check-node.sh only; diff 38+/57-):
  - gw_status already reports /ready (log line when /health 200 and /ready not 200; "ready"/"not ready" in its ok
    summary) -> check_gateway's two /ready info lines removed. gw_status does NOT check listeners -> D1's kept.
  - gw_status (meta readable) already compares the whole unit with gw_unit_text (image included) -> D1's
    ExecStart-image-vs-IMAGE check removed (it double-counted one drift).
  - check_gateway no longer reads gateway.meta: mode from GW_ST_MODE, health port parsed from
    GW_ST_UPSTREAM_READINESS (both set by gw_status from the unit file without root). The "readable by root only"
    early return is gone; have_fns list trimmed to tn_gateway_installed tn_node_health_bind gw_status.
  - _cn_gw_listener: [::]:P accepted as a wildcard next to *:P.
  - check_gateway_upstream hints: wildcard RPC w/o upstream -> "edit-config.sh, 'RPC access', '1) Private'";
    wildcard --healthcheck w/o upstream -> no edit-config item exists: set --healthcheck 127.0.0.1:<port> in the
    launch file, restart. [::]/:: health bind counted as wildcard too.
  - gates on check-node.sh: bash -n 0, sc error 0, sc warning 0 findings; check_node_unit_test 0, hardening 0.

- step 2 groups written and passing (2026-11-17T20:07Z): tools/tests/gateway_check_remove_test.sh, 105 checks 0 failures under
  bash 5: check_gateway, gateway-only host (whole script), check_gateway_upstream, remove-node.sh.
  Fixture lessons: a gateway-only fixture must not have /var/lib/telcoin (remove-node counts it as a node
  leftover); json_remove called directly needs RM_JSON=true (run_json_mode sets it); DEFAULT_RPC_PORT is readonly
  in common.sh.

- verification (2026-11-17T20:11Z): new test vs D1's committed check-node.sh: 11 failures, all step-1 items; vs edited: 0.
  Gates clean on both files (sc warning 0). check/remove tests all rc 0 except host_baseline_test (1 failure on
  install-caddy.sh's refresh count, from HEAD 6b01c10 unit B, not E4's files). bash 3.2 docker: 101 ok, 1 skip.
- hand-back sent.
