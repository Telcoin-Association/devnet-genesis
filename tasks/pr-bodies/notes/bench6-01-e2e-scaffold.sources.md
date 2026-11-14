# Sources: bench6-01-e2e-scaffold.md (not posted)

Head `test/bench6-e2e-scaffold` = 9ef55c989, previous head 8a42fec57 (7 commits), read with `git -C /home/drtnarg/coding/telcoin/telcoin-network show <sha>` and `git diff 8a42fec57..9ef55c989` (3 files: crates/e2e-tests/src/lib.rs, tests/it/common.rs, tests/it/restarts.rs).
Unit branch shas (PT-1, on main) map to the stack's: dddfd2014→422d3fbbd, f70b56841→41b953c56, eb51c0449→4ab437182, b9ef644cb→90d38b400, 653e6ab51→41b07e55a, cf5f865c0→1ebd9ddd7, 6e20da24d→9ef55c989 (same subjects; ledger row 01 "picked from the unit branch, no conflict").

## Figures and claims

| text | source |
|---|---|
| bench 6 e2e needs mixed fleets; restarts/epochs/sigkill sets must pass with each switch on | commit bodies 422d3fbbd, 90d38b400 |
| main copies one shared parameters.yaml, lib.rs:356, :388 | `git show 45dce8947:crates/e2e-tests/src/lib.rs` lines 356, 388 |
| only `start_validator_with_env` takes env, common.rs:527; start_nodes / observers none | `git show 45dce8947:crates/e2e-tests/tests/it/common.rs` 527-560 (`extra_env`), 657 (`start_named_observer` signature), 1122 (`start_nodes` signature) |
| log helpers private to restarts.rs:1368-1388, :2074 | `git show 45dce8947:crates/e2e-tests/tests/it/restarts.rs` |
| per-commit descriptions | commit bodies and diffs; `apply_parameters` at 9ef55c989 lib.rs:548-590; notice text lib.rs:793-795 |
| no override + variable unset = main's bytes, args, env; one `exists()` per start; variable read once, silent when empty | tasks/bench7/review/01-e2e-scaffold-report.md 2a (at 653e6ab51); `had_base = harness_base.exists()` in apply_parameters at 9ef55c989 |
| moved helpers byte-identical; no filter selects the moved test by path | review 2a last line, 2g.4 |
| docs warn chain-affecting keys fork the fleet (basefee_address, gc_depth) | lib.rs:443-449 at 9ef55c989 |
| 16 lib unit tests, test names | `#[test]` fns in lib.rs at 9ef55c989 (16); PT-1 checkpoint r2-libtests 16/16 |
| head gates: fmt clean; `cargo check --locked --all-targets -p e2e-tests -p tn-config -p tn-node`; `cargo nextest run --locked --no-fail-fast -p e2e-tests --lib -p tn-config` 160 passed | tasks/bench7-cherrypick-ledger.md per-head record 01; log tn-b7-stack/target/tmp/head01-9ef55c989.log (`CHECK EXIT=0`, `160 tests run: 160 passed, 0 skipped`, `TEST EXIT=0`); fmt command per ledger rule 2 with rust-nightly = nightly-2026-03-20 |
| unit gates before stacking: clippy (-p e2e-tests --all-targets) clean, 16 lib tests, 1 doctest | tasks/checkpoint-bench7-PT-1.md (FOLLOW-UP R2 gates); tn-b7-pt1/target/tmp/r2-clippy.log EXIT=0, r2-libtests.log `16 tests run: 16 passed`, r2-doctests.log `1 passed` |
| e2e: test_restarts_observer + test_log_field_reads_whole_fields passed, variable unset, on first five commits | PT-1 checkpoint ("e2e via lane 2", listed before the R1/R2 follow-ups); tn-b7-pt1/target/tmp/e2e-observer.log (`2 tests run: 2 passed`, EXIT=0) |
| first caller in the stack: exec_block.rs of `fix/1804-quorum-exec-block` | `git grep FleetOverrides|start_validator_with_overrides` at a11f14b1b and b7/int 8d4674666: only common.rs and exec_block.rs; exec_block.rs from 2ef63eb3e, footer `Topic: quorum-exec-block`; none in heads 02/03/04-node (6ad315794, 6d8fe775b, b30607017) |
| limits | review R2 (fixed by notice, 9ef55c989, trap remains), R3 (not fixed, optional), R4 (not fixed, optional, no effect on main), R5 (doc sentence asked "before upstream PR": NOT added at 9ef55c989, stated in the text), 2g.3 (mistyped key; `node switches` guard not added) |
| R1 fixed | 1ebd9ddd7 (unit cf5f865c0) |

## Left out

- The review's list of every e2e module the variable reaches (2g.3), for length.
- `parameters.yaml.merging` left after a refused merge (review 2e), minor.
