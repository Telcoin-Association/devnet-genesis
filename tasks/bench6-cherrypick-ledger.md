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
| 41-44 | U5 | tracker-drain | epoch_close_task_drain, epoch_record_state_check | 9277bf947, 1f00d60a2, 115be0879, 584f86a83 | 2783dfa79..42b2a6f39 | #1806 | | |
| (held) | U12a | pipelined-persist | (core; not integrated until last) | e74947cca, 938493304, fd81652d2 | — | — | | |
| 45 | U4b | recovery-pool | — (bench binary) | e3f6c4ba3 | d0824a0a4 | #1805 | | |
| 46 | U3 | mdbx-advice | mdbx_random_advice (+ per-persist storage fields, no switch) | 03eb27bda | dddccd4a6 | #1802 #1800 | | |
| 47 | U3 | digest-dedupe | — (`sender` on the skip line) | e1f4a1b65 | 8bc341967 | #1807 | | |
| 48 | U10 | digest-dedupe | digest_dedupe (proposer half) | b6f415761 | 7fdcb9ff5 | #1807 | | |
| 49 | U10 | bench6-obs | — (digest wait from first receipt; review note on #1819) | af793ae56 | c8e5ae7be | #1819 note | | |
| 50 | U11 | inflight-bound | — (backlog recorded at forward; gauge) | ee277abaf | f792ef186 | — | | |
| 51 | U11 | inflight-bound | rpc_admission_backlog_outputs | e61d4eeda | 256422898 | — | | |
| 52 | orch | tracker-drain | — (config doc: the check is on a STORED record; D44) | — | 2c9b43209 | #1806 | | |
| 53 | orch | inflight-bound | — (config doc: who is gated, bounds above 73 never close; D49) | — | 74662a889 | — | | |
| 54 | U6b | sealed-keep | sealed_tx_keep (builder side: ticket, mark on quorum ack, selection skip) | 760813fa0 | c08d78c33 | #1807 | | |
| 55 | U6b | sealed-keep | — (orphan pass clears sealed marks on every pool; conflict with U5's tests in close_epoch.rs resolved by keeping both test sections) | 11c813596 | 3bbcbe226 | #1807 | | |
| 56 | orch (U6b's patch, reworked) | sealed-keep | — (node wiring: the worker's sealing mode reaches the builder; without it the switch marks nothing) | — | 3ee6b629f | #1807 | | |
| (held) | U12b | pipelined-persist | pipelined_persist (wiring: run_sequential verbatim + run_pipelined; metrics; persist hooks) | 2e2d5f3b4..1f9dde523 (7) | b6/pipe-stack a89ff912c..1c6ba2ef7 | — | | |
| (held) | orch | pipelined-persist | — (execution delay hook in the pipelined build task) | 2ea56e7dd | b6/pipe-stack 27de9976e | — | | |
| (held) | ST-U12a | pipelined-persist | — (differential + fault tests) | 2f763333f | b6/pipe-stack a2d2c3255 | — | | |
| 57 | orch | mdbx-advice | — (test helper: fixed genesis time, so the re-open tests do not depend on the clock; proof: forced 1.1-s gap passes with the fix, fails 3 of 4 without) | — | dc7855cc6 | #1802 | | |
| (held) | ST-U12c | pipelined-persist | — (cycle bench, gate 5; ignored test) | c6e207b15 | b6/pipe-stack c6e207b15 | — | | |
| 58 | orch (review follow-up) | digest-dedupe | — (docs: when the worker suppresses a seal) | — | b89ad570f | #1807 | | |
| 59 | ST-A | quorum-exec-block | — (e2e: fast executor certification in three arms; mixed-switch fleet is one chain) | 72bf1a3e6 | 8bd68e514 | #1804 | | |
| 60 | ST-A | tracker-drain | — (e2e: a loaded epoch close with a slow member, drain and control arms) | 35a3e71a4 | 4e9c19782 | #1806 | | |
| 61 | ST-A | quorum-exec-block | — (e2e: the adaptive arm must beat the control and reach 0.75) | 65a4bbcca | 31ef1149c | #1804 | | |
| 62 | ST-B | sealed-keep | — (e2e: validators mark and every tx lands once; mixed fleet; restart with marks; switch-off control) | 21db45417 | fe86f1658 | #1807 | | |
| 63 | ST-B | inflight-bound | — (e2e: the bound refuses then readmits; bound-0 control; observer forward survives closed gates) | 376a3ebc1 | 1e563ad4c | — | | |
| 64 | ST-B | sealed-keep | — (e2e: an S9 kill that leaves nothing to resend is reported, not failed) | 2a0c07497 | ae62cc47a | #1807 | | |
| 65 | orch (review follow-up) | mdbx-advice | — ("applied" logged only with advised bytes; docs: off arm is libmdbx's own advice, re-advice on limit change) | — | c88936999 | #1802 | | |
| 66 | ST-B | sealed-keep | — (e2e: the switch-off control passes on either outcome and asserts a loss has the #1807 signature) | 47112ab84 | 341b2a269 | #1807 | | |
