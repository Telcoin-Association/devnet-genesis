status: done (through step 13)
unit: D3a (steps 10-13)
started: 2026-11-18T00:41:19Z
updated: 2026-11-18T01:20:17Z
completed sub-steps:
- preconditions (00:41Z): PASS
- 7.1 canary node1: PASS
- 7.1 rest: PASS (--only 10 rc 0, --verify rc 0)
- 7.2 canary v1: PASS
- 7.2 rest: PASS (--only 11 rc 0)
- 7.3 canary v1: PASS (started_by_installer=yes)
- 7.3 rest: PASS (--only 12 rc 0)
- 7.4 same-host node1: PASS
- 7.4 standalone node4: PASS
- 7.4 rest (01:16-01:20Z): --only 13 rc 0, 5 GATEWAY lines, all telcoin inactive, 80/443 open on caddy hosts, LE certs node1-5
next: nothing (step 14 belongs to the orchestrator). Records: tasks/l2/w3/d3a/as-run.md
