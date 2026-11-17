status: done
unit: G2 (devnet-keygen.sh, devnet-genesis-build.sh in dg-l2)
completed:
- S1 reading (rules, contract 8/9/12/A-5/A-7, units G2 row, facts) (2026-11-17T20:21:17Z)
- S2 TND confirm: setup-node.sh keygen accepts --rpc-http alone and neither flag (SN:2286-2291 rpc_args built only when set; ws gated behind http; keytool help: both optional, --rpc-ws requires --rpc-http) (2026-11-17T20:21:17Z)
- S3 devnet-keygen.sh edited (selection = tn_node_indices, gateway refused, rc 2 on bad target before passphrase, tn_role_dir dest, launch-2 RPC flags appended only when set) (2026-11-17T20:24:43Z)
- S4 devnet-genesis-build.sh edited (node 5 = first observer by role; step-1 comment) (2026-11-17T20:24:43Z)
- S5 genesis --help (new image, docker rc 0): every flag genesis.sh passes exists (--datadir --chain-id --bls-passphrase-source --accounts --epoch-duration-in-secs --min/--max-header-delay-ms --max-batch-delay-ms --worker-fee-config); no blocker (2026-11-17T20:26:20Z)
- S6 Safe assumptions read (addr 0x..07a0 hard-coded in step 5; slots 2/3/4; owners linked list keccak keys via cast; lowercase 32-byte words; 2/4/6-space YAML layout) (2026-11-17T20:26:20Z)
- S7a gates: bash -n 0/0; shellcheck keygen 1 before/1 after (pre-existing SC2295 line 163), genesis-build 0/0; portability rc 0 (2026-11-17T20:26:20Z)
- S7b arg lists: devnet new (extracted functions + stubbed IP/ssh, harness scratchpad/G2/argdump.sh) shown for 0-5, gateway refused; bench HEAD vs new 11/11 entries byte-identical (cmp rc 0) (2026-11-17T20:27:47Z)
- S7c unknown target: HEAD keygen rc 0 (keyed nothing), --pull-only rc 1; now keygen rc 2, --pull-only rc 1 (test_keygen.py:510 asserts 1: deviation from brief, reported), nothing created (2026-11-17T20:31:39Z)
- S7d bench tests from dg-l2: test_keygen 30 OK, test_gate 20 OK, check_mutations 0 tests (not a unittest module), test_node_image 108 errors all in scripts_ref() reading config.sh TN_NODE_SCRIPTS_REF placeholder (committed at HEAD 1a3985a, not G2's), re-run same (2026-11-17T20:31:39Z)
next: hand-back only
# superseded: S7c unknown target before/after, S7d bench tests
