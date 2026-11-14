# Figure-check FC-UI2: the three new bench-6 issue bodies

Checked 2026-11-14 (Sat Nov 14 03:54 UTC) against the writer's sources, the e2e logs under `tn-b6-u2/target/tmp/st-e-run{1..5}*`, the analysis files the notes cite, and the code at 45dce8947 (read with `git show 45dce8947:<path>`; the b7 worktree HEAD is 45dce8947).
Line numbers below are at 45dce8947 unless a file says otherwise.

## 1. `tasks/issue-bodies/bench6-restart-between-closing-block-and-record.md`

Verdict: FIX

Reachable on main: yes, by code.
On restart the committee comes from the canonical tip (`start_epoch.rs:239`, via `node.rs:998-999`); with epoch 0's closing block executed that committee is epoch 1's (the bench-6 log shows `entered=1 closing_block=38`).
The dummy record 0 is memory-only (`epoch_records.rs:2188-2195`), so after a restart `contains_epoch(0)` is false (`:2479-2487`), and `ensure!(committee.epoch() == 0)` at `node.rs:1320-1325` fails.
Nothing writes a record between `run()`'s start (`node.rs:868`) and the guard: only reads (`:1016`, `:1294` re-vote of an already stored record), and `try_restore_state` (`:1860`) touches no record.
A stop at a later epoch's close passes the guard because record 0 is durable by then, and `recover_previous_epoch_record` (`close_epoch.rs:559`, called at `run_epoch.rs:238`) rebuilds record N at the entry into N+1.
The guard at bench-6 `node.rs:1293-1298` (2df831e3c) is identical to main's, so the bench-6 reproduction transfers by code.
One confirming run: `test_restarts_cohort_exits_in_epoch_boundary_window` with the hook at epoch 0 (expect every node to exit with the error).

Errors:
1. Title, "can never start again": not true as an absolute on main.
   Main ships `telcoin-network db reset-execution --force`; `crates/telcoin-network-cli/README.md` (at 45dce8947, the `db reset-execution` paragraph) says it moves `db/`, `static_files/` and `restored-state-floor` aside "so the next start rebuilds it from genesis", and "the rebuild replays epoch 0 from the node's own packs".
   By the code, that start reads the genesis committee (epoch 0), passes the guard, seeds the dummy, replays epoch 0 and writes record 0 at its close (`close_epoch.rs:418-432` builds over a dummy).
   Moving the chain data aside and syncing as a new node is the other recovery. Neither was tried.
   Replacement title (115 characters): `A node stopped after executing epoch 0's closing block and before writing record 0 cannot restart from that datadir`
   Add after "We did not try to recover the failed datadirs; by the code, nothing writes a record before the check, so every later start fails the same way." the sentence: `By the code, an operator can still recover such a node, though we did not try: \`telcoin-network db reset-execution --force\` makes the next start rebuild execution from genesis, where the committee is epoch 0's, so the check passes and the replay of epoch 0 writes record 0 at its close; moving the chain data aside and syncing the node as a new one also works.`

Not traceable: none.

Weak:
1. "a SIGTERM, a crash or a power loss inside it leaves a datadir that cannot start": the reproduction is a graceful stop through the hook only (`run_epoch.rs:510-519`).
   For a crash or power loss the outcome depends on whether the executed closing block was already on disk; `close_epoch` (`run_epoch.rs:819-840`) waits for execution, not for a durable write, and the sources do not show it either way.
   Replacement: `A SIGTERM inside it leaves a datadir that cannot restart; by the code a crash or a power loss does too, once the executed closing block has reached disk.`
2. The text never says the reproduction did not run on main; the "Where in the code" section reads as if it did.
   Add at the end of the first Evidence paragraph: `We have not run it on main; the check and its place before the record sync are the same there as in the build we ran.`
3. "One of them logged `test hook: … epoch=0`": all 8 logged it (one per `node{2,3}-run0.log` in runs 1 and 2); "For example, one of them" reads better. Optional.

Rule breaches: none (no unit names, private paths, hosts, nicknames or attribution).
Words: 878 by prose count (899 by `wc -w`).

Matched, each opened: the error string (`node.rs:1322`; 8 of 8 `node{2,3}-run1.log` in `st-e-run{1,2}-logs/missed_record_round_{adaptive,always}`); 8 hook lines `epoch=0` in the `run0` logs; 12 of 12 `re-deriving it locally … previous_epoch=1` in runs 3-5 with 12 hook lines `epoch=1`; runs 3-5 all PASS (`tasks/checkpoint-bench6-ST-E.md` lines 12-14); `entered=1 closing_block=38` at 21:23:27.281992Z; start 21:23:27.255956Z to the error 21:23:27.296373Z = 40.4 ms; four validators and 120-s epochs (`epoch_close_forms.rs:163`, handoff line 151); `test_hooks.rs:185`; `run_epoch.rs:510-519`, `:238`; `start_epoch.rs:239`; `node.rs:998`, `:1320-1325`, `:1326`, `:1334`, `:772`; `epoch_records.rs:2188-2195`, `:2479-2487`; `close_epoch.rs:559`, `:569-571`, `:628-643`, `:495-499`, `:527-529`, `:384-385`, `:515-518`; `restarts.rs:865-868` ("It lasts about 200 ms per boundary"), `:899`, `BOUNDARY_WINDOW_EPOCH = 6` at `:745`; `eject.rs:526-532`, `:835-841` with "pre-existing product issue", tests at `:450` and `:793`; #1015 closed 2026-07-27 with the matching title, fixed by PR #1021 "write and persist the epoch record on all three epoch-close arms".

Counts: 36 checked / 33 matched / 1 wrong (title) / 0 untraceable / 2 weak.

## 2. `tasks/issue-bodies/bench6-rejoin-under-sustained-load.md`

Verdict: FIX

Errors:
1. Title, "it replays no faster than the network": contradicted by the body's own table.
   In r20261113-2118 the follower replayed 1.305 outputs/s against the network's 1.288 and gained about 4.5 outputs a minute (`benchmark/private/bench6-r20261113-2118/A3a/recovery.md` lines 8-9, 75-76).
   It also states a rate result for main, where the rate under load was not measured.
   Replacement title (119 characters): `A validator restarted under sustained load stayed inactive until the load ended: it replays at about the network's rate`
2. Table, row r20261114-0000, column "outputs behind: open-epoch entry, end of load": the text says `429, 425`.
   425 is the 02:53 minute, before the mixed phase ended at 02:53:52; the other three rows take the minute of the cooldown end, after the mixed end: r20261113-1351 15:57 = 513 (15:56 = 489), r20261113-1630 18:37 = 515 (18:36 = 508), r20261113-2118 23:26 = 402 (23:25 = 412).
   The same minute in r20261114-0000 is 02:54 = 466 (`benchmark/private/bench6-r20261113-2118/A3a/data/r3b-prom-recovery.json` `minutes[]`; cooldown end 02:54:28 from `recovery.md` line 17 and the `replay_loaded` window 02:37:45-02:54:28).
   Replacement cell: `429, 466`
3. "its RPC refused every transaction submission with `-32603 validator is inactive; retry another endpoint`": the quoted string is neither the code's nor the log's.
   Main returns code `INTERNAL_ERROR_CODE` (-32603) with the message `validator is inactive; retry another endpoint` (`crates/tn-reth/src/rpc_fee_cap.rs:72-76`); the generator logged `error code -32603: validator is inactive; retry another endpoint` (`benchmark/private/bench6-r20261113-1351/A1/kpis.md` line 158).
   Replacement: `its RPC refused every transaction submission with error code -32603 and the message \`validator is inactive; retry another endpoint\`;`

Not traceable: none.

Weak:
1. "They are not on main and let the network run at its validators' execution rate; we did not measure how far below that rate main runs." presupposes that main runs below that rate; nothing in the sources measured main.
   The switches are absent at 45dce8947 (`vote_queue_fix`, `quorum_exec_block`: no match in `crates/`).
   Replacement: `They are not on main and let the network run at its validators' execution rate. We have not measured main under this load, so whether a restarted validator gains on main's network is not known.`
2. "the committee ran one validator short from the kill to the promotion": in r20261114-0000 validator-02 was also demoted for 4m00.0s (02:51:51.4 to 02:55:51.7, `bench6-r20261113-2118/A3a/recovery.md` line 20).
   Replacement: `the committee ran at least one validator short from the kill to the promotion, 21m30.2s to 30m00.0s;`
3. Column header "generator 05 landed nothing for": the figures count from the kill to the end of the mixed phase (`bench6-r20261113-1351/A1/kpis.md` line 160; `bench6-r20261113-2118/A1/kpis.md` lines 127, 221).
   Replacement header: `generator 05 landed nothing, kill to end of load`
4. "roughly 90 more minutes of load to reach the window" is inferred arithmetic in the source (`bench6-r20261113-2118/A3a/recovery.md` line 10, "inferred arithmetic"); add `(inferred from that slope)`.
5. "#1513 (closed) replaced the exact-head rule with the 20-round window": an issue does not replace a rule. Replacement: `#1513 (closed): its fix replaced the exact-head rule with the 20-round window: enough for a node a few outputs behind, not hundreds.`
6. Optional: "in the three runs where we read it": `r3b-prom-recovery.json` holds `v05_queued_outputs` too (8 in every inactive minute but 02:36, 02:38 and 02:59), so "in all four runs" is supported by the data, though no analysis text states it.

Checked and matched, each opened:
- Start to `CvvActive` 16m40.8s, 16m30.1s (`bench6-r20261113-1351/A3a/recovery.md` line 16), 17m39.6s and 25m00.1s (`bench6-r20261113-2118/A3a/recovery.md` lines 5, 14); kill to `CvvActive` 21m30.2s to 30m00.0s (lines 15 and 14 of the two files).
- One promotion per restart, held; first certified header +0.76 s, +0.93 s, +0.52 s, +0.61 s (R2 table rows 16:02:40.397 and 18:42:50.743, R3 rows 23:31:39.129 and 03:00:22.457).
- Two records missed after each kill: epochs 4 and 5 (r20261113-1351, -1630, -2118), 6 and 7 (r20261114-0000).
- 402 to 605: the minimum and maximum of every per-minute `gap` while the node read `cvv_inactive`, across the four `*-prom-recovery.json` files (402 at 23:26 in r20261113-2118, 605 at 03:00 in r20261114-0000).
- Reads served from its own head: the generator's scanner reads from its own validator and saw pre-kill landings after the restart (`A1/kpis.md` lines 213, 322); no read method is wrapped (`rpc_fee_cap.rs:7-13`).
- Entry distances 452, 470, 438, 429 (state sync's distance at the open-epoch entry); end-of-load 513, 515, 402; rates 1.332/1.409, 1.180/1.243, 1.305/1.288, 1.063/1.091 (each over the entry-to-cooldown-end window); outages 949 s, 899 s, 1,008 s, 1,374 s.
- `round_gap` 802 to 1,144 rounds, window 20; queued outputs 8; 4.5 outputs a minute; promotion 5m01.9s, 5m31s, 5m02.8s, 5m54s after the cooldown end; 580-593 tx/s; first refusal 10 s and 9 s after the starts, last refusal 4 s and 3 s before the mixed ends; ten validators in ten regions; SIGKILL then start 300 s later.
- Code at 45dce8947: `subscriber.rs:136-149`, `:130-132`, `:173-192`; `primary/mod.rs:52` (`MAX_GC_DEPTH = 50`), `:87-89` (`gc_activity_window / 2`, with `GC_ACTIVITY_BUFFER = 10` at `:64`, so 20), `:217` (`MAX_COMMIT_RUN_AHEAD_ROUNDS = 1_000`); default `gc_depth` = `MAX_GC_DEPTH` (`crates/config/src/node.rs:348-350`); `state-sync/src/lib.rs:616-624`; `restarts.rs:1873-1888` (asserts "the load stopped before the lagged validator rejoined" at `:1959-1960`), `spawn_load` at `:1846` (one key, one thread, sequential sends); `rpc_fee_cap.rs:57-62`; `test_hooks.rs:117`.
- "the rejoin rule is unchanged from the bench-6 build": `git diff 2df831e3c 45dce8947` is empty for `subscriber.rs` and `primary/mod.rs`; `state-sync/src/lib.rs` changed only `get_missing_consensus` (the restart replay), not the follower's execution wait.
- #1513 closed 2026-11-04 ("Inactive validator cannot rejoin consensus while the chain is under load"); #1514 closed ("Transaction forwarding still targets inactive validators"); #1801 closed 2026-11-12, its closing comment names #1818 as the fix, carried to main by a3df64830 (an ancestor of 45dce8947); #1818 merged 2026-11-10 into the staging branch; bench 6 ran with it (the grace-hold metric exists in its runs). The difference from #1801 (a promotion that failed and looped, against a wait before one promotion that held) is stated correctly.

Rule breaches: none. Words: 868 by prose count (934 by `wc -w`, table pipes included).

Counts: 73 checked / 70 matched / 3 wrong / 0 untraceable / 5 weak (plus one optional).

## 3. `tasks/issue-bodies/bench6-newepoch-event-not-readable-over-rpc.md`

Verdict: FIX

Errors:
1. Title, "the docs do not say how to follow epochs instead": `docs/src/epoch-boundaries.md:116-119` names `extra_data` at the epoch boundary and says "The `extra_data` value serves as a public indicator that the epoch closed at this block."
   Replacement title (83 characters): `The registry's NewEpoch event never reaches eth_getLogs, and the docs do not say so`
2. Body line 14, "neither it nor `docs/src/rpc-methods/eth/eth_getlogs.md` says that the registry's events are never served, or how to follow epochs without them": the second half is wrong for the same reason.
   Replacement: `\`docs/src/epoch-boundaries.md:101\` says system calls are "invisible to users" and that their effects show only in state and in header fields, and \`:116-119\` names \`extra_data\` as the public marker of an epoch close; but neither it nor \`docs/src/rpc-methods/eth/eth_getlogs.md\` says that the registry's events are never served, and neither names the other reads below.`

Not traceable: none.

Weak:
1. "The same holds for the other registry events when the closing calls emit them (`ValidatorActivated`, `ValidatorExited`, `ValidatorSlashed`)": the list reads as complete, but the closing calls also emit `RefundQueued` and `ValidatorStakeVersionUpgraded` (`_processStakeVersionQueue`, `tn-contracts/src/consensus/ConsensusRegistry.sol:287`, `:297`, called from `concludeEpoch`) and `NextCommitteeSizeUpdated` (`_updateValidatorQueue`, `:1348`).
   Replacement parenthesis: `(among them \`ValidatorActivated\`, \`ValidatorExited\`, \`ValidatorSlashed\`, \`ValidatorStakeVersionUpgraded\` and \`RefundQueued\`)`; in the fix section, `a note on the other events the closing calls emit` in place of the three names.
2. "`getEpochInfo(E + 1).blockHeight` from the registry is the first block of epoch E + 1 … `tn_getEpochInfo` serves the same, but the contract keeps only a ring buffer": read before epoch E + 1 begins, a future epoch's `blockHeight` is 0 (`ConsensusRegistry.sol:421`, "Block height is unknowable ahead of time and remains 0"), and the ring buffer (current − 3 to current + 2, `:412-413`) limits the `eth_call` read as much as `tn_getEpochInfo`.
   Replacement: `\`getEpochInfo(E + 1).blockHeight\` from the registry, read once epoch E + 1 has begun (before that it reads 0), is the first block of epoch E + 1, so the closing block of E is \`blockHeight - 1\`, and \`getCurrentEpoch()\` by \`eth_call\` reads E at the block before it and E + 1 at it. The contract keeps only the epochs from three before the current one to two after it, and older requests revert, at the head by \`eth_call\` and by \`tn_getEpochInfo\` alike (\`crates/execution/tn-rpc/src/rpc_ext.rs:210-211\`).`

Checked and matched, each opened: `IConsensusRegistry.sol:123` (`event NewEpoch(EpochInfo epoch);`, submodule 10cc12b as pinned at 45dce8947); `ConsensusRegistry.sol:127-129` (emit in `concludeEpoch`, `onlySystemCall` at `:101`, `blockHeight = block.number + 1`); `crates/tn-reth/src/evm/block.rs:421-426` (no receipt "matching Ethereum", neither receipts root, `logs_bloom` nor `eth_getLogs`, "would change `receipts_root` and be a hard fork"); `system_calls.rs:415-422` (`log_registry_event`, target `engine`, field `event`); `epoch-boundaries.md:101` quote; `eth_getlogs.md` silent on system calls; `block.rs:2118` and `config.rs:209-222` (0 or 32 bytes, the epoch seed); `header.rs:255-257` (`(epoch << 32) | round`) and `output.rs:217-218` (the leader's nonce); `rpc_ext.rs:174-180`, `:210-211`; `epoch.rs:22-38`.
Evidence: the test asks node 0 (`epoch_close_forms.rs:798`, `:999-1004`, filter `address` + `fromBlock` = `toBlock`); `st-e-run{3,4,5}.log` each report 10 distinct closing blocks, all `(0 registry logs by eth_getLogs)`: 30 of 30; the four reads are asserted on every node (`:791` loop; `:816-821`, `:829-833`, `:851-853`, `:889-910`) and all tests passed in runs 3-5.

My view on filing, in one line: marginal; the behaviour is by design and the docs already call system calls invisible and name `extra_data` as the close marker, so the residual is two sentences and a NatSpec line, better sent as a small docs PR (plus a tn-contracts NatSpec change) than filed as an issue.

Rule breaches: none. Words: 577 by prose count.

Counts: 22 checked / 20 matched / 2 wrong / 0 untraceable / 2 weak.

## Titles (all three)

- Restart: 104 characters; not true of main as an absolute (error 1.1); replacement 115 characters.
- Rejoin: 116 characters; contradicted by r20261113-2118 and not measured on main (error 2.1); replacement 119 characters.
- NewEpoch: 109 characters; half false (error 3.1); replacement 83 characters.

## Cross-text consistency

The restart and NewEpoch texts describe the same e2e module the same way (four validators, not upstream, node build `bench/bench6-2026-11` at `2df831e3c`); the restart text's "120 s epochs" applies to the two hook tests only, which is the test it describes.
No quantity appears in two texts with different values.
