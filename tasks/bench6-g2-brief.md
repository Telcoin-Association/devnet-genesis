# Bench 6 — gate G2: the go for run 1 (written 2026-11-12 ≈ 11:00Z)

Nothing has been launched on the fleet.
Everything the handoff listed before this gate is done except one step that the session is not permitted to take: pushing the node image.
Details behind every line: `tasks/bench6-g2-notes.md` (N1-N7) and `tasks/checkpoint-bench6-orch.md`.

## 1. Two things only you can do

1. **Build and push the node image** (the permission system refused it to this session; about 6 minutes, the cache is warm):
   ```
   setsid bash tasks/bench6/orch-image-cut.sh /home/drtnarg/coding/telcoin/telcoin-network-b6 2df831e3c bench6-arms-20261112 > tasks/bench6/image-build-bench6-arms-20261112.log 2>&1 < /dev/null &
   ```
   It builds from the pushed branch only (`bench/bench6-2026-11` = `2df831e3c` on the remote), as `etc/Dockerfile` does, pushes `us-docker.pkg.dev/telcoin-network/tn-public/adiri:bench6-arms-20261112` and writes the digest to `tasks/bench6/image-build.meta.json` (last log line `IMAGE-CUT done rc=0`).
   Then the session probes it by digest, fills the env files and commits them.
2. **`gcloud auth login`** right before the launch (the token is valid now; run 1 is about nine hours and the teardown must not outlive it).

Optional tidy-up: `kill 84214` (a stray shell of this session that keeps four redundant e2e jobs of the first lane parked; the session may not kill it; nothing depends on it).

## 2. What is ready

| item | state |
|---|---|
| Node branch | `bench/bench6-2026-11` = **2df831e3c** = base 165e3fe01 + 98 commits, pushed. Pipelined persist is IN (your G1 answer 2): gate 5 passed on a quiet host, gate 6 passed (switch-off e2e sets 11/11, 11/11, 12/12). |
| Node tests on that head | workspace fmt, check, clippy clean and 4,388 tests, twice; the repo's e2e sets with all twelve switches on 11/11, 11/11, 12/12, and the node's own `node switches` line shows the twelve; the three pipelined e2e tests 5 of 5 runs. Every commit was reviewed (ten topic reviews and a delta review, no Critical or High). |
| Node image | NOT pushed (item 1 above). A local build of the same commit succeeds (329 s); its binary carries every contract string, the twelve switch keys, sub-second timestamps from genesis, and no test-delay hook. |
| Generator | `tn-transaction-generator` main pushed at 62bbd5f; image `…/txgen/tn-transaction-generator:blast-v2-62bbd5f` = `sha256:7cefcc50…c605a59`. |
| Harness | Head ec42468 (+ task files). Full gate alone on the host: 1,530 of 1,531 tests and 491 of 491 mutation cases; the one failure was the launcher's (`nohup` ignores SIGHUP) and that module's gate is clean without it. After the last arm-file edit the gate of the seven modules that read arm files: 406 tests, 195 of 195 mutations, clean. |
| Dry runs | Every arm file through the arm tool's `--print-state` (rc 0, switch sets as designed); the teardown's dry mode (0 candidates: the project holds nothing bench-labelled; 21 gcloud commands checked); the deploy's dry plan for both env files. The registry probe waits for the pushed digest. |
| Bench-5 page | Corrected and live since 02:56Z (G1 answer 4). |
| Base | No rebase: `origin/main` moved six commits; on the default build they change no block, consensus message or persist step. |

## 3. Decisions

**D1. Run 1 as planned?** Nine arms, sixteen blasts, about 7 hours of walk, plus 46 minutes of deploy and 35 of teardown.

| k | arm | steps | adds |
|---|---|---|---|
| 0 | `a0-control` | I, L, M4, M16 | the fleet as deployed (bench 5's behaviour) |
| 1 | `p1-mdbx-advice` | M16 | whole-map random-access advice, with the page-cache eviction |
| 2 | `v-vote` | L, M16 | vote fix, adaptive form |
| 3 | `v-vote-floor` | L, M16 | vote fix, always-on form |
| 4 | `pool-local` | M16@epoch | recovery pool, sealed-transaction keep, digest dedupe, tracker drain |
| 5 | `pipe` | M4, M16 | pipelined persist |
| 6 | `bound` | M4, M16 | admission bound (3 outputs) |
| 7 | `gr150` | I, L, M16s | parent grace 150 ms |
| 8 | `a0-prime` | M16 | closing control, with the eviction |

Recommendation: go as planned.
What changed since G1 that bears on it: upstream is leaving MDBX (draft PR #1834 makes tn-lmdb the default, aimed at the 2026-11-16 freeze).
The advice arm is then the MDBX baseline and the evidence of the mechanism, not a change upstream will need for long.
Pipelined persist's measured gain would not carry to storage v2 without a new design (v2 assumes no persist overlaps the next build).
If you would rather not spend fleet time on it: dropping it means taking `pipelined_persist` out of `pipe`, `bound` and `gr150`, the bound back to 2, and about 45 minutes less; the image keeps the switch, off.

**D2. Run 1b, the local-SSD deployment — which shape?** About 3 h 50 min of fleet time after run 1's teardown, three arms (control, advice, control with eviction).
Recommendation: the split fleet, in run 1's own zones, one deployment:

| group | validators | machine type | RAM | database on |
|---|---|---|---|---|
| local SSD | 03, 04, 05, 06, 07, 10 | `c3-standard-8-lssd` | 32 GiB | first local NVMe SSD |
| Hyperdisk, same RAM | 01, 02 (and the observer) | `c3-standard-8` | 32 GiB | Hyperdisk boot disk |
| Hyperdisk, run 1's shape | 08, 09 | `c3-highcpu-8` | 16 GiB | Hyperdisk boot disk |

Every validator executes the same outputs, so the two disk classes are compared at the same load and time.
Its limits: `c3-standard-8` does not exist in Hong Kong or Seoul, so the same-RAM Hyperdisk group is two validators; the disk class follows the region; the fleet's throughput is a mixed fleet's.
Alternatives: `c4-standard-8-lssd` in eight zones with two validators moved (another CPU generation, and a second deployment for the Hyperdisk leg); seven validators on C3 (not supported today: one more harness unit); or no run 1b.
First live use in run 1b: the bench's own create of `-lssd` nodes (TERMINATE host-maintenance policy, as the probe used; whether live migration is accepted could not be read, web access being denied), the mount script, and a mount point as the data directory under the deployment scripts. Each fails early and loudly: at the create, at the mount, at key generation.
A local SSD's write size limit is 2 MiB against the Hyperdisk's 256 KiB (`max_sectors_kb`); left at the defaults and reported.

**D3. Bench-5 page, one more sentence?** The page's caveat 2 still says that how memory pressure undoes the large blocks "is untested".
A local test did measure it (11 times fell to 4.3 times without the advice, 5.0 to 1.00 with it).
Recommendation: correct that sentence and republish (the same procedure as today's fix, about 10 minutes).

## 4. After your go
Fill the env files (run id, image digest, node and generator commits), commit, then per `benchmark/launch/README.md`:
`deploy12` → `arms --dry-run` → `arms` → `step15` → `teardown-dry` → `teardown` → `archive` → `reindex` → `arms-summary`; then run 1b with `bench6-run1-lssd.env` (its plan is pinned in the env file); then the analysis units and gate G3.
If the permission system refuses a launch command to the session, it will give you the exact line to run.
Stop rules stay as planned: an arm that shows the final-state halt line is stopped; the vote arms are read before `pipe` and `bound` run.

## 5. Owed, not blocking
- The per-commit compile check of the 98 commits is running now (needed before upstreaming; touch `tasks/bench6/STOP-per-commit` to stop it between two commits).
- Three mutation cases were left out (their tests raise before they assert); the launch README (H6b) and the first e2e lane's wait pattern are wrap-up items.
- The upstream port after the run: mechanical except the timing code in `tn-reth/src/env/execution.rs` and `output_overlay.rs`; the advice file must be gated off under the tn-lmdb feature.
