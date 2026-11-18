# Sources: l2-joiner-admission-renderer

| Item in the draft | Source | Status |
|---|---|---|
| Claim: the renderer cannot express "bootstrap from a hub, committee peers = genesis set" for a joiner | `tasks/challenges-l2.md` row 8 (open, no evidence column) | taken from the row, source not re-read |
| Title and consequence ("a validator joining after genesis has no native way") | `tasks/challenges-l2-report.md` section 4 table, line 245; section 2.3 | checked |
| Help for `--bootstrap-peers`, `setup-node.sh:85-95` | `git -C tn-node-deployment show origin/main:setup-node.sh \| sed -n '85,95p'` | checked |
| Quote "committee_peers from the --bootstrap-peers map (each left out when its flag is)", `setup-node.sh:105-112` (quote on 108-109) | same command, `sed -n '105,112p'` | checked |
| `setup-node.sh:2666-2671`, `committee="${CONFIG_DIR}/bootstrap-peers.yaml"`, call to `tn_network_config_render` | `git show origin/main:setup-node.sh \| sed -n '2666,2672p'`; `git grep -n` at both refs gives 2667 and 2671 | checked |
| Ranges identical at PR #68 head 79fb24e | `diff` of `sed -n '80,120p;2660,2680p'` at both refs: identical | checked |
| `lib/common.sh:2844` `tn_network_config_render()` | `git grep -n '^tn_network_config_render()'` at both refs | checked |
| Writes `admission`, `trusted_nodes`, `committee_peers` into `${DATA_DIR}/network-config` | `tasks/l2/facts/tnd-node.md` line 24 (LC:2795-2843) | taken from the fact sheet, source not re-read |
| No `--committee-peers` option | `git grep -c -- '--committee-peers' <ref> -- '*.sh'` at both refs: no match | checked |
| Path `/etc/telcoin/bootstrap-peers.yaml`, passed at every start | `setup-node.sh:93-95` help text (in the range above) | checked |
| Node rule: missing member is an error at epoch 0, a warning later; quote "discovery covers this gap until the inventory is updated" | `tasks/l2/facts/node-side.md` line 60 (network.rs:87-92, 238-280 at 5533ff73a) | taken from the fact sheet, source not re-read |
| Devnet renderer: non-committee node gets `bootstrap_peers` = hub, `committee_peers` = `bootstrap_servers` of committee.yaml | `tasks/l2/facts/dg-core.md` lines 193-196 (py:87, 509-518) | taken from the fact sheet, source not re-read |
| Devnet renders node 5's config itself (step 7) | `tasks/l2/facts/dg-core.md` line 138 | taken from the fact sheet, source not re-read |
| edit-config.sh re-renders `committee_peers` from the bootstrap map | `tasks/l2/facts/tnd-node.md` line 57 (EC:1724-1737) | taken from the fact sheet, source not re-read |
| Hub-only `committee_peers` at a later epoch: hub entry acceptance | none | not verifiable here |
