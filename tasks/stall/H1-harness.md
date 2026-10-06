status: complete
completed: [A, B, C, D, E, F]
pending: []

# H1 harness audit (r20261006-0053) — checkpoint

## A. Log preservation — DONE
Teardown order today (benchmark-teardown.sh): 59-60 SKIP_LOGS knob; 104-109 results dir must exist;
116-251 candidates+guards (buckets 187-192 via bench_bucket_names bench-lib.sh:1242-1245 =
label benchmark=1 OR name startswith tn-devnet-bench-); 293 health table; 295-378 load-VM gate;
380-434 LOG GATE (bench_pull_node_logs bench-lib.sh:740-781 -> logs/<inst>-telcoin.log.gz,
<inst>-telcoin-pre-*.log.gz, <inst>-unit-{stdout,stderr}.log.gz, <inst>.pulled markers);
436-451 recovery evidence (recovery-lib.sh:19-56 -> logs/<inst>-recovery-<id>.*.tgz);
DELETE 453+: 456-460 tunnels, 466-488 instances, 489-491 firewall, 493-504 disks,
505-520 bucket cp -r to results/<run>/bucket/<b>/ then rm -r, 521-533 IAM, 534-540 worktree,
541-548 genesis move; 555-578 provenance; 581-621 left-nothing (593 buckets).
Proposal: archive bucket ${PROJECT_ID}-tn-bench-archive (labels purpose=bench-archive,retain=true),
insert gated archive block between 451 and 453, rsync results (exclude genesis*/, tunnel.pid,
dot-files) + run bucket server-side, verify sizes, BENCH_TEARDOWN_SKIP_ARCHIVE override,
.archive manifest object, final non-gating sync after 578, collect opt-in BENCH_COLLECT_ARCHIVE.
Node side: nothing deletes telcoin logs; docker run --rm is the loss vector (mitigated).

## B. Chaos lateness — DONE
Cause = execution lag (not predictor/registry): 02:09:06 poll ran ~37 s past t_kill 02:09:38;
5 s sleep floor (blast:1000); pre-kill log save 4 s (02:09:48->02:09:52); IAP 3.3 s -> BEGIN
02:09:55.29. Restart re-based on kill end (blast:922) -> +17 inherited, +2 s python, +2.8 s IAP.
Observer t_obs = t_back+300 -> inherited 17 + 4 s save + 2.8 s IAP; manifest ts is END (record_chaos after ssh).
Fix: deadline-aware poll, 1 s floor, staged stdin script that saves log then waits on node clock, node-side begin/end in manifest.

## C. Manifest chaos note — DONE
blast:919-920 hard-codes "restart across the epoch boundary"; boundary queried once before restart
(blast:930-934) and never compared; this run's .chaos_boundary is genesis (epoch 3, height 0) because
recovery-schedule.py:46 accepts an unopened epoch. Fix: neutral note + .chaos[i].planned, crossed_boundary
computed after restart from node-side begin times, retried each poll.

## D. IAP 4033 retry — DONE
bench_iap_scp_down bench-lib.sh:270-275 single attempt; only caller do_collect blast:1040,1042.
Fix: bounded retry (3, 10/20 s) only when stderr matches [(4003|4033|4047): ; .part + mv; alarm + </dev/null.

## E. Stall note — DONE
round_stall_check blast:565-612; rounds advanced every poll this run (slowly); blocks flat 15513 at
02:13:06; poll deltas straddle the stall. Fix: commit_flat_check over BENCH_STATUS history (120 s) +
stall-scan.py over sampler CSV block column (30 s) at collect; BENCH_STALL_NOTE_SECS=60; never aborts.

## F. Other harness items — DONE
F1 recovery-schedule.py:46 height-0 epoch; F2 blast:931 single boundary query; F3 blast:926 ~317s;
F4 record_chaos ts = END; F5 blast:999 5 s floor; F6 blast:955 poll not deadline-aware;
F7 blast:1041/1043 warn-only (no manifest note).
