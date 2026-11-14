# Sources: bench6-epoch-record-closing-block-check.md (not for posting)

Private abbreviations: E3 = benchmark/private/bench6-r20261113-1351/E-3/findings.md; DRE = benchmark/private/bench7-prep/DR-E/findings.md; R6 = tasks/bench6-report-r20261113-1351.md; M = telcoin-network 45dce8947 (read with `git show 45dce8947:<path>` from /home/drtnarg/coding/telcoin/telcoin-network-b7, HEAD == M).

| claim / figure | source |
|---|---|
| holds by construction on main | E3 "The answer" (:9-10, read on 2df831e3c); DRE §2 (:56) re-checked on M; own read of M close_epoch.rs:409-411, :445-466 |
| #1834 added the stored-record guard | `git log -S "fn check_stored_final_state" 45dce8947` -> af0f1ccae (#1834); DRE :7 |
| guard on stored path and every entry, number+hash only, halts | M close_epoch.rs:430-433, :590-596, :712-749, :1265-1284 (:1274); run_epoch.rs:152-153, :238; DRE §1 (:26-35) |
| build path checks nothing; save :514, persist :518, publish :519; committees :476-490; build :505-512 | M close_epoch.rs:404-521 (own read) |
| vote signed on publish | M epoch_votes.rs:503-525 (own read) |
| markers: beacon root / nonce / seed / extra_data | M payload.rs:40 (nonce doc), :129-134, :140, :168-170; evm/block.rs:2114, :2118 (own read) |
| only re-derive reads beacon root + nonce epoch; extra_data nowhere | M close_epoch.rs:1294-1316 (own read); DRE §1 (:36-42) |
| final_state logged nowhere on success | DRE §3 (:72-74); M close_epoch.rs:735-745 is the only line naming it (own read of :404-750) |
| ring holds the whole sealed header; record path reads number+hash | M recent_blocks.rs:78, consensus_bus.rs:1354 (git grep); DRE :50 |
| guard unit tests use header without markers | M close_epoch.rs:2045 (header_of), :2111, :2278 (git show | grep -n); DRE §2 (:61-63), §7 (:109) |
| e2e helper checks only number+hash at final_state | M e2e-tests/tests/it/common.rs:1600-1639 (own read); E3 §5 (:125-129) |
| "every node would save the same wrong record ... stop only at the next entry" | inferred from M code (build path :411-519 vs entry check :590-596); marked inferred in the text |
| ten validators and one observer; arm walk nine configurations by rolling restart | R6 :96-98; E-4 findings :11 (11 nodes) |
| build bench/bench6-2026-11 at 2df831e3c; stored-record check was a switch (epoch_record_state_check) | E3 :3, §2 table (:54), §4 (:114-116) |
| six per-close checks (last block, ring entry, blockHeight-1, pin, same on every node) | E3 §3 (:62-69) |
| 37 closes; 25/271 run 1, 6/66 run 2, 6/66 run 2b; v05 replay after restart included | E3 "The answer" (:14), §3 table (:74-78) |
| one record hash per epoch in every vote, quorum line, fetched record | R6 §4.4 (:391); E3 :15 |
| no final-state halt, identity error, re-derive line | E3 §3 table column "halt, skip, identity-error, re-derive lines" = 0 (:76-78); R6 :392 |
| adaptive runs: one record hash and one closing block on all eleven nodes at every close | benchmark/private/bench6-r20261113-2118/A3a/vs-always-on.md:101; benchmark/private/bench6-r20261113-2118/A7/comparison.md:266 |
| final_state never observed; inferred from code + single hash (digest covers final_state) | E3 :16, :106-108, "What remains unknown" (:136) |
| fix shape (a)(b)(c), build/stored/entry/re-derive, no switch, adiri skip 160 | tasks/bench7/briefs/e1.md items 1-6; DRE "Changes to the design -> E1" (:119-127); M types/src/forks.rs:69-71 |
| base-fee identity in adjust_base_fees, logs only on failure | M run_epoch.rs:935-950 (own read); E3 :12; DRE :75 |
| e2e extension (extraData, beacon root, blockHeight) | E3 "Options" 4 (:147) |
| #1806 late members take the stored path | E-4 findings :12 (14 F0 cells), E3 :109 (14 late validator closes found the record stored); #1806 title via gh |

Left out (could not trace or not needed): the single run-1 close where nothing compared the stored record (E3 :110, switch off on bench 6 only; not relevant to main); one-batch closing output never exercised (E3 :36) — dropped for length.

## Revision after the figure-check (tasks/bench7/figcheck-UI1.md, text 1)

| changed sentence | source |
|---|---|
| line 8: guard runs "at every epoch entry that finds the previous record stored; a closing block at or below a snapshot-restored datadir's floor is not compared" (figure-check replacement) | M close_epoch.rs:569-571 (entry check only with the previous record stored and not the epoch-0 dummy; a missing record is re-derived, :628-672), :1271 (`Restored`), :723-730 (debug line); figcheck :27-28 |
| line 37: guard bullet names `check_stored_record` (:712-749) comparing in `check_stored_final_state` (:1265-1284); restored-floor skip (:1271); counter `tn_epoch.final_state_mismatches_total`, error line, stop (:733-746) (figure-check replacement) | M close_epoch.rs:712-749, :720, :733-746, :1265-1284, :1271; figcheck :27, :29 |
| line 38: "Among the record paths only `boundary_consensus_digest` ... reads any" (figure-check replacement) | other readers of the beacon root (node.rs:1869 ring restore, engine/inner.rs:65, :288) never compare with a record; figcheck :33 |
| evidence: "an arm walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by rolling restart; it has no public page)" | R6 :89 (fleet shape), :99 (each run its own deployment); figcheck :34; coordinator instruction 5 |

Cut for length after the replacements (no new claims): "Syncing nodes trust the record's committees, read at `final_state`."; the benchmark-run bullet under "How to verify"; the base-fee identity counter in the fix paragraph (`run_epoch.rs:935-950`).
