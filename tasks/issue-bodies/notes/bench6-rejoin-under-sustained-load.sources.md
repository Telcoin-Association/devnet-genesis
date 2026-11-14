# Sources: bench6-rejoin-under-sustained-load

Not for posting. Every figure of the body and where it comes from.
Abbreviations: R2 = `benchmark/private/bench6-r20261113-1351/A3a/recovery.md` (runs r20261113-1351 and r20261113-1630); R3 = `benchmark/private/bench6-r20261113-2118/A3a/recovery.md` (runs r20261113-2118 and r20261114-0000); K2 = `benchmark/private/bench6-r20261113-1351/A1/kpis.md`; K3 = `benchmark/private/bench6-r20261113-2118/A1/kpis.md`; CMP = `benchmark/private/bench6-r20261113-2118/A7/comparison.md`; REP = `tasks/bench6-report-r20261113-1351.md`.

## What happens

- Start to `CvvActive` 16m40.8s / 16m30.1s: R2 line 16; REP line 429. 17m39.6s: R3 line 5. 25m00.1s: R3 line 14.
- Kill to `CvvActive` 21m40.7s, 21m30.2s (R2 line 15), 22m39.8s (R3 line 5), 30m00.0s (R3 line 14); body gives the range 21m30.2s-30m00.0s.
- One promotion per restart, held, no failed promotion: R2 lines 6, 143; R3 lines 6, 94. Run 2b's pre-kill failed promotion (R2 line 69-70, CMP line 295) is why the body says "per restart".
- First certified header within a second: run 2 +0.76 s (R2 line 51), run 2b +0.93 s (R2 line 95), run 3 0.52 s (R3 line 94), run 3b +0.61 s (R3 table row 03:00:22.457). REP line 430 says 0.8-0.9 s for runs 2/2b.
- Two records missed after the kill (one down, one following): run 2 epochs 4 and 5 (R2 lines 129-130, 147); run 2b same (R2 line 90-92); run 3 epochs 4 and 5 (R3 line 10, which also lists epoch 2 before the kill); run 3b epochs 6 and 7 (R3 line 17).
- RPC refusal text `-32603 validator is inactive; retry another endpoint`: K2 line 158; R2 lines 35, 80; R3 run-3b row 02:35:33.5.
- Reads answered: generator 05's scanner reads blocks and receipts from its own validator (K2 line 213) and saw pre-kill landings up to 15:47:07Z / 18:28:23Z after the restart (K2 line 322). That reads are not gated: code (below).
- 402 to 605 outputs behind, per-minute samples (`tn_node_last_executed_consensus_height` gap): run 3 minimum 402 (R3 line 76, metric 445 → 402); run 3b maximum 605 at 03:00 (R3 run-3b row 02:52-03:00). Other runs inside: run 2 469 → 513 → 527, run 2b 483 → 515 → 585 (R2 lines 124-125).

## Evidence

- Setup (ten validators, ten regions, generators pinned to their validator, SIGKILL `docker kill -s KILL`, restart 300 s later): R2 table rows 15:40:59 / 15:45:59; K2 line 101, 161; CMP line 12.
- Vote changes on, not on main: REP §4.5 line 437 ("the vote fix removed that slack"), R2 line 13, 146 ("the vote fix lets the network run at its validators' execution rate"). The "did not measure main" is a plain statement.
- Table, column "outputs behind: open-epoch entry, end of load":
  - r20261113-1351: 452 at epoch-5 entry (R2 line 40), 513 at end of blast (R2 line 124, metric).
  - r20261113-1630: 470 at entry (R2 line 84), 515 at end of blast (R2 line 124).
  - r20261113-2118: 438 at entry (R3 line 74, "902 rounds (438 outputs)"), 402 at the end of the load (R3 line 76, per-minute metric to 23:26; log says 403).
  - r20261114-0000: 429 at entry into epoch 7 (R3 row 02:37:45.477), 425 at 02:52-02:53, the last minute before the mixed end 02:53:52 (R3 row 02:52-03:00).
- Column "follower / network outputs per s under load": 1.332/1.409, 1.180/1.243 (R2 line 9, 122); 1.305/1.288 (R3 line 9, 75); 1.063/1.091 (R3 line 15 and "Why 30 minutes" first bullet).
- Column "generator 05 landed nothing for": 949 s, 899 s (K2 line 160); 1,008 s (K3 line 127); 1,374 s (K3 line 221). CMP lines 43, 276 (`vs-always-on.md`) agree.
- `reason=round_gap` 802 to 1,144 rounds: run 2 934 → 988 (R2 line 41), run 2b 942 → 1,144 (R2 line 85), run 3 902 → 802 (R3 line 76), run 3b 862-904 (R3 row 02:37:46-02:51:26). Window 20: R2 line 108.
- Replaying the already-closed epoch first: R2 lines 118-119; R3 lines 72-73; run 3b R3 rows 02:35:31-02:37:45.
- `tn_engine_queued_outputs` 8: runs 2/2b R2 line 115 ("at every minute of both follower stretches after the first"); run 3 R3 line 69 ("every minute ... but one"). Not read for run 3b: hence "three runs where we read it".
- Run 3 gain 4.5 outputs/min, ~90 more minutes: R3 lines 8-9, 87 (inferred arithmetic in the source).
- Promotion 5m01.9s to 5m54s after cooldown end: run 2 5m01.9s (CMP line 120; R3 line 7 "5m02s"), run 3 5m02.8s (CMP line 120), run 2b 5m31s and run 3b 5m54s (R3 line 16).
- Generator 05 sent about 580-593 tx/s after restart (headline runs): K2 line 157; REP line 237. All refused: K2 lines 157-158 (accepted/s 0.0 in every minute, tables lines 118-128 and 143-152).
- "about 10 s after the start": run 2 start 15:45:59.084 (R2 line 30), first refusal 15:46:09Z (K2 line 158); run 2b start 18:26:20.152, first 18:26:29Z; run 3b start 02:35:22.132, first 02:35:33.466 (R3). "until the load ended": last refusals 15:56:45Z / 18:36:16Z against mixed ends 15:56:49 / 18:36:19 (K2 line 158; R2 lines 43, 88).
- Generator pinned, does not fail over: K2 line 161; REP line 242.

## Code on main 45dce8947 (/home/drtnarg/coding/telcoin/telcoin-network-b7)

- `git diff --stat 2df831e3c 45dce8947` over `crates/consensus/executor/src/subscriber.rs`, `crates/types/src/primary/mod.rs`: no change. `crates/state-sync/src/lib.rs` changed only the restart replay's epoch filter and log fields; `crates/tn-reth/src/rpc_fee_cap.rs` lost the bench-only `BacklogBound`, the inactive refusal is the same.
- `rejoin_ready` `subscriber.rs:136-149`; doc premise `:130-132` ("Under sustained load a node that must fetch, verify and execute every output is always a few outputs behind"); `rejoin_epoch_is_open` `:102-112`; stalled-head `:173-192`; `REJOIN_HEAD_MAX_AGE` `:45`; window computed `:475`.
- `MAX_GC_DEPTH = 50` `crates/types/src/primary/mod.rs:52`; `GC_ACTIVITY_BUFFER = 10` `:64`; `gc_activity_window` `:75-77`; `rejoin_round_window` `:87-89`; default `gc_depth` = `MAX_GC_DEPTH` `crates/config/src/node.rs:348-350`. `MAX_COMMIT_RUN_AHEAD_ROUNDS = 1_000` `mod.rs:217` (doc `:69-72`: execution may trail the committed round by up to it without demotion).
- State-sync execution wait: `crates/state-sync/src/lib.rs:616-624` (`wait_for_execution(base_execution_block)`, comment "We need to make sure execution has caught up so we can verify we have not forked").
- `test_restarts_lagged_under_load`: `crates/e2e-tests/tests/it/restarts.rs:1873-1888` (doc "must catch up and rejoin consensus before the load stops (issue #1513)"); `spawn_load` `:1841-1870` (one key `LOAD_SOURCE`, one thread, sequential sends).
- RPC: `node_mode_accepts_submissions` `crates/tn-reth/src/rpc_fee_cap.rs:57-62` (CvvInactive false; observers keep submissions "because their workers forward batches", `:56`); `ensure_can_submit` `:68-78`; module doc `:7-13` (only the two raw submission methods are wrapped).
- `TN_TEST_EXECUTION_DELAY_MS` `crates/types/src/test_hooks.rs:117-147`.

## Issues

- #1513 closed 2026-11-04, "Inactive validator cannot rejoin consensus while the chain is under load" (exact-match rule → distance rule).
- #1801 closed 2026-11-12, comment: "Fixed on main by a3df64830 (#1827, which carried #1826). The fix is #1818"; #1818 merged "fix: one rejoin per episode (...)".
- #1514 closed: transaction forwarding still targets inactive validators → the inactive refusal.
- No open issue found for rejoin under load (`gh search issues "rejoin load" --state open` → []).

## Left out

- Bench 5's 23m05.7s start-to-active: its build also had the promotion loop (#1801), so it does not isolate the replay pace.
- Run 3b's validator-02 mid-load demotion (4m00.0s, generator 02 refused): R3 line 20, K3 line 243; cut for length.

## Revision after the figure-check (tasks/bench7/figcheck-UI2.md §2), 2026-11-14

Changed sentences and their sources (no new figure):
- Title/H1 → "A validator restarted under sustained load stayed inactive until the load ended: it replays at about the network's rate" (119 chars): figcheck error 1 (line 51); r20261113-2118 replayed 1.305 against 1.288 (R3 lines 8-9, 75-76), main not measured.
- "stays `CvvInactive` until its replay passes the end of the load" → "stayed `CvvInactive` until its replay passed the end of the load" (tense matched to the new title; same runs).
- "the committee ran one validator short …" → "the committee ran at least one validator short from the kill to the promotion, 21m30.2s to 30m00.0s;" (figcheck weak 2, line 67; validator-02 inactive 4m00.0s in r20261114-0000, R3 line 20).
- "with `-32603 validator is inactive; retry another endpoint`" → "with error code -32603 and the message `validator is inactive; retry another endpoint`" (figcheck error 3, line 58; `rpc_fee_cap.rs:72-76`; generator log text K2 line 158).
- "They are not on main …; we did not measure how far below that rate main runs." → "They are not on main and let the network run at its validators' execution rate." + "We have not measured main under this load, so whether a restarted validator gains on main's network is not known." (figcheck weak 1, line 65).
- Table header "generator 05 landed nothing for" → "generator 05 landed nothing, kill to end of load" (figcheck weak 3, line 69; K2 line 160, K3 lines 127, 221).
- Table cell r20261114-0000 "429, 425" → "429, 466" (figcheck error 2, line 55): the end-of-load column now takes the cooldown-end minute in every row (15:57 = 513, 18:37 = 515, 23:26 = 402, 02:54 = 466; `bench6-r20261113-2118/A3a/data/r3b-prom-recovery.json` `minutes[]`, cooldown end 02:54:28).
- "roughly 90 more minutes of load to reach the window." → "… (inferred from that slope)." (figcheck weak 4; R3 line 87 "inferred arithmetic").
- "at the network's execution limit it cannot replay faster than the network produces" → "at the network's execution limit it replays at about the network's rate" (made consistent with the new title; r20261113-2118 gained slightly).
- "#1513 (closed) replaced …" → "#1513 (closed): its fix replaced the exact-head rule with the 20-round window: enough for a node a few outputs behind, not hundreds." (figcheck weak 5, line 71).
- Cut for length: the stalled-head sentence (`subscriber.rs:173-192`); "Separately: should a validator that follows for tens of minutes forward submissions …" → "Separately: should a following validator forward submissions to active members, as an observer does, instead of refusing them?"; test bullet "but its load, one account … is far below that limit" → "requires a rejoin \"before the load stops\" under one account sending from one thread (`spawn_load`, `:1846`), far below that limit."; "the time comes from the replay" → "the replay sets the time"; "at 802 to 1,144 rounds" → ": 802 to 1,144 rounds"; e2e bullet "with the load still running" → "under load".
- Not applied: figcheck weak 6 (optional, "in all four runs"): no analysis text states it, so the body keeps "in the three runs where we read it".
Word count after revision: 899 prose (935 `wc -w` with table pipes).
