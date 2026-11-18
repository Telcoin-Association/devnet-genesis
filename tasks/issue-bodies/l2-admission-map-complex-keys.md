# The admission renderer refuses a map whose BLS keys are YAML explicit keys (`? key`), and its error does not say why

`tn_network_config_render` accepts a trusted-nodes or bootstrap-peers map only if its first line is `{`, `key:` or `key: value`; a map written with YAML explicit keys (`? <key>`) is refused.
Anyone who generates the map with PyYAML meets it: `safe_dump` writes the 147-character base58 BLS keys that way, and the message blames the shape of the map.

## What happens

The setting is a devnet in mainnet shape: four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis.
Its map writer first produced the maps with PyYAML's `yaml.safe_dump`. Each top-level key came out as an explicit key, a line `? <147-character BLS public key>` with the value after it, and the renderer stopped with:

```
<path> does not start with a map keyed by BLS public key
```

The file is valid YAML and is a map keyed by BLS public key. The node itself was not asked; the scripts refuse the file before it gets there.

The devnet worked around it by writing the top-level keys as plain `key:` lines by hand.

## Evidence

- Local rehearsal before the live run (2026-11-17), reported in devnet-genesis `tasks/l2/rh0-report.md` (lines 12 and 96-97): the message above, and the 147-character keys.
- PyYAML on this host (6.0.3), checked: `yaml.safe_dump({"A"*128: 1})` and the same with 129 characters both begin with `? `. PyYAML writes a key of 128 characters or more as an explicit key (the shorter threshold was not tested).
- The renderer's test is read from code, not run on a PyYAML file here.

## Where in the code

At `origin/main` 2813343 (scripts 2.1.0) and at PR #68's head 79fb24e (scripts 2.2.0): `lib/common.sh:2870-2960` is identical at both, so the problem is on both.

- `lib/common.sh:2882-2908`: `nest(key, path)`, the awk function that copies the map into `network-config` two spaces deeper.
- `lib/common.sh:2899-2900`: the first non-blank, non-comment line must match `^[{]`, `^[^ \t#{-].*:$` or `^[^ \t#{-].*:[ \t]`. A line `? <key>` begins with `?` and holds no colon, so it fails all three, and line 2900 prints the message.
- The map body is then copied line by line (`out = out "\n  " s`), so explicit keys, once allowed past the first line, would reach the node unchanged; whether the node's YAML parser takes them inside `network-config` was not checked.

## What is not known

- Whether the node accepts `? key` entries in `network-config` if the check let them through.
- Whether `setup-node.sh`'s own check of the bootstrap-peers map with the release's parser (run before the renderer) accepts them; it was not reached in the rehearsal.

## What could be done (suggestions, none tried)

- Name the cause when the first line starts with `? `, for example "explicit YAML keys (`? key`) are not supported; write each key as `key:`".
- Or accept explicit keys whose value follows on a `: ` line, if the node's parser takes them (not checked).
- Or document the accepted forms beside `--trusted-nodes` and `--bootstrap-peers` in the help: block map with plain keys, or a JSON object.

## Related

- {{joiner-admission-renderer}}: the same renderer and the same maps.
- PR #68 does not change these lines.
