status: done
unit: TX (devnet-txgen.sh step 9 in dg-l2, branch l2/launch-2)
updated: 2026-11-17T19:46:01Z
completed sections:
- read rules/contract/units/facts; step_9 at :471-495, header :24, plan text :699
- edit: step 9 = one tx_ssh "sudo systemctl enable U >/dev/null && date +%s && sudo systemctl restart U >/dev/null", stdout last line (CR stripped) validated as digits else return 1; CHECK gets "since=<n>" prepended via { printf; cat; } <<'CHECK' | tx_stdin; journal read once with --since "@${since}", markers searched with grep -q <<<"$log" (no journalctl|grep -q SIGPIPE false MISSING); header :24 and plan :706 reworded
- gates: bash -n 0; shellcheck -x in repo 0 findings (exit 0); base vs new from scratch both 1 (SC1091 only); check-bash-portability exit 0
- stub test: ok -> exit 0 + remote command shown; garbage stdout -> exit 1; ssh fail -> exit 255; CHECK run locally vs 200k-line stub: 5/5 markers; old pattern gives false MISSING (pipestatus 141 0)
- wc -l 744 (was 727)
