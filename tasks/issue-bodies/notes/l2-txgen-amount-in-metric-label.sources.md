# Sources: l2-txgen-amount-in-metric-label

| Item in the draft | Source | Status |
|---|---|---|
| `type="native_transfer:62744256131388wei"`, 7,930 `txgen_` lines 25 min after start, unbounded | `tasks/challenges-l2.md` row 62 | taken from the row, source not re-read |
| `curl 127.0.0.1:9090/metrics` on txgen-devnet, 2026-11-18T02:21:56Z | `tasks/challenges-l2.md` row 62 | taken from the row, source not re-read |
| Log label `native_transfer:41932599727859wei` | `grep -rnoE 'native_transfer:[0-9]+wei' tasks/l2` -> `tasks/l2/w3/d3b/s17-19.log:9192-9193` | checked |
| Log label `faucet_drip:native:635271581257683523wei` | `tasks/l2/w3/d3b/s17-19-excerpts.txt` line 35 (log line 9197) | checked |
| One string feeds log label and metric label | inferred from the two | inferred |
| Generator code (metric families, where `type` is built) | source not on this host | not verifiable here |
