# Draft PR (telcoin-network) — topic `cert-requeue` — not yet opened; evidence section filled from the bench-5 analysis (Wave D)

Opened as #1821 (2026-11-10): head `feat/cert-requeue` → base `staging/benchmark-obs-2026-11` (PR 10 of 10, stacked). Final body: tasks/pr-bodies/bench5-09-cert-requeue.md.

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/cert-requeue origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: cert-requeue$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): 3304d94ce
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: tasks/bench5-land-time-baseline.md (lever S4/S5 tail).
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/cert-requeue --title "<title>" --body-file <this file's body>

## Title
feat(primary): re-queue digests of cancelled headers

## Body (per-commit summary)
- 3304d94ce `feat(primary): re-queue digests of cancelled headers`
  A header whose votes a newer own header cancelled can never be certified, yet its batch digests waited for a
    later own commit to re-queue them; bench 4 put Seoul at 31.5 % uncertified own headers under load, and far
    validators leave 70 % of their idle certificates uncommitted. The certifier now reports such a header on a
    bounded `uncertified_own_headers` queue (`try_send`, a full queue drops the report) where `new_proposal` ends
    its proposal, never after no certificate formed nor for a header with a stored certificate, and the proposer
    moves its digests to the front of the queue. The header is not signed or sent again, and only a header below
    the proposer's round moves. `digests resent` gains `cause=`; `tn_primary_digests_requeued_total{cause}` counts
    digests.

## Why (measured motivation)
See the issue text tasks/bench5-land-time-baseline.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` = bench/main-fixes-2026-11 @ 067639def, ten validators + one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), the bench-4 fleet, parameters and chaos plan; a light-load arm (8 and 16 senders × window 16, then 600 × window 4) before the 600 × 16 chaos blast. Analysis: benchmark/private/bench5-r20261107-1504/ (A1 KPIs, A2 certification, A3 recovery, A4n census/F2, A6 land path), summarised in tasks/bench5-report-r20261107-1504.md.

- `digests resent … cause=canceled`: a cancelled header's digests landed in the proposer's next header in 2,811 of 2,813 cases, 113-118 ms after the cancel instead of the 20-45 s fallback.
- It does not move the median: uncertified headers under load were a starvation problem (the F3-6 refusal), not a cancel problem, and on a starved node the next header is refused for the same reason (v04 re-queued 8,162 digests, v08 7,479, v10 3,543 to no effect).
- Keep it: correct, cheap, and it will matter once certification is healthy.

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
