# Bench 6 — notes for gate G2 (orchestrator's running list; the brief for the user is cut from this)

Started 2026-11-12T02:49Z. G2 = the user's go before any fleet action. Bring: the final run-1 arm table and its fleet time, the
local-SSD deployment's shape choice and plan, the image digests, the dry-run results, what is still owed.

## N1. Base re-check (B1, `tasks/bench6/base-recheck-2026-11-12.md`)
- `origin/main` moved 9aa1d6139 -> 6167184c0 (6 commits): #1759 (a TN-owned storage engine; the merged feature and crates are named
  `tn-lmdb`, off in the default build), a primary-sync hold-budget fix, and a separate advisory fix (967bbf959, reserved connections
  for privileged peers).
- **Recommendation: do not rebase the image.** On the default build #1759 changes no block, consensus message or persist step (still
  MDBX, same page size; plus six per-block timing histograms and RPC cache tasks under the task manager). The sync fix exempts
  committee keys from its budgets; the one change a validator sees is one RTT less per sync-stream open. Four of the six merge
  conflicts belong to the base PRs (#1826, #1827, being resolved in another session). A rebase would void the reviews and e2e runs
  on 80a0c76c0 for no measured gain.
- **Upstream is leaving MDBX.** PR #1834 (draft, aimed at the 2026-11-16 freeze, merges cleanly on main) makes tn-lmdb the default
  and keeps MDBX one release as an opt-in. What that does to bench 6's storage topics:
  - tn-lmdb still writes through a shared memory map and the page cache, so the whole-block write amplification applies to it too,
    but it already gives the kernel the random-access advice on every mapping. The `mdbx_random_advice` arm stays worth running as
    the MDBX baseline and as evidence of the mechanism; upstream will not need the change for long.
  - Pipelined persist: storage v2's parallel storage roots and execution cache assume that no persist overlaps the next build. A win
    measured on MDBX does not carry to v2 without a new design. The user's G1 answer (in if gates 5 and 6 pass) stands unless changed.
  - The per-persist log fields have a tn-lmdb counterpart the node does not export yet: the method carries over, the names do not.
  - A tn-lmdb arm is not possible on this base (it needs #1759, and #1834 for v2): a different image.
- Upstream port after the run: mechanical except the timing code in `tn-reth/src/env/execution.rs` and `output_overlay.rs`;
  `mdbx_advice.rs` must be gated off under the tn-lmdb feature; the held stack needs a v2 design if #1834 has landed.
- Not determined: the size of the one-RTT effect; tn-lmdb's amplification on Hyperdisk under node load; whether #1834 lands by the freeze.

## N2. Bench-5 page (published under the G1 authorisation; see the checkpoint for the commit)
- Sentences the probes also contradict, NOT changed (outside the authorisation): the page's caveat 2 says how memory pressure undoes
  the large blocks "is untested" (the local probe measured it: 11x -> 4.3x without the advice, 5.0x -> 1.00x with it); the internal
  report has the same claim twice and a lever line that gives the advice as 1.00x without saying it must be applied before the large
  blocks exist (applied after a read-through: 11.88x).

## N3. The local-SSD deployment (design L0: `benchmark/private/bench6-prep/design/design-local-ssd-deployment.md`)
- What the harness does today, which changes the premise: a node has NO separate data disk. The 100 GB Hyperdisk Balanced is the boot
  disk and `/var/lib/telcoin` is a directory on it. The change is to mount the `-lssd` shape's first local SSD at `/var/lib/telcoin`
  before the node's keys are generated; the sampler, host probe, fsync probe, eviction and folio census follow the data directory.
- **D-L1, the shape — recommendation (e), a split fleet, not one of the handoff's four options:** validators 03, 04, 05, 06, 07, 10 on
  `c3-standard-8-lssd` (data directory on the local SSD); validators 01, 02, 08, 09 and the observer on `c3-standard-8` (data directory
  on the Hyperdisk boot disk); run 1's own zones, nothing moved, one deployment. Every validator executes the same outputs, so commit
  time, write count, sync count and write size compare the two disk classes at the same load and time, on the same CPU and RAM.
  Confounds: the disk class follows the region (local SSD: Sydney, Tokyo, Ashburn, Netherlands, Singapore, Mumbai; Hyperdisk: Los
  Angeles, London, Hong Kong, Seoul), and the fleet's throughput is a mixed fleet's, not an all-local-SSD fleet's.
  The other options and their confounds: (a) mixed C3/C4 local SSD — two CPU generations and two SSD devices; (b) C4 in eight zones,
  two validators moved — a C4 CPU against run 1's C3 and two latencies changed; (c) seven validators on C3 local SSD — a committee of
  seven, not supported by the harness today (about one more unit); (d) other regions — another latency matrix.
  **Corrected after the zone reads (2026-11-12T03:05Z):** `c3-standard-8` does not exist in Hong Kong or Seoul (only `c3-highcpu-8`
  among the 8-vCPU C3 shapes, there and in their fallback zones). So (e) has three groups: six validators on `c3-standard-8-lssd`
  (32 GiB, local SSD); validators 01 and 02 and the observer on `c3-standard-8` (32 GiB, Hyperdisk); validators 08 and 09 on run 1's
  `c3-highcpu-8` (16 GiB, Hyperdisk). The same-RAM Hyperdisk comparison then rests on two validators (Los Angeles, London); the
  16 GiB pair pairs with run 1 directly and shows what the extra RAM does on the same disk. The summary groups by (disk class,
  machine type). Alternative for those two: `c4-standard-8` (30 GiB) — a second CPU generation; not recommended.
- D-L2: the Hyperdisk leg on the same shape comes inside (e) (two validators); under (a)-(d) it is a second deployment.
- D-L3 plan: `a0-control I L M4 M16`, `p1-mdbx-advice M16`, `a0-prime M16` (run 1's steps and relative order, so rows pair with run 1).
- D-L4 when: after run 1's teardown, before G3, with run 1's image. About 3 h 50 min of fleet time, about $40.
- D-L5: one local SSD (the first of the two on `c3-standard-8-lssd`), as the probe measured it; no RAID 0.
- D-L6: `read_ahead_kb` is 128 on both devices (probe r20261112-0024): nothing to set. But `max_sectors_kb` is 256 on the Hyperdisk and
  2,048 on the local SSD (and `nr_requests` 511 against 1,023): a write can be up to 2 MiB on the local SSD. Left at the defaults and
  stated; the per-write size is reported per class.
- D-L7: a local-SSD node keeps the fleet's Hyperdisk boot disk (OS, docker, logs on the same device on every node).
- D-L8: no page for this deployment; a section of run 1's analysis.
- Not verified (web access is denied in this session, so the GCE documentation could not be read): whether a local-SSD shape accepts
  live migration. The harness therefore creates `-lssd` nodes with the TERMINATE policy the probe used live. Consequence to accept: a
  host maintenance event during the 4-hour deployment would stop that node and blank its SSD; the deploy refuses to re-format a node
  whose SSD was mounted before (it reports `lost`), so such a node shows as down, never as silently restarted on an empty database.
- Quota binds nowhere (C3 100-300 vCPUs per region, C4 300, local SSD GB unlimited); `c3-standard-8` and `c3-standard-8-lssd`
  availability per zone: the handoff's table (the six local-SSD zones have it); `c3-standard-8` in the four Hyperdisk zones and the
  fallback zones still to read before G2.

## N4. Run 1's arm table as it stands (final at G2; `benchmark/launch/bench6-run1.plan`)
| k | arm | steps | what it adds |
|---|---|---|---|
| 0 | `a0-control` | I, L, M4, M16 | the fleet as deployed, every switch at bench 5's behaviour |
| 1 | `p1-mdbx-advice` | M16 | whole-map random-access advice, with the page-cache eviction |
| 2 | `v-vote` | L, M16 | the vote fix, adaptive form (4 rounds after a starved header) |
| 3 | `v-vote-floor` | L, M16 | the vote fix, always-on form (G1 answer 1: both forms) |
| 4 | `pool-local` | M16@epoch | recovery pool, sealed-transaction keep, digest dedupe, tracker drain |
| 5 | `pipe` | M4, M16 | pipelined persist — ONLY if gates 5 and 6 pass (G1 answer 2); otherwise the line is dropped |
| 6 | `bound` | M4, M16 | the admission bound |
| 7 | `gr150` | I, L, M16s | parent grace 150 ms (100 ms is the fallback arm, not in the walk) |
| 8 | `a0-prime` | M16 | the closing control, with the eviction |
Sixteen blasts, about 7 hours of walk (about 6 h 15 min without `pipe`), plus the deploy (46 min) and the teardown (35 min).
Then run 1b, the local-SSD deployment (N3): three arms, five blasts, about 3 h 50 min including its own deploy and teardown.

## N5. What the harness gained for run 1b (all committed, all with tests; nothing run against the cloud)
config knobs (b7ee67b), mount builders (b9b023a), arm summary by disk class and machine type (1729bd0), multi-type create (df9e97a),
the mount at deploy step 3 and the check at step 7 (4e0a42c), launch files and the plan pin (8ae3866, 2e68acc), 71 mutation cases
and a rehearsal of the data path (cdabcbd). With every new knob unset the deploy's dry plan, its create calls and every pre-start
session are byte-identical to before. A real defect was found on the way: the quota check would have stopped a live deploy on the
"unlimited" local-SSD quota (fixed).
First live use of: the bench-owned create of `-lssd` nodes (TERMINATE policy), the mount script, a mount point as the data directory
under the deployment scripts' key generation. Each fails early and loudly if wrong (step 2, step 3, step 5).
