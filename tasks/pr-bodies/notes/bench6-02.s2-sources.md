# Sources: bench6-02-vote-queue.md (#1864), second pass: the switch goes in {{pr-09}} (not posted)

Facts file: `tasks/bench8/pr9-facts.md`, sections "For operators", "R2" and "Limits the plan already names".
Bench 7 arms: `benchmark/arms/bench7-always.arm` and `benchmark/arms/bench7-adaptive.arm`.
Untouched: the stack-position lines, the merge-method sentence, the `Stack-wide gates` block, the Change list (true of this diff), the Problem section.
Line numbers are those of the edited file.

## Changed sentences

1. Summary :3.
   Old: "Adds the runtime switch `vote_queue_fix` (default `false`, main's behaviour) for the voter's side of #1804."
   New: "Adds a fix for the voter's side of #1804 behind the runtime switch `vote_queue_fix`, new in this PR (default `false`, main's behaviour)."
   Source: brief point 1 (say the change is behind the switch); same facts as before. "Fixes" avoided next to `#1804` so GitHub does not read a closing keyword.
2. Summary, new :7.
   New: "{{pr-09}}, the last PR of the stack, removes the switch and makes the change the node's behaviour: once the stack is collapsed into #1862 there is no switch, every voter waits before the lock, and a node starts only with `vote_timeout` below 9 s."
   Source: brief point 1; pr9-facts R2 "Gone" ("A voter always waits for the execution block a header names BEFORE the author lock"); "For operators" bullet 2 ("`vote_timeout` must now be strictly below 9 s for a node to start").
3. Heading :42.
   Old: "## With the switch off". New: "## The switch, and where it goes" (brief point 1's example).
4. :44.
   Old: "Every vote decision is main's." New: "In this PR's diff, with the switch off, every vote decision is main's." (brief point 1).
5. New paragraph :47-52, six sentences.
   - :47 "{{pr-09}}, the last PR of the stack, removes the switch and with it the switch-off path, the wait for execution under the author lock." Source: R2 "Gone: the switch; the wait for execution UNDER the author lock."
   - :48 "After it, every voter waits for the execution block a header names before the author lock, at most 1 s, and refuses a request that a newer request of the same author has superseded; once the stack is collapsed into #1862 there is no switch." Source: R2 "Gone" bullet, its second sentence, nearly verbatim (`VOTE_EXECUTION_WAIT` = 1 s).
   - :49 "{{pr-09}} also deletes this PR's switch-off tests, among them the first commit's test that pins main's wait in turn." Source: R2 "Deleted tests": `vote_queue_fix_off_refuses_malformed_header_without_the_wait`, `vote_queue_fix_off_answers_repeat_of_voted_header_from_cache`, `vote_queued_requests_of_one_author_wait_in_turn` ("#1864 added it to reproduce #1804"); the first commit is `84c517cf1` "pin that one author's vote requests wait in turn on its lock: main's behaviour, kept as the switch-off regression" (body :27). Not named in the text: the name at this PR's head was not checked against the name R2 gives.
   - :50 "So review the change as unconditional: what speaks for it is no longer the off state but the on arm, that is the unit tests under Testing, the stack-wide gates below run with the six switches on, `make test-upgrade` with main at 33b727fce as the previous binary among them, and the bench 6 and bench 7 runs that ran this switch on." Source: brief points 1-2; the body's Testing list (:59); the gates block (:75-76: "once with every switch off and once with the full stack's six switches on"; "`make test-upgrade` with main at 33b727fce as the previous binary … passed with every switch off and with the six on"); bench 6: body :20 ("an earlier version of this switch … in all four runs"); bench 7: `bench7-always.arm:10` and `bench7-adaptive.arm:10` `param vote_queue_fix true`.
   - :51 "The rolling-upgrade test ran beside main, not beside `v0.17.0-adiri`." Source: pr9-facts "Limits the plan already names", last item.
   - :52 "A `parameters.yaml` that still sets `vote_queue_fix` loads after {{pr-09}}; the node ignores the key." Source: pr9-facts "For operators" bullet 1 (`Parameters` has no `deny_unknown_fields`, `crates/config/src/node.rs:273`; test `unknown_keys_are_ignored`, `node.rs:1765` at a5be61615).
6. Mixed fleet :54.
   Old: "A mixed fleet is one chain: only a voter's answer changes, …"
   New: "A mixed fleet is one chain, whether its nodes set the switch differently (this PR's diff) or run main beside the stack (a rolling upgrade): only a voter's answer changes, …"
   Source: pr9-facts "What the PR is" ("The mixed fleet is covered by `make test-upgrade` with `main` as the previous binary"); the rest of the sentence is unchanged.
7. :55.
   Old: "… a switch-off voter decides as main does …" New: "… a voter on main, or with the switch off, decides as main does …" (the body's own :44: off is main's decision).
8. Testing :67-68 (stale-phrase item, old :59).
   Old: "Not run: no e2e test covers the switch, and no benchmark has run this head; a benchmark of the stack's earlier form on main at 45dce8947 runs it on, with the author-side switch, and has not finished."
   New: "Not run: no e2e test covers the switch, and no benchmark has run this head." and "Bench 7 ran the stack's earlier cut on main at 45dce8947 with this switch on, beside the author-side switch of #1868: the always-on form of that fix in [r20261115-1131](…), the adaptive form in [r20261115-1653](…), ten validators at 20,000 IOPS, one run each; #1868 and #1869 report its results."
   Sources: brief point 6 (ran 2026-11-15, the two run ids, 45dce8947); `bench7-always.arm:8,10` and `bench7-adaptive.arm:8,10` (`param quorum_exec_block true`, `param vote_queue_fix true`); #1868's body `tasks/pr-bodies/bench6-05-quorum-exec-block.md:23` ("the always-on form in [r20261115-1131], the adaptive form in [r20261115-1653]", "at 20,000 IOPS with ten validators"); #1869's body `bench6-06-digest-order-hold.md:67` ("ten validators at 20,000 IOPS, one run each"). No result stated.
9. Limits :86-87, the 800-waits bullet gains a second line.
   New: "Only the authenticated author can cause it, and on main N queued requests held their tasks for up to N × 1 s; counting waiters per author and answering `ExecutionBehind` at once past a small cap would bound it."
   Source: R2 "Three more points", third ("Only the authenticated author can cause it, and on `main` queued requests held their tasks for up to N × 1 s. A possible follow-up: count waiters per author and answer `ExecutionBehind` at once past a small cap"). The bullet's first line (800 = 8 × 100) is unchanged.
10. Limits :89-90 (old :79).
   Old: "The mark moves before the header checks: a malformed header below it gets `SupersededRequest`, not its penalty."
   New: "The mark moves when a request arrives, before the header checks, not when a vote is cast." and "A newer request that is itself refused or dropped still makes every lower round of that author `SupersededRequest`, even if this voter never voted for the newer round, and a malformed header below the mark gets `SupersededRequest`, not its penalty."
   Source: R2 "Three more points", first.
11. Limits :91, new: "A cached refusal is replayed under the lock, so a repeat of a refused header that names a block this voter has not executed waits up to 1 s before its cached answer; on main it came at once." Source: R2 "Three more points", second.
12. Limits :93 (old :81).
   Old: "Compare `total_ms` across settings, not `lock_ms`."
   New: "Compare `total_ms` with main's, or across switch settings in this PR's diff, not `lock_ms`: the change moves the execution wait from `lock_ms` to `prelock_wait_ms`." Source: the body's own :21.
13. Limits :94-98, new bullet with four sub-bullets: the four points in which a voter's answer differs from main after {{pr-09}}, and "{{pr-09}} changes four of main's own tests to assert the new answers". Source: R2 "What a voter answers differently from `main`", items 1-4, close to verbatim (tier three, `InvalidTimestamp`, 1 s, vote window).
14. Limits :99-100, new: `SupersededRequest` is not a new wire type; `PrimaryResponse::RecoverableError(String)`, "which main already has (0554efd4f)"; retries "up to 6 times at 250 ms, then with backoff until its next proposal cancels the request"; `AlreadyVotedForLaterRound` as `PrimaryResponse::Error`, fatal for that voter and header; no penalty either way; retries instead of one give-up. Source: R2 "On the wire and on the requester".
15. Limits :101-102, new: `vote_timeout` strictly below 9 s a start condition for every node after {{pr-09}}; plus 1 s under the 10 s request timeout, on entering any epoch the node can vote in; 8.999 s passes, 9 s refused; code default and mainnet preset 5 s, testnet preset keeps the default; a node at 9 s or more does not start. Source: pr9-facts "For operators" bullet 2 (`validate_vote_timeout`, `crates/config/src/consensus.rs`; `VOTE_EXECUTION_WAIT` 1 s, `LIBP2P_REQUEST_TIMEOUT` 10 s) and "Limits the plan already names", first item.
16. Related :108-109.
   Old: "- Refs #1804: the voter's side only; the author's side is `fix/1804-quorum-exec-block`, which builds on this head."
   New: the same with "#1868 (`fix/1804-quorum-exec-block`)", and a second line "A closing keyword for #1804, if the stack closes it, is in #1862's body, the only PR of the stack that merges into main." Source: brief point 4; the orchestrator's prompt. `Refs #1782` unchanged.
17. Related :112 (stale-phrase item, old :90).
   Old: "Next: `fix/epoch-record-closing-block-check`, `fix/epoch-record-collector-hardening` and `fix/epoch-loop-output-drop` build on this head."
   New: "Next: #1865 (…), #1866 (…), #1867 (…), #1868 (`fix/1804-quorum-exec-block`) and #1869 (`fix/1807-digest-order-hold`) build on this head, and last {{pr-09}}, which removes the stack's switches." Source: brief "What happened" (the stack's numbers and branches).

Left out of the text from R2: the coverage gap of `test_vote_cached_across_dropped_request`, the design note on an immediate tier-three refusal, and the renamed tests; they belong to {{pr-09}}'s own body.
`{{pr-09}}` placed: 8 (Summary 1, the retitled section 3, Limits 3, Related 1).
