# Code review: bench-6 plumbing (switches, obs, e2e scaffold, pipelined-persist plumbing)

Date: 2026-11-11
Scope: `telcoin-network-b6`, branch `bench/bench6-2026-11`, head d91d65d3e. The diff is `git show --format=` of the 15 commits in
`plumbing.scope.md` (bfc5611ab 3696d49f3 8ab9e89e4 5b9f13b25 38b65ff7b 4c7e5f032 d1b6b0ac3 b09d65945 9c91263e7 d789015b0 8d363e368
acd609838 082179d4d c8e5ae7be d91d65d3e). Code review only (`tn-review`). The scope waives the security evaluation, and nothing in
the review called for one: no line in this diff reaches a header, vote, certificate, batch or block, and none parses peer input.
Line numbers are at HEAD unless a commit is named.

## Verdict: APPROVE WITH FOLLOW-UPS

With every switch at its default, nothing here changes node behaviour. A genesis ceremony writes the same 14 keys to
`parameters.yaml` as before. The serde attributes and guard tests are correct and complete. The one finding that matters for the
benchmark (F1) applies only if pipelined persist is cut from the image: the key stays known to the node but does nothing, so the
harness's guard for optional switches cannot catch an arm that turns it on.

| # | Title | Severity | Status | Before image | Before upstream |
|---|-------|----------|--------|--------------|-----------------|
| F1 | `pipelined_persist` is known to every image from this branch but inert without the held stack, so a cut image defeats the optional-switch guard | Medium | CONFIRMED | yes, if the pipeline is cut | yes |
| F2 | `TN_E2E_PARAMETERS` accepts a mistyped key, so a switch-on e2e lane can silently run as a second control lane | Low | CONFIRMED | yes, if a lane result gates the image | no |
| F3 | `test_epoch_observer_forwards_to_second_worker` spawns its nodes directly and never gets `TN_E2E_PARAMETERS` | Low | CONFIRMED | no | no |
| F4 | `Parameters` ignores unknown keys without a warning (pre-existing; now pinned by a test) | Low | CONFIRMED | no | suggested |
| I1 | `tn_primary_digest_wait_seconds` changed meaning without a rename | Info | CONFIRMED | no | note in PR |
| I2 | `persister.rs` (empty `pub mod`) and `OutputBuildScope::seeded` have no caller on this branch | Info | CONFIRMED | no | land with consumer |
| I3 | A digest riding two tracked headers shares one first-receipt stamp, so its re-queue can under-report the wait | Info | CONFIRMED | no | no |

Verification: the skill's `findings-verifier` step needs an agent-spawning tool, and this session had none. I checked each finding
against the code a second time, re-reading the cited lines and every caller and reader found by grep, before I listed it.

## Findings

### F1. `pipelined_persist` is known to every image from this branch but inert without the held stack (Medium, CONFIRMED)
- Where: `crates/config/src/node.rs:460-461` (field), `:747` (listed by `switches()`, so on the `node switches` line and the
  `tn_node_switch` gauge); `crates/node/src/engine/inner.rs:572` (handed to the engine); `crates/engine/src/lib.rs:128,:210-218`
  (stored, and read only by its getter: no branch anywhere in production code reads it, by grep); `crates/engine/src/persister.rs:1-7`
  (empty; its own doc says "the engine always builds, persists and commits one output before it starts the next").
- Why it matters here: `benchmark/arms/README.md:51` makes `pipelined_persist` the one optional switch "because it is cut from the
  image unless its go/no-go tests pass", and `:109-112` says the only protection against an arm that sets it on an image without it
  is that the `node switches` line does not print the key. Decision D7 (`tasks/bench6-g1-notes.md:96-97`) says a failed gate means
  "the image ships without the key". D77 lists the image-cut checks and has no step that removes the key. These plumbing commits put
  the key on the integration branch, and the pipeline lives on the held stack `b6/pipe-stack-2`.
- Failure sequence: gate 5 or 6 stays open at the cut, so the image is built from `bench/bench6-2026-11` without the held stack. An
  arm file says `param pipelined_persist true`. The parser accepts it, because the key is in `switches.tsv`. `params-apply.sh` writes
  the key and restarts the nodes. Each node logs `pipelined_persist=true` and exports `tn_node_switch{name="pipelined_persist"} 1`,
  so the readback matches the arm's state. The engine runs the sequential loop. The arm's numbers are a second control run, labelled
  as pipelined persist.
- Fix (either one):
  1. Make the image's knowledge of the key match the implementation. Move 8ab9e89e4 (field, `switches()` entry, parse test),
     d789015b0 (engine setter and `configure_engine` line) and 8d363e368 (empty module) onto the held stack, so cutting the stack
     removes the key. The tests that name the field move with them: `node/src/manager/node.rs` switch-line test,
     `node/src/metrics.rs:test_node_switch_gauge_per_switch`, and `config` `pipelined_persist_parses`. Also update the expected line in
     the contract and `u0c-api.md`.
  2. Or keep the key and require live proof of it, the way sealed-keep uses `keeps_sealed=true`. The contract already plans an
     `output executed ... pipelined` field (row 48; on the held stack only `pipelined=true` lines carry it, per
     `checkpoint-bench6-u12a.md` deviation 3). Have the arm tool require that field on every node before it counts an arm with
     `pipelined_persist true` as ready.
  Option 1 is the simpler fix, and it matches what D7 already says.
- Not a duplicate of the known residual ("until each fix lands, the switch line and gauges report switches that do nothing yet",
  `u0c-api.md:49`). For the eleven required switches, that residual closes once every topic is integrated before the cut. For this
  switch, being cut is a planned outcome, and the harness's only defence against it is the key being absent, which these commits
  remove.

### F2. `TN_E2E_PARAMETERS` accepts a mistyped key (Low, CONFIRMED)
- Where: `crates/e2e-tests/src/lib.rs:759-779` (`parse_e2e_parameters` checks only the key's characters) and `:536-580`
  (`apply_parameters` checks that the merged file loads as `Parameters`, which ignores unknown keys; see F4). The crate doc at
  `lib.rs:19-25` tells the reader to check the `node switches` line, but nothing in the lane does.
- Failure sequence: `TN_E2E_PARAMETERS='pipelined_persit: true' cargo nextest run ...`. Every node starts with the typo in its file
  and runs at defaults. The restarts, epochs and sigkill sets pass, and the "switch on" gate named in d91d65d3e's message passes
  without testing the switch.
- Fix: in `e2e_parameters()`, refuse a key that is not a `Parameters` field. The field list is already obtainable, either with the
  `FieldNames` deserializer probe from `config/src/node.rs:1253-1280` (move it out of `#[cfg(test)]` behind `test-utils`) or as
  `Parameters::default().switches()` names plus the serialized default keys. Keep per-test `NodeOverrides` permissive, since the doc
  says tests may name keys an older binary does not know. Until then, grep each lane's `test_logs` for the `node switches` line
  with the intended values before counting the lane.

### F3. One epochs test bypasses `TN_E2E_PARAMETERS` (Low, CONFIRMED)
- Where: `crates/e2e-tests/tests/it/epochs.rs:819` (`test_epoch_observer_forwards_to_second_worker`). It builds its datadirs with
  `config_local_testnet_with_worker_fee_configs` (`:827`), then spawns four validators and an observer with `bin.command()`
  (`:864-877`), not through a start helper.
- Effect: under a switch-on lane this test runs every node at defaults. That matches the commit message's wording ("every node a
  start helper starts") but not its purpose (the epochs set must pass with each switch on).
- Fix: call `NodeOverrides::default().apply_with_e2e_parameters(&temp_dir.path().join(&name))?` before `bin.command()` at `:864`.
  The other `bin.command()` sites, `state_export_import.rs:310,591,1024` and `upgrade.rs:206`, are one-shot `db load-state` /
  `--version` runs and do not start a node.

### F4. Unknown keys in `parameters.yaml` are ignored without a warning (Low, CONFIRMED, pre-existing)
- Where: `crates/config/src/node.rs:211-212` (`#[derive(Deserialize)]` with no `#[serde(deny_unknown_fields)]`), loaded by
  `crates/config/src/traits.rs:47` (`serde_yaml::from_str`), from `Config::load` at `node.rs:92-93`. The new test
  `unknown_keys_are_ignored` (`node.rs:1408-1411`) pins this behaviour on purpose, and the doc at `:720-723` says the switch line
  exists because of it.
- This is not a regression, and the benchmark's arm tool covers it (see 2g). For an operator outside the harness, though, a typo in
  any key (`max_header_dela: 300ms`, `vote_queue_fx: true`) runs the default, and nothing in the node's own log says so.
- Suggestion for upstream: warn once at load for each top-level key the struct does not know. One way is to read the file into a
  `serde_yaml::Mapping` and compare its keys with the field list; another is the `serde_ignored` crate. Do not reject such keys:
  that would break a rollback to an older binary over a newer file.

### I1. `tn_primary_digest_wait_seconds` changed meaning without a rename (Info)
`crates/consensus/primary/src/proposer.rs:462-464` now samples from a digest's first receipt instead of its last queueing. The
change is intended and documented (`metrics.rs:98-103`, contract row 47). Bench-5 and bench-6 values of this histogram are not like
for like for headers carrying re-queued digests. Say so in the upstream PR text and in any cross-run comparison.

### I2. Code with no caller on this branch (Info)
`crates/engine/src/persister.rs` is an empty `pub mod`. `OutputBuildScope::seeded` (`crates/tn-reth/src/env/execution.rs:738`) is
called only by its own test (`:1251`). Both are harmless here. Upstream, they should land in the same PR as their consumer. Fix 1 of
F1 does this.

### I3. Duplicate digests share one stamp in `proposed_first_received` (Info)
With `digest_dedupe` off (the default), a digest reported twice can ride two tracked headers. `drain_digests_for_header`
(`proposer.rs:1120-1125`) keeps one stamp per digest, keyed by digest. The first commit (`:916-920`) or re-queue (`:1622`) of either
header removes it. A later re-queue of the other header then falls back to `requeued_at`, so the wait is under-reported in exactly
that case. This affects the metric and log line only, and nothing leaks. Every inserted stamp leaves on commit or re-queue: a failed
proposal ends `run()` at `:1449`, and the proposer is rebuilt each epoch (`primary.rs:109`). No change needed. Worth a sentence in
the field's doc.

## Answers to the brief's questions

### 2a. Switch off = before
Yes, for this group. These lines run with every switch at its default and did not run before. All of them are logging, metrics or
data no other code reads:
- `crates/node/src/manager/node.rs:763` calls `announce_switches` (`:2075`), which logs one info line on target `node::switches` and
  sets 12 `tn_node_switch` gauges (`crates/node/src/metrics.rs:63-67`). The recorder is installed before `launch_node`
  (`telcoin-network-cli/src/node.rs:229-231`), so the gauges are not lost on a node run with `--metrics`.
- `crates/consensus/primary/src/proposer.rs`, not behind a switch (c8e5ae7be):
  - one `Instant::now()` and two `min` passes over the header's digests (`:456-472`);
  - the histogram sample now taken from the first receipt (`:462-464`);
  - the new log field `oldest_requeue_wait_ms` (`:486`);
  - one `BTreeMap` insert per drained digest (`:1120-1125`) and removes on commit (`:916-920`) and re-queue (`:1622`).
  The header payload is still `(m.digest, m.worker_id)` (`:446`). `first_received` is read nowhere except `:462` and `:470`, and the
  order of the digest queues is unchanged.
- `crates/tn-metrics/src/recorder.rs:176-193`: four `Matcher::Full` bucket layouts for the engine stage histograms. This changes
  exposition only. `SUB_MS_SECONDS_BUCKETS` keeps every bound of `SECONDS_BUCKETS`, and the execution and persist durations keep the
  old layout (the test checks both).
- `crates/node/src/engine/inner.rs:572` writes `pipelined_persist = false` into an engine field that nothing reads (F1).
- `crates/config/src/node.rs:326-461`: `skip_serializing_if = "is_default"` affects only how the struct is written. With defaults,
  the ceremony (`telcoin-network-cli/src/genesis/mod.rs:315-336`, `Parameters::default()` plus four non-switch overrides and
  `basefee_address`) writes the same 14 keys and values as on main. I checked the pre-switch field list at `3696d49f3^` against
  `NON_SWITCH_KEYS` (`node.rs:1202-1217`).
- `OutputBuildScope::seeded`, `persister.rs` and the e2e code never run in a node.

### 2b. Mixed fleet
Nothing in this group changes a message or any state another validator checks. `Parameters` is only ever read from YAML and written
as YAML (`traits.rs:47,109`; ceremony `genesis/mod.rs:336`). No code binary-encodes it, hashes it or sends it, by grep. That also
means `skip_serializing_if` cannot break a bincode or bcs round trip. The proposer change never reaches the header (`:446`). The
switch line and gauge are local. Each switch's own effects on a mixed fleet are reviewed with its topic.

### 2c. Liveness
Nothing here can drop or delay work that used to make progress. The proposer's new map is written and read only for metrics, and
nothing waits on it. With the switch default, `configure_engine` changes nothing in the engine loop.

### 2d. Byzantine or slow peers
No new exposure. `proposed_first_received` is filled only from this node's own workers' digests (`OurDigestMessage::process`, `:70-81`). Its
size is bounded by the payloads of the own headers already tracked in `proposed_headers`, at most `max_header_num_of_batches` entries
per header at about 48 bytes each. That is the same bound that already applies to `proposed_headers`, and a peer cannot grow it.

### 2e. Restart and epoch boundary
`proposed_first_received` lives in the proposer, which is rebuilt each epoch (`primary.rs:109`), so the map drops at the boundary
and on restart. A header re-proposed from the store after a restart has no stamps, and its re-queue falls back to `requeued_at`, as
documented at `:1608-1610`. The switch line and gauges are set once per process in `EpochManager::new`. A restart sets them again;
an epoch change does not touch them, which is correct because a switch changes only at restart.

### 2f. Determinism
None. `Instant::now()` in the proposer feeds only the log line and the histogram. The header's `created_at` still comes from
`now_ms()` (`:437`), as before. `BTreeMap` order is never observed.

### 2g. The scope's questions
1. A switch at its default is not written. All 12 switch fields carry `#[serde(default, skip_serializing_if = "is_default")]`
   (`node.rs:326, 338, 349, 360, 371, 383, 392, 403, 415, 437` with `humantime_serde`, `450, 460`). `is_default` (`:794`) compares
   with `T::default()`, which equals both the serde default and the struct's `Default` values (`:563-574`). The guard tests close
   every hole I could find:
   - `switches_list_every_switch_field` (`:1284-1312`) gets the struct's real field list from a deserializer probe, so a field that
     is never serialized cannot hide from it. It fails if a field is in neither `switches()` nor `NON_SWITCH_KEYS`, and it asserts
     that `Parameters::default()` writes exactly `NON_SWITCH_KEYS`. So a new switch that forgets the `skip` attribute fails.
   - `switch_values_render_as_their_yaml` (`:1317-1335`) asserts each default switch is absent and that its rendered value parses
     back to the default.
   - `reserializing_keeps_the_existing_keys` (`:1375-1404`) runs a bench-5 file and the mainnet and adiri presets.
   - `chain_presets_leave_every_switch_at_its_default` (`:1415-1425`) checks that no preset names a switch.
   I found no gap.
2. An unknown or mistyped key is silently ignored by the node. `Parameters` (`node.rs:211-212`) has no `deny_unknown_fields`, and
   `ConfigTrait::load_from_path` (`traits.rs:47`) returns `serde_yaml::from_str(&cfg_string)` with no unknown-key check. Nothing is
   logged, and the test at `:1408-1411` pins this. A key with the right name but a wrong type does fail the start: for example
   `parent_grace: 150` without a unit, `recovery_threads: -1`, or `quorum_exec_block: yes` (a string in YAML 1.2). For the
   benchmark, the arm tool closes the gap. Its parser refuses an unknown `param` key (`benchmark/arms/README.md:85,92`), and after
   every restart it reads the `node switches` line back and compares it with the arm's full state (`:110`), so a misspelled switch
   cannot run as a control arm unnoticed. Two holes remain: F1, where a cut image still knows `pipelined_persist`, and F2, the e2e
   lane, which has no readback.

## The e2e scaffold (`crates/e2e-tests/src/lib.rs`, `tests/it/common.rs`)
- What each node gets: the harness's own `parameters.yaml`, kept the first time as `parameters.yaml.harness-base`. Then
  `TN_E2E_PARAMETERS` entries, then the test's `NodeOverrides` entries, merged in that order with the last entry for a key winning.
  The file is staged as `.merging`, loaded through the node's own loader, then moved into place. This holds:
  - `layered_over` (`lib.rs:481-484`) puts the fleet-wide entries first;
  - `merge_parameters_yaml` (`:668-696`) removes an existing top-level entry, including its block value, before appending, so the
    merge is idempotent;
  - the tests at `:1059-1328` cover replacing a key, replacing a whole block, matching whole keys only, the later entry winning,
    rejected keys and values, layering, and a failed merge leaving the file untouched.
- Per-node overrides are keyed by datadir name (b09d65945). A restart of a subset therefore finds the same nodes' overrides. Every
  start rebuilds the file from the harness copy, so an earlier start's entries do not survive, and a start with no entries restores
  the harness file.
- Every helper that starts a node applies the overrides first: `start_validator*` through `start_validator_with_overrides`
  (`common.rs:502-515`), `start_named_observer` (`:711-716`), `start_nodes_with_overrides` (`:1200-1203`) and `spawn_local_testnet`
  (`lib.rs:793`). The one node-spawning site outside them is F3.
- Env overrides are set after `TestBinary::command`'s forwarded variables (`common.rs:538`), so a per-node value wins and never leaks
  into the harness process.
- No test writes `parameters.yaml` between starts (grep), so the `.harness-base` copy cannot go stale.
- 4c7e5f032 moves code without changing it. d1b6b0ac3 adds doc-only modules. Style is consistent with the crate.

## What I did not examine
- The security evaluation (`tn-security-eval`), which the scope waives.
- Each switch's behaviour behind its plumbing. Those are other topics' commits and reports.
- The held `b6/pipe-stack-2` code beyond confirming that the pipeline is not on this branch.
- The other bench-6 e2e tests that use this scaffold (`exec_block.rs`, `sealed_txs.rs`, `persist_pipeline.rs` at HEAD), beyond
  the grep for direct writes to `parameters.yaml`.
- Whether the bench node's log filter keeps `node::switches` at info. The harness readback fails closed if the line is missing,
  and H15 covers the prefilter.
- I compiled and ran nothing (no cargo, by the brief), so the tests' pass status comes from their code, not from a run.
