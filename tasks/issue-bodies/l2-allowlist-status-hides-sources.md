# The P2P allowlist's status gives counts only, so an operator cannot tell a scanner from a peer missing from the list

The committee P2P allowlist reports how many addresses it admits by kind and how many packets it dropped, but not which address came from where nor which sources were dropped.
Every validator operator who turns the allowlist on meets it, and so does whoever debugs a joining validator that cannot connect.

## What happens

The setting is a devnet in mainnet shape: four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis.
With the allowlist on, validator-1-devnet admitted five IPv4 addresses for four committee keys; the fifth is the trusted RPC node. Sixteen minutes after `on` its counters read `accept=177128 drop=992`.

- The 992 dropped packets carry no source. A scanner on the P2P port and a validator that should have been listed (a joiner after its activation, or a member whose record did not resolve) produce the same number.
- The summary gives counts by kind: on the tn-node-deployment side, `firewall-setup.sh --p2p-committee status` prints `epoch N: A IPv4 and B IPv6 sources (K keys, F floor, S static)`. No line lists each address with its source (committee key, floor, static or trusted entry), so the operator has to work out which address is the RPC node.

## Evidence

- Live run, 2026-11-18 02:44 UTC, validator-1-devnet: `accept=177128 drop=992` 16 minutes after `on` (row 72 of the run's challenge list; taken from the row).
- The devnet driver's own summary of that status, devnet-genesis `tasks/l2/w3/d4/as-run.md` line 52: `P2P_COMMITTEE validator-1-devnet on epoch=2 v4=5 v6=0 keys=4 check=ok mode=CvvActive head=2682`. This line is the driver's reduction and leaves out the `static` and `floor` counts; what `firewall-setup.sh` printed beside it (in particular whether it showed `1 static`) is not in the evidence read here.
- tn-node-deployment, read from code at `origin/main` 2813343 (scripts 2.1.0): `firewall-setup.sh:1624-1640` (`fw_allow_summary`) builds the summary from the tool's result line (`result=... epoch=N v4=N v6=N static=N floor=N keys=N`); `:2027-2031` read `COUNTER_ACCEPT_PACKETS` and `COUNTER_DROP_PACKETS` from the tool's status and print "`<acc>` packets accepted from listed sources, `<drop>` dropped from others". PR #68's head 79fb24e has the same code at `:1762-1771` and `:2169`.

Which part belongs to which tool, as far as the evidence shows: the counters and the per-kind counts come from tn-p2p-allow-sync's status; `firewall-setup.sh` only relays them. A per-address source list or per-source drops would have to come from tn-p2p-allow-sync first. Whether its status file already holds per-address sources is not determined.

## What is not known

- tn-p2p-allow-sync's source is not on the host this was written from, so "Where in the code" is left out: where the status file is written, which fields it has, and whether the nftables rule keeps per-source counters or a log could.
- How many of the 992 drops were scanners and how many were peers.

## What could be done (suggestions, none tried)

- In tn-p2p-allow-sync's status: one line per admitted address with its source (committee key, floor, static/trusted), and the top dropped sources over the last interval (an nftables set with counters, or a rate-limited log rule).
- In `firewall-setup.sh --p2p-committee status`: print those lines, and a `--json` form a driver can read.

## Related

- {{observability-scrape-gaps}}: the same counters are not scraped.
- {{unknown-flags-exit-zero}}: another `firewall-setup.sh` output that drivers have to parse.
- tn-node-deployment PR #68 touches `fw_committee_report` (moved, same content in the lines read).
