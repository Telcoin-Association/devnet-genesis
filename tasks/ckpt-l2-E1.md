status: done
unit: E1 (gateway fixture tests) -- TND /home/drtnarg/coding/telcoin/tnd-l2-gateway
updated: 2026-11-17T20:13:13Z

## Completed sections
- [x] 0. read rules, contract, units row, facts, review notes, code under test
- [x] 1. tools/tests/gateway_setup_test.sh library cases (render, refusals, image trust, idempotence, status, refresh, rollback, remove)
- [x] 2. script cases (setup-gateway.sh copy beside a stand-in lib/common.sh)
- [x] 3. addon_oldlib_test.sh: setup-gateway.sh added to the two loops (48, 91), nothing else
- [x] 4. gates: bash -n, shellcheck error/warning, check-bash32, check-perl-interp, check-network-hits all rc 0; run.sh 5 files exit 0; bash:3.2 exit 0 (400 checks, 3 root skips) (2026-11-17T20:13:13Z)

## Result
- 405 checks (bash 5, as a user), 0 failures; no defect found in lib/gateway.sh or setup-gateway.sh; neither edited
- not written: docker-not-installed refusal (real docker on PATH); SIGINT/SIGHUP (TERM only)
