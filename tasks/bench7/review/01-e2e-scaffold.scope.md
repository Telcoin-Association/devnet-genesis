# Scope: head 01 `test/bench6-e2e-scaffold` (unit PT-1)

- Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt1` (branch `b7/pt1`). Base 45dce8947, tip 653e6ab51. Diff: `git diff 45dce8947..653e6ab51` (test code only: `crates/e2e-tests/src/lib.rs` +674, `crates/e2e-tests/tests/it/common.rs` +134/−4, `tests/it/restarts.rs` +5/−70).
- Commits, in order: dddfd2014, f70b56841, eb51c0449, b9ef644cb, 653e6ab51.
- Switch: none (test harness). No node crate is touched.
- Upstream: no issue; this is PR 01 of the stack.
- Claims and residuals: the unit's hand-back in `tasks/checkpoint-bench7-PT-1.md`; the API note `tasks/bench7/briefs/pt1-api.md`; bench 6's review `tasks/bench6/review/plumbing-report.md` (open: `TN_E2E_PARAMETERS` accepts a mistyped key and does not reach one epochs test).
- Security evaluation: no.
- Questions specific to this topic:
  1. Does a test that passes no override start its nodes exactly as on main (same `parameters.yaml` bytes, same environment, same arguments)? Name any difference.
  2. `parameters.yaml.harness-base` and `parameters.yaml.merging` in a node's datadir: can a crash between writes leave a node with a half-written `parameters.yaml`; can a restart helper without overrides silently drop a previous override (the unit says yes and documents it: is the doc enough or is it a trap for a test author)?
  3. `TN_E2E_PARAMETERS`: which of main's e2e tests does it NOT reach (the unit lists three places), and can a mistyped key pass silently (it can: main ignores unknown keys)? Is there a cheap guard (the node's `node switches` line arrives with head 00: a test helper that asserts the key is reported)?
  4. The moved log helpers: any test filter in the Makefile, the nextest config or the workflows that selected a test by its old module path?
  5. Fixed ports and parallelism: does anything in the scaffold make two tests more likely to collide than on main?
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench7/review/01-e2e-scaffold-report.md`. Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench7-R-01.md`.
