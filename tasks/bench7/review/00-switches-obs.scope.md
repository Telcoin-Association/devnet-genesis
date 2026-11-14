# Scope: head 00 `feat/bench6-switches-obs` (unit PT-0)

- Worktree: `/home/drtnarg/coding/telcoin/tn-b7-pt0` (branch `b7/pt0`). Base 45dce8947, tip d8273bbe3. Diff: `git diff 45dce8947..d8273bbe3` (9 files, +1098/−32).
- Commits, in order: a233d64dc, 0777ed06e, be63208e5 (the switch machinery: `runtime_switches!` in `crates/config/src/node.rs`, the `node switches` line, the `tn_node_switch` gauge), 3d100a147 (gauge `tn_primary_epoch_entry_rounds_behind`), adfd41f41 (sub-millisecond buckets for ten stage histograms), 7471f329e (a digest's first receipt kept across a re-queue; changes what `tn_primary_digest_wait_seconds` measures), a91cfe02a, 12148de2c, d8273bbe3 (review follow-ups).
- Switch: none is added here; this is the machinery that later topics add their switches to. No behaviour change is intended at all.
- Upstream: no issue; this is PR 00 of the stack.
- Claims and residuals: the unit's hand-back in `tasks/checkpoint-bench7-PT-0.md`; the API note `tasks/bench7/briefs/pt0-api.md`; bench 6's review of the same topic `tasks/bench6/review/plumbing-report.md` (its open follow-ups: unknown keys in `parameters.yaml` are ignored without a warning, pre-existing; `tn_primary_digest_wait_seconds` changed meaning without a rename).
- Security evaluation: no.
- Questions specific to this topic:
  1. With zero switches defined, is anything different from main except the one `node switches` info line at start, the new gauges and the bucket layout? In particular: does `Parameters` serialize and deserialize every existing `parameters.yaml` exactly as on main (a written file byte-identical when no switch is set)?
  2. The epoch-entry gauge keeps a process-wide static (`Mutex<Option<(Epoch, Round)>>` in the primary's `metrics.rs`): can it be poisoned, contended on a hot path, or wrong across an epoch change or a mode change?
  3. `proposed_first_received` (commit 7471f329e) in the proposer: can an entry be left behind forever (a leak across an epoch), and is anything it stores read on the path that decides a header's contents?
  4. The bucket change: does it alter any metric's NAME or label set (dashboards and the benchmark's readers depend on the names)?
  5. Is the `runtime_switches!` macro's guard test (`switches_list_every_switch_field`) enough to stop a later topic from adding a field that is not listed?
- Report: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench7/review/00-switches-obs-report.md`. Checkpoint: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench7-R-00.md`.
