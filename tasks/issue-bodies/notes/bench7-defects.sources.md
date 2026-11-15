# Sources for the two bench 7 defect reports (not for posting)

Files: `tasks/issue-bodies/bench7-far-validator-batches-not-committed.md` (for Telcoin-Association/telcoin-network) and `tasks/issue-bodies/bench7-metrics-agent-network-relabel.md` (for Telcoin-Association/tn-node-deployment).

Abbreviations: R = `tasks/bench7-report-r20261115-1131.md` (line numbers as of this writing); FV = `benchmark/private/bench7-r20261115-1653/A10/far-validators.md` (rendered from `A10/far-validators.json`); C = `benchmark/private/bench7-r20261115-1653/A9/comparison.json`; L7a / L7b = `benchmark/private/bench7-r20261115-1131/A7/losses.json` / `benchmark/private/bench7-r20261115-1653/A7/losses.json`; G = `tasks/bench7/briefs/gate.md`.

## Report 1: far validators' batches

### Definitions and runs

- Far = validators 02 and 06, near = the other eight: R l.503; FV l.5.
- "certificates usually form among the last of the ten": FV l.47-48 (B0) and l.76-77 (B1), rank p50 of own certificate among the ten, far 8-10 in every filled cell, near 3.5-9; key `cert_rank_batch_headers.{not_committed,committed}.p50` (FV l.157-158). Run 7a has no rank (FV l.133).
- Four runs, builds, windows: FV l.18-23. 20,000 IOPS and the bench 6 pages: G l.13. Branches: `bench/bench6-2026-11` at 2df831e3c (u-common l.10); `bench/bench7-2026-11`, node commit 91a15e223 on main 45dce8947 (G l.14). Ten validators and one observer: G l.13.

### What happens / what it costs

- Bench 7 re-queue 50-61 rounds: R l.508 [C Q3F.07, Q3F.17]; FV l.42 (B0 7a 50/52, 7b 60/60), l.71 (B1 7a 58/50, 7b 60/61). Keys: L7a `far_generators.by_window.<W>.<NN>.batches.resent_round_minus_from_round.p50`; L7b `far_generators.by_window.<W>.<NN>.resent_round_minus_from_round_p50` (FV l.152).
- About 21 s, run 7b only: R l.508 [C Q3F.08, Q3F.18]. C values: B0 21.030 / 21.033 s, B1 21.057 / 21.389 s; key L7b `far_generators.by_window.<W>.<NN>.resent_s_since_from_round_p50`; run 7a has no key ("no key in this run").
- 12.9 to 61.4 s against 0.93 to 1.37 s: R l.47, l.509 [C Q3F.06, Q3F.16]. C values (ms): 7a B0 16140.3 / 20328.6 (near 925.8); 7b B0 44854.7 / 61434.8 (near 925.55); 7a B1 15797.3 / 15167.4 (near 1346.45); 7b B1 12880.3 / 14655.1 (near 1368.1); key in both runs `far_generators.by_window.<W>.<NN>.batches.first_proposal_to_execution_ms.p50`.
  Discrepancy for the checker: FV l.38, l.67 show run 7b's first-proposal-to-execution as "-" and FV l.148 says "not in run 7b's file"; C reads it from L7b at the key above, and R l.511 says the latency starts at the first own proposal on all four runs. The issue follows R and C (44.9 / 61.4 and 12.9 / 14.7).
- Bench 7 blast 1 seen p50 16.7-18.2 s against 2.11-2.12 s: R l.506 [V q3_far_validators B1.seen_p50_s]; FV l.59 (7a 18.2 / 16.7, near 2.11; 7b 16.6 / 17.7, near 2.12); key `far_generators.by_window.B1.<NN>.generator.seen_ms_p50` / 1000 (FV l.140).
- 2 to 10 % of the near median's rate in blast 0: R l.504 [V far_generators_b6 answer_by_blast].
- "The generators keep a fixed number of transactions in flight, so their rate follows the latency": FV l.91 ("the generator's window (16 in flight per sender) over the latency ... Little's law in the loss analyses"); FV marks the movers [inferred] (l.85).

### Evidence

- Table, every cell: R l.516-518, l.521, l.524-526, l.529 (the report's §4.5 table), cross-read with FV l.35, 37, 38/40, 45, 64, 66, 67, 74. Keys: `bh_cnc_share` = `own_headers.with_batches.certified_not_committed` / batch headers (FV l.144-145); `ppb_p50` (FV l.147; C Q3F.05, Q3F.15); `first_to_exec_p50_s` (FV l.148; C Q3F.06, Q3F.16); `committed_share_pct` from each run's validator-01 log, A2 `numbers.json tables['blast <i> mixed'].committed_share_ref_pct.<NN>` for bench 7 (FV l.155; C Q3F.09, Q3F.19). "-" for run 7a's blast 0 near share: R l.516, FV l.35.
- Every batch-carrying header certified in bench 7: R l.507 [V B0.bh_not_certified, B1.bh_not_certified]; FV l.33, l.62 (0 / 0 in both bench 7 runs and blasts). Not claimed for bench 6 (B1 has 0 / 3 and 3 / 5 not certified).
- Re-queue 41-60 rounds in bench 6: R l.519, l.527 (48/48, 60/60; 48/48, 58/41). 50-61 in bench 7: as above.
- Seconds 14.3-21.1 in bench 6, 21.0-21.4 in run 7b: R l.520, l.528 (16.8/16.8, 21.1/21.1, 21.0/21.0; 16.8/16.9, 20.3/14.3, 21.1/21.4).
- Near median count of commit-path re-queues 0 in every cell: R l.511 [V B0/B1.requeue_events_committed].
- 127 of 127 within 50 ms of the own `certificate committed` line, bench 6 light blasts: R l.535; FV l.12, l.106-115.
- Rank 9th or 10th at the median, not committed, blast 1, run 7b and both bench 6 runs; 7 or 8 of nine had proposed the next round in run 7b: R l.534 [V B1.cert_rank_nc_p50, B1.late_nc_p50]; FV l.76 (9/9, 9/10, 9/10), l.78 (7b 7/8).
- Order hold not involved: R l.536 [C Q3F.10, Q3F.20: 0 / 0 for both runs and blasts]; FV l.52, l.81; bench 6 blast 0 share 0.36-0.71: FV l.35. Hold switch and #1807: G l.45.
- No leader slot in blast 0 in any run; blast 1 bench 6 0.48-1.72 %, bench 7 0.00: R l.522, l.530; FV l.46, l.75.

### Where in the code (read at 33b727fce in `/home/drtnarg/coding/telcoin/tn-b7-p2`, `git show 33b727fce:<path> | sed -n ...`)

- `crates/consensus/primary/src/consensus/state.rs`: `:746` `own_rounds_committed`, `:748` `has_headers`, `:765-771` the loop over `committed_sub_dag.headers()` (`:766` `has_headers = true` for every header, `:769-770` own rounds pushed), `:809-814` `if has_headers { ... committed_own_headers().send((leader_commit_round, own_rounds_committed)).await ...`.
- `crates/consensus/primary/src/proposer.rs`: `:815-822` doc comment ("Headers that are skipped with no hope of being committed (proposed in a previous round)", `:816-817`), `:823` `fn process_committed_headers`, `:825-832` `max_committed_round` from the notice's own rounds (committed rounds removed from `proposed_headers` at `:829`), `:846-854` the walk (`take_while` at `:849`), `:857-862` `prepend_requeued(..., RequeueCause::Committed)`, `:929` `fn prepend_requeued`, `:940-947` the `info!` with `cause` and the message "digests resent", `:1238-1240` the select arm calling `process_committed_headers`. Not cited in the issue: `:920` the cancel path (`RequeueCause::Canceled`).
- "the same in both bench builds": FV l.121-122 (2df831e3c: proposer.rs `:910`, `:942`, `:956-959`, state.rs `:746`, `:770`, `:809-812`; 91a15e223: proposer.rs `:959`, `:999`, `:1027-1030`, state.rs the same lines, "lines 760-830 identical"); R l.535. I did not re-read those two commits.
- Difference from FV and R l.535 wording: they say the notice is sent "only when a committed sub-dag holds an own header (`if has_headers`)". At 33b727fce `has_headers` is set for any header (state.rs:766), so a notice can carry no own round; the proposer then takes `max_committed_round` 0 and the walk re-queues nothing (`:825-832`, `:849`). The issue states the code as read; the effect (a re-queue only on an own commit) is the same.
- "the walk learns that only from a later own commit": my reading of `:825-854`; the committed own rounds are removed first (`:829`), so the walk re-queues earlier own headers.
- Bench 7 adds bookkeeping on this path that neither gates nor delays the re-queue: R l.536; FV l.123 (not stated in the issue beyond "the same in both bench builds").

### What is not known

- Inferred parent step; parents and certificate arrival not logged: R l.537; FV l.132 (rank and lateness use each author's own `quorum reached` and the others' `header proposed`).
- Blast 1 committed share 2.12-3.50 % against 3.96-6.49 %, rounds overlap: R l.540. Storage engine and vote-handler rework together, round rate 2.83-2.84 against 2.80-2.81, no counter isolates: R l.541-542; G l.12. Leader slots a lead, not a finding: R l.543.

### Suggestions and how to tell more

- The three suggestions and the two logging items: G l.61. The field on `header proposed`: also R l.714. The verify criterion (one proposal per batch, latency near the near validators') follows the table's near columns; it is a criterion, not a result.

## Report 2: the metrics agent's `network` relabel

### The file

- Repository: `git -C tn-node-deployment remote get-url origin` = `git@github.com:Telcoin-Association/tn-node-deployment.git`.
- Path: `git -C tn-node-deployment ls-files | grep -i alloy` = `observability/config.alloy` (and its `.sha256`).
- Read in the working tree at d9446f7 (branch `devnet-docker-images` on the remote); the file's last commit is af97ae7 (`git log -- observability/config.alloy`), which `git branch -r --contains` places on `origin/main`. No fetch was made, so a later change to the file on main is not ruled out.
- Quoted rule: `observability/config.alloy:126-129`. The `chain` rule: `:121-124`. The comment naming `node-metrics.json`'s `$network` variable: `:104-105`. `prometheus.remote_write "central"` with only `endpoint { url, bearer_token }`, no queue options: `:137-142`. Scrape interval 15 s: `:97`.
- Byte-identical upstream copy: `tn-node-deployment/docs/testnet-addons.md:546` (`observability/config.alloy` (functional blocks) mirrors an upstream copy) and `:573-575` ("must be byte-identical to upstream"). The issue names neither the upstream repository nor its path.
- The benchmark harness's selectors on `network="bench"`: `benchmark/benchmark-blast.sh`, `benchmark/benchmark-deploy.sh`, `benchmark/bench-lib.sh` (grep), e.g. `max by (node) (tn_primary_round{network="bench"})`.

### What happens / cost

- Node's own `network` = `primary` / `worker-0`; about 910 pairs, about 110 with different values, `tn_network_*`: R l.191, l.637 [RF 7a] [RF 7b] [O 14:28Z].
- Collapse on every node, no per-network figure from Prometheus: R l.191-192, l.645.
- Idle check stopped all three runs on a healthy node: R l.64, l.620, l.691.
- Figures from Prometheus cover fewer validators: R l.167.

### Read on a live node

- Validator-09's agent config read during run 7a; scrape, set `network`, remote-write: R l.635-636 [O 14:28Z].
- Error text: R l.638 [O 12:40Z] (quoted with its ellipsis as the report has it).
- About 737 samples every 15 s, 102,244 of 658,244 (15.5 %); the agent restart did not help; validator-08 three times at start-up then never: R l.643 [O 12:40Z]. Restart time 12:37:50: R l.168 [RF 7a].

### Measured on the three fleets

- Table rows: R l.647-654; also R l.165-166 (validator-09's series), l.175-179 (run 7b).
- The first attempt is not published: G l.56; R l.130 (section "The lost first attempt at run 7b").
- Idle stops: 12:30:02 (validator-09) and 17:45:57 (validator-05): R l.114; 16:04:23: R l.608.
- Validator-05 killed and restarted by design: G l.56; series back after its restart: R l.642, l.652.
- Not new in bench 7: R l.193 [RF 7a].

### Explanation (inferred)

- Second sample of a pair dropped inside one request; straddling pair rejects the whole batch on every scrape; series order per process: R l.639-641 [inferred] [O 14:28Z]. The 2,000-sample batch size is the report's (l.640, inferred there); that the file sets no queue options is from config.alloy:137-142.
- A series registered mid-run can move the boundary: R l.659 (given there as the reason the sampler covers all nodes).

### What stood in

- Endpoint keeps both labels: R l.192, l.662. Run 7b every 60 s, 94 rounds, about 5,100 series a node: R l.182, l.660. Run 7a end-of-run snapshots of validators 09 and 08: R l.169, l.663. Within about 1 % over whole windows, up to about 5 % in 300-s buckets: R l.185.

### The suggested fix

- My own proposal, checked against the file's rule syntax (`:106-134`). That a `replace` rule with `source_labels = ["network"]` copies the value with the default regex `(.*)` and replacement `$1`, and that an empty result sets no label, is Prometheus relabel behaviour as Alloy's `prometheus.relabel` applies it: from knowledge, not read from a source here, and not tested.
