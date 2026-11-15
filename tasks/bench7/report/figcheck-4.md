# Figure-check FC-4: §5 (s5.md) and §7 (s7.md)

## Counts

| section | figures checked | match | wrong | untraceable | weak |
|---|---|---|---|---|---|
| §5 s5.md | 192 | 178 | 5 | 0 | 9 |
| §7 s7.md | 301 | 294 | 6 | 0 | 1 |

Not checked: s7.md line 20, "Q5 bucket rows" (whether `q5_per_validator` holds bucket rows); s7.md lines 61-80, the key names in parentheses inside the value cells (values, classes and notes were compared against `q6_contradictions`, the first/second key fields were not); s5.md line 62, the high side of the 300-s bucket ratios was only checked down to 1.0759 (the low side, 0.9488 and 0.9507, is confirmed as the two lowest outside the queued-outputs gauge).

## Wrong

W1. s5.md line 22, the lost attempt's idle cell: "3.7 min after the stop".
Source: chain log `tasks/bench7/r20261115-1450/chain-20261115T145016Z.log` last lines, `CHAIN stop reason=idle-check up up=9/11 … 2026-11-15T16:04:23Z`; `tasks/bench6/r20261115-1450/blast15-20261115T160808Z.log` line 1, `== blast15 start 2026-11-15T16:08:08Z`: 225 s = 3.75 min, which rounds to 3.8; the deploy ended at 15:59:07Z (`deploy12-20261115T145017Z.log` line 13829, `== deploy12 rc=0 2026-11-15T15:59:07Z`), 9.0 min before the blast.
Replacement cell: "3.8 min after the stop (9.0 min after the deploy's end, 15:59:07Z)".

W2. s5.md line 45, lost attempt row: "each lacked one to three must-have series at the idle check".
Source: `tasks/bench7/r20261115-1450/prom-idle-check.txt` lines 1, 3, 4, 5, 14 (`status=incomplete`): validator-01 lacks three must-haves, validator-05 three, validator-09 two, validator-10 none; validators 09 and 10 lacked `up` (chain log, `up=9/11 missing=bench-validator-09,bench-validator-10`), and `up` is not one of the check's must-haves.
Replacement cell: "validators 01 and 05 lacked three must-have series each and validator-09 two; validators 09 and 10 lacked `up`".

W3. s5.md line 56: "88 rounds hold all 11 nodes and five, during validator-05's outage (18:44:37Z to 18:48:36Z), lack it; the orchestrator's count leaves one round unchecked [O 19:28Z]."
Source: `tasks/bench7/r20261115-1653/endpoint-sampler-20261115T174624Z.log`: 94 `ENDPOINT_SAMPLE` round lines, 89 with `ok=11/11`, rounds 59 to 63 (18:44:37Z to 18:48:36Z) with `ok=10/11 failed=bench-validator-05`, no other round short; the orchestrator's entry (19:28Z, line 1255: "88 with 11/11 … (+1 round to check)") miscounted.
Replacement: "89 rounds hold all 11 nodes; the other five (18:44:37Z to 18:48:36Z, validator-05's outage) lack validator-05 and no other node [RF 7b]."

W4. s5.md line 63: "blast 2's consensus-store write-stall seconds agree within 0.03 s on the seven validators whose export is whole other than validator-05".
Source: `benchmark/private/bench7-r20261115-1653/A6/disk.json` `q3_commit.tndb_write_stall_b2_prom_vs_snap`: validator-06 `prom_s` 10.0904, `snap_s` 10.1220, a difference of 0.0316 s; the other six differ by at most 0.022 s (validator-04).
Replacement: "blast 2's consensus-store write-stall seconds agree within 0.032 s on the seven validators whose export is whole other than validator-05 (the widest, validator-06: 10.090 s in the export, 10.122 s in the samples)".

W5. s7.md line 21, per-run files column: "`A7/losses.json` `senders`, `generator05`" under "both runs unless marked".
Source: `benchmark/private/bench7-r20261115-1131/A7/losses.json` has no key `generator05`; run 7b's has it.
Replacement cell: "`A1/kpis.json`; `A7/losses.json` `senders`, `generator05` (7b)".

W6. s7.md line 29: "`last_closed_epoch_in_export`" in `A4/closes.json`, unmarked.
Source: run 7a's `A4/closes.json` has no key `last_closed_epoch_in_export`; run 7b's has it.
Replacement cell: "`A4/closes.json` `closes`, `closing_block_check`, `close_identity_check`, `certified_through_at_end`, `last_closed_epoch_in_export` (7b)".

W7. s7.md line 30: "`side_by_side`" and "`rejoin_mark`" in `A4/recovery.json`, unmarked.
Source: run 7a's `A4/recovery.json` has neither key; run 7b's has both (7a's replay key is `replay_of_epoch5_s`, 7b's `replay_of_epoch4_s`, as the row says).
Replacement cell: "`A4/recovery.json` `kill`, `side_by_side` (7b), `kill_to_cvv_active_s`, `cooldown_end_to_promotion`, `rejoin_mark` (7b), `replay_of_epoch5_s` (7a) or `replay_of_epoch4_s` (7b); `A8/rounds.json` `q7_kill_epoch`".

W8. s7.md lines 24 and 28: `A9/comparison.md`, `A9/recommendation.md` and `A10/far-validators.json`, `.md` listed in the per-run column ("A-paths are per run, both runs unless marked").
Source: these four files exist only under `benchmark/private/bench7-r20261115-1653/`; none exists under `benchmark/private/bench7-r20261115-1131/`.
Replacement cells: line 24 "all of the comparison; `benchmark/private/bench7-r20261115-1653/A9/comparison.md`, `…/A9/recommendation.md`"; line 28 "`A7/losses.json` `far_generators`; `A2/numbers.json` `far`; `benchmark/private/bench7-r20261115-1653/A10/far-validators.json`, `.md`".

## Weak

K1. s5.md line 8: "At about 16:24Z, … the token could not be refreshed: "Reauthentication failed. cannot prompt during non-interactive execution" (the blast log's line 411)".
Source: the 16:24Z time comes from the endpoint sampler (`tasks/bench7/r20261115-1450/endpoint-sampler-20261115T160817Z.log`: rounds 1-16 `ok=11/11`, round 17 at 16:24:21Z `ok=0/11`) and the fleet watch ("list-failed" from 16:24:48Z, [O 16:45Z]); the blast log's line 411 comes after its 16:39:41Z poll and its line 409 "deadline reached", when the driver tried to collect the blasters at about 16:40Z, not at 16:24Z.
Replacement: "At about 16:24Z, 16 minutes into the blast segment and during the first light blast, the login's token expired: from 16:24:21Z the endpoint sampler reached none of the 11 nodes [O 16:45Z]. When the driver tried to collect the light blast at about 16:40Z, the copy failed with "Reauthentication failed. cannot prompt during non-interactive execution" (the blast log's line 411) [O 16:45Z]."

K2. s5.md line 14: "it is not a bench 7 run, and no figure in this report comes from it".
Source: [RF 7b] line 57 says "no figure comes from it" of the measurements; this section itself gives the attempt's idle-check times, `up` count, missing series and idle (lines 7, 22, 45).
Replacement: "it is not a bench 7 run, and no measurement in this report comes from it; this section uses only its harness times and its idle check [L 2026-11-15] [RF 7b]."

K3. s5.md line 25: "Every node the check named was healthy: its own metrics endpoint was whole and its logs complete [O 12:40Z] [O 16:10Z] [O 17:50Z]."
Source: [O 16:10Z] records the endpoints (5,104-5,106 series) and fleet health only; the lost attempt was not reindexed or archived and has no log-coverage check ([O 16:55Z]); "logs whole" is in [RF 7a] line 58 and [RF 7b] line 59, not in the cited entries.
Replacement: "Every node the check named was healthy and its own metrics endpoint was whole [O 12:40Z] [O 16:10Z] [O 17:50Z]; in runs 7a and 7b its logs are complete too [RF 7a] [RF 7b]."

K4. s5.md lines 35-37 (the mechanism stated as fact).
Source: [O 14:28Z] (line 1127) records as read on validator-09 only the config: scrape → relabel → remote_write, the relabel setting `network` = TN_CHAIN on every series; the silent drop inside a request, the straddled 2,000-sample batch boundary and the per-process hash order are the orchestrator's explanation in the same entry, not reproduced; what was observed is the HTTP 400 "duplicate sample for timestamp …; overrides not allowed: existing 0, new value 1" on a batch of about 737 samples every 15 s ([O 12:40Z] line 1025) and validator-05's missing series returning after its restart ([O 19:28Z] line 1258).
Replacement line 35: "By the orchestrator's explanation, not reproduced, Prometheus drops the second of such a pair silently inside one remote-write request [O 14:28Z]."
Replacement line 36: "When a pair with different values straddles the boundary between two 2,000-sample batches, the later request meets a committed sample and Prometheus rejects that whole batch; what the agent logged on validator-09 was "duplicate sample for timestamp …; overrides not allowed: existing 0, new value 1" on a batch every scrape [O 12:40Z] [O 14:28Z]."
Replacement line 37: "By the same explanation the batch hit depends on the order in which the node process exposes its series (hash order per process); in run 7b validator-05's missing series came back after its restart [O 14:28Z] [O 19:28Z]."

K5. s5.md line 39: "Bench 6's run 3 lost a validator's vote-stage series the same way [O 14:28Z]."
Source: a nickname without its run id (the text's rules); the run id is `r20261113-2118` (`benchmark/private/bench7-r20261115-1653/A10/vs-bench6.json` `q1_same_shape.runs.b6r3`); the entry states it in a parenthesis with no evidence of its own.
Replacement: "By the orchestrator's reading, bench 6's run 3 (`r20261113-2118`) lost a validator's vote-stage series the same way [O 14:28Z]."

K6. s5.md line 53: "What stands in is `tasks/bench7/orch-endpoint-sampler.sh`, built at the lost attempt's idle check".
Source: rule 7 of the writers' brief: private paths appear only in the appendix and in cites.
Replacement: "What stands in is the orchestrator's endpoint sampler, written at the lost attempt's idle check: one read-only ssh per node per round, a `curl` of the node's own exporter, the text gzipped [O 16:10Z]."

K7. s5.md line 64: "the vote stage's pre-lock wait mean differs by up to 19.2 % before the kill".
Source: `benchmark/private/bench7-r20261115-1653/A8/rounds.json` `coverage.endpoint_xcheck`: `B2-prekill.prelock_wait_mean_ms.max_rel_diff_pct` 19.2, but `B2-first120` (also before the kill) 96.5 and `B2-poststart` 39.38.
Replacement: "the vote stage's pre-lock wait mean differs by 19.2 % over blast 2 before the kill, by 96.5 % over its first 120 s and by 39.4 % after validator-05's start, and its lock mean by up to 100 % [7b A8 coverage.endpoint_xcheck]."

K8. s7.md line 90: cite "[O 20:02Z]".
Source: five entries of `tasks/checkpoint-bench7-orch.md` carry 20:02Z (lines 450, 455, 457, 1420, 1427); the one meant is the last ("A5 of 7a DONE", line 1427), and the cite form defines only `b` for a second entry.
Replacement: "[O 20:02Z, A5 of 7a]" (or extend line 11's cite-form note: "where several entries share a time, the cite names the unit").
