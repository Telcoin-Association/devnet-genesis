# Plan: fastest viable block cadence across a 10-region fleet (2026-10-06)

Source plan: the approved "latency-adjustments" plan (see transcript). Branch
`bench/preserve-logs-and-harness-fixes`; txgen `fix/preamble-gap-repair`. No Claude attribution.

## Wave 1 (parallel, opus)
- [x] W1 committed c47cb79: probe + matrix tools, 18 zones probed (no UDP loss; QUIC-only transport confirmed), tables under benchmark/latency/2026-10-06/ incl. kth-nearest-final.md
- [x] W2 committed e8ef7f1: ZONES = LA, London, Sydney, Tokyo, Montréal, NL, Singapore (Jakarta has no c3-highcpu-8), Hong Kong (alt Taiwan), Seoul, Mumbai zone c; all quotas OK, none filed; step-0 machine/quota preflights; blaster family fallback (no live trial yet: run `benchmark-blast.sh fund --run <id>` dry-run before stage 1)
- [x] W4 merged (b601b84..ce71bc7): archive code gone, local gate + INDEX/CHECKSUMS, cert-rate.py/block-rate.py, verify.md 319/319 MD5 match
- [x] W5 txgen image blast-v2-9f61303 built (Cloud Build 9edb4446, 4m18s), gate passed 15/15 flags; digest sha256:515311a6a8ffdde56ed190f85c11cee6abdec1434e2fff5e8ffd57d4a554eee2; branch pushed; run env: `export BENCH_TXGEN_SHA=9f61303` (tag form only, never @sha256)

## Wave 2
- [x] W4 merged; suite 282 OK, shellcheck OK, mutations OK; ANALYSIS.md saved; CI covers tools (46db468)
- [x] W3a committed f7ad4ae: per-node overrides, log filter, step-9 per-node checks (ran out of budget before the tool)
- [x] W3b committed b08f7c0: params-apply.sh (phase A read-only, validate, serial apply, PARAMS_OK, param_arms), provenance/bundle per-node values, probe log flags
- [x] W3c merged (e6d5900, f594514): manifest.certification/cert_failures, cert-fail log snapshots the local gate enforces, Certification-by-node table + caveat
- [ ] final suite + shellcheck on the merged tree, push (dry-run deploy already shown in tasks/regions/evaluation.md)
- [x] gs://tn-devnet-benchmark-archive deleted ~18:20 UTC after verify.md review; only tn-devnet_cloudbuild remains

## W6 — latency-adjustments.md (repo root) → USER REVIEW GATE
- [x] written + committed 46db468 (model: idle round ≈ 400 ms for min ≤ 300 on the new layout; arms A0 250/500, A1 50/250, A2 400/800, A3 250/1000, A4 500/1000)
- [ ] user review + arm confirmation

## Live checks the operator/stage-1 runbook must do first
- blast `fund`/`run` dry-run (new create argv; permission classifier blocked it here)
- `params-apply.sh --from-config --stage-test bench-observer-11`, then one validator arm
- deploy step 9 with overrides live once (host datadir parse, yaml rewrite, log flags, docker inspect)
- first teardown with a failing validator exercises the cert-fail snapshot path
- site schema: tn-benchmarks/scrub.py needs optional `overrides`/`param_arms` under consensus before publishing a run that has them

## W7 stage 1 sweep → W8 stage 2 full run
