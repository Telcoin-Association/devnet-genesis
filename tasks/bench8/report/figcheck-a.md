# Figure-check FC-R8a: §1, §2, §3 of the bench 8 report (s1.md, s2.md, s3.md)

FIX
No error changes a conclusion; two are wrong (one fact about run 1's manifest, one evidence mark in §1), five are weak, one breaks the report's rules.

## Method

§3's tables were compared by script against the JSON (markdown parsed, JSON keys read): 3.1, 3.3, 3.4, 3.5 (both tables) and 3.6, 3.7 cell by cell (626 values, 626 match), 3.2's 32 cells (start, certified %, proposed, reached: 128 values, all match; epoch and validator-05 labels read by eye, all match).
The W-e5 and Wgen rows were read from q2-/q4u-*-We5.json and *-Wgen.json; run 1's W-e5 per-author line from q2-r20261116-2011-We5.json; 3.8 from each run's analysis/certification.json ("blast 2 mixed") and the run facts.
§2's timelines were read from the three manifests (timestamps, param_arms, coordinated_start, blasts[].phases, chaos, fleet_ready, prom_window, archive, log_coverage) and the run facts (export, teardown, archive verify); every time offset the text computes was recomputed.
§1 was compared with §3 to the digit and, for its marks and wording, with the analyses' figure-checks and with s4.md.

## Errors

1. s2.md §2.5, "Run 1's manifest has `archive` and `log coverage` empty (null)".
The manifest (benchmark/results/r20261116-2011/manifest.json) has both filled: `archive` {kind local, files 649, bytes 3,074,580,815, verified_at 23:07:04Z, reindexed_at 23:10:50Z} and an 11-entry `log_coverage`.
Only the run facts (RF1 lines 34-35) read them as null; s2.sources.md cites RF1, not the manifest.
Old: "Run 1's manifest has `archive` and `log coverage` empty (null) while its run facts record the archive verify; runs 2 and 3 have both fields filled."
New: "Run 1's run facts read the manifest's `archive` and `log coverage` as empty (null), but the manifest in the results directory has both filled, as runs 2 and 3 do; the run facts also record the archive verify."

2. s1.md, Answer bullet 4, mark "[measured]" on "so depth moves the threshold".
§4.3 (s4.md line 89) marks that reading "[inferred, a timing fit] The threshold moves with the floor"; only the two epoch figures and the regrown spread are measured there.
Old: "- [measured] A floor of 16 kept the first load epoch clean (99.919 %) and not the second (95.988 %), so depth moves the threshold and does not remove the drift (§4.3)."
New: "- [measured; that depth moves the threshold is inferred, a timing fit] A floor of 16 kept the first load epoch clean (99.919 %) and not the second (95.988 %): depth moves the threshold and does not remove the drift (§4.3)."

## Weak

1. s1.md, "Run 1's first 817 s read 99.895 %, as clean as run 3".
Run 1's W-817 lost 24 headers, run 3's 12 (99.895 against 99.949 %); A-F3's figure-check (note 5, not note 1 as s1.sources.md says) says only that it is "inside the same row's thresholds".
Old: "Run 1's first 817 s read 99.895 %, as clean as run 3: the contrast between full and reduced load is in the longer windows."
New: "Run 1's first 817 s read 99.895 % with 0.03 % under-held, inside the same thresholds of the plan's rule as run 3's 99.949 %: the contrast between full and reduced load is in the longer windows."

2. s1.md line 14, "7a's rate is bench 7's chain count over its whole mixed phase".
Bench 7's 9,289 is over the 2,375 s in which all ten generators were in their mixed phase (bench 7 report line 26; §3.6 says so), not the whole mixed phase (2,425 s in 7a's certification.json).
Old: "7a's rate is bench 7's chain count over its whole mixed phase, a different window."
New: "7a's rate is bench 7's chain count over the 2,375 s in which all ten generators were in their mixed phase, a different window."

3. s2.md §2.3, "10,334 of their transactions landed" gives the count to generators 02 and 06.
A-F3's figure-check (line 19) and first look (line 62) count all generators' own landed transactions in those 85 s.
Old: "sent until 16:06:15; 10,334 of their transactions landed and validator-01 executed 28,893 in those 85 s"
New: "sent until 16:06:15; the generators landed 10,334 transactions of their own and validator-01 executed 28,893 in those 85 s"

4. s2.md §2.1, "the same eight switches (…)" lists seven names; the eighth, the floor parameter, is missing from the list (both .arm files hold eight params).
Old: "Both arms set the same eight switches (`quorum_exec_block` on, `quorum_exec_block_starved_rounds` 0, `vote_queue_fix`,"
New: "Both arms set the same eight switches (`quorum_exec_block` on, `quorum_exec_block_starved_rounds` 0, `quorum_exec_block_floor_outputs`, `vote_queue_fix`,"

5. s3.md §3.0 and s2.md §2.2: runs 1 and 2's manifest mixed phase "matched the generators' own phases" / "the same as the manifest" has no source in s3.sources.md or s2.sources.md for run 1.
The generators' results (blasters/*.json `run.phases`) show the manifest's start is the earliest generator's; the others began up to 16 s later in run 1 (21:54:55 to 21:55:11) and up to 9 s later in run 2 (00:54:44 to 00:54:53).
Old (s3.md): "which matched the generators' own phases in those runs."
New (s3.md): "which is the earliest generator's own mixed start in those runs (the others began up to 16 s later in run 1 and 9 s later in run 2)."
Old (s2.md): "| blast 2 mixed phase, generators' own | the same as the manifest | the same as the manifest |"
New (s2.md): "| blast 2 mixed phase, generators' own | the manifest's start for the earliest generator, the others up to 16 s later | the manifest's start for the earliest generator, the others up to 9 s later |"

## Rule breaches

1. s2.md §2.5 table: the bucket name `tn-devnet-benchmark-archive` carries the cloud project id (`project: "tn-devnet"` in every manifest).
Old: "archive verify (`gs://tn-devnet-benchmark-archive/runs/<run>/results/`)"
New: "archive verify (the canonical archive bucket, `runs/<run>/results/`)"
No host name, IP address, assistant, agent (other than the nodes' metrics agent) or tool is named; every running-text line holds one sentence; "one run per configuration" is said in §1 (line 4), §2.3 and §3.

## Not traceable

None in the text.
The run 3 export's "17 MB" is only in tasks/checkpoint-bench8-orch.md (line 326), not in RF3; s2.sources.md says so.

## Notes (no change needed, or optional)

- §2.2's teardown times are the run facts' `TEARDOWN_DONE` lines (23:10:27, 02:28:38, 19:03:06); the manifests' `timestamps.teardown_done` read 23:09:43, 02:27:42 and 19:02:05; both are traceable.
- §3.8, 7a per validator: certification.json has all ten; optional replacement in s3.md: "06 83.6, 08 85.5, 04 95.6, 10 97.7 (the others not in the run facts)" → "01 100.0, 02 98.7, 03 98.2, 04 95.6, 05 100.0, 06 83.6, 07 99.9, 08 85.5, 09 99.5, 10 97.7".
- §1 against §4: bullets 1, 2, 3, 5 and "New in bench 8" read the same as s4.md (1,251 of 1,258; 99.40 / 82.26; 193 of 230; 0.959-0.984 and 0.555-0.589; 53; nine minutes, never in runs 1 and 3; 96-98 %, 17-30 %); bullet 3's mark matches A-F2 line 223 and A-F3 line 160; bullet 2's round end is measured by timing in §4.2.
- The plan's rule is quoted exactly: Step 5d, row R, "…; stop".
- "For the owner" states nothing as decided; the merge (#1862, main 5533ff73a, no switch left) matches the orchestrator log at 14:30Z.
- s1.sources.md cites "AF3's figure-check note (1)" for 99.895 %; it is note 5 (AF3/figcheck.md line 72).

## Counts

Figures checked: about 1,160 (§3 about 940: 626 table values by script, 128 bucket values, 32 bucket labels, 39 window bounds and lengths, 30 harness per-validator values, the rest prose; §2 about 175; §1 about 45).
Matched: about 1,152.
Wrong: 2.
Weak: 5 (W5 counts its two places once).
Rule breaches: 1.
Not traceable: 0.
