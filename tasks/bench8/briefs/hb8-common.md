# HB8 units — common brief (the bench 8 harness)

Read `tasks/bench8-agent-rules.md` first (budget 35 tool calls, about 120 printed lines per call; checkpoints `tasks/checkpoint-bench8-<unit>.md`), then the section "Harness units" of `tasks/bench7-agent-rules.md` and the files it tells a harness unit to read first (`tasks/bench4-agent-rules.md`, `tasks/bench4-obs-agent-rules.md`, the "Harness and txgen units" section of `tasks/bench5-agent-rules.md`: `grep -n '^## '` first, read only those sections), then this file, then your own brief.

## What bench 8 is

Bench 7 (2026-11-15) lost certification before the kill of validator-05 (94.0 % in run r20261115-1131, always-on; bench 6 had 99.96 %). Bench 8 changes one thing per run on bench 7's image commit plus log fields (branch `bench/bench8-2026-11`, from 91a15e223: the SEVEN switches of bench 7's image stay, `epoch_record_conflict_halt` among them, plus one new count parameter `quorum_exec_block_floor_outputs`, default 8).
- Control shape: bench 7's always-on run with the kill (`benchmark/launch/bench7-always.env`, `benchmark/arms/bench7-always.arm`).
- Run F: the same with `quorum_exec_block_floor_outputs 16`. Run C: the control repeated (floor 8 written out). Run H: the control without the order hold (`digest_order_hold false`). Run R: the control at reduced load, about 5,300 tx/s in the load blast (`BENCH_SENDERS=300`, `BENCH_WINDOW=3`; the harness has no pacing option; the run is void outside 4,500-6,500 tx/s).
- Read window: the load blast before the kill, and its first 817 s (run r20261115-1131's kill came 817.1 s into the load blast's mixed phase; run r20261115-1653's came 1,121.2 s in, with the same profile).
- The report's list of what to fix before the next run: `tasks/bench7-report-r20261115-1131.md`, section "To fix before the next run" (`grep -n '### To fix before the next run'`, nine lines) and "What cost fleet time" above it.

## Rules (on top of the harness rules you read)

- You do NOT commit; the orchestrator commits per unit. One writer per file: only the files your brief lists. If you need another file, stop that item and say so.
- A knob left unset keeps the old path byte-identical, with a test that proves it. Dry runs never share a code path with a live call. No literal IPv4 except the documentation nets, never the cloud project's name as a literal, no absolute home path in a harness file.
- Gates: `bash -n`, `shellcheck -S warning`, `python3 -m py_compile` and the 3.9 grammar check on what you changed; your own test module(s) green; the test modules that import or run what you changed green. The whole-suite gate (`benchmark/tests/gate.sh`) is the orchestrator's.
- Nothing remote: no `gcloud`, no ssh, no docker pull. Fakes for tests are under `benchmark/tests/fixtures/` and `tasks/bench7/tests/fakes/`.
- Hand back: files with +/- counts, every new knob, arm, manifest key, CSV column, log tag and exit code verbatim, the gates with their results, and what you found that the other harness unit or the orchestrator must know.
