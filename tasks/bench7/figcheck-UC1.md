# Figure-check FC-UC1: the five bench-6 issue comments (#1806, #1802, #1803, #1805, #1774)

Checked 2026-11-14 against the report, the analysis files the notes cite, upstream main at 45dce8947 (`telcoin-network-b7`), the bench-6 build at 2df831e3c (`telcoin-network-b6`) and each issue as it stands (`gh issue view`, read only).
One section per comment; each has its verdict line first.

## Summary

Overall: FIX on all five; no BLOCK (no error changes a comment's conclusion).
Counts over the five: 153 figures and claims checked / 144 matched (19 of them with weak wording) / 9 wrong / 0 untraceable.
- #1806: FIX, 3 errors (per-close vs per-node label on 55-1,310; the four headline runs never named, r20261113-2118 absent; "there" covers the wrong run and bench 5's 11.0 s contradicts the issue's 10.9 s). The 15 false-quorum lines re-derive exactly (7 + 3 + 1 + 3 + 1); the tracker overflow with the drain switch off in r20261113-1630 on validator-05 (two loaded closes) and validator-01 (outage close, 272 lines) is right.
- #1802: FIX, 2 errors ("125 of 677" reads as skipped; "re-applied on growth" misdescribes the bench-6 switch). The 8.7× is a local probe and the text says so, but the `mdbx_stat` effect itself is read from code and should say so (weak 1). `--db.gap-fill auto` is main's default on Linux tn-lmdb: right.
- #1803: FIX, 2 errors (r20261113-1351's generator figures are two runs' range; 95 % rounds to 96 %). The +24 % loaded round is right in value, arm (`gr150` against the arm before, `bound`) and window (the short 600 × 16 blast against `bound`'s 600 × 16), with a blast-shape caveat the text gives only to throughput; the far pair's leader share did not recover: right.
- #1805: FIX, 1 error (r20261114-0000 does not repeat "the costliest engine set the rate"). Every bench figure and the arm are right; the 50,000 IOPS pattern is labelled a correlation.
- #1774: FIX, 1 error (the `Invalid epoch` totals are not "at the same closes"); "delayed, not lost" holds as read from code on main; recommend not posting.

Cross-text: the four texts that name r20261112-1520 all use "an arm walk on the same fleet (r20261112-1520, nine configurations by rolling restart)". In #1802, #1803 and #1805 "the same fleet" has no antecedent at that point and nothing says the run has no page; one wording for all four is proposed under each text's weak items ("on the bench-6 fleet (r20261112-1520: nine node configurations applied one after another by rolling restart; it has no public page)"). Same quantities read the same across texts (IOPS per run, vote-form names, the 15 = 11 + 4 false-quorum count against the new issue body).
Length: by prose words (markup and URLs excluded) the texts are 500 (#1802), 471 (#1803), 495 (#1805), 498 (#1806), 155 (#1774); the additions proposed under "Weak" push #1802, #1805 and #1806 past 500, so trim elsewhere if they are taken.

## bench6-1806.md (#1806, open, no comments)

Verdict: FIX

Errors:
1. "### The tracker-drain arm", "every node reaped all its tracked tasks (55-1,310 per close)": the range is per node at one close, not per close: `task tracking finished tracked=55..1,310 reaped=69..1,316` at the arm walk's single loaded close with the switch on, 20:00:32, v10 55 tasks to v02 1,310 (`benchmark/private/bench6-r20261112-1520/A3/boundary.md:53`, `:86-87`).
   Replacement: "with it on, every node reaped every task it had tracked at the loaded close (55 to 1,310 tasks per node), but no validator overflowed with it off in that run either, so the fix was not exercised."
2. "### The closes", line 5 "and the four headline runs": the four headline runs are never named, and r20261113-2118 appears nowhere in the comment, so "five runs" (line 1) and "the five runs" (the false quorum error) cannot be mapped to run ids. Counts behind 52: 25 + 6 + 6 + 6 + 9 (`benchmark/private/bench6-r20261113-1351/E-1/findings.md:7-8`; report `tasks/bench6-report-r20261113-1351.md:391`, `:716`, `:741`).
   Replacement for line 5: "All 52 closes of five runs certified with at least 7 of 10 signers, each on one record hash and one closing block: 25 in an arm walk on the same fleet (r20261112-1520, nine configurations by rolling restart, not published as a page) and 27 in the four headline runs, [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) and [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) (always-on vote form, 20,000 and 50,000 IOPS, 6 closes each), [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) and [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/) (adaptive form, 20,000 and 50,000 IOPS, 6 and 9 closes)."
   (The links on lines 6, 7 and 14 then become second mentions and can stay or go.)
3. "### The closes", line 7 "Loaded commit gaps were 3.5-14.5 s there ... against bench 5's 22.5 and 11.0 s": (a) "there" follows a sentence naming r20261112-1520 and r20261113-1351, but 3.48-14.49 s is r20261113-1351 alone; the arm walk's loaded gaps were 14.9-34.0 s (report `:396-404`; `benchmark/private/bench6-r20261112-1520/A3/boundary.md:103`). (b) The issue itself gives the bench-5 epoch-8 gap as 10.9 s (body, "Problem", the evidence table and "Mechanism"); the report's 11.0 s (`:408`) will read as a contradiction.
   Replacement: "Loaded commit gaps were 3.5-14.5 s in r20261113-1351 and 3.4-10.3 s in r20261113-1630, against bench 5's 22.5 and 10.9 s."

Not traceable: none (every figure found; the four adaptive-run false-quorum lines are in the adaptive-run analysis files, not in the report, as the writer says).

Weak:
1. "With it off, the headline runs overflowed again: in r20261113-1630 ...": the overflow at a close is sourced for r20261113-1630 only (`benchmark/private/bench6-r20261113-1351/A3b/census.md:132`, `:180-182`); r20261113-1351's overflow (about 1,400 lines, 15:47-15:48) is validator-05's catch-up after its restart, not a close (`census.md:126`), and no analysis of the adaptive runs counts the tracker line.
   Replacement: "With it off, the overflow came back at loaded closes of r20261113-1630: validator-05 at the two loaded closes before its kill and validator-01 at the outage close (272 lines on validator-01 in that minute)."
   The drain switch was off in all four headline runs: confirmed (report `:145`, `:669`; default off).
2. "with one run each their closes looked the same (the outage close's first quorum at 12.82 s always-on, 9.87 s adaptive)": the source says the 3 s difference is inside the always-on run's own spread of loaded closes, 4.47-12.82 s (`benchmark/private/bench6-r20261113-2118/A3a/closes.md:209-210`), and the pair is the 50,000 IOPS one, unnamed in the text.
   Replacement: "and with one run each, their closes differed by no more than one run's own spread: at 50,000 IOPS the outage close's first quorum came at 12.82 s always-on (r20261113-1630) and 9.87 s adaptive (r20261114-0000), inside the 4.47-12.82 s of the always-on run's loaded closes."
3. "validator-02 for 4 minutes after an epoch opened in r20261114-0000": reads as "4 minutes after"; the source is demoted 30 s after epoch 8 opened, `CvvInactive` for 4m00.0s (report `:817`).
   Replacement: "and validator-02 for 4 minutes, from 30 s after epoch 8 opened, in [r20261114-0000](…)".
4. "the node's own round times out after 25 waits": the log field is `timeouts=25`, but on main the loop breaks on the 26th timed-out 2.5 s wait (`crates/node/src/manager/epoch_votes.rs:100`, `:154-157`; its own doc at `:30-33` says up to `MAX_EPOCH_VOTE_TIMEOUTS + 2` windows), about 65 s, which is what the new false-quorum issue body says.
   Replacement: "so the node's own round gives up about 65 s later (`timeouts=25`) and fetches the same hash."
5. The false quorum error has its own new issue body (`tasks/issue-bodies/bench6-false-quorum-error-on-epoch-close.md`, same 11 + 4 = 15 count); the comment should point to it, e.g. append to that sentence: "Filed separately as {{false-quorum-error-on-epoch-close}}." (the orchestrator's slug; add it to the slug list).
6. "inside the boundary arm of the `tokio::select!` whose other arm reaps tasks (`:484-562`)": the `select!` has five arms; the reaping one is `until_task_ends` at `:560`. Suggested: "whose `until_task_ends` arm (`:560`), the one that reaps tasks, is not polled meanwhile (`:484-563`)".

Checked and right: 52 closes (25 + 6 + 6 + 6 + 9), at least 7 signers, one hash and one closing block; seventh vote and seventh `Starting epoch` 0.2 s apart (E-1 `:131`); 3.42-10.31 s in r20261113-1630; the 18:22:19 close (exactly 7 voted, v01 and v02 draining 15-output backlogs, no eighth vote; `A3a/closes.md:7`, `:44`, `:46`); late v01 / v05; early-vote drop (E-1 `:100-104`); v05 demoted twice at 18:02:19 for 4.05 s (report `:409`); 15 false-quorum lines = 7 (r20261112-1520, observer included) + 3 + 1 + 3 + 1, each on a node already holding the certified record (`A3a/closes.md:84-87`; adaptive `A3a/closes.md:125-128`, `:215-217`); 272 lines on v01; "neither vote form reaches the record path" (report `:412-413`).
Code on main at 45dce8947, all as cited: `run_epoch.rs:835-840` (shutdown notify, then `wait_for_consensus_execution(target_hash)`), `:484` `select!`, boundary arm `:492-544`, `until_task_ends` arm `:560`; `task_manager.rs:298` `mpsc::channel(1000)`, `:199-201` `try_send` failure and the error text; `epoch_votes.rs:152-156` (break on quorum or `timeouts > MAX_EPOCH_VOTE_TIMEOUTS`), `:231-237` the error; `handler.rs:903-914` drop for unknown or certified record; `close_epoch.rs:430-433` `check_stored_record` (body `:712-749`, compares with this node's closing block). (D) and (E) are absent on main: no `epoch close drained`, `task tracking finished` or close-drain gauge in `crates/` at M.
Issue: OPEN, no comments; the comment does not misstate the body.

Rule breaches: none (no unit names, private paths, hosts or nicknames).

Counts: 41 figures and claims checked / 38 matched (6 of them with weak wording) / 3 wrong / 0 untraceable.

## bench6-1802.md (#1802, open, no comments)

Verdict: FIX

Errors:
1. "### What starts and ends the state", line 6, "so libmdbx skipped its prefault writes (125 of 677 grown pages)": reads as 125 pages skipped; the source is 125 pages prefaulted of 677 grown, so about 550 skipped (`benchmark/private/bench6-r20261112-1520/I-9/findings.md:11`, `:34`; report `tasks/bench6-report-r20261113-1351.md:334`).
   Replacement: "so libmdbx skipped most of its prefault writes (it prefaulted 125 of 677 grown pages) and new pages landed in order-4 and order-5 folios."
2. "### The fix, measured", line 13, "whole-map `MADV_RANDOM`, re-applied on growth": the bench-6 switch advises every mapping once at open and re-applies only when the map's upper limit changes; growth inside the limit adds no mapping and is not re-advised (`telcoin-network-b6` at 2df831e3c, `crates/tn-reth/src/env/mdbx_advice.rs:13-18`; test `crates/tn-reth/src/env/mod.rs:1026-1030`). That is also what the issue's fix (a) says ("again after any geometry change").
   Replacement: "whole-map `MADV_RANDOM`, re-applied whenever the map size changes (fix (a) above)".

Not traceable: none.

Weak:
1. Line 33, the `mdbx_stat` caution: that a stock `mdbx_stat` turns the node's prefault writes off is read from code (`mdbx_stat.c:3515` opens `MDBX_RDONLY` without `MDBX_NORDAHEAD`; `mdbx.c:22486-22500`; `benchmark/private/bench6-prep/I-1r/verdict.md:15`, `:134-137`), never measured with an `mdbx_stat` against a node; the 8.7 is a local probe arm with prefault switched off directly (`7-pfoff`, 8.685 device bytes per MDBX-dirtied byte; 1.000 with prefault on; `I-1r/verdict.md:11-13`, `:31`).
   The text does say "a local probe"; it should also say "read from code" and what the probe switched.
   Replacement: "For the `mdbx` build, one caution about the sampler proposed above: a stock `mdbx_stat` opens without `MDBX_NORDAHEAD`, which turns the node's prefault writes off (read from code: `mdbx.c:22486-22500`), and a local probe with prefault switched off wrote 8.7 times its page bytes, against 1.00 with it on."
2. Line 15, "Bench 5 wrote 10-13 times": the issue body expects "about 4" for the same ratio in bench-5-like conditions (its §Proposal item 3, Δdevice ÷ (Δ(newly + cow) × 4096)), from an every-page bound; the model behind 10-13 says that bound is three to four times what MDBX copied (`benchmark/private/bench6-r20261112-1520/A8/writes-model.md:263-264`). A maintainer will see two numbers for one ratio.
   Suggested addition after "(through a model: it logged no page counts)": "; the issue's 'about 4' divided by an every-page bound, which the model puts at three to four times the pages MDBX copied".
3. Line 5, "an arm walk on the same fleet": no fleet has been named yet in this comment (the headline runs come at line 13), and the run has no page.
   Replacement: "We traced it in an arm walk on the bench-6 fleet (r20261112-1520: nine node configurations applied one after another by rolling restart; it has no public page)."
4. Line 6, "from the ninth output on": the source says "from output 9 (15:49:22Z) on", output numbers, a minute after genesis (`I-9/findings.md:11`, `:42`).
   Replacement: "from output 9 on, a minute after genesis".
5. Line 7 and line 33 cite `mdbx.c:<line>` without naming the file; the lines are right in main's vendored libmdbx 0.13.7 (`vendor/reth/crates/storage/libmdbx-rs/mdbx-sys/libmdbx/mdbx.c`). Optional: name it once ("libmdbx 0.13.7 as vendored on main, `mdbx.c:20581-20590`").

Checked and right: first process after genesis, every node, frontier pages cached past the open-time advice, order-4/5 folios (`I-9/findings.md:11`, `:62-64`); restart ends it, open discards the file past its used size (`mdbx.c:20583-20590`, `MADV_REMOVE` for the first opener on a WRITEMAP environment, at main's vendored copy); later processes 1.00-1.52 (`I-9:39`); observer 6.5-10.9 (`I-9:14`, report `:337`); correlation only, bench 5 not checked (`I-9:82-83`, `:97`); four runs with the advice from the first start (report `:145`, `:669`); prefault 1.000-1.025 every process every blast (`A4p/disk.md:45`, `:380`; adaptive `A4p/vs-always-on.md:188`, `:382`); no folio above order 3 (`disk.md:46`; `vs-always-on.md:191-192`, `:385-386`); 1.16-1.19 at full load over the four runs (1.156-1.193); 19,967 writes/s, 0.998, 3.74 writes of 5.0 KiB per tx (`disk.md:33`, `:35`, `:64`); bench 5 0.68 writes of 227 KB (`disk.md:235`); 6,701 → 4,508-4,846 tx/s (`disk.md:36`); 50,000 IOPS at 0.497 (`disk.md:38`).
Code on main at 45dce8947: `crates/tn-reth/Cargo.toml:157-161` (`mdbx = []`, off by default); `crates/tn-lmdb/src/file.rs:826-839` (`map_reservation` advises `MADV_RANDOM` unless `readahead`), remaps through the same call (`:453-455`); `crates/tn-lmdb/src/env.rs:397` (`readahead: !cfg!(target_os = "linux")`), kept by the node (`crates/tn-lmdb-reth/src/env.rs:313-324`); `crates/tn-reth/src/cli.rs:112-119` (`DEFAULT_DB_GAP_FILL` is `Auto` on Linux without the `mdbx` feature; the doc at `:101-107` says fewer, larger writes for more bytes written): "trades bytes for fewer writes" is right; no `madvise`/`MADV_RANDOM`/`mdbx_random_advice` under `crates/tn-reth/src` on main.
`mdbx_stat.c:3515` (vendored) opens `MDBX_RDONLY` with no `MDBX_NORDAHEAD`: right.
Issue: OPEN, no comments; "fix (a) above" and "the sampler proposed above" match the body (Proposal table row (a); item 3 and the test plan's `mdbx_stat -e` sampler).

Rule breaches: none.

Counts: 33 figures and claims checked / 31 matched (5 of them with weak wording) / 2 wrong / 0 untraceable.

## bench6-1803.md (#1803, open, no comments)

Verdict: FIX

Errors:
1. "### The headline runs left it off", line 26, "their generators landed 9-12 % of the others' rate at a seen p50 of 13-17 s": 9-12 % and 13-17 s span r20261113-1351 and r20261113-1630 together; r20261113-1351 alone is 11 % and 12 % at 17.29 and 15.86 s (`benchmark/private/bench6-r20261113-1351/A1/kpis.md:258-259`; the 9 % and 13.2-14.4 s are r20261113-1630's, `:264-265`; the summary line `:274` covers both runs).
   Replacement: "In [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) the far pair again held 2.74 % and 2.68 % of committed certificates at light load, and their generators landed 11 % and 12 % of the other eight's median rate at a seen p50 of 17.3 and 15.9 s, as in bench 5."
2. "### Idle and light load", line 12, "ended complete on 95 % of those": 6,117 of 6,396 armed (95.6 %) at idle and 7,488 of 7,838 (95.5 %) in the light blast (`benchmark/private/bench6-r20261112-1520/A2/grace.md:27`, `:29`, `:47-48`); both round to 96 %.
   Replacement: "ended complete on 96 % of those".

Not traceable: none.

Weak:
1. Line 20, "the median round was 461.6 ms against 371.3 ms in the arm before (+24 %)": the arithmetic is right (461.6 / 371.3 = 1.243) and the comparison arm is right (`bound`, the arm before, whose switches the grace arm kept, so only the grace differs; report `:128-140`), but the two blasts differ in shape too (300 s mixed phase against 480 s, colder cache), and the source attaches that caveat to the round time as well (`A2/grace.md:42-43`); the text attaches it only to throughput.
   Replacement: "... and the median round was 461.6 ms against 371.3 ms in the arm before (+24 %), though the two blasts also differed in length and cache state."
   Then line 21: "Executed throughput held (4,084 against 4,093 tx/s), but for the same reasons its effect on throughput is not settled."
2. Line 5, "an arm walk on the same fleet": no fleet or run has been named before this line, and the run has no page.
   Replacement: "The grace ran in an arm walk on the bench-6 fleet (r20261112-1520: nine node configurations applied one after another by rolling restart, each keeping the earlier arms' switches; it has no public page), among them the adaptive vote fix and pipelined persist: an idle mark, a light 8 × 16 blast and a short 600 × 16 blast."
3. Line 15, "Validator-10's fell from 11-13 % to 0-5 %": sits under "Idle and light load", but the 5 % is the short 600 × 16 blast (0.89 % idle, 0 % light, 5.07 % loaded; `A2/grace.md:60`).
   Replacement: "Validator-10's fell from 11-13 % to 0.9 % at idle and 0 % at light load (5.1 % in the loaded blast), unexplained."

Checked and right: arm = `parent_grace=150ms` on top of `bound`'s switches, adaptive form and pipelined persist among them (`grace.md:8-11`; report `:130-140`, `:586`); one G only (`grace.md:72`); the leader exception is bench-6 commit 79a355f82 "fix(primary): never hold the next round's leader in a parent grace", an ancestor of 2df831e3c, and its reason matches line 6; 1.8-2.8 % → 10.0 % (1.82-2.82 → 9.98-10.0; `grace.md:23-29`); never committed 79-84 % → 0.0-0.6 % (78.9-84.2 → 0.0-0.6; `grace.md:37`); generators 10.2 / 8.8 tx/s at 15.2 / 15.9 s → 50.9 / 49.4 at 2.53 / 2.55 s (`A7/verdicts.md:357`); armed 94-95 % (`grace.md:47`); waits p50 85-102 ms (`grace.md:50`); round 345 → 441-443 ms, +28 % (`grace.md:35-36`); model 364-404 ms (issue, Proposal (A)); floor seen p50 1.51 → 1.77 s (`verdicts.md:356`, sampled); 02/06 leader share 0 % light, under 1 % idle (`grace.md:59`); loaded: 6,699 of 7,109 armed, 965 expired (`grace.md:31`, `:49`); executed 4,084 vs 4,093 (`A4p/cache.md:46`, `:48`); the "about 0 under load" correction (`tasks/bench6-upstream-followups.md:14`); why left off (`tasks/bench6-g3-brief.md:79-82`); 2.74 / 2.68 % in r20261113-1351 (`A2/certification.md:183`); still-open items (followups `:15-17`, report `:584-587`).
Code on main at 45dce8947: `proposer.rs:566-576` `calc_min_delay` gives the next even round's leader `Duration::ZERO`; `:771-780` ignores older parents; no `grace` or `parent_grace` in `proposer.rs`: "unchanged on main" holds.
Issue: OPEN, no comments; the comment quotes the body correctly ("the wait almost never runs ... the cost is about 0"; (A) applies to leaders too; (E) "their scores recover ... revisit only if their leader share stays below about 5 %").

Rule breaches: none.

Counts: 30 figures and claims checked / 28 matched (3 of them with weak wording) / 2 wrong / 0 untraceable.

## bench6-1805.md (#1805, open, no comments)

Verdict: FIX

Errors:
1. "### The headline runs, without it", line 27, "[r20261114-0000] repeats the pattern (15.1 against 19.1-19.8)": "the pattern" reads as the whole sentence before it, including "that costliest engine set the fleet's executed rate". In r20261114-0000 the costliest at-cap engine did not set the rate: validator-02 (finish 19.1, task 137.8 µs/tx) executed 6,912 tx/s against 7,244-7,256 on the others, fell behind and was demoted `epoch_behind` (`benchmark/private/bench6-r20261113-2118/A4e/vs-always-on.md:492`, `:494-499`; report `:817-818`). Only the `finish` spread repeats.
   Replacement: "...and that costliest engine set the fleet's executed rate. [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/) shows the same `finish` spread (15.1 µs/tx on a drained queue against 19.1-19.8 at the cap)."

Not traceable: none.

Weak:
1. Lines 13-14, the quiet-host bench: the comment reports the dedicated pool's cost in the root against the issue's 5 % line but not that `finish` itself failed the issue's 15 % line with two jobs (3.64 against 3.09, ratio 1.177, `result=fail`; one job passed at 1.098; `benchmark/private/bench6-prep/I-3/contention-u4b.md:54-55`; `I-3/verdict.md:155`, which reads the fail as spread at that load, since the two-job loop case passed at 1.049).
   Suggested addition after "The dedicated pool removes that wait": "(`finish` passed the 15 % line with one job and missed it with two, at +17.7 %, which the loop case at the same load passed)".
2. Line 18, "switched on with three other switches": the same arm also moved the vote fix back from the always-on to the adaptive form (`starved_rounds=4`; report `:136`).
   Replacement: "switched on with three other switches, and with the vote fix back to its adaptive form, across an epoch boundary."
3. Line 18, "an arm walk on the same fleet": no fleet has been named before this line, and the run has no page.
   Replacement: "`recovery_threads=3` ran in an arm walk on the bench-6 fleet (r20261112-1520: nine node configurations applied one after another by rolling restart; it has no public page), ..."
4. Line 13, "94-98 %": that range is all four one-shot lines, the whole-host ones included (93.6-97.5 %, `contention-u4b.md:75`); at the validators' shape alone it is 95-98 %. Optional: "95-98 %".

Checked and right: bench shape 6,000 transactions, 20 blocks, `taskset -c 0-3,8-11` = 4 cores × 2 threads, dedicated pool 3 threads, quiet host (`contention-u4b.md:3-4`, `:14-19`; `verdict.md:142`); the table, every cell: shared 3.03 / 11.07 (+8.04) / 19.45 (+16.42), dedicated 3.09 / 3.40 (+0.30) / 3.64 (+0.55) (`contention-u4b.md:46`, `:49-51`, `:54-55`); root +7-16 % beside the job (`verdict.md:156`; ratios 1.069-1.159 at c8, `contention-u4b.md:83`), outside the issue's "evm + root within 5 %" line; 78 ms on three threads against 51 ms on eight (`contention-u4b.md:49`, `:54`); fleet arm `pool-local-r2` across an epoch boundary (report `:136`); finish 16.9 → 7.3, 7.3-10.3, back to 15.1 (`benchmark/private/bench6-r20261112-1520/A4e/execute.md:112`); job 21.1 vs 13.6, `recover_wait` 0.5 (`execute.md:109-110`); root +15.4 of which faults 3.5-7.7, the rest with the pool, labelled a timing coincidence there (`execute.md:101-103`); execute 99.6 → 107.2 (`execute.md:115`); inconclusive, confounded (`A7/verdicts.md:237`, `:424`); switch off in the headline runs (report `:145`, `:669`); r20261113-1351 queues at the cap 0.98-0.99 and finish 18.1-19.1 (`benchmark/private/bench6-r20261113-1351/A4e/engine.md:162-171`, `:183`); r20261113-1630 finish 13.6 (v06, at the cap 3 % of samples) to 19.2 (v01, 98 %), v01's capacity 7,287 tx/s = the fleet's rate (`engine.md:172-181`, `:184-185`); correlation only (`I-10/findings.md:117`): the 50,000 IOPS pattern is labelled a correlation in the text.
Code on main at 45dce8947: `crates/engine/src/lib.rs:247-252` (`enqueue` spawns `RecoveryHandle::spawn` per non-empty output); `crates/tn-reth/src/env/execution.rs:240-258` (`recover_output_signers`, `par_iter` on the global pool; no `recovery_threads` anywhere in `crates/`); `:435` `builder.finish(&root_provider)`, whose reth `HashedPostState::from_bundle_state` is `into_par_iter` with the `rayon` feature (vendored `trie/common/src/hashed_state.rs:49-54`, `trie/trie/Cargo.toml:21`); `:470` `rayon::join` in the seal, which main adds to the finish lap (`:449-451`); `crates/tn-reth/src/env/output_overlay/parallel.rs:1-30` storage-root tasks on rayon's global pool, a busy pool degrades the root to serial, the file came with #1834 (af0f1ccae). The bench-6 tree has neither `parallel.rs` nor tn-lmdb, so "an MDBX build without the parallel root" is right. Both main statements are labelled "read from code".
Issue: OPEN, no comments; "as described above" (the issue's mechanism item 2) and "the 5 % pass line above" (its test plan) match the body.

Rule breaches: none.

Counts: 34 figures and claims checked / 33 matched (4 of them with weak wording) / 1 wrong / 0 untraceable.

## bench6-1774.md (#1774, closed 2026-11-12, no comments)

Verdict: FIX (and post only if a record on the closed issue is wanted)

Errors:
1. Line 1, "beside 2,838 and 5,883 `Invalid epoch` refusals at the same closes": those are whole-run totals, and most of them came after validator-05's restart, not at a close: 2,263 of 2,838 (r20261113-1351, 15:47-15:48) and 4,456 of 5,883 (r20261113-1630, 18:26-18:29) fall in the after-restart window; the windows holding the loaded closes, the same windows that hold the 177 and 742, have 575 (372 + 176 + 27) and 1,427 (485 + 635 + 307) (`benchmark/private/bench6-r20261113-1351/A3b/census.json`, the two runs' `Invalid epoch` template `by_window`; `A3b/census.md:129`, `:172`; the 177 / 742 windows `census.md:118`, `:225`).
   Replacement: "..., at loaded epoch closes with every pool switch off, beside 575 and 1,427 `Invalid epoch` refusals in the same windows, as the batch builders retried across the boundary."

Not traceable: none.

Weak:
1. Line 3, "those transactions wait until the builder's batch carries the new epoch": true for a lagging sender, whose old-epoch batch is refused by peers already in the new epoch (validator-05 and validator-01, the late validators, logged most of the repeats: 97 of 177 on v05; 263 and 125 of 742 on v05 and v01; `census.md:118`). The other direction also occurred: the sender's quorum waiter logs these refusals (`crates/consensus/worker/src/quorum_waiter.rs:94-99`), and the census's example `Invalid epoch` lines read "expected epoch 2 got epoch 3" (`census.md:172`; `expected` is the refusing peer's epoch, `crates/batch-validator/src/validator.rs:124-128`), a sender already in the new epoch refused by a peer still in the old one; there the batch already carries the new epoch and the wait ends when the refusing peer enters it (its new handler starts with an empty set, `handler.rs:202-206`). The pool does outlive the epoch's builder (`crates/node/src/engine/inner.rs:107-116`: each epoch's builder takes the worker's persistent pool), which the writer's note left unchecked.
   Replacement: "Read from code and not traced per transaction in the logs: those transactions stay in the worker's pool, which outlives the epoch's batch builder, and go out again once the sender and the refusing peer are in the same epoch, as they would have without the cache, so nothing here needs the issue reopened."

Delayed, not lost, traced on main at 45dce8947: the peer refuses a cached digest before validation (`handler.rs:540-543`); only body faults are cached, `InvalidEpoch` and `InvalidBaseFee` among them (`handler.rs:107-121`, `:249-257`); the set is per epoch because the handler is rebuilt per epoch (`handler.rs:196-207`), capacity 1,024 (`:53-59`); the validator takes the epoch's base fee and epoch at epoch start (`crates/node/src/manager/node/start_epoch.rs:926-927`, `crates/node/src/engine/inner.rs:254-263`), so within one handler a cached refusal equals a re-validation; the sender's quorum waiter counts the `RPCError` as rejected stake (`quorum_waiter.rs:94-99`); on `QuorumRejected`, `AntiQuorum`, `Timeout`, `FailedToReport` or `FailedQuorum` the builder returns `BuildOutcome::Failed` and "applies no changes to transaction pool" (`crates/batch-builder/src/lib.rs:420-430`); the next epoch's builder is built on the same pool (`inner.rs:107-116`). The claim "delayed, not lost" holds as read from code; not traced per transaction.
`RejectedBatchRepeat` and its message `batch {0} was already rejected in this epoch` cite #1774 on main (`crates/consensus/worker/src/network/error.rs:74-78`): "the fix's refusal" is right. Every pool switch off in both runs: right (report `:145`).
Issue: CLOSED 2026-11-12T21:10:28Z, no comments; the comment does not misstate it (its suggested fix: "Keep the rejected digests of the epoch in a bounded set, and refuse a repeat without validation").

Worth posting: low value.
It records that the fix's refusal is intended and harmless, which nobody asked about on a closed issue.
The one point a maintainer could act on is not in it: the expected refusal reaches the sender's log at error level (`quorum_waiter.rs:95-98`, 742 lines in r20261113-1630, 1,305 in r20261112-1520 per `census.md:118`).
Recommendation: do not post; if a record is wanted, post the corrected three sentences, optionally with that log-level point as a fourth.

Rule breaches: none (155 words, under the 150-500 rule only by the brief's own "three sentences" allowance).

Counts: 15 figures and claims checked / 14 matched (1 of them with weak wording) / 1 wrong / 0 untraceable.
