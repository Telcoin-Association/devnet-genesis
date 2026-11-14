# FC-UI1: figure-check of three new epoch-record issues and the #1807 comment

Checked 2026-11-14 against the report, E-3, E-4, DR-E, DR-1807, the #1807 findings note, A7 comparison §3, A3a closes and vs-always-on, the hold design, and the code: main at 45dce8947 (read with `git show 45dce8947:<path>`) and the bench-6 build at 2df831e3c.
Read-only; nothing was edited but this file and the checkpoint.

## Overall

Verdict: FIX (three small errors, one per text 1, 2 and 4; text 3 passes; no BLOCK).
Counts over the four texts: 159 checked / 155 matched / 3 wrong / 0 untraceable (plus weak items below).
Every figure (37 closes, 25/271 and 6/66, 403 of 407, 373 + 28 + 2, 5.47 s and 3.86 s, 11 = 7 + 3 + 1, 0.1-4.5 s, 64.5-65.0 s, 0.07-0.29 s, 4 = 3 + 1, the twelve table cells, 715 of 717, 183, 173 and 12) matches its source and what it counts.
Every `path:line` on main opens on what the text says it shows.
No unit names, private paths, host names, run nicknames or attribution in any text.

## Text 1: issue-bodies/bench6-epoch-record-closing-block-check.md

Verdict: FIX.
Counts: 46 checked / 45 matched / 1 wrong / 0 untraceable.
Title: 109 characters, true of main (the build path saves and publishes the record, which a member votes, with no check: close_epoch.rs:411-519, epoch_votes.rs:503-525).
First paragraph says "a missing assertion, not an observed fault": yes (line 6).
"all 37 closes": 25 + 6 + 6 closes = 37, and 271 + 66 + 66 node-closes, on every node that closed them (E-3 :14, table :76-78); the text states both counts correctly.
Each "missing" item is missing on main: build path has no check before `save_record` (:411-519); no path compares beacon root, nonce epoch or `extra_data` with a record (only `boundary_consensus_digest` :1294-1316 reads two of them, to re-derive); `final_state` is logged only in the mismatch error (:735-745); no test asserts it (guard tests use `header_of` :2045 with no markers; `assert_epoch_records_verify` common.rs:1600-1639 checks number and hash only).

### Errors

1. Where: "What happens", line 8 ("Since #1834, main stops the node when a stored record's `final_state` differs from its closing block, on the stored close path and at every epoch entry.") and "Where in the code", line 37 (the guard bullet).
   What the text says: the guard runs at every epoch entry and stops the node on any difference.
   What main does: the entry check runs only when the previous record is stored and is not the epoch-0 dummy (close_epoch.rs:569-571; a missing record is re-derived through the unchecked build path, :628-672); a closing block at or below a snapshot-restored datadir's floor is not compared (:1271, `Restored`, debug line :723-730); on a mismatch it also counts `tn_epoch.final_state_mismatches_total` and logs an error before stopping (:733-746); the method called at :432 and :590 is `check_stored_record` (:712-749), which calls `check_stored_final_state` (:720).
   Replacement for line 8: "Since #1834, main stops the node when a stored record's `final_state` differs from its closing block, on the stored close path and at every epoch entry that finds the previous record stored; a closing block at or below a snapshot-restored datadir's floor is not compared."
   Replacement for line 37: "- The guard, `check_stored_record` (`close_epoch.rs:712-749`, comparing in `check_stored_final_state`, `:1265-1284`), compares number and hash only (`:1274`), skips a closing block at or below the datadir's restored-state floor (`:1271`), and on a mismatch counts `tn_epoch.final_state_mismatches_total`, logs an error and stops the node (`:733-746`). It runs on the stored close path (`:430-433`) and at entry (`:590-596`, from `run_epoch.rs:238`, against the `blockHeight - 1` header read at `run_epoch.rs:152`)."

### Weak

- Line 38, "Only `boundary_consensus_digest` (`close_epoch.rs:1294-1316`) reads any, on the re-derive path": other code reads `parent_beacon_block_root` (ring restore `crates/node/src/manager/node.rs:1869`, `crates/node/src/engine/inner.rs:65`, `:288`), never against a record. Replacement: "Among the record paths only `boundary_consensus_digest` (`close_epoch.rs:1294-1316`) reads any, on the re-derive path." (Line 12's "Only the restart re-derive path reads the first two" is read in the same record context and can stay.)
- Line 21, "an arm walk on the same fleet": each run was its own deployment (report :99); the source supports the same fleet shape at 20,000 IOPS (report :89). Replacement: "an arm walk on the same fleet shape at 20,000 IOPS". The same phrase is in text 2 line 25 and text 3 line 11.

### Rule breaches

- None. Length 915 words by `wc -w` with title and headings, 870 without headings: inside 400-900.

### Placeholder

- Line 60: "- {{epoch-record-collector-gaps}}: a record the network leaves uncertified, or certifies differently from a node's own."

## Text 2: issue-bodies/bench6-epoch-record-collector-gaps.md

Verdict: FIX.
Counts: 47 checked / 46 matched / 1 wrong / 0 untraceable.
Checked and right: the stop on main (state-sync/src/epoch.rs:241-346: a held-certified epoch is skipped :243-262, the next is requested :264, a failed request breaks at :343-345; the loop :391-419 resumes from that epoch every 5 s, `EPOCH_COLLECT_RETRY_SECS` :23); peers serve a record only with its certificate (handler.rs:1909-1919 `get_epoch_by_number`, `UnavailableEpoch` otherwise); re-vote covers only N-1 (epoch_votes.rs:483-502) and the latest record at startup (:563-578), with main's own comment at :552-558; a conflicting certified record is only logged (`ConflictingRecord` -> `stop_on_local_failure`, storage/src/epoch_records.rs:2707, :2721-2727, `error!` and `Ok`; the pass returns `epoch - 1`, :281-284) while the vote round's recovery calls `node_shutdown.notify()` (epoch_votes.rs:279-289).
"Established" / "Undetermined" matches DR-E verdict 6 and §6 (:99-105, "Could not determine" :159): full pack needs a stored record (consensus.rs:302-354, read), partial pack needs record K+j-1; the header walk is DR-E's open point.
403 of 407 (E-4 :11-13), 373 + 28 (14 + 14) + 2 = 403, the 4 = validators 01-04 stopped before r20261112-1520's teardown close (E-4 :13, :122).
5.47 s (observer, r20261112-1520 epoch 4) and 3.86 s (E-4 :120); the brief's "5.5 s" is the same figure rounded.
"r20261114-0000's epoch-7 close also first reached quorum on exactly 7": found, benchmark/private/bench6-r20261113-2118/A3a/vs-always-on.md:122 ("loaded closes whose first quorum formed on exactly 7 votes": run 2b 1, the kill close; run 3b 1, epoch 7).
r20261113-1630's 18:22:19 close, exactly 7 voters, one down, two 13-15 s late: E-4 :179, report :404.
Adaptive runs, all eleven nodes held every record: vs-always-on.md :37, :124.
"about 65 s": right by main's code (26 timed-out 2.5 s waits, see text 3).

### Errors

1. Where: the title, "One uncertified epoch stops every node's record collector there for good; a conflicting certified record is only logged".
   What the text says: any uncertified epoch stops the collector for good.
   What the source says: every epoch is uncertified until its first quorum (1.2-34.9 s after each close, E-4 :173), and the walk moves on once a peer holds the certificate (epoch.rs:243-262); it stays stopped only for an epoch the network never certifies (body lines 8-12; DR-E :105; E-4 :143 "it can stay uncertified for good").
   Replacement (118 characters): "An epoch the network never certifies stops every record collector there; a conflicting certified record is only logged"

### Weak

- Line 44, "No test leaves an epoch uncertified": the test it cites at `epoch.rs:651` does leave the node's own record uncertified (E-4 :146, "our record stays, uncertified"); DR-E §7 (:114) says no test withholds votes. Replacement: "No test leaves an epoch uncertified across the network; tests at `state-sync/src/epoch.rs:651` and `:798` pin G2."
- Line 25, "an arm walk on the same fleet": as text 1.

### Rule breaches

- None. Length 925 words by `wc -w`, 883 without headings: inside 400-900.

### Placeholder

- Line 64: "- {{epoch-record-closing-block-check}}: the check before a node saves its own record."
- Texts 1 and 2 reference each other, so whichever is created first cannot carry the other's number without a later edit. To avoid the edit, create the collector issue first with its line 64 reworded to "- A separate issue covers the check before a node saves its own record." (or deleted), then create the closing-block issue with line 60 carrying the collector issue's number; or the reverse with text 1's line 60 reworded to "- A separate issue covers a record the network leaves uncertified, or certifies differently from a node's own."

## Text 3: issue-bodies/bench6-false-quorum-error-on-epoch-close.md

Verdict: PASS (one weak item).
Counts: 24 checked / 24 matched / 0 wrong / 0 untraceable.
Title: 113 characters, true of main (the error at epoch_votes.rs:231-237 has no store check; the round's length is the code's 26 waits; the measured gap is 64.5-65.0 s, E-4 :14, :118).
"about 65 s" is right: `EPOCH_VOTE_RECV_TIMEOUT` = 2,500 ms (:27), `MAX_EPOCH_VOTE_TIMEOUTS` = 24 (:34), the loop breaks on the timed-out wait that finds the counter above 24 (:154) and adds 1 otherwise (:157), so the 26th timed-out wait ends the round (26 × 2.5 s = 65 s); the error line logs `timeouts=25` because the last wait is not counted.
The same constants and loop are at 2df831e3c (epoch_votes.rs:27, :34, :154), so bench 6's own "25 timed-out 2.5-s waits, about 62.5 s" (report :415, E-4 :179) is the figure that is off, not this text's; if a public run page says 62.5 s, it disagrees with this issue.
The text never calls the three runs "always-on": it says "In three bench-6 runs …: 7 in an arm walk … (r20261112-1520 …), 3 in r20261113-1351 and 1 in r20261113-1630", which matches E-4 :14, :117 and report :421; "4 more in the adaptive runs" = 3 in r20261113-2118 + 1 in r20261114-0000 (A3a/closes.md :127, :217; vs-always-on.md :36, :123).
"a build whose vote round and vote-drop rule are main's": `git diff 2df831e3c 45dce8947 -- crates/node/src/manager/epoch_votes.rs` touches only tests; the bench-6 handler has the same drop line (handler.rs:765 at 2df831e3c).
Code lines: :238 calls `record_epoch_record_signers`, :622-624 sets `tn_node.epoch_record_signers`; recovery :239-323; handler.rs:866-915 forwards a vote only for a held uncertified record; `cert_by_digest` at storage/src/epoch_records.rs:898; `test_failed_round_sets_signer_gauge` at epoch_votes.rs:2225.
"1 to 5" signers: report :422; A3a closes.md :127 (4-5), :217 (1).

### Weak

- Line 27, "The same check can skip the signer gauge at `:238`.": main sets the gauge on every failed round by design (doc at epoch_votes.rs:616-621: "A round that fails to reach quorum sets it too"), and the fix in preparation changes nothing else in the round (tasks/bench7/briefs/e2.md item 3: "Nothing else in the vote round changes"), so the sentence describes a change the announced PR will not make. Replacement: delete the sentence, or "Whether the signer gauge at `:238` should also skip such a round is open: main sets it on every failed round by design (`:616-621`)."
- Line 11, "an arm walk on the same fleet": as text 1.

### Rule breaches

- None. 404 words by `wc -w` with the title, 381 without it: inside 250-400.

### Placeholder

- None.

## Text 4: issue-comments/bench6-1807.md (comment on #1807)

Verdict: FIX.
Counts: 42 checked / 41 matched / 1 wrong / 0 untraceable.
#1807 read with gh: open, 0 comments, so nothing is repeated or contradicted.
The mechanism paragraph checks on main's proposer.rs at 45dce8947: per-worker FIFO lanes `digests: BTreeMap<WorkerId, VecDeque<ProposerDigest>>` (:139); `drain_digests_for_header` pops lane fronts (:974-999); `prepend_requeued` puts re-queued digests in front (:950-954); the cancelled path `process_uncertified_header` (:902-921) and the commit path over tracked headers at or below the committed round (:847-862); "both run after a newer own header drained" is DR-1807 Q1 (:46-49); payload order is execution order is DR-1807 Q6.
The cost table matches A7 comparison.md §3 cell by cell, per run id and column order (run 2 = r20261113-1351, run 3 = r20261113-2118, run 2b = r20261113-1630, run 3b = r20261114-0000; A7 :9-10): gap resends :240, unlanded after the 180-s tail scan :249, landed over accepted :251; the counts are blast 2 (the 600 × 16 blast, mixed windows 2,410-2,447 s, A7 :236), as the intro says.
715 of 717 = 31 + 124 + 175 + 385 of 31 + 124 + 177 + 385 (A7 :256); 183 all generator 05 (A7 :249, "183 / 0"); 173 and 12 never executed, from headers lost in an epoch's last 13-30 s (A7 :248; L :12, :114, :142).
Why the pool-side switches are not proposed: matches report §4.7 (:477 no gap resends and nothing unlanded, pool 230 → 10,244, confounded with four switches and an epoch boundary; :481 19 % not executed, about 1.22× pages per transaction, duplicate digests; :488 the keep alone; :478 dedupe counters 0 on or off); neither switch exists on main (`git grep` at 45dce8947: none) and the bench 7 task list has no port unit for them.
The hold is described as in preparation, untested and to be measured in the next run before a PR (line 34), with no claim that it works; header contents only, no timing or validity change, switch off by default match the hold design (:5, :20, :26, :28).
The comment says plainly that it changes the body's recommendation (line 31: "This changes the body's proposal: it preferred (A) and rejected holding nonces at the builder …"; body :129, :167-169).

### Errors

1. Where: "Still open", line 38: "The second defect, a sealed transaction invisible to the RPC: the hold does not touch it."
   What the text says: the body's second defect is RPC invisibility.
   What the source says: the body's second defect is "A resend executes beside the original" (#1807 body, "Problem" item 2); invisibility to the pool and the RPC is the cause the body gives for both defects ("Problem" first paragraph; the body's Proposal calls the visibility fix "Symptom 2").
   Replacement: "- The second defect, a resend that executes beside the original because a sealed transaction is invisible to the pool and the RPC: the hold does not touch it."

### Weak

- Line 1, "all four headline runs": the report uses "the headline" for r20261113-1351 alone (report :98); the four runs are named only in the table. Replacement: "the loss showed in all four of bench 6's load runs".
- Line 19, "a generator on a running validator": the 715 of 717 count generators 01-04 and 06-10, i.e. every generator but the killed validator's (A7 :256). Replacement: "Of the seconds in which a generator other than the killed validator's resent, 715 of 717 over the four runs fell 280-345 s after a lost own header of that generator's validator, as the 300-s gap check predicts (measured; the mechanism is read from code)."
- Optional: the body's "Related" also said of the two re-queue paths "no change proposed"; the hold leaves them as they are and changes only what a new header takes, which the comment could say in one clause.

### Rule breaches

- Length: 537 words by `wc -w`, 507 without its headings, against the 500-word cap (u-common: 150-500; the brief: 300-500). Applying the replacements above does not shorten it; dropping the optional last sentence of the mechanism paragraph or the "A later analysis attributes these side effects to the keep alone." sentence would.

### Placeholder

- None.

## Cross-text

- "about 65 s" reads the same in texts 2 and 3, and both match main's code and the measured 64.5-65.0 s; the private report and E-4 carry 62.5 s.
- The arm walk is named r20261112-1520 with "nine configurations by rolling restart" in texts 1 and 2, and as an arm walk in texts 3 and 4: consistent.
- Ten validators and one observer, 20,000 and 50,000 IOPS per run id: consistent across all four.
- Titles: 109, 119 (118 with the fix), 113 characters.
