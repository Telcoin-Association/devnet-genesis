status: done
unit: DP (devnet-deploy.sh in dg-l2)
updated: 2026-11-17T20:30:53Z

completed sections:
- S0 read rules, contract 8/10/11/12/14(A-5,A-7), units DP row + DG gates, dg-core s4
- S1 read current devnet-deploy.sh (330 l) + lib helpers; baseline shellcheck -x = 0 findings, portability rc 0
- S2 wrote dg-l2/devnet-deploy.sh: 20 steps, --to, pre-gates 1-6, DNS records+dig check, run log tee, EXIT-trap resume line
- S3 gates: bash -n 0, shellcheck -x 0 findings, portability rc 0 no WARN
- S4 stub exercise (scratch DP/setup.sh, run.sh): full --yes rc0 calls == table; --from 5 --to 10 rc0 + wipe warning; --only 20 rc0; exit-3 at 10 rc3 + msg; --only+--to rc1; --from>--to rc1; placeholder on real config rc1; effective-value + tag gates rc1; contracts dir missing rc1; no-tty step4 rc1; wrong DNS rc1 with list

- S5 hand-back sent (report in final message)
