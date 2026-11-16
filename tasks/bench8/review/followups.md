# Removal units — review follow-ups still to apply (orchestrator's list; a closing unit applies them)

| from | severity | where (at the reviewed tip) | what |
|---|---|---|---|
| RV-1a (a5be61615) | Low | `crates/e2e-tests/tests/it/epoch_record_walk.rs:471` | "the walks: with the walk on, each validator walks past K once": drop "with the walk on" |
| RV-1a (a5be61615) | Low | `crates/state-sync/src/epoch.rs:132`, `:539`, `:1816`, `:1869`, `:1905`, `:2101`, `:2508` | doc lines left short after the switch clause was cut: rewrap (wording is correct) |
