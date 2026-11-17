status: done (partial deliverable: --staged blocked on tn-node-deployment, see P1-finding)
unit: OB
completed:
- P1-finding (2026-11-17T20:28:57Z): setup-observability.sh --json on a STOPPED node STARTS it whenever it has to add a reth flag.
  Path: run_json_mode exports TN_ASSUME_YES=true (TND setup-observability.sh:651) -> json_enable_pipes -> obs_enable
  -> obs_ensure_reth_flags (lib/observability.sh:1368, call at :1558) -> flags added -> confirm (forced yes) ->
  obs_restart_window (:1112; obs_quorum_guard :1137 passes on devnet when the committee cannot be read, doc :1131-1133;
  epoch wait skipped with TN_SKIP_EPOCH_WAIT=1) -> systemctl restart "$svc" (:1408) = start of an inactive unit.
  No env switch prevents it (only TN_SKIP_EPOCH_WAIT / TN_ALLOW_QUORUM_RISK, both let it through). Clean only when the
  flags are already on the launch file (:1396 returns before the restart). --enable-health alone never restarts (SO:572-611).
  Decision: --staged NOT implemented (refuses, nothing touched); contract change request in the hand-back.
  Alloy one config file: lib/observability.sh:29 (OBS_ETC_DIR), :861 (native ExecStart), :949 (docker mount).
- P1-code (2026-11-17T20:32:06Z): dg-l2/devnet-observability.sh 375 lines: --staged refuses (exit 2, nothing touched); normal mode visits
  tn_node_indices only, gateway entry skipped with a curl line; targets by index/instance/node name (unknown -> exit 2);
  tn_fleet_check first; health header. Stub checks: --staged rc 2 0 calls; normal rc 0, 6 node hosts, 0 DG restart/start;
  node-host remote command byte-identical to HEAD (sha 4dda4717c6a6f7b4 both). Harness: scratchpad/OB/t (runcase.sh).
- P2-code (2026-11-17T20:32:06Z): dg-l2/devnet-dashboards.sh written (UI install + install-caddy --phase enable, preflight, public 401 check).
- P2-checks (2026-11-17T20:33:18Z): preflight missing rc1, 10-char rc1, 20-char rc0; full run rc0: publish node1,2,3,5,6, UI-only validator-4,
  gateway-4 skipped; stdin sha of all 13 enable calls = fake pw; fake pw in stub argv/env/outputs/run logs: 0; DNS missing
  rc1 naming the record; --no-public-check 0 local curl; changed rpc block detected rc1; bad flag rc2.
- gates (2026-11-17T20:33:18Z): bash -n 0/0; shellcheck -x obs 0 findings (HEAD 0), dash 0 findings (HEAD 1, SC2001); portability 0/0.
next: hand-back sent.
