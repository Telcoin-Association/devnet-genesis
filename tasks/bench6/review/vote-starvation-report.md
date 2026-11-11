# Topic review: vote-starvation (#1804; topics `quorum-exec-block` and `voter-lock`)

Reviewed 2026-11-11 against `bench/bench6-2026-11` in `/home/drtnarg/coding/telcoin/telcoin-network-b6`.
- **The diff:** `git show --format= 86755c450 82ed5801a d4be3a435 5d7821dfb 2b9a69925 14b55b04c 8bd68e514 31ef1149c 20858d28d 56f66e160`
  (10 commits, +3582 lines with tests).
- **The switches:** `quorum_exec_block` (bool), `quorum_exec_block_starved_rounds` (u32) and `vote_queue_fix` (bool), all off by
  default.
- **Head:** the scope named head `56f66e160`. The branch moved to `d91d65d3e` during the review. Its five later commits are
  parent-grace fixes and one e2e change. They touch `proposer.rs`, `proposer_tests.rs` and `config/node.rs` but no exec-block
  or vote-path line (grep of the diff).
- **Line numbers:** given at `d91d65d3e`. `handler.rs`, `message.rs`, `error/network.rs`, `metrics.rs`, `recent_blocks.rs` and
  `consensus_bus.rs` are identical at both heads; in `proposer.rs` the numbers moved.

## Verdict: APPROVE WITH FOLLOW-UPS

Nothing is Critical, High or Medium. Nothing has to change before the benchmark image. The review found 3 Low and 5 Info
findings (confirmed or plausible) and 2 unverified Info observations. Two pre-existing items outside this diff are listed
separately.

- **Switch off:** every behaviour is unchanged. The header bytes come from the same call at the same point. With
  `vote_queue_fix` off the voter makes the same waits and the same lock order and gives the same answers. What runs that did
  not run before:
  - pure lookups and early returns in the proposer;
  - four fields on `header proposed`;
  - one registered, never-sampled `prelock_wait` stage series and `prelock_wait_ms=0` on a debug line;
  - an empty map per handler;
  - the switch listing.
- **Mixed fleet:** cannot fork, cannot make honest validators reject each other, cannot stall.
  - Every reader of a header's named block (voter, subscriber, state-sync) only checks that the number and hash are on its
    own chain. Nothing checks that the block is recent, monotonic or the author's tip.
  - `vote_queue_fix` changes answers only, through an existing recoverable wire variant.
  - The e2e test ran a 2+2 mixed fleet across epochs and a restart: one chain, 3 of 3.
- **The central safety question:** an honest proposer never names a block it has not executed. The block is always its own
  ring entry, at or below its tip. Honest proposers never name a block below the epoch's opening block, so even a voter
  restored from an epoch export can check it.
  - The one way below that bound is a Byzantine parent. Combined with an honest restore at an epoch start, it can keep the
    fleet halted after the restored node is back (L1, Low, plausible). The benchmark has no Byzantine member and restores only
    from epoch exports. Fix it before the upstream PR: about 10 lines.
- **The voter change cannot drop a wanted vote.** The certifier cancels every outstanding request before it sends a newer own
  header, so a superseded request is one the author has already abandoned. The pre-lock wait starts on arrival, never later
  than the old wait under the lock.
- **Before the benchmark analysis (no code):** the adaptive policy starts over at every epoch boundary, not only at a restart
  (L2). Each starved fast node pays the 5-10-header climb again in the first ≈ 130 rounds of every epoch. Read the adaptive
  arm with that in mind.
- **For reading run 1:** superseded refusals have no counter. Under the bench's log filter (`primary=debug`,
  `benchmark/config.sh:268`) they are countable from the debug line `vote path timing` `outcome=superseded`. A fleet that
  drops DEBUG sees nothing (L3).

### How the review ran
- **Code review:** the repository's `tn-review` method, run as one agent. Its `findings-verifier` confirmed 4 findings
  (1 Low, 3 Info) and rejected none.
- **Security evaluation:** `tn-security-eval` with seven evaluators:
  - consensus safety;
  - state transitions;
  - DoS;
  - determinism;
  - the nemesis logic audit, run as a general-purpose agent;
  - STRIDE;
  - DREAD, started because one candidate reached Medium.

  Its verifier checked six submitted findings. It falsified the Medium (an honest-only restore halt) and kept two Low and
  three Info.
- **Not started:**
  - contract safety: no Solidity;
  - crypto correctness: no cryptography changed;
  - dependency audit: no `Cargo.toml` or `Cargo.lock` change.
- **Merge:** done by hand. The two reports overlap in three places: the epoch reset (L2), the restore floor (L1 and the code
  review's I1) and the late window (I3, also my own candidate).
- **Verification caveat:** neither nested verifier could start isolated per-finding agents; each checked the claims itself.
  The Medium was falsified twice, once by the verifier from the claim only and once by the DREAD evaluator. To make up the
  rest, I checked these directly against the code:
  - the voter's check (`recent_blocks.rs:120-128`, `:192-207`; `consensus_bus.rs:1705-1757`) and every other reader of the
    field (`subscriber.rs:1223`, `:1385`; `state-sync/src/lib.rs:588`; `consensus/state.rs:786`);
  - the switch-off tip source (`consensus_bus.rs:1354-1356` against `proposer.rs:1933-1937` and `:1974-1977`);
  - the certifier's cancel (`certifier.rs:819-824`) and the order of checks in `vote_request` (`handler.rs:849-935`);
  - L1's premises: `snapshot.rs:1116-1130`, `run_epoch.rs:911`, `message.rs:299-315`, `tn-reth/src/env/mod.rs:483-488`;
  - L2: `run_epoch.rs:226`, `:394`; `primary.rs:109`;
  - L3's gate: `benchmark/config.sh:268`;
  - the code reviewer's open question: the canonical reader is installed in `create_engine` (`node.rs:1825`), before
    `run_epochs`, so before any vote.

## Findings (most severe first)

### L1. A Byzantine low parent plus an honest restore at an epoch start can keep the fleet halted after the restore (Low, PLAUSIBLE)
- **Where:**
  - `proposer.rs:1984-2009`: the weighted walk takes the minimum of a minimal parent set, then floors at 8 ring entries back.
  - `handler.rs:1340`: `BelowRestoreFloor`.
  - `message.rs:299-315`: the catch-all `InvalidHeader(_) => Error` makes it fatal for that header; `handler.rs:1046` caches it.
  - `recent_blocks.rs:199-200`: a restored voter refuses every number below its floor.
- **Premises checked:**
  - A restored floor B is always an epoch-closing block (`snapshot.rs:1116-1130`).
  - The close waits for the closing output to execute (`run_epoch.rs:911`), so every honest member's tip is at least B when
    the epoch starts.
  - The rule counts only same-epoch, round > 0 parents (`proposer.rs:1984`). By induction every honest named block is at
    least B, so honest-only fleets cannot reach this.
  - A restored ring holds output-final blocks only down to B − (`BLOCKHASH_ANCESTORS` − 1) (`env/mod.rs:483-488`).
- **Sequence (n = 4, f = 1; X Byzantine, R honest):**
  1. In the first one or two outputs of an epoch, at a load above about 32 blocks per output, R loses its datadir. The live
     honest proposers now build on minimal parent sets: {own, X, the other honest node}.
  2. X's certified header names an old canonical block. Every honest voter accepts it, because there is no lower bound.
  3. The honest round-r headers take the minimum (I1) and name their floor entry, 8 outputs back, which lies below
     B − 255.
  4. X withholds its votes. The operator restores R from the only snapshot it can use, at B.
  5. R holds the floor block neither in its ring nor in its database and answers `BelowRestoreFloor`, which is final and
     cached per header.
  6. The honest headers can never certify, so the round cannot advance. After a restart the stored header is re-proposed
     unchanged (`proposer.rs` `propose_next_header`, the re-propose branch), so turning the switch off does not help.
  - With the switch off, honest headers name tips at or above B, and R votes.
  - Escape: resync R from genesis or from an older epoch export.
- **What is new:** BFT promises no liveness while f Byzantine members are silent and one honest node is down. It does promise
  that liveness returns once the honest node is back. Here it does not.
- **Fix:** clamp the named block to at least the epoch's opening block (`epoch_info.blockHeight − 1`, passed in through
  `ExecBlockInputs`), and treat parent values below it as unusable in the loop at `proposer.rs:1983-1987`. That turns the
  induction into an enforced invariant. Making `BelowRestoreFloor` recoverable does not help, because the answer never
  changes.
- **Caveat from the security evaluation:** if a mid-epoch or on-demand export is ever added, the honest-only variant returns
  at about Medium, and the clamp does not cover it. That case needs the floor bounded in blocks below the own tip.
- **Gate:** before the upstream PR. The benchmark is not exposed: there is no Byzantine member, and restores come only from
  epoch exports. The clamp is cheap enough to ride along if the image is rebuilt anyway.
- **The code review's Info I1** ("the rule widens the window for a fatal `BelowRestoreFloor`") is this finding without the
  Byzantine step. Without that step it does not happen, by the induction above.

### L2. The adaptive window starts over at every epoch boundary, not only at a restart (Low, CONFIRMED)
- **Where:**
  - `proposer.rs:196` is the field, documented "Epoch-scoped with the proposer"; it is built at `:355-358`.
  - `run_epoch.rs:226` builds a fresh epoch task manager, and `:394` starts the primary on it.
  - The primary then builds a new `Proposer` (`primary.rs:109`), so `next_window`, `certified_streak` and the window bounds
    return to K = 4, 0 and 0.
- **Scenario:** a fast node starved by slow voters has climbed to `next_window = 128`. The epoch ends. In the new epoch its
  first failed tip header opens a 4-round window, and it climbs 4 → 8 → 16 → 32 → 64 → 128 again. That is about 124 rounds
  of windows plus the probes, with one or two cancelled headers per failed return: 5-10 headers, every epoch, on every
  starved node.
- **Gap in the docs:** the cost note at `proposer.rs:1648-1661` and the U1b notes count the ramp only "whenever a regime
  starts or the node restarts".
- **Size:**
  - At the devnet's 3600-s epoch (`devnet-genesis/config.sh:155`) and about 0.86 s per round, that is about 0.1-0.25 % of a
    starved node's headers. It is small, but it lands in the first ≈ 2 minutes of each epoch.
  - The bench steps are where the 0.985 steady-state figure is claimed. A step that contains an epoch start reads lower.
- **Fix:**
  - (a) For the analysis now: leave the first ≈ 130 rounds after each epoch start out of the adaptive arm's steady-state
    share, or report it separately.
  - (b) For the PR, optional: carry only `next_window` and `certified_streak` across epochs in a node-lifetime cell. Never
    carry `window_start` or `starved_through`, because rounds restart each epoch.
- **Gate:** before the benchmark analysis; decide (b) before the upstream PR. The image does not change.

### L3. Superseded refusals leave no counter and no INFO line (Low, CONFIRMED)
- **Where:** `metrics.rs`: `VoteMetrics` has no outcome label. `handler.rs:804-808` counts only votes created and recast.
  The outcome appears only on the DEBUG line `vote path timing` (`handler.rs:817-834`, `outcome=superseded`). The mark
  moves silently.
- **Effect:**
  - Run 1 is not affected: the bench filter `primary=debug` (`benchmark/config.sh:268`) keeps target `primary::network` at
    debug, so the outcome is countable per voter and author.
  - A production fleet that filters DEBUG cannot see which voter refused which author, or how often.
- **Fix:** a `votes_refused_superseded_total` counter, or `vote_outcomes_total{outcome}` fed from `VoteOutcome::as_str`.
- **Gate:** before the upstream PR.

### I1. One low parent sets the quorum value when the parent set is minimal; the design text says it cannot (Info, CONFIRMED)
- **Where:** `proposer.rs:1979-1998`. With the own tip plus 2f other parents, the walk reaches the threshold only at the last
  value, which is the minimum. `test_quorum_exec_block_choice_table` pins it (`proposer_tests.rs:1971`, "f low parents in a
  minimal parent set drag the choice to the floor and no lower").
- **What is wrong:** the issue's design text says f Byzantine parents naming low blocks cannot move the choice
  (`tasks/issue-bodies/bench5-execution-behind-vote-starvation.md:194-196`). That is false for a minimal set: one low parent
  is enough. Lagging honest parents do the same.
- **Bound:** the 8-entry floor and the own tip.
  - Under K = 0 it adds nothing, because the floor is already the steady state (D1).
  - Under K > 0 it moves window headers from about 1 output stale to the floor.
  - It is staleness only, and it is L1's enabling step.
- **Fix:** correct the design and PR text. L1's clamp also removes it below the epoch's opening block.
- **Gate:** before the upstream PR.

### I2. The superseded mark is raised on arrival, before validation (Info, CONFIRMED)
- **Where:** `handler.rs:904-905` with `refuse_superseded_request` (`:1093-1113`). The mark is recorded before the lock,
  before header validation and before the `AlreadyVotedForLaterRound` check (`:991-1000`). Only the author moves its own mark
  (`:849-857`).
- **When it bites:** an honest author's rounds can go backwards inside an epoch only after its epoch database is lost, or a
  `LastProposed` read fails at proposer start. Then:
  - every voter that merely received the higher round refuses the lower ones as `SupersededRequest` (recoverable);
  - voters that decided the higher round also answer recoverably, where they used to answer with the fatal
    `AlreadyVotedForLaterRound`. The requester therefore retries a request that cannot succeed, until its next own header
    cancels it.
- **Bound:** only that author's own slots. The refusals end when its round passes the mark, or at the epoch change.
- **Fix (optional):** consult the decided `auth_last_vote` entry before refusing as superseded.
- **Gate:** before the upstream PR.

### I3. A header that enters the vote window after arrival gets no execution wait (Info, CONFIRMED)
- **Where:** `handler.rs:904-906`: the header is outside the window on arrival, so there is no pre-lock wait and no mark.
  `vote_inner` re-reads the committed round, finds the header in window and checks execution once, without a wait
  (`:1297-1310`).
- **Cost:** one recoverable `ExecutionBehind` and one 250-ms retry. It needs a voter at least `gc_depth` rounds behind on
  commits.
- **Fix (optional):** in `vote_inner`, use the bounded wait whenever the pre-lock wait did not run.
- **Gate:** before the upstream PR.

### I4. The post-wait superseded check and the pre-lock `Closed` path are not pinned by tests (Info, CONFIRMED)
- **Where:** `handler.rs:919-920` (the check after the wait) and `:916-918` (`Closed` during the pre-lock wait).
- **Why the suite cannot catch it:** in every voter-lock test (`network_tests.rs:4875-5583`), the check under the lock
  (`:931-935`) refuses the same requests at the same time. Deleting the post-wait check therefore still passes. No test closes
  the watch during the wait.
- **Fix:** add a contended-lock case: a request superseded during its wait, while another request holds the lock, must be
  refused when the wait ends, not after the lock is released. Add a test that closes the watch during the wait.
- **Gate:** before the upstream PR.

### I5. `quorum_exec_block_starved_rounds` is not validated (Info, CONFIRMED)
- **Where:** `crates/config/src/node.rs`: `Parameters::validate` does not read it. The value is used at
  `proposer.rs:1819-1858`.
- **Behaviour:**
  - A value above 128 is used as is and never doubled.
  - A very large K makes the first window effectively permanent, which turns the policy into `always`. It does not panic,
    because the arithmetic saturates.
  - A non-zero K with `quorum_exec_block: false` is silently ignored.
- **Fix:** warn on K > 0 while the switch is off, and reject or clamp K above `QUORUM_EXEC_BLOCK_MAX_STARVED_ROUNDS`.
- **Gate:** before the upstream PR.

### Unverified Info observations (carried as reported, not counted)
- **A restored proposer's ring holds imported, stateless output-final headers in [B−255, B).** The rule could name one only
  through a Byzantine low parent; the hashes are canonical. The doc comment that the block is "always this node's own
  execution" (`proposer.rs` `choose_exec_block` docs) is inexact there. (Security evaluation, not verified.)
- **Test coverage of the mixed fleet.** The mixed-fleet e2e runs only K = 4 together with `vote_queue_fix`
  (`exec_block.rs:93-103`). It does not run a K = 0 mixed fleet, `vote_queue_fix` alone, or a restored member. No unit test
  uses a voter with `restored_state_floor = Some(B)`.
  - The old-block voter answers are pinned with `vote_queue_fix` both off and on: `network_tests.rs:5583` and `:5629`, ring
    and canonical-database paths.
  - So the direction "rule-on proposer, voter without `vote_queue_fix`" is covered by unit tests, not by e2e.

### Accepted residuals checked and not worse than stated
- **D34:** the per-author lock wait was already outside `vote_timeout`, which wraps only `vote_inner`
  (`handler.rs:1007-1010`). With the switch on, the lock is held for less time.
- **D35:** changes form, not size. With N requests from one author, N tasks were parked on the lock before; now N tasks
  wait up to 1 s each on the execution watch. Both are bounded by the same serve budget.
- **D70, D71, D1, D29, D30:** unchanged by anything found here. L2 adds an epoch-start trigger to D71's "staleness, not
  starvation" reading.

### Pre-existing, outside this diff (not counted)
- **`TooNew` is fatal and cached.** It maps to a fatal `Error` and is cached in `auth_last_vote`, so a later lower round from
  the same author is refused `AlreadyVotedForLaterRound` (`vote_queue_fix_far_future_round_does_not_move_mark` shows it).
  This came from the code review.
- **A restored voter's ring disagrees with its database.** For blocks in [B−255, B), the ring answers `Match` while the
  database refuses them (`recent_blocks.rs:120-127` against `tn-reth/src/env/helpers.rs:646`). This came from the security
  evaluation and is not verified.

## Answers to 2a-2g

### 2a. Switch off = before
Yes. With all three switches at default, every decision path is the previous one.
- **Header bytes:**
  - `ExecBlockInputs::choose` with `ExecPolicy::Off` (`proposer.rs:1933-1937`) makes the previous call,
    `consensus_bus.app().latest_execution_block_num_hash()`.
  - It runs at the previous point: synchronously at `:440`, after `created_at`, before `Header::new`, with no await in
    between.
  - `test_quorum_exec_block_switch_off_keeps_header_bytes` (`proposer_tests.rs:2338`) compares the encoding and the digest.
- **With `quorum_exec_block` on and the adaptive policy outside a window (`Tip`), the block also comes from the same
  source.** `choose_exec_block` returns `ring.latest_execution_block_num_hash()` (`:1974-1977`) from the same watch that
  `ConsensusBusApp::latest_execution_block_num_hash` reads (`consensus_bus.rs:1354-1356`). Tip headers are byte-identical to
  switch-off headers.
- **Lines that now run with the switches off, none of which changes a decision:**
  - The `ExecBlockPolicy::new` field init (`proposer.rs:355`).
  - The own-certificate scan and `on_certified`, which returns at `!adaptive()` (`:1253-1258`, `:1849`).
  - `ExecBlockInputs::new`: two committee lookups and an empty parents vector (`:1259-1264`).
  - `on_cancelled`, which returns at `!adaptive()` (`:1007`, `:1819`).
  - Four fields on `header proposed` (`:489-492`; with the switch off `exec_block` = `exec_tip`, `exec_basis=tip`,
    `exec_policy=off`).
- **Voter with `vote_queue_fix` off:**
  - Every new await, lock and mark access sits behind `if parameters().vote_queue_fix` (`handler.rs:898-922`, `:931-935`).
  - The per-author lock is still the first lock.
  - `vote_inner`'s `timeout(..).await.ok()` (`:1311-1318`) maps one-to-one onto the old match: `Elapsed` gives `None`, then
    `ExecutionBehind`, with the same counter.
- **Visible but harmless:**
  - The `stage="prelock_wait"` histogram and timeout series are registered and never sampled.
  - `prelock_wait_ms=0` appears on the debug `vote path timing` line.
  - The `VoteStage::index` shift is internal, since series are keyed by label.
  - An empty `newest_vote_requests` map is allocated per handler.
  - The three switches appear in `Parameters::switches()`, which feeds the `node switches` line and the `tn_node_switch`
    gauge.
  - The new `message.rs` and `error/network.rs` arms are reachable only when a `SupersededRequest` exists, and only the switch
    creates one.

### 2b. Mixed fleet
No fork, no cross-rejection, no stall.

**What the switches change that another validator checks:**
- `quorum_exec_block` changes one consensus-visible thing: the header's `latest_execution_block`. It is in the wire bytes
  and the digest.
- Every validator checks that field by membership only:
  - **Voters:** ring by number and hash, then the canonical database; the only lower bound is a restored floor
    (`recent_blocks.rs:120-128`, `:192-207`).
  - **Subscribers:** the same check. Only a different hash at that number shuts the node down, and the wait floor is a
    running maximum (`subscriber.rs:1223`, `:1385`).
  - **State-sync:** the same wait and check (`state-sync/src/lib.rs:588`).
- Nothing else reads the field: `Header::validate` and certificate verification do not, and `consensus/state.rs:786` only
  logs it.
- `vote_queue_fix` changes only the voter's answers. `SupersededRequest` travels as the existing `RecoverableError` wire
  variant (`message.rs:296-298`) with no penalty, and old requesters retry it.

**Both directions:**
- **Rule-on proposer, rule-off (or older) voter:** the voter sees an older block on its own chain and matches it, from the
  ring or from the database. The voter is not touched by `quorum_exec_block` at all.
- **Rule-off proposer, rule-on node:** headers name tips, exactly as before.
- **`vote_queue_fix` on the voter, either requester:** requests that are still wanted are answered as before. Abandoned ones
  get a recoverable refusal the requester was no longer waiting for.
- **`vote_queue_fix` off on the voter:** unchanged.

**Evidence and the exception:**
- E2e: two nodes with nine switches on (K = 4, `vote_queue_fix`) and two with none formed one chain across epochs 0-2 and a
  restart, with matching certified epoch records, 3 of 3 (`exec_block.rs:866`, ST-A).
- The only exception found needs a Byzantine member and a restore (L1).

### 2c. Liveness under the switch
- **Nothing is delayed without bound:**
  - The pre-lock wait is bounded at 1 s (`handler.rs:908-912`).
  - A window always ends, at most 128 rounds past the proposer's round (`proposer.rs:1819-1845`).
  - A cancel report dropped because its queue was full only skips a window (`certifier.rs:780-787`).
  - Batch digests and the epoch close are untouched: `on_cancelled` runs first in `process_uncertified_header`
    (`proposer.rs:1007`) and returns nothing.
- **Nothing is dropped:**
  - A superseded request is always one the author already cancelled. `certifier.rs:819-824` notifies `new_proposal` before
    any different own header is proposed, and identical re-sends keep the in-flight proposal.
  - Same-round retries and the missing-parents resend pass the strict `<`.
  - A restart re-proposes the stored same-round header.
- **The execution window is not shortened:**
  - Before, a request waited for its lock turn and then up to 1 s.
  - Now it waits up to 1 s from arrival, then for its lock turn, then checks again without a wait. Execution can advance
    during both waits.
  - The two exceptions cost one 250-ms retry each: I3, and an `Unconfirmed` database read under the lock that the old code
    would have retried for 200 ms.
- **Costs that remain:** the epoch-start ramp under K > 0 (L2), D1's staleness under K = 0, and the halt in L1, which needs
  a Byzantine member.

### 2d. Byzantine or merely slow peers
- **One faulty parent:**
  - In a minimal parent set it drags honest headers to the floor: at most 8 entries stale, and nothing added under K = 0
    (I1).
  - High values are capped at the own tip (`proposer.rs:1995`), so a header is never less votable than with the switch
    off.
  - f high parents can push the choice to a block that only f+1 honest members hold, which is today's starvation, no worse.
- **f Byzantine members with an honest restore:** L1.
- **A Byzantine author:** can move only its own mark (`handler.rs:849-857`), and can hold each of its own requests up to 1 s
  before validation (D35). That is one watch receiver and one timer per request; nothing is sized by peer data.
- **f Byzantine voters plus one laggard:** hold an honest node in long windows (D70, staleness only).
- **A slow honest voter:** opens windows for faster nodes (D71). It refuses only blocks it has not reached, as before.
- **A restored honest voter:** never refuses an honest header after the restore (the induction in L1).

### 2e. Restart and epoch boundary
- **`ExecBlockPolicy`** (`next_window`, `window_start`, `starved_through`, `certified_streak`) lives in the per-epoch
  `Proposer`. It resets at every restart and at every epoch change (L2).
  - Under K = 0 there is no state.
  - Under K > 0 the ramp is paid again.
  - Carrying `next_window` and the streak across epochs would be reasonable. The window bounds must not be carried.
- **`newest_vote_requests`** lives in the per-epoch `RequestHandler` (`network/mod.rs:2433`), so it starts empty after a
  restart and at each epoch. That is safe: the durable `Votes` store and `auth_last_vote` remain the equivocation guard, and
  a superseded refusal is never cached (`handler.rs:931-937`).
- **The recent-blocks ring** is node-wide (`manager/node.rs:790`, capacity `gc_depth`) and spans epochs. The canonical reader
  is installed in `create_engine` (`node.rs:1825`) before `run_epochs`, so before any vote: a ring miss after a restart goes
  to the database, not to `Fork`.
- **Old blocks at epoch start:** at round 2 and later of an epoch, honest headers can name the previous epoch's closing block
  and nothing older. Nothing minds, and only a restored voter could (L1).
- **The epoch-close canary (accepted residual D2):** with the rule on, the epoch-close divergence check looks at an older
  block. I-4 therefore recommends `epoch_record_state_check` on in every arm that has `quorum_exec_block` on.

### 2f. Determinism
Nothing consensus-visible depends on iteration order, the wall clock or thread timing in a way that matters.
- **The header's named block is the author's own choice.** No other node recomputes it; certified, its bytes are ordered
  identically everywhere.
- **The choice itself:**
  - It is a weighted quantile, so the order among equal numbers cannot change it (`proposer.rs:1989`).
  - The `BTreeSet` only removes duplicate authors.
  - The ring read happens at the same point as the old tip read.
- **Timing-dependent state is author-local by design:** the adaptive window follows local cancel timing.
- **`newest_vote_requests`** is never iterated.

### 2g. The scope's questions
1. **Older named block at the voter; lower bounds.** A header that names a block the voter has executed is always
   acceptable, however old: the voter checks only that the number and hash are on its chain (`recent_blocks.rs:120-128`;
   database `:192-207`), with no wait (`network_tests.rs:5583`, both switch values).
   - The only lower bound a voter enforces is a snapshot-restored floor (`BelowRestoreFloor`). There is no staleness bound
     and no epoch or first-block bound.
   - Restores are epoch-closing only (`snapshot.rs:1116-1130`). Honest named blocks never fall below the epoch's opening
     block: by induction over same-epoch parents, with every tip at least B at the start (`run_epoch.rs:911`).
   - A Byzantine parent can push the choice below it (L1, I1).
2. **Can the rule name an unexecuted block, or one on another fork?**
   - Never an unexecuted block. The block is always the proposer's own ring entry, `nth_newest(8)` or
     `newest_at_or_below(v ≥ floor)` (`proposer.rs:2000-2009`), and ring entries are pushed after execution and persist.
   - A diverged proposer names its own chain. It can pass for up to 8 entries on a pre-divergence block, which is the
     accepted canary residual.
   - The evidence of what a quorum executed is the parents' certified named numbers, each matched by at least f+1 honest
     voters.
   - Downward skew: one low parent in a minimal set (I1), bounded by the floor.
   - Upward skew: capped at the own tip, so honest headers are never less votable than with the switch off.
3. **The adaptive state: K never resets, or resets every round.**
   - **Never resets:** in any regime where a cancel report arrives at least once per 64 certified tip headers. That covers
     latency cancels (D71), and any report restarts the streak, ignored or not (`proposer.rs:1819-1826`).
     - The node then sits in 128-round windows separated by one- or two-round probes.
     - While it is ahead it names a block about one output stale, or the floor if the whole fleet is in windows. Otherwise
       the cap gives its own tip.
     - That is staleness, not lost headers: about 2 per 130 at the bound.
   - **Resets every round:** impossible since `20858d28d`, which needs 64 consecutive certified tip headers. With the old
     rule, alternating success reset it every six rounds (0.81 in ST-A).
   - **Restart and epoch:** the state survives neither (L2). For the PR, carrying `next_window` and the streak would remove
     the per-epoch ramp.
4. **`vote_queue_fix`: dropped or late votes, and starvation across peers.**
   - No vote for a valid, still-wanted header is dropped. Only strictly lower same-epoch rounds of the same author are
     refused, and the certifier has already cancelled those.
   - None is answered later than before: the wait starts on arrival.
   - The only lost waits are I3 and the `Unconfirmed` retry under the lock, one retry each.
   - One peer cannot starve another. Marks and locks are per author and moved only when the peer is the author. The
     `parking_lot` mutex is never held across an await. The only shared resource is the serve budget (D35).
   - A mark can hold back an honest author only after that author's round goes backwards (I2).
5. **Mixed fleet, both directions:** see 2b. There is no fork, rejection or stall. Voters never read the proposer switches,
   and the voter switch changes only answers, over an existing recoverable variant.

## Not examined
- **Nothing was compiled or run.** Tests were read, not executed, because `cargo` was off-limits.
- **Test bodies:** most bodies of the new unit tests were read only by name, apart from the choice table, the switch-off
  byte test and the old-block voter tests.
- **E2e:** the e2e file was read lightly. The adaptive arm's 0.88 threshold leaves about 4 points of margin over the three
  measured runs (0.922-0.931) and may flake on a loaded machine.
- **Other topics:**
  - The five parent-grace commits after `56f66e160`, beyond a grep showing they change no exec-block or vote-path line.
  - Whether the pipelined-persist topic keeps "the ring is pushed only after a block is persisted" true
    (`consensus_bus.rs:1740-1741`). If it does not, `Unconfirmed` under the lock (an `ExecutionBehind` with no wait when
    `vote_queue_fix` is on) becomes more frequent.
- **Network internals:** how libp2p maps a peer id to a BLS key, inbound request limits, and the serve budget.
- **BelowFloor handling:** the subscriber's and state-sync's handling of `BelowFloor` on restored nodes, beyond the
  membership check.
- **Fleet dynamics:** not modelled. The sizes in L2 and in the D70/D71 readings rest on the U1b model table and the
  devnet's epoch length. The bench fleet's epoch length was not confirmed.
- **Verification isolation:** findings L3, I2, I4 and I5 were checked only by the nested verifiers, without isolation.
