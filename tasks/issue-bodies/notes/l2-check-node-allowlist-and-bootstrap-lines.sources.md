# Sources: l2-check-node-allowlist-and-bootstrap-lines

| Item in the draft | Source | Status |
|---|---|---|
| Rows 73-74 claims, cited `check-node.sh:801` (main) / `:809` (PR), `check_p2p_committee` `:2506-2528` (PR) "the same on main" | `grep -E '^\| 7[34] \|' tasks/challenges-l2.md` | checked against code (see below) |
| `  ->  Bootstrap peers:  $(cat /etc/telcoin/bootstrap-peers.yaml)`, validator-4-devnet, 02:57Z | `tasks/l2/w3/v/r13-check-node-3.txt:17` (grep) ; time from row 73 | checked (line); time taken from the row |
| `tn_launch_flag_get "$file" --bootstrap-peers` at main 799, PR 807 | `git -C tn-node-deployment grep -nE 'bootstrap-peers' <ref> -- check-node.sh` | checked; the print at 801/809 not re-read (consistent +2 offset) |
| `check_p2p_committee` comment at main 2263, PR 2506 | same grep with `p2p.?allow\|allowlist` | checked (row's "the same on main" is the same code at 2263, not the same line) |
| "silent when it is off and when all is well"; no allowlist line in validator-4-devnet reports, `check=ok` | row 74 | taken from the row, source not re-read |
