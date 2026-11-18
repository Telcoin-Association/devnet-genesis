# Sources: l2-rpc-private-address-bind

| Item in the draft | Source | Status |
|---|---|---|
| Claim: RPC cannot bind a private address only, local readers hard-code loopback, wildcard bind guarded by ufw | `tasks/challenges-l2.md` row 4 (no file:line cited) | taken from the row, source not re-read |
| "a firewall reset needs `gateway_upstream=off` around it" | `tasks/challenges-l2-report.md` section 2.13 | taken from the report, source not re-read |
| `set_gateway_upstream` at PR head `edit-config.sh:2834`, comment 2815-2833 (0.0.0.0 binds, TN_RPC_ADDR, GATEWAY_UPSTREAM, ufw guards, off -> 127.0.0.1) | `git -C tn-node-deployment show 79fb24e…:edit-config.sh \| sed -n '2815,2834p'` | checked |
| PR head `edit-config.sh:123`, `:140-141` help; `:2857` `--http.addr 127.0.0.1` | `git grep -nE 'http\.addr\|--healthcheck[ =]' 79fb24e… -- edit-config.sh` | checked |
| main has no `gateway_upstream`; `setup-node.sh:2774`, `:2783` `--http.addr 127.0.0.1 --ws.addr 127.0.0.1` | same grep at `origin/main` (no gateway_upstream lines in edit-config.sh) | checked |
| Loopback readers: 5 in setup-node.sh, 3 in migrate-node-naming.sh, 1 in install-caddy.sh, both refs | `git grep -cE '127\.0\.0\.1:(\$\{?RPC_PORT\|8545\|\$\{?HEALTH)' <ref> -- '*.sh' 'lib/*.sh'` | checked (count only; lines not read) |
| `tn_local_rpc_url` | named in the comment at PR head `edit-config.sh:2823` | checked (helper not read) |
| Gateways on their own hosts (gateway-4-devnet) | report section 2.13 (row 53 text) | taken from the report, source not re-read |
| Which readers break on a private bind; `--healthcheck <ip>:<port>` | none | not verifiable here |
