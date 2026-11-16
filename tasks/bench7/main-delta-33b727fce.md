# Bench 7: what main's three new commits mean for the stack, its PR texts and the harness

Read-only delta read, 2026-11-15.
M = `45dce89474e1efc7f90c6fbd1e51332cc237ab9b` (the stack's base), N = `33b727fcea4f6004d4b0cd2bd7923258e081e94f` (upstream `main` now).
Repository read: `/home/drtnarg/coding/telcoin/tn-b7-p2` (git object reads only; no build, no test run).
`M..N` is three commits, M is an ancestor of N: `bc571cb8c` (#1848), `d4d53c115` (#1849), `33b727fce` (#1855).
Heads (each contains the one before; commits above M): 00 `81a06c4e1` (12), 01 `48dae6a5f` (20), 02 `ad83a72f3` (30), 03 `cd52dcd81` (33), 04 `ca258b37c` (61), xf `38a8012f5` (70), 05 `b608a9eb8` (88), 06 `fac7a05fb` (105).

Evidence tags: [code] read from code at the named revision, [PR] stated by a PR or issue text, [inferred] my conclusion from the code, [merge-tree] the output of `git merge-tree --write-tree <head> N`.
"merged head NN" means the tree `git merge-tree --write-tree <head NN> N` writes, conflict markers included; its line numbers are cited as `merged-03:<path>:<line>`.

## Findings first

- The bench 7 image (the stack on M) runs M's code wherever N fixed something; nothing in N shows the stack itself misbehaving on a fleet.
  Two of N's fixes are on paths a fleet can reach and the image lacks [PR #1849; code]: an unexpected `preadv2(RWF_NOWAIT)` error fails a tn-lmdb commit on M (`crates/tn-lmdb/src/file.rs:578` M) where N turns gap fill off (`:131` N), and a latched database is retried by the engine's persist on M where N stops at once; and an observer or non-committee node holding its own record that conflicts with a certified one runs on (logged only) on M and with every head-04 switch off, where N stops it.
  The stack does not touch `crates/tn-lmdb*` [code: `git diff --stat M fac7a05fb`].
- PR text 04 is false of today's main in three places: "as on main" (line 37), the pre-flight (line 38) and line 79 (section 2); its line 14 is true of M only.
  Issue #1850's G2 is fixed on main by #1849 (section 3).
- An auto-merge of N into head 03 or above does not compile: N's new record-0 call uses `check_stored_record`'s M signature, which head 03 changed (`merged-03:crates/node/src/manager/node/close_epoch.rs:458`).
- After the merge, head 04's `epoch_record_conflict_halt` has no effect: every validated conflict stops the node through N's `stop_on_local_failure`, right after the stack's line saying the node keeps its own record.
  Recommended: keep head 04's evidence line and counters in front of main's stop, drop the switch and the threshold (section 2, option 2).

## 1. What N changed that the stack touches or calls

The stack (`git diff M fac7a05fb`, 41 files) shares five files with `M..N`: `crates/config/src/node.rs` and `crates/node/src/manager/node.rs` (#1848), `crates/node/src/manager/node/close_epoch.rs`, `crates/state-sync/src/epoch.rs` and `crates/node/src/metrics.rs` (#1849), `crates/node/src/manager/node.rs` again (#1855), plus two READMEs (`crates/telcoin-network-cli/README.md`, `crates/tn-reth/README.md`) [code].
The stack does not change `start_epoch.rs`, `crates/config/src/network.rs`, `crates/storage/src/consensus.rs` or `consensus_pack.rs`; it calls them unchanged [code].

### #1848 `bc571cb8c` feat(config): bundled bootstrap servers per named chain

- `crates/config/src/node.rs:53` (N): new field `Config::bootstrap_servers: Option<BTreeMap<BlsPublicKey, BootstrapServer>>`, `#[serde(skip)]`; set only by `Config::load_adiri` (`:137`) and `Config::load_mainnet` (`:166`) from the compiled-in `chain-configs/*/bootstrap_servers.yaml`; `None` from `load_or_default` and the datadir loaders [code].
  The stack builds no `Config { .. }` literal outside this file (`git grep exex_critical fac7a05fb`), so the new field breaks no stack code [code].
  `Parameters` is untouched by #1848 (its hunks are at `:3`, `:42`..`:145`, `:577` and the end of `mod test`; the stack's are at `:254`..`:562` of `Parameters` and the end of `mod test`) [code], so the stack's `switches_list_every_switch_field` test keeps its field list.
- `crates/config/src/node.rs:194` (N): new `Config::default_bootstrap_servers(&Committee)`: the built-in list, else `genesis_committee.bootstrap_servers()` [code].
- `crates/config/src/node.rs:637` (N): new `parse_bootstrap_servers(chain, yaml)` [code].
- `crates/config/src/node.rs` `mod test` (N `:1061`..): three new tests at the end of the module, `bundled_bootstrap_servers_are_dialable`, `count_entries_sees_repeated_keys`, `named_chain_configs_carry_bundled_bootstrap_servers`, `default_bootstrap_servers_prefer_the_built_in_list` [code]; the stack appends its `// ---- bench6 bench6-switches ----` tests at the same place, hence the one textual conflict (section 2).
- `crates/config/src/network.rs:102` (N): new `BootstrapSource` enum (`Cli`, `NetworkConfig`, `Bundled`, `GenesisCommittee`, displayed `command line`, `network-config`, `built-in chain list`, `genesis committee file`); `:415` `resolve_bootstrap_peers` renames its parameter `genesis` to `chain_default`, same logic; `:431` new `bootstrap_source(cli_override, bundled)` [code].
- `crates/node/src/manager/node.rs:788` (N): `EpochManager::new` takes `builder.tn_config.default_bootstrap_servers(&committee_zero)` instead of `committee_zero.bootstrap_servers()`, and logs at `info` (target `epoch-manager`) when the committee file lists other servers than the built-in list [code].
  The stack's own change in `EpochManager::new` (the `parameters.log_switches()` / `record_node_switches` lines, head 00) sits a few lines above, at M `:770`, and auto-merges [merge-tree].
- `crates/node/src/manager/node.rs:1057`..`:1067` (N): new startup log `bootstrap peers selected` with `servers` and `source` [code]; `:1094`..`:1105` new `warn` `no bootstrap peers, committee peers or trusted nodes are configured, ...` when all three are empty [code].
- `chain-configs/mainnet/committee.yaml` and `testnet/committee.yaml`: `bootstrap_servers` maps emptied; the lists moved to `bootstrap_servers.yaml` (`crates/types/src/genesis.rs:144`, `:152` N: `TESTNET_BOOTSTRAP_SERVERS`, `MAINNET_BOOTSTRAP_SERVERS`) [code].
  Tests that read servers out of `MAINNET_COMMITTEE` were moved to `tn_types::test_utils::bootstrap_servers_fixture()` [code]; the stack's diff never names `MAINNET_COMMITTEE`, `TESTNET_COMMITTEE` or `bootstrap_servers()` (`git diff M fac7a05fb | grep`) [code].

### #1849 `d4d53c115` storage v2 follow-ups (the parts the stack touches)

- `crates/state-sync/src/epoch.rs:215` (N): new `const FINAL_STATE_MISMATCHES: &str = "tn_epoch.final_state_mismatches_total"` [code].
- `crates/state-sync/src/epoch.rs:228`..`:245` (N): `stop_on_local_failure` now returns an error for `EpochDbError::ConflictingRecord { .. }` (it returned `Ok(())` at M), after counting `tn_epoch.final_state_mismatches_total` and logging at `error` (target `epoch-manager`, fields `epoch`, `e`) `a certified epoch record from peers conflicts with this node's own record for the epoch: this node's execution diverged from the certified chain, stopping the node`; the error text starts `epoch {epoch}: a quorum certified an epoch record other than the one this node built from its own execution` [code].
  Every other refusal (`CertificateMismatch` and the rest) is still logged and asked again [code: the N test `test_only_local_store_failures_and_conflicts_stop_collection`].
- `crates/state-sync/src/epoch.rs` tests (N `:674`, `:823`): `test_collect_epoch_records_keeps_going_past_a_refused_record` renamed `test_collect_epoch_records_stops_on_a_record_conflicting_with_our_own` and inverted; `test_only_local_store_failures_stop_collection` renamed `test_only_local_store_failures_and_conflicts_stop_collection` and inverted for the conflict, with a `DebuggingRecorder` assert on the counter [code].
- `crates/node/src/metrics.rs:26` (N): doc only; `final_state_mismatches_total` now also covers the collector's count [code].
- `crates/node/src/manager/node/close_epoch.rs:430`..`:433` (N): new arm in `write_epoch_record`: an uncertified record 0 whose `final_state` is not `BlockNumHash::default()` (this node's own record 0, not the dummy) goes through `self.check_stored_record(&epoch_rec, false, parent_state, engine).await?` and is then built again [code].
- `crates/node/src/manager/node/close_epoch.rs:1280` (N): `check_stored_final_state` skips on `local.number < *floor` (M: `<=`); the floor block itself is now compared [code].
  `:734` the skip's debug text is now `stored epoch record not compared: its closing block is below this datadir's restored-state floor, so this node holds only a scaffolded header for it` [code].
- `crates/node/src/manager/node/close_epoch.rs` tests (N `:2215`..): new `replay_guard_stops_on_an_uncertified_epoch0_record_that_does_not_match`; `replay_guard_skips_a_closing_block_this_node_restored` rewritten as `replay_guard_skips_only_closing_blocks_below_the_restored_floor` (closing block at the floor is compared, one below is skipped, a matching one at the floor succeeds) [code].
- `crates/telcoin-network-cli/src/node.rs:398` (N): the node refuses to open its execution database when a `load-state-in-progress` marker is in the datadir (`crate::db::refuse_interrupted_load_state`, `src/db/load_state_marker.rs:92`) [code].
- Outside the stack's files: tn-lmdb and tn-lmdb-reth hardening (`boot_record.rs`, `file.rs`, `timeout.rs`, `tx.rs`), `db reset-execution` and the new `db load-state` marker, `exec_cache.rs`, `output_overlay/parallel.rs`, `rpc_blocking.rs`, `tn-reth/src/metrics.rs` (+76) [code: file list]; section 5 reads what of it changes per-block writes.

### #1855 `33b727fce` store each transaction once (new datadirs)

- `crates/node/src/manager/node.rs:1884` (N): `create_engine` calls `reth_env.attach_tx_packs(&self.consensus_chain, self.tn_datadir.epochs_db_path())?` before the engine and RPC start; the doc at `:1861`..`:1865` says a datadir that stores transactions by their position in the packs refuses to start when a pack its rows can point into is missing [code]; `RethEnv::attach_tx_packs` is `crates/tn-reth/src/env/mod.rs:321` (N).
- `crates/node/src/manager/node/start_epoch.rs:151`..`:160` (N): `replay_missed_consensus` calls `self.consensus_chain.persist_current().await?` before the first replayed output is sent, when anything is missing (one extra pack persist per restart replay) [code].
- `crates/storage/src/consensus.rs:2109` `ConsensusChain::live_batch`, `:2136` `live_batches`, `:2524` `struct LiveBatches`; `crates/storage/src/consensus_pack.rs:1579` `ConsensusPack::batch_now`, `:1732` `struct PackReader`, `:6812` `enum BatchReadError` (N): additions for the execution side's reads of transactions out of the packs [code].
  The one changed existing function is `Inner::batch` (`consensus_pack.rs:5448`..`:5503` N), now a wrapper over the new `batch_checked`; same `Option<Batch>` contract, same three log texts (`batch loaded from the pack does not hash to its indexed digest (a stale index entry)` kept at `warn`; the two `error` texts folded into `indexed batch could not be served from the pack: {e}`) [code].
  `ConsensusChain::heal_static` (`consensus.rs:2477`..) is a pure refactor into `read_side_heal()` [code].
- The stack calls none of the new storage items and changes no storage file [code: `git diff M fac7a05fb` names no `crates/storage/` file].

## 2. Per head, what a bring-forward onto N needs

The orchestrator's merge-tree result holds [merge-tree, re-run for all eight heads]: `crates/config/src/node.rs` conflicts from head 00 on, `crates/state-sync/src/epoch.rs` from head 04 on; `close_epoch.rs`, `node/src/manager/node.rs`, `node/src/metrics.rs`, both READMEs auto-merge.
An auto-merge is not a clean merge here: merged head 03 does not compile (below), and heads 03 and 04 carry tests that N's behaviour fails.

| head | textual conflicts | semantic overlap with N | what must change | head tests that would need to change |
|---|---|---|---|---|
| 00 `feat/bench6-switches-obs` | `crates/config/src/node.rs`: 1 hunk (merged-00 `:1208`..`:1751`); both sides append tests at the end of `mod test`; mechanical (keep both, the stack's block under its `// ---- bench6 bench6-switches ----` marker) | #1848's `Config::bootstrap_servers` is on `Config`, not `Parameters`, so the switch list and `switches_list_every_switch_field` are untouched [code]; #1848 adds two startup lines on target `epoch-manager` beside the `node switches` line (section 4) | nothing beyond the hunk | none known [inferred; `cargo nextest -p tn-config` on the merge is the check] |
| 01 `test/bench6-e2e-scaffold` | as 00 (inherited) | none in code: N's e2e edits are in `tests/it/resync.rs` and `upgrade.rs`, which the stack does not touch [code]; at N every e2e datadir is a new datadir that stores transactions by position (#1855) and runs `attach_tx_packs` at start | nothing | none known; the per-node override tests must re-run at N [inferred] |
| 02 `fix/1804-vote-queue` | as 00 | none: N does not touch `crates/consensus/primary/` [code] | nothing | none known |
| 03 `fix/epoch-record-closing-block-check` | as 00; `close_epoch.rs` auto-merges | (1) N's new record-0 arm calls the guard with M's signature: merged-03 `close_epoch.rs:458` `self.check_stored_record(&epoch_rec, false, parent_state, engine).await?;`, while head 03's `check_stored_record` (merged-03 `:792`) takes `(stored, certified, local: &SealedHeader, seed: Option<B256>, path: RecordCheckPath, engine)`: the merge does not compile (E0061) [code; inferred error class, the exact check is `cargo check -p tn-node` on the merge]. (2) N's floor rule now runs head 03's markers check at the floor block, because head 03 rides on `check_stored_final_state`'s answer (merged-03 `:1368` `local.number < *floor`) [code] | pass the closing header, the seed and `RecordCheckPath::Stored` in the record-0 arm, as the certified-reuse arm below it does; rewrite head 03's "at or below" docs (merged-03 `:791`, `:1625`) to "below" | `the_restored_floor_skips_the_closing_markers_too` (merged-03 `:3361`; floor 20, closing block 20, expects the skip; at N block 20 is compared and refused `BeaconRoot`); N's `replay_guard_skips_only_closing_blocks_below_the_restored_floor` (merged-03 `:2695`; its last step executes `header_of(recorded)`, a header without markers, and expects `write_epoch_record` to succeed: under head 03 it is refused) needs `execute_closing`/`closing_header_of`; N's `replay_guard_stops_on_an_uncertified_epoch0_record_that_does_not_match` passes once the call compiles (the `final_state` compare fails first) [inferred] |
| 04 `fix/epoch-record-collector-hardening` | as 00, plus `crates/state-sync/src/epoch.rs`: 2 hunks. Hunk 1 (merged-04 `:593`..`:615`): the doc of `collect_epoch_records`, mechanical in form but its content must say the conflict now always stops. Hunk 2 (merged-04 `:1312`..`:1328`): the test N renamed `test_collect_epoch_records_stops_on_a_record_conflicting_with_our_own`; the stack added `&mut walk_off()` to the call and kept the `Ok` expectation, N expects the error; not mechanical (take N's expectation with the stack's 5-argument call) | the conflict halt against #1849's unconditional stop (detail below): after the auto-merge, `Collection::refused` falls through to N's `stop_on_local_failure` (merged-04 `:297`), so every validated conflict stops the node with the switch off and below the threshold [code] | one of the three options below; recommended: keep the evidence line and the conflict counters, drop the switch and the threshold | `test_collect_epoch_records_halts_on_a_conflicting_certified_record` (merged-04 `:2251`, expects `Ok` with the halt off at `:2279`), `test_startup_sync_walks_and_halts_under_the_switches` (`:2327`, expects startup to succeed with the halt off, `:2367`), `test_conflict_and_invalid_record_lines_carry_the_evidence` (`:2394`, asserts `collected.is_err() == switches.conflict_halt` at `:2414` and the `this node keeps its own record` text), `test_conflict_halt_needs_a_super_quorum_of_the_full_committee` (`:2473`, expects `Ok` below the threshold); the conflicted test of hunk 2 [inferred from the asserts; the check is `cargo nextest run -p state-sync` on the merge] |
| xf `fix/epoch-loop-output-drop` | as 04 (inherited) | N touches the replay that the fix's recovery advice relies on (`start_epoch.rs:151`..`:160` N: `persist_current` before the first replayed output): additive, the advice "a restart replays the missing output from the consensus DB" stays true [code]; N does not touch `run_epoch.rs` [code] | nothing | none known |
| 05 `fix/1804-quorum-exec-block` | as 04 | none in code (proposer, `epoch_votes.rs`); `tests/it/epoch_close_forms.rs` (head 05) documents `CONFLICT_LOGS` as "an epoch-record conflict that does not stop the node: the collector's (with `epoch_record_conflict_halt` off, or below its threshold)" (`fac7a05fb:crates/e2e-tests/tests/it/epoch_close_forms.rs:86`), untrue at N | the doc; add N's line `a certified epoch record from peers conflicts with this node's own record for the epoch` to the fatal lines | the doc only; the assertion (no node logs any of these lines) still holds in a healthy run [inferred] |
| 06 `fix/1807-digest-order-hold` | as 04 | none: N does not touch `order_hold.rs`, `proposer.rs` or the primary [code] | nothing | none known |

### Conflict halt (head 04) against #1849's unconditional stop

Both paths act on the same event: `collect_epoch_records` downloads a record and certificate for an epoch this node holds without a certificate, the record passes `validate_downloaded_record`, and `save` refuses it with `EpochDbError::ConflictingRecord` because this node stores a different (its own, uncertified) record for the epoch [code: N `crates/state-sync/src/epoch.rs:272`, `:301`, `:308`; head 04 merged-04 `:243`].

| | main at N (`stop_on_local_failure`, `epoch.rs:228` N) | head 04 at M (`Collection::refused`, merged-04 `:243`..`:298`) |
|---|---|---|
| records that reach it | every validated certified record that conflicts with this node's own, whatever its signer count: validation accepts a super-quorum of a smaller committee left by an on-chain ejection, 5 of an anchor committee of 10 [PR 04 text; head 04 doc merged-04 `:228`] | the same records |
| decision | always stop [code] | stop only with `epoch_record_conflict_halt` on and signers >= `2n/3 + 1` of the `n` members the previous record names (`halt_threshold`); otherwise log and ask again on a later pass [code] |
| nodes | every node that runs the collector or the startup sync: committee validators, non-committee validators, observers [code: `spawn_epoch_record_collector` is a critical task, `epoch.rs:412` N; `sync_epoch_records_to_tip` `:94` N] | the same nodes, per their own switch |
| counted | `tn_epoch.final_state_mismatches_total` (Prometheus `tn_epoch_final_state_mismatches_total`), the counter the close-time guard uses [code `:215`, `:230`] | `tn_state_sync.epoch_record_conflicts_total` always, `tn_state_sync.epoch_record_conflicts_below_halt_threshold_total` below the threshold [code] |
| logged | one `error` line, target `epoch-manager`, fields `epoch` and `e`: `a certified epoch record from peers conflicts with this node's own record for the epoch: this node's execution diverged from the certified chain, stopping the node`; the task error begins `epoch {epoch}: a quorum certified an epoch record other than the one this node built from its own execution` [code `:231`..`:244`] | one `error` line, target `epoch-manager`, with `epoch`, `stored`, `offered`, `peer`, `signers`, `committee`, `signer_ids`, `offered_epoch`, `offered_parent`, `offered_final_number`, `offered_final_hash`, `halt_threshold`, `conflict_halt`; text `epoch record conflict halt: ...` or `epoch record conflict: ... this node keeps its own record` [code] |
| restart | stops again: the startup sync and the collector ask for the same epoch [code: N doc `:226`..`:227`] | stops again with the halt on at the threshold; runs on otherwise [code] |

What the auto-merged head 04 does [code: merged-04 `:252`..`:297`; inferred outcome]: with the halt on and the threshold reached, the stack returns its own error first, so main's counter and main's line are skipped for that conflict; in every other case the stack counts and logs `epoch record conflict: ... this node keeps its own record`, then `stop_on_local_failure` counts `tn_epoch.final_state_mismatches_total`, logs main's line and stops the node.
So below the threshold, or with the switch off, the node now stops, right after a line saying it keeps its own record; `epoch_record_conflict_halt=false` no longer means "as main", and `tn_state_sync.epoch_record_conflicts_below_halt_threshold_total` no longer predicts who would stop.
The two decisions differ only on records certified by fewer than `2n/3 + 1` of the anchor committee: main stops on those, the stack's threshold exists to not stop on them [code; PR 04 text, "at most f faulty members cannot reach the halt threshold"].

Options for head 04:

1. Drop the switch and the threshold; main's stop is the only decision.
   Remove `epoch_record_conflict_halt` (its `Parameters` field, `node switches` entry, `ConflictEvidence::halt_threshold`, the below-threshold counter), keep or drop the evidence line.
   Consequences: PR 04 goes from three switches to two; four head-04 tests are deleted or reduced (list in the table); the harness drops the switch from `benchmark/config.sh:329` `BENCH_NODE_SWITCH_KEYS`, `benchmark/arms/switches.tsv:7` and the tests that name it (`benchmark/tests/test_params_apply.py:2020`, `:2031`, `:2051`, `:2125`, `test_arms_summary.py:432`, `test_report_provenance.py:752`, `:755`, `test_node_image.py:3056`) [code]; a bench 7 image from the stack on M still has the switch, so the harness change waits for the image built on N.
2. Keep the stack's line and counters around main's stop (recommended).
   `refused` logs the evidence line with the text changed to say the node stops, counts `tn_state_sync.epoch_record_conflicts_total`, then hands every conflict to `stop_on_local_failure`; the switch and the threshold go (as in 1), or the below-threshold counter stays as information with no decision attached.
   Consequences: one stop rule, main's; main's counter counts every conflict, which keeps main's doc of `final_state_mismatches_total` (`crates/node/src/metrics.rs:23`..`:26` N) true; operators keep the signers, peer and offered record that main's line lacks; the test changes are those of 1 plus rewording the evidence asserts.
3. Keep both.
   With the switch off this is option 2 with a stale switch; with it on, the stack's error pre-empts main's, so main's counter misses the stops it is documented to count; to give the switch any effect it would have to let a node run on below the threshold, which weakens the stop main chose and breaks the stack's own rule that a switch at its default behaves as the base [rules file, "Every behaviour change sits behind its switch"].

Recommendation: option 2.
The evidence fields are the part of head 04's conflict work main does not have; the threshold disagreement (main stops on a record a smaller post-ejection committee certified) is a question for upstream, raised as a comment on #1850 (section 3), not a switch that can only weaken main's stop.
One gap the change leaves for the re-certify path [inferred]: head 04's re-certify round on an older record still logs `own epoch record differs from a certified record in a re-certify round` and runs on with the halt off (PR 04 text); at N the collector stops on the same divergence once it reaches that epoch, so for consistency that line should lead to the same stop, or say why a vote-round conflict on an older record is different.

What in `tasks/pr-bodies/bench6-04-collector-hardening.md` becomes untrue at N (quoted):
- Line 14: "A conflicting certified record is only logged (`state-sync/src/epoch.rs:279`), though the vote round's recovery stops the node on it (`epoch_votes.rs:279-289`)." True of M only; N stops on it (`epoch.rs:228`..`:245` N).
- Line 37: "Recovery: switch it off and restart: the node logs `epoch record conflict: … this node keeps its own record`, counts it and runs on, as on main." At N (merged) the node stops after that line, and main stops too.
- Line 38: "Pre-flight (the switch's doc), with it off: if that counter exceeds `tn_state_sync.epoch_record_conflicts_below_halt_threshold_total`, the node would stop; grep logs for both conflict lines; flip one node at a time." At N every conflict stops the node with the switch off.
- Line 51: "Nodes differ only in which records they hold certified and who halts; ..." At N, for the collector, every node halts on a conflict; only the re-certify round's handling differs.
- Line 79: "Turning the halt on stops a node already holding a conflict: hence the pre-flight." At N the node stops without the switch.
- Line 80: "Open: a failed committee read counts as below the threshold (the pre-flight misses it)" is moot at N.
- Line 3 and line 46 stay literally true ("three switches, default off"; "the `epoch record conflict:` line before main's handling"), but main's handling is now a stop, which the text does not say.
The text is pinned "On main at 45dce8947" in line 12 and the PRs go into a staging branch at M, so lines 12-14 are accurate for that base; lines 37-38 and 79 describe behaviour, and they are false for any merge with today's `main`.

### Closing-block check (head 03) against the narrowed floor rule and the record-0 path

Head 03 has no floor rule of its own: `check_stored_record` (head 03 `close_epoch.rs:786`..`:836`) runs `require_closing_block` only when `check_stored_final_state` answers `Matches`, and skips it on `Restored` [code].
After the merge it therefore follows N's rule (`<`) by construction: the floor block is compared on both counts, a block below the floor on neither [code: merged-03 `:1368`].
That is consistent with N's reason for the change: the floor block's header is the real one the restore imported (N doc, `close_epoch.rs:1265`..`:1269`), so it carries the closing markers the engine wrote [inferred: the header bytes are the original node's; I cannot tell without a restore that the imported header keeps `parent_beacon_block_root`, the nonce and `extra_data`; the check is a `db load-state` restore followed by a node start past the restored epoch, or a unit test that imports a real closing header at the floor].
What does not follow by construction is head 03's text: the doc of `check_stored_record` (merged-03 `:791` "A closing block at or below it is compared in neither way"), the `branch` doc (`:1625` "`stored_restored` for one whose closing block it restored") and the test `the_restored_floor_skips_the_closing_markers_too`, which must put the floor at 21 for the skip and expect a refusal at floor 20.

For this node's own uncertified record 0 (N `close_epoch.rs:430`..`:433`), the check must run where main's guard runs: the arm should call head 03's `check_stored_record` with `&closing_block`, the seed taken as in the certified-reuse arm, and `RecordCheckPath::Stored`, so main's `final_state` compare fails first and the markers are checked after it.
Then the record is built again and the build path checks the markers a second time, so that close counts two `ok` results in `tn_epoch_epoch_record_closing_block_check_total` [inferred]; harmless, but the PR text's "Every check counts" stays true only in that literal sense.

What in `tasks/pr-bodies/bench6-03-closing-block-check.md` becomes untrue or incomplete at N (quoted):
- Line 14: "On main at 45dce8947 the #1834 guard stops the node when a stored record's `final_state` differs from its closing block (`crates/node/src/manager/node/close_epoch.rs:1274`), on the stored close path (`:432`) and at every entry (`:590`)." Accurate for M; at N main also guards this node's own uncertified record 0 (`:430` N), a third path the text does not list.
- Line 30: "Kept: record contents byte-identical to main, the restored-floor skip, main's guard tests (their fixtures now carry the markers)." At N the restored-floor skip is narrower (below the floor, not at it) and N's two new or rewritten guard tests do not carry the markers.
- Line 49 names `the_restored_floor_skips_the_closing_markers_too` among the passing tests; at N it fails as written [inferred].
- Line 37: `branch` = `stored_restored` stays a possible value, now only below the floor.
- Line 69: "False positives, traced in the code with none failing: ... a snapshot restore ..." was traced under the old rule; at N the floor block is checked, which is the trace that needs redoing (the restore check above).

### Does N change anything the walk or the re-certify relies on?

The walk (`epoch_record_collect_past_uncertified`) relies on the collection loop of `collect_epoch_records`, on peers answering "not held" for an epoch they hold no certificate of (`crates/consensus/primary/src/network/handler.rs`, untouched by N), on `validate_downloaded_record` (untouched) and on the save's refusals [code].
N changes one of those: a `ConflictingRecord` at a gap retry or after a walk now stops the node instead of ending the pass [code].
The walk itself cannot produce one for the walked epoch: the next record must validate against this node's own record of it, so its certified twin is the same record [inferred, from PR 04's "the next record must validate against that own record"].
`test_a_refusal_after_a_walk_reaches_the_end_of_the_pass` (merged-04 `:2629`) exercises a parent mismatch (`PARENT_MISMATCHES`), not a conflict, so it is unaffected [code].
The re-certify (`epoch_record_recertify`) lives in `crates/node/src/manager/epoch_votes.rs` and `revote_uncertified_epoch_record_on_startup`; N touches neither (N's `node.rs` hunks are at `:316`, `:758`, `:781`, `:1039`, `:1067`, `:1823`, `:1842` of M) [code].
It relies on own uncertified records staying in the store; N's record-0 arm stops a node whose own record 0 does not match its closing block before any re-vote, which is the guard's purpose and changes nothing for a matching record [code].

## 3. The posted issues at N

All four are open with no comments (`gh issue view <n> --repo Telcoin-Association/telcoin-network`, read 2026-11-15) [code: gh].
Files the issues cite that N leaves byte-identical: `crates/node/src/manager/epoch_votes.rs`, `crates/node/src/manager/node/run_epoch.rs`, `crates/engine/src/lib.rs`, `crates/consensus/primary/src/network/handler.rs`, `crates/storage/src/epoch_records.rs`, `crates/consensus/executor/src/subscriber.rs`, `crates/tn-reth/src/payload.rs` (`git diff --stat M N` over them names only `crates/tn-reth/src/evm/block.rs`) [code].

### #1850 (G1: an uncertified epoch stops every collector; G2: a conflicting certified record is only logged)

- G1 is still present at N [code]: the pass skips epochs held certified (N `crates/state-sync/src/epoch.rs:272`..`:291`), asks for the next (`:293`), and ends at the first epoch no peer serves (`:372`..`:374`, `break` when `result_epoch != epoch`); the loop resumes from there (`:419`..`:446`); peers still serve a record only with its certificate (`handler.rs` unchanged) and the re-vote is unchanged (`epoch_votes.rs` unchanged).
- G2 is fixed at N by #1849 [code]: `stop_on_local_failure` (`:228`..`:245`) counts `tn_epoch.final_state_mismatches_total` and stops the node on `ConflictingRecord`; the two tests the issue cites as pinning G2 (M `:651`, `:798`) are renamed and inverted (N `:681` `test_collect_epoch_records_stops_on_a_record_conflicting_with_our_own`, `:828` `test_only_local_store_failures_and_conflicts_stop_collection`).
  #1849's stop is the issue's own proposed G2 fix ("stop the node on a conflicting certified record, as the vote round's recovery does, and count it"), without a signer threshold.
- The issue needs a follow-up comment. Facts:
  1. G2 was fixed by #1849 (`d4d53c115`): `stop_on_local_failure` now stops the node on a validated conflicting certified record and counts `tn_epoch_final_state_mismatches_total` (`crates/state-sync/src/epoch.rs:228-245` at 33b727fce); a restart stops again.
  2. G1 is unchanged at 33b727fce: the pass still ends at the first epoch no peer serves (`:372-374`), peers serve only certified records, the re-vote is unchanged.
  3. Open for G2: main stops on any record that passes validation, which after an ejection accepts a super-quorum of the smaller committee (5 of an anchor committee of 10); the prepared change would only have stopped at 2n/3+1 of the anchor committee.

### #1851 (no check that `final_state` is the closing block)

- Still present at N [code]: the build path samples `latest_execution_block_num_hash()` (N `close_epoch.rs:411`) and saves the record unchecked (`:520`); no path compares `parent_beacon_block_root`, the nonce's epoch or `extra_data` with the record; the guard's test header has no markers (`header_of`, `:2054`).
- N changed two facts the issue states [code]: the guard now skips only a closing block below the restored floor, not at it (`:1280`, `<`), and it also runs on this node's own uncertified record 0 before that record is rebuilt (`:430`..`:433`).
  Line numbers moved: guard `check_stored_record` M `:712` is N `:718`; the `extra_data` write M `evm/block.rs:2118` is N `:2137`; `boundary_consensus_digest` M `:1294` is N `:1303` [code].
- A follow-up comment is optional; if one is posted, the facts:
  1. At 33b727fce (#1849) the guard skips a closing block only below the restored-state floor; the floor block is compared (`close_epoch.rs:1280`).
  2. #1849 also sends this node's own uncertified record 0 through the guard (`:430-433`), a stored path the closing-block check must also cover.
  3. The build path, the markers and the missing `final_state` log are unchanged; line references in the issue are for 45dce8947.

### #1852 (false quorum error)

- Still present at N, at the same lines: `epoch_votes.rs` is byte-identical between M and N, so `:231`..`:237` still raise `failed to reach quorum on epoch close` with no store check [code].
- No follow-up comment needed.

### #1860 (the epoch loop drops a consensus output when pre-empted)

- Still present at N [code]: `run_epoch.rs` and `crates/engine/src/lib.rs` are byte-identical between M and N; the drain is at the same lines (N's `close_epoch.rs` hunks start at M `:416`, below the drain's `:319`..`:348`); `to_engine`'s capacity at `node.rs:91` is above N's first `node.rs` hunk (`:316`).
- N changed what a hit costs in one place [code]: #1855's execution stores each block's transactions as positions in the batch it executed (`crates/engine/src/payload_builder.rs:44`..`:49` N), and #1855 persists the current pack before a restart replay (`start_epoch.rs:151`..`:160` N).
  Neither adds a check of the output's number or consensus parent in the engine, so X+1 still executes on X-1's state [code: `payload_builder.rs` N diff adds no such check].
  The issue's recovery reference (`telcoin-network db reset-execution --force`, `crates/telcoin-network-cli/README.md:487-493`) points into a file #1849 rewrote (README +29 lines, `reset_execution.rs` +297) [code: file stats]; I did not re-read the recovery, so whether its text still holds at N is not checked.
- A follow-up comment is not needed for the defect; if one is posted, the facts:
  1. Unchanged at 33b727fce: `run_epoch.rs`, `crates/engine/src/lib.rs` and the drain in `close_epoch.rs` are byte-identical to 45dce8947 (line numbers hold).
  2. #1855 stores transactions as batch positions and persists the pack before replay; neither changes the drop or the engine's missing continuity check.
  3. The README recovery section cited was rewritten by #1849; check its line numbers before linking.

## 4. The harness

Verdict [inferred from the items below; the exact check is the deploy gate's image probe plus steps 7-10 on one VM]: an image built from the stack brought onto N starts under the harness as it is.
Nothing the harness passes, writes or requires is renamed or removed by N, except two startup log phrases the teardown prefilter keeps and no tool reads.
An image built from plain N (no stack) is refused at the gate by `require node switches` (`benchmark/node-image-contract.txt`), as designed: the phrase exists at M and N only in two doc comments (`crates/storage/src/consensus.rs:1221`, `crates/telcoin-network-cli/src/db.rs:1816` at M), which are not in the binary [code].
Every harness item below that names `epoch_record_conflict_halt` changes only if head 04 drops the switch (section 2).

| item | at N | evidence |
|---|---|---|
| node image contract strings (`benchmark/node-image-contract.txt`, 16 `require*`/`forbid*` lines) | unchanged: each string occurs as often in `crates/`, `bin/`, `vendor/` at N as at M | [code: `git grep -F -c` per string at M and N, all 16 equal] |
| CLI flags the gate checks (`BENCH_NODE_FLAGS_NODE`, `_GENESIS`, `_KEYTOOL`, `benchmark/bench-lib.sh:1253`..`:1255`) and `--db.sync-mode` / `--allow-faucet-on-chain` | unchanged: N adds no `#[arg]` to `node`, `genesis` or `keytool`; its one new flag is `db reset-execution --for-swap`; `--bootstrap-peers` keeps its name (doc text only, `crates/telcoin-network-cli/src/node.rs:96` N); `--db.gap-fill` and `DEFAULT_DB_GAP_FILL` unchanged (`crates/tn-reth/src/cli.rs:140`, `:152` N) | [code: `git diff -U0 M N` over `crates/telcoin-network-cli/src`, `crates/tn-reth/src/cli.rs`, `rpc_server_args.rs`] |
| genesis and keygen (deploy steps 5-6 call `devnet-keygen.sh` and `devnet-genesis-build.sh`, `benchmark/benchmark-deploy.sh:1297`..`:1304`) | unchanged: #1848's `genesis/mod.rs` edits are in `mod tests` only; a committee file without `bootstrap_servers` now loads with an empty map (`crates/types/src/committee.rs` `#[serde(default)]`), which only widens what loads | [code] |
| bootstrap servers for the bench's own genesis | unchanged in effect: the bench starts no node with `--chain` (no `--chain` in the fleet scripts), so `Config::bootstrap_servers` is `None` and the default stays the genesis committee file's servers (`Config::default_bootstrap_servers`, `crates/config/src/node.rs:194` N); validators then dial those (their network-config sets `committee_peers`, not `bootstrap_peers`), the observer its network-config's hub entry (`devnet-network-config.py:514`) | [code; inferred for the fleet] |
| new startup lines from #1848 | added: `bootstrap peers selected` (`servers`, `source` = `genesis committee file` on a validator, `network-config` on the observer) at `info` on `epoch-manager` (`crates/node/src/manager/node.rs:1063`..`:1068` N); the `warn` `no bootstrap peers, committee peers or trusted nodes are configured, ...` (`:1099`..`:1104`) cannot fire on the bench fleet, whose nodes all set at least one of the three | [code; inferred for the fleet] |
| `parameters.yaml` keys the harness writes (`benchmark/parameters.yaml`, the switch keys of `benchmark/arms/switches.tsv`) | unchanged: N adds no `Parameters` field and removes none (`crates/config/src/node.rs` N hunks are outside `Parameters`); `Config::bootstrap_servers` is `#[serde(skip)]` | [code] |
| node start: refusal on an unfinished `db load-state` | new, inert for the bench: the node refuses to open its execution database when `<datadir>/load-state-in-progress` exists (`crates/telcoin-network-cli/src/node.rs:398` N); the harness never runs `db load-state` (no `load-state` in `benchmark/*.sh`) | [code] |
| node start: pack coverage (#1855) | new, inert for the bench: a datadir that stores transactions by position refuses to start unless every epoch from its first stored transaction to its tip has a consensus pack (PR #1855, "Startup and replay"; call at `crates/node/src/manager/node.rs:1884` N); the harness never moves or deletes `consensus-db/` (it only sizes and lists it, `benchmark/node-sampler.sh:158`..`:167`) | [code; PR] |
| datadir paths the samplers read: `db/tn-lmdb.dat`, `db/mdbx.dat`, `static_files/` (`benchmark/node-persist-sampler.sh:77`..`:79`; `benchmark/tools/folio-census.py:77`), `consensus-db/epochs`, `cache`, `epoch` (`node-sampler.sh:158`..`:160`) | unchanged paths: N's fixture of a new datadir has `db/tn-lmdb.dat`, `db/database.version` and `static_files/static_file_*` as before (`crates/tn-reth/tests/fixtures/format-freeze/v2-ptr/datadir/`) | [code] |
| what those paths hold on a datadir created at N | changed: the reth marker `tn_storage_layout` records format version 2, `LAYOUT_VERSION_TX_POINTERS` (`crates/tn-reth/src/env/layout.rs:80`, `:88` N); the `Transactions` jars under `static_files/` are NippyJar version 3 and hold each transaction's batch position, about 15 B instead of about 186 B per transaction (PR #1855); `db/` is unchanged (PR #1855, "Space"); the transaction bodies now exist only in `consensus-db/epochs/`, which the folio census does not cover, so the census's targets (page file plus `static_files/`) no longer include any page a transaction read touches | [code; PR; inferred for the census] |
| log phrases the teardown prefilter keeps (`benchmark/tools/log-shapes.txt`) | changed, two of them: `reth datadir: storage layout` and `keeps its storage layout` no longer exist at N; the lines are now `new reth datadir: storage format` / `reth datadir: storage format` with `layout` and `tx_bodies` (`crates/tn-reth/src/env/layout.rs:411`, `:460` N) and the warning `this reth datadir keeps its storage format: ...` (`:462`); the prefilter would drop them; no harness tool reads them (grep of `benchmark/tools/*.py`, `benchmark/report/*.py`, `benchmark/*.sh`); every other phrase occurs at N as often as at M, or more | [code: `git grep -F -c` per phrase at M and N] |
| `persisted output` (the persist sampler's page-operation source) | unchanged fields: `first`, `last`, `blocks`, `txs`, `receipts`, `accounts`, `storage_slots`, `open_ms`, `save_blocks_ms`, `markers_ms`, `commit_ms` (`crates/tn-reth/src/env/execution.rs:1115`..`:1128` N; M `:903`..`:916`) | [code] |
| fail-stop phrases (the `# bench 7 fail-stops` block of `log-shapes.txt`, `node-sampler.sh`'s `halt=`) | gap at N: #1849's stop, `a certified epoch record from peers conflicts with this node's own record for the epoch: ...` (`crates/state-sync/src/epoch.rs:235`..`:236` N), is in neither list, so the prefilter drops it and the halt count misses it; with head 04 brought forward by option 2 this is the collector's only stop line | [code] |
| metric names the export requires (`MUST_HAVE`, `tasks/bench7/orch-prom-export.py:51`..`:96`) | unchanged as far as source names go: the main-sourced names (`tn_reth.persist_commit_seconds`, `tn_reth.persist_save_blocks_seconds` at `crates/tn-reth/src/env/execution.rs:980`, `:982` N, and the engine, executor, primary and reth-db fragments) occur at N as at M; N adds `tn_reth.tx_body_inline_rows_total`, `tn_reth.tx_body_resolves_total`, `tn_reth.tx_body_resolve_failures_total`, `tn_reth.tx_body_pack_opens_total`, `tn_reth.tx_body_cache_bytes` (`crates/tn-reth/src/metrics.rs` N); whether every name is exported at run time cannot be told without running (the export's own `EXPORT_CHECK` against a live scrape is the check); `tn_state_sync_epoch_record_conflicts_below_halt_threshold_total` is in `MUST_HAVE` and goes if head 04 drops the threshold | [code; cannot tell without running] |

## 5. What N changes for the measurement

### Stated by the PRs

#1855 (`gh pr view 1855 --json body`):
- A new tn-lmdb datadir on storage layout v2 writes each `Transactions` static-file row as the transaction's position in its batch instead of the full transaction; "The transactions segment shrinks by 92%, from about 186 B to 15 B per transaction"; "Space on the same chain (129k txs): 186.5 → 15.3 B per tx; `db/` is unchanged".
- Existing datadirs "keep storing transactions inline and write exactly what they wrote before".
- "Block building, the persist and the pack save never read a pack"; the pack format peers exchange is unchanged.
- "The restart replay persists the current pack before it executes the first replayed output".
- Benches are macOS M1 Max, "CPU-side; durable-commit times need Linux": `save_blocks_sf` ×0.76 to ×0.82, total mean ×0.992 to ×0.996, per-output p50 ×0.989 to ×1.002, `signer_recovery` +5.5–8%; "Linux bench runs for durable-commit numbers and the cold-page-cache read column" are listed as follow-ups.
- Reads (p50 µs, inline → from the decoded-batch cache → from a warm pack → pack must be opened): tx by hash 3.4 → 4.5–6.4 → 146 → 922; receipt by hash 150 → 154–160 → 294 → 922; the cache is 64 MiB (56 MiB recent batches filled after each persist, 8 MiB cold).

#1849 (`gh pr view 1849 --json body`):
- "Nothing here changes what a node computes for a block."
- Exec A/B against main, macOS: "total mean ×1.007 and ×1.010; Mgas/s ×0.993".
- "A writer open drops the page cache on any 'open' record" (the tn-lmdb boot record), i.e. after an unclean stop.
- "`truncate_changesets` syncs the record it flushed before writing the `.conf`."
- New operator switch `TN_EXEC_CACHE=0` (build without the execution cache); the bench does not set it.

### Read from code

- Per block, the persist path is the same call with one more argument: `persist_output_with_retry(&reth_env, &executed_blocks, &tx_positions)` (`crates/engine/src/payload_builder.rs:416` N), down to the vendored provider's `save_blocks_with_tx_positions`, which writes through the same `write_blocks_data` (`vendor/reth/crates/storage/provider/src/providers/database/provider.rs` N, hunk at M `:546`) [code].
- No sync is added to or removed from the per-block path: across `crates/tn-lmdb/src`, `crates/storage/src`, `crates/tn-reth/src/env` and `vendor/reth/crates/storage`, every `sync_*`/`persist` call `M..N` adds is in a test, except the replay's `persist_current` (`crates/node/src/manager/node/start_epoch.rs:158`..`:160` N, only when the restart has outputs to replay) [code: the `-U0` diff, `grep`].
- #1849's added `truncate_changesets` sync is reached only from `prune_account_changeset_data` and `prune_storage_changeset_data` (`vendor/reth/crates/storage/provider/src/providers/static_file/writer.rs:1895`, `:1914` N), a prune path, not the steady per-block one [code; inferred that the bench never prunes].
- After each committed persist, `reth_env.cache_persisted_batches(&output, &tx_positions)` hands the output's batches to the decoded-batch cache, "whose sink copies them off this thread" (`crates/engine/src/payload_builder.rs:429`..`:431` N): memory and CPU, no disk write [code].
- On tn-lmdb (`TxBodies::for_new_datadirs()` is `Pointers` unless built with `mdbx`, `crates/tn-reth/src/env/layout.rs:169` N), every fresh bench datadir is a pointer datadir, since each run starts from genesis [code; inferred for the bench].

### Inferred: what a bench run on M misstates about main at 20,000 IOPS

- Bytes: a node on M writes about 171 B per transaction more into `static_files/static_file_transactions_*` than a node on N (186.5 − 15.3 B, PR #1855's figure, not measured on Linux); per 1,000 tx/s that is about 171 kB/s more device bytes and a `static_files/` total in the persist CSV that grows faster by the same amount.
- Write count and syncs: the same files are appended and synced at the same commits on M and N (code above), so the syncs per persist are the same.
  The shed bytes are sequential appends to one file, at most about 42 pages of 4 KiB per second per 1,000 tx/s; even if each were its own write I/O, that is at most 0.2% of 20,000 IOPS per 1,000 tx/s (arithmetic on PR #1855's figure).
  On Hyperdisk at 20,000 IOPS the write count and the syncs bind, not the bytes (the program's working rule on disk classes, set by the user on 2026-11-11), so a run on M should show main's binding disk behaviour within that bound.
  This is an inference: the check is one A/B, M's image against an N-based image, on one VM class with the persist sampler's `disk_wr_ios_total`, `disk_wr_bytes_total` and `disk_flush_ios_total` per persisted output.
- Reads: on N, RPC reads of a transaction body go through the decoded-batch cache or the consensus packs; the bench's RPC readers (the blaster's receipt reads) read recent blocks, which the 56 MiB recent cache should hold, and PR #1855's own numbers put a cached receipt read within 3-7% of inline; pages of `consensus-db/epochs/` read for cold transaction bodies are outside the folio census (section 4).
- CPU: PR #1855's macOS numbers show execution per output within ±1.1% and `signer_recovery` +5.5–8%; PR #1849's ×1.007 to ×1.010; neither PR measured durable commits on Linux, so whether a persist-bound node on Linux moves is not known from either source.
- Restarts: on N an unclean restart (a kill) drops the tn-lmdb file's page cache at open (PR #1849), and a restart with outputs to replay persists the pack once more (code above); a run that kills and restarts a validator would see a colder restart on N than on M; nothing else in N changes the steady-state per-block writes.

## 6. Effort of bringing the stack onto N by merge

The heads' commits stay as they are.
Two shapes, both merges:

- A merge per head, cascading: fast-forward the staging branch from M to N (N descends from M [code]), merge it into head 00, then merge each merged head into the next head up.
  The hand resolution happens twice, at head 00 (`crates/config/src/node.rs`, 1 hunk, keep both test blocks) and at head 04 (`crates/state-sync/src/epoch.rs`, 2 hunks); every later merge inherits them [inferred from the merge-tree results: heads 01-03 and xf-06 conflict only in the files 00 and 04 already conflict in].
  The code changes of section 2 then go on top as ordinary commits at heads 03 and 04, before the next head's merge, so each PR's diff carries its own adaptation.
  PRs 00-04 keep their texts' structure; PRs 03 and 04 need the text changes listed in section 2.
- One merge of N at the top (`fac7a05fb`): one resolution of the same three hunks and the same code changes, in one place; heads 00-05 stay on M, so PRs 00-04 into the staging branch at M stay as they are, and only the image's source moves to N.
  This leaves the PR texts true for their base and puts every N adaptation in a commit no PR shows.

Work, with what it rests on:

| item | size | basis |
|---|---|---|
| node.rs hunk (head 00) | mechanical, about 15 min | [merge-tree] one hunk, both sides append tests |
| epoch.rs hunks (head 04) | about 30 min | [merge-tree] hunk 1 a doc comment, hunk 2 one test's expectation |
| head 03 adaptation: the record-0 call (one line), three doc passages, two tests (`the_restored_floor_skips_the_closing_markers_too`, N's floor test fixtures) | 1 to 1.5 h with its unit runs | [code] section 2 |
| head 04, option 2: `refused` text and fall-through, remove `epoch_record_conflict_halt` (field, `node switches` entry, `EpochRecordCollectSwitches::conflict_halt`, the halt branch), decide on the below-threshold counter, four to five tests | 3 to 4 h with its unit runs | [code] section 2; my judgement for the hours |
| head 05: `epoch_close_forms.rs` doc and fatal-line list | 15 min | [code] |
| PR texts 03 and 04 (section 2's sentences), the #1850 comment (section 3) | 1 to 2 h with a figure-check | judgement |
| harness, only if option 1 or 2 drops the switch: `benchmark/config.sh:329`, `arms/switches.tsv:7`, six test files; add `reth datadir: storage format`, `keeps its storage format` and #1849's stop line to `tools/log-shapes.txt` and the halt count | 1 to 2 h, plus the whole-suite gate (about 70 min, alone on the host) | [code] section 4; the 70 min from `tasks/checkpoint-bench7-orch.md:670` |
| domain review of the head 03 and head 04 changes (one `tn-domain-reviewer` each, as the rules require) | about 1 h of waiting | rules file, "Domain review" |

Gates that would have to re-run, and what is known of their cost:

- Package tests of the changed crates (`-p tn-node -p state-sync -p tn-config`), per changed head: minutes each; the orchestrator's runs of six packages are logged without durations (`tasks/checkpoint-bench7-orch.md:381`, `:555`).
- Workspace tests (`cargo nextest run --locked --workspace`): needed, since N changes `tn-reth`, `tn-lmdb`, `tn-storage`, `tn-engine` and the vendored reth well outside the stack; the stack's last run was 5,532 tests (`checkpoint-bench7-orch.md:760`), duration not recorded.
  Known noise: `tn-lmdb-reth` `tests::differential::random_scripts_match_mdbx_multi_leaf` failed once on a random seed and passed 10 of 10 on the same tree (`:760`, `:777`).
- Clippy lanes (`./etc/ci-lanes.sh clippy`, the release graph and the workspace with all features and with all but `mdbx`): needed; duration not recorded.
- The repository's e2e sets: `make test-epochs`, `make test-restarts`, `make test-sigkill` (each a lane-2 job that holds the host's quiet window, about 25 to 30 min of every other build waiting, `checkpoint-bench7-orch.md:211`), and `make test-e2e-resync` and `make test-upgrade`, which N's PRs changed and ran (PR #1849, PR #1855).
- The stack's 13 e2e tests ×3: one iteration was 13 passed in 3,394 s (56.6 min) (`checkpoint-bench7-orch.md:776`), so about 2.8 h of lane time, plus lane waits of 12 to 90 min seen in this program (`:514`, `:676`, `:704`).
- The image: about 16 min for a main-based build (this program's notes on image builds), then the gate's image probe.

Total, for the per-head merge with option 2: about 8 to 11 h of work and review, and 5 to 6 h of lane time that cannot overlap other builds (13 e2e ×3 about 2.8 h, the repository sets about 1.5 to 2 h, the image and the harness suite about 1.5 h), so in practice one long working day.
The top-only merge saves the per-head test runs of heads 00-02, xf and 05-06 (each of those merges is mechanical), which is roughly 1 to 2 h of the work and none of the lane time.
The lane-time figures rest on the recorded runs above; the work hours are my judgement from the size of the changes in section 2.
