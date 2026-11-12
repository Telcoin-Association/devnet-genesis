# Bench 6 — G1 decision brief

From `tasks/bench6-g1-notes.md` (D1-D84, read in full), `tasks/plan.md`, `tasks/bench6-upstream-followups.md`, `bench6-run1.plan`,
`benchmark/arms/README.md` and the orchestrator checkpoint (to 2026-11-12T00:28Z); numbers are copied from them. **FLAG** = two
sources disagree, or are silent on something a decision needs. Items owed only to the upstream PRs appear in §5 only.

## 1. State in ten lines

1. **Integrated:** head 80a0c76c0 = base 165e3fe01 + 79 commits. Eleven switches act; `pipelined_persist` is plumbed but inert
   (its stack is held). Every default is bench 5's behaviour.
2. **Verified there:** fmt, check, clippy, nextest green (4,351 passed, 30 skipped). Every commit is reviewed (ten topic reviews +
   the sealed-keep delta review); no Critical or High anywhere.
3. **e2e:** repo sets on d91d65d3e: all off 11/11, 11/11, 12/12; eleven on 11/11, 11/11, 12/12; on 80a0c76c0 sealed_txs + admission 7/7.
4. **Held:** pipelined persist, stack `b6/pipe-stack-2` = d91d65d3e + 19 (tip d30bb1809), not yet rebased onto 80a0c76c0.
5. **Its go/no-go gates:** 1, 2 (differential, faults) PASS · 3 (close barrier) PASS · 4 (e2e) PASS · 7 (review) PASS · 5 (cycle
   ≤ 1.1 × max(execute, persist), quiet host) not measured · 6 (repo e2e sets on the stack): on 11/11, 11/11, 12/12; off waiting.
6. **Harness:** complete except its README (H6b, W9) and the full gate alone on the host (≈ 30-35 min). H12's rehearsal walked
   run 1's real data path. `BENCH_TXGEN_SHA` for the image = 62bbd5f.
7. **Probe:** the one-VM GCE probe on the fleet's shape is done (r20261111-2310, 20/20 arms, DOWN_OK). Findings: §2B.
8. **Running:** the two-device probe r20261112-0024 (Hyperdisk vs local NVMe, c3-standard-8-lssd, us-west1-a, 12 records, ends by
   02:24Z). The eleven-switch sets on 80a0c76c0 and the stack's switch-off sets wait behind other sessions' attest jobs.
9. **Owed before the image:** gates 5 and 6; the stack's rebase (if IN); the base re-check; the image built as `etc/Dockerfile`
   does, pushed, digest recorded; D84's arm-summary column (status not in the notes). Owed, no stated timing: U4b's full
   contention run on a quiet host (I-3 §3b waits on it). Not recorded: the exec_block + epoch_drain result on 80a0c76c0.
10. **Bench 5:** the corrected report (I-6 + I-6b) is ready and uncommitted until your review (§2D). Benches 3-5 are archived
    and verified in GCS; nothing local is deleted.

## 2. Decisions for G1 (27 items: finding · options · recommendation as recorded · default if unanswered)

### A. What the fleet runs

The walk as it stands (`bench6-run1.plan`, fixed by hand at G2): a0-control I L M4 M16 → p1-mdbx-advice M16 → v-vote L M16 →
pool-local M16@epoch → pipe M4 M16 → bound M4 M16 → gr150 I L M16s → a0-prime M16 (14 blasts).

- **A1. Commit-cost drift between arms** (D3, D24). Bench 5's per-output commit drifts ≈ +0.031 s per minute of load in both
  windows (0.37 → 0.52 s in 600 × 4; 0.88 → 1.27 s in 600 × 16, fit r² 0.963): arms compare only at equal database age. The arm
  summary corrects the drift only for blast types both control arms ran (M16); L and M4 rows are raw.
  - Options: D3: A-B-A with equal M16 windows, every arm corrected by the fitted drift / alternate short blocks / evict and
    restore between arms. D24: add an L and an M4 to A0′ (+ ≈ 23 min) or accept raw rows. Rec.: none recorded. Default: the walk.
- **A2. The control arm keeps bench 5's double start** (D16). Bench nodes ran their load in a re-opened DB whose advice covered
  only the genesis pages (stage-only start, then start-all); the probe found a re-open alone does not amplify (g5-7default 1.00×).
  - Options: keep the stage-only start in A0 / drop it. Rec.: orchestrator: yes for A0 ("the fix arms then show whether
    whole-map advice alone repairs a re-opened DB"). Default: not stated.
- **A3. Run 1 as three launches** (D39, D40). The sequencer does not watch: a fatal DB failure inside a long step, a commit stall
  while idle, the BOUND entry rule (abort when a validator enters ≥ 30 rounds behind), memory late in the run, and the plan's
  "read the vote arm before PIPE or BOUND". Resuming an evict arm restarts every node again (≈ 10 min).
  - Options: one walk / three launches. Rec.: orchestrator: three, arms 0-2 (control, P1, V), a read of the vote arm, arms 3-7.
    Default: not stated (on its own the tool walks straight through).
- **A4. Pool gate before saturated blasts** (D12, D41). Stale queued entries (21,332 fleet-wide in bench 5; queued peaked at
  9,341 on v04 against reth's 10k default) plus 9,600 in flight per node leave almost no headroom (bench 5: 3,804 queued-pool
  evictions). As built: each blast records `pool_at_start`; the sequencer waits up to 10 min, then stops, if queued ≥ 1,000
  before a saturated blast; pools unreadable at the deadline let the walk go on with a note.
  - Options: D12: record only / refuse or wait above a threshold / rolling restart between an arm's blasts (≈ 10 min) / raise
    the queued limit (changes the system under test). D41: make the unreadable case strict? Rec.: D12: record always, and
    require queued < 1,000 per node at an M16 start; D41: none recorded. Default: as built.
  - FLAG (wording): H1b calls its record-only driver "as proposed in D12"; the < 1,000 rule is in the sequencer (H11).
- **A5. Tail-scan length** (D21). Plan 180 s; I-2's spec 120 s for load blasts; env files 180. Tail landings count only in new
  fields (D20), so the KPIs keep bench 5's definition. Options: 180 / 120. Rec.: none recorded. Default: 180 s.
- **A6. Which form of the vote fix** (D1; D29, D61 closed by U1b). Local e2e, fast node's own headers certified: off 0.53 / 0.69
  / 0.71; always (K = 0) 1.00 / 0.99 / 0.99; adaptive (K = 4) under U1b's rule (64 consecutive certified tip headers) 0.922 /
  0.931 / 0.923 in 90-s windows, ramp-limited (was 0.81-0.82). Model: adaptive ≈ 0.985 steady state, a 5-10-header ramp at each
  regime start, restart and epoch, own tip ≈ 98 % of the time when not starved; always names a block ≈ 8 outputs stale at every
  load (≈ 14 s at bench-5 saturation), so "lag 0 at idle" fails by construction.
  - Options: adaptive (`v-vote`) / always (`v-vote-floor`, file exists) / both (one more arm); I-4 also lists a smaller N; the
    tip in the header (wire + fork-gated) is not for bench 6.
  - Rec.: U1b: adaptive for the vote-fix arm; always only if steps are short or a number must hold in the first minute.
    Orchestrator: run 1 keeps the adaptive arm; adding `v-vote-floor` for a measured comparison on the real fleet is proposed at
    G2. Which form the V arm and the headline use is your call, here and at G3. Default: run 1 runs `v-vote` (K = 4) only.
- **A7. `epoch_record_state_check` with the vote fix on** (D2, D79). With the fix on, the voter and subscriber checks read the
  older named block, so neither stays immediate; a member that reaches the close late skips its final_state comparison today;
  U5's check closes that window. It halts a node on a divergence from any cause; four halted members of ten stall the fleet
  until they restart.
  - Options: the plan's default (off in the image) / on wherever `quorum_exec_block` is on. Rec.: I-4: on in every such arm.
    Run rule (D79): a halt line on any node stops the arm and is the finding. Default: not in the notes (arm-file contents not
    listed; U5: "for the bench the check is on only as a tripwire").
- **A8. Leader rounds lost under the vote fix** (D30). A failed return to the tip can land on the node's own leader round and
  lose that slot; staying in the window while leading would avoid it (reviewer's idea, not built). Options: build / measure.
  Rec.: orchestrator: measure in run 1 (leader rounds lost per validator in the V arm), build only if it shows. Default: not built.
- **A9. Parent-grace value** (D63; D38 superseded by U9b's bounds). Not free under load: the grace arms on almost every round and
  costs up to G per round, never above `max_header_delay` (1 s on the fleet); the issue's "about 0 under load" is wrong; an
  author always past G also costs G every round. GR150 is judged on the far validators' committed share against that cost.
  - Options: GR150 as planned (I, L, M16s) / add GR100 (file exists, not in the walk) / both. Rec.: as recorded, "whether 150 ms
    per round is worth it at ten regions is the question run 1 answers; G = 100 ms is the fallback arm"; nothing recorded on
    adding GR100 to run 1. Default: gr150 only.
- **A10. The admission-bound arm** (D47; D9 settled by U12b). Under saturation the gate is closed most of the time; the generator
  resends a refused transaction for ≈ 30 s and drops it on the 22nd refusal (nonce not advanced). The verdict reads landed tx/s
  AND refused/dropped counts AND the confirmation latency of what was admitted. Bound: 2 sequential, 3 with pipelining (A13).
  - Options: the saturating rate (M16, as planned) / a rate just above the execution ceiling. Rec.: none recorded ("a question
    for the gate"). Default: `bound M4 M16`.
- **A11. Disk classes at fleet level** (D82). Your steer: NVMe is bound by bytes, a network disk (4,500-20,000 writes/s on ours,
  ≈ 1 ms per sync) by the number of writes. On the probe's Hyperdisk (20,000 IOPS / 800 MiB/s) the amplified commit hit the
  THROUGHPUT cap (1,469 ops × 256 KiB = 367 MiB per commit, 59 ms per op); the fix raised the op count (3,091 → 5,627) yet cut
  the commit 243 → 35 ms, so the orchestrator's "may lengthen it" was wrong in direction for this disk. Healthy commits are
  op-bound (5,600-14,800 writes at ≈ 1.3 ms). The two-device probe's results are not in the notes yet.
  - Options: (a) nothing beyond the probe; (b) a short second run-1 deployment on local-SSD shapes for the control and advice
    arms (one more deploy, ≈ 2-3 h of fleet time; C3 has local SSD only on `-lssd` standard shapes, a machine-type confound
    against `c3-highcpu-8`; c3-standard-8-lssd is not in us-west2); (c) run 2's headline on both disk classes (two headline
    deployments). Rec.: none recorded. Default: (a).
- **A12. Provisioned IOPS as the persist ceiling** (D84). If a real output dirties about as many pages as the node-like arm
  (≈ 15,000 write ops; g1-node 14,832), back-to-back persists at 20,000 IOPS cannot beat about one per 0.75 s, amplified or not;
  bench 5's persist took 1.17 s per output. The probe sustained ≈ 9,800-12,000 of 20,000 IOPS; at 4,500 IOPS the same commits
  would be IOPS-bound outright. No node switch changes this.
  - Options: read write ops per persist and sustained IOPS against the cap per arm and node (required either way) / also raise
    `BENCH_NODE_DISK_IOPS` for one arm. Rec.: recorded only that this "is the direct test"; no arm, no cost. Default: no IOPS arm.
- **A13. Pipelined persist in or out** (D7; D46 superseded; D9, D69, D78). The ×1.41 gain is a ceiling (≈ ×1.2 if persist slows
  20 % while a build overlaps). Gates: §1 line 5. Without the stack, an arm file that sets the key runs sequentially, silently.
  - IN: integrate the stack rebased on the head; `bound`, `gr150`, `gr100` go to bound 3 (+ `switches.tsv`, README table,
    print-state golden). OUT: revert 8ab9e89e4, d789015b0, 8d363e368 on the image branch (the arm tool then refuses files that
    set the key); drop the key from `pipe`, `bound`, `gr150`, `gr100` (bound stays 2); drop `pipe` from the walk; fix
    recovery-pool's two stale doc comments on its own branch.
  - Rec.: orchestrator (D7): the cutoff is the moment the integrated branch enters its W3 gates; "if any of the five gates is not
    green then, the image ships without the key". I-5: go; enable the arm only if gates 1-5 are green by the cutoff.
    Default: D7's rule (OUT unless the gates are green at the cutoff).
  - FLAG: D7 and I-5 count five gates (design.md §6.5), later sections seven; gate 6 is "the domain review" in U12b but "the
    switch-off suites and e2e sets on the stack" in ST-U12b and the pipelined-persist review. Which gates D7 binds is not stated.

### B. The persist root cause

Settled by the probe (r20261111-2310, one `c3-highcpu-8`, medians per output):
- The GCE kernel and Hyperdisk do not amplify by themselves (node-like arms 1.00-1.01×): I-1r's leading hypothesis (35 %) is refuted.
- Bench 5's signature is a read-through: it wrote 222-228 KB (decimal; 217-223 KiB) per op from minute 1, as only the read-through arms do (255.6 KiB
  per op, 11.85-11.88×, commit 411-412 ms). Prefault-off writes 77 KiB ops (9.70×, 243 ms), a foreign opener 8 KiB (1.80×).
  WHAT read `mdbx.dat` (or refaulted it with read-around) on bench 5's nodes is not identified.
- The fix (whole-map `MADV_RANDOM`) works only before large folios exist: 9.70× and 1.80× → 1.00×; healthy 36 → 36 ms; a
  polluted cache stays 11.88× with or without it, and `read_ahead_kb` 16 does not help. So the advice arm also evicts, and the
  control pair a0-control / a0-prime ("defaults, with and without eviction") matters: "eviction alone may be the cure on a fleet node".
- Without WRITEMAP nothing amplifies (1.00× even after a read-through): ≈ 23 % more commit time when healthy (129 vs 105 ms), 3×
  faster when polluted (134 vs 411 ms). Not switchable in bench 6 (D83, an upstream design option).

What run 1 must show:
- D28 stands: the first persist arm may not show the planned recovery; "commit 178 → 25-38 µs/tx" is a hope, not an expectation.
- Large folios at minute 1 or not: the control arm's folio census at each blast start and the node's page-operation fields
  (prefault on ⇔ Σ`page_prefault` ÷ growth of `mdbx_last_pgno` ≥ 0.9, D73; amplification = device bytes ÷ ((`page_newly` +
  `page_cow`) × 4096)).
- P1's verdict is commit time and throughput, not the ratio (D82); beside it write ops and IOPS (D84), refault and major-fault
  deltas (D65), the advice as the node measured it (D66), and whether P1 flattens the +0.031 s/min drift (D3). The
  multi-page GC/freelist idea is mostly ruled out (GC records are one page each under BIGFOOT).
- Rule: nothing but the node opens a live node's database (a stock `mdbx_stat` turns a node into the 8.7× case).

- **B1. A prefault-off switch (a 13th)** (D17). Cheap: one `mdbx_env_set_option` call, requiring `mdbx_random_advice` (prefault
  off without it is the 8.7× case). With the advice, prefault off measured 1.000 locally and 1.00× / 35 ms on GCE. Recorded:
  decide after I-1r and the VM run; the build is the orchestrator's, the arm use yours. Nothing recorded after the probe.
  Default: not built.
- **B2. "No node start in the stage-only step"** (D32, with D16). It has no local evidence behind it unless g5-7default amplifies
  on GCE; it did not (1.00×). Recorded: hold it until the VM run; nothing recorded after it. Default: held (not made).
- **B3. Persist arms P2 / P3.** Listed in `plan.md`'s G1 line; the notes name neither (the walk has P1 only; the arms README's
  example arm "p2" = advice + read-ahead 16 + evict). Not in the notes.
- FLAG: D18 (I-1) says P1's eviction step "is not expected to matter"; the probe section says eviction "may be the cure", and
  does not say it supersedes D18.
- D68 (a Prometheus scrape can run reth's `stat()` on the persist's live write transaction) is "to be checked against the
  persist root-cause list"; no result is recorded.

### C. The image and the boot image pin

- **C1. Boot image pin** (D23). `BENCH_NODE_BOOT_IMAGE` = `ubuntu-2404-noble-amd64-v20261105`, bench 5's by the earlier gcloud
  read (v20261105, kernel 7.0.0-1017-gcp); run artifacts do not record the source image; deploy step 0 will `images describe`
  it. Confirm the pin, and accept a deprecated image if Google has deprecated it? Rec.: none recorded. Default: the pin.
  - FLAG: this image has no `fincore` (the first probe run failed on it). The notes say the fleet's samplers fall back to the
    census tool; the arms README says `host evict-mdbx` fails on a node unless fincore then reports 0 resident pages, and D18
    keeps that check. Whether the evict step (P1 and the evicting control arm) has a fallback is not in the notes.
- **C2. #1808 in the image?** (D10). The #1790 restart-replay fix, approved, unattested upstream; it affects adiri builds only,
  and the bench image is a `faucet` build. Rec.: none recorded. Default: not stated.
- Image-cut checklist (the orchestrator's; no decision unless you object): A13's IN/OUT steps; the vote arm per A6; `BENCH_TXGEN_SHA`
  62bbd5f (replaces 2b51b2c, 82b3e82); build as `etc/Dockerfile` (`-p telcoin-network`, no extra features), `TN_TEST_PERSIST_DELAY_MS`
  and `TN_TEST_EXECUTION_DELAY_MS` unset (D77); cut from a head whose commit list matches what was reviewed (re-review anything
  later); workspace gates and e2e sets on it; push, record the digest, `--probe-node-image` by digest; pin the generator image.

### D. Bench 5's corrected report; pruning

- **D1. Approve and republish the corrected bench-5 report.** I-6 corrected 12 defects (a 16-entry list); I-6b 28 statements
  from I-1 to I-4 (22 entries under "## Corrections (2026-11-11)"), the backfill summary and caveats 2, 5, 7; re-bundle 719 s;
  site gates green (115 tests, scrub 0/0). The report, backfill and tn-benchmarks run files stay uncommitted until your review.
  Options: approve, then commit and republish / ask for changes / hold. Rec.: none recorded. Default: nothing committed or
  republished.
  - FLAG: I-6b lists I-1 to I-4 as its sources. Not among them: I-1's ranked trigger #1 is "NOT sufficient as stated" (I-1r);
    bench 5's signature is a read-through (the probe); bench 5 peaked at 9,741 pending against reth's 10,000 cap, so some of its losses may be pool
    evictions (H15; bench 5 did not collect the eviction counter). Whether the report reflects these is not in the notes.
- **D2. Prune the local results of benches 3-5.** r20261103-1922, r20261107-1504 and r20261105-0803 are in
  `gs://tn-devnet-benchmark-archive/runs/<run>/results/`, every file matching by size and MD5 (231 / 781 / 227 files; bench 4
  = 91.4 GB); `genesis/`, `tunnel.pid` and dot-files were excluded (24-25 per run); report `tasks/bench6/w0-archive-verify.md`.
  Options: prune / keep. Rec.: none recorded. Default: nothing deleted. (The plan also lists 81 GB of old target dirs,
  "nothing deleted without the user's word"; not marked as a G1 item.)

### E. Other items the notes put to the gate

| item | D | question | recorded recommendation | default |
|---|---|---|---|---|
| rehearsal in the gate | D57 | keep the ≈ 4-min run-1 rehearsal in the harness gate, or run it on request? | keep it: "the only test of the whole data path" | not stated |
| archive vs teardown | D26 | teardown uploads and verifies before deleting, so 11 VMs stay up (bench 5's 2.5 GB ≈ 5-14 min; far more with debug logs) | skip that gate (`BENCH_TEARDOWN_SKIP_ARCHIVE=1`), run `tools/archive-run.sh --run <R>` right after (verify included) | archive before delete |
| durability-barrier issue | D5 | file it upstream after the run? (v09 lost 3 leader rounds; `persist_ms` 1,639 / 5,294 / 2,074 ms) | none; a zgrep is to size it (status not in the notes) | not filed |
| bench-4 execute split | D6 | split bench 4's execute offline from ≈ 49 GB of logs per node? | orchestrator: no, low value | not done |
| read cache across outputs | D11 | left as a follow-up (a pipelined N+1 starts with trie runs only): OK? | none beyond leaving it | follow-up |
| judging sealed-keep | D13 | judge on stalled-for-300-s senders and the exact ≥ 256 s landing count, not land p99 | as stated (I-2) | not stated |
| gate observers too | D50 | observers' own submissions pass the bound; one line changes that | none; the load goes only to validators | not gated |

## 3. Decided by the orchestrator, reversible

- D1 (action): the twelfth switch `quorum_exec_block_starved_rounds` was added so both vote-fix forms are built. D4: no separate
  pool for the state root (single-threaded); a pool for `finish` is what U4b measures (full run owed).
- D15, D19, D25: I-2's extra generator measurements (H9b), the sampler additions, one persist-CSV column after the freeze. D20:
  tail landings count only under `run.tail_scan` (generator 2b51b2c); undo = redefine the KPIs, on your word.
- D27: no cancel object for a late blaster create (a slow create costs one unsent attempt, a possible re-fund); undo = build it.
  D34: the `vote_timeout + 1 s < 10 s` check is not in the image; it goes to the W8 PR unless you want it now.
- D36: no Criterion; the contention bench is a plain timed binary; undo = add Criterion (a new dependency tree in `Cargo.lock`).
  D37: no per-late-certificate author line for run 1; U9b's debug fields `waiting_for` / `still_missing` name awaited authors.
- D52: under pipelining "executed" = durable AND announced; a built, not yet durable output counts as behind.
- D62: a node that leads the round it proposes in never arms a grace (fixes M2); undo re-opens M2 (a stranded leader header, a
  leader never committed).
- D72: a node never waits for its own certificate; cost: its previous header no longer gets up to G more to certify; undo =
  restore the wait, which on a far node mostly expires and makes its next certificate later for everyone.
- D66: arms are labelled by what the node measured (c88936999), the recovery-pool arm likewise by `pool=dedicated`. D73:
  prefault counts as on at a ratio ≥ 0.9; the advice state is reported as columns, not as pass/fail.
- D74, D80: with `sealed_tx_keep` on, the pending sub-pool holds twice the limits (20,000 tx / 40 MiB; 80a0c76c0), shared, not
  reserved; undo brings back the confound (≈ 9,600 in flight = 96 % of the 10,000 cap; silent drops on the switch-on arm only).
- D78 (with D69): the OUT rule of A13; the summary's `pipelined` column is the second line of defence. D79: a final-state halt
  line on any node stops the arm. D81: a counter with no series reads n/a, not 0 (0 would hide an image that does not export it).

## 4. Information, no decision

- #1807 reproduced locally with no client resend (ST-B): switch off, whole windows of 2-3 senders lost in 2 of 4 runs; on, no
  loss in 4 of 4 (3,300-3,550 tx each, each in exactly one block); not shown: the live repair of an out-of-order execution. The
  deterministic control lost 0, 16 of 3,655 and 32 of 2,812 in three runs, each loss with #1807's signature.
- Vote starvation reproduced (ST-A: each slow voter refused 25-42 headers), but not bench 5's near-zero share (a test limit).
  Mixed-switch fleets are one chain: ST-A 3 of 3, ST-B 4 of 4, ST-U12b 3 of 3 (pipelined and sequential nodes together).
- The admission bound refuses and readmits 4 of 4; forwards survive closed gates 3 of 3; the load goes straight to validators.
  Pipelined core: 400-case differential and fault hunts, no finding; three hand mutations caught; SIGKILL mid-pipeline 3 of 3.
  The drain: no regression, but the tracking overflow is not provoked on four nodes; run 1 is its first real test.
- Reviews: ten topics + the sealed-keep delta, no Critical or High; parent-grace was CHANGES REQUIRED, fixed by U9b (M1, M2,
  L1, L2, L4). The grace arms' author fields already reach the pulled logs with today's filter (H15).
- Bench 5 (I-2, I-3): no window was generator-bound; both windows were engine-bound (3,868.5 and 3,466.2 tx/s); ≥ 95 % of the
  34,378 unlanded were lost, not late; the ≥ 256 s cliff existed in benches 3 and 4 too (2.20 %, 0.87 %).
- Residuals accepted for the benchmark: D42 (the halt does not survive a restart), D43, D45 (5-min read-transaction timeout;
  persist ≈ 1.2 s), D48, D51 (sealed-keep), D64 (after a restart a resend is accepted as new and lands once), D75 (not exposed).
- Reading rules: D55 (pipelined `task_ms` runs build → commit), D56 (`proc_write_bytes` an upper bound), D65 (on kernel ≥ 6.3
  the advice also changes reclaim: read refaults beside the amplification), D67 (the control is not "kernel default"), D71 (latency cancels raise `exec_policy=starved`: staleness, not loss), D77 (count `pinning the
  output overlay failed`; skip the restart's mixed window); with sealed-keep on, "pending" includes in-flight sealed tx;
  `gen_pool_full` is read against the control; watch `recover_ms` after boundaries in POOL+LOCAL.
- D76: the adaptive policy starts over at every epoch boundary ("≈ 0.1-0.25 % at one-hour epochs"). FLAG: `bench6-run1.plan`
  gives the epoch as 1,200 s; the notes give no figure for that length.
- D14: the epoch-boundary loss (I-2's "65") has no fix; the POOL arm puts a boundary inside its M16; S6 and S7 e2e are not
  written; a fix is decided after run 1. D53: with pipelining, RPC `latest` can show up to two non-durable outputs (sequential: one).

## 5. Every D-number

Sections are named by their headings in the notes. "§2 A6" etc. point into this page.

| D | title | class | notes section |
|---|---|---|---|
| D1 | Which vote-fix form ships | user (§2 A6) | From I-4; ST-A; U1b |
| D2 | State check with vote fix | user (A7) | From I-4 |
| D3 | Arm design against drift | user (A1) | From I-3 |
| D4 | Separate pool for root/finish | orchestrator (§3) | From I-3; U4a and U0c |
| D5 | File durability-barrier issue | user (E) | From I-3 |
| D6 | Split bench-4 execute offline | user (E) | From I-3 |
| D7 | Pipelined go/no-go cutoff | user (A13) | From I-5 |
| D8 | RPC latest non-durable outputs | superseded by D53 | From I-5 |
| D9 | Admission bound with pipelining | superseded by U12b (3) | From I-5; U11; U12b |
| D10 | #1808 into the image | user (C2) | From I-5 |
| D11 | Read cache across outputs | user (E) | From I-5 |
| D12 | Pool hygiene between blasts | user (A4) | From I-2; U2 and H1b; H11 |
| D13 | Sealed-keep judging criterion | user (E) | From I-2 |
| D14 | Epoch-boundary loss path | info (fix after run 1) | From I-2 |
| D15 | Extra generator measurements | orchestrator (done) | From I-2 |
| D16 | Control arm double start | user (A2) | From I-1 |
| D17 | Prefault-off switch | user (B1) | From I-1; the local probe; U3 |
| D18 | P1 keeps eviction step | orchestrator (FLAG, B) | From I-1 |
| D19 | Sampler additions (H4) | orchestrator (built) | From I-1 |
| D20 | Tail-scan KPI comparability | orchestrator (resolved) | From the harness units |
| D21 | Tail-scan length | user (A5) | From the harness units |
| D22 | Unlanded export lookups | info | From the harness units |
| D23 | Boot image pin | user (C1) | From the harness units |
| D24 | L and M4 in A0′ | user (A1) | From the harness units |
| D25 | Persist CSV extra column | orchestrator (done) | From the harness units |
| D26 | Archive before fleet deletion | user (E) | From the harness units |
| D27 | Late blaster create unsent | orchestrator (not built) | From the harness units |
| D28 | P1 may not recover | info (stands) | From the local probe; I-1r |
| D29 | When K resets | superseded by D61 / U1b | From U1 |
| D30 | Leader rounds under fix | user (A8) | From U1 |
| D31 | Approve the GCE probe | info (covered; ran) | From I-1r |
| D32 | Hold stage-only start change | user (B2) | From I-1r |
| D33 | Report pgno-0 prefault quirk | deferred upstream (after G4) | From I-1r |
| D34 | Vote request vs libp2p timeout | orchestrator (not built; W8) | From U2 and H1b |
| D35 | Pre-lock wait spam cost | deferred upstream (#1804 PR) | From U2 and H1b |
| D36 | No Criterion dependency | orchestrator | From U4a and U0c |
| D37 | Late certificate author unrecorded | orchestrator | From U9 |
| D38 | Grace cost bound | superseded by parent-grace review / U9b | From U9 |
| D39 | What the sequencer misses | user (A3) | From H11 |
| D40 | Resume re-applies the arm | info | From H11 |
| D41 | Strict gate, unreadable pools | user (A4) | From H11 |
| D42 | Halt lost after restart | deferred upstream (#1806 PR) | From U5 |
| D43 | wait_for_exit grace overflow | info (not fixed) | From U5 |
| D44 | State-check doc fix | orchestrator (done) | From U5 |
| D45 | 5-minute read-transaction timeout | deferred upstream (PR text) | From U12a; U12b; pipelined-persist review |
| D46 | Go/no-go status | superseded by pipelined-persist review | From U12a |
| D47 | Bound arm under saturation | user (A10) | From U11 |
| D48 | Gates close together; observers | info (not changed) | From U11 |
| D49 | Bound limit above 73 | orchestrator (doc done) | From U11 |
| D50 | Gate observers too | user (E) | From U11 |
| D51 | Sealed-keep residuals | info (accepted) | From U6b |
| D52 | "Executed" under pipelining | orchestrator | From U12b |
| D53 | RPC latest, two outputs | deferred upstream (PR text) | From U12b |
| D54 | Barrier's stated reason | info (docs fixed) | From U12b |
| D55 | Pipelined series and task_ms | info (analysis) | From U12b |
| D56 | proc_write_bytes upper bound | info (analysis) | From U12b |
| D57 | Rehearsal module in gate | user (E) | From H12 |
| D58 | TERM orphaned the blast | orchestrator (closed by H14a) | From H13; H14a |
| D59 | Commit-notice window | deferred upstream | digest-dedupe review |
| D60 | No worker-proposer test | deferred upstream | digest-dedupe review |
| D61 | Adaptive misses 98 % | superseded by U1b (closed) | From ST-A |
| D62 | No grace when leading | orchestrator (§3) | parent-grace review; U9b |
| D63 | Grace not free under load | user (A9) | parent-grace review |
| D64 | Marks lost at restart | info (accepted; PR text) | From ST-B |
| D65 | Advice also changes reclaim | info (analysis) | mdbx-advice review |
| D66 | Label arm by measurement | orchestrator (done) | mdbx-advice review |
| D67 | Control is not kernel default | info (docs fixed) | mdbx-advice review |
| D68 | Scrape stat() on write txn | deferred upstream (own issue) | mdbx-advice review |
| D69 | Pipelined key without stack | orchestrator (checklist) | inflight-bound review |
| D70 | Minority holds long windows | deferred upstream (PR text) | From U1b |
| D71 | Latency cancels restart streak | info (analysis) | From U1b |
| D72 | Never wait for own certificate | orchestrator (§3) | From U9b |
| D73 | Prefault-on threshold 0.9 | orchestrator (unit's choice) | From H14b |
| D74 | Pool global-cap confound | orchestrator (fixed in U6c) | sealed-keep review; U6c; H15 and H16 |
| D75 | Byzantine low parent, restore | deferred upstream | vote-starvation review |
| D76 | Adaptive restarts each epoch | info (analysis; FLAG §4) | vote-starvation review |
| D77 | Image-cut checks, pipelined stack | orchestrator (checklist) | pipelined-persist review |
| D78 | Image-cut rule for the key | orchestrator (§3) | plumbing review |
| D79 | Halt line stops the arm | orchestrator (run rule) | tracker-drain review |
| D80 | Doubled cap is shared | info | From U6c |
| D81 | Missing counter reads n/a | orchestrator (kept) | From H15 and H16 |
| D82 | Disk-class comparison | user (A11) | The GCE probe's first live run; the probe on the fleet's shape §5 |
| D83 | No-WRITEMAP option | deferred upstream (design option, not switchable) | The GCE probe on the fleet's shape |
| D84 | IOPS as persist ceiling | user (A12) | The GCE probe on the fleet's shape |

No number beyond D84 and none missing. Unnumbered items the notes defer to G4: whether the `pipelined_persist` kill switch stays
upstream for one release (I-5), and whether a canary up to N outputs stale is acceptable (I-4, design question E3).

## 6. Orchestrator's addendum (2026-11-12, after reading this brief against the notes): the flags resolved, the silent items given a recommendation

1. **Pipelined persist's gates** are the design's seven: 1 unit tests, 2 differential and fault properties, 3 the close
   barrier, 4 e2e (the unit's three tests and the repo's sets with the switch ON), 5 the cycle bench, 6 the switch-OFF suites
   unchanged on the stack, 7 reviews with no open High. Status: 1, 2, 3, 4, 7 PASS (the repo's sets with the switch on:
   11/11, 11/11, 12/12); 5 not measured (needs a quiet host); 6 partly (the engine suite and the workspace tests pass on the
   stack; the repo's sets with the switch off are queued behind other sessions' e2e jobs).
2. **D18 is superseded by the probe.** Eviction is not "harmless and not expected to matter": a cache that already holds
   large folios is repaired only by evicting it (the advice alone leaves 11.88×). The pair a0-control / a0-prime (defaults,
   without and with eviction) is the first comparison to read; P1 is read against a0-prime.
3. **`host evict-mdbx` works on the pinned image.** It counts resident pages with `fincore` when present and otherwise with
   mincore over an untouched map (`bench-lib.sh`, the host program); only the arms README's wording says "fincore". To fix
   in the README at wrap-up.
4. **D76 at run 1's epochs.** Run 1 uses 1,200-s epochs, not one hour: the adaptive policy's climb (5-10 headers) then
   recurs every 20 minutes, about 0.2-0.4 % of a starved node's own headers.
5. **The bench-5 page needs one more correction before it is republished.** Its text says the likely trigger (about 60 %)
   is the re-open of a database created during staging. Both probes contradict that: a re-open alone writes 1.000× locally
   and 1.00× on a GCE VM of the fleet's shape. The sentence becomes: the trigger is not identified; the write pattern
   (222-228 KB per operation, decimal) is that of pages that sat in large page-cache blocks before they were changed; a re-open
   alone does not produce it. The page's statement that the disks wrote 470-530 MB/s with peaks at the 800 MiB/s limit
   agrees with the probe (amplified commits are throughput-bound). The orchestrator makes the edit and shows the diff;
   nothing is pushed before your word.
6. **B1 — the prefault-off switch (D17): recommendation, do not build.** On GCE prefault ON is the healthy state (1.00×);
   prefault off is the 9.70× case and the advice closes it. A switch would add an arm that tells nothing new.
7. **B2 — "no node start in the stage-only step" (D32): recommendation, do not make.** The re-open is not the trigger.
8. **B3 — the optional persist arms.** P2 (`read_ahead_kb` 16, +32 min): recommendation, drop — the probe shows it does not
   help (11.88× with it). P3 (no-WRITEMAP, +32 min): recommendation, not in run 1 — no switch is built (it needs a
   vendored change), and the probe already measured it (1.00× always, +23 % commit time when healthy). It stays an upstream
   design option (D83). If you want it on the fleet, it is about a day of work before the image.
9. **D84's column** (write operations per persist, sustained write IOPS and MiB/s against the provisioned caps, per arm and
   node) is not in the arm summary yet; a small harness unit adds it before run 1.
10. **D68** (a metrics scrape can run a libmdbx stat on the live write transaction) reads meta pages, not the file: it is
    not a read-through path and not a candidate for the large folios. It stays an upstream issue of its own.
11. **On 80a0c76c0** the vote-fix and drain e2e modules passed 3 of 3 (902 s) and the sealed-keep and admission modules 7 of
    7; the all-switches-on repo sets on that head are queued behind other sessions' e2e jobs.
12. **What read `mdbx.dat` on bench 5's nodes** stays open. Two signatures bracket bench 5 (225 KB, decimal, = 220 KiB per operation at 4.3×):
    read-through (256 KiB, 11.9×) and prefault-off (77 KiB, 9.7×). Run 1's control arm decides between them from the
    node's own fields: prefault on or off per persist, and the folio census at each blast's start.
13. **The two-device probe is in (r20261112-0024): on GCE the local NVMe SSD is slower than the fleet's Hyperdisk for an
    MDBX commit in every arm** — 1.5 to 2.4 times the commit time for the same bytes and the same number of writes (the
    node-like arm 95 ms on Hyperdisk, 167 ms on NVMe; the amplified arm 241 ms and 580 ms). In a commit burst the Hyperdisk
    served 137,000-153,000 writes per second, the local SSD 83,000-95,000 (about one GCE local SSD's write limit) and it
    needs real flushes. One VM, one run per record; a bare-metal NVMe is a different device.
14. **D84 is answered from bench 4's and bench 5's own snapshots:** healthy (bench 4) the validators wrote 8,200-9,000
    operations per second, about 45 % of the provisioned IOPS and a quarter of the throughput — the IOPS provisioning was
    not the ceiling (it would be near 10,000 tx/s); amplified (bench 5) they wrote 500-536 MiB/s sustained with peaks at
    the 800 MiB/s cap — bound by throughput.
15. **D82, recommendation:** no fleet-level local-SSD deployment in bench 6; keep the write-count columns; if the ceiling
    nears 10,000 tx/s raise the provisioned IOPS before changing the disk class.
