# Bench 6 — cherry-pick ledger

Integration branch `bench/bench6-2026-11` in `/home/drtnarg/coding/telcoin/telcoin-network-b6`, base 165e3fe01
(`origin/fix/benchmark-obs-review-followups`, PR #1827, on the attested staging tip 514bf6687, PR #1826).
One row per topic commit. `git log --grep='^Topic: <slug>$'` on the integration branch is the cherry-pick index for W8.
Integration order: U0a-c, U8, U5, U4, U3, U2, U1 (+U1v), U7, U6a-b, U9, U10, U11, U12 last (so it can be left out).
The orchestrator is the only writer. Verdict column: filled from the analysis units' files after each run, nothing else.

| # | unit | topic slug | switch | unit commit(s) | integrated as | issue | run-1 verdict | run-2 verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | U8 | bench6-obs | — | f3d34932e | bfc5611ab | #1813 review note | | |
