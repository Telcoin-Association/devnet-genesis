# Sources: l2-fresh-install-false-alarms

| Item in the draft | Source | Status |
|---|---|---|
| Claim part 1 (row 52): warns on every fresh launch, twice, reads the public RPC URL | `tasks/challenges-l2.md` row 52; evidence `tasks/l2/w3/d3a/as-run.md` | checked against the as-run file |
| `[warn] could not count the committee members that are down (the committee could not be read; <URL> does not answer with chain 32285); going…` printed twice | `tasks/l2/w3/d3a/as-run.md` line 15 (python search for `down`/`twice`); URL replaced by its role | checked |
| "again twice per host on the five that restarted"; `done: ok` on all six | `tasks/l2/w3/d3a/as-run.md` line 17 | checked |
| Times 00:59Z-01:13Z, date 2026-11-18 (log dir `20261118_010222`) | `tasks/l2/w3/d3a/as-run.md` lines 15, 17 | checked |
| Claim part 2 (row 64): `curl: (7) Failed to connect to 127.0.0.1 port 8080 after 0 ms: Couldn't connect to server` before `✅ … answering on 127.0.0.1:8080`, six of six hosts, step 17 | `tasks/challenges-l2.md` row 64 | taken from the row, source not re-read |
| `setup-observability.sh:761` names `tn_committee_down_guard`, both refs | `git -C tn-node-deployment grep -nE 'down' <ref> -- setup-observability.sh` | checked |
| Probe / `answering on` line not found in `install-ui.sh` | `git grep -nE '8080\|answering' <ref> -- install-ui.sh \| grep -E 'curl\|answering'`: no match at either ref | checked (negative; may live in a library) |
| Why the warning prints twice; where the UI probe is | none | not verifiable here |
