# Sources: l2-unknown-flags-exit-zero

| Item in the draft | Source | Status |
|---|---|---|
| Claim (rows 17, 18), cited `firewall-setup.sh:3998`, `install-caddy.sh:3352`, `setup-node.sh:3850`, `firewall-setup.sh:4047-4100` | `tasks/challenges-l2.md` rows 17-18 | checked against code (all match on `origin/main`) |
| Title, consequence, `--gateway-from` example, "inferred, not run" | `tasks/challenges-l2-report.md` section 2.14 and section 4 line 247 | checked |
| `*) shift ;;` at firewall-setup.sh 3998 / 4339, install-caddy.sh 3352 / 3933, remove-node.sh 2067 / 2261 | `git -C tn-node-deployment grep -nE '^\s+\*\) (shift\|print_warn "Unknown)' <ref> -- <file>` at both refs; `sed -n` of 3994-4001, 3348-3355, 2066-2068 on main | checked |
| setup-node.sh 3850 / 3850 `print_warn "Unknown argument: $1" >&2` | same grep; `sed -n '3846,3853p'` on main | checked |
| `--gateway-from`: 19 at PR head, 0 on main | `git grep -c -- '--gateway-from' <ref> -- firewall-setup.sh` | checked |
| `--status` sets `action="status"` at 3985 (PR 4324) | `git grep -nE 'action=' <ref> -- firewall-setup.sh` | checked |
| JSON branch 4031-4046 (PR 4377), reset/enable 4047 (PR 4393), source flags ~4075, `--p2p-committee` 4084-4097, `main_menu` 4100 (PR 4447) | `git grep` of `"$action"`, `json_mode`, `main_menu` at both refs; `sed -n '4031,4036p;4047,4060p;4060,4100p'` on main | checked (PR head: line numbers from grep only, branch bodies not re-read) |
| `--enable --gateway-from <addr>` on 2.1.0 applies the rest with no gateway rule | inferred from the parser and dispatch above | read from code, not run |
| A lone unknown flag falls through to the menu | same | read from code, not run |
| `main_menu` hangs a non-interactive caller | row 18 ("inferred, not run") | not verifiable here |
| Facts tnd-firewall §1, tnd-caddy §1, tnd-node §1 (named by row 17) | not opened; the code was read directly instead | taken from the row, source not re-read |
