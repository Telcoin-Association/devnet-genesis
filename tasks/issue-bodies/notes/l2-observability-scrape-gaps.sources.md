# Sources: l2-observability-scrape-gaps

| Item in the draft | Source | Status |
|---|---|---|
| Claim: no native scrape for gateway metrics, nftables counters or the sync timer | `tasks/challenges-l2.md` row 13 (open, no evidence); report section 2.15 "from the plan, no run evidence" | taken from the row, source not re-read |
| No `worker_gateway` / `nft` / `p2p-allow` / `p2p_allow` in `setup-observability.sh`, `lib/observability.sh` at both refs | `git -C tn-node-deployment grep -c -- <k> <ref> -- setup-observability.sh lib/observability.sh` (all 0; `job_name` 1) | checked (files not read in full) |
| Gateway `--metrics` / `WORKER_GATEWAY_METRICS_ADDR`, unset = no metrics listener | `tasks/l2/facts/gateway-binary.md` lines 53, 76-77 | taken from the fact sheet, source not re-read |
| Series `tn_worker_gateway_*`, `tn_worker_gateway_upstream_ready{worker_id,upstream}`, in-flight gauges | `tasks/l2/facts/gateway-binary.md` lines 196-198 | taken from the fact sheet, source not re-read |
| `telcoin-p2p-allow-sync.timer`, `.service` (`firewall-setup.sh:65-67`) | `tasks/l2/facts/tnd-firewall.md` line 61 | taken from the fact sheet, source not re-read |
| `accept=177128 drop=992`, validator-1-devnet, 16 min after `on`, 02:44Z | `tasks/challenges-l2.md` row 72 | taken from the row, source not re-read |
| Date 2026-11-18 for 02:44Z | run log dirs dated 20261118 (`tasks/l2/w3/d3a/as-run.md` line 17) | checked |
| `main` has no gateway setup | `gateway_upstream` absent on main (see l2-rpc-private-address-bind sources) | checked (indirect) |
| Whether PR #68's gateway setup passes `--metrics` | none | not verifiable here |
