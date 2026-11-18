# Sources: l2-healthcheck-bare-port-binds-loopback

TND = /home/drtnarg/coding/telcoin/tn-node-deployment, M = origin/main (2813343), P = 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (PR #68 head). TN = telcoin-network at 5533ff73a.

| Item in the draft | Source | Status |
|---|---|---|
| Claim: bare port binds loopback, scripts still write it with a ufw rule | `tasks/challenges-l2.md` rows 3 and 38; report section 2.4 | checked against code below |
| "read from code, not run against a real monitor" | row 38 ("read from code"), report 2.4 ("Read from code; not run against a real monitor") | taken from the row, source not re-read |
| `health_flag_add` injects `--healthcheck ${TN_KUMA_PORT}`, `setup-observability.sh:78-90` | `git -C TND show M:setup-observability.sh \| sed -n '78,90p'`; `git grep -n healthcheck` at M and P (same line numbers 78, 84, 87) | checked (both refs) |
| Row 38 cites `setup-observability.sh:84` | line 84 is the `obs_inject_flags ... "--healthcheck ${TN_KUMA_PORT}"` call at both refs | checked, matches |
| `lib/common.sh:9693-9694` (M), `:9727-9728` (P), node-launch flag tail | `git grep -n healthcheck M/P -- lib/common.sh` | checked (both refs) |
| `TN_KUMA_PORT="43174"`, `lib/testnet-addons.env:40` | `git grep -n "TN_KUMA_PORT=" M -- lib/` | checked at M only |
| Comment `setup-observability.sh:147` "(--healthcheck binds on every interface)" | `sed -n '144,149p'` at M; grep at P shows the same line 147 | checked (both refs) |
| Comment `setup-observability.sh:356-357` and warnings `:359-363` ("reachable from the INTERNET") | `sed -n '350,366p'` at M; grep at P shows line 356 identical | checked at M, line 356 at P by grep |
| Comment `lib/common.sh:11160-11161` (M), `:11194-11195` (P) | `sed -n '11155,11166p'` at M; grep at P gives 11194 | 11160-11161 checked at M; 11194 checked at P by grep, 11195 inferred |
| `require_testnet` refuses off testnet, `lib/common.sh:9205-9212` (M) | `sed -n '9205,9212p'` at M | checked at M |
| `check-node.sh:2138-2151` fails a mainnet node with `--healthcheck` | `git grep -n -i "mainnet.*healthcheck" M -- check-node.sh` | checked at M (lines 2138, 2151 by grep) |
| README quote "From the next release a bare `--healthcheck <port>` binds `127.0.0.1` only. The scripts pass the bare port …" | `git grep -n "next release a bare" M -- README.md` (line 454); `git show P:README.md \| sed -n '453,460p'` (line 455) | checked (both refs) |
| `v0.16.0-adiri` does not accept the address form; on-host probes reach a loopback bind | P README.md:455 | checked at P |
| PR #68 writes `--healthcheck 0.0.0.0:43174` for `gateway_upstream`, `edit-config.sh:2817` (P) | `git grep -n "healthcheck 0.0.0.0" P` | checked at P (comment line; code below it not read) |
| TN `crates/node/src/health.rs:21-23` quote, issue #1689 | `git -C TN show 5533ff73a:crates/node/src/health.rs \| sed -n '18,26p'` | checked |
| TN CLI README `:356` flag table, "binds `127.0.0.1`" | `git grep -n -i healthcheck 5533ff73a -- crates/telcoin-network-cli/**` | checked |
| Devnet in mainnet shape, 2026-11-17 | brief and challenge report | taken from the row, source not re-read |
| "load-balancer checks" | row 3 wording; no LB reader found in the lines read | not verifiable here |
| Report 2.4 "which mainnet will run" | contradicted: add-on refused on mainnet (`require_testnet`, `check-node.sh`) | checked; draft corrects it |
