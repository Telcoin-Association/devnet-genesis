# Bench 6 — cherry-pick ledger

Integration branch `bench/bench6-2026-11` in `/home/drtnarg/coding/telcoin/telcoin-network-b6`, base 165e3fe01
(`origin/fix/benchmark-obs-review-followups`, PR #1827, on the attested staging tip 514bf6687, PR #1826).
One row per topic commit. `git log --grep='^Topic: <slug>$'` on the integration branch is the cherry-pick index for W8.
Integration order: U0a-c, U8, U5, U4, U3, U2, U1 (+U1v), U7, U6a-b, U9, U10, U11, U12 last (so it can be left out).
The orchestrator is the only writer. Verdict column: filled from the analysis units' files after each run, nothing else.

| # | unit | topic slug | switch | unit commit(s) | integrated as | issue | run-1 verdict | run-2 verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | U8 | bench6-obs | — | f3d34932e | bfc5611ab | #1813 review note | | |
| 2 | U0a | bench6-switches | (adds the switch field) | 8de796736 | 3696d49f3 | | | |
| 3 | U0a | quorum-exec-block | (adds the switch field) | cb38f8f77 | 86755c450 | | | |
| 4 | U0a | voter-lock | (adds the switch field) | a3095531b | 82ed5801a | | | |
| 5 | U0a | mdbx-advice | (adds the switch field) | ddae99181 | de08ef7f1 | | | |
| 6 | U0a | sealed-keep | (adds the switch field) | 60171c9fc | 1169532a8 | | | |
| 7 | U0a | digest-dedupe | (adds the switch field) | aa1372dda | 478dd3d23 | | | |
| 8 | U0a | recovery-pool | (adds the switch field) | 4d5722736 | 11a1cae01 | | | |
| 9 | U0a | tracker-drain | (adds the switch field) | 663966a06 | 901505021 | | | |
| 10 | U0a | parent-grace | (adds the switch field) | 93aac1e6b | 5c1c28720 | | | |
| 11 | U0a | inflight-bound | (adds the switch field) | 57d609550 | 639817091 | | | |
| 12 | U0a | pipelined-persist | (adds the switch field) | dcde49bee | 8ab9e89e4 | | | |
| 13 | U0a | inflight-bound | (adds the switch field) | b14ae1ddd | 5ef5152a9 | | | |
| 14 | U0a | tracker-drain | (adds the switch field) | 7a3732253 | 43158b0d0 | | | |
| 15 | U0a | bench6-switches | (adds the switch field) | da9dc0ff3 | 5b9f13b25 | | | |
