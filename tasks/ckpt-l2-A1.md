status: done
unit: A1 (lib/gateway.sh in /home/drtnarg/coding/telcoin/tnd-l2-gateway, 1115 lines, new, untracked)
completed sections:
- reading done (rules, contract 1-3/12, units A1 row, facts, alerts.sh 1-142, common.sh helper docs).
- lib/gateway.sh written, all function groups; C1 landed; orchestrator note matched.
- gates: bash -n 0, shellcheck -x --severity=error 0, --severity=warning 0 (file-level SC2034 directive), check-bash32 0, check-perl-interp 0, check-network-hits 0.
- 2026-11-17T19:53:54Z harness (scratch A1/harness.sh, harness2.sh) passes: same-host+caddy, same-host+none, standalone+caddy args; 2nd enable no-op (tree unchanged, no restart, caddy no-op); refusals tree untouched; rollback on /health failure restores tree (parent /etc/telcoin tracked, fix applied); remove; refresh no-op and new image; non-root status from unit file.
unfinished: none. Not committed (orchestrator commits).
