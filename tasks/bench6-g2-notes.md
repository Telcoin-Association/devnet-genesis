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
