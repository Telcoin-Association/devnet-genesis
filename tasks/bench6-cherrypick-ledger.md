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
| 67 | U1b | quorum-exec-block | quorum_exec_block_starved_rounds (adaptive form: the window resets only after 64 consecutive certified tip headers) | ab5cb926b | 20858d28d | #1804 | | |
| 68 | U1b | quorum-exec-block | — (e2e: the adaptive arm must reach 0.88) | 446280250 | 56f66e160 | #1804 | | |
| 69 | U9b | parent-grace | parent_grace (M1: a late certificate of the previous round puts its author back in the wait set) | 2c6fb42e7 | d83f8f79b | #1803 | | |
| 70 | U9b | parent-grace | — (M2: the next round's leader never arms a grace) | eb9ffe725 | 79a355f82 | #1803 | | |
| 71 | U9b | parent-grace | — (L1 a grace stays within G; L2 warn when capped; L4 authors on the grace lines; cost docs) | 903cdc693 | 4a9c61886 | #1803 | | |
| 72 | U9b | parent-grace | — (test: order of the round-jump end and the readiness latch) | 130513613 | f4ee92d92 | #1803 | | |
| 73 | ST-U12b | bench6-switches | — (e2e harness: TN_E2E_PARAMETERS merges parameters.yaml entries into every node a test starts) | e6bfabef1 | d91d65d3e | — | | |
| (held) | stack rebuilt | pipelined-persist | b6/pipe-stack-2 = d91d65d3e + 18: the 13 of b6/pipe-stack, ST-U12b's persist-delay hook and three e2e tests, and the orchestrator's 86956df51 (the hook read where the persist runs, so the standard e2e binary has it) | — | b6/pipe-stack-2 86956df51 | — | | |
| 74 | U6c | sealed-keep | sealed_tx_keep (M2: a pool that keeps sealed transactions gets twice the pending sub-pool limits) | a74a2b3a2 | 891e2b962 | #1807 | | |
| 75 | U6c | sealed-keep | — (M1: selection skips a candidate that left the pool after its snapshot) | 79aeea195 | d2c695797 | #1807 | | |
| 76 | U6c | sealed-keep | — (L1: a mark that lands after its digest was orphaned is refused) | ddf17068a | cc022b4d0 | #1807 | | |
| 77 | U6c | sealed-keep | — (a replacement that took a candidate's nonce holds back the sender's later nonces) | 75460dff9 | 8b23bb608 | #1807 | | |
| 78 | U6c | sealed-keep | — (the orphan pass fences late marks with the ticket floor) | ead6f624b | c8659e2fa | #1807 | | |
| 79 | orch (U6c's patch + test) | sealed-keep | — (the env builds the worker pool with its sealed_tx_keep: without it the raised limits never applied) | — | 80a0c76c0 | #1807 | | |
| (in) | orch | pipelined-persist | pipelined_persist — **INTEGRATED 2026-11-12** (G1 answer 2: gates 5 and 6 passed): b6/pipe-stack-2's 19 commits cherry-picked onto 80a0c76c0 with no conflict as b6/pipe-stack-3, and bench/bench6-2026-11 fast-forwarded to its tip. The diff of the new tip against the old one equals d91d65d3e..80a0c76c0 (same patch-id). Rows 80-98 map each old commit to its integrated one. | d91d65d3e..d30bb1809 (19) | 80a0c76c0..2df831e3c | — | | |
| 80 | stack | pipelined-persist | — (feat(tn-reth): pin one read snapshot per output for the layered state root) | 5472d5ee1 | 86d86d910 | — | | |
| 81 | stack | pipelined-persist | — (refactor(engine): split output execution into build and commit halves) | ceab12841 | 49d4356aa | — | | |
| 82 | stack | pipelined-persist | — (feat(engine): pipelined persist core behind PersistPipeline) | cbe6e1af0 | a4a1f0962 | — | | |
| 83 | stack | pipelined-persist | — (feat(engine): pipelined persist metrics) | 81e5f7144 | da6e4c90c | — | | |
| 84 | stack | pipelined-persist | — (test(tn-reth): persist delay hook for engine pipeline tests) | 70c553f44 | 07a3008ac | — | | |
| 85 | stack | pipelined-persist | — (feat(engine): run the pipelined persist behind pipelined_persist) | 9b3a4cbfc | e83e6799b | — | | |
| 86 | stack | pipelined-persist | — (docs(tn-reth): atomicity contract with a pipelined engine) | ff5cd2185 | 93c5c3abd | — | | |
| 87 | stack | pipelined-persist | — (docs(engine): queued recovery jobs share the recovery pool when one is set) | a3d266304 | 02c704c96 | — | | |
| 88 | stack | pipelined-persist | — (fix(engine): pipelined loop fails closed with nothing to wait on) | 3e314c545 | 1b583ca2c | — | | |
| 89 | stack | pipelined-persist | — (docs(engine): pipelined persist series export zero on a sequential node) | 466d6174c | df2d19936 | — | | |
| 90 | stack | pipelined-persist | — (test(engine): apply the execution delay hook in the pipelined build task) | 7276103fd | e82405057 | — | | |
| 91 | stack | pipelined-persist | — (test(engine): differential and persist-fault tests of the pipelined persist) | 181320d5f | 0015715e8 | — | | |
| 92 | stack | pipelined-persist | — (test(engine): cycle bench of the pipelined persist (go/no-go gate 5)) | 9bcbf8bc4 | dc80cd040 | — | | |
| 93 | stack | pipelined-persist | — (test(types): TN_TEST_PERSIST_DELAY_MS holds every persist for e2e tests) | 71ae39958 | f8ae2459e | — | | |
| 94 | stack | pipelined-persist | — (test(e2e): pipelined and sequential validators build the same chain) | c76114d64 | 9c87e8cef | — | | |
| 95 | stack | pipelined-persist | — (test(e2e): pipelined validators close an epoch under load) | c6240f467 | 330913184 | — | | |
| 96 | stack | pipelined-persist | — (test(e2e): SIGKILL a pipelined validator mid-pipeline and replay) | f61988587 | 2c6454432 | — | | |
| 97 | stack | pipelined-persist | — (test(reth): read the persist delay hook where the persist runs) | 86956df51 | 9409c2db5 | — | | |
| 98 | stack | pipelined-persist | — (test(reth): log the persist delay hook when the environment is created) | d30bb1809 | 2df831e3c | — | | |
