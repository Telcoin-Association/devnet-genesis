<!-- Returned by the task-decomposer on 2026-11-14 (it has no Write tool); saved by the orchestrator from its hand-back.
The orchestrator's rulings on it are at the end, under "Orchestrator's rulings". Unit names here are the ones the briefs use. -->

# Bench 7 task list: decomposition of the approved plan (2026-11-14)

I checked the draft against the plan, the rules, the briefs on disk (pt0, pt1, pt2, pt3a, hb4a, u-common, u-c1, u-i2), the bench-6 ledger, the orchestrator checkpoint, and both trees (M in `telcoin-network-b7`, bench 6 in `telcoin-network-b6`). I had no Write or Bash tool, so I saved no memory and ran no git commands. Every overlap below comes from grep, glob and ranged reads.

**Legend.**
- Agents:
  - **GP**: general-purpose opus with `tn-rust-skills` and the `tn-domain-*` skills. Writes its unit tests, runs package gates, spawns a `tn-domain-reviewer`, commits.
  - **GH**: general-purpose opus under the harness rules. Does not commit.
  - **W**: opus writer with `human-writing`.
  - **FC**: opus figure-check.
  - **AN**: opus analysis.
  - **e2e**: `tn-write-e2e-agent` (opus). **PT**: `tn-write-proptest-agent` (opus). **REV**: `tn-review-agent` (opus). **SEC**: `tn-security-eval`. **ORCH**: the orchestrator.
- Paths:
  - `cfg` = `crates/config/src/node.rs`
  - `mgr/` = `crates/node/src/manager/`
  - `nm` = `crates/node/src/metrics.rs`
  - `pri/` = `crates/consensus/primary/src/`
  - `ss/` = `crates/state-sync/src/`
  - `it/` = `crates/e2e-tests/tests/it/`
  - `th` = `crates/types/src/test_hooks.rs`
  - `bm/` = `benchmark/`
- **§** = shared by rule: the unit edits only its own marked block, and the orchestrator resolves adjacency at integration.
- Budgets are in thousands of tokens.

## A. Unit table

### W0 and Track P
| id | what | agent | files owned | depends on | parallel with | budget | brief |
|---|---|---|---|---|---|---|---|
| W0-a/b | tick list, rules, checkpoint; fetch M, staging, integration worktree | ORCH | — | — | — | — | done |
| W0-c | memory pointer | ORCH | memory | — | all | — | open |
| W0-d | project-context | **sonnet** | `telcoin-network-b7/.claude/project-context.md` | — | all | 100 | running |
| DR-1807 | delta read of the hold design on M | opus, read-only | `bm/private/bench7-prep/DR-1807/findings.md` | — | all | 100 | dr-1807 (running) |
| DR-E | delta read of the epoch-record designs on M | opus, read-only | `…/DR-E/findings.md` | — | all | 100 | dr-e (running) |
| **W0-f** (new) | names contract `tasks/bench7-contract.md`: switch keys (E1's switch name included), log lines and metrics from the designs, amended from each hand-back | ORCH | that file | DR-1807, DR-E, PT-2A | — | — | no |
| **W0-g** (new) | bench-7 cherry-pick ledger | ORCH | `tasks/bench7-cherrypick-ledger.md` | PT-0 | — | — | no |
| P1 | four backfill files | W | `bm/report/backfill/2026-11-13-bench6-*.json` | — | all | 150 | p1 (running) |
| P1-FC | figure-check of P1 | FC | notes | P1 | — | 80 | no |
| P2, P3, P4 | commit and four bundles; site gates; push | ORCH | — | P1-FC, then in sequence | — | — | — |
| P5 | maintainers' summary | W | `tasks/bench6-maintainer-summary.md` | — | all | 120 | p5 (running) |
| P5-FC | figure-check of P5 | FC | notes | P5 (links after P4) | — | 80 | no |

### Track N
| id | what | agent | files owned | depends on | parallel with | budget | brief |
|---|---|---|---|---|---|---|---|
| PT-0 | switch machinery and obs (six commits incl. 16695b20a) | GP | `cfg`§ (machinery), `mgr/node.rs` (`announce_switches`), `nm`§, `pri/metrics.rs`§, `pri/proposer.rs`, `pri/tests/proposer_tests.rs`, `crates/tn-metrics/src/recorder.rs`, `pt0-api.md` | — | W0, P | 200 | pt0 (running) |
| PT-1 | e2e scaffold and `TN_E2E_PARAMETERS` | GP + `tn-write-e2e` skill | `crates/e2e-tests/src/lib.rs`, `it/common.rs`, `it/restarts.rs`, `pt1-api.md` | PT-0 (brief); M is possible, see D3 | PT-3a, E1, E2 | 200 | pt1 |
| PT-2A | verdict on M | opus (+ one test) | `tn-b7-pt2`; `pri/tests/network_tests.rs` (EOF§, only if DROP keeps a test) | — | all | 150 | pt2 (running) |
| PT-2B | port `vote_queue_fix` and the superseded-refusal counter (PORT only) | GP | `pri/network/handler.rs`, `pri/error/network.rs`, `pri/metrics.rs`§, `network_tests.rs` EOF§, `cfg`§ | PT-2A = PORT; PT-0 (new worktree at the post-PT-0 head) | PT-3a, E* | 200 | no |
| PT-3a | QEB commits 1-3 and 5, D75, starved-rounds validation | GP | `cfg`§, `pri/recent_blocks.rs`, `pri/proposer.rs`, `proposer_tests.rs` | PT-0 | PT-1, PT-2B, E1, E2, HD-2a, HD-4a | 200 | pt3a (remove commit 4) |
| **PT-3v** (new) | commit 4 (14b55b04c): voter-side tests re-expressed on M's handler | GP | `pri/tests/network_tests.rs` EOF§ | PT-3a's field commit | HD-1 | 150 | no |
| PT-3b | ST-A e2e port (8bd68e514, 31ef1149c, 56f66e160) | e2e | `it/exec_block.rs`, `it/main.rs`§ | PT-1, PT-3a | HD-1, HD-2* | 150 | no |
| ECF | port `b6/st-epoch-close-forms` and extend its four tests (new line, counters, switches, `FORK_LOGS`) | e2e | `it/epoch_close_forms.rs`, `it/main.rs`§ | PT-1, PT-3a, E1, E2, E3, E4 | HD-* | 180 | no |
| HD-1 | #1807 observability | GP | `pri/proposer.rs`, `pri/metrics.rs`§, `proposer_tests.rs` | PT-3a, DR-1807 | PT-3v, PT-3b, E* | 180 | no |
| **HD-2a** (new split) | pure `OwnChainOrder`, the `digest_order_hold` field, inline unit tests | GP | `pri/order_hold.rs` (new), `pri/lib.rs` (mod line), `cfg`§ | PT-0, DR-1807 | PT-3a, HD-1 | 120 | no |
| HD-2b | wiring: `propose_next_header`, drain, both re-queue paths, held metrics, unit tests incl. switch-off golden | GP | `pri/proposer.rs`, `pri/metrics.rs`§, `proposer_tests.rs` | HD-1, HD-2a | HD-2c, HD-3 | 200 | no |
| HD-2c | property test (one-author model; the switch-off model finds counterexamples) | PT | `pri/tests/order_hold_proptest.rs` + its mod line in `order_hold.rs` | HD-2a | HD-2b | 150 | no |
| HD-3 | orphan re-pool counters | GP | `mgr/node/close_epoch.rs`, `nm`§ | E1, DR-1807 | HD-2b | 120 | no |
| **HD-4a** (new split) | `TN_TEST_OWN_CERT_DELAY_MS` hook | GP | `th`§, `pri/certifier.rs` | PT-0, DR-1807 | anything | 100 | no |
| HD-4b | hold e2e; load helpers copied from b6 `sealed_txs.rs` | e2e | `it/digest_order_hold.rs` (new), `it/main.rs`§ | PT-1, PT-3a, HD-2b, HD-3, HD-4a | ECF | 200 | no |
| E1 | `final_state` check | GP | `close_epoch.rs`, `mgr/node/run_epoch.rs`, `nm`§, `cfg`§, `crates/node/tests/it/main.rs` | DR-E, PT-0 | E2, PT-3a | 200 | no |
| E2 | epoch-record observability | GP | `ss/epoch.rs`, `ss/metrics.rs`, `pri/network/mod.rs`, `mgr/epoch_votes.rs`, `nm`§ | DR-E, PT-0 | E1 | 180 | no |
| E3 | walk past own uncertified epoch, retry set, conflict halt | GP | `ss/epoch.rs`, `ss/metrics.rs`, `cfg`§, `mgr/node.rs`§ (record-collector call sites) | E2 | E4 | 200 | no |
| E4 | re-certify, `RetainedEpochVotes` | GP | `mgr/epoch_votes.rs`, `cfg`§, `mgr/node.rs`§ (vote-collector and startup re-vote call sites), `nm`§ | E2 | E3 | 200 | no |
| **E5a** (new split) | `TN_TEST_WITHHOLD_EPOCH_VOTE` hook | GP | `th`§, `mgr/epoch_votes.rs` (read site) | E4 | E3 | 80 | no |
| E5b | `test_uncertified_epoch_walked_past` and the recertify variant, in a **new** module | e2e | `it/epoch_record_walk.rs`, `it/main.rs`§ | PT-1, E1, E3, E4, E5a | HD-* | 180 | no |
| R-00 … R-06 | per-head review (R-02 only if PORT or a kept test) | REV ×7 | review notes | that head integrated | each other | 150 | no |
| SS-03 / SS-04 / SS-05 / SS-06 | E1 / E3+E4 / PT-3a+PT-3v / hold (HD-1, HD-2a, HD-2b, hook compiled out) | SEC ×4 | — | E1 / E3+E4 / PT-3v / HD-2b+HD-4a | each other | own | no |
| G-02, G-04 | PR-head gates: nextest, all-off e2e sets; G-04 adds E5b ×3 | ORCH | — | heads 02 / 04 integrated | — | — | — |
| G-TOP | top-head gates and the long property-test hunt | ORCH | — | everything in Track N | — | — | — |
| IMG | image cut, digest, probe by digest, local trial | ORCH | — | G-TOP, **HB-1** | — | — | — |

### Track U
| id | what | agent | files owned | depends on | budget | brief |
|---|---|---|---|---|---|---|
| **U-SCRIPT** (new) | shim-tested `gh` create/comment scripts, dry run by default | GH | `tasks/bench7/gh-*.sh`, `tasks/bench7/tests/test_gh_scripts.py` | — | 120 | no |
| U-C1 | comments on #1802, #1803, #1805, #1806, #1774 | W | `tasks/issue-comments/*` (5 files) | — | 200 | u-c1 |
| U-C2 | #1804 interim comment (plus PT-2's evidence if DROP) | W | `…/1804.md` | PT-2A | 100 | no |
| U-C3 | #1807 interim comment (mechanism in four runs, the hold) | W | `…/1807.md` | DR-1807 | 120 | no |
| U-I1 | issues: closing-block check gap; collector gaps G1 and G2; the false quorum error | W | `tasks/issue-bodies/bench6-*.md` (3-4 files) | DR-E | 150 | no |
| U-I2 | issues: rejoin and the follower's dead RPC; epoch-0 restart gap; `NewEpoch` over RPC | W | 3 files | — | 200 | u-i2 |
| U-I3 (merged) | issues: in-flight bound measurements; execute and persist in series at 50,000 IOPS; plus the does-not-carry write-up | W | 2 issue bodies + the write-up file | DR-E | 180 | no |
| U-P1 / U-P2 / U-P3 | PR texts 00+01 / 02 (PORT only) / 03+04 | W ×3 | `tasks/pr-bodies/bench6-NN-*.md` | G-02+R-00+R-01 / PT-2B+R-02 / G-04+R-03+R-04+SS-03+SS-04 | 100-120 | no |
| U-FC1 / U-FC2 | figure-check of issues and comments / of PR texts and the write-up | FC ×2 | notes | their writers | 120 | no |

### Track H
| id | what | agent | files owned | depends on | parallel with | budget | brief |
|---|---|---|---|---|---|---|---|
| HB-4a | chained launcher, fleet-health watch, export check | GH | `tasks/bench7/orch-run-chain.sh`, `orch-fleet-health.sh`, `orch-prom-export.py`, `tasks/bench7/tests/test_orch_scripts.py` | — | all | 150 | hb4a |
| HB-1 | faucet build of M starts. **Absorbs** HB-4's listener ports and the `BENCH_NODE_EVICT_MDBX` knob | GH | `bm/benchmark-deploy.sh`, `bm/node-image-contract.txt`, `bm/config.sh`, `bm/bench-lib.sh`, `bm/arms/MANIFEST-FIELDS.md`, `bm/tests/test_node_image.py`, `test_node_deploy.py` | P2 (4th bundle), or now in a worktree (D7) | HB-3 | 200 | no |
| HB-2 | switch list, `bench7-{always,adaptive}.arm`, provenance | GH | `bm/arms/switches.tsv`, the two arm files, `bm/config.sh` (lines 325-330), `bm/report/provenance.py`, `bm/tools/params-apply.sh`, `test_params_apply.py`, `test_report_provenance.py`, `test_node_image.py`, `MANIFEST-FIELDS.md` | HB-1, PT-2A, W0-f | HB-3 | 180 | no |
| HB-3 | storage measures on tn-lmdb | GH | `bm/node-persist-sampler.sh`, `bm/tools/folio-census.py`, `bm/tools/log-shapes.txt`, `bm/tools/arms-summary.py` + their tests; `bm/benchmark-probe.sh`, or declared out of scope | P2 | HB-1, HB-2 | 200 | no |
| HB-5 | `bench7.env`, README, the #1807 and hold readers | GH | `bm/launch/bench7.env`, `bm/launch/README.md`, new reader files, `log-shapes.txt` (after HB-3) | HB-2, HB-3, W0-f | — | 180 | no |
| HB-GATE | full gate alone on the host, print-state ×2, deploy dry plan, teardown dry mode | ORCH | — | HB-1…HB-5, HB-4a, IMG | — | — | — |

### Runs, analysis, wrap-up
| id | what | agent | depends on | budget |
|---|---|---|---|---|
| RUN-7a / RUN-7b | deploy12 → idle checks → blast15 → … → archive | ORCH | IMG, HB-GATE, the user's go and a fresh `gcloud auth login` / RUN-7a's blast done | — |
| A1…A8 ×2 runs | KPIs; certification; per-header basis and window share; closes and recovery; engine; disk; losses (#1807); rounds | AN ×16 | that run's archive. A6 needs HB-3; A7 needs HB-5 | 200 each |
| A9 / A10 | 7a against 7b / against runs 2 and 3 | AN ×2 | all eight units of both runs | 200 |
| A11 / A12 | report writers; each writes a **part file**, the orchestrator joins them (A11: facts, KPIs, certification, per-header, rounds, the form; A12: closes, engine, disk, #1807, against bench 6, open questions) | W ×2 | A9, A10 | 150 |
| A13 | figure-check of the report | FC | A11, A12 | 120 |
| GATE-F | form gate | ORCH + user | A13 | — |
| post-gate (asked) | U-P5 (PR 05 and 06 texts), U-C4 (the last comments), P7-1 (bench-7 backfills) + P7-FC, PT-3x (only if the decision changes a default) | W, W, W+FC, GP | GATE-F | 100-150 |
| WRAP | ledger verdicts, todo, lessons, memory, README, push | ORCH | all | — |

## B. File-ownership conflicts

★ = the draft missed it.

| file | writers, in order | resolution |
|---|---|---|
| `cfg` | PT-0, then PT-2B, PT-3a, HD-2a, E1, E3, E4 | § (as the draft says). |
| ★`mgr/node.rs` | PT-0, then E3 and E4 | On b6, `announce_switches` (b6 :2075) lists every switch by name, and the tests at :2801/:2829 are single string literals. Every topic would collide there. PT-0's `pt0-api.md` must guarantee the line and the test come from the list (its brief asks for this; verify on its hand-back). E3 and E4 edit different call sites (b6 :1307-1332 and :1253-1270): §. Better still if DR-E finds a handle the collectors already receive. |
| ★`nm` | PT-0, then E1 ∥ E2, then HD-3 and E4 | §. E2's design file list omits `nm`, but `tn_node.epoch_record_round_ended_certified_total` lives there. |
| ★`pri/metrics.rs` | PT-0, then PT-2B (parallel), then HD-1, then HD-2b | § for PT-2B; serial along the HD chain. |
| `pri/proposer.rs`, `proposer_tests.rs` | PT-0 → PT-3a → HD-1 → HD-2b | Strictly serial: PT-3a and HD-1 both change the `header proposed` line. |
| ★`pri/tests/network_tests.rs` | PT-2A (DROP with a test) or PT-2B, and PT-3v | Appends at the end of the file under each unit's marker; keep both at integration, as bench 6 did in `close_epoch.rs`. |
| ★`pri/network/handler.rs` | PT-0 (if 16695b20a touches it), then PT-2B | Check `git show --stat 16695b20a`. PT-2B needs a fresh worktree at the post-PT-0 head; phase A's worktree is at M. |
| ★`th` | HD-4a ∥ E5a | §: each adds its own constant, reader and list entries (M :185-193, :257-283). |
| `pri/certifier.rs` | HD-4a only | No ported topic touches it (grep on b6). |
| ★`it/main.rs` | PT-3b, ECF, HD-4b, E5b | One `mod` line each, §. PT-1 adds none (its brief). |
| `it/common.rs`, `e2e-tests/src/lib.rs` | PT-1 only | E5b and HD-4b keep their helpers inside their own modules. |
| `close_epoch.rs` | E1 → HD-3 | As the draft says. |
| `run_epoch.rs` | E1 only | — |
| `ss/epoch.rs`, ★`ss/metrics.rs` | E2 → E3 | Same order for both files. |
| ★`mgr/epoch_votes.rs` | E2 → E4 → E5a | E5a's hook read site is a third writer. |
| `pri/network/mod.rs` | E2 only | — |
| `it/epoch_close_forms.rs` | ECF only | Port and extension merged into one unit. |
| ★`bm/config.sh` | HB-1 → HB-2; HB-4's ports folded into HB-1 | Serial. Harness agents share one working tree and the orchestrator commits by path, so § cannot work for harness files. |
| `bm/arms/switches.tsv` | HB-2 only | — |
| `bm/report/provenance.py` | HB-2 only | HB-1 writes the engine key where the manifest is assembled. If that turns out to be `provenance.py`, HB-1 → HB-2 is already serial. |
| ★`test_node_image.py`, `MANIFEST-FIELDS.md` | HB-1 → HB-2 | `test_node_image.py` keeps `BENCH_NODE_SWITCH_KEYS` equal to `switches.tsv`. |
| ★`bm/tools/log-shapes.txt` | HB-3 → HB-5 | Serial. |
| ★`bm/benchmark-probe.sh` | nobody | 39 MDBX references and no owner: give it to HB-3 or declare it out of scope. |
| ★`tasks/bench7-report-<run>.md` | A11, A12 | Part files, joined by the orchestrator. |

## C. Waves

**Running now:** P1, P5, project-context, DR-1807, DR-E, PT-0, PT-2A.

**Start now (no dependency):**
- HB-4a (brief exists; outside `benchmark/`).
- U-C1 and U-I2 (briefs exist).
- U-SCRIPT.
- PT-1 at M (optional, D3).

**Start as each hand-back arrives:**
| hand-back | what starts |
|---|---|
| P1 | P1-FC, then P2 (four bundles). After the 4th bundle: HB-1 and HB-3, then HB-2, then HB-5. |
| DR-E | U-I1, U-I3. With PT-0 also back: E1, E2. Settle E1's switch name into W0-f. |
| DR-1807 | U-C3. With PT-0 also back: HD-2a, HD-4a. |
| PT-2A | U-C2. If PORT: PT-2B. Either way HB-2 can freeze the switch list. |
| PT-0 | Integrate 00; R-00. Then PT-1 (if not started), PT-3a, plus whatever DR-E and DR-1807 have unlocked. |
| PT-1 | Integrate 01; R-01. |
| PT-3a | HD-1, PT-3v, PT-3b. |
| E1 | HD-3, SS-03. |
| E2 | E3 and E4 together. |
| E4 | E5a. |
| E3 + E4 + E5a | E5b; SS-04. |
| HD-1 + HD-2a | HD-2b. |
| HD-2a | HD-2c. |
| HD-2b + HD-4a | SS-06 (it does not need the e2e). |
| HD-2b + HD-3 + HD-4a | HD-4b. |
| E1-E4 + PT-3a/3v | ECF; then R-05 and SS-05. |

**Critical path to the image cut:** PT-0 → PT-3a → HD-1 → HD-2b → HD-4b (lane) → R-06 (and fixes) → integration of 06 → G-TOP (lane) → IMG.
- That is four serial node units after PT-0, then the lane. The E chain (DR-E → E1/E2 → E3/E4 → E5a → E5b) is one level shorter, so it should not set the date.
- IMG also needs HB-1 for the image contract strings and the start line. That puts Track H on the path through P1 → P1-FC → P2's four bundles (memory: provenance > 30 min per bundle).

**Critical path to the first fleet launch:** IMG → HB-GATE (alone on the host) → dry plan with the digest → the user's go.

**Cargo slots:** three host-wide slots, not the agent count, cap Track N. When the queue is long, hold the off-path units (HD-3, E5a, PT-3v, HD-2c) before the critical ones.

**The e2e lane:** one job at a time; the bottleneck after HD-2b. Queue priority:
1. PT-1's smoke run (it unblocks every e2e unit).
2. HD-4b's runs whenever they are waiting: they are on the critical path and jump the queue.
3. E5b ×1, then G-04 (all-off sets plus E5b ×3) for PRs 03-04.
4. G-02 (all-off sets) for PRs 00-02.
5. PT-3b ×1 (its findings can reach PT-3a's follow-ups early).
6. ECF ×1.
7. G-TOP: each new test ×3 first (the likeliest to fail), then the sets with switches off, the sets with the bench-7 set on, and the mixed fleet (it is in ST-A).

To save lane time:
- Units run their e2e tests ×1 while developing; ×3 happens only at the gates.
- One gate run on head 02 serves PRs 00-02, and one on head 04 serves PRs 03-04.
- The long property-test hunt goes through a cargo slot alongside the lane, not after it.

## D. Corrections

1. **Commit attributions in the port index.**
   - 12bb5bb45 is the same change as 16695b20a: the tracker-drain gauge `tn_primary_epoch_entry_rounds_behind`. It belongs to PT-0 only; remove it from PT-2. PT-2's checkpoint already flags this.
   - 4e9c19782 is tracker-drain's ST-A e2e (`epoch_drain.rs`). It is not ported; remove it from PT-3.
2. **Superseded-refusal counter.** The plan puts it in PT-3; the pt3a brief moves it to PT-2B (`handler.rs`). If the verdict is DROP it has no home: decide whether to ship it as observability on M's handler or drop it.
3. **PT-1's stated reason for following PT-0 is wrong.** `TN_E2E_PARAMETERS` (d91d65d3e) moved into PT-1, so PT-0 touches no e2e file. PT-1 can start at M unless it wants a smoke run that reads the `node switches` line.
4. **E5's place in the stack.** E5's fifth test cannot live in `epoch_close_forms.rs` in head 04, because that file arrives in head 05 and its four tests need the quorum-exec-block switches. Put the fifth test in a new module (E5b, head 04). The four-test extension rides with the ECF port in head 05.
5. **Split, for the 200k budget or for parallel work.**
   - PT-3a: commit 4 → PT-3v. It shortens the critical path.
   - HD-2 → HD-2a (pure module), HD-2b (wiring), HD-2c (property test).
   - HD-4 and E5 → hook units (GP) and e2e units, one agent type each.
   - Contingency cuts if a unit passes 150k: HD-2b after the wiring and four core tests (the rest becomes HD-2d; drop the `digest_dedupe` interplay test, which is moot); E3 at the conflict halt; E4 between retained votes and the re-vote; HD-4b at the kill arm.
6. **Merge.**
   - The ECF port with E5's four-test extension (one writer per file).
   - The in-flight and serial-persist issues with the does-not-carry write-up (same facts).
   - SS-E3 and SS-E4 into SS-04 (one PR).
   - HB-4's listener ports into HB-1.
7. **Track H can start before the bundles.** It could run in a devnet-genesis worktree (`b7/harness`) instead of waiting for them: `launch.sh` only checks the main tree, and the harness rules forbid absolute home paths. HB-1's brief would need to confirm with `grep -rn devnet-genesis benchmark/`.
8. **Missing units.** W0-f (names contract), W0-g (ledger), U-SCRIPT, U-FC1, U-FC2, G-02, G-04, the post-gate units (U-P5, U-C4, P7-1, P7-FC, PT-3x), and review-fix units (GP, conditional).
9. **Dependencies the plan states wrongly or leaves out.**
   - HD-3 also needs DR-1807.
   - HD-4 also needs PT-1, PT-3a, HD-3, and the load helpers from the unported b6 `sealed_txs.rs` (`run_load_across_boundary` at :1131, `assert_exactly_once` at :1266).
   - The image probe and trial need HB-1.
   - HB-GATE needs the image and an otherwise quiet host.
   - PT-3b should drop `epoch_record_state_check` from `exec_block.rs` rather than wait for E1. That switch does not exist on M; ECF does need it.
   - HB-2's "three record switches" are four if E1 has its own switch.

## E. Agent Assignment Summary

| agent type and model | count | ids |
|---|---|---|
| general-purpose opus, node (`tn-rust-skills` + domains) | 15 (+PT-3x, + fixes) | PT-0, PT-1, PT-2B, PT-3a, PT-3v, HD-1, HD-2a, HD-2b, HD-3, HD-4a, E1, E2, E3, E4, E5a |
| opus read-only (node) | 3 | PT-2A, DR-1807, DR-E |
| `tn-write-e2e-agent` opus | 4 | PT-3b, ECF, HD-4b, E5b |
| `tn-write-proptest-agent` opus | 1 | HD-2c |
| `tn-review-agent` opus | 7 | R-00 … R-06 (per topic, as the plan says) |
| `tn-security-eval` | 4 | SS-03, SS-04, SS-05, SS-06 |
| general-purpose opus, harness | 6 | HB-1, HB-2, HB-3, HB-4a, HB-5, U-SCRIPT |
| opus writers (`human-writing`) | 15 | P1, P5, U-C1, U-C2, U-C3, U-I1, U-I2, U-I3, U-P1, U-P2, U-P3, A11, A12, U-P5, U-C4 (+P7-1) |
| opus figure-checks | 6 | P1-FC, P5-FC, U-FC1, U-FC2, A13, P7-FC |
| opus analysis | 18 | A1-A8 ×2, A9, A10 |
| sonnet | 1 | project-context |
| orchestrator jobs | 17 | W0-c, W0-f, W0-g, P2, P3, P4, G-02, G-04, G-TOP, IMG, HB-GATE, Track U creation, RUN-7a, RUN-7b, GATE-F, bench-7 publish, WRAP |

That is about 80 agents in total. Peak parallelism comes right after PT-0, DR-E and DR-1807 return: about 14 agents, capped in practice by the three cargo slots and the single e2e lane.

## Orchestrator's rulings (2026-11-14, after DR-E and DR-1807 returned)

- **E1 has NO switch and does not wait for PT-0** (DR-E: M's guard is unconditional; the plan says to extend it where it is). E1 and E2 were started at M. E1 owns `crates/node/src/metrics.rs` inside `EpochMetrics` only; E2 counts with the `tn_node.*` macro pattern already in `epoch_votes.rs` and touches no node metrics file. `cfg` is not E1's.
- D1 accepted: 12bb5bb45 is PT-0's (same change as 16695b20a); 4e9c19782 is not ported.
- D2: the superseded-refusal counter goes with PT-2B if the verdict is PORT; if DROP, it is dropped with the fix (the refusal it counts would not exist).
- D3 accepted: PT-1 starts at M.
- D4 accepted: E5b's test lives in a new module `it/epoch_record_walk.rs` (head 04); the four `epoch_close_forms.rs` tests are ported and extended by ECF (head 05).
- D5 accepted: PT-3v, HD-2a / HD-2b / HD-2c, HD-4a / HD-4b, E5a / E5b. HD-2a is the pure module only (no switch field), so it starts at M; HD-2b adds the field.
- D6 accepted (U-I3W already runs merged; listener ports go to HB-1 as a bench-only `net.ipv4.ip_local_reserved_ports` step, not a port change: the ports are in the repo-root `config.sh` that the devnet scripts share).
- D7 not taken: Track H waits for the fourth bundle launch (one working tree, simpler commits).
- D8: `tasks/bench7-contract.md` and `tasks/bench7-cherrypick-ledger.md` are the orchestrator's, written at PT-0's integration.
- `benchmark/benchmark-probe.sh` (the standalone MDBX write-back probe) is out of scope for bench 7: no owner, not touched.
