# firewall-setup.sh, install-caddy.sh and remove-node.sh drop unknown flags silently, so older scripts ignore newer flags

Three scripts end their argument loop with `*) shift ;;`: an unknown flag, and its value, are skipped without a word; `setup-node.sh` warns and goes on.
An operator whose installed scripts are older than the runbook gets a run that reports success without the change asked for. A second, smaller problem in the same parser: `firewall-setup.sh --status` without `--json` opens the interactive menu.

## What happens

Read from code, not run.

- PR #68 adds `--gateway-from` to `firewall-setup.sh` (19 occurrences at its head, none on `main`). On scripts 2.1.0 a runbook line such as `firewall-setup.sh --enable --gateway-from <addr>` applies the recommended rules, skips `--gateway-from` and `<addr>`, and returns the result of the rest: no gateway rule, no message.
- Given alone, the same unknown flag leaves no action set, and the script falls through to the interactive menu.
- `install-caddy.sh` and `remove-node.sh` do the same with any flag they do not know.
- `setup-node.sh` prints `Unknown argument: <flag>` on stderr and continues; a driver that reads only the exit status or the `--json` stdout does not see it.
- `firewall-setup.sh --status` sets the status action, but only the `--json` branch handles it. Without `--json` the run reaches `main_menu`, which waits for input; a non-interactive caller would hang there (inferred, not run).

This matters for mainnet because validator operators keep installed scripts across releases, and a flag added in one release is used by runbooks written for it.

## Evidence

- The catch-all lines and the dispatch below, at both refs (`git -C tn-node-deployment show <ref>:<file> | sed -n …`, `git grep -n` for the `*)` lines).
- `--gateway-from`: `git grep -c -- '--gateway-from'` in `firewall-setup.sh`: 19 at PR #68's head, 0 on `origin/main`.
- Found by reading the code while preparing a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), 2026-11-17. No run with older scripts is on record.

## Where in the code

Line numbers at `origin/main` 2813343 (scripts 2.1.0) and at PR #68's head 79fb24e (scripts 2.2.0). The problem is on both.

| File | `main` | PR #68 head | Line |
|---|---|---|---|
| `firewall-setup.sh` | 3998 | 4339 | `*) shift ;;` |
| `install-caddy.sh` | 3352 | 3933 | `*) shift ;;` |
| `remove-node.sh` | 2067 | 2261 | `*) shift ;;` |
| `setup-node.sh` | 3850 | 3850 | `*) print_warn "Unknown argument: $1" >&2; shift ;;` |

`--status` in `firewall-setup.sh` on `main`: the flag sets `action="status"` (3985); the `--json` branch (4031-4046) is the only one that reads it; the reset/enable branch (4047), the source-flag branch and the `--p2p-committee` branch (4084-4097) do not; 4098-4100 run `check_root`, `fw_load_network` and `main_menu`. PR #68's head has the same order: 4324, 4377, 4393, 4447.

## What is not known

- What `main_menu` does when stdin is not a terminal (loops, waits or exits); not run.
- Whether any caller relies on unknown flags being ignored (for example a newer driver passing optional flags to older scripts).

## What could be done (suggestions, none tried)

- End each loop with `*) print_error "Unknown argument: $1"; exit 2 ;;` (in `--json` mode, the usual JSON error), in all four scripts.
- In `firewall-setup.sh`, make `--status` without `--json` print the human status and exit; open the menu only when no flag is given and stdin is a terminal.

## Related

- PR #68 adds flags (`--gateway-from` among them) to these parsers without changing the catch-all.
- {{allowlist-status-hides-sources}}: another `firewall-setup.sh` output a driver has to parse.
