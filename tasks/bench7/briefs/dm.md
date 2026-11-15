# DM — what main's three new commits mean for the bench 7 stack, its PRs and the harness (read-only)

Unit: `DM` (delta analysis, opus; load `tn-rust-skills`, `tn-domain-epoch`, `tn-domain-storage`). Rules: `tasks/bench7-agent-rules.md` (the common sections). Checkpoint: `tasks/checkpoint-bench7-DM.md` (a `status:` header and the list of finished sections, rewritten after EACH section; on start read it and continue from the first unfinished section). Budget: under 200k tokens.
Read-only: git read commands only (`git diff`, `git show`, `git log`, `git merge-tree --write-tree`, `git grep <rev>`), `gh pr view` / `gh issue view` (reads). No checkout, no worktree change, no branch, no fetch, no cargo, no cloud, no `gh` write. Deliverable file: `tasks/bench7/main-delta-33b727fce.md`; if a Write is refused, return its complete text between `===== BEGIN <path> =====` / `===== END <path> =====`.

## The situation

The bench 7 stack is 105 commits on upstream `main` at **M = 45dce89474e1efc7f90c6fbd1e51332cc237ab9b**, in eight heads (repository worktree `/home/drtnarg/coding/telcoin/tn-b7-p2`, local branches; each head contains the one before):

| # | branch | tip | what |
|---|---|---|---|
| 00 | `feat/bench6-switches-obs` | 81a06c4e1 | runtime switch list in `Parameters`, `node switches` line, observability |
| 01 | `test/bench6-e2e-scaffold` | 48dae6a5f | e2e per-node overrides |
| 02 | `fix/1804-vote-queue` | ad83a72f3 | `vote_queue_fix` |
| 03 | `fix/epoch-record-closing-block-check` | cd52dcd81 | the closing-block check (no switch), extends main's stored-record guard |
| 04 | `fix/epoch-record-collector-hardening` | ca258b37c | collector walk past an uncertified epoch, conflict halt, re-certify (three switches) |
| — | `fix/epoch-loop-output-drop` | 38a8012f5 | fix for issue #1860 |
| 05 | `fix/1804-quorum-exec-block` | b608a9eb8 | both vote forms |
| 06 | `fix/1807-digest-order-hold` | fac7a05fb | the own-chain hold |

Pull requests 00-04 into the staging branch (`staging/benchmark-bench6-2026-11`, at M) were about to be opened; their texts are `tasks/pr-bodies/bench6-0{0,1,2,3,4}-*.md` and `bench6-xf-epoch-loop-output-drop.md`. The bench 7 node image is built from this stack on M.
Since M, upstream `main` gained three commits and is at **N = 33b727fcea4f6004d4b0cd2bd7923258e081e94f** (the object is already in `tn-b7-p2`): #1848 `feat(config): bundled bootstrap servers per named chain` (bc571cb8c), #1849 `Storage v2 follow-ups: crash windows, static-file and engine hardening, RPC bounds, operator doc` (d4d53c115), #1855 `Store each transaction once: Transactions rows point into the consensus pack (new datadirs)` (33b727fce).
Already established by the orchestrator (verify, do not take on trust):
- `git merge-tree --write-tree <head> N` conflicts in `crates/config/src/node.rs` from head 00 on and in `crates/state-sync/src/epoch.rs` from head 04 on; `close_epoch.rs`, `node/src/metrics.rs`, `telcoin-network-cli/README.md` auto-merge.
- #1849 makes `stop_on_local_failure` in `crates/state-sync/src/epoch.rs` stop the node, unconditionally, when a certified record from peers conflicts with the node's own record (`EpochDbError::ConflictingRecord`, counted in `tn_epoch.final_state_mismatches_total`). The stack's head 04 does a related thing behind the switch `epoch_record_conflict_halt` (a validated conflicting certified record stops the node at a signer threshold; stable phrase `epoch record conflict halt:`; below the threshold it counts and goes on; notes `tasks/checkpoint-bench7-E3.md`, `-E3-FU.md`).
- #1849 narrows the restored-floor skip of main's stored-record guard in `close_epoch.rs` from "at or below the floor" to "below the floor" (`check_stored_final_state`), and sends the node's own uncertified record 0 through the guard. The stack's head 03 adds its closing-block check beside that guard and keeps the old floor rule for its own skip (`tasks/checkpoint-bench7-E1.md`).

## Sections of the deliverable (in this order; checkpoint after each)

1. **What N changed that the stack touches or calls**: for each of #1848, #1849, #1855, the files and functions that the stack's diff (`git diff M fac7a05fb`) also changes or depends on, with `path:line` at N and one line each on what changed. Include `crates/node/src/manager/node.rs`, `start_epoch.rs`, `close_epoch.rs`, `crates/state-sync/src/epoch.rs`, `crates/config/src/node.rs`, `crates/config/src/network.rs`, `crates/storage/src/consensus.rs` and `consensus_pack.rs` where the stack reads them.
2. **Per head, what a bring-forward onto N needs** (a table: head · textual conflicts (file, how many hunks, mechanical or not) · semantic overlap · what must change · which of the head's tests would need to change). For the two known overlaps give the detail:
   - **Conflict halt (head 04) against #1849's unconditional stop**: compare the two precisely (which records reach each path, validated or not, which nodes, what is counted and logged, whether a restart stops again, what happens below the stack's threshold now that main stops regardless). Then the options for head 04 with their consequences: drop the switch and the threshold in favour of main's stop; keep the stack's line and counters around main's stop; keep both. Recommend one, and say what in PR 04's text (`tasks/pr-bodies/bench6-04-collector-hardening.md`) becomes untrue at N, quoting the sentences.
   - **Closing-block check (head 03) against the narrowed floor rule and the record-0 path**: what the check must do at the floor block and for the node's own uncertified record 0 to stay consistent with main; which sentences of `tasks/pr-bodies/bench6-03-closing-block-check.md` become untrue at N.
   - Also: does N change anything the walk (`epoch_record_collect_past_uncertified`) or the re-certify (`epoch_record_recertify`) relies on.
3. **The posted issues at N**: for each of #1850 (two gaps: an epoch the network never certifies stops every collector; a conflicting certified record is only logged), #1851 (no check that `final_state` is the closing block), #1852 (false quorum error), #1860 (the epoch loop drops a consensus output when pre-empted): is the defect still present at N, with `path:line`; if N fixed or changed it, how, and whether the issue text needs a follow-up comment (draft the comment's facts in three lines, no prose polish). Read the issue bodies with `gh issue view <n> --repo Telcoin-Association/telcoin-network`.
4. **The harness** (`/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/`): would a node image built from N start under the bench harness as it is? Compare M and N for: the CLI flags and environment the deploy passes (read `benchmark/benchmark-deploy.sh` only where it builds the node's start line and the genesis / keygen calls; `benchmark/node-image-contract.txt`), config keys in `parameters.yaml` / the node config the harness writes, the datadir layout the harness's samplers read (`benchmark/node-persist-sampler.sh`, `benchmark/tools/folio-census.py`: headers and path constants only), the log shapes in `benchmark/tools/log-shapes.txt`, and the metric names the export requires (the must-have list in `tasks/bench7/orch-prom-export.py`). #1848's bundled bootstrap servers: what a chain that is not one of the named chains (the bench's own genesis) gets. #1855's "new datadirs": what differs on disk for a datadir created at N. List each harness item as unchanged / changed (what) / cannot tell without running.
5. **What N changes for the measurement**: from #1855's and #1849's descriptions (`gh pr view <n> --repo Telcoin-Association/telcoin-network --json body`) and the diff, what changes in what a node writes per transaction and per block (device writes, syncs, bytes), on which path, and whether a bench run on M would misstate main's disk behaviour at 20,000 IOPS. Say what is stated by the PR and what you infer from code, separately. No estimate without a source.
6. **Effort**: what bringing the stack onto N by MERGE (never rebase or force-push: the heads' commits stay as they are, a merge commit per head or one merge at the top) involves: conflicted hunks, code changes from section 2, tests to change, and which gates would have to re-run (workspace tests, clippy lanes, the repository's e2e sets, the stack's 13 e2e tests, the image). Hours, with what they rest on.

## Rules of evidence

Every statement about code carries `path:line` at a named revision (M, N or a head). Quote identifiers, log texts and metric names verbatim. Mark each conclusion as read from code, stated by a PR text, or inferred. Where you cannot tell without compiling or running, say so and name the exact check. Do not propose code beyond one or two sentences per change.

## Hand back (a summary, not the file)

First: anything that would make a node built from the stack on M misbehave on a fleet, or a PR text false today. Then, in five lines each: the conflict-halt recommendation; the closing-block check's adaptation; the issues' state at N; the harness verdict; the measurement verdict; the effort. Then the path of the deliverable (or its text between markers).
