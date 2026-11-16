## Summary

Adds a fix for the voter's side of #1804 behind the runtime switch `vote_queue_fix`, new in this PR (default `false`, main's behaviour).
With it on, a voter waits for execution (up to 1 s) before the per-author vote lock instead of under it, so one author's queued requests stop waiting a second each in turn.
The voter also refuses at once a request older than that author's newest (`SupersededRequest`, recoverable, no penalty), and the node needs `vote_timeout` below 9 s.
Every node, switch on or off, counts vote requests by outcome.
{{pr-09}}, the last PR of the stack, removes the switch and makes the change the node's behaviour: once the stack is collapsed into #1862 there is no switch, every voter waits before the lock, and a node starts only with `vote_timeout` below 9 s.

PR 3 of 9 in the stack #1862 to {{pr-09}}; #1862 targets `main`, this PR targets #1863's branch (`test/bench6-e2e-scaffold`), so the Files tab shows this change alone (10 commits).
The stack will be collapsed into #1862 (each PR merged into the branch below it); `main` is then merged into that branch and `make attest` runs on the result.
Please merge with 'Create a merge commit': a squash would leave the pull requests above this one with commits their base no longer has.

## Problem

On main at 33b727fce, `vote_request` holds the author's lock (`crates/consensus/primary/src/network/handler.rs:1029-1033`) through `vote_inner` (`:1158-1162`) and its 1 s execution wait (`:1462-1507`), so a voter behind on execution answers one author's queued requests a second apart, even for headers the author replaced (its cancel never reaches the voter).
The rework in #1822, #1839, #1842 and #1844 keeps this; #1842 adds a wait under the lock for a pending attached parent (`:1845-1855`).
Read from the code; the first commit's test pins it: the sixth of six queued requests is answered after the 5 s vote timeout.
Bench 5 ([r20261107-1504](https://benchmark.telcoin.network/runs/r20261107-1504/)) measured validator-01 waiting 7.3 to 8.5 s for the lock on validator-04's requests.

Bench 6 ran an earlier version of this switch, on an older base, in all four runs ([r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/), [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/), [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/)) and measured `lock_ms` p95 at 0 on every voter in every window.
That does not isolate the switch: the author-side fix was on too, and the switch moves the execution wait from `lock_ms` to `prelock_wait_ms`, where the slowest voter still waited the full second (validator-05's `prelock_wait_ms` p95 1,001 ms over the 600 × 16 blast's mixed phase of r20261113-1630 and r20261114-0000).
A voter without the block still does not vote: over the 600 × 16 blast's mixed phase of r20261113-1630, voters answered 93,730 requests `superseded` against 265 refused-behind votes.
What the switch alone does to certification is not known.

## Change

- `84c517cf1` test(primary): pin that one author's vote requests wait in turn on its lock: main's behaviour, kept as the switch-off regression.
- `d96b72ec7` feat(config): add the vote_queue_fix switch: the field, default `false`, listed in `runtime_switches!`.
- `efce070ad` fix(primary): wait for execution before the per-author vote lock: with the switch on, the wait runs before the lock and the check under it does not wait (same refusals).
  The author's newest in-window `(epoch, round)`, kept in memory per epoch, refuses a lower round of that epoch on arrival, after the wait, and under the lock after the cached vote and the recast.
  Equivocation checks, signing and the vote store stay under the lock; `SupersededRequest` is never written to the author's entry.
  On purpose, a repeat of an older voted header after a newer request is refused, not answered from the cache; nothing is signed either way.
  Adds `prelock_wait_ms`, the stage `prelock_wait` and the outcome `superseded`.
- `53f0cf63d` docs(primary): say that a requester's cancel does not reach the voter: corrects the comment #1842 added, with a test.
- `6cb8aed74` feat(primary): count vote requests by outcome: `tn_primary_vote_outcomes_total{outcome}`; no switch.
- `4638a56cb` test(primary): pin the superseded check after the pre-lock wait.
- `62f5771dc` fix(primary): skip the wait before the vote lock for a header that fails its own checks: it gets its switch-off refusal, penalty and author entry at once, still under the lock, where that entry refuses a later same-round header.
- `40c5d0b3c` fix(config): keep vote_timeout plus the wait before the vote lock under the request timeout: with the switch on, `vote_timeout` must be below 9 s (the 10 s transport timeout less the wait); the default and both shipped presets pass.
- `3f1b9522c` docs(primary): say what a vote permit is held through with vote_queue_fix on: `record_outcome` indexes its counters directly.
- `17327280d` docs(config): state the 9 s vote_timeout ceiling with vote_queue_fix on: field docs and the CLI README.

## The switch, and where it goes

In this PR's diff, with the switch off, every vote decision is main's.
New with it off: an empty per-author map, three reads of the switch per request and one at epoch start, `tn_primary_vote_outcomes_total{outcome}` (ten series), `prelock_wait_ms=0` on the debug `vote path timing` line, an unused `prelock_wait` label on `tn_primary_vote_stage_seconds` and `tn_primary_vote_timeouts_total`, and `vote_queue_fix=false` on the `node switches` line.

{{pr-09}}, the last PR of the stack, removes the switch and with it the switch-off path, the wait for execution under the author lock.
After it, every voter waits for the execution block a header names before the author lock, at most 1 s, and refuses a request that a newer request of the same author has superseded; once the stack is collapsed into #1862 there is no switch.
{{pr-09}} also deletes this PR's switch-off tests, among them the first commit's test that pins main's wait in turn.
So review the change as unconditional: what speaks for it is no longer the off state but the on arm, that is the unit tests under Testing, the stack-wide gates below run with the six switches on, `make test-upgrade` with main at 33b727fce as the previous binary among them, and the bench 6 and bench 7 runs that ran this switch on.
The rolling-upgrade test ran beside main, not beside `v0.17.0-adiri`.
A `parameters.yaml` that still sets `vote_queue_fix` loads after {{pr-09}}; the node ignores the key.

A mixed fleet is one chain, whether its nodes set the switch differently (this PR's diff) or run main beside the stack (a rolling upgrade): only a voter's answer changes, `SupersededRequest` travels as `RecoverableError`, which every node already retries, and signed votes are the same.
For a lower round after a newer request from the same author, a voter on main, or with the switch off, decides as main does (`AlreadyVotedForLaterRound` once it voted the newer one); the author has cancelled that header, so no certificate depends on it.

## Testing

Unit tests in `crates/consensus/primary/src/tests/network_tests.rs`: `vote_queue_fix_queued_requests_wait_once`, `vote_queue_fix_stale_round_refused_at_once`, `vote_queue_fix_refuses_request_superseded_on_the_lock`, `vote_queue_fix_keeps_equivocation_refusals`, `vote_queue_fix_refuses_repeat_of_voted_header_after_newer_request` and its switch-off twin, `vote_queue_fix_on_refuses_malformed_header_without_the_wait`; in `crates/config/src/consensus.rs`, `vote_queue_fix_keeps_vote_timeout_plus_the_prelock_wait_below_the_request_timeout`.

On main at 33b727fce, at this head's tip `17327280d`:
- `cargo check --locked --workspace --all-targets`, warnings denied: clean.
- `cargo nextest run --locked --no-fail-fast -p tn-config -p tn-types -p tn-node -p tn-primary -p tn-network-libp2p`: 1,825 passed, 9 skipped, the tests above among them.

On the stack's earlier cut on main at 45dce8947, on a form of this head's first nine commits whose tree differed from theirs only by doc comments in the e2e crate: `cargo check --locked --all-targets` and `cargo nextest run --locked --no-fail-fast`, each with `-p tn-primary -p tn-config -p tn-network-libp2p`, passed (nextest: 1,303 passed, 4 skipped), as did `cargo fmt --all -- --check`.

Not run: no e2e test covers the switch, and no benchmark has run this head.
Bench 7 ran the stack's earlier cut on main at 45dce8947 with this switch on, beside the author-side switch of #1868: the always-on form of that fix in [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/), the adaptive form in [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/), ten validators at 20,000 IOPS, one run each; #1868 and #1869 report its results.

Stack-wide gates ran before these PRs were opened, on the top of the full stack: `fix/1807-digest-order-hold` at `500e21afa`, 103 commits on main at 33b727fce, carries the code of all eight pull requests (#1862 to #1869).
- `cargo +nightly-2026-03-20 fmt --all -- --check`: clean.
- `./etc/ci-lanes.sh clippy`: passed.
- `cargo nextest run --locked --workspace`: 5,624 passed, 149 skipped.
- Every one of the 103 commits compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied).
- `make test-restarts` 11/11, `make test-epochs` 11/11, `make test-sigkill` 12/12 and `make test-e2e-resync` 1/1, once with every switch off and once with the full stack's six switches on.
- `make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time): passed with every switch off and with the six on.
- The 13 e2e tests the full stack adds, three runs each: all passed.
- The three `state_export_import` tests, which restore a node from an exported state: passed.
- Against a later main, c1b1eb9fe (#1859): the top merges without conflict, and the merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-storage` (1,764 passed, 21 skipped).
- Against the main of 2026-11-16, 0554efd4f (#1861): one file conflicts, `crates/node/src/manager/epoch_votes.rs`. #1861 renamed the collector's failure channel and ends a vote round on a forked record with an error; #1866 added the kept signatures to the same functions. In a local trial merge both changes are kept, the drop of a forked record's kept signatures moves in front of #1861's early return, and one test of #1866 expects the fork as an error. The merged tree passes `cargo check --locked --workspace --all-targets` with warnings denied and `cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-types -p tn-reth -p telcoin-network-cli` (2,175 passed, 17 skipped). The merge itself is made after the stack is collapsed.

## Limits and what a reviewer should look at

- The pending-parent wait (#1842) stays under the lock, so a newer request still waits up to `vote_timeout` behind an older one parked on a pending parent (`vote_queue_fix_newer_request_waits_for_pending_parent_wait`); closing that needs the wait out of the lock.
- Worst case per request: 1 s, the lock wait, then `vote_timeout`; only the 10 s transport timeout bounds the lock wait, as on main.
- One peer can park up to 800 waits before the lock (8 connections × 100 streams) under the default, unbounded vote serve class; on main they wait on the lock.
  Only the authenticated author can cause it, and on main N queued requests held their tasks for up to N × 1 s; counting waiters per author and answering `ExecutionBehind` at once past a small cap would bound it.
- A header failing only a check under the lock (parents, drift tier, seed signature) still waits first.
- The mark moves when a request arrives, before the header checks, not when a vote is cast.
  A newer request that is itself refused or dropped still makes every lower round of that author `SupersededRequest`, even if this voter never voted for the newer round, and a malformed header below the mark gets `SupersededRequest`, not its penalty.
- A cached refusal is replayed under the lock, so a repeat of a refused header that names a block this voter has not executed waits up to 1 s before its cached answer; on main it came at once.
- A restarting proposer that cannot read `LastProposed` may propose below the mark and be refused as superseded until its rounds pass it.
- Compare `total_ms` with main's, or across switch settings in this PR's diff, not `lock_ms`: the change moves the execution wait from `lock_ms` to `prelock_wait_ms`.
- After {{pr-09}} this change is the voter's only path, and what a voter answers differs from main in four points; {{pr-09}} changes four of main's own tests to assert the new answers.
  - Once a newer in-window request of an author has been seen, a request of that author for a strictly lower round of the same epoch gets the recoverable `SupersededRequest` on arrival, before the lock, where main answers `InvalidHeader(AlreadyVotedForLaterRound)` once it has decided the newer header, and decides the older one in full after a recoverable answer to the newer one (a timeout, `ExecutionBehind`, a deferral), which leaves no entry; a different header for the same round still gets `AlreadyVotedForLaterRound`.
  - A repeat of an older header the voter already voted for then gets `SupersededRequest` instead of the cached vote.
  - The old answers remain while no newer in-window request of that author is recorded: the record lives in memory and starts empty when the handler is built (a restart, a mode change), or the newer header was outside the vote window when it arrived.
  - A header with a tier-three timestamp lead that names a block the voter has not executed gets the same `InvalidTimestamp`, but after up to 1 s instead of at once, because the wait before the lock runs before the drift check, which stays under the lock; a tier-three header that names a block the voter holds is refused at once, and a header that fails validation or is outside the vote window skips the wait.
- `SupersededRequest` is not a new wire type: it goes out as `PrimaryResponse::RecoverableError(String)`, which main already has (0554efd4f), and a requester retries it up to 6 times at 250 ms, then with backoff until its next proposal cancels the request.
  `AlreadyVotedForLaterRound` went out as `PrimaryResponse::Error`, which the certifier treats as fatal for that voter and header; neither carries a penalty, so an older request now costs retries where it cost one give-up, and they normally end at once because the author has moved on.
- After {{pr-09}}, `vote_timeout` strictly below 9 s is a start condition for every node: `vote_timeout` plus the 1 s wait before the lock must stay under the 10 s request timeout on entering any epoch the node can vote in, so 8.999 s passes and 9 s is refused.
  The code default and the mainnet preset are 5 s and the testnet preset keeps the default; a node configured at 9 s or more fails the check when it enters such an epoch, at start-up or after replaying closed ones.

Nothing that should be fixed before merge is open.

## Related

- Refs #1804: the voter's side only; the author's side is #1868 (`fix/1804-quorum-exec-block`), which builds on this head.
  #1862's body, the only PR of the stack that merges into main, refers to #1804 with `Refs`, not a closing keyword.
- Refs #1782: the bounded execution wait this moves.
- Ported onto main's vote-handler rework: #1822, #1839, #1842, #1844.
- Next: #1865 (`fix/epoch-record-closing-block-check`), #1866 (`fix/epoch-record-collector-hardening`), #1867 (`fix/epoch-loop-output-drop`), #1868 (`fix/1804-quorum-exec-block`) and #1869 (`fix/1807-digest-order-hold`) build on this head, and last {{pr-09}}, which removes the stack's switches.
