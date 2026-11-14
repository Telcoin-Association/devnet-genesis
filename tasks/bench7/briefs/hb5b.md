# HB-5b — the bench 7 analysis columns in the arms summary, and three small things in the halt watch

Unit: `HB-5b` (harness unit, opus). Rules: `tasks/bench7-agent-rules.md` ("Harness units" and the common sections). Checkpoint: `tasks/checkpoint-bench7-HB-5b.md`. Budget: under 200k tokens.
You do not commit. The `benchmark/` tree is free when your launch prompt says so.

## Part 1 — three small things left by the unit before you (do these first; one hour at most)

Its notes: `tasks/checkpoint-bench7-HB-5a.md` (the halt count in `benchmark/node-sampler.sh`, the watch `tasks/bench7/orch-fleet-health.sh`, how the two golden fixtures that embed the sampler are regenerated).
1. **The seventh fail-stop.** The sampler's `halt=` counts six phrases. The node has one more stop: a re-certify round that finds this node's old record in conflict logs `own epoch record differs from a certified record in a re-certify round` with the field `stop=true` when it stops the node (and `stop=false` when it only reports). Count a line that carries BOTH the message and `stop=true`; a `stop=false` line is not a halt. Regenerate the fixtures; tests for both forms.
2. **The watch can be restarted after a halt.** Today a halt alarm ends the watch with exit 3 and a restarted watch alarms again at once (the count never goes back down). Add `--halt-baseline <n>` (default 0): the alarm is raised only when the fleet's halt sum is ABOVE the baseline; the `FLEET_HEALTH` line still prints the real sum and the halted nodes. Tests.
3. **Two doc lines.** `benchmark/README.md` describes `BENCH_STATUS` without `halt=`; the file table at the top of `benchmark/launch/README.md` lacks the two bench 7 env files. Add them.

## Part 2 — what the bench 7 analysis needs from `benchmark/tools/arms-summary.py`

The tool summarizes a run per arm from the run's manifest, the generator's results, the samplers' CSVs and the node logs (streamed through `tools/log-shapes.txt`; the unit before you added the build's new lines there). Bench 7 has ONE arm per run (the arm is applied before the first start), so "per arm" is "per run"; the new blocks are mostly PER VALIDATOR tables inside that one arm.
Source of truth for every name: `tasks/bench7-contract.md` (sections 2 and 3, from the node's code). Where a figure can come from the logs, take it from the logs (the tool does not read Prometheus); say for each new figure which line and fields it reads.
New output appears ONLY when the run's lines carry the new fields (a bench 6 run's `arms.md` and `arms.json` stay byte-identical: the two tests that compare with earlier commits must pass unchanged, as they did after the last change to this tool: `tasks/checkpoint-bench7-HB-2f.md` says how that unit kept them so).

A. **The order hold (#1807), per validator** (from `header proposed`: `round`, `num_batches`, `own_parent`, `held`, `held_lanes`, `blockers`, and the line's reason/trigger field if it has one: check the contract; from `digests resent`: `out_of_order`, its cause field; from `proposer stopped`; from the warning `digests re-queued out of order under the order hold`; from `uncertified own header report dropped` if the bench filter logs it):
   1. headers built; headers with batches; **the share of batch-carrying headers whose NEXT own header has `own_parent=false` or skips a round** (this is the one number the hold's review asks for: how often a blocker is created);
   2. headers with `held > 0`; the longest and the median run of consecutive headers with `held > 0` (in headers and in seconds, from the lines' timestamps); the largest `held`; headers with `held > 0` and `num_batches = 0` (a header built that could carry nothing);
   3. re-queues: digests re-queued, of them `out_of_order` (by cause), the count of the out-of-order warning (expected 0 with the hold on);
   4. cadence: the median and p95 interval between own headers, split into headers with `held > 0` and without;
   5. at the proposer's stop: `queued_digests`, `uncertified_digests`, `in_flight_digests` per epoch (the largest).
   One table, one row per validator, plus a fleet row; a legend that says what each column counts and that "out of order" is counted per re-queue event at the proposer, not a confirmed execution inversion.
B. **The vote fix's forms, per validator** (from `header proposed`: `exec_policy`, `exec_basis`, `exec_tip`, `exec_block`): the share of headers by policy (`off|always|tip|starved`) and by basis (`tip|quorum|floor`), the largest `exec_tip − exec_block`, and the share of headers certified by policy if the tool already joins headers with `quorum reached` (it has a certification record: reuse it; do not build a second join). If bench 6's tool already prints part of this, extend it rather than duplicate, and say what was there.
C. **Epoch records, per node** (from `epoch record published` with `branch`; `epoch record re-certify round`; `epoch record certified from kept votes`; `epoch record collector walking past an uncertified epoch`; `epoch record conflict:` and `epoch record conflict halt:`; `failed to reach quorum on epoch close` and its info twin; `retrieved cert for epoch`): closes seen; records published by branch; re-certify rounds and what certified them; walks; conflicts; halts. One row per node; everything 0 or "none" on a healthy run, so the block also says in one line whether every node published a record for every closed epoch.
D. **Fail-stops and hooks**: one line listing every fail-stop phrase of the contract's section 4 with its count over all nodes (0 expected), and one line asserting that no `test hook:` line appears (a benchmark image must have none).
`arms.json` carries the same figures under new keys (list them); the markdown legend explains every new column in one sentence each.

## Files you own

Part 1: `benchmark/node-sampler.sh`, its two golden fixtures, `tasks/bench7/orch-fleet-health.sh`, `tasks/bench7/tests/test_orch_scripts.py`, `benchmark/tests/test_recovery.py` (your tests), `benchmark/README.md` (the `BENCH_STATUS` description), `benchmark/launch/README.md` (the file table).
Part 2: `benchmark/tools/arms-summary.py`, `benchmark/tests/test_arms_summary.py`, `benchmark/tools/log-shapes.txt` only if a line Part 2 reads is missing there (say which). One block appended to `benchmark/tests/check_mutations.py`.
Nothing else. No other unit edits `benchmark/` while you work.

## Tests and gates

`bash -n`, `shellcheck -S warning`, py_compile and the 3.9 grammar check on what you changed; from `benchmark/tests`: `test_arms_summary`, `test_run1_rehearsal`, `test_recovery`, `test_node_image`, `test_pull_logs` green; `tasks/bench7/tests` green; a bench-7-shaped fixture run with two validators whose lines exercise every new column (one validator with held headers and an out-of-order re-queue, one clean), with the expected figures computed by hand in the test; mutation anchors by hand, reported verbatim: count a `stop=false` line as a halt; ignore the halt baseline; count the next header's `own_parent` on the wrong header (off by one); let the new block appear on a run whose lines lack the fields: each must fail a named test. The whole suite is the orchestrator's to run.
Never end your turn while a test run of yours is going. If an Edit or Write is refused by the permission layer, do not work around it: hand back the text.

## Hand back

As the rules say, plus: Part 1's three changes in one line each; every new column with the line and fields it reads; the new `arms.json` keys; the fixture's expected figures; the mutation anchors with the test each fails; what the tool cannot know from logs alone (so the analysis must take it from the metric export).
