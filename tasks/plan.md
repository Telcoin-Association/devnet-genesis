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
- [x] vote-path root cause (source trace + regression on the run's per-link vote timings): strict multistream-select V1 negotiation = +1 RTT per vote; Europe↔Asia on external IPs routes via the US (vote = 2×(RTT to LA + RTT LA→peer) within 7 ms). latency-adjustments.md §9.2/§9.4
- [x] node debug filter default now includes primary=debug (+3 =info overrides), tn_primary::network::handler, multistream_select, libp2p_swarm::connection::pool, peer-manager
- [x] USER DECISION 2026-10-07: external IPs stay (production realism; no VPC addressing). Path: external probe → V1Lazy + classification fix in a new image → A3 re-check → stage 2. Subagents keep the main context clean.

## W9 — external-address latency probe (opus; checkpoint tasks/checkpoint-probe-external.md)
- [ ] latency-probe.sh `--external`: each VM measures every peer on internal AND external IP in one run; firewall sources = probe VMs' external /32s; latency-matrix.py `external-vs-internal.md` + external matrices; tests
- [ ] live run on the ten fleet zones (incl. asia-south1-c, unprobed before) → benchmark/latency/2026-10-07/; verdict: external ≈ internal (detour is in the node) or external ≈ via-LA sum (network path)

## W10 — telcoin-network: lazy protocol negotiation + error classification (tn-rust-engineer; checkpoint tasks/checkpoint-v1lazy.md)
- [ ] branch fix/libp2p-lazy-protocol-negotiation off devnet-bench-10-5-2026 @ ba43a1f0e: `with_substream_upgrade_protocol_override(Version::V1Lazy)` in network-libp2p consensus.rs swarm config
- [ ] classification helper: `Io(Other)` wrapping multistream-select NegotiationError treated as unsupported protocol in the peer-penalty, peer-exchange fallback and sync-capability arms; unit test
- [ ] cargo fmt/check/clippy/test on the crate; merge --no-ff into devnet-bench-10-5-2026; push
- [ ] image `adiri:mmap-subsecond-v1lazy-10-7-2026` via `make docker-devnet` (amd64), pushed; `benchmark-deploy.sh --probe-node-image` passes with EXPECT sha/forks; digest recorded

## W11 — A3 re-check on the new image (fable live orchestrator, one fleet shared with W12)
- [ ] consensus-parameters.yaml → max 1000 / min 250 / batch 250 (A3) committed; deploy 0..12 with the new image + EXPECT values, debug filter default (vote handler + negotiation), BENCH_CHAOS=0
- [ ] ~10 min idle + 480 s blast (index 0) + collect; propose-latency/cert-rate per window WITHOUT teardown (unit-stdout pull or wait) — decide: every validator ≥ 90 % idle → stage 2 at 250/1000; else min_header_delay = slowest C p95 + ~50 ms (params-apply --arm stage2) and record why
- [ ] negotiation check from the logs: `Dialer: Proposed protocol` → `Received confirmation` gap on London→Tokyo ≈ 0 extra RTT; per-link vote ≈ 1× effective RTT

## W12 — stage 2 (same fleet): 40-min chaos run
- [ ] BENCH_RUN_INDEX=1, BENCH_CHAOS=1 (epoch-timed kill of validator-05), BENCH_DURATION_SECS=2400, warm 120 / cool 180 defaults; collect; teardown with local gate; `--reindex` after analysis
- [ ] report: every validator's certification idle/load, orphan share, inclusion gaps, blocks/s, KPI table vs 0458/0053, cert_failures + paths; bundle via make_bundle --blast-index 1 (local; publishing = operator); followups, lessons, memory; final config committed to consensus-parameters.yaml
