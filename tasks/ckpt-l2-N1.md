status: done
unit: N1 (devnet-network-config.py maps / validate --native / role rpc)
updated: 2026-11-17T20:28Z (was 2026-11-17T20:23Z)

## Completed sections
- 0 reading (rules, contract 1/8/9/12/A-5/A-7, units row, facts, rh0) — 2026-11-17T20:23Z

- 1 code: role rpc (native only), maps, validate --native, help/docstring; py_compile ok; existing 27 tests still OK — 2026-11-17T20:28Z
- 2 fixtures: native/committee.yaml (node1-4), native/observers/node6.yaml (derived), native/golden (11 maps), native/rendered (node1/5/6 from the REAL tnd renderer @405af9e) — 2026-11-17T20:33Z
- 3 tests: NativeMapsTests/NativeValidateTests/NativeRefusalTests, 13 new, all pass — 2026-11-17T20:33Z
- 4 gates: py_compile 0; test_network_config 27 -> 40 OK (rc 0); golden diff empty; test_finalize_modes 51 OK (rc 0) — 2026-11-17T20:37Z

## Decisions so far
- rpc role: accepted only by `maps` and `validate --native`; render/validate/merge refuse it (ConfigError, exit 1).
- --hub: optional for maps and validate --native (still required for render; validate without --native errors as before).
- Emitter: reuse _emit_node (plain BLS keys at column 0, byte-stable); bootstrap map checked line-for-line vs committee.yaml bootstrap_servers block.
- rpc: sub-maps kept verbatim (P2pNode declares rpc; TrustedNode deny_unknown_fields does not reach P2pNode).
- Native fixture fleet: committee = existing 3 + node4 (existing keys) ; node5 observer (existing); node6 rpc keys derived from sha256 labels (recipe in file header).
- Scratch: /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/N1/

## Next
- hand-back only
