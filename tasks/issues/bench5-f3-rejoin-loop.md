# A promoted validator cannot rebuild its DAG mid-epoch, so it loops between promotion and demotion until the next epoch

## Problem

A validator that was demoted to `CvvInactive` mid-epoch never rejoins for good before the next epoch starts. Each time its
follower gets within the rejoin window it promotes itself, restarts its epoch tasks as an active validator, makes no commit,
and is demoted 7 to 9 s later. The cycle repeats about every 71 s. Only an epoch entry holds, because every node starts the
new epoch at round 1.

In the 2026-11-05 run a validator killed and restarted under load was out of the committee for 36 minutes after its restart,
and a validator demoted by commit lag for 48 minutes. Neither failed promotion was caused by load: twelve of the thirteen
promotions of the restarted validator happened after the chain had gone idle.

The promoted node rebuilds its DAG from an empty certificate store and has to fetch the missing certificates from peers. The
lowest rounds it needs are rounds its peers have already deleted, so the fetch can never complete, nothing is accepted, and
Bullshark never commits. Three smaller defects make each attempt worse: the proposer starts from the wrong round and proposes a
header with the genesis parents, it then re-proposes that stored header on every later promotion, and nothing stops the next
promotion from repeating the same failure.

## Evidence

Run r20261105-0803: ten validators in ten regions, closed-loop load, one validator killed and restarted. Times are UTC.

The restarted validator (validator-05):
- killed at 09:33:50, restarted at 09:38:50.608, demoted at once on the epoch rule (`validator-05:09:39:04.822`), and followed
  consensus at 236 to 308 rounds behind the newest header while the load ran. It only came within the rejoin window after the
  load stopped.
- first promotion at `validator-05:10:00:59.570`: `attempting to rejoin consensus handled_round=730 newest_round=750
  round_gap=20 rejoin_window=20`, then `dag restored num_certs=0 rounds=0 gc_round=680`.
- from `validator-05:10:01:00.549` to `10:01:06.977` the certificate fetcher failed eleven times with `Fetch task failed: The
  certificate … is pending acceptance due to missing parents`, and 656 certificates were parked as `Processing certificate with
  missing parents`. No certificate was committed.
- demoted at `validator-05:10:01:08.403`: `we are behind … exec_round=730 committed_round=730 round=771 reason=outside_gc_window`.
- eleven more pairs, each 7.1 to 8.9 s active and 70.4 to 72.5 s apart: 10:02:11.083/10:02:19.291, 10:03:22.130/10:03:30.844,
  … 10:13:59.909/10:14:06.979. On every one the restored DAG was empty, `committed_round` stayed at the handled round, and the
  demotion came at `round = exec_round + 41`. Between attempts the follower stalled for 60.5 s until `catch-up stalled after
  retries, requesting the missing consensus range from the fetch task`, then caught up in 1.5 s and promoted again.
- held only at the next epoch entry: `attempting to rejoin consensus handled_round=2 newest_round=12` at
  `validator-05:10:14:58.184`, first own certificate at 10:14:59.055.

The proposer on each attempt:
- first promotion: the proposer started with round 0, its first poll fired the max-delay tick, and it proposed round 5 of the
  epoch with the ten genesis certificates as parents (`header proposed round=5 epoch=5 num_parents=10`,
  `validator-05:10:00:59.572`). That header can never be certified, but it is now the stored `LastProposed`.
- the eleven later promotions: `reproposing header current_round=5 header_round=5 primary_round=4` against committed rounds of
  876 to 2,326. Peers refused it 257 times as too old.

The other two inactive validators show the same pattern. validator-07 was promoted 21 times and held once, at the next epoch
entry; its entry into the previous epoch, made 20 rounds behind the committee (round 46 against 66), failed like the mid-epoch
attempts (demoted at `validator-07:09:55:34.5`). validator-08 failed one idle promotion (`validator-08:09:53:42.495`, demoted
`09:53:51.330`) and held when it entered the next epoch at round 2.

User-visible effect: the committee runs one or two voters short for most of an epoch, the inactive validator's RPC answers
`-32603 validator is inactive`, its pooled transactions (6,710 on validator-05) wait, and every failed attempt restarts the
epoch tasks.

## Mechanism

Line numbers are at main 4bf4604d2.

1. **Peers have deleted the rounds a rejoiner needs.** The certificate store deletes every round below the newest round written
   minus `ROUNDS_TO_KEEP` = 64 (`crates/storage/src/lib.rs:66`; `gc_rounds` at `crates/storage/src/stores/certificate_store.rs:157`,
   called from `write` at `:192`). A promoted node restarts consensus from its last handled round `C`
   (`crates/consensus/primary/src/consensus/state.rs:513`), so its certificate manager requires the parents of every
   certificate above `C - gc_depth + 1` (`crates/consensus/primary/src/state_sync/cert_manager.rs:108`) and Bullshark's parent
   check requires the same rounds (`state.rs:242`). The fetcher asks peers for everything above `C - gc_depth`
   (`crates/consensus/primary/src/certificate_fetcher.rs:365`), and peers serve only what their store still holds. With
   `gc_depth` 50 the bottom of that window is gone on every peer once the peers' newest round `H` is 16 or more rounds above `C`.
   The rejoin rule promotes at a gap of up to 20 rounds between `C` and the newest committed leader
   (`crates/consensus/executor/src/subscriber.rs:71`, window from `crates/types/src/primary/mod.rs:84`), and `H` runs a few
   rounds past that leader and keeps moving during the epoch restart. For the first promotion above, the node needed round 681
   and its peers kept rounds from about 689 (inferred from the rounds in the promotion and demotion lines; the fetch lines do
   not log rounds). The fetched certificates wait for parents that no peer has, nothing is accepted,
   `committed_round` stays at `C`, and `behind_consensus` demotes the node when the network reaches `C + 41`
   (`crates/consensus/primary/src/network/handler.rs:215`). An epoch entry escapes while the committee is below round 65,
   because until then no peer has pruned anything; validator-07 entered with the committee at round 66 and failed.
2. **The restored DAG is empty.** The follower path writes consensus output to the pack and never writes certificates
   (`crates/state-sync/src/lib.rs`, `save_consensus`). The gossip handler's store write for an inactive validator is
   unreachable (`handler.rs:331` returns first, see #1516), so `construct_dag_from_cert_store` (`state.rs:143`) finds nothing
   above the GC round. Making that write reachable is not the fix: the rebuild inserts certificates without a parent check
   (`state.rs:157`), and `order_dag` logs and skips a parent that is missing from the DAG
   (`crates/consensus/primary/src/consensus/utils.rs:71`), so a store with gaps lets the node commit a different sub-DAG than
   its peers.
3. **The proposer starts at the wrong round.** `Proposer::new` (`crates/consensus/primary/src/proposer.rs:191`) starts at round
   0 unless the stored `LastProposed` is ahead of `primary_round` (`:227`), with the genesis certificates as parents (`:243`).
   `enough_parents` (`:1007`) only checks that the parents are not empty, so the first max-delay tick proposes
   `primary_round + 1` with genesis parents. A replayed parent set from a lower round than `primary_round` takes the "future
   round" branch (`:608`) and moves the `primary_round` watch backwards. Once a header is stored as `LastProposed`, every later
   start in the same epoch whose round lands on it re-sends it (`:818`, `reproposing header` at `:824`), and the max-delay path
   re-sends `LastProposed` with no round or epoch check (`:1016`, `:1063`). `LastProposed` is cleared only at the epoch
   boundary. On validator-05 `primary_round` was 4 at every promotion although the handled and executed round was 730 or more;
   `prime_consensus` (`crates/state-sync/src/lib.rs:69-93`) should have primed it from the executed round, and why it did not
   is open.
4. **Nothing stops a repeat.** The rejoin rule does not know whether the last promotion held, and `behind_consensus` demotes a
   node that was promoted a few seconds earlier exactly as it demotes one that fell behind.

## Proposal

Each rule is a separate commit. The first is the fix; the others make each attempt cheaper and bound the damage.

1. **Keep the rounds a rejoiner needs.** Raise `ROUNDS_TO_KEEP` from 64 to 128 and check at startup that
   `gc_depth + gc_activity_window(gc_depth) + 10 <= ROUNDS_TO_KEEP`, so a node anywhere inside the demotion window (40 rounds
   at `gc_depth` 50) can fetch the whole window it rebuilds from. Invariant kept: the DAG is still built only from certificates
   whose parents were accepted first (cert manager, `check_parents`); this only changes how long peers keep certificates.
   Cost: about 640 more certificates per node, a few megabytes. Not consensus-observable. It also closes the restart gap in
   #1518 for any lag below 80 rounds.
2. **Start the proposer at the network head.** In `prime_consensus` (CvvActive entry only), seed `primary_round` with the larger
   of the last executed leader round and the newest known header's leader round when that header is from the current epoch;
   leave `committed_round` as it is, because a higher `committed_round` raises the certificate manager's GC round and would
   let certificates in without their parents. In `Proposer::new`, start at `max(recovered round, primary_round)` so replayed
   parents from older rounds are ignored. Do not propose with the genesis parents unless the next round is 1. Re-send
   `LastProposed` on the max-delay tick only when it is from the current epoch and not below the proposer's round. Invariant
   kept: `LastProposed` is not deleted, so the equivocation guard and the restart re-send of the same header still hold; the
   epoch start is unchanged (round 0, genesis parents, round 1).
3. **A short grace after a promotion.** For 30 s after a promotion, `behind_consensus` does not demote on the GC-window rule;
   it logs that it held. The epoch rule still demotes. Use a dedicated constant next to `rejoin_round_window`, not
   `max_consenus_round_timeout`, which is the GC fetch timer. Invariant kept: voting is unchanged (too-new check, execution
   check, parents), so a lagging node can only fail to vote, as it does while inactive.
4. **At most two promotions per epoch.** After two failed promotions the node stays inactive until the next epoch entry, where
   the counter starts again. Invariant kept: epoch-scoped state is reset at the epoch boundary, not at a mode change.
5. **Refuse vote requests while inactive.** Take #1531 rather than writing a second version: it refuses before the parent
   lookups, without a penalty and as a recoverable error, and still re-casts a stored vote.
6. **Bound the voter's wait for execution** to 1 s inside `vote_timeout` (#1782). A voter that is behind answers with a
   recoverable "execution behind" error instead of holding the request. With ten validators and a quorum of seven, up to three
   slow voters do not delay certification. The execution-hash check still runs whenever the wait completes.

Rejected:
- Storing gossiped certificates while inactive and promoting once the store reaches the head. The store must stay causally
  complete (#1516, #1547), it would make the #1518 gap the normal case at every promotion, and it still leaves the bottom of
  the window to peers that have deleted it.
- Shrinking the rejoin window to fit 64 rounds of retention. That leaves about 6 rounds, which a follower under load would
  almost never reach.
- Seeding `committed_round` from the newest header. Certificates would then be accepted without their parents.

## Test plan

- Storage/consensus unit test for rule 1: write rounds 1 to `H` through `write` with pruning, set `C = H - 25` and
  `gc_depth = 50`, and assert every round from `C - 49` is still in the store; the same case with 64 rounds fails today.
- The startup check rejects a `gc_depth` whose window does not fit `ROUNDS_TO_KEEP`.
- `prime_consensus` with a newer same-epoch header seeds `primary_round` from it; with a future-epoch header it does not.
- Proposer tests next to the existing restart tests: a stale `LastProposed` below the seeded round is not re-sent; the
  restart case (stored round above `primary_round`) still re-sends the same header; a seeded round with genesis parents does
  not propose until parents for that round arrive; epoch start still proposes round 1.
- `behind_consensus` with a paused clock: held inside the grace, demoted after it, epoch rule never held.
- Rejoin predicate: the third promotion in an epoch is refused, the counter resets in the next epoch.
- e2e `test_restarts_lagged_under_load` (`crates/e2e-tests/tests/it/restarts.rs:1829`): after the node rejoins, one rejoin
  transition, still active 30 s later, no `outside_gc_window` demotion, new own certificates, no re-proposed header below the
  newest round at the rejoin. The test runs with `gc_depth` 25, where 64 rounds of retention already cover the window, so it
  only reproduces the bench failure when run with `gc_depth` 50.

## The bench-5 fields that prove it

- Per demoted node, `tn_node_mode_transitions_total{to="cvv_active",reason="rejoin"}` rises once per episode, and the node is
  still active a minute later.
- No `Fetch task failed … pending acceptance due to missing parents` after a promotion; `certificate committed` lines resume on
  the promoted node within the grace.
- Kill to first own certificate under two minutes when the follower is inside the window.
- No `reproposing header` with a header round below the rejoin's `newest_round`; no header proposed with genesis parents
  above round 1; the `primed consensus rounds` line shows `primary_round` at or above `newest_round`.
- Grace holds and exhausted attempts both zero; voter refusals while inactive and execution-behind refusals counted per node.

## Related

- #1513 (closed): the distance rule for promotion. It warned that a promotion near the demotion edge would flip back and forth.
- #1518: store pruning and the DAG rebuild count from different rounds. Rule 1 widens the margin; #1529 changes when pruning runs.
- #1516: the inactive store write never runs and must not be revived. This issue agrees and does not revive it.
- #1517: an inactive validator can still sign round-1 votes. Fixed by #1531.
- #1529: prune the certificate store only after a durable commit. Compatible with rule 1; the kept window still has to cover
  `gc_depth` plus the rejoin lag.
- #1531: refuse new votes while inactive. Rule 5 adopts it.
- #1547: skip the certificate-manager path on an inactive validator. Compatible; it removes the per-certificate error lines.
- #1782: a lagging voter holds vote requests on its execution wait. Rule 6 bounds that wait.
