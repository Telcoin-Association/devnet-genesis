# Sources: l2-public-rpc-serves-tn-namespace

TND = /home/drtnarg/coding/telcoin/tn-node-deployment, M = origin/main (2813343), P = 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (PR #68 head). TN = telcoin-network at 5533ff73a. DG = devnet-genesis.

| Item in the draft | Source | Status |
|---|---|---|
| Claim: `tn_*` incl. admission snapshot public on a native public-RPC node; no run evidence | `tasks/challenges-l2.md` row 12; report section 2.9 ("Seeded from the plan; the row has no run evidence") | taken from the row, source not re-read |
| API list for a `0.0.0.0` bind, row 20 cites `edit-config.sh:2702-2775` | row 20; `git show M:edit-config.sh \| sed -n '2700,2706p;2748,2768p'`: `edit_rpc()` at 2704, list at 2760 inside the setter's `0.0.0.0` branch | checked; the range is roughly right (2702 is the closing brace of the previous function) |
| `edit-config.sh:2791` at P | `git grep -n "http.api" P -- edit-config.sh` | checked |
| Setter span 2733-2775 | DG `tasks/l2/facts/tnd-node.md:54` | taken from the row, source not re-read (not cited in the draft) |
| `setup-node.sh:2518-2521` flag string and comment "HTTP limited to eth, net, web3 and tn" | `git grep -n "http.api" M -- setup-node.sh` (2521); `git show M:setup-node.sh \| sed -n '2508,2521p'` | checked at M only |
| No method filter in `install-caddy.sh` | `git grep -n -i -E "tn_\|jsonrpc\|request_body\|@method\|\"method\"" M -- install-caddy.sh` (only unrelated hits) | checked at M only |
| `tn` method names | `git -C TN grep -n '#[method(name = ' 5533ff73a -- crates/` (rpc_ext.rs:133-221, first 13 shown) | checked (list not exhaustive) |
| `admissionSnapshot` doc quotes, `rpc_ext.rs:141-150`, namespace at `:128` | `git -C TN show 5533ff73a:crates/execution/tn-rpc/src/rpc_ext.rs \| sed -n '139,151p'` | checked |
| ext merged `crates/node/src/engine/inner.rs:177` | `git -C TN grep -n "TelcoinNetworkRpcExt::new" 5533ff73a` | checked (merge into which servers not read) |
| Default namespaces `eth, net, web3, rpc, tn`; explicit list must include `tn`; `cli.rs:207-208`, `rpc_server_args.rs:106-112` | DG `tasks/l2/facts/node-side.md:31-33` | taken from the row, source not re-read |
| RPC node `committee_peers 4`, `mode Open` | DG `tasks/l2/w3/d3a/as-run.md:9` ("node6 (rpc-6) "mode Open, committee_peers 4, trusted_nodes none"") | checked |
| Snapshot would expose validators' P2P addresses | inference from the doc + the RPC node's config | not verifiable here (not called) |
| WS listener serves default set incl. `tn` (no `--ws.api` written) | no `ws.api` hit in the greps of `setup-node.sh`, `edit-config.sh`, `lib/common.sh` at M; defaults from facts file | inferred, not verified |
| PR #68 `gateway_upstream` key sets `--http.addr 0.0.0.0` without the list | row 20 status; P `edit-config.sh:2830` comment ("no --http.api") | checked by grep at P |
