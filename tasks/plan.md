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
- [x] user review + arm confirmation (2026-10-06: "continue launch the stage-1 sweep"; arms A0..A4 and the Singapore-for-Jakarta layout unchanged)

## Live checks the operator/stage-1 runbook must do first
- blast `fund`/`run` dry-run (new create argv; permission classifier blocked it here)
- `params-apply.sh --from-config --stage-test bench-observer-11`, then one validator arm
- deploy step 9 with overrides live once (host datadir parse, yaml rewrite, log flags, docker inspect)
- first teardown with a failing validator exercises the cert-fail snapshot path
- site schema: tn-benchmarks/scrub.py needs optional `overrides`/`param_arms` under consensus before publishing a run that has them

## W7 stage 1 sweep → W8 stage 2 full run
- [x] deploy gained `--to N` (stop after a step) so the sweep deploys 0..12, then blasts per arm with `--from 13 --to 15` under a new BENCH_RUN_INDEX; plan text shows chaos off when BENCH_CHAOS=0
- [x] W7 stage-1 sweep r20261006-2058 (2026-10-06 20:59Z → 2026-10-07 01:50Z; three orchestrator handoffs; checkpoint `tasks/checkpoint-bench-stage1.md`)
  - [x] deploy 0..12 (certfix image digest caeb6be2…, txgen blast-v2-9f61303, log filter on, BENCH_CHAOS=0) → params-apply `--stage-test bench-observer-11` → A0 → A1 → A2 → A3 → A4, each: open arm, ~8 min idle, 480 s blast (warm 60 / cool 60), collect, per-arm analysis
  - [x] teardown with the local gate (passed; 4 cert-fail snapshots pulled); stage-1 section in benchmark/private/followups.md; lessons
  - [x] analysis: `results/r20261006-2058/analysis/stage1-summary.md`. NO ARM PASSES §6: bench-validator-02 (London) 7-50 % and -06 (Netherlands) 0.7-21 % own-header certification idle in every arm (Asian voters answer them at ~2× RTT; their 6th vote lands after the 7th other certificate, so they advance and cancel their own header). Idle round 527-550 ms in every arm (min 50..500 ms never binds). Best among the healthy eight: A3 = max 1000 / min 250 / batch 250 (fewest re-proposals, 1.41 rounds/s, 5005 tx/s loaded).
  - chosen config for W8, conditional on the v02/v06 finding: `max_header_delay_ms: 1000`, `min_header_delay_ms: 250`, `max_batch_delay_ms: 250`; fallback if the vote path is not fixed: `min_header_delay_ms ≥ 600` (pre-check first, never an arm)
- [ ] W8 prerequisites: add the vote-request handler target to the node debug filter (`primary::network::handler=debug`); decide fix-or-accept for London/Netherlands (upstream question in followups); re-check Mumbai (74-90 % under load)
- [ ] W8 stage-2 40-min chaos run with the chosen config
