# Sources: l2-scripts-start-stopped-node

TND = /home/drtnarg/coding/telcoin/tn-node-deployment, M = origin/main (2813343), P = 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (PR #68 head). DG = devnet-genesis.

| Item in the draft | Source | Status |
|---|---|---|
| Claims: no finalize `--no-start` (row 15); `edit-config.sh --set` restarts unconditionally (row 16); `setup-observability.sh --json` forces yes and restarts (row 37) | `tasks/challenges-l2.md` rows 15, 16, 37; report section 2.11 | checked against code below where noted |
| `setup-node.sh:2867` `systemctl start "$SERVICE_NAME"`; no `no-start` | `git grep -n -E "no-start\|systemctl (enable --now\|start) " <ref> -- setup-node.sh` at M and P | checked (both refs) |
| Closing JSON "finalized and started" | `git show M:setup-node.sh \| sed -n '3575,3582p'` (see the finalize draft) | checked at M |
| `edit_restart` `edit-config.sh:2370-2382` (M), restart at `:2380` | `git show M:edit-config.sh \| sed -n '2368,2383p'` | checked at M; row 16's `2370-2382` matches |
| `edit_restart` at `:2401` (P) | `git grep -n "^edit_restart()" P -- edit-config.sh` | checked (start line only) |
| `setup-observability.sh:651` `export TN_ASSUME_YES=true   # belt-and-braces: no lib confirm should block` | `git show M:setup-observability.sh \| sed -n '649,652p'`; P by `git grep` | checked (both refs) |
| Line 651 is on the `--json` path | row 37 | taken from the row, source not re-read |
| `lib/observability.sh:1402-1408` (M): early return, `confirm "Restart ${svc} now?"`, `obs_restart_window`, `systemctl restart "$svc"` | `git show M:lib/observability.sh \| sed -n '1399,1409p'`; P `:1405` by grep | checked at M; `:1405` at P; row 37's `1401-1408` matches |
| `confirm` honours `TN_ASSUME_YES` | comment at line 651 | inferred, not read |
| No `is-active` check before these restarts | lines read above; `is-active` hits in `edit-config.sh` are at M `:2328`, `:2340`, `:2362` (after-restart verification region, not read) | checked for the lines read only |
| `STAGED validator-1-devnet state=inactive enabled=enabled`, "staged: finalized, then stopped, enabled (1)", 00:42-00:47 UTC | DG `tasks/l2/w3/d3a/as-run.md:7` | checked |
| Other five hosts staged | DG `tasks/l2/w3/d3a/as-run.md:9` | checked |
| Driver stops nodes again after edit-config / observability steps | row 37 status ("the devnet's staged mode stops the node again"), report 2.11 | taken from the row, source not re-read |
| PR #68 guard for `gateway_upstream` | row 16 status column; `git grep is-active P -- edit-config.sh` shows only the shifted existing lines | not verifiable here (not located) |
