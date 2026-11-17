# ckpt-l2-PC (unit PC: dg-l2/devnet-p2p-committee.sh, new)
status: done
sections:
- [x] S1 read rules, contract §1/§8/§10/§11/§12/A-5/A-7, units PC row + DG gates, facts
- [x] S2 read dg-l2 lib/config names, observability sweep 100-326, tn_select_indices
- [x] S3 wrote dg-l2/devnet-p2p-committee.sh (704 lines, untracked)
- [x] S4 DG gates: bash -n 0; shellcheck -x 0 (0 findings); tasks/check-bash-portability.sh 0 (no ERROR)
- [x] S5 stub-ssh scenarios (2026-11-17T20:32Z): clean sweep exit 0 (4 P2P_COMMITTEE lines); snapshot never authoritative on host 2 exit 3 (host 2 probe+snap only, 3-4 untouched); on refused x2 then ok exit 0 (on x3); check missing on host 3 exit 1 (kill switch first, missing 10.164.0.9, host 4 untouched); validator-3 CvvInactive after host 1 exit 1 (no call to host 2 beyond probes, 2-4 untouched); extras: dry run 0, gateway/rpc/unknown/--status+--off/bad knob 2, already-on 0 (no snap), --status 0 / 1 when an on host is check-missing, --off --yes 0
- [x] S6 hand-back (2026-11-17T20:32Z)
notes:
- stub harness: /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/PC/{stub-lib.sh,run.sh}; outputs out-<scenario>.txt there
