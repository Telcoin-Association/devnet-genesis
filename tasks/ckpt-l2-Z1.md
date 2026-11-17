status: done
unit: Z1 (devnet-finalize.sh, worktree dg-l2)
started: 2026-11-17T20:21:00Z
completed sections:
- 0 read rules/contract/facts
- 1 TND setup-node.sh finalize flags (HEAD 405af9e) confirmed:
  - init_node_extra_flags (SN:1483, called SN:3874 for every phase) checks --bootstrap-peers/--trusted-nodes files
    (exists, regular, readable, mode has 044, <=65536 bytes; owner NOT checked) and normalises --admission.
    keygen-only rule "--trusted-nodes needs --admission" skipped for finalize (SN:1501).
  - finalize_node_extra_flags (SN:1598): flags given on the finalize argv win; absent ones read back from .node-meta
    (BOOTSTRAP_PEERS_FILE, ADMISSION_MODE, TRUSTED_NODES_FILE). Keygen need NOT have had them.
  - prepare_node_extra_flags (SN:2434, from step_create_service SN:2739): require_admission_release, install
    /etc/telcoin/bootstrap-peers.yaml (root 0644, parse-checked by the release) + /etc/telcoin/trusted-nodes.yaml (root 0644),
    write .node-meta BOOTSTRAP_PEERS_FILE=/etc/telcoin/bootstrap-peers.yaml ADMISSION_MODE=<mode>
    TRUSTED_NODES_FILE=/etc/telcoin/trusted-nodes.yaml|"" ; setup_admission_config renders <datadir>/network-config.
  - release check: docker + no --release-tag -> node_release_version = tn_docker_release_tag_for(NETWORK,IMAGE) or the image
    ref; rc2 unknown -> warn, write anyway; rc1 (<0.17.0) -> setup_fail. NOT verified what tn_docker_release_tag_for returns for devnet.
  - --public-ws-url optional (default "", validation loop skips empty, SN:1393-1400; .node-meta PUBLIC_WS_URL="").
- 2 design (2026-11-17T20:25:37Z): wait_healthy = unit active + GET / on 127.0.0.1:43174 -> liveness 200 (node-side.md:13), no peers/blocks;
  _start_all waits only on wait_healthy -> no native change needed. Plan: tn_select_indices -> tn_node_indices + refuse gateway (exit 2);
  NODES_SPEC from tn_node_indices; _native(); _rs_ready emits bp_sha/tn_sha (native) instead of nc lines; gate compares with python
  hashlib of local ADMISSION_MAPS_DIR/<node>.*.yaml; finalize_args: rpc url from tn_public_domain, ws only when tn_gateway_mode none,
  native adds --admission/--bootstrap-peers/--trusted-nodes; _nc_verdict gets optional <Mode> native; A4 extra pattern via split heredoc;
  A6 assert_admission_meta. HEAD copy: scratchpad/Z1/finalize.head.sh
- 3 edits applied (2026-11-17T20:28:21Z); gates pending
- 4 harness (2026-11-17T20:32:46Z): devnet cmd lines captured (cap.new.devnet); bench finalize diff empty; all 24 bench remote cmds identical HEAD vs new
- 5 gate-fail + gateway-refusal checked (2026-11-17T20:35:05Z): node5 mismatched trusted map -> not ready, no finalize sent; targets 6/gateway4 -> exit 2. unittest running (bg bp11pbmjw)
- 6 unittest finished (2026-11-17T20:35:40Z): OK
status: done (see hand-back)
