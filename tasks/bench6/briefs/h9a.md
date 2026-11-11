# H9a generator counters and series — original brief (as sent to the first agent; recovered from the session transcript 2026-11-11)

You are generator unit **H9a (counters and per-second series)** of the bench-6 program. Read /home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md first (all sections except "Node units", "Test units" and "Investigations"; the "Harness and generator units" section and the older rule files it names apply to you), and follow it exactly. Repo (you are its only writer in this round): /home/drtnarg/coding/telcoin/tn-transaction-generator (HEAD 6dad96f; check `git -C … status` first and report anything already dirty without touching it). Checkpoint: /home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-H9a.md (on start, read it and continue from the first unfinished section). You do not commit and you do not push.

## Why
The load generator ("blaster": closed loop, 600 senders × an in-flight window per blaster, each blaster pinned to one validator, a 300-s nonce-gap repair) wrote too little about itself in bench 5 to prove whether it or the node limited a window: there is no per-second `submitted` series, no record of how long senders sat blocked at the window, and resends are not counted by cause. The user's decision: **measurements only — the sending behaviour must not change.**

## Spec
Harness design §7 "Generator measurements": /home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-harness--arms-and-runs.md (read §7 fully; it is the contract). A refinement may arrive later from the investigation unit I-2 at /home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/I-2/h9-measurement-spec.md — if that file exists when you start a section, read it and fold in what is additive; if not, proceed on §7.

## You own (this unit)
`src/blast/**` and `bench/schema/**` in the generator repo, plus the tests beside them. The follow-up unit H9b adds the tail scan (`--tail-scan-secs`, `run.tail_scan`, `late` on landings rows) in the same files after you: do NOT implement the tail scan, but do not make it harder (note where it would hook in).

## Deliver (checkpoint after each)
1. Read the send path, the window/in-flight accounting, the gap repair and resend paths, the report writer and the schema docs; write down (in the checkpoint) where each new counter is observed and why observing it cannot change timing or ordering (no new awaits, locks or allocations on the per-transaction send path beyond an atomic add; per-second aggregation happens off the send path).
2. Additive report fields in the blaster JSON (schema id stays `tn-blast/v2`; new columns are additive and column-named, documented in `bench/schema/README.md`): `series.send_per_second` with columns for submitted, accepted, resent, re-signed, rpc errors, blocked senders and in-flight (names exactly as §7 gives them); `senders.blocked` (per-sender time blocked at the window, as §7 shapes it); resends counted by cause.
3. **Proof that the send path is unchanged**: the byte-diff test §7 describes (the same seeded run against the mock RPC produces byte-identical request bodies and ordering with and without the new accounting — or, if the code has no switch, against a golden recorded before your change: record the golden FIRST, from the untouched tree, and keep it as a fixture).
4. Schema fixture updated; an old report (without the new fields) still parses in whatever consumes it inside this repo.

## Gates
Through the slot wrapper, the repo's own target dir: `cargo test`, `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`; capture `EXIT=` as the rules say.

Hand-back: every new JSON field and column verbatim with its unit and semantics (the harness report code and the analysis units parse them), the byte-diff test's name and what it compares, `git diff --stat`, gate results, and the hook points for H9b.
