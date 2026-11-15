# Sources: bench6-00-switches-obs.md on today's main (not posted)

Main = 33b727fcea4f6004d4b0cd2bd7923258e081e94f (`33b727fce`). Head `feat/bench6-switches-obs` = local mark `b7/n2-00` = b29d59bef7b46220aad81ddaeb48101f197a14b4 (12 commits on 33b727fce), read in `/home/drtnarg/coding/telcoin/tn-b7-p2` with `git show`, `git diff 33b727fce b7/n2-00`, `git range-diff 45dce8947..feat/bench6-switches-obs 33b727fce..b7/n2-00`.
Statements not listed here are unchanged from the earlier note `bench6-00-switches-obs.sources.md` and rest on code the move did not change (range-diff: commits 2-12 `=`, commit 1 differs only in the context of its test-module hunk).

## What changed and why

| text | source |
|---|---|
| "PR 1 of 6", merge order 00, 01, 02, 03, 04, then `fix/epoch-loop-output-drop` | `tasks/bench7/briefs/w-n.md` "What happened" (six PRs, merge order) |
| compare link `33b727fce…b29d59bef` (full shas), 12 commits | `git rev-parse 33b727fce b7/n2-00`; `git log --oneline 33b727fce..b7/n2-00` = 12 lines |
| twelve ids in "Change", each with its exact subject | `git log --reverse --format='%h %s' 33b727fce..b7/n2-00`, matched by subject to `45dce8947..feat/bench6-switches-obs`; each checked `git merge-base --is-ancestor <id> b7/n2-06` and subject verbatim (scratch script idcheck.sh: 13 OK) |
| "except the closing-block check, the epoch-loop fix and one eviction rule of the collector hardening, which have none" | `runtime_switches!` at b7/n2-03 = `vote_queue_fix` only (no switch added by head 03); at b7/n2-xf = the same three as b7/n2-04 (no switch added by the epoch-loop head); head 04's eviction at `b7/n2-04:crates/node/src/manager/epoch_votes.rs:610-621` (`vote_queues.retain(...)`, `if vote_queues.len() >= 5` → remove the lowest epoch's entry) reads no switch; review `tasks/bench7/review/n34-reshaped-heads-report.md` finding 6 ("the one switch-off difference from main in head 04") |
| On main at 33b727fce, `Parameters` (`crates/config/src/node.rs:273-274`) does not deny unknown fields | `git show 33b727fce:crates/config/src/node.rs`: 273 `#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]`, 274 `pub struct Parameters {`; no `deny_unknown_fields` in the file (grep). #1848 changed node.rs only in `Config` and a new `parse_bootstrap_servers` (diff 45dce8947..33b727fce) |
| "only comments added" to `Parameters` (unchanged statement, re-checked) | `git diff 33b727fce b7/n2-00 -- crates/config/src/node.rs`: struct hunk @374 and `Default` hunk @475 add marker comments only |
| `recorder.rs:18-19`, `:170` | unchanged file (`git diff --stat 45dce8947 33b727fce` has no recorder.rs); at 33b727fce 18 `const SECONDS_BUCKETS`, 19 `&[0.005, …]`, 170 `.set_buckets_for_metric(Matcher::Suffix("_seconds"…` |
| `proposer.rs:842`, `:1384-1385` | unchanged file; at 33b727fce 842 `// a re-queued digest's wait restarts here…`, 1384-1385 the `push_payload` doc "keeps no arrival time … restarts at `requeued_at`" |
| `handler.rs:353-358` | unchanged file; at 33b727fce 353 `} else if exec_epoch + 1 == epoch {` … 358 `round > gc_depth.max(6)` |
| switches line set in `EpochManager::new` (unchanged statement, re-checked after #1855 touched node.rs) | `git diff 33b727fce b7/n2-00 -- crates/node/src/manager/node.rs`: the four lines at @771 inside `pub(crate) async fn new` (line 767) |
| test names in "Pinned by" and Limits | `git grep -l "fn <name>" b7/n2-00 -- crates`: node.rs (5), tn-metrics recorder.rs (1), primary network_tests.rs (1), proposer_tests.rs (1) |
| at 17327280d: `cargo check --locked --workspace --all-targets`, warnings denied, clean; nextest of tn-config, tn-types, tn-node, tn-primary, tn-network-libp2p: 1,825 passed, 9 skipped | `tasks/bench7/gate-n1-02.log` lines 1-4 (`start 17327280d`, `check … rc=0`, `1825 tests run: 1825 passed, 9 skipped`, `done rc=0`); the commands from the gate script (orchestrator scratch `orch/gate-n1-02.sh`: `RUSTFLAGS="-D warnings -D unused_extern_crates"`, `cargo nextest run --locked --no-fail-fast -p tn-config -p tn-types -p tn-node -p tn-primary -p tn-network-libp2p`); 17327280d is `b7/n2-02` and contains b7/n2-00 |
| earlier cut: fmt and clippy clean over the four packages | `/home/drtnarg/coding/telcoin/tn-b7-pt0/target/tmp/g-fmt.log` (EXIT=0), `g-clippy.log` (`clippy --locked --all-targets -p tn-config -p tn-types -p tn-node -p tn-primary -- -D warnings`, EXIT=0), run on 8a42fec57 (same twelve commits on 45dce8947) |
| earlier cut: `cargo test` three times, 25 fork-pin failures each run, epoch-entry test ok | `tn-b7-pt0/target/tmp/g-cargotest-{1,2,3}.log` (EXIT=101), `g-fail-1.txt` 25 lines, `g-fail-{2,3}.txt` identical (`diff -q` silent); `g-cargotest-1.log:299` `epoch_entry_gauge_records_rounds_behind ... ok`; Makefile note at 33b727fce:188 still present |
| earlier cut, first nine commits: 1,207 passed with `-p tn-metrics` | `tn-b7-pt0/target/tmp/nextest3.log` (START line with the command; `1207 tests run: 1207 passed, 7 skipped`, EXIT=0); `tasks/checkpoint-bench7-PT-0.md:13` "gates on d8273bbe3"; d8273bbe3 = `test(primary): pin the epoch-entry gauge's max over epoch and round`, `git rev-list --count 45dce8947..d8273bbe3` = 9 |
| Stack-wide gates line | brief item 5 (exact line) |
| "(two switches)" for head 04, "(no switch)" for the epoch-loop head | `runtime_switches!` at b7/n2-04 adds `epoch_record_recertify`, `epoch_record_collect_past_uncertified`; at b7/n2-xf nothing more |
| tn-lmdb advises `MADV_RANDOM` on Linux, `env.rs:309-317` | at 33b727fce 309-316 the `readahead` doc, 317 `pub readahead: bool,`; 397 `readahead: !cfg!(target_os = "linux")`; `mdbx` feature off by default: `crates/tn-reth/Cargo.toml:148` `default = []`, `:163` `mdbx = []` |
| main runs the stored-record check unconditionally, `close_epoch.rs:718-755` | at 33b727fce 718 `async fn check_stored_record(` … 755 its closing brace; called at 431 (own record 0, #1849), 438 (stored record), 596 (entry). Was 712-749 at 45dce8947 |
| `parallel.rs:70-90` | at 33b727fce 70 "The walk and the tasks read separate transactions…", 80 "What would break it: persisting an output while the next one builds (a pipelined persist)…", 90 "…between the start of an output and its first root."; was 63-82 at 45dce8947 (#1849 rewrote the file) |
| placeholders | `{{epoch-record-closing-block-check}}`, `{{execute-and-persist-in-series}}` kept as is (the lint resolves them to #1851, #1853) |

## Dropped against the earlier text

- "On this head: … 677 passed" (earlier cut, nextest with a package filter): superseded by the gate at 17327280d, which runs the same packages and more.
- The old commit ids (`d1b89080d` for the first nine commits) and the stack-wide gate paragraph on `91a15e223` (brief item 5).

## Not verified at the new tip

- fmt and clippy on b29d59bef or 17327280d: no log; stated only for the earlier cut.
- `test_engine_stage_histograms_render_sub_ms_buckets` (tn-metrics) on today's main: tn-metrics is not in the gate at 17327280d; stated only for the earlier cut.
