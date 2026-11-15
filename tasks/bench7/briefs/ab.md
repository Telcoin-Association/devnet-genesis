# AB — the analysis briefs for bench 7 (runs 7a and 7b), written before the runs

Unit: `AB` (brief writer, opus, no code, no cargo, no cloud). Rules: `tasks/bench7-agent-rules.md` (the common sections). Checkpoint: `tasks/checkpoint-bench7-AB.md` (a `status:` header and the list of finished sections, rewritten after EACH brief; on start read it and continue from the first unfinished section). Budget: under 200k tokens. If a Write is refused, do not work around it: return the complete text in your final answer between `===== BEGIN <path> =====` / `===== END <path> =====`.

## Why

Bench 7 runs the two forms of the vote fix once each at 20,000 IOPS on the latest main (execution store tn-lmdb), with the own-chain hold (#1807), the closing-block check and the three epoch-record switches on: run 7a = always-on (`quorum_exec_block_starved_rounds 0`), run 7b = adaptive (`4`). Each run is analysed by eight opus units, then two comparison units, then two report writers (`tasks/bench7-task-list.md` lines 99-105; the plan's paragraph "Analysis per run" and the "Fleet" line of its Verification section: `/home/drtnarg/.claude/plans/here-is-a-summary-lively-dolphin.md`). The runs have not happened yet. Your deliverable is the set of briefs those units will be launched from, so the analysis starts the moment a run is archived.

## Deliverable (files you write, all new, under `tasks/bench7/briefs/`)

- `a-common.md`: what every analysis unit reads first (the run facts as placeholders `<run>`, `<form>`; where the run's results, node logs and metric export are; the windows; the output directory `benchmark/private/bench7-<run>/<unit>/`; the checkpoint rule; the hand-back format; the rule that every figure names its source file and query; the rule that findings text is returned between BEGIN/END markers because a sub-agent's Write of `findings.md`-style files under `benchmark/private/` has been refused before).
- `a1.md` … `a8.md`: one per unit, in the task list's order: A1 KPIs · A2 certification · A3 per-header basis and window share · A4 closes and recovery · A5 engine · A6 disk · A7 losses (#1807) · A8 rounds. Each: the questions it must answer (as a numbered list a reader can tick), the scripts it reuses (path, what each takes, what must change for bench 7 and why), the metrics and log lines it reads (names verbatim from the sources below), its outputs (file names), and what it must NOT conclude (see "Limits").
- `a9.md`: run 7a against run 7b (the form comparison: the heart of bench 7). `a10.md`: bench 7 against bench 6's runs 2 (`r20261113-1351`, always-on) and 3 (`r20261113-2118`, adaptive), both 20,000 IOPS.
- A table at the end of `a-common.md`: unit → inputs → scripts → outputs → which other unit's output it needs.

Briefs are written for a reader who has none of this conversation: full paths, exact names, no unit jargon without its meaning. Model: `tasks/bench6-run2-analysis-brief.md` (87 lines: read it whole first) and one of this program's briefs for the form (`tasks/bench7/briefs/hb5b.md`).

## What you may read (and nothing beyond it: hand back instead of exploring)

- `tasks/bench6-run2-analysis-brief.md`; `tasks/bench6-handoff-2.md` §4.5 and §4.7 (the export, what the comparison must answer).
- The bench-6 analysis units, for their script names, arguments and outputs only (list the directories, read each script's header and argument parsing, not its body): `benchmark/private/bench6-r20261113-1351/{A1,A2,A3a,A3b,A4e,A4p,A6,A7,I-10}/` and `benchmark/private/bench6-r20261113-2118/{A1,A2,A3a,A4e,A4p,A7,I-10}/`; `benchmark/private/bench6-r20261113-1351/cross-unit-notes.md`.
- What bench 7's build and harness export: `tasks/bench7-contract.md` (the names contract); `benchmark/tools/log-shapes.txt` (the 32 kept log shapes); the hand-backs `tasks/checkpoint-bench7-HB-3.md` (storage measures on tn-lmdb), `-HB-5a.md` (launch files, `halt=` in the sampler, the export's 38 must-haves), `-HB-5b.md` (the arms summary's bench 7 blocks, the seventh fail-stop); `tasks/bench7/briefs/hd1-api.md` and `hd2-api.md` (the hold's observability: `tn_primary_requeued_out_of_order_total{cause}`, `own_parent` / `held` on `header proposed`, `tn_primary_headers_held_total`, `tn_primary_digests_held`); `tasks/checkpoint-bench7-HD-3.md` (orphan re-pool counters); `tasks/checkpoint-bench7-E2.md` (the certified-through gauge, the info line for the false quorum error); `tasks/checkpoint-bench7-E1.md` (the closing-block check's line and counters); `tasks/checkpoint-bench7-PT-3c.md` (the adaptive window now counts headers BUILT); `tasks/bench7/review/06-digest-order-hold-report.md` (only its open design question: held digests count toward the early-header trigger).
- `benchmark/tools/ANALYSIS.md`, `benchmark/tools/arms-summary.py` (header and `--help` text only), `tasks/bench7/orch-prom-export.py` (header only), `benchmark/launch/bench7-always.env`, `benchmark/launch/bench7-adaptive.env`, `benchmark/arms/bench7-*.arm`.
- `tasks/bench6-report-r20261113-1351.md` §8 only (the form comparison bench 6 could make) for the rows bench 7 must fill again.

## What the briefs must carry (decisions already taken; do not reopen them)

1. Run shape: run 2's shape (ten validators + one observer, the validator-05 kill, generator 62bbd5f, 20,000 IOPS Hyperdisk, the light and full blasts of the launch env); each configuration runs ONCE, so every comparison says "one run each" and gives no significance claim.
2. Two things changed against bench 6 at once: the storage engine (MDBX → tn-lmdb, #1834) and the hold. A10 attributes with node counters where it can and says where it cannot.
3. Disk: report BOTH the device write count (and syncs) and the bytes; on Hyperdisk the count and the syncs bind, not the bytes. Do not carry MDBX-only measures (page write ratio from the MDBX mapping) without saying they do not exist on tn-lmdb.
4. #1807 (A7): out-of-order re-queues by cause, `nonce_too_high` or its equivalent on this base, gap resends, unlanded, per validator; the hold's cost per validator (headers held, digests held, how long a lane stayed held, the validator's throughput share); and the measurement the hold's review asked for: the share of headers with `own_parent=false` per validator, and how often a header was built early because HELD digests counted toward the trigger (if the log fields allow it: say exactly which fields; if they do not, say so in the brief as a limit). Also `tn_worker_batch_reports_over_quota_total`.
5. The adaptive form's window (A3): `exec_policy=starved` counts headers built, not rounds, so its share is not comparable with bench 6 run 3's without that note.
6. Epoch records (A4): per close: signers, one hash, the `epoch record published` line's `branch`, the closing-block check counters (no mismatching result on any node), the certified-through gauge at the last closed epoch on every node, no line starting `epoch record conflict halt:` and none starting `epoch record conflict:`; recovery after the kill as bench 6 measured it.
7. The fleet checks of the plan's Verification section, as a pass/fail table in A1 or A7 (say which): `out_of_order`, `nonce_too_high`, gap resends and unlanded near 0 (generator 05's outage apart), `headers_held > 0` where headers were lost, no `mismatched` closing-block count, the gauge at the last closed epoch on every node.
8. The form gate (A9): the result is a recommendation to the user on the default form, with what would change it; it does not decide.

## Limits to state in the briefs

- A script of bench 6 that reads an MDBX field, a removed switch (`sealed_tx_keep`, `digest_dedupe`, `epoch_record_state_check`, `mdbx_random_advice`, `pipelined_persist`) or a log shape that this base no longer writes must be named with what replaces it. You establish this from the scripts' headers and the names contract only: where you cannot tell without reading a script's body or a node source file, write "to be checked by the unit on its first run" in that brief, with the exact thing to check. Do not guess a metric or field name: every name in a brief is copied from one of the sources above, with the source beside it in `a-common.md`'s table.
- No brief asks a unit to open a live node's data directory, to run cargo, or to touch the cloud: the units read the archived run only (`benchmark/results/<run>/`, the metric export, the node logs).

## Not yours

No script is changed or copied, nothing under `benchmark/` is written, no commit. Do not write the report writers' briefs (A11, A12).

## Hand back (a summary, not the files)

The list of files written (or their text between markers if a Write was refused); per analysis unit one line: scripts reused, what must change for bench 7; every "to be checked on the first run" item; anything in the sources that contradicts this brief or the plan; anything the harness does not export that an analysis question needs (that is a finding for the orchestrator BEFORE the fleet launches: put it first).
