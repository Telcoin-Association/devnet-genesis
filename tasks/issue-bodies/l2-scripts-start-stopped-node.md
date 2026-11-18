# setup-node.sh has no --no-start; edit-config.sh --set and setup-observability.sh --json start a stopped node

Three scripts start the node with no way to say no: finalize always starts it, and `edit-config.sh --set` and `setup-observability.sh --json` restart the unit even when it is stopped, which starts it.
A launch team that stages genesis validators stopped before a coordinated start meets it on every host: a node started early runs alone until someone stops it again.

## What happens

- `setup-node.sh` finalize ends with `systemctl start "$SERVICE_NAME"`; there is no `--no-start`. Its closing JSON says "finalized and started".
- `edit-config.sh --set` ends in `edit_restart`: `systemctl daemon-reload`, the epoch-window wait, then `systemctl restart "$TARGET_SERVICE"` whatever the unit's state. On a stopped unit, `restart` starts it.
- `setup-observability.sh` sets `export TN_ASSUME_YES=true` ("belt-and-braces: no lib confirm should block"), so in `--json` runs the question "Restart ${svc} now?" is answered yes.
  Whenever it had to add a log or metrics flag, `lib/observability.sh` then runs `systemctl restart "$svc"`. No switch turns that off.
- None of these checks `systemctl is-active` before the restart in the lines read.

The devnet works around all three by stopping each node again after the step. Finalize ran as "finalized, then stopped": `STAGED validator-1-devnet state=inactive enabled=enabled`.

## Evidence

- Devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), run of 2026-11-17/18. The genesis validators were held stopped until a coordinated start.
- Finalize staging on validator-1-devnet, 2026-11-18 00:42-00:47 UTC: devnet-genesis `tasks/l2/w3/d3a/as-run.md:7` ("staged: finalized, then stopped, enabled (1)"); the other five hosts at `:9`.
- `edit-config.sh` and `setup-observability.sh`: read from code, not run against a stopped node here. The challenge rows record the devnet's driver stopping the node again after them.
- How long a node ran between the script's start and the driver's stop was not measured.

## Where in the code

tn-node-deployment `origin/main` (2813343) / PR #68's head (79fb24e).

- `setup-node.sh:2867` / `:2867`: `systemctl start "$SERVICE_NAME"`. `git grep no-start` finds nothing at either commit.
- `edit-config.sh:2370-2382` / from `:2401`: `edit_restart`, with the unconditional restart at `:2380` (main). Row 16 cites these lines; they match at main.
- `setup-observability.sh:651` / `:651`: `export TN_ASSUME_YES=true`. That this line is on the `--json` path is taken from the row, not re-read.
- `lib/observability.sh:1402-1408` (main): return unless a flag or the unit changed, then `confirm "Restart ${svc} now?"` (`:1405` at both commits), the restart window, `systemctl restart "$svc"`. Row 37 cites `:1401-1408`.
- That `confirm` answers yes under `TN_ASSUME_YES=true` is inferred from the comment, not read.

## What is not known

- Whether mainnet's genesis will be staged stopped as the devnet's was; the plan for the mainnet launch was not read here.
- PR #68 guards its new `gateway_upstream` key against starting a stopped node, per the challenge row; the guard was not located here, and other keys are unchanged.
- Whether a node started early does harm beyond running alone (for example a first epoch with one member's votes only); not observed.

## What could be done (suggestions, none tried)

- `setup-node.sh --no-start`: finalize writes and enables the unit and leaves it stopped, and its JSON says so.
- In `edit_restart` and in `lib/observability.sh`, return before the restart when `systemctl is-active` says the unit is not active, and print that the change applies at the next start. Row 37 names this as the smallest fix.

## Related

- {{finalize-reports-validators-as-observers}}: the same closing JSON.
- PR #68: the `gateway_upstream` guard in `edit-config.sh` (row 16).
