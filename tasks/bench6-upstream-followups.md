# Bench 6 — what each topic still owes before its upstream PR (W8)

Collected from the topic reviews (`tasks/bench6/review/<topic>-report.md`) and the e2e units. Nothing here blocks the benchmark
image unless it says so. Each line: the item, where it is described, and its state.

## digest-dedupe (#1807)
- D59 commit-notice window (Low): document as a residual, or send each sub-dag's own committed rounds inside the sequencing
  loop. Report §Low 1. OPEN.
- D60 two proposer tests with the real worker against the real proposer (sketched in the report). OPEN.
- Config doc on when the worker suppresses a seal. DONE b89ad570f.

## parent-grace (#1803)
- M1 re-entry of a late author, M2 no grace for the round's leader, L1, L2 (warn), L4 (authors on the lines): DONE (U9b, d83f8f79b..f4ee92d92). D72 (a node never waits for its own certificate) for the PR text. One narrow window left open (a swap naming this node leader of the current round during a grace).
- M3 / D63 cost under load: issue and PR text ("about 0 under load" is wrong). OPEN (text).
- L2 validation of `parent_grace` against `max_header_delay` (the review suggests rejecting above half of it; the bench
  build only warns). L3 D38 wording. L5 two far validators waiting on each other (measure with the new author field). OPEN.
- Idea, not built: a node-wide grace budget (a burst of G refilled per round) to cap a sustained delayer. OPEN (design).

## mdbx-advice (#1802)
- Nine Info items (probe cost inside two lap fields, the non-Linux stub reports success, weak test assertions, an unused
  open-time lookup with the switch off, ungated test helpers, an uncapped retry loop, two unreachable gaps). Report §4-11. OPEN.
- "Applied" logged only with advised bytes; docs. DONE c88936999.
- D68 a pre-existing race: a Prometheus scrape can run libmdbx's stat on the persist's live write transaction. OWN ISSUE. OPEN.

## inflight-bound (no issue yet)
- M1 (Medium; before upstream, and before the image ONLY if load went through an observer — it does not: each blaster
  targets its own validator, `benchmark-blast.sh:1759`): while honest gates are closed, one validator's −32000 rejection of
  an observer-forwarded transaction becomes final, because the other hops answer −32003 and the walk treats that as
  try-next; the transaction is removed without a requeue. Fix: when any hop answered try-next, an unconfirmed rejection is
  no verdict: requeue. `forward.rs`. OPEN.
- L1 a requeue the observer's pool refuses is lost and not counted. L3 a `--forward-txs` node relays −32003 without trying
  another target (the docs say the opposite). L2 before the first output finishes the backlog reads only the engine's held
  count (doc describes a seeding nothing does). L4 admission ignores fees; junk bytes reveal the gate state (doc). OPEN.
- I7 during a rolling restart, load admitted by ungated validators can keep a gated one closed: same K on every node, and
  the flip window stays out of the arm's statistics (the harness already measures from `ready`). NOTED.

## sealed-keep (#1807)
- S6 (a seal that fails to report at the epoch boundary) and S7 (eviction of a marked transaction) e2e tests. OPEN.
- D64 marks do not survive a restart (a resend is accepted as new, lands once). PR text. OPEN.
- Review DONE (approve with follow-ups). M1 (walk race), M2 (pending cap under the switch), L1 (late mark after the orphan pass): DONE (U6c 891e2b962..c8659e2fa + wiring 80a0c76c0); delta review APPROVE with L5-L8 (presence check takes the pool read lock per candidate; a tail packed across a nonce gap; a 250-ms wait at low load; the orphan fence sits inside a per-digest function) and six Info (two wrong doc comments; trait defaults can silently disable the fix in a future pool; the refused-mark counter mixes three causes; hold-backs are not counted). The per-sender cap (256 slots) versus in-flight transactions: decide with the pending-cap doubling. OPEN. L2 (a sender's later nonces are re-sealed and skipped every cycle while an earlier batch is late), L3 (a builder walk on every wake while anything is marked), L4 (clearing a mark is a side effect of the generic re-pool method), ten Info: OPEN.
- Upstream alternative for M2: seed a TN pending-pool default in `init_reth_defaults`, or state the global cap as a residual. OPEN (decision).

## quorum-exec-block / voter-lock (#1804)
- Review DONE (approve with follow-ups; nothing C/H/M). D75 (clamp the named block to the epoch's opening block; ≈ 10 lines), D76 (carry the adaptive window across epochs, optional), a counter for superseded refusals, `quorum_exec_block_starved_rounds` not validated, five Info: OPEN.
- D61 the adaptive reset rule: DONE (U1b, 20858d28d). D70 (a vote-withholding minority can hold a node in long windows: staleness only) and D71 (latency cancels restart the streak) for the PR text. Review running.

## recovery-pool (#1805)
- Review DONE (approve with follow-ups). The `proptest` dev-dependency of `crates/engine` is unused without the pipelined stack's tests; two stale doc comments (`payload_builder.rs:70-72`, `tn-reth execution.rs:216-218`) are fixed only on the pipelined stack: if the stack is cut, fix them on this topic's branch. The full contention bench run is still owed. OPEN.

## plumbing (switches, obs, e2e scaffold)
- Review DONE (approve with follow-ups). Unknown keys in `parameters.yaml` are ignored without a warning (pre-existing); `TN_E2E_PARAMETERS` accepts a mistyped key and does not reach one epochs test; `tn_primary_digest_wait_seconds` changed meaning without a rename. OPEN.

## tracker-drain (#1806)
- Review DONE (approve with follow-ups). F1 the e2e test must show the slow member ran the stored-record check (`vote_skipped{certified_before_close}` ≥ 1); F2 WARN vs ERROR for a critical task's failure during a drained close; F3 log levels in `join_tasks_within` changed for every TaskManager, not behind a switch; F4 the vote-skip counter cannot account for a late signer; F5 the switch doc leaves out the empty-ring skip; F6 close gauges only on the live boundary close. D42, D43 stand. OPEN.

## pipelined-persist (#1800)
- Held stack `b6/pipe-stack-2` (19 commits on d91d65d3e). Review DONE (approve with follow-ups; nothing C/H/M). For the PR: F1 (a durable output rolled out of memory when the commit task dies and the head read fails; node halts), F2 (no test reaches the I/O-side fail-closed guards), the doc claim at `output_overlay.rs:156-158` (seeded and unseeded builds emit differently shaped trie updates; root and rows identical), D45 restated (the pinned read transaction lives for a commit plus a build), ten Info. Gates 5 and 6 open.
