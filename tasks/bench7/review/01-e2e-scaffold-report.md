# Review R-01: topic 01, e2e scaffold (`test/bench6-e2e-scaffold`, unit PT-1)

Scope: `/home/drtnarg/coding/telcoin/tn-b7-pt1` (branch `b7/pt1`), `git diff 45dce8947..653e6ab51`, commits dddfd2014, f70b56841, eb51c0449, b9ef644cb, 653e6ab51.
Files: `crates/e2e-tests/src/lib.rs`, `crates/e2e-tests/tests/it/common.rs`, `crates/e2e-tests/tests/it/restarts.rs`.
Test-harness code only; no node crate is touched.
Done: the code review (tn-review) on that range, with the five raw findings verified independently by a findings-verifier run.
Not done, as the scope says: the security evaluation.
Line numbers are at the tip 653e6ab51, paths relative to `crates/` unless given in full.

## Verdict: APPROVE WITH FOLLOW-UPS

Nothing here can hurt a ten-node benchmark run: the image does not contain this code.
A test that passes no override starts its nodes exactly as on main, apart from one `stat` per start (2a).
The verification confirmed all five findings and found no false positives.
One is a real but narrow bug (R1, a process leak on an error path); one is a documented test-authoring trap (R2); three are informational.

| # | Title | Severity | Status | Fix before image | Fix before upstream PR |
|---|-------|----------|--------|------------------|------------------------|
| R1 | `start_nodes_with_overrides` leaks the nodes it already spawned when a later node's apply fails | Low | CONFIRMED | no | yes (three-line hoist) |
| R2 | A restart through a helper without overrides silently drops the node's own entries | Low | CONFIRMED | no | recommended (one warn line) |
| R3 | `parameters.yaml.harness-base` is written with a non-atomic `fs::copy` | Info | CONFIRMED, unreachable | no | optional |
| R4 | `db load-state` runs before the observer's first start, so it never sees `TN_E2E_PARAMETERS` | Info | CONFIRMED, no effect at M | no | optional comment |
| R5 | The merge is checked with the harness's `Parameters`, and previous-release nodes get the entries too | Info | CONFIRMED | no | doc sentence |

Known residuals not re-reported (bench 6 `plumbing-report.md` F2 and F3): a mistyped key in `TN_E2E_PARAMETERS` passes silently, and `test_epoch_observer_forwards_to_second_worker` bypasses the variable.
Neither is worse than stated; see 2g, questions 2 and 3.

## Findings

### R1. `start_nodes_with_overrides` leaks the nodes it already spawned (Low, CONFIRMED)

Where: `e2e-tests/tests/it/common.rs:1259-1262`.
The `?` on `node_overrides.apply_with_e2e_parameters(&dir)` sits inside the loop that spawns each node at `:1297`.
On that error the function returns and drops `children` (`:1257`).
Dropping a `std::process::Child` neither kills nor waits for the process.
Callers wrap the children in `ProcessGuard` only after an `Ok` (`eject.rs:223-225`, and the restart at `eject.rs:677-682`), and `ProcessGuard::drop` (`common.rs:275-279`) kills only what it holds.

Failure sequence:
1. A test gives node 3 alone a value the loader refuses: `FleetOverrides::default().parameter(["validator-4"], "max_header_delay", "soon")`.
2. Nodes 0 to 2 spawn; the apply for node 3 fails at `:1262` and the function returns `Err`.
3. The caller's `?` skips `ProcessGuard::new`, and three node processes keep running, holding ports and writing to `test_logs/` after the test has failed.

Reach today: narrow.
No test calls `start_nodes_with_overrides` yet.
`start_nodes` passes the default fleet (`:1235`), so every node gets the same fleet-wide entries and a bad `TN_E2E_PARAMETERS` value fails at node 0, before anything spawns.
A failure at node k > 0 needs a per-node override, or an I/O fault in one datadir.
The bench-7 e2e units that build mixed fleets on this helper are the ones who will reach it.
The `.expect` calls at `:1269`, `:1270` and `:1297` leak the same way on panic, but that was true on main.

Fix: apply every node's overrides in a first pass before spawning any, and drop the call at `:1262`:

```rust
for (v, _) in validators {
    fleet.node(v).apply_with_e2e_parameters(&temp_path.join(v))?;
}
```

### R2. A restart through a helper without overrides silently drops the node's own entries (Low, CONFIRMED)

Where: `e2e-tests/src/lib.rs:546-552` (no entries: `parameters.yaml.harness-base` is renamed back over `parameters.yaml`) and `lib.rs:511-515, 554-561` (fleet-wide entries only: the file is rebuilt from the base plus those).
The plain helpers apply empty node overrides: `start_validator` and `start_validator_with_args` reach `start_validator_with_env`, which builds env pairs only (`common.rs:539-543`); `start_named_observer` uses `NodeOverrides::default()` (`common.rs:772-774`); `start_nodes` passes the default fleet (`common.rs:1235`).
Nothing prints, logs or fails when a start removes entries an earlier start of the same datadir wrote.
The documentation (`lib.rs:427-432, 447-449`, `common.rs:553-555, 1245-1246`) and the unit test that pins the behaviour (`lib.rs:1201-1220`) are the only guard.

Failure sequence:
1. A test starts validator-2 with `start_validator_with_overrides` and a fleet that sets a switch on it.
2. Following the restart pattern every existing test in `restarts.rs` uses, it restarts validator-2 with `start_validator_with_args`.
3. The restart runs with the harness's file: the switch is off, the test checks the default path after the restart and passes.
   If the key changes what the chain computes, the restarted node forks from its peers instead, and the test fails somewhere far from the cause.

The verifier rated this Info because the behaviour is intended (bench 6 chose "rebuild per start") and documented.
I keep it at Low because it is the trap the scope asks about (2g, question 2): the safe call differs from the call every existing restart uses, and the failure is silent.

Fix (cheap, keeps the design): in `apply_parameters`, when `parameters.yaml.harness-base` exists and the file this start is about to write differs from the current `parameters.yaml`, print one line to stderr and to tracing naming the datadir and the entries before and after.
A no-override test never creates the base, so the line never fires there.
Once head 00 is in, a test that restarts a switched node should also assert the `node switches` line of the new run (2g, question 3).

### R3. `parameters.yaml.harness-base` is written with a non-atomic `fs::copy` (Info, CONFIRMED, unreachable)

Where: `e2e-tests/src/lib.rs:554-558`.
`parameters.yaml` itself is replaced only by `rename` from the same directory (`:548`, `:572`), after the staged file passed the node's own loader (`:565-571`).
A copy cut short (ENOSPC) leaves a truncated base that a later start of the same datadir would merge from.
That later start cannot happen: the copy error fails the start (`common.rs:544`, `:773-774`, or an `Err` from `start_nodes*`), and datadirs are per-test `TempDir`s that no later test reuses.
The harness's own first `parameters.yaml` is also written by `fs::copy` (`lib.rs:380`, `:412`, unchanged code), so this adds no new exposure.
Optional fix: copy to `parameters.yaml.harness-base.tmp` and `rename` it into place.

### R4. `db load-state` never sees `TN_E2E_PARAMETERS` (Info, CONFIRMED, no effect at M)

Where: `e2e-tests/tests/it/state_export_import.rs:306-316, 589-598, 1022-1031`.
Each runs `db load-state` on the observer's datadir before the observer's first start (`:343`, `:621`, `:1066`, through `start_observer` and `start_named_observer`), so it reads the harness's `parameters.yaml` without the lane's entries.
At M, `db load-state` loads the config (`telcoin-network-cli/src/db.rs:879-882`) but uses only `genesis()` (`:887`) and `chain_spec()` (`:941`), so nothing differs today.
`resync.rs:294-301` (`db reset-execution`) runs on a datadir a start has already merged, so it does read the lane's entries.
Optional fix: a comment at the load-state calls, so the topic that first makes `db load-state` read a `Parameters` field knows the lane does not reach it there.

### R5. The merge is checked with the harness's `Parameters`; previous-release nodes get the entries too (Info, CONFIRMED)

Where: `e2e-tests/src/lib.rs:565` checks the merged file with the e2e crate's own linked `tn_config::Parameters` (`lib.rs:39`), not the binary that will read it.
`upgrade.rs:253-254` and `:272-281` start previous-release binaries through `start_validator` and `start_named_observer`, and `reth_db_migration.rs:298` does the same, so they now merge `TN_E2E_PARAMETERS` too.
Neither the previous release (`ba7654d8a`, `make build-e2e-bin-prev`'s default) nor M has `deny_unknown_fields` on `Parameters` (checked with `git show`), so an old node ignores a new switch key.
A switch-on lane therefore runs these tests as a mixed fleet: old nodes without the switch, new nodes with it.
That is a useful mixed-fleet test, but it is not what the crate docs (`lib.rs:5-25`) lead a lane owner to expect.
Fix: one sentence in the crate docs naming these two tests and saying only the current loader checks the merge.

## Answers to 2a to 2g

### 2a. A test that passes no override starts its nodes exactly as on main

Yes, with `TN_E2E_PARAMETERS` unset.
The only line that runs and did not run before is one `exists()` check on `<datadir>/parameters.yaml.harness-base` per start (`lib.rs:546-547`), reached through `apply_with_e2e_parameters` (`lib.rs:505-514`).
The variable is read once per test process (`lib.rs:732-757`).
It prints nothing when it holds no entries (`lib.rs:745-753`).
Per start helper:
- `start_validator`, `start_validator_with_args`, `start_validator_with_env` (`common.rs:496-545`) now delegate to `start_validator_with_overrides` (`:560-601`). The arguments are unchanged. The env pairs reach `command.envs` in the same order, at the same point before `setup_log_dir` (`:596`).
- `start_named_observer` (`:761-800`) gains only the apply (`:772-774`).
- `start_nodes` (`:1229-1236`) delegates to `start_nodes_with_overrides` (`:1248-1306`). The added `command.envs(…)` (`:1293`) iterates an empty list, which is a no-op in `std`.
- `spawn_local_testnet` (`lib.rs:805`) gains only the apply.
No file is read or written; the `parameters.yaml` bytes, the arguments and the environment are main's.
New error paths (a `Result` from `start_validator_with_overrides` unwrapped with main's own `"failed to execute"` message at `common.rs:544`, a new `expect` at `:773-774`, a `?` at `:1262` and `lib.rs:805`) fire only on an I/O error around a base file that a no-override test never creates.
The moved log helpers (f70b56841) are byte-identical apart from `pub(crate)` and the import lists.

### 2b. Mixed fleet

Not applicable: test code; no message, header, vote, certificate or batch is touched.
The scaffold lets a test build a mixed fleet on purpose (`FleetOverrides`, `lib.rs:578-659`), and its docs warn that a chain-affecting key given to some nodes forks the test fleet (`lib.rs:443-449`).
A switch-on lane also turns `upgrade.rs` and `reth_db_migration.rs` into mixed fleets (R5).

### 2c. Liveness

Not applicable: test code.
On the harness side, R1 is the only new path that leaves work behind (leaked node processes).

### 2d. Byzantine or slow peers

Not applicable: test code parses no peer input.
`TN_E2E_PARAMETERS` is local operator input, checked by `parse_e2e_parameters` (`lib.rs:771-790`) and by the node's loader before the move (`lib.rs:565-571`).

### 2e. Restart and epoch boundary

The new state is on disk: `parameters.yaml.harness-base` in each datadir from the first start with entries until a start without any.
A `parameters.yaml.merging` file stays after a refused merge.
There is also one process-wide `OnceLock` for the variable (`lib.rs:734`).
Across a node restart the base is what makes a restart rebuild from the harness's file (R2 is the consequence).
Node crashes cannot interleave with these writes: the harness writes synchronously in the test process before it spawns the node, and the node only reads `parameters.yaml` (`config/src/node.rs:89-97`).
Epoch boundaries: nothing.

### 2f. Determinism

Not applicable: test code feeds nothing into consensus-visible data.
`FleetOverrides` is a `BTreeMap` (`lib.rs:609`), and the merge is a pure, idempotent text function (`lib.rs:675-701`, pinned at `:1133-1139`).

### 2g. The scope's own questions

1. Same as 2a: yes, with one extra `stat` per start.

2. Half-written `parameters.yaml`: no.
   The file is replaced only by `rename` from the same directory, after the staged file passed the node's loader (`lib.rs:548`, `:565-572`).
   `parameters.yaml.harness-base` is written non-atomically, but no later start can read a cut-short copy (R3).
   A restart helper without overrides does silently drop a previous override (R2).
   The documentation is accurate and appears in four places.
   It is still a trap: every existing restart in `restarts.rs` uses the plain helpers, so a test copied from one loses its switch at the restart with no message.
   The cheap guard is the stderr line in R2's fix, plus a `node switches` assertion after any restart of a switched node.

3. `TN_E2E_PARAMETERS` reach.
   Node starts it does not reach: only `epochs.rs:856-877` (`test_epoch_observer_forwards_to_second_worker`, four validators and an observer spawned with `bin.command()`), the known residual.
   The unit's other two "places" are not node starts.
   One is the `db` subcommands: `resync.rs:294-301` reads the merged file and `state_export_import.rs` load-state reads the unmerged one (R4).
   The other is `upgrade.rs:212`, a `--version` call.
   Every other node start in `tests/it/*.rs` goes through a helper that applies the variable.
   That covers clock_skew, basefee, metrics, forward_txs, rpc_namespaces, sync, sigkill, restarts, eject, epochs (except the one test above), governance_safe_fork, resync, state_export_import, upgrade and reth_db_migration, plus the in-process faucet and genesis tests via `spawn_local_testnet`.
   It also reaches previous-release nodes (R5).
   A mistyped key passes silently: yes, as bench 6's F2 says; not worse than stated.
   The same holds for a key that belongs in another file.
   Cheap guards, in order of cost:
   - After head 00 lands, a `common.rs` helper, run once per node after its start. For each `e2e_parameters()` entry it calls `wait_for_node_log_line(test, instance, run, "node switches", &[format!("{key}={value}")], timeout)`. The moved helpers already match whole `key=value` tokens. It covers switch keys only (the line lists only switches), and the lane must write the value in the line's form (`150ms`, `true`, `4`).
   - At parse time, `e2e_parameters()` refuses a key that is neither a key of the serialized `Parameters::default()` nor a name in head 00's `Parameters::default().switches()` (`config/src/node.rs:605` in `tn-b7-pt0`), or that the `FieldNames` probe bench 6 named does not list. This fails a typo before any node starts. It needs head 00 underneath, so it belongs in a later head, not this PR on M. The tests' own `NodeOverrides` should stay permissive.

4. Moved log helpers: no filter selects a test by its old module path.
   The only moved test is `test_log_field_reads_whole_fields`, now `common::` instead of `restarts::`.
   `Makefile:397` and `:601` filter on the substring `test_restarts`, which matched neither name.
   The other Makefile filters are `faucet::` (`:199`), `test(sigkill::)` (`:401-403`), `test_epoch` (`:409`, `:600`), `test_upgrade` (`:424`), `test_governance_safe_fork` (`:478`), `reth_db_migration::` (`:491`) and `resync::` (`:511`).
   `.config/nextest.toml` filters by package or `test(sigkill::)`.
   `.github/workflows/durable-e2e.yaml` runs `make test-restarts`.
   The test is a plain `#[test]`, so every unfiltered nextest run of the package still runs it, as before.

5. Fixed ports and parallelism: nothing makes two tests more likely to collide.
   The port picks are unchanged (`common.rs:574`, `:1269-1270`, `lib.rs:806-810`).
   The apply runs before the pick, so the pick-to-bind window is unchanged.
   The new files live in each test's own datadir.
   The `OnceLock` is per process, nextest runs one process per test, and the `e2e` group is `max-threads = 1` (`.config/nextest.toml`).
   The new unit tests in `lib.rs` use their own `TempDir`s and never read the variable, so a lane with it set does not change them.
   Only R1's leaked nodes would hold ports past their test.

## What I did not examine

- The security evaluation (the scope says no).
- No `cargo` was run. The unit's gates (fmt, clippy, check, 14 lib tests and the doctest, two e2e tests on lane 2) are taken as reported in `tasks/checkpoint-bench7-PT-1.md`.
- Head 00's `node switches` rendering beyond its API note (`tasks/bench7/briefs/pt0-api.md`); R-00 reviews it.
- Other topics' tests that will use these helpers.
- Whether the previous release reads any key the lane might set with a different type: only its lack of `deny_unknown_fields` was checked.
