# Draft PR (telcoin-network) — topic `signer-reuse` — not yet opened; evidence section to be filled from the bench-5 analysis (Wave D)

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/signer-reuse origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: signer-reuse$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): 9039198de
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: tasks/issues/bench5-f2-execution-ceiling.md.
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/signer-reuse --title "<title>" --body-file <this file's body>

## Title
perf(engine): recover signers when an output is queued, off the execution thread

## Body (per-commit summary)
- 9039198de `perf(engine): recover signers when an output is queued, off the execution thread`
  Bench 4 executed at 163-170 us/tx with signer recovery inside every block build on the execution thread (an
    estimated 3-17 us/tx of wall time) while 2.8-5.2 outputs waited in the engine queue. A blocking job started
    when an output is queued now runs RethEnv::recover_output_signers (one Vec per batch in flatten_batches order,
    the same drop-and-count semantics, tx_len logged instead of the bytes); the execution task builds from its
    result through build_block_from_recovered_payload, which the bytes path wraps. A job without a result falls
    back to inline recovery and counts tn_engine_recovery_fallback_total, never an error. `output executed`
    reports recover_wait_ms in place of recover_ms and the job logs `signers recovered`; differential tests pin
    identical blocks.

## Why (measured motivation)
See the issue text tasks/issues/bench5-f2-execution-ceiling.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run <R>)
(to be filled in Wave E from benchmark/private/bench5-<run>/{A1,A3,A4n,A6}: the fields named in tasks/checkpoint-bench5-design.md for this topic, with file cites; verdict confirmed / inconclusive / regressed)

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
