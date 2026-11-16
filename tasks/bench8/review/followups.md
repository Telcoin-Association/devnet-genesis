# Removal units — review follow-ups still to apply (orchestrator's list; a closing unit applies them)

| from | severity | where (at the reviewed tip) | what |
|---|---|---|---|
| RV-1a (a5be61615) | Low | `crates/e2e-tests/tests/it/epoch_record_walk.rs:471` | "the walks: with the walk on, each validator walks past K once": drop "with the walk on" |
| RV-1a (a5be61615) | Low | `crates/state-sync/src/epoch.rs:132`, `:539`, `:1816`, `:1869`, `:1905`, `:2101`, `:2508` | doc lines left short after the switch clause was cut: rewrap (wording is correct) |
| RV-1b (b67c0acdd) | Low | `crates/node/src/manager/epoch_votes.rs:3239` | private label "P2's same-digest branch" in a test doc: say what the branch is instead |
| RV-1b (b67c0acdd) | Low | `crates/node/src/manager/epoch_votes.rs:4572` | private label "V3:" in a test doc: drop it |
| RV-1b (b67c0acdd) | Low | `crates/node/src/manager/epoch_votes.rs` (tests) | no test shows that a certified latest record re-armed at startup gets no vote of this node's own (only the guard `cert_by_digest(...).is_none()` at `:727`): run row `(false, true)` of `test_startup_rearm_recertifies_behind_a_certified_latest_record` through `spawn_epoch_vote_collector` and assert the published epochs are {1} |
| RV-1b (b67c0acdd) | Low | doc of `recertify_older_record` (and the PR text) | the operator note "a later pick stops the node again until an operator acts" went with the removed field's doc (`config/src/node.rs` at the base `:432-440`): carry it to the function's doc |
| RV-1b (b67c0acdd) | Low | `crates/e2e-tests/tests/it/epoch_record_walk.rs` (Walk arm) | "every re-certify pick is for K" must now hold at every close of the run: a flake risk if any older record is left uncertified; watch it in the three e2e repetitions, and narrow the check to the closes around K+2 if it flakes |
| RV-1b (b67c0acdd) | Low | `epoch_votes.rs:1164`, `:4573`; `epoch_close_forms.rs:209`; `epoch_record_walk.rs:184` | comment lines left short after the switch words were cut: rewrap |
