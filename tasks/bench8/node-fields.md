# The bench 8 node build: every new parameter, log field, line and metric, verbatim

Private. The orchestrator's file, written from the units' hand-backs; the harness's kept-shape filter and parsers and the analysis scripts are written from it.
Branch `bench/bench8-2026-11` (worktree `tn-b8-bench`) and the side chain `b8/side` (worktree `tn-b8-bench2`), both from 91a15e223 (bench 7's image commit). The side chain is cherry-picked onto the bench branch before the image is built.
An authority is always rendered as its full base58 `AuthorityIdentifier` (about 44 characters; the node has no short form). Lists are `[a,b,…]`, no spaces, in `AuthorityIdentifier` (byte) order unless a row says "arrival order".

## Parameter (B8-1: 77d7909c1, 19074c301)

- `quorum_exec_block_floor_outputs`: `u64`, flat `Parameters` field, default 8, left out of a written `parameters.yaml` at 8.
- Listed LAST in `runtime_switches!`: the `node switches` line ends with `quorum_exec_block_floor_outputs=<n>`; the gauge `tn_node_switch{name="quorum_exec_block_floor_outputs"}` carries the count.
- Read once in `Proposer::new`; the proposer names, under the rule, the quorum value floored at the ring entry that many block-bearing outputs back from its own tip (or the oldest entry of a shorter ring).
- Start-up refusal (`Parameters::validate_operational_floors`): outside `1..=gc_depth`: `quorum_exec_block_floor_outputs {v} must be at least 1 and at most the {gc_depth} entries of the recent-blocks ring (gc_depth)`. The ring is built with `gc_depth` entries (`crates/node/src/manager/node.rs:800`).
- Proposer-side only: no voter code reads it. A restored voter gets no new refusal from an honest proposer.
- At 8 the header payloads equal 91a15e223's (golden table of 20 rows on 4 rings; at 16 exactly 8 rows differ).

## `header proposed` (target `consensus::metrics`, INFO) — appended after `blockers`, in this order (B8-1b: 1f87d7860)

| field | type | meaning |
|---|---|---|
| `exec_quorum` | u64, block number | the highest number the own tip and the counted parents, holding at least a quorum of power, reached; BEFORE the cap at the own tip, the floor and the opening-block bound, so it can be above `exec_tip`; 0 when the rule did not run (`exec_policy=off`, the tip policy outside a window, an empty ring) or the usable power is short of a quorum |
| `exec_floor` | u64, block number | the ring entry `quorum_exec_block_floor_outputs` back from the tip (the oldest entry of a shorter ring); on every header under the rule; 0 when the rule did not run |
| `parents` | list | the authors of the parent certificates the header names; one per parent (= `num_parents`) |
| `pending_unheld` | usize, digests | `pending_before` minus `held` (digests the order hold did not keep back); equals `pending_before` with the hold off |

Sample tail: `… held=1 held_lanes=1 blockers=1 exec_quorum=0 exec_floor=0 parents=[7TcAuZ…3fZL,C7mwJb…9k2t,HPRfph…fFP9] pending_unheld=1`

## `vote path timing` (target `primary::network`, DEBUG) — appended after `total_ms`, in this order (B8-2: fbea152d4; B8-2b: 42f9bdb32, 5a81a11f5)

| field | type | meaning |
|---|---|---|
| `exec_named` | u64 | number of the execution block the header names |
| `exec_tip_arrival` | u64 | this voter's latest executed block number when the request arrived, before any wait |
| `exec_tip_answer` | u64 | the same when the answer was decided (for a vote: after it was stored, so a few ms later) |
| `exec_deficit_outputs` | u64, ring entries | block-bearing outputs the voter still had to execute at arrival to hold the named block: 0 when held; else the ring entries above the arrival tip up to and including the first at or above the named block; a lower bound when `exec_deficit_open=true` or when more outputs than the ring holds ran |
| `exec_deficit_open` | bool, on every line | true when the wait ended without the block |
| `superseded_by_round` | u32 | outcome `superseded` only: the round of the author's newest request mark at the refusal (may be more than one above this request's round); else 0 |
| `superseded_after_ms` | u64 | outcome `superseded` only: from this request's arrival to the FIRST arrival of that mark round's request; 0 when the newer request had arrived first (refused on arrival); else 0 |

Histogram `tn_primary_vote_exec_deficit_outputs{open="true"|"false"}` (crate name `tn_primary.vote_exec_deficit_outputs`), one sample per request, buckets 0, 1, 2, 4, 8, 12, 16, 24, 32, 64.
What `superseded` means: a newer-round request of the same author, authenticated and inside the vote window, reached this voter (`refuse_superseded_request`); checked on arrival, after the pre-lock wait and once the author lock is taken. The pre-lock wait (`VOTE_EXECUTION_WAIT`, 1 s) is not woken by a newer request.

## The lines that end a vote round at the author (target `consensus::metrics`, INFO) — appended in this order (B8-3: 3dfd7e0b0)

On `quorum reached`, on `header uncertified … reason=no_certificate` and on `header uncertified … reason=canceled`:

| field | type | rendering |
|---|---|---|
| `vote_arrivals` | list, arrival order | `[voter:ms,…]`: every voter whose vote reached this node before the round ended ("received", not "counted") |
| `vote_errors` | list, order of first such answer | `[voter:first_ms:last_ms:kind:count,…]`: one entry per voter that answered with something other than a vote |
| `votes_at_end` | u64 | votes the round counted, the author's own included; 0 means the round never started |
| `stake_at_end` | u64 | their voting power |

Zero of the clock: a monotonic instant taken just before the round's vote requests are spawned; a request issued again later is still timed from it.
`kind`: `missing_parents`, `deferred` (the voter kept answering a recoverable error through the handle's own retries: behind on execution, not an active validator, timed out on its side, or it has a newer request: the author cannot tell which), `timeout`, `network`, `refused` (a fatal refusal: too old, any other invalid header, a wrong response type), `parents_unavailable`, `invalid_vote`, `other`.
Answers after the round's end are not listed.

## `leader schedule updated` (target `consensus::metrics`, INFO) — new line (B8-5: 48991d94c)

Fields in order: `epoch` (u32), `round` (u64: the committed leader round the scores belong to), `scores` (`[id:score,…]`, every authority), `good` (`[id,…]`: swapped in), `bad` (`[id,…]`: swapped out), `final_of_schedule` (bool, always true).
At most ten entries per list, a closing `+N` for the rest; `[]` when empty.
Once per schedule change: at most once per window of 60 committed leader rounds (120 rounds), only if the window's last leader is committed; once more per restart, restating the restored table (de-duplicate on `(epoch, round)`).
Removed with it: three DEBUG lines of target `primary::leader_schedule` ("Good node on round …", "Bad node on round …", "Reputation scores on round …").

## Still to come

- B8-4: `certificate accepted` (`epoch`, `round`, `origin`, `round_certs`, `parents_sent`, `late_ms`, `source`, `parents_resent`).
- B8-6: the engine's output lines: `store_bytes`, `outputs_behind`, `cpu_ms`, `commit_wait_ms` (and `txs`, `blocks` where missing).
- B8-7: `order hold released`, `subdag parent skipped`.
