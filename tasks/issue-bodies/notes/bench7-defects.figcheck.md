# Figure-check FC-DR: the two bench 7 defect reports

FIX

No figure is wrong and no error changes a conclusion; 12 statements are weaker in their source than in the text (5 in report 1, 7 in report 2), each with a replacement below.

## Counts

- Report 1, `tasks/issue-bodies/bench7-far-validator-batches-not-committed.md`: 106 items checked (48 table cells, 58 other figures, ids, links and code statements); 99 match, 0 wrong, 0 untraceable, 7 weak (in 5 entries).
- Report 2, `tasks/issue-bodies/bench7-metrics-agent-network-relabel.md`: 73 items checked (18 table cells, 55 others); 66 match, 0 wrong, 0 untraceable, 7 weak.
- Rule breaches: none in either text (no private path, no unit name, no host or person name, no tool or assistant attribution; bench 6 runs named by id; suggestions marked as suggestions, none claimed to work).

## Report 1: what was checked and holds

- Every table cell (l.20-27) equals the report's §4.5 table (R l.516-518, 521, 524-526, 529) and V `q3_far_validators.summary_rows` / FV l.35-45, l.64-74; the bench 7 latency cells equal C Q3F.06 / Q3F.16 (7a 16140.3 / 20328.6, near 925.8; 7b 44854.7 / 61434.8, near 925.55; 7a 15797.3 / 15167.4, near 1346.45; 7b 12880.3 / 14655.1, near 1368.1 ms).
- One latency start in all cells: run 7b's L7b `far_generators.by_window.<W>.<NN>.batches.first_proposal_to_execution_ms` carries `start: "first own `header proposed` holding the batch"`; run 7a's key is the same; bench 6 is FV's "first proposal -> own execution".
- l.10 16.7-18.2 s: the low end is run 7b's 02, `seen_ms_p50` = 16650 ms (V 16.65), so 16.7 rounds half-up; FV l.59 prints 16.6 (half-even); match.
- l.7, l.30 delays: 50-61 rounds (C Q3F.07 50/52, 60/60; Q3F.17 58/50, 60/61), 21.0-21.4 s (C Q3F.08 21.030/21.033, Q3F.18 21.057/21.389), bench 6 41-60 rounds and 14.3-21.1 s (FV l.42-43, l.71-72): values match (label: W1).
- l.31-33, l.35, l.53, l.55: near commit-path re-queue count 0 in every cell; 127 of 127 within 50 ms (FV l.108-115 sum 127); rank 9 or 10 not committed in blast 1 (b6r2 9/9, b6r3 9/10, 7b 9/10) and 7 or 8 of nine (7b 7/8); held 0 (C Q3F.10, Q3F.20); committed share 2.12-3.50 % against 3.96-6.49 %; leader slots 0.00 against 0.48-1.72 %: all match.
- l.15: run ids, page links (gate.md l.13), branches and commits (u-common l.10, gate.md l.14), ten validators and one observer (bench 6 report l.16; gate.md l.13): match. #1807 exists and is open ("A sealed transaction leaves the pool and the RPC, …"), the issue the order hold addresses.
- Code at 33b727fce, every cite re-read: state.rs:765-771 (loop over `committed_sub_dag.headers()`, own rounds pushed at :769-770), :809-814 (`if has_headers` → `committed_own_headers().send((leader_commit_round, own_rounds_committed))`); proposer.rs:1238-1240 (select arm → `process_committed_headers`), :823 (fn), :825-832 (`max_committed_round` 0 when the notice holds no own round; committed rounds removed at :829), :846-854 (walk, `take_while` at :849), :857-862 (`prepend_requeued(…, RequeueCause::Committed)`), :940-947 (`info!` "digests resent"), :815-822 (doc comment, quote at :816-817): all true as stated.
- The notice condition: `has_headers = true` is set at state.rs:766 for every header of a committed sub-dag, not only own ones, so a notice is sent whenever any header was committed and may carry no own round; the proposer then re-queues nothing (max 0, :825-832, :849). The issue's l.41 ("whenever the sub-dags hold any header") is right as written; the report's l.535 and FV l.13, l.122 ("only when a committed sub-dag holds an own header") are not, at 33b727fce or at either bench build.
- "The same in both bench builds" (l.39): state.rs lines 746, 748, 766, 770, 809, 812 identical at 2df831e3c and 91a15e223; proposer.rs fn / `take_while` / `RequeueCause::Committed` / select arm at :910 / :942 / :959 / :1438 (2df831e3c) and :959 / :999 / :1030 / :1658 (91a15e223): match.
- l.6 "only through the commit-path re-queue": the other re-queue path (proposer.rs:920, `RequeueCause::Canceled`) handles uncertified own headers (:905-914); match.
- Inference marks: l.50-51 mark the parent step as inferred and say parents and certificate arrival are not logged (R l.537, FV l.132): match.

## Report 1: weak

1. l.7 and l.30, the re-queue delay's label.
   - Text l.7: "In bench 7 the re-queue came a median 50-61 rounds after the header that carried the batch (about 21 s in the run that records seconds)."
   - Text l.30: "The re-queue came a median 41-60 rounds after the carrying header in bench 6 and 50-61 in bench 7; in seconds, 14.3-21.1 s in bench 6 and 21.0-21.4 s in r20261115-1653."
   - Source: the delay is per re-queue event, counted from its `from_round`, the round of the oldest own header it returns (proposer.rs:927-928 at 33b727fce; FV l.121 "from_round = the oldest such header"; keys L7a `far_generators.by_window.<W>.<NN>.batches.resent_round_minus_from_round.p50`, L7b `…resent_round_minus_from_round_p50`, `…resent_s_since_from_round_p50`); a re-queue can return several headers (validator 02 in run 7a's blast 1: 114 certified, not-committed batch headers against 16 commit-path re-queues, FV l.63, l.70), so a batch in a later header waited less.
   - Replacement l.7: "In bench 7 a commit-path re-queue came a median 50-61 rounds after the oldest own header it returned (about 21 s in the run that records seconds)."
   - Replacement l.30: "Counted from the oldest own header each re-queue returned, the re-queue came a median 41-60 rounds later in bench 6 and 50-61 in bench 7; in seconds, 14.3-21.1 s in bench 6 and 21.0-21.4 s in r20261115-1653."
2. l.11, scope and an unmarked inference.
   - Text: "The generators keep a fixed number of transactions in flight, so their rate follows the latency: in the first light blast the far generators landed 2 to 10 % of the near median's rate."
   - Source: 2 to 10 % is bench 7's (V `far_generators_b6.answer_by_blast.0.far_share_of_other8_rate`: 7a 0.099 / 0.062, 7b 0.025 / 0.020); bench 6's blast 0 is 2.9-11.9 % (0.114 / 0.119, 0.033 / 0.029); "rate follows the latency" is marked [inferred] in FV l.85 and l.91 (16 in flight per sender, Little's law).
   - Replacement: "The generators keep a fixed number of transactions in flight (16 per sender), so their rate is expected to follow the latency (inferred, not measured separately): in bench 7's first light blast the far generators landed 2 to 10 % of the near median's rate."
3. l.43, code in code font that is not the code's text.
   - Text: "`:846-854` walks `proposed_headers` in round order with `take_while(header_round <= max_committed_round)`; …"
   - Source: proposer.rs:849 at 33b727fce reads `.take_while(|(header_round, _)| **header_round <= max_committed_round)`.
   - Replacement: "- `:846-854` walks `proposed_headers` in round order with `.take_while(|(header_round, _)| **header_round <= max_committed_round)`; `:857-862` puts the digests of every header it passed back at the front of the queue (`prepend_requeued`, `RequeueCause::Committed`), logged as `digests resent` (`:940-947`)."
4. l.46, "rare".
   - Text: "… the walk learns that only from a later own commit, and a far validator's own commits are rare (the committed share above)."
   - Source: the share is lower, not rare in count: committed share 0.92-6.49 % against the near median's 11.0-12.3 % (the issue's own table); in bench 6's light blasts 02 and 06 had 59-224 own commit events a window with a p50 gap of 2 rounds and a p95 gap of 16-58 rounds (FV l.108-115).
   - Replacement: "The doc comment (`:815-822`) calls such headers "skipped with no hope of being committed"; the walk learns that only from a later own commit, and a far validator's certificates are committed less often than a near validator's (the committed share above) and with long gaps (in bench 6's light blasts the 95th-percentile gap between two own commits of 02 or 06 was 16-58 rounds)."
5. l.54, the list of what changed.
   - Text: "Bench 7 changed the storage engine and took in the upstream vote-handler rework together, the round rate barely moved (2.83-2.84 own headers per second against 2.80-2.81), and no counter separates the candidates."
   - Source: gate.md l.12 (the storage engine, the upstream vote-handler rework, the order hold and the run's shape moved together between bench 6 and bench 7); R l.542; the rates are 02's and 06's (V `summary_rows` B1 `headers_per_s`: bench 7 2.84 / 2.84, 2.83 / 2.83; bench 6 2.81 / 2.81, 2.80 / 2.80).
   - Replacement: "Between bench 6 and bench 7 the storage engine, the upstream vote-handler rework, the order hold and the run's shape changed together; the round rate of 02 and 06 barely moved (2.83-2.84 own headers per second against 2.80-2.81), and no counter separates the candidates."

## Report 2: what was checked and holds

- Repository `git@github.com:Telcoin-Association/tn-node-deployment.git`; path `observability/config.alloy` (with its `.sha256`); the quoted rule is :126-129 verbatim, tabs included; the file's last change is af97ae7 on HEAD and on the local `origin/main` ref, no difference between them.
- The file: :98 the scrape forwards to `prometheus.relabel.tn`; :104-105 the comment on node-metrics.json's `$network` variable; :121-124 the `chain` rule with `sys.env("TN_CHAIN")`; :137-142 `prometheus.remote_write "central"` with only `endpoint { url, bearer_token }`, no queue options; :97 scrape interval 15 s; docs/testnet-addons.md:546 maps the file's functional blocks to an upstream copy and :573-575 require them byte-identical: every statement of l.5, l.51, l.74, l.77, l.80 about the file matches.
- The suggested rule (l.66-71) is a `rule` block of the same kind as the file's own (same component, tab indentation, aligned `=`), with `source_labels` (a list of strings) and `target_label`; like the file's rules it relies on the default action; the text places it before the `network` rule. The fix is marked "(not tested)" in its heading and the other way (l.76-78) as an option; the harness selectors on `network="bench"` exist (benchmark-blast.sh 1, benchmark-deploy.sh 2, bench-lib.sh 1).
- The live node (l.25-29) against the run log 12:40Z and 14:28Z entries (tasks/checkpoint-bench7-orch.md l.1020-1038, l.1119-1135) and R l.635-643: the pipeline read on validator-09; the error text `duplicate sample for timestamp …; overrides not allowed: existing 0, new value 1` (the log's own wording after "HTTP 400 …", l.1025-1026); about 737 samples every 15 s; 102,244 of 658,244 = 15.5 %; the agent restart at 12:37:50 that did not help (l.1032-1033); validator-08 three times at start-up and then never: all match.
- About 910 pairs, about 110 with different values, `tn_network_*`, every node, not new (l.1030-1031, R l.191-193, l.637, l.645): match.
- The table (l.37-42) equals R l.649-654 and l.165-179 row by row: validator-09 `up`, `scrape_*` and thirteen named series (R l.166 names 13); the earlier attempt's 01 and 05 three must-haves each, 09 two, 09 and 10 `up`; run 7b's validator-01 four series, validator-05 three until 18:40:00, validator-08 six series stopping 18:29:45, the observer's four stopping 18:58:45: match.
- Times 12:30:02, 16:04:23, 17:45:57 (R l.114, l.608); validator-05's series back after its restart (R l.642, l.652); the explanation (l.50-54) under "(inferred, not reproduced)" as R l.639-641 and l.659 mark it; 94 rounds, about 5,100 series, every 60 s; run 7a's two end-of-run snapshots (R l.182, l.660, l.663): match.

## Report 2: weak

6. l.17, "for as long as the node process runs".
   - Text: "On some nodes the remote write also has one batch rejected on every scrape, and the series in that batch are missing from Prometheus for as long as the node process runs."
   - Source: validator-08 in r20261115-1131 lost a batch three times at start-up and then never (run log 12:40Z l.1026; R l.643); in r20261115-1653 validator-08's and the observer's series stop mid-run (R l.178-179, l.653-654); only validator-09 (whole run) and validator-05 (until its restart) fit the sentence.
   - Replacement: "On some nodes the remote write also has one batch rejected on every scrape, and the series in that batch are missing from Prometheus while that lasts: on one validator for a whole run, on others from mid-run, on one only for three scrapes at start-up."
7. l.20, what the idle check did.
   - Text: "The benchmark's idle check halts a run when a node's `up` is missing, and it stopped all three runs on a healthy node."
   - Source: R l.620 ("The idle check stopped the chain in every run, each time on a missing `up` series while modes and switches were in order, and the blast was launched by hand"); R l.64; the earlier attempt stopped on two nodes, 09 and 10 (R l.650); every blast went on by hand (R l.114, l.608).
   - Replacement: "The benchmark's idle check stops its step sequence before the blast when a node's `up` is missing; it did so on all three fleets, each time on nodes that were otherwise healthy, and each blast was then launched by hand."
8. l.33, the earlier attempt's run id.
   - Text: "The fleets of r20261115-1131, of an earlier attempt at [r20261115-1653](…) that is not published, and of r20261115-1653; one run each, times in UTC."
   - Source: R l.132 (the first attempt is `r20261115-1450`, lost when its login expired) and l.134 (not a bench 7 run); the text gives the lost attempt the published run's id and no id of its own (the table row l.38 and l.44 then say only "earlier attempt").
   - Replacement: "The fleets of r20261115-1131, of an earlier, lost attempt at the adaptive run (r20261115-1450, not published), and of [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/); one run each, times in UTC."
9. l.44, "stopped the chain".
   - Text: "The idle check stopped the chain at 12:30:02 (`up` missing for validator-09), at 16:04:23 (the earlier attempt) and at 17:45:57 (`up` missing for validator-05)."
   - Source: "the chain" in R l.114 and the run log is the harness's step chain; the blockchain kept running (run log 12:40Z l.1023: validator-09's rounds in line with the fleet); a node maintainer reads "the chain" as the blockchain; the earlier attempt's stop was on `up` missing for validators 09 and 10 (R l.650).
   - Replacement: "The idle check stopped the benchmark's step sequence (the blockchain kept running) at 12:30:02 (`up` missing for validator-09), at 16:04:23 (the earlier attempt; `up` missing for validators 09 and 10) and at 17:45:57 (`up` missing for validator-05)."
10. l.58, "both labels".
    - Text: "The node's own metrics endpoint keeps both labels."
    - Source: R l.192 (the snapshots and samples "keep both labels", the two `network` values) and l.662 ("the node's own `network` label is intact in them"); the endpoint has no chain label, so "both labels" reads as the node's and the chain's.
    - Replacement: "The node's own metrics endpoint keeps its `network` label, so both series of each pair are there."
11. l.60, the stand-in's agreement.
    - Text: "Where Prometheus held a validator whole, the samples agreed with it within about 1 % over whole windows and up to about 5 % in 300 s buckets."
    - Source: R l.185 and l.667: the engine figures (executed tx/s, busy time, persist mean; seven validators; run r20261115-1653 only); R l.667 a gauge's average (queued outputs) does not agree (0.0000 to 2.0875), R l.669 the vote stage's pre-lock wait mean differs by 19.2-96.5 % and its lock mean by up to 100 %.
    - Replacement: "Where Prometheus held a validator whole in r20261115-1653, the engine figures taken from the samples (executed transactions per second, busy time, persist mean) agreed with it within about 1 % over whole windows and up to about 5 % in 300 s buckets; a gauge's average and the vote stage's wait means did not agree as well."
12. l.73, relabel semantics stated as fact.
    - Text: "With the default `replace` action this copies `primary` or `worker-0` to `tn_network` and adds nothing to series without a `network` label (an empty value sets no label)."
    - Source: none of the allowed sources; the writer's note (bench7-defects.sources.md l.98) says it is from knowledge and not tested; the heading's "(not tested)" covers the fix, but this sentence states the behaviour as known.
    - Replacement: "With the default `replace` action (regex `(.*)`, replacement `$1`) this should copy `primary` or `worker-0` to `tn_network`; for a series without a `network` label the result is empty, and as we read Prometheus's relabelling an empty result sets no label (not tested)."

## Notes for the orchestrator (not errors in the texts)

- The bench 7 report's l.535 and FV l.13 / l.122 misstate the notice condition (see "The notice condition" above); the issue is right; correct the report if it is republished.
- FV l.38, l.67, l.148 say run 7b's loss file has no first-proposal latency; it has one (`first_proposal_to_execution_ms`, start "first own `header proposed` holding the batch"), the figure the report and the issue use.
- Run 7b's blast 0 first-proposal medians rest on 7 (02) and 5 (06) batches; the 61.4 s top of l.9's range is a median of five; the writer may add the batch counts (bench 7 cells: 5 to 220 batches).
- Report 1's table labels the blasts "0" and "1" while the prose says "first" and "second light blast"; a header "light blast (0 = first, 1 = second)" would join them.
- Report 2's "on main" (l.5) is checked against the local `origin/main` ref only (no fetch allowed); a fetch before posting would rule out a later change.
- Report 2's error quote omits the log's "HTTP 400 …" prefix; adding it would help a maintainer search the agent's logs.
