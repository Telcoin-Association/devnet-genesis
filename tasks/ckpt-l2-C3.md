status: done
unit: C3 (edit-config.sh gateway_upstream)
completed sections:
- S0 read rules/contract/facts
- S1 anchors (2026-11-17T19:43:24Z): header --set docs end EC:119; lib check EC:131-137; edit_field_known EC:2082;
  set_field EC:2130; set_rpc_addr EC:2738 (node.env TN_RPC_ADDR write EC:2764-2773); run_set EC:3803 (restart EC:3850);
  EDIT_PENDING trap EC:619; edit_admission_meta EC:1696 (generic backup+meta_set); UI helper allowlist refuses unknown fields (ui/telcoin-ui-helper.sh:1080 die "field not editable").
  Decisions: prev healthcheck read raw via tn_launch_flag_get (not tn_node_health_bind, which normalizes bare port); RPC port from tn_local_rpc_url.
- S2 implemented (2026-11-17T19:44:36Z): header doc, lib check (+tn_gateway_from_rules_ok), edit_field_known, set_field, edit_rpc_addr_env (extracted from set_rpc_addr), set_gateway_upstream (after set_rpc_addr), run_set stopped guard (is-active after lock; daemon-reload, no restart, done ok:true)
- S3 gates all rc 0 (bash -n, sc error, sc warning 0 findings, bash32, perl-interp, network-hits); 4 existing test files 28 checks 0 failures (C1 helpers present in lib/common.sh)
- S4 harness (2026-11-17T19:47:05Z): scratchpad/C3/gw_harness.sh, 30 checks 0 failures (refusal byte-identical, set active restart x1, stopped never started, off restores bare port, off with no prior flag)
- S5 hand-back sent
