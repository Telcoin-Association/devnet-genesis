# Sources: l2-p2p-committee-not-scriptable

TND = /home/drtnarg/coding/telcoin/tn-node-deployment, M = origin/main (2813343), P = 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (PR #68 head). DG = devnet-genesis.

| Item in the draft | Source | Status |
|---|---|---|
| Claims: no `--json`, manual step per host (row 7); `--wait 30` waits for the lock, refusal at once, driver retries (row 23); tool off sudo's PATH (row 68) | `tasks/challenges-l2.md` rows 7, 23, 68; report section 2.10 | checked against code and evidence below where noted |
| Refusal text "--p2p-committee goes alone: not with --json, --status, --enable, --reset, --port or a source flag …" at `:4015` (M), `:4361` (P) | `git grep -n -E "p2p-committee.*json"` at M and P | checked (both refs) |
| Design comment quote at `:3602-3604` (M), `:3918` (P) | `git show M:firewall-setup.sh \| sed -n '3602,3607p'`; P line 3918 by grep | checked at M; first line at P |
| Argument parsing `:3990` (M), `:4329` (P) | `git grep -n "p2p-committee)"` at M and P | checked (both refs) |
| Row 23 cites `firewall-setup.sh:1745`; `fw_allow_run sync --require-authoritative --wait 30` | `git grep -n -- "--wait 30"` at M (1745) and P (1883) | checked: matches at M; at P the line is 1883 |
| Comment `:1662-1670` (M): exits 1 and writes nothing when not authoritative, `reason=`, removes what this run installed | `git show M:firewall-setup.sh \| sed -n '1662,1670p'`; P comment at 1803 by grep | checked at M; P start line by grep |
| `--wait 30` waits for the lock only; tn-p2p-allow-sync `docs/contract.md:287-288` | row 23 (facts tnd-firewall §5) | taken from the row, source not re-read |
| The devnet driver retries | row 23 status column; no retry line found by `grep -i "retr\|reason=\|not authoritative" tasks/l2/w3/d4/as-run.md` | taken from the row, source not re-read |
| Tool path `/usr/local/libexec/telcoin/tn-p2p-allow-sync` at `:1500`, `:1573` (M), `:1638`, `:1711` (P) | `git grep -n "libexec/telcoin"` at M and P | checked (both refs) |
| OPERATOR.md file table `:307` (M) / `:308` (P); bare name `:635`, `:649` (M) / `:637`, `:651` (P) | `git grep -n -E "tn-p2p-allow-sync (status\|check)\|libexec/telcoin/tn-p2p" <ref> -- OPERATOR.md` | checked (both refs) |
| `sudo: tn-p2p-allow-sync: command not found`, rc 1, `status` and `check` | DG `tasks/l2/w3/d4/as-run.md:55-58` | checked |
| Full path `check`: `result=ok missing_total=0 mismatch_total=0`, rc 0 | row 68 evidence column; as-run lines 55-58 show the `status` result (rc 0), the `check` line is beyond what was read | taken from the row, source not re-read |
| validator-1-devnet at 02:29 UTC | row 68 evidence column; as-run names `B-v1-*` files | taken from the row, source not re-read |
| Validators 3 and 4: same message | DG `tasks/l2/w3/d4/C-v3-check.txt:2`, `C-v4-check.txt:2` (`grep -rn "command not found" tasks/l2/w3/`) | checked |
| Row 72: `keys=4` beside five addresses, `accept=177128 drop=992` | `tasks/challenges-l2.md` row 72 | taken from the row, source not re-read |
