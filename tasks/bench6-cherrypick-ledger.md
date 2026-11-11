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
| 16 | U7 | digest-dedupe | digest_dedupe | 93e9d7c21 | 93e9d7c21 | #1807 | | |
| 17 | U1 | quorum-exec-block | (ring helpers) | 73b8a0d24 | d4be3a435 | #1804 | | |
| 18 | U1 | quorum-exec-block | quorum_exec_block, quorum_exec_block_starved_rounds | e823da217 | 5d7821dfb | #1804 | | |
| 19 | U0b | bench6-e2e-scaffold | — (test harness) | d1b3e91ef | 38b65ff7b | | | |
| 20 | U0b | bench6-e2e-scaffold | — | 56f50b1a4 | 4c7e5f032 | | | |
| 21 | U0b | bench6-e2e-scaffold | — | 9208e4d30 | d1b6b0ac3 | | | |
| 22 | U0b | bench6-e2e-scaffold | — | a045aaebc | b09d65945 | | | |
| 23 | U2 | voter-lock | vote_queue_fix | c56b33c0a | 2b9a69925 | #1804 | | |
| 24 | U2 | tracker-drain | — (gauge) | 12bb5bb45 | 16695b20a | #1806 | | |
| 25-36 | U0c | bench6-switches, mdbx-advice, recovery-pool ×2, sealed-keep ×2, inflight-bound ×2, pipelined-persist ×4 | (plumbing; no behaviour) | 644569519..8c64788b8 (12) | 16695b20a..7cfe52acd | | | |
| 37 | U4a | recovery-pool | recovery_threads | 4a9e1c014 | aa71a50f8 | #1805 | | |
| 38 | U9 | parent-grace | parent_grace | 2741f6df0 | 80584c6f6 | #1803 | | |
| 39 | U9 (U1v) | quorum-exec-block | — (voter tests) | 5edc17421 | 14b55b04c | #1804 | | |
| 40 | U6a | sealed-keep | sealed_tx_keep (store + pool side) | da24d6780 | edc616c0d | #1807 | | |
