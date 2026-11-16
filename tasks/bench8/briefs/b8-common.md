# B8 units — common brief (the bench 8 node build: one parameter and log fields on the bench branch)

Read `tasks/bench8-agent-rules.md` first (budget 35 tool calls, about 120 printed lines per call; checkpoints `tasks/checkpoint-bench8-<unit>.md`), then the sections "What nobody but the orchestrator does", "Node units" and "HAND BACK" of `tasks/bench7-agent-rules.md`, then this file, then your own brief.
Skills: `tn-rust-skills`, then the `tn-domain-*` skills your brief names.

## What this build is

`bench/bench8-2026-11` starts at 91a15e223, the commit of bench 7's image (old base 45dce8947, SEVEN runtime switches). It is a BENCH branch: the switches stay, the `node switches` line stays, and bench 7's rule holds here: with every parameter at its default the tree behaves as 91a15e223 (header payloads, block contents, the consensus pack byte-identical). It is never merged upstream and never rebased onto `main`.
The only differences from bench 7's image are what the B8 units add: one bench-only parameter and log fields, so that bench 8 infers nothing bench 7 had to infer.

Why: bench 7's certified share of headers before the kill fell to 94.0 % / 94.95 % (bench 6: 99.96 % / 99.56 %). Most of the loss is in headers naming an execution block that fewer than a quorum of voters held ("under-held"). The proposer's tip was more than 8 block-bearing outputs ahead of the 6th-highest other voter's tip on 12.08 % (run r20261115-1131) and 8.78 % (r20261115-1653) of the headers, never more than 16. Parents of a header, the voter's tip when a request arrives, when each vote reaches the author, and when a certificate becomes a parent candidate were not logged.

## Worktrees

- B8-1, B8-3, B8-4 work one after another in `/home/drtnarg/coding/telcoin/tn-b8-bench` (branch `bench/bench8-2026-11`).
- B8-2, B8-5, B8-6 work one after another in `/home/drtnarg/coding/telcoin/tn-b8-bench2` (branch `b8/side`, from 91a15e223); the orchestrator cherry-picks that chain onto the bench branch.
- Read-only copy of bench 7's image commit: `/home/drtnarg/coding/telcoin/tn-b7-stack`.
- Start from your worktree's tip (`git log --oneline 91a15e223..HEAD`): an earlier unit may have changed the files you read. `grep -n` before every line number.

## Rules for every B8 unit

- New log fields and metrics need no switch. A new field goes at the END of an existing line's field list (the harness parses by key, and a new key at the end cannot shift an old parser). A new line has an explicit `target:`, fixed `key = value` fields, and one line per header / certificate / vote round / output, never per transaction.
- A list in a field is logged compactly and bounded (ten authorities at most): use the short authority form the neighbouring lines already use; say in your hand-back exactly how one is rendered, with one sample line from a unit test or a local run.
- No behaviour change, except the one parameter of unit B8-1. No new dependency. No `unwrap()`/`expect()` outside tests, no lock across `.await`, no HashMap/HashSet iteration on a consensus path (sort before you log a set).
- Cost: these lines run at about 25 headers a second per fleet under load. No allocation per transaction, no clone of a batch, nothing behind a lock that the hot path contends on; a `Vec` of at most ten small items per header is fine.
- Tests: unit tests for every new field's value (not only that it exists) and for the parameter. No e2e module.
- Gates (through the slot wrapper, one long cargo call per tool call, to a log): `cargo check --locked --all-targets -p <touched crates>`; fmt check; clippy for the touched crates; `cargo nextest run --locked -p <touched crates>` (never `-p e2e-tests`).
- Commits: in your worktree, staged by path, each compiling alone; subject `feat(<crate>): …` or `test(<crate>): …`; a short body saying what the field measures and for which question of bench 8; no attribution; last line `Topic: bench8-obs`.
- Hand back, verbatim, every new log message, field (name, type, unit, exact rendering), metric (name, type, labels, buckets) and parameter (name, type, default, where it is read): the harness's kept-shape filter and the analysis scripts are written from your hand-back.
