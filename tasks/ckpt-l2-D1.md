# ckpt-l2-D1 (check-node.sh gateway + validator sections)
status: done
updated: 2026-11-17T19:50:53Z

## Completed sections
- S0 read rules, contract, units D1 row + TND gates, project-context check-node passages
- S1 read check-node.sh structure (C1 names present in lib/common.sh; lib/gateway.sh absent)
- S2 edits: CN_GATEWAY_ONLY global; detect_node; header; sections 1-7 wrapped (no reindent); 9.6 guarded;
  new 9.8 (check_gateway, check_gateway_upstream, helper _cn_gw_listener, defined after check_alerts); summary wording
- S3 gates all rc 0 (bash -n, shellcheck error+warning clean, bash32, perl-interp, network-hits);
  check_node_unit_test + check_node_hardening_test rc 0
- S4 harness /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/D1/harness.sh {healthy,stopped,upstream,oldlib,gwonly}; outputs /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/D1/<scenario>.out

## Next
- none (hand-back sent). check-node.sh: 3363 lines, +268 -12.
