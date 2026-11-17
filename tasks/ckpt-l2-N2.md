status: done
unit: N2 (devnet-network-config.sh native mode), worktree /home/drtnarg/coding/telcoin/dg-l2
scratch: /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/N2

## completed sections
- [x] 1 read rules / contract 8,9,12,A-5,A-7 / units N2 + DG gates / facts dg-core 2,6 (2026-11-17T20:21Z)
- [x] 2 read existing script (by range) + baseline gates: file == HEAD; shellcheck/portability before in /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/N2/{sc,port}.before.txt (2026-11-17T20:23Z)
- [x] 3 implement native mode: header, TN_ADMISSION_VIA switch, NODE_IDX selection, maps render, nm_* per-node install/verify/recheck, NC_WHAT summary (2026-11-17T20:26Z)
- [x] 4a gates (bash -n 0, shellcheck -x 0 findings before/after, portability 0) + bench diff HEAD vs new: B1-B7 identical rc/stdout/remote/py (harness /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/N2/h) (2026-11-17T20:29Z)
- [x] 4b native stubbed runs N1-N7 (devnet config, new version): local render, --yes node1/node5/node6, --verify with injected rc 255 + finalized node5, gateway target rc 2, TRUST knob rc 2, jobs 3, local+target rc 2 (2026-11-17T20:33Z)
- [x] 5 bench tests from dg-l2: test_finalize_modes 51 OK rc 0; test_network_config 40 OK rc 0; check_mutations.py rc 5 (0 tests: not a unittest module); test_node_image rc 1, 108 errors ALL scripts_ref() regex on root config.sh TN_NODE_SCRIPTS_REF (G1 placeholder), none from this file (2026-11-17T20:34Z)
- [x] 6 hand-back (2026-11-17T20:34Z)
