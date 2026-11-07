# Draft PR (telcoin-network) — topic `cert-requeue` — not yet opened; evidence section to be filled from the bench-5 analysis (Wave D)

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

## Evidence (bench 5, run <R>)
(to be filled in Wave E from benchmark/private/bench5-<run>/{A1,A3,A4n,A6}: the fields named in tasks/checkpoint-bench5-design.md for this topic, with file cites; verdict confirmed / inconclusive / regressed)

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
