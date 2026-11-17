status: partial (H1 M1 M2 L1 L2 L3 L4 L7 done; M3 L5 L6 L8 open)
updated: 2026-11-17T21:09:28Z
scratch: /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/FX-D/ (pc/ = H1/L1-L3 harness, PCc/ = copy of unit PC harness)
completed sections:
- H1 (devnet-p2p-committee.sh): baseline round after on+check (max head, or max tn_latestConsensusHeader .number with REQUIRE_ADVANCE=0), this host must exceed it; same for --off. Proof: pc/run.sh PTICK=0 FREEZE=validator-1-devnet: committed passes v1 and touches v2; new stops at v1 (exit 1, kill switch, v2-4 untouched). Healthy x3 + idle healthy exit 0; idle frozen fails. Gates bash -n 0, shellcheck 0 (0 before), portability 0. Unit PC harness copy: clean/off/alreadyon/status/dry exit 0.
- L1 (--off continues past a failed host, exit 1): proof pc l1-old stops at v1, l1-new turns off v3 (culprit) and v4, exit 1.
- L2 (INT/TERM/HUP trap prints the kill switch for PC_CUR): proof pc l2 TERM -> kill switch + exit 143.
- L3 (transport-fault re-send -> kill switch + "state unknown"): proof pc l3-old "Nothing was changed", l3-new kill switch + unknown.
- M1 (devnet-teardown.sh): _td_describe 3-way (exists / not-found by text "/<name>' was not found" or "'<name>' was not found" / unknown); login first in every mode; plan_err stops before anything; LB + txgen + post-verify same. Proof FX-D/td: old auth/server/crash/wrongproj rc0 17 deletes, new rc1 0 deletes; healthy both rc0 18 deletes; rerun-absent rc0; B (--keep-lb, auth broken) old rc0, new rc1; LB urlmap server error old rc0, new rc1. Gates 0/0/0.
- M2 (devnet-gateway.sh --rpc-edge --yes): read-only systemctl is-active on each rpc host first; not active -> exit 1, nothing sent. Proof FX-D/gw (GW stub + STUB_UNIT_STATE): committed inactive exit0 rpc-enable sent; new inactive exit1 not sent; new active exit0 sent.
- L4 (dashboards + observability refuse under set -x): proof FX-D/l4 bash -x -> refusal exit 1.
- L7 (README deploy list = the 20 steps, no LB script).
NOT DONE (tool-call cap 65 reached): M3 (postcheck settle loop for admission/heads/chain + deploy step-16 comment), L5 (dash_caddy_state summary: gateway port/probe_port, rpc advertised_http/ws), L6 (firewall --enable gateway note -> install-caddy.sh opens 80/443 itself), L8 (stake epoch_line '(status as of activation)'). devnet-deploy.sh, devnet-postcheck.sh, devnet-firewall.sh, devnet-stake-node5.sh untouched.
next: M3, then L5, L6, L8 (fresh agent).
