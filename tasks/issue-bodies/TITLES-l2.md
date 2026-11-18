# Launch 2 issue drafts: titles

Local drafts only. NOTHING HERE IS POSTED: the owner decides, draft by draft, whether one is filed.
Bodies: `tasks/issue-bodies/l2-<slug>.md`; each has a sources table in `tasks/issue-bodies/notes/l2-<slug>.sources.md`
(every number, quoted line and file:line with where it comes from and whether it was re-checked).
Rows are those of `tasks/challenges-l2.md`; the report is `tasks/challenges-l2-report.md`. Every title is the body's H1
and at most 120 characters. A reference such as `{{slug}}` inside a body names another draft of this table.
Before any draft is posted it needs a figure-check against its sources table, as the earlier drafts in this directory had.

| # | slug | repository | title | length | rows | advice |
|---|---|---|---|---|---|---|
| 1 | publish-worker-gateway-image | telcoin-network | No CI job builds or publishes the worker-gateway image, and the binary's --version reports no commit. | 101 | 2, 29, 30 | file |
| 2 | joiner-sync-stalls-behind-allowlist | telcoin-network | A node not yet in the validators' P2P allowlists falls up to 476 blocks behind while its dials to them hang. | 108 | 67, 11 | file after the re-read once node 5 is in the allowlists (evidence to add) |
| 3 | log-silent-peer-refusal | telcoin-network | A validator logs nothing when it drops a non-admitted peer, while healthy observers warn about sync once a second. | 114 | 33, 39 | file |
| 4 | forwarder-one-client-per-rpc-node | telcoin-network | An RPC node is one client IP to every worker gateway, so one busy sender drew a 429 and a 30 s demotion. | 104 | 10, 42, 43, 44 | file |
| 5 | gateway-keepalive-close-after-429 | telcoin-network | After a 429 the worker gateway closes keep-alive connections without Connection: close, so Caddy answers 502. | 109 | 35, 75 | file |
| 6 | node-record-api-standalone-build | telcoin-network | bin/node-record-api does not build on its own: SealedHeader is not serde::Serialize without feature unification. | 112 | 28 | file |
| 7 | public-rpc-forwarding-guidance | telcoin-network | Public-RPC docs centre on --forward-txs, which skips the node-record path that worker gateways rely on. | 103 | 9 | hold: a question about which mode is meant for mainnet; no run evidence, the pool's checks not read |
| 8 | forwarder-rejected-warning-for-included-txs | telcoin-network | The RPC node warns that a forwarded transaction was rejected (nonce too low) when it is already included. | 105 | 76 | file; stronger once a forwarder re-send is told apart from a generator double-send |
| 9 | healthcheck-bare-port-binds-loopback | tn-node-deployment | The scripts write a bare `--healthcheck` port, which telcoin-network main binds to loopback, so monitors reach nothing | 118 | 3, 38 | file, to track the fix; testnet and devnet only (mainnet refuses the add-on) |
| 10 | caddy-acme-empty-email | tn-node-deployment | install-caddy.sh sets no ACME email, so Caddy's Let's Encrypt account has no contact and a failed renewal alerts no one | 119 | 54 | file, centred on the missing certificate-expiry check (the expiry-email point is from memory: check it first) |
| 11 | finalize-reports-validators-as-observers | tn-node-deployment | setup-node.sh's finalize JSON calls every node an observer, including genesis validators it has just read as Active | 115 | 51 | file |
| 12 | public-rpc-serves-tn-namespace | tn-node-deployment | The public-RPC launch flags put `tn` in `--http.api`, so a public RPC node serves `tn_admissionSnapshot` to any caller | 118 | 12, 20 | hold: `tn` is in `--http.api` on purpose; a question for the maintainers |
| 13 | p2p-committee-not-scriptable | tn-node-deployment | firewall-setup.sh --p2p-committee refuses --json, waits for a lock rather than a snapshot, and its tool is off PATH | 115 | 7, 23, 68 | file |
| 14 | scripts-start-stopped-node | tn-node-deployment | setup-node.sh has no --no-start; edit-config.sh --set and setup-observability.sh --json start a stopped node | 108 | 15, 16, 37 | file |
| 15 | admission-version-floor-missing | tn-node-deployment | setup-node.sh cannot check a digest-pinned image against the admission floor, so it writes the settings unchecked | 113 | 14, 57 | file |
| 16 | joiner-admission-renderer | tn-node-deployment | setup-node.sh writes committee_peers from the --bootstrap-peers map, so a joiner cannot bootstrap from a hub alone | 114 | 8 | file |
| 17 | admission-map-complex-keys | tn-node-deployment | The admission renderer refuses a map whose BLS keys are YAML explicit keys (`? key`), and its error does not say why | 116 | 32 | file |
| 18 | unknown-flags-exit-zero | tn-node-deployment | firewall-setup.sh, install-caddy.sh and remove-node.sh drop unknown flags silently, so older scripts ignore newer flags | 119 | 17, 18 | file |
| 19 | rpc-private-address-bind | tn-node-deployment | PR #68's gateway_upstream binds a validator's RPC and health check to 0.0.0.0, guarded only by ufw | 98 | 4 | not an issue: code that exists only in PR #68; raise it in that PR's review |
| 20 | observability-scrape-gaps | tn-node-deployment | setup-observability.sh scrapes neither the worker gateway's metrics nor the P2P allowlist's counters and sync timer | 115 | 13 | file; no run evidence (from the plan) |
| 21 | fresh-install-false-alarms | tn-node-deployment | A fresh install warns twice that committee members cannot be counted, and install-ui.sh prints a curl error first | 113 | 52, 64 | file |
| 22 | checksum-sidecar-rule-conflict | tn-node-deployment | gen-checksums.sh and AGENTS.md disagree on when .sha256 sidecars change, and main's ui/requirements sidecar is stale | 116 | 22, 46 | file |
| 23 | check-node-allowlist-and-bootstrap-lines | tn-node-deployment | check-node.sh prints the bootstrap-peers flag's shell text, and shows nothing when the committee allowlist is healthy | 117 | 73, 74 | file |
| 24 | allowlist-status-hides-sources | tn-p2p-allow-sync | The P2P allowlist's status gives counts only, so an operator cannot tell a scanner from a peer missing from the list | 116 | 72 | file; the raw status says "5 IPv4 … (4 keys, 4 floor)", so the fifth address is not accounted for |
| 25 | txgen-amount-in-metric-label | tn-transaction-generator | The transaction generator puts the transfer amount in its metrics' type label, so every transaction is a new series | 115 | 62 | file |
| 26 | txgen-faucet-drip-reverts | tn-transaction-generator | The generator's native faucet drip reverts in eth_estimateGas with LowLevelCallFailure on an image without `faucet` | 115 | 63 | file; cause not verified |

## Not drafted

- ship-rotated-release-key (tn-node-deployment, row 49): the owner is preparing that pull request.
- Rows 45 and 53 (PR #68's own code): for that pull request's review, with `rpc-private-address-bind`.
- devnet-genesis rows (26, 27, 47, 50, 56, 58-61, 65, 69-71, 81; 66, 78 and 84 are already fixed): local follow-ups, listed in the report's section 3.
- Rows 77 and 79-83 (added after the drafts were written): notes or small points; the report's sections 2.5, 2.7, 2.11 and 2.12 carry them. Row 80 (the RPC node's batch limit of 100) and row 82 (`tn_nodeMode` says "CvvActive" before the node votes) are the two that could become telcoin-network issues.
