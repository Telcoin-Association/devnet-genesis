# Bench 4 review B — benchmark harness half

Reviewer B, 2026-11-04 (xerxes). Read-only review of the uncommitted tree on main @ c0f3ca1.
Scope: `benchmark/pull-lib.sh` (new), `bench-lib.sh`, `benchmark-deploy.sh`, `benchmark-teardown.sh`,
`benchmark-blast.sh`, `config.sh`, `recovery-schedule.py`, `report/{kpis,make_bundle,provenance}.py`,
`.gitignore`, `benchmark/.gitignore`, and their tests/fixtures. Root drivers and devnet-lib are review A's.

Snapshot note: `benchmark-deploy.sh`, `test_node_image.py`, `test_pull_logs.py`, `test_report_bundle.py` and
`check_mutations.py` changed on disk at 17:42-17:46 while this review ran (the deploy's mkdir manifest lock
was replaced by the `NODE_JOBS_SPOOL` spool). The deploy was re-read after that change; the lock-leak
finding I had drafted no longer applies and is not listed.

## Verification done

- `bash -n` and `shellcheck -S warning` on pull-lib, bench-lib, deploy, teardown, blast, config: clean. The one
  hit, SC2148 in `tests/fixtures/node-image/v2-lib-common.sh`, is the same at HEAD.
- `tasks/check-bash-portability.sh` on the six scripts: no ERROR. No bash-4 constructs in the added lines
  (`&>>`, `|&`, `${x,,}`, `declare -A`, `mapfile`, `wait -n`, `EPOCHSECONDS`).
- Suites test_pull_logs, test_tunnel, test_teardown_local_gate, test_certification, test_admission_gate,
  test_cert_rate, test_recovery, test_report_kpis, test_report_bundle, test_report_provenance and
  test_repo_hygiene: 323 tests, 1 failure. The failure is
  `test_report_bundle.Run20260929IntegrationTests.test_slow_blast0_bundle`, and it comes from the
  environment: `results/r20260929-1647/logs` holds no node logs on xerxes (they were pruned to GCS), and
  HEAD's `provenance.py` finds no start line there either. The 17:45 edit to `test_report_bundle.py` makes
  that test depend on whether the logs are present, so this failure is already dealt with. Re-runs after
  the 17:42-17:46 edits: test_pull_logs + test_node_image ran 128 tests, all OK (5 skipped);
  `Run20260929IntegrationTests` OK.
- End-to-end pull, run in a scratch tree with the real bench-lib, pull-lib and devnet-lib. The
  `fixtures/pull` fake gcloud ran the sessions locally, a wrapper answered `instances describe`, and the
  "node" held `telcoin.log`, `.1` and `.2.gz`. Results:
  - The span, unit and rotated logs all landed. `rotated-1` decompresses to `.1` byte for byte, and
    `rotated-2` is byte-identical to `.2.gz`.
  - The marker lists all four files.
  - `LOGCOV` reads ok=1 against a covering window and ok=0 when due is before the first line.
  - A re-pull with aged markers dropped the identical stamped copies of the rotated generations.
  - No temp file was left locally or in the node's log dir.
- Mutations, run in a scratch copy:
  - Killed: both U-H1 anchors and the U-H3 anchor. Also killed: removing the tar end-block check,
    dropping `TN_IAP_RETRIES=0` on the stdin path, and dropping the reauth stop-file `touch`.
  - Two bench-lib wiring mutants survive all of test_teardown_local_gate, test_certification and
    test_pull_logs (S1).
- `git check-ignore -v --no-index`:
  - `/logs/`, `/archive/` and `/telcoin` ignore only the root. `benchmark/logs/` is still ignored
    (benchmark `/logs/`), and so is `common/logs/` (common's own `.gitignore`).
  - The fixture `etc/telcoin` and `libexec/telcoin` dirs are now plainly visible.
  - The only newly visible untracked file is `tasks/archive/plan-latency-adjustments-2026-10-06.md`, as U-H10
    recorded. `benchmark/private/` and `.secrets/` stay ignored.

## Findings

| # | severity | file:line | problem | concrete fix |
|---|---|---|---|---|
| B1 | BLOCKING | `benchmark/benchmark-teardown.sh:661` + `benchmark/bench-lib.sh:768` | **This is the one remaining way for the teardown to delete a node whose logs were never checked for coverage.** With `coordinated_start.due` and `blast_end` both known, `ok=-` can only mean that `<inst>.logspan` is missing, and the teardown counts `ok=-` as a note and deletes. `_bench_pull_node` treats span rc 1 (the session exited 0 and printed nothing) as "said, not failed" (`_bench_pull_rc 1` leaves `xfer=0`), so the node still gets its marker. A healthy span script always prints at least one `LOGSPAN` line per stream (`gen=0 bytes=-` when the file is missing), so an empty answer means the session broke. The comment at :763, "no unit file at all", describes a case the script never produces. The gate then quietly falls back to the presence-only check bench 3 had. In the same case a stale `.logspan` from an earlier pass stays in place and is read as current. | (a) bench-lib.sh:768: `1) echo "      ✗ ${inst}: the span session answered nothing" >&2; r=2 ;;` so `_bench_pull_rc` fails the node and no marker is written. (b) Teardown coverage loop: when `cov_due` and `cov_end` are both known, and the instance still exists (it is in `GATE_IDS`/`ALL_INST`), and `SKIP_LOGS` is not 1, count `ok=-` as not covered (`cov_bad`, named "no recorded span"). `ok=-` stays a note only for an unknown run window, a gone instance, or `SKIP_LOGS=1`. Add a teardown test: due and end known, live INST without a `.logspan`, expect exit 1 with nothing deleted. |
| S1 | SHOULD | `benchmark/bench-lib.sh:765-796` (tests) | **No test runs `_bench_pull_node` / `bench_pull_node_logs` end to end** (span → container → saved → unit → rotated → stamped dedupe → marker). The teardown tests write `.logspan` by hand and accept a fresh marker. test_pull_logs tests the helpers only. Two mutants survive test_teardown_local_gate, test_certification and test_pull_logs: (i) dropping `[ "${r}" -le 1 ] \|\| echo …; _bench_pull_rc "${r}"` after `bench_pull_rotated_logs` (:795-796). A failed rotated pull then still gets a marker, coverage passes from the node-side span, and the node is deleted without that generation: D19 again. (ii) Replacing `bench_pull_unit_span … \|\| r=$?` (:765) with `r=0`. No span is pulled, every node reads `ok=-`, and the teardown deletes. | Add one teardown test that ages INST's marker and lets the fake answer real span, rotated and unit sessions against a three-generation node dir. The scratch harness shows the shape: a gcloud wrapper answering `instances describe` with an id, plus `sudo` and `docker` stubs. Assert the landed names and bytes, the marker's file list, and `LOGCOV … ok=1`. Add a variant where the rotated session fails (`FAKE_OUTCOMES`), expecting exit 1 with nothing deleted. Register mutant (i) as a check_mutations anchor (U-H11). |
| S2 | SHOULD | `benchmark/benchmark-deploy.sh:597-601` (used at :676) | `create_fail_log` checks `-r` on the per-instance log path against the deploy's cwd. But `common/create-instances.sh:12` runs `cd "${REPO_ROOT}"` and names its logs `./logs/instance-creation/<ts>/<inst>_creation_<ts>.log`, relative to REPO_ROOT. Run from any other cwd (`cd benchmark && ./benchmark-deploy.sh --from 2 …`), the check falls back to the whole round log. There, one node's stockout text lets another node's quota or other failure pass `bench_is_stockout`, and that node moves to a fallback zone for a non-stockout reason. The stub prints absolute paths, so the tests cannot catch this. | Before the `-r` test: `case "${f}" in /*) ;; ?*) f="${REPO_ROOT}/${f#./}" ;; esac`. When the per-instance file is still unreadable, match only that instance's block in the round log (its "Failed to create instance <name>" line and the "Last 10 lines" that follow), or die. Do not judge it on the whole log. |
| S3 | SHOULD | `benchmark/benchmark-deploy.sh:1543` (`prom_window_wait`) | `bench_fleet_ready` returns 0 on its first pass when every validator reads `CvvActive` once. Bench 3's F3 target was promoted 11 times and demoted 8-34 s later each time, and U-TN5 only adds observability, so the loop can come back. If step 15 reads one of those brief promotions, the window ends with `end_reason=fleet_ready` before the real rejoin. That is exactly the defect item 24 was meant to close. | For the step-15 wait, require the mode to hold: read the chaos target again `BENCH_NODE_BACK_SECS` later, or across the next epoch boundary, and keep waiting up to the cap unless it is still `CvvActive`. Alternatively, end the window no earlier than the first epoch boundary after the restart plus `BENCH_FLEET_READY_SETTLE_SECS`. |
| S4 | SHOULD | `benchmark/benchmark-deploy.sh:174` / `:1895` (`deploy_log_start`) | `last-deploy.status` and `BENCH_DEPLOY_RESULT` come only from the EXIT trap that `deploy_log_start` installs. A `--yes` invocation that exits before that point writes neither and leaves the previous invocation's status in place (say `--to 12`, rc=0). Such early exits are config.sh validation (including the new zones.env count check and the knob checks), bench-lib refusing a missing `pull-lib.sh`, and argument errors. A watcher polling the status file for `--from 13 --to 15` would read a stale success and could start the teardown on a fleet that never ran. The coverage gate would then pass that fleet with `ok=-`, because there is no `blast_end`. | Watchers key on `started=` ≥ their own launch time (write that into the run procedure). In code: right after argument parsing, when `CONFIRM=1` and the run id is known, write `${DIR}/results/${BENCH_RUN_ID}/last-deploy.status` as `rc=-` (running) with `started=<now>` before sourcing bench-lib. The path can be computed before config.sh. |
| N1 | NIT | `benchmark/bench-lib.sh:372`, `:404` | `_bench_pull_node_log` and `_bench_pull_unit_log` now refuse an existing zero-byte `<out>` (rc 2, counted as a failed transfer), where HEAD replaced it. The callers pick a stamped name only when the file is non-empty (`-s`), so a zero-byte leftover blocks that node until someone removes it. | Pick the stamped name when `-e`, or `rm -f` a zero-byte `<out>` before the pull. |
| N2 | NIT | `benchmark/tests/test_teardown_local_gate.py:198` | `FakeCloud.env` does not pin `TN_IAP_RETRIES=0`, although the D3 test-side contract and the 2026-11-03 lesson require it. The pull path pins it itself, but recovery-lib's `tn_iap_ssh_stdin` and the gcloud describe/delete calls run with the default 2. | Add `"TN_IAP_RETRIES": "0"` to `FakeCloud.env`. |
| N3 | NIT | `benchmark/recovery-lib.sh:48` (unchanged) | The recovery-evidence pull is the only teardown pull that does not go through `bench_pull_stream`. A reauth there neither touches `BENCH_PULL_STOP_FILE` nor prints the login hint ("recovery evidence missing … nothing was deleted"). A retried session can concatenate output, but `tar -tzf` catches that, so it fails closed. | Pull it with `bench_pull_stream … gz … stdin`, then `tar -tzf`, or call `stop_if_reauth` when it fails. |
| N4 | NIT | `benchmark/benchmark-blast.sh:1037-1040` | `chaos_schedule_refresh` runs `bench_tunnel_up` (up to a 45 s wait) and an unalarmed `python3 recovery-schedule.py` (three RPCs at a 10 s timeout each) inside a poll. The only guard is `t_kill - now > GUARD + STAGE` (120 s). Add a ~40 s poll and the worst case reaches the kill's staging time. Normally the refresh takes about 1-3 s and moves the kill later, so this is unlikely. | Wrap the call: `perl -e 'alarm shift; exec @ARGV' 30 python3 …`. Skip the refresh at this poll when the tunnel was not already up, or add 75 s to its guard. |
| N5 | NIT | `benchmark/benchmark-teardown.sh:884` | `timestamps.teardown_done` is written even when instances are still deleting after `BENCH_TEARDOWN_DELETE_WAIT_SECS`, and `make_bundle.run_times` ends there. | Write it only when `PENDING` is empty; otherwise add a note. |
| N6 | NIT | `benchmark/pull-lib.sh:338-382` (design) | Coverage is judged from the node-side span taken at pull time, not from how far the local copies reach. A unit file vouched by an accepted marker ends at that earlier pull. This is harmless in the D5 flow, where only the teardown pulls and it runs after `blast_end`. | Add one line to the README "Teardown guarantees" row (U-H11). |
| N7 | NIT | `benchmark/benchmark-deploy.sh:1871-1875` | `BENCH_DEPLOY_RESULT` is printed after a drain wait of at most 10 s. A copier still draining writes to the same terminal, so later lines can follow the "last" line. | Accept this as is, or keep waiting while the copier still reads. |
| N8 | NIT | `benchmark/benchmark-teardown.sh:222` | The credential check passes on a cached access token, which can still need a reauth refresh mid-pull. The stop file covers that case. | Keep D5's "token refresh before each segment" step, right before the teardown. |
| N9 | NIT | `benchmark/tests/test_pull_logs.py:51-58` | The SHIM's stand-in `tn_iap_fault_kind` (used "until U-H6 lands") is now dead code, because devnet-lib defines the function. It already had to be edited by hand to follow devnet-lib's new reauth pattern (17:45), and it will drift again. | Drop the stand-in and rely on `source "${DEVNET_LIB}"`. |

Checked and found sound (no finding):
- **(2) `bench_pull_stream`**:
  - Every attempt writes a fresh `mktemp <out>.aXXXXXX`, with `TN_IAP_RETRIES=0` on both the cmd and the
    stdin path.
  - Checks before the rename: `gzip -t` plus a non-empty first byte for gz; `tar -tf` plus 1024 zero bytes
    at the end for tar. `mv` runs only after the check.
  - A cut stream that still returns rc 0 is retried as a transport fault.
  - rc semantics 0/1/2/3 and the stop file are implemented as specified.
  - No temp file survives, on either side.
- **(3) Deploy outputs and fds**:
  - `exec 5>&1 6>&2` runs before the redirect into the FIFO.
  - Every tunnel-spawning call runs with `5>&- 6>&-`: steps 10, 11 and 13, `prom_window_wait`,
    blast fund/run/collect, and the teardown. No root driver detaches a child.
  - `bench_die`, `set -e`, TERM, HUP and INT all reach the EXIT trap (checked on bash 5.3).
  - A dry run prints no result line, and `--note` exits before the log starts.
- **(4) Zone fallback**:
  - Stockout detection folds whitespace before matching.
  - At most 3 rounds; `zones.env` is written atomically (mktemp + mv) and config.sh checks the zone count.
  - `zones_used` is always recorded. create-instances skips instances that already exist.
  - A non-stockout failure dies (cwd caveat in S2). `BENCH_RUN_ID` is exported, so child drivers read
    `zones.env`.
- **(5) Prometheus window**:
  - `--start`/`--end` are passed only after a wait; `end_reason` takes the four contract values.
  - The collector's `resolve_window` lets each flag win alone, and `parse_ts` accepts jq's `todate` output.
- **(6) Chaos schedule refresh**:
  - Guard `t_kill - now > GUARD + STAGE` and the projected-start guard; one refresh only.
  - `.chaos_schedule_refresh` keys match the contract; `kill_extra` is rewritten in do_run's scope.
  - Both chaos sessions and `chaos_do` pin `TN_IAP_RETRIES=0`; the kill action label matches the step-15
    regex.
- **(7) Parallel node steps**:
  - jobs=1 keeps the inline, byte-identical loop.
  - jobs>1 prints outputs in fleet order, applies the spooled `node_startup` records in order, and dies
    after all nodes. Locals are visible to `step9_node_check` through dynamic scope.
- **(8) Pre-start 7a/7b**:
  - `.bak` is kept or written; a marked file without a `.bak` fails.
  - `tn_write_root_file DEST MODE` matches `tn-node-deployment/lib/common.sh:564` at `TN_NODE_SCRIPTS_REF`
    d9446f7, fed by a here-string.
  - `DEFAULT_LOG_DIR` and `TN_LOG_GROUP` are read through `tnlib eval`, and the placeholders are checked
    gone. A failed `logrotate -d` triggers `fail` before any start; real logrotate 3.22 rejects a bad size
    in the test.
  - `PRECFG_OK` matches the contract string exactly. v2's `setup-node.sh:1911` calls
    `tn_install_logrotate` without a size, so the bench file is kept.
- **(9) Tunnel supervisor**:
  - The heredoc is quoted and `$0` is `tn-bench-tunnel-supervisor` (`TUNNEL_PAT` matches).
  - It gives up after the consecutive-failure limit, the `MIN_UP` reset works, and it exits on
    "not found".
  - `tunnel.log` is appended with `>>`. The teardown kills it by group before any delete.
- **(10) Admission**: `ADM_WARN` and `admission_denied_check` are never fatal, and `_bench_adm_kv` always
  returns 0 under `set -e`. The default is 0 only under trust-everywhere.
- **(11) Report**:
  - The provenance D20 check reads `instances[]` roles validator/observer.
  - `_NODE_LOG_RE` parses plain and stamped rotated names and leaves `.logspan` out.
  - `best_window_mean` returns None below the width; no caller or site build needs that KPI to be present.
  - `run_times` ends at `teardown_done`.
- **(12) Cross-unit contracts**:
  - pull-lib ↔ bench-lib: skip-name forms, rc values, the `.logspan` path.
  - bench-lib ↔ teardown: `LOGCOV` on stdout, `due` as unix seconds and `end` via `fromdateiso8601`
    (blast writes `bench_now_iso` Z form).
  - `PRECFG_OK` fields ↔ `prestart_node`; `KEYGEN_DONE` ↔ `keygen_record`.
  - Every root-driver knob that config.sh exports is read by its driver. Secrets are never on argv.

## Defect closure (followups.md 900-983, plus the D3 item numbers)

- **D19** (pull every generation, coverage gate, logrotate size, read all generations): closed in code.
  - Done: the span plus rotated pulls; the `LOGCOV` gate between certification and the local gate; 20G
    bench logrotate with no `maxsize`; certification glob `*-unit-stdout*.log.gz`; step 9 `ufgen`
    (UF, .1, .2.gz); provenance regex.
  - Still open: B1 (fail-open on a missing span) and S1 (wiring untested).
- **Retry-corruption** (`_tn_iap_retry` concatenation): closed for every node-log pull (`bench_pull_stream`;
  its mutants are killed). The recovery-evidence pull stays outside it but fails closed (N3).
- **D9** tunnel supervisor give-up plus test: closed.
- **D10** `tunnel.log` truncated: closed (`>>`, one start line per start).
- **D11** plan text: closed (one line per mode, in bench_tunnel_up and the deploy plan).
- **D12** silent Monitors: closed for every exit after the log starts. Partly open for earlier exits (S4).
- **D13** `.bak` convention: closed.
- **D15** per-line timestamps and `--note`: closed.
- **D16** keygen clone cost: partly closed, as planned. It is now measured (`keygen_timing`,
  `logs/keygen-*.log`); the clone itself is unchanged.
- **D1** stockout fallback: closed (cwd caveat in S2).
- **D8** serial loops: closed for deploy steps 7/9 (`BENCH_NODE_JOBS=4`). The finalize, keygen and
  network-config jobs are review A's.
- **D20** startup provenance with `starts=0`: closed.
- **D21** `teardown_start` overwritten: closed.
- **D22** serial deletes: closed (`--async` plus a poll; N5).
- **D4/D5, D6, D7, D2/D17**: root drivers, review A. This review only checked that the config knobs reach
  those drivers.
- **D3**: fixed earlier (7855f63).
- **F9** (bench.invalid RPC): harness side closed (`KEYGEN_RPC_ADVERTISE=internal-ip`); the keygen code is
  review A's.
- **F10** (observer trusted only by v01): harness side closed (`NETCFG_TRUST_OBSERVERS_EVERYWHERE=1`,
  `BENCH_ADMISSION_DENIED_MAX=0`, `ADM_WARN`); the network-config code is review A's.
- **Report tooling, `kpis.recovery()` first transient promotion**: already closed at HEAD (71adae4, "a
  rejoin must hold to the end of the metrics window").
- **Prometheus collection ended before the rejoin (item 24)**: partly closed (S3).
- **27** boundary refresh: closed.
- **30** cert glob: closed.
- **31b** reauth sentinel and token check: closed. Credentials are checked first; the stop file is read
  after the pull and after the snapshots, and the teardown exits with the login hint.
- **32-34** (U-H2): the numbered list itself was not found. These were verified: no new snapshot when a
  vouched cert-fail snapshot exists, `BENCH_TEARDOWN_SKIP_ANALYSIS`, and sources named on the
  cert-failure lines.
- **38/39/40** (D20, `best_window_mean`, `run_times`): closed.
- **params-apply / pre-start marker convention**: closed (7a).
