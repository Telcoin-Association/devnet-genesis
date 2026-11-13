# Stage latency: r20261106-1000

- bench-validator-01: authority A1aaaaaaaaaa, 5 own blocks, 53 log lines from bench-validator-01-unit-stdout.log.gz; generator bench-blaster-01.json; F1 build: yes.

## Headline (seconds; chain = summed stages, gen = from the generator's own_submit_p50_ms)

| window | ts p50 | ts p95 | commit p50 | commit p95 | seen p50 | seen p95 | gen ts p50 | gen ts p95 | gen commit p50 | gen commit p95 | gen seen p50 | gen seen p95 | coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| light8 | 0.705 | 0.884 | 1.305 | 1.484 | 3.069 | 3.248 | 0.707 | 0.886 | 1.307 | 1.486 | 3.075 | 3.254 | 100 % of 2 |
| load | 0.583 | 0.884 | 1.305 | 1.484 | 1.970 | 3.248 | 0.585 | 0.886 | 1.307 | 1.486 | 2.371 | 3.254 | 50 % of 4 |
| all | 0.583 | 0.884 | 1.305 | 1.484 | 1.970 | 3.248 | 0.585 | 0.886 | 1.307 | 1.486 | 2.371 | 3.254 | 50 % of 4 |

## light8: 2026-11-06T10:00:00Z → 2026-11-06T10:01:00Z, epoch boundaries excluded

| stage | what | n | p50 ms | p95 ms | unmeasured | basis |
|---|---|---:|---:|---:|---:|---|
| S0 | RPC accept | 2 | 6 | 7 | 0 |  |
| S1 | pool wait | 2 | 40 | 60 | 0 |  |
| S2 | seal -> 2f+1 acks | 2 | 128 | 148 | 0 |  |
| S3 | report | 2 | 5 | 6 | 0 |  |
| S4 | digest wait | 2 | 164 | 345 | 0 | batch_reported 2 |
| S5 | certification | 2 | 150 | 150 | 0 |  |
| S6a | own cert -> leader created | 2 | 190 | 190 | 0 | leader_created_at_ms 2 |
| S6b | leader created -> commit | 2 | 600 | 600 | 0 | leader_created_at_ms 2 |
| S7 | execution wait | 2 | 1200 | 1200 | 0 | waited_line 2 |
| S8 | batch fetch | 2 | 4 | 4 | 0 |  |
| S9 | pack persist | 2 | 3 | 3 | 0 |  |
| S10 | channel + engine queue | 2 | 305 | 305 | 0 | forward+queue 2 |
| S11 | execute | 2 | 80 | 80 | 0 |  |
| S12 | persist + announce | 2 | 22 | 22 | 0 | persist+announce 2 |
| S13 | visibility (scanner) | 2 | 150 | 150 | 0 | output_executed 2 |

Aux (p50 / p95): queued_before 3 / 5; pending_before 10 / 12; build_ms 2 / 3; slots_persist_ms 1 / 1; depth 2 / 2; task_ms 102 / 102; recover_ms 10 / 10; evm_ms 40 / 40; root_ms 20 / 20; finish_ms 8 / 8; other_ms 2 / 2.

## load: 2026-11-06T10:00:00Z → 2026-11-06T10:01:00Z

| stage | what | n | p50 ms | p95 ms | unmeasured | basis |
|---|---|---:|---:|---:|---:|---|
| S0 | RPC accept | 4 | 5 | 7 | 0 |  |
| S1 | pool wait | 4 | 40 | 60 | 0 |  |
| S2 | seal -> 2f+1 acks | 4 | 138 | 148 | 0 |  |
| S3 | report | 4 | 5 | 6 | 0 |  |
| S4 | digest wait | 4 | 96 | 345 | 0 | batch_reported 4 |
| S5 | certification | 4 | 150 | 150 | 0 |  |
| S6a | own cert -> leader created | 4 | 190 | 200 | 0 | leader_created_at_ms 3, leader_own_batch 1 |
| S6b | leader created -> commit | 4 | 600 | 750 | 0 | leader_created_at_ms 3, leader_own_batch 1 |
| S7 | execution wait | 4 | 0 | 1200 | 0 | no_line_below_threshold 2, waited_line 2 |
| S8 | batch fetch | 4 | 3 | 4 | 0 |  |
| S9 | pack persist | 4 | 2 | 3 | 0 |  |
| S10 | channel + engine queue | 4 | 305 | 356 | 0 | forward+queue 4 |
| S11 | execute | 4 | 60 | 80 | 0 |  |
| S12 | persist + announce | 4 | 16 | 22 | 0 | persist+announce 4 |
| S13 | visibility (scanner) | 4 | 150 | 200 | 0 | output_executed 4 |

Aux (p50 / p95): queued_before 2 / 5; pending_before 6 / 12; build_ms 2 / 3; slots_persist_ms 1 / 1; depth 2 / 3; task_ms 77 / 102; recover_ms 8 / 10; evm_ms 30 / 40; root_ms 15 / 20; finish_ms 5 / 8; other_ms 2 / 2.

## all: all blocks

| stage | what | n | p50 ms | p95 ms | unmeasured | basis |
|---|---|---:|---:|---:|---:|---|
| S0 | RPC accept | 5 | 6 | 9 | 0 |  |
| S1 | pool wait | 4 | 40 | 60 | 1 |  |
| S2 | seal -> 2f+1 acks | 4 | 138 | 148 | 1 |  |
| S3 | report | 4 | 5 | 6 | 1 |  |
| S4 | digest wait | 4 | 96 | 345 | 1 | batch_reported 4 |
| S5 | certification | 4 | 150 | 150 | 1 |  |
| S6a | own cert -> leader created | 4 | 190 | 200 | 1 | leader_created_at_ms 3, leader_own_batch 1 |
| S6b | leader created -> commit | 4 | 600 | 750 | 1 | leader_created_at_ms 3, leader_own_batch 1 |
| S7 | execution wait | 4 | 0 | 1200 | 1 | no_line_below_threshold 2, waited_line 2 |
| S8 | batch fetch | 4 | 3 | 4 | 1 |  |
| S9 | pack persist | 4 | 2 | 3 | 1 |  |
| S10 | channel + engine queue | 4 | 305 | 356 | 1 | forward+queue 4 |
| S11 | execute | 4 | 60 | 80 | 1 |  |
| S12 | persist + announce | 4 | 16 | 22 | 1 | persist+announce 4 |
| S13 | visibility (scanner) | 4 | 150 | 200 | 1 | output_executed 4 |

Aux (p50 / p95): queued_before 2 / 5; pending_before 6 / 12; build_ms 2 / 3; slots_persist_ms 1 / 1; depth 2 / 3; task_ms 77 / 102; recover_ms 8 / 10; evm_ms 30 / 40; root_ms 15 / 20; finish_ms 5 / 8; other_ms 2 / 2.

