# check-node.sh prints the bootstrap-peers flag's shell text, and shows nothing when the committee allowlist is healthy

Two small, separable problems in one script's report: `check-node.sh` prints the literal `$(cat /etc/telcoin/bootstrap-peers.yaml)` instead of the peers, and its committee-allowlist check prints nothing when the allowlist is on and healthy.
Every validator operator who runs `check-node.sh` meets them, and so does anyone reviewing its report to confirm that a validator's allowlist is on.

## What happens

The setting is a devnet in mainnet shape: four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis.

Part 1. On validator-4-devnet the report showed:

```
  ->  Bootstrap peers:  $(cat /etc/telcoin/bootstrap-peers.yaml)
```

That is the text of the launch flag as the start wrapper writes it (the wrapper substitutes the file at start), not the peers the node received. The report neither counts nor names them.

Part 2. On the same host the allowlist was on, with `check=ok` from the allowlist tool, and the report had no allowlist line at all. The check is written to be "silent when it is off and when all is well", so a report from a host with the allowlist on and one from a host with it off look the same.

## Evidence

- Part 1: live run, 2026-11-18 02:57 UTC, validator-4-devnet, devnet-genesis `tasks/l2/w3/v/r13-check-node-3.txt` line 17, checked.
- Part 2: the same run's reports for validator-4-devnet (row 74 of the run's challenge list); taken from the row, the reports were not re-read here.

## Where in the code

At `origin/main` 2813343 (scripts 2.1.0) and PR #68's head 79fb24e (scripts 2.2.0). Both problems are on both.

- Part 1: `check-node.sh:799` on `main`, `:807` at the PR head, reads the value with `tn_launch_flag_get "$file" --bootstrap-peers`; the row places the print two lines below, at `:801` and `:809` (the print line itself was not re-read).
- Part 2: `check_p2p_committee`, its comment beginning at `check-node.sh:2263` on `main` and `:2506` at the PR head (the row gives `:2506-2528` at the PR head and "the same on `main`"; on `main` the same comment is 243 lines earlier, at 2263).

## What is not known

- Whether other launch flags stored as `$(cat …)` are printed the same way.
- Whether `check-node.sh --json` (if used) carries the allowlist's state when healthy.

## What could be done (suggestions, none tried)

- Part 1: when the value is `$(cat <file>)`, read the file and print the number of peers (and their BLS keys shortened), or print the file path.
- Part 2: one OK line when the allowlist is on and healthy, with the size of the set and the time of the last good sync.

## Related

- {{allowlist-status-hides-sources}}: the allowlist's own status, which the OK line could summarise.
- {{joiner-admission-renderer}}: the same bootstrap-peers file.
