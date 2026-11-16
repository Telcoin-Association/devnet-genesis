## Summary

Adds the runtime switch `vote_queue_fix` (default `false`, main's behaviour) for the voter's side of #1804.
With it on, a voter waits for execution (up to 1 s) before the per-author vote lock instead of under it, so one author's queued requests stop waiting a second each in turn.
The voter also refuses at once a request older than that author's newest (`SupersededRequest`, recoverable, no penalty), and the node needs `vote_timeout` below 9 s.
Every node, switch on or off, counts vote requests by outcome.

PR 3 of 8 in the stack #1862 to #1869; #1862 targets `main`, this PR targets #1863's branch (`test/bench6-e2e-scaffold`), so the Files tab shows this change alone (10 commits).
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

## With the switch off

Every vote decision is main's.
New with it off: an empty per-author map, three reads of the switch per request and one at epoch start, `tn_primary_vote_outcomes_total{outcome}` (ten series), `prelock_wait_ms=0` on the debug `vote path timing` line, an unused `prelock_wait` label on `tn_primary_vote_stage_seconds` and `tn_primary_vote_timeouts_total`, and `vote_queue_fix=false` on the `node switches` line.

A mixed fleet is one chain: only a voter's answer changes, `SupersededRequest` travels as `RecoverableError`, which every node already retries, and signed votes are the same.
For a lower round after a newer request from the same author, a switch-off voter decides as main does (`AlreadyVotedForLaterRound` once it voted the newer one); the author has cancelled that header, so no certificate depends on it.

## Testing

Unit tests in `crates/consensus/primary/src/tests/network_tests.rs`: `vote_queue_fix_queued_requests_wait_once`, `vote_queue_fix_stale_round_refused_at_once`, `vote_queue_fix_refuses_request_superseded_on_the_lock`, `vote_queue_fix_keeps_equivocation_refusals`, `vote_queue_fix_refuses_repeat_of_voted_header_after_newer_request` and its switch-off twin, `vote_queue_fix_on_refuses_malformed_header_without_the_wait`; in `crates/config/src/consensus.rs`, `vote_queue_fix_keeps_vote_timeout_plus_the_prelock_wait_below_the_request_timeout`.

On main at 33b727fce, at this head's tip `17327280d`:
- `cargo check --locked --workspace --all-targets`, warnings denied: clean.
- `cargo nextest run --locked --no-fail-fast -p tn-config -p tn-types -p tn-node -p tn-primary -p tn-network-libp2p`: 1,825 passed, 9 skipped, the tests above among them.

On the stack's earlier cut on main at 45dce8947, on a form of this head's first nine commits whose tree differed from theirs only by doc comments in the e2e crate: `cargo check --locked --all-targets` and `cargo nextest run --locked --no-fail-fast`, each with `-p tn-primary -p tn-config -p tn-network-libp2p`, passed (nextest: 1,303 passed, 4 skipped), as did `cargo fmt --all -- --check`.

Not run: no e2e test covers the switch, and no benchmark has run this head; a benchmark of the stack's earlier form on main at 45dce8947 runs it on, with the author-side switch, and has not finished.

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
- A header failing only a check under the lock (parents, drift tier, seed signature) still waits first.
- The mark moves before the header checks: a malformed header below it gets `SupersededRequest`, not its penalty.
- A restarting proposer that cannot read `LastProposed` may propose below the mark and be refused as superseded until its rounds pass it.
- Compare `total_ms` across settings, not `lock_ms`.

Nothing that should be fixed before merge is open.

## Related

- Refs #1804: the voter's side only; the author's side is `fix/1804-quorum-exec-block`, which builds on this head.
- Refs #1782: the bounded execution wait this moves.
- Ported onto main's vote-handler rework: #1822, #1839, #1842, #1844.
- Next: `fix/epoch-record-closing-block-check`, `fix/epoch-record-collector-hardening` and `fix/epoch-loop-output-drop` build on this head.
