status: done
updated: 2026-11-17T19:55:19Z
completed: setup; Q1 (neg + pos); Q2; Q3 config A (two runs: rpc up / rpc absent then started; B and C not needed); Q4 (fresh 3.7 s, restart 1.2 s); report; cleanup
deliverable: tasks/l2/rh0-report.md
cleanup: no l2rh0- container or network left (docker ps -a / docker network ls --filter name=l2rh0- empty); passphrase file and node-keys/ deleted; DBs deleted.

## Rebuild (scratch S=/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/RH0; scripts kept in $S/bin, logs in $S/logs)
- Start clean: rm -rf $S/data $S/gen $S/gen2 $S/maps $S/tnroot (node-info.yaml survives without node-keys, which would make setup.sh skip keygen).
- bin/setup.sh: network l2rh0-net 172.30.99.0/24 (v1 .11 .. v4 .14, rpc .15, join .16; udp 9000/9001), passphrase secret/pass (600), keytool generate validator (rpc: observer), telcoin genesis --chain-id 0x1e7 --epoch-duration-in-secs 90, distribute.
- python3 -I bin/maps.py $S; bin/render.sh DATADIR MODE TRUSTED|none COMMITTEE|none (TND tn_network_config_render): v1-v4 closed rpc.trusted validators; rpc open none validators; join closed rpc.trusted validators; v4bad closed rpc.trusted validators-missing-v1.
- bin/start.sh NAME DATADIR IP MAPFILE; bin/rpc.sh; bin/status.sh; bin/watch.sh; bin/q4poll.sh NAME; python3 -I bin/snap.py $S [p]
