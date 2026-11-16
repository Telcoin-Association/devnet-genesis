# The bench 8 node build: every new parameter, log field, line and metric, verbatim

Private. The orchestrator's file, written from the units' hand-backs; the harness's kept-shape filter and parsers and the analysis scripts are written from it.
Branch `bench/bench8-2026-11` (worktree `tn-b8-bench`) and the side chain `b8/side` (worktree `tn-b8-bench2`), both from 91a15e223 (bench 7's image commit). The side chain is cherry-picked onto the bench branch before the image is built.
An authority is always rendered as its full base58 `AuthorityIdentifier` (about 44 characters; the node has no short form). Lists are `[a,b,…]`, no spaces, in `AuthorityIdentifier` (byte) order unless a row says "arrival order".

## Parameter (B8-1: 77d7909c1, 19074c301)

- `quorum_exec_block_floor_outputs`: `u64`, flat `Parameters` field, default 8, left out of a written `parameters.yaml` at 8.
- Listed LAST in `runtime_switches!`: the `node switches` line ends with `quorum_exec_block_floor_outputs=<n>`; the gauge `tn_node_switch{name="quorum_exec_block_floor_outputs"}` carries the count.
- Read once in `Proposer::new`; the proposer names, under the rule, the quorum value floored at the ring entry that many block-bearing outputs back from its own tip (or the oldest entry of a shorter ring).
- Refused when each epoch's consensus config is built (`Parameters::validate_operational_floors`, reached from `configure_consensus`, `start_epoch.rs:452` → `ConsensusConfig::new_for_epoch`), so a bad value stops the node at its first epoch start: outside `1..=gc_depth`: `quorum_exec_block_floor_outputs {v} must be at least 1 and at most the {gc_depth} entries of the recent-blocks ring (gc_depth)`. The ring is built with `gc_depth` entries (`crates/node/src/manager/node.rs:800`). A floor equal to `gc_depth` names the oldest entry of a full ring, `gc_depth`-1 back.
- Proposer-side only: no voter code reads it. A restored voter gets no new refusal from an honest proposer.
- At 8 the named execution block equals 91a15e223's on all 20 golden rows (4 rings), and every other header byte is built by unchanged code; at 16 exactly 8 rows differ.

## `header proposed` (target `consensus::metrics`, INFO) — appended after `blockers`, in this order (B8-1b: 1f87d7860)

| field | type | meaning |
|---|---|---|
| `exec_quorum` | u64, block number | the highest number the own tip and the counted parents, holding at least a quorum of power, reached; after the parent filters (another epoch, round 0, below the epoch's opening block, the own certificate, a repeated author) and BEFORE the cap at the own tip, the floor and the final opening-block bound, so it can be above `exec_tip`; 0 when the rule did not run (`exec_policy=off`, the tip policy outside a window, an empty ring) or the usable power is short of a quorum |
| `exec_floor` | u64, block number | the ring entry `quorum_exec_block_floor_outputs` back from the tip (the oldest entry of a shorter ring); on every header under the rule; 0 when the rule did not run; it may lie below the epoch's opening block (and below `exec_block`) during an epoch's first `quorum_exec_block_floor_outputs` block-bearing outputs, and is then never named |
| `parents` | list | the authors of the parent certificates the header names; one per parent (= `num_parents`) |
| `pending_unheld` | usize, digests | `pending_before` minus `held` (digests the order hold did not keep back); equals `pending_before` with the hold off |

Sample tail (authorities abbreviated here; the node logs the full base58, about 44 characters): `… held=1 held_lanes=1 blockers=1 exec_quorum=0 exec_floor=0 parents=[7TcAuZ…3fZL,C7mwJb…9k2t,HPRfph…fFP9] pending_unheld=1`

## `vote path timing` (target `primary::network`, DEBUG) — appended after `total_ms`, in this order (B8-2: fbea152d4; B8-2b: 42f9bdb32, 5a81a11f5)

| field | type | meaning |
|---|---|---|
| `exec_named` | u64 | number of the execution block the header names |
| `exec_tip_arrival` | u64 | this voter's latest executed block number when the request arrived, before any wait; 0 while the ring is empty (start-up) |
| `exec_tip_answer` | u64 | the same when the answer was decided (for a vote: after it was stored, so a few ms later); 0 while the ring is empty |
| `exec_deficit_outputs` | u64, ring entries | block-bearing outputs the voter still had to execute at arrival to hold the named block: 0 when held; else the ring entries above the arrival tip up to and including the first at or above the named block; a lower bound when `exec_deficit_open=true` (and 0 for an open request refused before any output executed) or when more outputs than the ring holds ran |
| `exec_deficit_open` | bool, on every line | true when the named block was above the arrival tip and still not in the ring at the answer, for ANY outcome, including requests refused on arrival without a wait (`exec_deficit_outputs` is then the outputs executed between arrival and answer, often 0): split by `outcome` and by `prelock_wait_ms + exec_wait_ms > 0` in analysis |
| `superseded_by_round` | u32 | outcome `superseded` only: the round of the author's newest request mark at the refusal (may be more than one above this request's round); else 0 |
| `superseded_after_ms` | u64 | outcome `superseded` only: from this request's arrival to the first arrival of that round's request that raised the mark (from its author, inside the vote window); 0 when the newer request had arrived first (refused on arrival); else 0 |

Histogram `tn_primary_vote_exec_deficit_outputs{open="true"|"false"}` (crate name `tn_primary.vote_exec_deficit_outputs`), one sample per request, buckets 0, 1, 2, 4, 8, 12, 16, 24, 32, 64; `open="true"` includes requests refused without a wait (they land in bucket 0): split by `outcome` in analysis.
What `superseded` means: a newer-round request of the same author, authenticated and inside the vote window, reached this voter (`refuse_superseded_request`); checked on arrival, after the pre-lock wait and once the author lock is taken. The pre-lock wait (`VOTE_EXECUTION_WAIT`, 1 s) is not woken by a newer request.

## The lines that end a vote round at the author (target `consensus::metrics`, INFO) — appended in this order (B8-3: 3dfd7e0b0)

On `quorum reached`, on `header uncertified … reason=no_certificate` and on `header uncertified … reason=canceled`:

| field | type | rendering |
|---|---|---|
| `vote_arrivals` | list, arrival order | `[voter:ms,…]`: every voter whose vote reached this node before the round ended ("received", not "counted") |
| `vote_errors` | list, order of first such answer | `[voter:first_ms:last_ms:kind:count,…]`: one entry per voter that answered with something other than a vote; `kind` is the code of its latest such answer, `count` counts all of them whatever their code |
| `votes_at_end` | u64 | votes the round counted, the author's own included; 0 means the round never started |
| `stake_at_end` | u64 | their voting power |

Zero of the clock: a monotonic instant taken just before the round's vote requests are spawned; a request issued again later is still timed from it.
`kind`: `missing_parents`, `deferred` (the voter kept answering a recoverable error through the handle's own retries: behind on execution, not an active validator, timed out on its side, or it has a newer request: the author cannot tell which), `timeout`, `network`, `refused` (a fatal refusal: too old, any other invalid header, a wrong response type), `parents_unavailable`, `invalid_vote`, `other`.
Answers after the round's end are not listed.

## `leader schedule updated` (target `consensus::metrics`, INFO) — new line (B8-5: 48991d94c)

Fields in order: `epoch` (u32), `round` (u32, `Round`: the committed leader round the scores belong to), `scores` (`[id:score,…]`, every authority), `good` (`[id,…]`: swapped in), `bad` (`[id,…]`: swapped out), `final_of_schedule` (bool, always true).
At most ten entries per list, a closing `+N` for the rest; `[]` when empty.
Once per schedule change: at most once per window of 60 committed leader rounds (120 rounds), only if the window's last leader is committed; once more per restart, restating the restored table (de-duplicate on `(epoch, round)`).
Removed with it: three DEBUG lines of target `primary::leader_schedule` ("Good node on round …", "Bad node on round …", "Reputation scores on round …").

## `certificate accepted` (target `consensus::metrics`, INFO) — new line (B8-4: e8eb8e199; and 453123d5e, a fix to the vote round's lists)

Once per certificate that enters its round's aggregator at this node (own and peers'), before that certificate's parent set is sent; a second certificate of an author already seen in the round logs nothing. Fields in order:

| field | type | meaning |
|---|---|---|
| `epoch` | u32 | the certificate's epoch |
| `round` | u32 | its round |
| `origin` | id | its author |
| `round_certs` | usize | certificates of that round this node holds now, this one included (distinct authors) |
| `parents_sent` | bool | a parent set of that round had been handed to the proposer BEFORE this certificate |
| `late_ms` | u64 | 0, or milliseconds since the quorum certificate was appended, just before the first send was awaited (monotonic clock) |
| `source` | `own` / `peer` / `recovered` | built here; another authority's verified certificate (a broadcast and a fetch are not told apart); reloaded from the store at start-up |
| `parents_resent` | bool | this certificate was sent to the proposer on its own, after the first send (true on every certificate after the quorum) |
| `quorum_reached` | bool | true on the one certificate that completed the quorum and caused the first send |

Sample (the 8th of 10): `certificate accepted epoch=0 round=1 origin=<id> round_certs=8 parents_sent=true late_ms=25 source=peer parents_resent=true quorum_reached=false`
What the proposer does with a late certificate (read at this tip): the parents of the round r+1 header are taken with `std::mem::take(&mut self.last_parents)` (`proposer.rs:1554` at fdb9d22a9; `:1430` at e8eb8e199) and `self.round` moves up (`:1479`); a round r parent set that arrives after that falls into `process_parents`'s `Ordering::Less` arm (`:998-1007`, "ignoring older parents") and is dropped, so no header of that node ever names the late certificate.
Fix in 453123d5e: a vote that fails the aggregator's signature check is listed under its voter in `vote_errors` with kind `invalid_vote` (it stays in `vote_arrivals` too: the lists only grow).

## The engine's per-output lines (target `engine`, DEBUG) — one new key at the END of each (B8-6: 94ebb2e50, d7d9920eb)

| line | fields before | new key | meaning |
|---|---|---|---|
| `output executed` | consensus_number, leader_round, blocks, batches, execute_ms, persist_ms, announce_ms, txs, recover_wait_ms, evm_ms, root_ms, finish_ms, other_ms, max_block_root_ms, max_block_evm_ms | `cpu_ms` (u64, optional) | CPU time of the executing thread over exactly the span of `execute_ms`, from `/proc/thread-self/schedstat` read at both ends (each reading can lag one scheduler tick: 4 ms at HZ=250; the start reading lies inside `execute_ms`'s span: one procfs read, about 10-30 µs); not counted: the parallel signer recovery and other pool threads; the key is absent where the file is missing; always 0 on a kernel without scheduler statistics |
| `persisted output` | first, last, blocks, txs, receipts, accounts, storage_slots, open_ms, save_blocks_ms, markers_ms, commit_ms | `store_bytes` (u64, optional) | pages of the newest committed state × page size, read right after the commit from a clone of the `Arc<TnLmdbEnv>` the provider factory holds (the same environment, no second opening; one read of the current snapshot pointer, no writer slot, no I/O; the high-water mark, free pages included); absent on an MDBX build |
| `output execution task finished` | consensus_number, queue_wait_ms, task_ms, forward_wait_ms | `outputs_behind` (usize) | outputs still in the engine's queue when this output's task ends (not those still in the channel the engine has not polled) |

Not added, and why: a separate `commit_wait_ms`: `open_ms` on `persisted output` already is the wait for the store's single writer slot (the time inside `database_provider_rw()`); `txs` / `blocks` on the task line: join on `consensus_number`.

## `order hold released` (target `consensus::metrics`, INFO) — new line (B8-7: b3067a77e)

One line per own header that an order-hold plan named a blocker, written when that header leaves the proposer's tracked set; never one per digest; nothing with `digest_order_hold` off. Fields in order:

| field | type | meaning |
|---|---|---|
| `epoch` | u32 | the committee's epoch |
| `round` | u32 | the blocker header's round |
| `lanes` | usize | distinct workers in that header's payload (the lanes it held) |
| `digests` | usize | digests queued, when the line is written, in the lanes this header held that no other tracked blocker still holds (a lane two blockers share counts at the last to leave; on a cancel or a `requeue_on_commit` the line comes after the re-queue, so the header's own re-queued digests are counted) |
| `waited_ms` | u64 | wall clock now minus the header's `created_at_ms` |
| `cause` | quoted string | `cancel` (the uncertified header was re-queued), `commit` (a commit notice named it), `requeue_on_commit` (a commit notice for a higher own round re-queued it), `epoch_end` (the proposer stopped: epoch end or shutdown; not written on an error exit) |

Sample: `order hold released epoch=0 round=1 lanes=1 digests=3 waited_ms=4 cause="cancel"`

## `subdag parent skipped` (target `consensus::metrics`, INFO) — new line (B8-7: fdb9d22a9)

At most one line per committed leader (per sub-dag ordered), only when at least one parent was skipped because its round is STRICTLY below its origin's last committed round (a parent at exactly that round is the routine frontier skip and is not counted). Each counted certificate was either committed by an earlier sub-dag or is never committed: join `(origin, round)` against the `certificate committed` lines to tell which. Fields in order: `epoch`, `leader_round`, `skipped` (distinct certificates skipped that way), `edges` (parent edges that hit such a skip), `skips` (`[origin:round:last_committed,…]`, the lowest ten by (round, origin), origin ordered by its raw id bytes (not by the base58 text); `skipped` keeps the full count).
Sample: `subdag parent skipped epoch=0 leader_round=3 skipped=3 edges=5 skips=[<idA>:1:2,<idB>:1:3,<idB>:2:3]`
Rate: at most one line per two rounds per node (about 1.25 a second at bench load).

## Reviewed

The side chain (`b8/side`, 91a15e223..d7d9920eb) was reviewed on 2026-11-16 by a reader that did not write it (`tasks/bench8/review/b8-side-chain.md`): approve with follow-ups, no Critical or High, one Medium (the meaning of `exec_deficit_open`, corrected above) and nine Lows (test strength; an empty ring logs tip 0). With every parameter at its default no decision, send, stored value or error differs from 91a15e223. The line that grows most is `vote path timing`: about 150 bytes more per line, about 3.3 kB per second per node at DEBUG.

The main chain's first three commits (the parameter and the `header proposed` fields: 77d7909c1, 19074c301, 1f87d7860) were reviewed on 2026-11-16 (`tasks/bench8/review/b8-main-chain-1.md`): approve with follow-ups, no Critical, High or Medium, seven Lows. At floor 8 a header comes out exactly as on 91a15e223; the moved floor read cannot change the choice; the final raise to the opening block cannot be reached at any floor; no code outside the proposer reads the floor.
What a run at floor 16 exercises: only headers under the rule whose quorum value lies 9 to 16 ring entries below the proposer's tip (they name the quorum value, `exec_basis=quorum`, where they named the entry 8 back), and headers whose quorum value is deeper than 16 (they name the entry 16 back). It does not exercise: round 1 of an epoch (the header names the own tip), any voter-side change (there is none), a short ring (only on a node that restarts during the run). About 510 bytes more per `header proposed` line (about 1.3 kB per second per node).
The main chain's five observability commits (3dfd7e0b0, 453123d5e, e8eb8e199, b3067a77e, fdb9d22a9) were reviewed on 2026-11-16 (`tasks/bench8/review/b8-main-chain-2.md`): approve with follow-ups, no Critical, High or Medium, seven Lows. With every parameter at its default they change only logging: no decision, send, stored value, returned error or sub-dag order differs from 91a15e223. Together they add or grow about 29-31 INFO lines per second per node, about 7.5 kB per second typical (most of it `certificate accepted`, about 24 lines per second at about 250 bytes).
