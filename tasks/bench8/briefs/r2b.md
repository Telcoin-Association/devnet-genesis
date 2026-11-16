# R2b — finish unit R2: four tests of `main` that pinned the removed path

You continue unit R2. Read `tasks/bench8-agent-rules.md` ("Removal units (R1-R5)"; budget 35 tool calls, about 120 printed lines per call), the brief `tasks/bench8/briefs/r2.md`, and R2's checkpoint `tasks/checkpoint-bench8-R2.md` (site map, resume point, script paths). Your checkpoint: `tasks/checkpoint-bench8-R2b.md`.
Skills: `tn-rust-skills`, `tn-domain-consensus`, `tn-domain-networking`.
Worktree `/home/drtnarg/coding/telcoin/tn-b8-uc`, branch `refactor/remove-bench-switches`, tip d2b80ced5 (R2's commit: `vote_queue_fix` is gone; clippy and fmt clean; nextest `-p tn-config -p tn-primary -p tn-network-libp2p`: 1,377 passed, 4 failed).

## The four failing tests (all in `crates/consensus/primary/src/tests/network_tests.rs`; upstream `main`'s own tests; they ran with default parameters, so with the switch off, and were never run against the path that is now the only one)

| test (line at d2b80ced5) | on `main` | now |
|---|---|---|
| `test_vote_older_round_rejected` (`:2241`) | an older round gets `InvalidHeader(AlreadyVotedForLaterRound)` | `SupersededRequest { round: 1, newest_round: 2 }` |
| `test_vote_cached_across_stale_headers` (`:1826`) | a different header for the older round gets `AlreadyVotedForLaterRound` | `SupersededRequest` |
| `test_vote_cached_across_dropped_request` (`:1910`) | a repeat of the older, already voted header gets the cached vote | `SupersededRequest` |
| `test_vote_tier_three_lead_is_rejected_before_execution_wait` (`:3145`) | a header with a tier-three timestamp lead is refused at once | refused after the pre-lock execution wait (1 s) |

## The orchestrator's ruling

The code does not change: it is what #1864 shipped behind the switch and what two benchmarks ran. The tests follow the kept behaviour, and each difference is written down exactly, because the pull request must tell a reviewer what a voter answers differently from `main`.

For each of the four:
1. Read the test and the handler path it exercises (at this tip). Say in two sentences, with file:line, WHY the answer differs: which check now runs first.
2. Change the expectation to the kept behaviour and keep every other assertion of the test (what is cached, what is stored, that no vote is cast twice). Rename a test whose name states the old behaviour. Do not delete a test unless nothing of it is left to assert; say so if that is the case.
3. For the first three: is the old answer still reachable at all (for example when no newer request of that author has been seen)? If a case of the old test still gets the old answer, keep that case.
4. For the tier-three test, find out and state precisely: does the voter wait the full `VOTE_EXECUTION_WAIT` before refusing ANY header with such a lead, or only one that names an execution block the voter does not hold yet? Add the case that shows the other side (a header with a tier-three lead that names a block the voter holds is refused at once, if that is what the code does). Do not move the drift check in the handler: say in your hand-back what moving it before the pre-lock wait would take and what it would change, so the owner can decide.
5. What does the REQUESTER (the author's certifier) do with `SupersededRequest` against `AlreadyVotedForLaterRound` and against a cached vote: retry, give up the header, count an error? One paragraph with file:line. And: is `SupersededRequest` a variant an older binary (upstream `main` 0554efd4f: `git -C /home/drtnarg/coding/telcoin/tn-b8-uc show 0554efd4f:<path>`) can decode off the wire, or was the variant added by #1864? If it was added: what does a `main` author do when a voter of this tree answers with it?

Also: R2 reports that `validate_vote_timeout`'s last check (`vote_timeout < LIBP2P_REQUEST_TIMEOUT`, `crates/config/src/consensus.rs` near `:565`) can no longer fire, because the check before it (`vote_timeout + VOTE_EXECUTION_WAIT < LIBP2P_REQUEST_TIMEOUT`) is now unconditional and stricter. Remove the dead check and its test's now-unreachable assertion, keep the error text of the live check, and say so in the commit body.

## Commit, gates, hand back

One commit `test(primary): …` for the four tests (and one small `refactor(config): …` for the dead check if you prefer it apart), each compiling alone; body: per test, the old answer and the kept one, in plain words; `Refs #1804`; last line `Topic: remove-bench-switches`.
Gates: check, fmt, clippy for `tn-config`, `tn-primary`, `tn-network-libp2p` and `e2e-tests` (check only); `cargo nextest run --locked --no-fail-fast -p tn-config -p tn-primary -p tn-network-libp2p` must be green.
Hand back as the rules file says, plus the answers to points 1, 3, 4 and 5 written so they can go into a pull request's "Limits and what a reviewer should look at" section.
