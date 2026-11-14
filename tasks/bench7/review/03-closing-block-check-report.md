# R-03 topic review: head 03, `fix/epoch-record-closing-block-check` (unit E1)

Verdict: **APPROVE WITH FOLLOW-UPS.**
The topic itself has one Low finding (operator text) and six Info items; nothing in the diff is Medium or above.
Separately, the security evaluation found a **High bug that is not in this diff** (it is on base 45dce8947 unchanged) on a path this topic's code is called from: the leftover drain can make a lagging node execute output X+1 without X.
It is listed first below because of its severity; it does not block this topic, but it can hurt a ten-node benchmark run (see finding 1).

Scope: worktree `/home/drtnarg/coding/telcoin/tn-b7-e1`, `git diff 45dce8947..d3028fad7` (c5e36b674 the check, d3028fad7 the identity counter).
Line numbers are the tip's unless marked "base".
Date: 2026-11-14.

## How this was reviewed

- Code review (tn-review): my own read of the diff and of every engine site that writes a marker the check compares.
- Security evaluation (tn-security-eval): eight read-only agents (model opus), one shared brief, each limited to a named read list: consensus safety, a hand-run logic audit aimed at false positives (the nemesis slot), state transitions, crypto correctness, DoS, determinism, DREAD, STRIDE.
- Not started, because their question cannot apply: contract safety (the diff has no Solidity) and dependency audit (no `Cargo.toml` or `Cargo.lock` change).
- Verification (the skills' own step): one findings-verifier run (opus) over the review's and the evaluation's Low-and-above findings together (V1, V2), each re-checked by an independent sub-agent that saw only the claim, the key question and the files.
  Info items are not verified under the skills' tiering; I checked the ones I cite against the code myself.
- Not re-run, cited: the repository's e2e sets passed on integration head 14372820d, which contains this change (restarts 11/11, epochs 11/11, sigkill 12/12), and no node logged the new halt message (`tasks/bench7/orch-e2e-sets-14372820d-off.log`).
- No cargo, no edits, no commits.

## Findings, most severe first

### 1. High, CONFIRMED, NOT IN THIS DIFF (base 45dce8947 unchanged): the leftover drain forwards X+1 after a cancelled send dropped X

- Location: `crates/node/src/manager/node/run_epoch.rs:484` (`tokio::select!`), `:749` (`recv()`), `:730` (`to_engine.send(output).await`), `:732` (`last_forwarded_consensus_number` set only after the send); `crates/node/src/manager/node/close_epoch.rs:320-340` (Phase 1 of `send_leftover_consensus_output_to_engine`).
  The same lines exist on base; the diff's hunks start at close_epoch.rs:398 and run_epoch.rs:933.
- Sequence:
  1. A validator lags in execution, so `to_engine` (capacity `TO_ENGINE_CAPACITY`, node.rs:898; the engine pulls only while it holds fewer than `MAX_QUEUED_OUTPUTS` = 8, engine/src/lib.rs:61, :326) is full.
  2. `wait_for_epoch_boundary` has taken output X off the consensus-output queue (`:749`) and is parked in `to_engine.send(X).await` (`:730`).
  3. Another arm of the `select!` at `:484` wins: `closed_by_record` (`:549`, a certified record shows the running epoch already closed) or the epoch tasks ending Ok (`:560`, a demotion to sync); `node_ended` (`:485`) is a narrow race.
     The pending send is dropped with X in it, and `last_forwarded_consensus_number` still names X-1.
  4. `finish_epoch` runs Phase 1 of the leftover drain (close_epoch.rs:320-340), which forwards X+1 through `process_output` with no continuity check (the only one is on the live path, run_epoch.rs:756).
     Phase 2 starts from `last_forwarded + 1` only after Phase 1 has moved it (`:347-350`), so X is never backfilled.
  5. Neither the engine's intake (engine/src/lib.rs:160-171, :336-346) nor `execute_consensus_output` (payload_builder.rs:76-110) checks the consensus parent, so the node executes X+1 on top of X-1.
     Its execution diverges from consensus (the leader count of X alone changes the closing block's rewards).
  6. Next, with medium confidence (the catch-up path after this was not read): if the certified record of the epoch is stored, which is likely for a lagging node, base's `FinalStateMismatch` guard stops the node at its close, with divergent blocks already persisted (recovery needs a manual execution reset); if not, the node builds, saves and votes a divergent record that cannot reach quorum alone.
     This topic's new check does not catch it: the closing block's markers are still correct, and `final_state` is compared first.
- The comment at run_epoch.rs:751-755 states the assumption that breaks: "The `consensus_output` queue never drops an output".
  The queue does not, but a cancelled send of an output already taken from it does.
- Fix (verifier's proposal, which I agree with): in `wait_for_epoch_boundary`, take the channel permit before dequeuing (`let permit = to_engine.reserve().await?;` then `recv()`, the batch eviction, and `permit.send(output)`), so no await point holds a dequeued output; as a backstop, run `check_output_continuity` in Phase 1 and fall through to Phase 2's backfill on a gap.
- Before the benchmark image: recommended.
  Earlier benchmark runs saw healthy validators demoted by commit lag (bench 4) and a rejoin loop (bench 3), which is the trigger shape (execution lag plus demotion or `closed_by_record`); one hit costs a node for the rest of the run.
  It belongs to its own unit and upstream issue, not to this topic's PR.
- Severity note: one node out of ten diverges and, in the likely branch, stops; the network is not at risk.

### 2. Low, CONFIRMED: the refusal text gives the wrong reason on the stored and entry paths

- Location: `crates/node/src/manager/node/close_epoch.rs:1555-1556` (`impl Display for ClosingBlockMismatch`).
- The text always ends "stopping the node rather than save, vote on or publish a record that commits another block", whatever `path` is (it is only printed, `:1559`).
  On the stored path the record was read from the store (`:433`), so it is already saved; on the entry path (`:642-650`) record N-1 is stored and, if this node built it, was published and voted at the previous close, and the success branch only clears tables (`:675-676`).
  Base's `FinalStateMismatch` text (`:1295-1309`) says "rather than run on a chain no epoch record attests", which is what the stop prevents on those two paths.
- Effect: operator text only; the node stops through `?` regardless, and no test asserts this clause.
- Fix: choose the clause by path (`Built` keeps "save, vote on or publish a record that commits another block"; `Stored` and `Entry` take base's "run on a chain no epoch record attests").
- Before the upstream PR; not needed for the benchmark image.

### 3. Info: a refusal on the restart re-derive path is logged as `path=built`

- `recover_previous_epoch_record` re-derives a missing record N-1 through `write_epoch_record` (`close_epoch.rs:725-726`), so a refusal there logs `path="built"` and "(built path)", while `RecordCheckPath::Built` is documented as "a record this node builds at the close" (`:1359-1360`).
  Only the preceding warn "previous epoch record missing on restart ... re-deriving it locally" (`:716`) tells it apart.
- Fix: document `Built` as covering the re-derive, or wrap the error at `:726` with re-derive context.
- Before the upstream PR, optional.

### 4. Info: an empty recent-blocks ring on the build path is reported as `check=beacon_root`

- `latest_execution_block()` returns a default header when the ring is empty (`crates/consensus/primary/src/recent_blocks.rs:78-80`); the build-path check then fails with "its parent_beacon_block_root is not that consensus header's digest" (`close_epoch.rs:476-488`), not with its own message as the delta read's change E1.2 described.
- Not reachable in practice: every build-path caller runs after `wait_for_consensus_execution` on the closing output, which always yields a block, or (re-derive) after comparing the ring tip with the executed tip (`:688-697`).
- Fix, optional: an explicit "no executed block" error before the check.

### 5. Info: the engine-equivalence unit test bypasses tn-engine's payload builder

- `a_closing_block_the_engine_builds_passes_the_check` (`close_epoch.rs:2887`) builds blocks with `TNPayload::new` plus `execute_payload_and_update_canonical_chain`, not `execute_consensus_output`, so the empty closing output (payload_builder.rs:182-246) and the `adiri` uneven-batch tolerance (`:138-158`) are covered by reading, not by a unit test of the rule.
  The e2e sets above executed real closes through the engine with no halt.
- Fix, optional: one engine-level test that closes an epoch on an empty output and runs `closing_block_check` on the result.

### 6. Info: the `adiri` feature comment in `crates/node/Cargo.toml` is now stale

- `crates/node/Cargo.toml:46-48` says "tn-node's own adiri code is test-only"; `closing_marker_checked` (`close_epoch.rs:1471-1481`) is now production code under `cfg(feature = "adiri")`.
  The wiring is correct: tn-engine's `adiri` is reachable only through tn-node's (`crates/node/Cargo.toml:49-55`), so the engine's tolerance and the node's skip are always compiled together.
- Fix: update the comment (the file is outside the diff).

### 7. Info: the restored-floor branch still compares nothing

- A closing block at or below the restored-state floor skips both the `final_state` compare and the new markers (`close_epoch.rs:1341`, `:792-801`), exactly as on base, although that block (the snapshot block B) is a real header whose hash the import pins to the certified record (`crates/tn-reth/src/snapshot.rs:648-657`).
  Nothing base checked is lost; it is a scope choice.

### 8. Info: the seed compare is implied by the beacon-root compare

- The sub-dag digest hashes `randomness` (`crates/types/src/primary/output.rs:916`) and the consensus header digest covers the sub-dag digest (`crates/types/src/primary/block.rs:61-80`), so once (a) passes on an engine-built block, `extra_data_seed` can fail only if the engine stops writing `committee_shuffle_seed()` (the accepted residual I6).
  The 32-byte length compare is the part of (c) that adds information: it pins the output's last block.

## Answers to 2a-2g

### 2a. What changed for every node (no switch)

- Build path (`write_epoch_record`): the ring tip is sampled once as a whole header (`close_epoch.rs:419-420`); the boundary header is taken and checked before any committee read (`:476-488`); then the same build, save, persist as base, plus the info line `epoch record published` (`:568`) before the publish (`:569`).
- Stored path: after base's `final_state` compare, `require_closing_block` runs on `Matches` (`:779-790`); the seed comes from the node's own boundary header only when its `(number, digest())` is the record's `final_consensus` (`:441-451`); the info line logs `stored_matched` or `stored_restored`.
- Entry path (every epoch entry): the same compare against the registry pin, seed `None` (`:640-652`).
- `adjust_base_fees`: a counter only (`run_epoch.rs:936-937`); the identity check and its error are unchanged.
- New metrics: `tn_epoch.epoch_record_closing_block_check_total{result}` (`ok`, `beacon_root`, `nonce_epoch`, `extra_data_length`, `extra_data_seed`) and `tn_epoch.epoch_close_identity_check_total{result}` (`ok`, `mismatch`) (`crates/node/src/metrics.rs:52-74`).
  New log lines: the error "epoch record final_state is not the block where the epoch-closing calls ran, stopping the node" and the info "epoch record published".
- What the record contains is byte-identical to base: `parent_state` is `executed_blocks.back()...num_hash()` on both (`recent_blocks.rs:73` base call vs `:78` now), and `final_consensus` is the same `ConsensusNumHash::new(header.number, header.digest())` on the same stashed header, only computed earlier (`close_epoch.rs:479-480`).

### 2b. Mixed fleet

A rolling restart mixes old and new binaries; nothing another validator checks changes.
Records, votes, certificates, headers and blocks are byte-identical (2a), so no fork and no rejection; the change adds only a local stop.

### 2c. Liveness

- The only new way to stop progress is the stop itself; no honest execution was found that triggers it (2g, Q1).
- A stopped node stops again on every restart (the entry check runs at every entry; a build-path refusal leaves no record, so the re-derive at the next entry stops the same way, `close_epoch.rs:682-726`), the same recovery story as base's #1834 guard; nothing is destroyed.
- An entry refusal now skips `clear_stale_epoch_tables` (`:675`), which base would have run: less state changed, not more.
- Not caused by this diff but on its caller path: finding 1.

### 2d. Byzantine or slow peers

Nothing new.
A record enters the store either from this node's own build path (`close_epoch.rs:563`, the only production save without a certificate) or with a super-quorum certificate checked by `validate_downloaded_record` (`crates/storage/src/epoch_records.rs:401-416`; collector `crates/state-sync/src/epoch.rs:272-279`; vote recovery `crates/node/src/manager/epoch_votes.rs:274-295`, which fail-stops on another digest).
A subset committee still needs about 4n/9+1 signers, more than f (`crates/types/src/primary/epoch.rs:145-162`).
`final_state` is compared first, so a peer's record reaches the marker check only if it names the very block this node executed; the seed is only ever the node's own.
A leader or client cannot shape the markers: they come from the certified leader header (nonce), the output digest (beacon root) and the sub-dag randomness (seed), and uneven batches are refused before any block outside adiri <= 160 (`payload_builder.rs:138-158`).

### 2e. Restart and epoch boundary

No new state outlives a call.
The boundary-header stash is now taken before the committee read; a refusal or a committee-read failure leaves it `None` (base left it `Some` on the latter), but nothing can observe that: it has no other production reader, `run_epoch` resets it on every entry (`run_epoch.rs:149`), every caller propagates with `?` before its tables clear (`:253`/`:254`, `:523`, `:645`/`:654`, close_epoch.rs `:726`/`:750`), and `run_epochs` returns the error and the process exits (`crates/node/src/manager/node.rs:1802`; `bin/telcoin-network/src/main.rs:22-25`).
The counters are process-local and restart at zero.

### 2f. Determinism

Nothing consensus-visible changes (2a).
The check's outcome is a pure function of the block header, the record's epoch, `final_consensus` and an optional seed, which are identical on honest nodes once `final_state` matches.
The per-node inputs (seed `None` on entry or without the stash; the restored-floor skip) only weaken the check, so they cannot split the fleet.
No wall clock, iteration order or floating point; `deconstruct_nonce` is plain shifts (`crates/types/src/helpers.rs:284-287`).
The ring has two production writers, both pushing real full headers: the startup restore from the database (`node.rs:1864-1888`) and one update per output carrying that output's last block and its consensus hash in one write (`node.rs:1941-1946`, `crates/tn-reth/src/env/execution.rs:642-648`); so the sample after `wait_for_consensus_execution` is the closing output's last block on every node.

### 2g. The topic's own questions

Q1, false positives.
None found, by me and independently by the consensus-safety, logic-audit and determinism agents.
- Restart in the middle of a close: killed before the closing output executes, replay flags and stashes it by the same predicate (`start_epoch.rs:177-197`); killed after it executes, the entry check compares the registry pin, which is the record's own `final_state` block, or the re-derive looks the header up by the block's own beacon root (`close_epoch.rs:682-726`); an output is persisted in one commit, so reth's tip is always a complete output's last block.
- A follower with records from peers: `final_state` first; an honest record's `final_consensus` is that block's beacon root.
- A snapshot-restored node: blocks at or below the floor are skipped on the stored and entry paths; the build path reaches the floor only by a re-derive at B, which is a real header; scaffold headers never reach the ring (it is filled down to `real_header_floor` only, `crates/tn-reth/src/env/mod.rs:422-427`).
- First epoch and the dummy record: entering epoch 0 returns early (`:615`); the dummy has no certificate, so epoch 0 is always built (`:433-438`) and entering epoch 1 with the dummy goes to the re-derive (`:621`); nonce epoch 0 holds.
- Empty closing output: one empty block with the marker (`payload_builder.rs:182-246`; `output.rs:278-282` is true at index 0 with no digests).
  Several batches: only the last block carries it, and the ring receives that block.
- Leftover or replayed outputs: every stash site returns at the first output that reaches `self.epoch_boundary`, the same predicate `process_output` flags with (`run_epoch.rs:719`, `:777-794`; `close_epoch.rs:323-339`, `:353-369`); the stash is always the output the engine flagged (finding 1 shows a run where that output follows a dropped one, and the check still passes).
- Mode-change re-entry, governance changes to the committee or `epochDuration`: the check reads no contract state and none of the three markers depends on it.
- Adiri: at or below 160, (c) is skipped and (a)/(b) compare the flagged output against itself; above 160 uneven batches stop the engine, so every closing block carries the marker.
  Historical records stay the accepted residual L4.

Q2, a fleet-wide halt.
The rule is the engine's rule in every branch:
- beacon root: both the batch loop (`payload_builder.rs:335-346`) and the empty closing output (`:230-241`) pass `output.digest()`, the cached `digest_from_parts` (`output.rs:143-145`, `:392`), written at `crates/tn-reth/src/evm/block.rs:2150`; `final_consensus.hash` is `ConsensusHeader::digest()` of the same parts, `extra` excluded on both sides (`block.rs:61-80`);
- nonce epoch: `TNPayload::new` sets `output.nonce()` (`payload.rs:140`), the leader's `epoch << 32 | round` (`header.rs:255-256`), copied at `evm/block.rs:2114`; `Epoch` is u32, so `deconstruct_nonce` is exact;
- `extra_data`: written only from `ctx.close_epoch` (`evm/block.rs:2118`), which is set only on `close_epoch_for_last_batch` (`payload.rs:128-134`), always 32 bytes; its value is the stored `sub_dag.randomness` (`output.rs:327`), the field the check reads (`:883`); the fork-gated seed derivations run once at commit time, not at execution;
- the epoch-closing calls run under the same `ctx.close_epoch` (`evm/block.rs:1885`), so the marker and the calls cannot separate;
- adiri: the engine tolerates uneven batches for `output.leader().epoch() <= 160` (`payload_builder.rs:147-159`) and the check skips (c) for record epoch <= 160 (`close_epoch.rs:1471-1481`), evaluated after (b) has shown the record epoch is the leader epoch; tn-engine's `adiri` is only enabled through tn-node's, so both sides share one flag.

Q3, ordering on the build path.
Order now: stored lookup, `take()` (`:476`), check (`:481-488`), committee reads (`:529-547`), `prev_record`, build (`:554`), `save_record` (`:563`), `persist` (`:567`), log (`:568`), publish (`:569`).
Every caller verified (2e): none retries in-process, all propagate before clearing tables, and the stash is reset at every `run_epoch` entry.
A refusal saves and publishes nothing; saved-but-unpublished still arises only from a `persist` failure, as on base.

Q4, what a Byzantine member can do: nothing new (2d).
`final_state` is compared first (`:779-790`), and the seed is used only when the node holds the header the record commits (`:441-451`).

Q5, the restored-floor skip and the entry path with seed `None`.
Nothing base checked is left unchecked: base compared nothing at or below the floor and only `final_state` at entry; entry now also compares (a), (b) and the length of (c).
The seed at entry would need a consensus-store read; given finding 8 it would add nothing on an engine-built block.

Q6, the published line and the counters.
No field leaks anything: every logged value is chain or consensus data already public (block hash, beacon root, nonce epoch, `extra_data`, the seed that `extra_data` carries, `final_consensus`, the record digest); `extra_data` is printed as hex.
Both counters take labels from closed sets of static strings (five values and two); path and branch are log fields, not labels.
The counter has no `path` label, so the path of a refusal is only in the log line; that is enough for an operator, since a refusal stops the node right after the line.

## Residuals from the scope (not re-reported)

L4 (adiri history), I5 (the adiri predicate in two crates) and I6 (the marker rules in two places) stand as stated; nothing found makes them worse.
For L4 the reviews narrowed it: a historical record whose `final_state` is not the closing block already stops a resyncing node on base, so the new exposure is only a record whose `final_state` is right but whose `final_consensus` or the block's nonce epoch disagrees with that block.

## Not examined

- Whether `QueChannel::recv` is cancel-safe (finding 1 assumes a consensus-side lag loses nothing); the catch-up path a node takes after finding 1's divergence.
- Snapshot-restore validation beyond the real-header window and the pinned snapshot block.
- The integration head's copy of these commits (0f7917f29, 14372820d): reviewed on b7/e1 at d3028fad7; the orchestrator reports the cherry-picks as clean.
- No test was compiled or run (no cargo); test bodies were read only where a finding needed them.
