status: complete
completed: [read, F1, stall-scan, blast-B, blast-C, blast-E, blast-F, config, tests, README, verify]
pending: []

# HB chaos implementation — checkpoint

## read — DONE
Audit H1 B/C/E/F, lessons 1-60, benchmark-blast.sh (1087 lines), test_recovery.py, recovery-schedule.py,
recovery-lib.sh, bench-lib helpers (bench_save_node_log 287, tn_iap_ssh_stdin devnet-lib.sh:54).
Prototype stall scan on r20261006-0053 sampler: only stretch inside planned mixed+cooldown window is
block 15513 02:10:00 -> 02:15:00 (300 s). Matches the audit.

## Deviations (with reasons)
- Staged script prints the SAME marker lines as the direct path (`BENCH_CHAOS_BEGIN node=<i> <unix.ms>`,
  `BENCH_CHAOS_END node=<i> rc=<rc> <unix.ms>`) so one parser reads both paths and chaos-remote.log keeps
  one format.
- Poll deferral covers kill/restart/observer only (not lag pause/unpause): an unpause retried every 60 s
  would otherwise defer every poll forever and starve the abort watchers.
- Commit-flat stretches must START inside the planned mixed phase (cooldown counts toward duration and
  closing only): cooldown is the generator's drain (no new sends), so blocks go flat there by design.
- chaos-stage-test uses due = now + BENCH_CHAOS_STAGE_SECS (the production lead), not now+5: with the log
  save (~4 s) and IAP setup (~3 s) a 5 s lead would measure setup, not staging. BENCH_CHAOS_STAGE_SECS=5 gives
  the spec's form. Requires --yes to touch the node (dry run prints the plan + bash -n of the script).
- Owed restart after an abort: t_back pulled forward to now (like t_unpause) so it runs on the next pass;
  lag pause excluded from the sleep target once aborted (the 1 s floor would otherwise spin).

## F1 — DONE
recovery-schedule.py snapshot(): epoch>0 with block_height 0 = not opened; test_recovery unopened case
now loops over encoded_epoch(epoch=7) and encoded_epoch(height=0, epoch=8). 7/7 green.

## stall-scan — DONE
benchmark/stall-scan.py (stdlib): --results DIR [--min-secs 60] [--bucket-secs 30]; prints JSON array
(start,end,secs,block,source:"sampler"[,open]) — blast.sh writes it to .commit_stalls_sampled.
Fixtures tests/fixtures/stall-scan/run/{manifest.json,sampler/*.csv}; tests/test_stall_scan.py 4/4 green.
Real run r20261006-0053 (read-only) -> one stretch 02:10:00-02:15:00, 300 s, block 15513.

## blast-B/C/E/F + config — DONE (bash -n OK; tests pending)
benchmark-blast.sh: header + chaos-stage-test/--instance args (help 2,53p); STAGE<GUARD check;
run-state globals (CHAOS_BEGIN, KILL_ENTRY, KILL_BEGIN, BACK_BEGIN, BOUNDARY_DONE, STATUS_SEEN,
POLL_SAMPLES, FLAT_*, STALL_WIN_*); chaos_mark, record_chaos (planned/begin/end/late/staged, END rc),
chaos_do (captures output), chaos_direct_cmd, CHAOS_STAGE_SCRIPT heredoc (function-wrapped, BEGIN write
checked), chaos_stage_send (validated CHAOS_* lines), chaos_save_report, chaos_staged (fallback),
chaos_restart_v05 [due]; next_action_due, poll_deferred, sleep_until (floor 1), status_samples,
status_collect, fleet_round/round_text, commit_flat_check, commit_stall_record, commit_flat_flush,
chaos_boundary_check [final]; loop rewired; do_collect collect_missing + stall_scan; do_chaos_stage_test.
config.sh: appended BENCH_CHAOS_STAGE_SECS=30, BENCH_CHAOS_GUARD_SECS=90, BENCH_STALL_NOTE_SECS=60.

## tests — DONE
test_recovery.py: helpers blast_functions/stage_script_block/run_chaos_shell; ChaosTimingTests (9: staged
script order+timing+bash -n, fallback before BEGIN, MAX_WAIT refusal w/o double save, poll deferral,
1 s floor, record_chaos parse, kill note, boundary verdict true/false/not-opened/retry/mixed) and
CommitFlatTests (3). 18/18 green. Mutation check on a scratch copy: 9/9 mutants rejected.

## README — DONE
Chaos section: staging paragraph, chaos-stage-test paragraph, boundary verdict paragraph (replaces the
chaos_boundary/chaos-remote lines), chaos[] fields paragraph. Abort rules: guard sentence + commit-stall
paragraph after the table.

## verify — in progress
bash -n OK; shellcheck -S warning clean (local 0.11 + docker koalaman v0.9.0); v0.9.0 all-severity: only
notes, +3 SC2016 (jq filters, existing pattern), SC2015 count unchanged. py_compile OK.
test_recovery 18/18, test_stall_scan 4/4, full suite 238/238, check_mutations.py all rejected.
--help lists chaos-stage-test; chaos-stage-test dry run (bash -n of the script + plan) rc 0; missing/unknown
--instance dies; dry collect under a throwaway run id prints the stall-scan step, creates nothing.
Scratch end-to-end do_run simulation (epoch mode, stubbed GCP, real staged script via local bash -s):
late 0.221/0.148/0.193 s, poll deferred twice, restart = kill begin + downtime, obs = restart begin + delay,
crossed_boundary true + notes, commit_stalls entry. Mixed+abort simulation: kill staged late 0.205 s,
abort at the next poll, owed restart ran 1 s later over the direct path (staged=false), no boundary
fields in mixed mode. NOT verified: the staged script over a real IAP session (orchestrator runs
chaos-stage-test --yes against a live node).

## follow-up (r20261006-0458 false positive) — DONE
status: complete
completed: [F-rounds, F-bookkeeping, F-stall-scan, F-tests, F-verify]
pending: []
Plan: commit stall needs blocks flat AND fleet-max rounds advance <= BENCH_STALL_NOTE_MAX_ROUNDS (default 4,
defined in benchmark-blast.sh: config.sh is not mine this round) over [since, last flat sample], read from
Prometheus with `offset` at those times (fleet_round_at). Blocks flat + rounds advancing = idle: one console
line, no record. Advance closes a stretch even after the window end (end = advancing sample, round_end =
round at end, no open); open only at the end-of-watch flush. node-sampler.sh has no round column ->
stall-scan stays blocks-only, source "sampler-blocks-only", README caveat.
Deviation: rounds judged over the stretch's LAST BENCH_STALL_NOTE_SECS, not the whole stretch. Saved
Prometheus series (results/r20261006-0053/metrics.json): blocks flat from ~02:10:00 but rounds +15 until
02:10:28, then +0 to 02:15:13. Whole-stretch delta (~15) > 4 would miss the real stall. 0458: rounds
+40/15 s throughout -> idle either way.
Done: fleet_round_at <unix> (Prometheus max(epoch*1e8+round) with `offset`), commit_flat_judge
(stall/idle/unknown; idle re-judged silently each poll), commit_flat_close (advance closes even after
cooldown; end = advancing sample, round_end = round at end, no open), commit_flat_flush (open only at the
end of the watch). STALL_WIN_END removed. BENCH_STALL_NOTE_MAX_ROUNDS default 4 + integer check in
benchmark-blast.sh (config.sh not mine this round). stall-scan: node-sampler.sh has no round column ->
blocks-only, source "sampler-blocks-only", docstring + README caveat. README commit-stall paragraph rewritten
(also corrects the old claim that rounds kept advancing in the 6 Oct stall).
Tests: CommitFlatTests now 8 (stall entry, idle no entry, close-after-cooldown bookkeeping, open at flush,
cooldown drain, unknown rounds retried, fleet_round_at offset query, status samples). 5/5 mutants rejected.
Verify: bash -n OK; docker shellcheck v0.9.0 -S warning rc 0; test_recovery 23/23; test_stall_scan 4/4;
full suite 243/243. Replay of real data: 0053 -> stall 02:10:18-02:15:23 (305 s, rounds 1783->1787);
0458 -> idle line, no entry.
