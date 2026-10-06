# Plan: fastest viable block cadence across a 10-region fleet (2026-10-06)

Source plan: the approved "latency-adjustments" plan (see transcript). Branch
`bench/preserve-logs-and-harness-fixes`; txgen `fix/preamble-gap-repair`. No Claude attribution.

## Wave 1 (parallel, opus)
- [ ] W1 latency probe (`benchmark/tools/latency-probe.sh`, `latency-matrix.py`, tests) + live matrix over 21 zones → `benchmark/latency/<date>/`
- [x] W2 committed e8ef7f1: ZONES = LA, London, Sydney, Tokyo, Montréal, NL, Singapore (Jakarta has no c3-highcpu-8), Hong Kong (alt Taiwan), Seoul, Mumbai zone c; all quotas OK, none filed; step-0 machine/quota preflights; blaster family fallback (no live trial yet: run `benchmark-blast.sh fund --run <id>` dry-run before stage 1)
- [ ] W4 (worktree) remove GCS archive → local gate; `tools/cert-rate.py`, `tools/block-rate.py`; archive verification script output `tasks/archive/verify.md`
- [x] W5 txgen image blast-v2-9f61303 built (Cloud Build 9edb4446, 4m18s), gate passed 15/15 flags; digest sha256:515311a6a8ffdde56ed190f85c11cee6abdec1434e2fff5e8ffd57d4a554eee2; branch pushed; run env: `export BENCH_TXGEN_SHA=9f61303` (tag form only, never @sha256)

## Wave 2
- [ ] merge W4 worktree, run suite + mutation checks, commit
- [ ] W3 per-node param overrides, log filter, params-apply.sh, certification outcomes (uses W4 cert-rate.py)
- [ ] rebase, suite, shellcheck, dry-run deploy with 10 zones, commit, push
- [ ] delete gs://tn-devnet-benchmark-archive after reviewing verify.md (user-mandated)

## W6 — latency-adjustments.md (repo root) → USER REVIEW GATE

## W7 stage 1 sweep → W8 stage 2 full run
