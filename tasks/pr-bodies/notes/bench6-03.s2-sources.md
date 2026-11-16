# Sources: bench6-03-closing-block-check.md (#1865), second pass: the switches go in {{pr-09}} (not posted)

This PR has no switch. Its three mentions of switches, checked against the stack as it merges:
- :6 "No switch: this extends main's unconditional stored-record guard (#1834, #1849), …": true of this diff, and after {{pr-09}} the stack has no switch at all. Unchanged.
- the two lines of the `Stack-wide gates` block ("once with every switch off and once with the full stack's six switches on"; "passed with every switch off and with the six on"): they report runs that were made; the block belongs to a script. Unchanged.
`Refs #1851` unchanged: its pointer to `epoch_close_forms.rs` still holds after the removal (the file exists at 57a55b221 on `refactor/remove-bench-switches`; pr9-facts R3 keeps `test_held_member_two_closes` and `test_missed_record_round` and deletes only their adaptive twins).
Line numbers are those of the edited file.

## Changed sentences

1. Testing :58-59 (stale-phrase item).
   Old: "- Not run: no fleet has run this head (a benchmark of the stack's earlier cut on main at 45dce8947, which carries the check, is under way), and no e2e test makes the check fire."
   New: "- Not run: no fleet has run this head, and no e2e test makes the check fire." and "Bench 7 ran the stack's earlier cut on main at 45dce8947, which carries the check, on 2026-11-15: [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/) and [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/), ten validators at 20,000 IOPS, one run each; #1868 and #1869 report its results."
   Sources: brief point 6 (ran 2026-11-15, the two run ids, the cut on 45dce8947); "which carries the check" is the old sentence's; #1869's body `tasks/pr-bodies/bench6-06-digest-order-hold.md:67` ("ten validators at 20,000 IOPS, one run each"), #1868's body `bench6-05-quorum-exec-block.md:23` ("at 20,000 IOPS with ten validators"). No result about the check is stated.
2. Related :89 (stale-phrase item, old :88).
   Old: "- Next: `fix/epoch-record-collector-hardening` builds on this head."
   New: "- Next: #1866 (`fix/epoch-record-collector-hardening`), #1867 (`fix/epoch-loop-output-drop`), #1868 (`fix/1804-quorum-exec-block`) and #1869 (`fix/1807-digest-order-hold`) build on this head, and last {{pr-09}}, which removes the stack's switches."
   Source: brief "What happened" (the stack's numbers and branches, bottom to top).

`{{pr-09}}` placed: 1.
