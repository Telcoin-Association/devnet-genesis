# Sources: bench6-00-switches-obs.md (not posted)

Head `feat/bench6-switches-obs` = 8a42fec57 (12 commits on 45dce8947), read with `git -C /home/drtnarg/coding/telcoin/telcoin-network show <sha>` and `git diff 45dce8947..8a42fec57`.

## Figures and claims

| text | source |
|---|---|
| four runs, ids, "tested fixes behind runtime switches" | launch prompt; tasks/bench7/briefs/u-common.md "Where the facts are" |
| `Parameters` does not deny unknown fields, main node.rs:220-221 | `git show 45dce8947:crates/config/src/node.rs` lines 220-221 (derive without deny_unknown_fields) |
| a new field would be written into ceremony files and the mainnet preset | commit 0777ed06e body |
| first bound 5 ms, recorder.rs:18-19, :170 | `git show 45dce8947:crates/tn-metrics/src/recorder.rs` lines 17-19 (SECONDS_BUCKETS starts 0.005), 170 (Suffix `_seconds`) |
| evm 26.5, root 49.2, finish 11.4 µs/tx at saturation, r20261107-1504 | public PR #1813 body lines 60-61 (`gh pr view 1813 --json body`); same text in tasks/pr-bodies/bench5-02-exec-split.md "Evidence" (median of ten validators) |
| re-queued digest's wait restarts, proposer.rs:842, :1384-1385 | `git show 45dce8947:crates/consensus/primary/src/proposer.rs` lines 842, 1384-1385 |
| review note on #1819 | commit 7471f329e body |
| behind_consensus, handler.rs:353-358, 40 rounds at gc_depth 50 | `git show 45dce8947:crates/consensus/primary/src/network/handler.rs` 353-358; "40 rounds at a gc_depth of 50" from the gauge doc at 8a42fec57 crates/consensus/primary/src/metrics.rs (epoch_entry_rounds_behind doc) |
| one validator entered an epoch about one round inside the window, r20261107-1504 | commit 3d100a147 body ("validator-01 entered epoch 8 at round 39 of it, one round inside the 40-round activity window"); tasks/bench5-analysis-brief.md:148 ("v01 entered at fleet round 39 — a margin of ONE round"); tasks/checkpoint-bench5-I-E.md:26, :28. Epoch number left out: :26 says e8, :28 says e7 |
| per-commit descriptions | each commit's diff and body |
| "only comments added" to Parameters; byte-identical written file; mixed fleet identical messages | tasks/bench7/review/00-switches-obs-report.md 2a, 2b, 2g.1; checked against `git diff 45dce8947..8a42fec57 -- crates/config/src/node.rs` (struct edits are the marker comments at 324-329 and 431-432) |
| `parking_lot` mutex, never across `.await` | 8a42fec57 metrics.rs `use parking_lot::Mutex`, `start_`/`record_epoch_entry_rounds_behind`; review 2c |
| stamp map filled only from own worker digests; dropped per epoch | review 2d, 2e; proposer.rs diff (`OurDigestMessage::process`, `drain_digests_for_header`) |
| five new `le` values | 8a42fec57 recorder.rs SUB_MS_SECONDS_BUCKETS vs main SECONDS_BUCKETS |
| `oldest_requeue_wait_ms` between `requeued` and `pending_before` | proposer.rs diff at the `header proposed` info! |
| tests named | `git diff 45dce8947..8a42fec57` new `fn` names; "mainnet and adiri presets round-trip" from review 2g.1 |
| head gates: check, fmt, clippy -D warnings; nextest 677 passed (2 skipped); cargo test x3, 25 identical fork-pin failures | tasks/checkpoint-bench7-PT-0.md "follow-up gates on 8a42fec57"; logs /home/drtnarg/coding/telcoin/tn-b7-pt0/target/tmp/g-check.log, g-fmt.log, g-clippy.log, g-nextest.log (`677 tests run: 677 passed, 2 skipped`, EXIT=0), g-cargotest-{1,2,3}.log (EXIT=101), g-fail-1.txt (25 lines) |
| d8273bbe3 nextest 1,207 passed (7 skipped) | tn-b7-pt0/target/tmp/nextest3.log (`1207 tests run: 1207 passed, 7 skipped`, EXIT=0) |
| Makefile `test-cargo` note | `git show 45dce8947:Makefile` lines 187-191 |
| re-applied by hand; bench 6 ran its own versions on an older base | commit bodies 3d100a147, adfd41f41, 7471f329e; u-common.md (bench 6 build 2df831e3c predates #1834) |
| limits | review F1-F4 and "Known residuals"; F1 fixed 8a42fec57, F2 doc 859b945d1, F4 doc 6007c08be, F3 stated in Limits |
| #1806, #1819 refs | commit footers (3d100a147, a91cfe02a, d8273bbe3, 859b945d1, 8a42fec57: Refs #1806; 7471f329e: Refs #1819); titles via `gh issue/pr view` |
| later topics' switches (vote_queue_fix; three for collector hardening; none for closing-block check) | tasks/bench7-contract.md section 1; tasks/bench7/briefs/u-p.md stack table |

## Not-carried section

All figures from tasks/bench6-not-carried-writeup.md: 1.156 to 1.193 device bytes per page byte (validators, full load, r20261113-1351 and r20261113-1630); 19,967 writes/s against 20,000 IOPS and 3.74 writes per executed transaction (r20261113-1351 load blast); "each configuration ran once". Main cites re-checked at 45dce8947: crates/tn-lmdb/src/env.rs:309-317 (MADV_RANDOM doc), crates/tn-reth/Cargo.toml:157-161 (`mdbx` feature, off by default), crates/node/src/manager/node/close_epoch.rs:712 (`check_stored_record`), crates/tn-reth/src/env/output_overlay/parallel.rs:63-82 (":74 a pipelined persist"). Placeholders: {{epoch-record-closing-block-check}}, {{execute-and-persist-in-series}}.

## Left out

- The writeup's observer figures (6.5 to 10.9 times; 1.06) and the arm walk r20261112-1520 figures (no run page), for length.
- The epoch number of bench 5's one-round entry (records disagree, see above).
