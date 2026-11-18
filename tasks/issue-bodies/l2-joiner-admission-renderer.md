# setup-node.sh writes committee_peers from the --bootstrap-peers map, so a joiner cannot bootstrap from a hub alone

`setup-node.sh --admission` fills the node's `committee_peers` from the same file it passes as `--bootstrap-peers`; no option takes a separate committee map.
A validator that joins after genesis, and should dial one hub at start while naming the genesis committee as its committee peers, cannot be set up with the scripts.

## What happens

The setting is a devnet in mainnet shape: four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis.
The allowlist on the validators drops the fifth node until it is in the committee, so it has to bootstrap from a node the allowlist does not gate (here the RPC node), and its `committee_peers` should still be the four genesis validators.

The scripts have one input for both:

- `--bootstrap-peers <file>` is installed as `/etc/telcoin/bootstrap-peers.yaml` and passed to the node as `--bootstrap-peers` at every start.
- `--admission <mode>` writes `committee_peers` from that same file. The help says: "committee_peers from the --bootstrap-peers map (each left out when its flag is)".

A joiner set up with the scripts therefore gets one of three layouts, none of which is the one it needs:

- bootstrap peers and committee peers both the four validators: at start it dials only peers whose allowlist drops it until its activation;
- both the hub: `committee_peers` names a node outside the committee and leaves out every member;
- no `--bootstrap-peers`: `committee_peers` is left out and the node starts from the genesis bootstrap servers, again the validators.

The node checks a non-empty `committee_peers` against the committee: a missing member is an error at epoch 0 and a warning in later epochs ("discovery covers this gap until the inventory is updated"). That is read from the node's code, not run with a hub-only map.

The devnet did not use the scripts for this. It wrote the fifth node's network-config with its own renderer, which gives a non-committee node `bootstrap_peers` = the hub and `committee_peers` = the genesis `bootstrap_servers` of `committee.yaml`.

## Evidence

- The scripts' behaviour is read from code, not run: the lines below, at both refs.
- No `--committee-peers` option: `git grep -c -- '--committee-peers'` over `*.sh` finds nothing at either ref.
- The devnet's own renderer: devnet-genesis fact sheet `tasks/l2/facts/dg-core.md` (its composition of `committee_peers` and `bootstrap_peers`), taken from the sheet.
- The node's `committee_peers` rule: fact sheet `tasks/l2/facts/node-side.md` (telcoin-network at 5533ff73a, the image's commit), taken from the sheet, not re-read.
- The run itself (2026-11-17, the fifth node joining with the devnet's config) is in the challenge list as row 8, open, with no log attached.

## Where in the code

At `origin/main` 2813343 (scripts 2.1.0) and at PR #68's head 79fb24e (scripts 2.2.0); the cited ranges are identical at both, so the problem is on both.

- `setup-node.sh:85-95`: help for `--bootstrap-peers`, the file passed to the node at every start.
- `setup-node.sh:105-112`: help for `--admission`, with `committee_peers` taken from the `--bootstrap-peers` map.
- `setup-node.sh:2666-2671` (`setup_admission_config`): `committee` is `${CONFIG_DIR}/bootstrap-peers.yaml` when `--bootstrap-peers` was given, otherwise `none`; it goes to `tn_network_config_render` with the mode and the trusted-nodes file.
- `lib/common.sh:2844` (`tn_network_config_render`): writes `admission`, `trusted_nodes` and `committee_peers` into `${DATA_DIR}/network-config`.

## What is not known

- What the node does at a later epoch with a `committee_peers` that holds only a non-committee hub: warnings per missing member are expected from the code; whether the hub entry is accepted was not checked.
- Whether `edit-config.sh` can set a separate committee map after setup; its admission edits re-render `committee_peers` from the bootstrap map according to the fact sheet (not re-read).

## What could be done (suggestions, none tried)

- Add `--committee-peers <file>` to `setup-node.sh` and `edit-config.sh`, defaulting to the `--bootstrap-peers` map so today's behaviour stays for genesis validators.
- Or document that a joiner leaves `--bootstrap-peers` to the hub and gets `committee_peers` from `committee.yaml`'s `bootstrap_servers`, and render it that way when the node is not in the genesis committee.

## Related

- {{admission-map-complex-keys}}: the same renderer, refusing a map written by PyYAML.
- The joiner's slow sync behind the allowlist (the same run): the reason a joiner wants a hub as its bootstrap peer.
- PR #68 does not change these lines.
