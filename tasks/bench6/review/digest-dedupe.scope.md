# Review scope — digest-dedupe

Topic footer(s): `Topic: digest-dedupe`. Upstream issue: #1807. Switch: `digest_dedupe` (bool; default false).
Branch head when this was written: dc7855cc6. Size: 4 commits, +956 lines (tests included).

## Commits (the diff under review, in branch order)
- `478dd3d23` feat(config): add the digest_dedupe switch
- `93e9d7c21` fix(worker): skip a sealed batch whose digest was already reported and is still uncommitted
- `8bc341967` feat(reth): log the sender of a skipped invalid transaction
- `7fdcb9ff5` feat(primary): drop a batch digest the proposer already holds

## Files touched
- `crates/config/src/node.rs`
- `crates/consensus/primary/src/metrics.rs`
- `crates/consensus/primary/src/proposer.rs`
- `crates/consensus/primary/src/tests/proposer_tests.rs`
- `crates/consensus/worker/src/metrics.rs`
- `crates/consensus/worker/src/worker.rs`
- `crates/tn-reth/src/env/execution.rs`

## Where the topic's claims and known residuals are written (read these before the code)
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-contract.md`: the switch table row `digest_dedupe` and the three `digest-dedupe` rows under "Node log lines and metrics" (worker half, the `sender` log field, proposer half; what is NOT deduplicated).
- `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-g1-notes.md`, sections "From U7" (worker half) if present and the U10 hand-back recorded in the plan; decisions around #1807 (D13, D14).
- The issue body: `ls /home/drtnarg/coding/telcoin/devnet-genesis/tasks/issue-bodies/ | grep -i -e sealed -e resend -e 1807` and its evidence `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-2/sealed-keep-test-cases.md` (cases S4 and S5: worker and proposer dedupe, and what the proposer must NOT drop).
- Unit checkpoints: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-u7.md`, `…-u10.md`.

## Questions specific to this topic (2g)
1. THE question: can either half ever drop the ONLY live copy of a batch digest, so that a batch a worker sealed and a quorum acknowledged is never proposed? Walk every path on which a digest leaves the worker's "already reported" state or the proposer's index (success, failed report, primary restart with the worker alive, worker restart, epoch change, a cancelled or expired header whose digests are re-queued, a header re-sent after restart) and say for each whether a later legitimate report is accepted.
2. The proposer's index mirrors the pending lanes with a counting map plus an in-flight list: find a sequence in which the index and the lanes disagree (the code logs a warn if a drained digest is missing — is that path reachable, and is the node still correct after it?).
3. Memory: both halves hold per-digest state. What bounds it within an epoch and across epochs? Can a faulty local worker (or anything that can reach the primary's digest channel) grow it?
4. With the switch off the proposer's lanes, drain and header payloads must be identical to before: check the claim against the diff, including the order of digests in a header.
5. The `sender` field added to the `skipping invalid transaction` log line: any cost or information concern on a hot path?

## Your files
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/digest-dedupe-report.md`
- Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-review-digest-dedupe.md`
