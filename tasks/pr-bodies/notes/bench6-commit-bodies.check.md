# Bench 6 stack: commit-message fact check (heads 00, 01, 02, 03, 05, 06)

Check unit FC-CB, 2026-11-15. Read-only over telcoin-network; upstream main = 45dce8947.
For each commit message: every benchmark fact, every statement about main or an upstream number, any description the
diff does not bear out where it jumps out, and every private label. Ranks: WRONG (contradicted by a source),
UNTRACEABLE (not found; where I looked is given), PRIVATE LABEL, WEAK (stronger than the source).
"Sources" below are the posted issue and PR texts of the program, the bench-5 and bench-6 reports, the code at
45dce8947 and `gh ... view` of the upstream numbers. Proposed corrections cite no private path.

## Head 00: feat/bench6-switches-obs (45dce8947..8a42fec57, 12 commits)

### F00-1 WRONG: adfd41f41 fix(metrics): give the execution stage histograms sub-millisecond buckets

Sentence: "The engine's per-output stage histograms (tn_engine_{recover,evm,root,finish}_seconds, #1813) and main's
per-block ones (tn_reth_block_{execute,signer_recovery,finish,hashed_state,state_root,overlay_extend}_seconds, #1834)
fell through to the default `_seconds` layout, whose first bound is 5 ms."

What is wrong: the per-block histograms came to main with #1759, not #1834. `git log -S block_overlay_extend_seconds
45dce8947 -- crates` first hits 6167184c0 "TN-owned storage engine for the reth execution database (behind the `tndb-b`
feature) (#1759)" (gh: merged into main 2026-11-11). All six names are already recorded in crates/tn-reth/src at
6167184c0 (execution.rs:199 `RETH_METRICS.block_signer_recovery_seconds.record(...)`, :237 `block_execute_seconds`,
:250 `block_finish_seconds`, :266 `block_overlay_extend_seconds`), in a module that is not feature-gated, and the
occurrence counts are the same before and after af0f1ccae (#1834). The rest holds: #1813 added
`recover_seconds`/`evm_seconds`/`root_seconds`/`finish_seconds` to crates/engine/src/metrics.rs (gh pr diff 1813), and
main's `SECONDS_BUCKETS` starts at 0.005 (crates/tn-metrics/src/recorder.rs:18-19).

Corrected: "The engine's per-output stage histograms (tn_engine_{recover,evm,root,finish}_seconds, #1813) and main's
per-block ones (tn_reth_block_{execute,signer_recovery,finish,hashed_state,state_root,overlay_extend}_seconds, #1759)
fell through to the default `_seconds` layout, whose first bound is 5 ms."

### F00-2 UNTRACEABLE: adfd41f41 (same commit)

Sentence: "Bench 5 (r20261107-1504) measured these stages at tens of microseconds per transaction and single
milliseconds per output, so at light load every lap sat in the first bucket and histogram_quantile over them was flat."

What is wrong: the per-transaction half holds (bench-5 PR text for the execute split, posted: "At saturation execute =
87.4 µs/tx = recover_wait 0.0 + evm 26.5 + root 49.2 + finish 11.4 + other 0.2"; bench-5 report: "At light load all
ten validators and the observer cost the same (`finish` 4.4-4.9 µs/tx ...)"). "Single milliseconds per output" and
"every lap sat in the first bucket ... was flat" are in no posted bench-5 text nor in the bench-5 report (searched
issue-bodies/bench5-*.md, pr-bodies/bench5-*.md and the report for "per output", "first bucket", "single milli", "5 ms",
"light load" with "execut/evm/root"). The report's per-output figure is under load: "Per output (A6, pre-kill p50): task
1,658 ms = execute 479 + persist 1,167". At light load its output was "a 479-tx output (light8)", and at the saturation
costs above that is about 13 ms of evm and 24 ms of root per output (arithmetic, assuming the light-load per-tx cost of
those two laps equals the saturated one, which no source gives), above the 5 ms bound, not under it.

Corrected: "Bench 5 (r20261107-1504) measured these stages at a few to tens of microseconds per transaction (evm 26.5,
root 49.2 and finish 11.4 µs/tx at saturation), so a lap over one block, or over a light-load output, can fall under
the 5 ms first bound, where histogram_quantile only interpolates inside one bucket."

### F00-3 WEAK: a91cfe02a fix(primary): keep the epoch-entry gauge across a mode change

Sentence: "A node that entered an epoch past the activity window recorded window+1, demoted, and its re-entry wiped the
value before a 15 s scrape could see it: the case the gauge was added for (bench 5, r20261107-1504)."

What is wrong: the parenthesis attaches bench 5 to a node that entered past the window and demoted. In bench 5 no node
did; posted #1806: "The entry was one round short of an `epoch_behind` demotion. validator-01 started epoch 8 at
17:56:33.613. The fleet's newest header was round 39". The 15 s scrape holds (etc/prometheus/prometheus.yaml:10
`scrape_interval: 15s` at main).

Corrected: "A node that entered an epoch past the activity window recorded window+1, demoted, and its re-entry wiped
the value before a 15 s scrape could see it: the case the gauge was added to catch, which bench 5 (r20261107-1504)
missed by one round."

### Checked and holding (head 00)

- 3d100a147, the known example: "In bench 5 (r20261107-1504) validator-01 entered epoch 8 at round 39 of it, one round
  inside the 40-round activity window that demotes a node which has not executed the new epoch yet". The posted bench-5
  text (#1806, local body and the issue as posted) says epoch 8: "And validator-01 entered epoch 8 when the network was
  at round 39 of it: one round more and the `epoch_behind` rule would have demoted it" and "validator-01 started epoch 8
  at 17:56:33.613. The fleet's newest header was round 39". The "epoch 7" reading of the private records is the same
  event named by the closing epoch (#1806's table row "epoch 7 (17:55:43) ... validator-01 in 17:56:33.613"). Keep
  epoch 8. Main's rule matches the 40-round window: for a certificate of the next epoch `round > gc_depth.max(6)` with
  `gc_depth = gc_activity_window(...)` = gc_depth − 10 (handler.rs:340, :354-360; types primary/mod.rs:64-77), so 39 is
  one round inside the window's edge, as #1806 says ("39 vs 40").
- a233d64dc: the four run ids are the four public bench-6 runs, all on one image (report §8: "Everything else is the
  same between a run and its twin: image 2df831e3c"); Parameters at main has no `deny_unknown_fields`
  (crates/config/src/node.rs:220-221), so an unknown key is ignored. Note, not a finding: in the four headline runs the
  arm was written at deploy before the coordinated start (report §2: "applied at deploy step 7 before the first start:
  no arm walk ... no restart before load"; §7 note 8: each node ran once at staging with defaults first), so "rewriting
  the file and restarting" holds only in that sense; the rolling rewrite-and-restart was the arm walk.
- 0777ed06e: genesis writes `Parameters::default()` plus CLI overrides (telcoin-network-cli genesis/mod.rs:315);
  the ignored regeneration test exists (`regenerate_mainnet_chain_configs`, :684); the bench-6 build has the private
  helper (2df831e3c crates/config/src/node.rs:803 `fn is_default`).
- 7471f329e: the review note on #1819 exists (inline comment on proposer.rs: "A re-queued digest restarts its wait here
  ... That is the far-validator population #1803 looks at, so its digest wait is under-reported by one proposal cycle
  each time it loses a header"); main has no parent-grace or digest-dedupe code (no `parent_grace`/`dedupe` in
  crates/consensus/primary/src at 45dce8947).
- a91cfe02a: main has the neighbouring static (`static MAX_CONSENSUS_OUTPUT_BYTES: AtomicU64`, primary metrics.rs:24).
- 859b945d1: at that commit behind_consensus reads `is_active_cvv` (:301), the last block (:308), records the round
  (:364) and only then sends `CvvInactive` (:451).
- 8a42fec57: main's Makefile `test-cargo` is `cargo test --workspace --no-fail-fast` (Makefile:193-194).
- No private label in any of the twelve messages (no finding ids, unit names, tasks/ paths, hosts or tool mentions).

Counts, head 00: commits read 12; sentences checked 23; wrong 1; untraceable 1; private labels 0; weak 1.

## Head 01: test/bench6-e2e-scaffold (8a42fec57..bf9853709, 8 commits)

No finding.

Checked and holding:
- 422d3fbbd "Bench 6 puts each bench 5 fix (run r20261107-1504) behind a top-level parameters.yaml switch": bench-6
  report §1 "Bench 6 put every fix for bench 5's concerns behind one of twelve switches".
- 90d38b400 "Every bench 6 switch defaults off": report §2 "Every fix is a node switch, off by default".
- 4ab437182 "eject.rs restarts nodes[1..2]": main crates/e2e-tests/tests/it/eject.rs:997
  `start_nodes(temp_path, &nodes[1..2], "eject_restart", 2)?;`.
- bf9853709: upgrade.rs, reth_db_migration.rs and resync.rs are the e2e files on main that read `TN_BIN_PATH_PREV`;
  main's durable-e2e.yaml:96 says the migration lane's previous binary "is the `mdbx` build".
- 41b07e55a "Review of the port onto main found ..." is plain prose, no label.
- No private label in the eight messages.

Counts, head 01: commits read 8; sentences checked 7; wrong 0; untraceable 0; private labels 0; weak 0.

## Head 02: fix/1804-vote-queue (bf9853709..6e771ac39, 10 commits)

### F02-1 WEAK: 07189a807 test(primary): pin that one author's vote requests wait in turn on its lock

Sentence: "The vote handler's rework since (#1822, #1839, #1842, #1844, #1846) keeps the lock across the whole
evaluation."

What is wrong: four of the five numbers rework the voter (gh: #1822 "record every author that cites a missing parent",
#1839 "recast a stored vote under the author lock and keep it cached", #1842 "follow-ups to #1822: pending attached
parents, duplicate parent verification, cancelled vote requests", #1844 "keep this node's cast vote cached across other
decisions about its author"; all on main). #1846 "verify fetched certificates before handing them on, and keep
checked copies" changes the proposer's parent attachment, the fetch responder and the certificate manager; in
handler.rs it rewords one comment and passes `collector.into_verified_stream()` in the certificate-stream responder,
nothing in the vote evaluation (git show b0188d69f -- crates/consensus/primary/src/network/handler.rs). The lock claim
itself holds at main (handler.rs:1029-1032 takes `auth_lock.lock().await` and the evaluation with its `vote_timeout`
runs under it, :1049, :1159).

Corrected: "The vote handler's rework since (#1822, #1839, #1842, #1844) keeps the lock across the whole evaluation."

### Checked and holding (head 02)

- 64c3bb06e "a vote request on validator-02 waited 291 ms for the per-author lock and then 1,001 ms for execution
  while holding it (round 1073)": posted #1804 "`validator-02:17:45:01.357`: `vote path timing … round=1073 epoch=7
  outcome=behind lock_ms=291 exec_wait_ms=1001 total_ms=1293`".
- 07189a807 and 68ea027b4 "each queued request waited its own second (lock_ms in seconds)" / "waited up to a second per
  request while holding the per-author vote lock": #1804 "Every refusal was `outcome=behind` with `exec_wait_ms` 1000 or
  1001" and "(this run: about 8 s on the slowest voter for seven of the nine other authors)"; bench-6 comment on #1804
  "bench 5's validator-01 waited 7.3-8.5 s for the lock on validator-04's requests at 17:45". "Bench 6 fixed it behind
  vote_queue_fix": the switch is in the bench-6 arm (report §8.2 arm list); the comment's caveat (both fixes on, so
  the runs show the level, not the switch alone) is about attribution, which the sentence does not claim.
- "main still queues them that way" (64c3bb06e, 68ea027b4): main's `VOTE_EXECUTION_WAIT` is 1 s
  (crates/config/src/consensus.rs:459) and the wait runs under the author lock.
- 048997705: main's put-back comment, added by #1842 (b1baed048), reads "the network layer drops this future when
  the requester cancels the request" (handler.rs:1149-1150 at main).
- 4c7958adf, 6e771ac39: `LIBP2P_REQUEST_TIMEOUT` = 10 s (consensus.rs:449); default and mainnet preset `vote_timeout`
  5 s; main's CLI README:637 and :705 give only the 10 s bound.
- 44321d55d: before it the `vote path timing` line is `debug!` (handler.rs:983 at 44321d55d^).
- "The bench-6 review ...", "The domain review of the voter-lock port found ...", "The review of the voter-lock port
  recorded this" (44321d55d, bed302576, f87a80752) are plain prose; no finding id or unit name follows them.
- No private label in the ten messages.

Counts, head 02: commits read 10; sentences checked 17; wrong 0; untraceable 0; private labels 0; weak 1.

## Head 03: fix/epoch-record-closing-block-check (6e771ac39..1e38f1882, 3 commits)

No finding.

Checked and holding:
- 0238163c2 "bench 6 measured it at all 37 closes of runs r20261112-1520, r20261113-1351 and r20261113-1630": posted
  #1851 "That held at all 37 closes on every node that closed them: 25 closes and 271 node-closes in r20261112-1520, 6
  and 66 in each of the others". "nothing checked the block's own markers": #1851 "compares number and hash only".
- 0fafd5968: main's `adjust_base_fees` (crates/node/src/manager/node/run_epoch.rs:880) errors on
  `tip.number + 1 != block_height` and its passing branch logs nothing; a chain-global read failure returns before the
  compare. "could only infer it from a missing halt line": #1851 "no node logged a final-state halt, an identity error
  or a re-derive line".
- 1e38f1882 cites #1851, the closing-block-check issue (gh-posted row `epoch-record-closing-block-check 1851`).
- No private label in the three messages.

Note, not counted: 0238163c2 names r20261112-1520, which has no public page. #1851 names it with that caveat ("an arm
walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by rolling restart; it has no public
page)"). If the body should be traceable on its own: "... at all 37 closes of runs r20261113-1351, r20261113-1630 and
the arm walk r20261112-1520 (no public page; #1851 gives the counts), ...".

Counts, head 03: commits read 3; sentences checked 6; wrong 0; untraceable 0; private labels 0; weak 0.

## Head 05: fix/1804-quorum-exec-block (be483a955..d155f04df, 18 commits)

### F05-1 WRONG: 0c2f9e9eb feat(primary): resolve recent blocks by number and by entries back from the tip

Sentence: "In bench 5 (run r20261107-1504) the three fastest executors certified 0.2 %, 0.0 % and 16.3 % of their
headers: each header named the proposer's own execution tip, and a quorum of voters refused it as execution behind."

What is wrong: the third figure. Posted #1804, which the commit refs: "In the 2026-11-07 run Tokyo, Hong Kong and
Mumbai certified 0.2 %, 0.0 % and 16.2 % of their own headers" and "validator-10 (Mumbai) 149 of 918"; 149 / 918 =
16.23 %. The 16.3 % comes from the bench-5 report's "149 of 918 (16.3 %)", a mis-rounding that two posted bench-5 PR
texts also carry; the head's own first commit (81b92ad47) says 16.2 %.

Corrected: "In bench 5 (run r20261107-1504) the three fastest executors certified 0.2 %, 0.0 % and 16.2 % of their
headers: each header named the proposer's own execution tip, and a quorum of voters refused it as execution behind."

### F05-2 WRONG: 5217e3e7a feat(primary): name an execution block a quorum holds behind quorum_exec_block

Sentence: "Bench 5 (run r20261107-1504) starved the three fastest executors of votes (0.2 %, 0.0 % and 16.3 % of
headers certified): each header named the proposer's own tip, which voters had not executed."

What is wrong: as F05-1; #1804 gives 16.2 % (149 of 918).

Corrected: "Bench 5 (run r20261107-1504) starved the three fastest executors of votes (0.2 %, 0.0 % and 16.2 % of
headers certified): each header named the proposer's own tip, which voters had not executed."

### F05-3 WRONG: 8b5611c9e test(e2e): fast executor certification and a mixed-switch fleet

Sentence: "The benchmark flips switches by rolling restart (bench 6: r20261113-1351, r20261113-1630, r20261113-2118,
r20261114-0000), so the second test runs two validators with every runtime switch on and two late ones with none,
restarts a switched node, and requires one chain: ..."

What is wrong: none of the four public runs flipped switches by rolling restart. Bench-6 report §2: "Runs 2 and 2b
used the launcher's segments ... with `benchmark/arms/final.arm` applied at deploy step 7 before the first start: no
arm walk, no eviction, no restart before load", and §8 for runs 3 and 3b: "Everything else is the same between a run
and its twin". The rolling restart was the arm walk (report §2 table: run 1 r20261112-1520 "nine arms by rolling
restart"; posted #1851: "an arm walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by
rolling restart; it has no public page)").

Corrected: "The benchmark flips switches by rolling restart (bench 6's arm walk, r20261112-1520, ran nine
configurations that way; its four public runs started with their switches set), so the second test runs two
validators with every runtime switch on and two late ones with none, restarts a switched node, and requires one chain:
..."

### F05-4 WEAK: 8b5611c9e (same commit)

Sentence: "With every switch off the fast one certifies 0.60 of its own headers; quorum_exec_block with starved_rounds
4 and vote_queue_fix certifies 0.93, and starved_rounds 0 certifies 1.00 (tn-lmdb, the bench-6 delay and load)."

What is wrong: an e2e figure, not a benchmark one, but the commit and the test it adds disagree. exec_block.rs at
8b5611c9e documents the control as "measured 0.61 to 0.74" (`MAX_CONTROL_SHARE`), the adaptive arm as "measured 0.922,
0.931 and 0.923 in three runs" and the always arm as "measured 0.98 to 1.0". The 0.60 is one run (0.604) outside the
doc's own range.

Corrected: "With every switch off the fast one certifies about 0.6 to 0.74 of its own headers; quorum_exec_block with
starved_rounds 4 and vote_queue_fix certifies about 0.93, and starved_rounds 0 about 1.0 (tn-lmdb, the bench-6 delay
and load)." (Or widen the test doc to "0.60 to 0.74".)

### Checked and holding (head 05)

- 81b92ad47 "Tokyo, Hong Kong and Mumbai certified 0.2 %, 0.0 % and 16.2 % of their own headers" and "the other seven
  validators had not executed yet, and those seven refused them": #1804, verbatim figures and "naming blocks the other
  seven had not executed yet, and those seven refused them"; validator-04 Tokyo, -08 Hong Kong, -10 Mumbai (#1804).
  "Bench 6 ran both forms (runs ...), so both stay": report §8 "The always-on form ... is run 2 `r20261113-1351` ... and
  run 2b `r20261113-1630` ... The adaptive form ... is run 3 `r20261113-2118` ... and run 3b `r20261114-0000`".
- 5217e3e7a "With starved_rounds 0 the rule covers every header and the fleet settles on the floor": report §8 "The
  always-on form (every header names its author's executed tip minus 8 outputs, the floor)".
- db8e5aa60 "certified 0.81 of its headers against the 0.98 target": exec_block.rs doc "0.81 to 0.82 when one certified
  tip header reset the window" and "the bench-6 target of 0.98"; #1804 "Own-header certification of at least 98 %".
- 57fa4bdbe and 5f91fcf35: `HeaderError::BelowRestoreFloor` and `UnknownExecutionResult` exist at main
  (crates/consensus/primary/src/error/network.rs:263, :286). "Bench 6 pinned two of these answers on the old handler":
  the bench-6 build 2df831e3c has `quorum_exec_block_voter_votes_old_executed_block_at_once` and
  `quorum_exec_block_voter_refuses_old_number_with_another_hash` (network_tests.rs:5583, :5629).
- d155f04df: #1850 and #1851 are the collector-gaps and closing-block-check issues (gh-posted rows).
- "The bench-6 review ...", "The domain review of this topic found ...", "Found by the domain review of this change."
  (57fa4bdbe, f5578d57c, 4c955921a, 748236a05, ece7d6041) are plain prose.
- No private label in the eighteen messages.

Note, not counted: 81b92ad47 and 5217e3e7a describe the adaptive window in rounds ("for K rounds after an own header
was cancelled"); 9bad2765c later counts it in headers and 7b31fc4b2 updates the docs. Each message is true of its own
commit; a squash or PR text should use the header count.

Counts, head 05: commits read 18; sentences checked 21; wrong 3; untraceable 0; private labels 0; weak 1.

## Head 06: fix/1807-digest-order-hold (d155f04df..b93a8e682, 17 commits)

Sources for this head: the bench-6 comment posted on #1807 ("Bench 6 data for this issue: the loss showed in all four
of bench 6's load runs ..."; its table and its "Still open" list) and the bench-6 report §8.4.3.

### F06-1 WRONG: 947a34863 feat(node): count what the orphan re-pool does with each transaction

Sentence: "Bench 6 counted 185 such batches across runs r20261113-1351, r20261113-1630, r20261113-2118 and
r20261114-0000 and could not say what happened to their transactions."

What is wrong: two things. The 185 are from two runs, not four: #1807 comment, "173 re-queued batches in
r20261113-1630 and 12 in r20261114-0000 never executed; why is unknown" (the run comparison has 0 and 0 for
r20261113-1351 and r20261113-2118: "Re-queued batches never executed | 0 | 0 | 173 | 12"). And "such batches" (the
previous sentence: batches of headers that never commit, coming back through the orphan re-pool) says more than the
source, which says only that they never executed and that why is unknown.

Corrected: "Bench 6 found 185 re-queued batches that never executed, 173 in r20261113-1630 and 12 in r20261114-0000,
and could not say whether the re-pool took them or what happened to their transactions."

### F06-2 WRONG: baa05065e feat(tn-reth): re-export the pool's error kind

Sentence: "Bench 6 could not say what happened to the transactions of 185 batches that never executed (runs
r20261113-1351, r20261113-1630, r20261113-2118, r20261114-0000)."

What is wrong: the run list, as F06-1: #1807 comment "173 re-queued batches in r20261113-1630 and 12 in r20261114-0000
never executed".

Corrected: "Bench 6 could not say what happened to the transactions of 185 batches that never executed (173 in
r20261113-1630, 12 in r20261114-0000)."

### F06-3 WEAK: a09d3bbdb test(primary): hold a validator's own certificate on demand

Sentence: "Far validators hit it in the bench 6 runs (r20261113-1351, r20261113-1630, r20261113-2118,
r20261114-0000); a four-validator local e2e test almost never does."

What is wrong: no bench-6 source ties the re-queue to the far validators. #1807 comment: "the loss showed in all four
of bench 6's load runs" and "Of the seconds in which a generator other than the killed validator's resent, 715 of 717
over the four runs fell 280-345 s after a lost own header of that generator's validator". The bench-6 report §8.4.3
names near validators for one run ("at 20,000 IOPS the first resend wave opened from the near validators' cancelled
own-tip headers") and, at 50,000 IOPS, validators whose execution led. London and the Netherlands (validators 02 and
06) are among the losers in some runs, not the whole set.

Corrected: "Validators that lost an own header hit it in all four bench 6 runs (r20261113-1351, r20261113-1630,
r20261113-2118, r20261114-0000); a four-validator local e2e test almost never does."

### F06-4 WEAK: 750249465 feat(primary): count batch digests re-queued out of order

Sentence: "... the re-queue put the older batch behind the newer one, and its transactions failed on their nonces."

What is wrong: "its" reads as the older batch, whose transactions execute normally; the ones that fail are the newer
batch's, the sender's later nonces. #1807 comment: "payload order is execution order, so the sender's later nonces
execute first, are skipped as `nonce too high`, and return to no pool."

Corrected: "... the re-queue put the older batch behind the newer one, whose transactions, the sender's later nonces,
were then skipped as nonce too high."

### F06-5 WEAK: 836a3ea20 feat(primary): log what the proposer leaves when it stops

Sentence: "Bench 6 (r20261113-1351 to r20261114-0000) found 185 batches that never executed near boundaries and could
only infer where they went."

What is wrong: the span takes in two runs with none (as F06-1), and the source says "why is unknown", not that the
destination was inferred. "Near boundaries" is not in the posted comment; the run record has it ("from headers lost in
an epoch's last 13-30 s"), so it holds, but no public text gives it. Main's proposer shutdown arm does return silently
(proposer.rs:1212-1213 `_ = &self.rx_shutdown => { return Ok(()) }`).

Corrected: "Bench 6 found 185 re-queued batches that never executed near epoch boundaries (173 in r20261113-1630, 12 in
r20261114-0000) and could not say where they went."

### F06-6 WEAK: 56e5d2b51 feat(config): add the digest_order_hold switch

Sentence: "Bench 6 counted lanes overtaken through re-queued own headers in runs r20261113-1351, r20261113-1630,
r20261113-2118 and r20261114-0000."

What is wrong: no posted text gives such a count, and the run analysis counted headers, not lanes: report §8.4.3
"lost fewer headers with overtaken own transactions (858 against 2,202)", run-3 record "176 of the 509 lost headers
before the kill had overtakers". Nothing counted worker lanes.

Corrected: "Bench 6 counted lost own headers whose re-queued batches were overtaken by a newer own header's in runs
r20261113-1351, r20261113-1630, r20261113-2118 and r20261114-0000."

### F06-7 WEAK: b93a8e682 test(e2e): the own-chain hold keeps every accepted transaction while a validator's chain breaks

Sentence: "Bench 6 lost transactions on far validators (runs r20261113-1351, r20261113-1630, r20261113-2118,
r20261114-0000): a cancelled or uncommitted own header had its batch digests re-queued behind newer digests of the same
worker, so a sender's later transaction executed first as "nonce too high"."

What is wrong: "on far validators", as F06-3. The loss itself holds (#1807 comment table: unlanded after the tail scan
183 / 10,767 / 14,928 / 20,768; landed over accepted 99.9987 % to 99.8591 %). "executed first as" compresses the
comment's "execute first, are skipped as `nonce too high`".

Corrected: "Bench 6 lost transactions in all four load runs (r20261113-1351, r20261113-1630, r20261113-2118,
r20261114-0000): a cancelled or uncommitted own header had its batch digests re-queued behind newer digests of the same
worker, so a sender's later transaction reached execution first and was skipped as "nonce too high"."

### Checked and holding (head 06)

- 860cd5a08 "the load generators paid 29,546 / 133,975 / 104,280 / 255,453 gap resends" in the order 1351, 1630,
  2118, 0000: #1807 comment table "gap resends | 29,546 | 104,280 | 133,975 | 255,453" in the order 1351, 2118, 1630,
  0000; each pair matches. "traced to the batch reordering of issue #1807": the comment's 715 of 717 seconds within
  280-345 s of a lost own header, with "(measured; the mechanism is read from code)".
- 52c11f4b9, ea7d9c040, 12b6fb432 (re-queued digests ran after newer digests of the same lane, later nonces failed):
  #1807 comment "Mechanism on main" and report §8.4.3 "The mechanism is the same in all four runs".
- c59ad945f: main's `report_canceled` returns silently on shutdown and logs only a failed `try_send`
  (certifier.rs:781-800).
- 947a34863: main's epoch teardown re-pools own batches that never reached consensus (close_epoch.rs:8-10).
- d738147d0 "Bench 6 ... could not measure that": no `own_parent` field existed; the #1807 comment says of the hold
  "It is untested; we will measure it in the next run before a PR."
- No private label in the seventeen messages.

Counts, head 06: commits read 17; sentences checked 22; wrong 2; untraceable 0; private labels 0; weak 5.

## Totals

| head | commits read | sentences checked | wrong | untraceable | private labels | weak |
|---|---:|---:|---:|---:|---:|---:|
| 00 | 12 | 23 | 1 | 1 | 0 | 1 |
| 01 | 8 | 7 | 0 | 0 | 0 | 0 |
| 02 | 10 | 17 | 0 | 0 | 0 | 1 |
| 03 | 3 | 6 | 0 | 0 | 0 | 0 |
| 05 | 18 | 21 | 3 | 0 | 0 | 1 |
| 06 | 17 | 22 | 2 | 0 | 0 | 5 |
| all | 68 | 96 | 6 | 1 | 0 | 8 |

Private-label scan: every message of the six heads was also grepped for finding-id and unit-name shapes
(`[A-Z]{1,3}[0-9]+`, `[A-Z]{2,4}-...`), tasks/ and private paths, host names, the cloud project, tool and assistant
words; nothing matched except Rust's "private is_default helper" (00, 0777ed06e) and "unit test" (01, 41b953c56).
