# Sources: l2-allowlist-status-hides-sources

| Item in the draft | Source | Status |
|---|---|---|
| Claim: status shows `keys=4` beside five addresses, does not say where the fifth (trusted RPC node) comes from; drop counter names no source | `tasks/challenges-l2.md` row 72; report sections 2.10 and 3.3 | taken from the row, source not re-read |
| `accept=177128 drop=992`, validator-1-devnet, 02:44Z, 16 min after `on` | `tasks/challenges-l2.md` row 72 | taken from the row, source not re-read |
| `P2P_COMMITTEE validator-1-devnet on epoch=2 v4=5 v6=0 keys=4 check=ok mode=CvvActive head=2682` | `grep -rn 'keys=4' tasks/l2` -> `tasks/l2/w3/d4/as-run.md:52` (also :90-92 for validators 1-3) | checked |
| That line is the devnet driver's reduction, without `static`/`floor` | inferred: `firewall-setup.sh`'s own summary has `static` and `floor` (below) and this line does not | inferred |
| `fw_allow_summary` `firewall-setup.sh:1624-1640` on main: grammar `result=... epoch=N v4=N v6=N static=N floor=N keys=N`, output `epoch N: A IPv4 and B IPv6 sources (K keys, F floor, S static)` | `git -C tn-node-deployment show origin/main:firewall-setup.sh \| sed -n '1624,1626p;1630,1642p'` | checked |
| Counters: `COUNTER_ACCEPT_PACKETS` / `COUNTER_DROP_PACKETS`, "packets accepted from listed sources, … dropped from others"; `drop=` at 2031 | `git grep -nE 'keys=\|drop='` (2031) and `sed -n '2024,2044p'` on main (comment lines filtered, so 2027-2030 neighbours approximate) | checked (2031 exact; range approximate) |
| PR head: `:1762`, `:1771`, `fw_committee_report` `:2111`, `:2169` | `git grep -nE '^fw_committee_report\(\)\|keys=\|drop=' 79fb24e… -- firewall-setup.sh` | checked (same text on grep'd lines) |
| Fifth address is the trusted RPC node | row 72 | taken from the row, source not re-read |
| tn-p2p-allow-sync status file fields, per-source counters | source not on this host | not verifiable here |
