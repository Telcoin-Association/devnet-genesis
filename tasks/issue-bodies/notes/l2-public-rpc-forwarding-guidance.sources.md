# Sources: l2-public-rpc-forwarding-guidance

| Item in the draft | Source | Status |
|---|---|---|
| Title, scope row 9 | `tasks/challenges-l2.md` row 9 (no evidence column); report section 4 | checked (title reworded: "advise" -> "centres on") |
| Two modes; dedicated validator; pool + background forward to the validator in its node record | `git -C telcoin-network show 5533ff73a:docs/src/getting-started/public-rpc-nodes.md \| sed -n '1,14p'` (lines 5-10) | checked |
| "so the node-record path above never sees the transaction"; `EthSubmitForwarded` | `git show 5533ff73a:crates/tn-reth/README.md \| sed -n '505,522p'` (line 507) | checked |
| Without `--sanitize-txs` only the `--rpc.txfeecap` guard, decodes nothing at cap 0 | same, line 519 | checked |
| Flag table `crates/telcoin-network-cli/README.md:562-563` | `git grep -nE -- '--forward-txs\|--sanitize-txs' 5533ff73a -- '*.md'` | checked |
| Devnet used the record path; gateway URL in each validator's record | `tasks/l2/rh5-report.md:9-11` | checked |
| RH5 2026-11-17 21:05-21:14 UTC, one transfer end to end | `tasks/l2/rh5-report.md:3,9-11` | checked |
| Gateway is the only pre-check on the record path | row 9 | taken from the row, source not re-read; not verified in code |
| tn-node-deployment renders neither flag | row 9 ("has no script support") | taken from the row, source not re-read |
