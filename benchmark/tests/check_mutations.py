"""Reject thirty-four broken code paths in checked temporary copies of the source.

Each case copies the files its test module needs into a fresh temporary tree laid out like the repo
(<tmp>/<tree>/config.sh, <tmp>/<tree>/benchmark/...), since the tests find their scripts and
fixtures relative to their own location. The target test must pass on an unmutated tree (so a
rejection is the mutation's doing, not a broken copy), and fail at an assertion on a second tree
carrying the mutation; a mutated shell script must still pass `bash -n`.

No __pycache__ is copied and the tests run with PYTHONDONTWRITEBYTECODE=1: a mutant of a .py file
that keeps its size, written within the second its original was, would otherwise load the
original's cached bytecode and pass. Every case runs; the summary names each one's result, and the
exit status is 1 when any case was not killed.
"""
from pathlib import Path
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile

repo = Path(__file__).resolve().parents[2]
SUBMODULES = ("common/", "tn-node-deployment/")

# What each test module reads besides itself, relative to the repo root (directories recurse). A path
# inside a submodule (SUBMODULES) is copied when it is there and skipped when the submodule is not
# checked out (CI's checkout fetches none); the tests that read one skip or fall back without it.
# bench-lib.sh sources benchmark/pull-lib.sh and benchmark/obs-lib.sh (it refuses to load without either),
# so every suite that copies it copies both.
suites = {
    "test_recovery": ("benchmark/recovery-schedule.py", "benchmark/recovery-lib.sh",
                      "benchmark/node-sampler.sh", "benchmark/benchmark-blast.sh",
                      # the chaos kill runs through devnet-lib's real IAP wrappers
                      "devnet-lib.sh"),
    "test_report_windows": ("benchmark/report/windows.py", "benchmark/tests/fixtures/report"),
    "test_report_scrub": ("benchmark/report/scrub.py", "benchmark/tests/fixtures/report"),
    "test_propose_latency": ("benchmark/tools/propose-latency.py",),
    # test_node_image.TREE (copied from the repo root into each sandbox) plus its fixtures.
    "test_node_image": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                        "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                        "benchmark/benchmark-deploy.sh", "benchmark/node-sampler.sh",
                        "benchmark/node-image-contract.txt", "benchmark/tests/fixtures/node-image",
                        "benchmark/tests/fixtures/v2-node", "benchmark/consensus-parameters.yaml",
                        "benchmark/benchmark-blast.sh",
                        # test_node_image.OBS_BUNDLE: the bench-obs bundle; the startup script and the
                        # dashboards come from fixtures/node-image (no submodule needed)
                        "benchmark/obs"),
    "test_admission_gate": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                            "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                            "benchmark/report/scrub.py", "benchmark/tests/fixtures/admission"),
    # The gate's real validator (devnet-network-config.py) runs on U-H9's fleet in TrustEverywhereTests.
    "test_finalize_modes": ("devnet-finalize.sh", "devnet-lib.sh", "devnet-network-config.py",
                            "benchmark/tests/fixtures/finalize", "benchmark/tests/fixtures/network-config/fleet"),
    # The library comes from the submodule's working tree; without it the module skips itself.
    "test_v2_launch_edit": ("benchmark/tests/fixtures/v2-node", "tn-node-deployment/lib"),
    # --from-config sources benchmark/config.sh, which sources the root config.sh.
    "test_params_apply": ("benchmark/tools/params-apply.sh", "benchmark/tests/fixtures/params-apply",
                          "benchmark/consensus-parameters.yaml", "benchmark/config.sh", "config.sh"),
    # test_teardown_local_gate.TREE (the teardown runs in a copy) plus its fixtures and the curl stub;
    # benchmark-deploy.sh is read by a source test.
    "test_teardown_local_gate": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                                 "benchmark/pull-lib.sh", "benchmark/obs-lib.sh", "benchmark/benchmark-teardown.sh",
                                 "benchmark/benchmark-deploy.sh",
                                 "benchmark/recovery-lib.sh", "benchmark/tools/cert-rate.py",
                                 "benchmark/tools/block-rate.py", "benchmark/tests/fixtures/teardown",
                                 "benchmark/tests/fixtures/node-image/stub-curl-forbidden.sh"),
    "test_certification": ("benchmark/bench-lib.sh", "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                           "benchmark/benchmark-teardown.sh",
                           "benchmark/benchmark-blast.sh", "benchmark/config.sh", "benchmark/tools/cert-rate.py",
                           "benchmark/tests/fixtures/certification", "benchmark/tests/fixtures/teardown"),
    "test_collect_retry": ("benchmark/bench-lib.sh", "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                           "benchmark/tests/fixtures/teardown"),
    "test_report_kpis": ("benchmark/report/kpis.py", "benchmark/report/windows.py",
                         "benchmark/tests/fixtures/report"),
    "test_report_provenance": ("benchmark/report/provenance.py", "benchmark/tests/fixtures/provenance"),
    "test_pull_logs": ("benchmark/pull-lib.sh", "devnet-lib.sh", "benchmark/tests/fixtures/pull",
                       "benchmark/report/provenance.py"),
    # The bench-obs INDEX test loads the real bench-lib.sh in a copy of the scripts it sources; the
    # fixtures carry the HEAD baseline (baseline-28c7623.sh) the byte-identity tests compare against.
    "test_tunnel": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                    "benchmark/pull-lib.sh", "benchmark/obs-lib.sh", "benchmark/benchmark-teardown.sh",
                    "benchmark/tests/fixtures/tunnel"),
    # test_obs.TREE (copied into each sandbox) plus the fakes; the scopes test skips itself without common/.
    "test_obs": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                 "benchmark/pull-lib.sh", "benchmark/obs-lib.sh", "benchmark/obs", "benchmark/tests/fixtures/obs"),
    # The driver runs against fixtures/log-filter/config.sh (CONFIG_FILE), never the root config.sh; the
    # session-script tests that need tn-node-deployment/lib skip themselves without it.
    "test_log_filter": ("devnet-log-filter.sh", "devnet-lib.sh", "benchmark/tests/fixtures/log-filter"),
    "test_iap_retry": ("devnet-lib.sh", "benchmark/tests/fixtures/iap-retry"),
    "test_keygen": ("devnet-keygen.sh", "devnet-lib.sh", "benchmark/tests/fixtures/keygen"),
    "test_network_config": ("devnet-network-config.sh", "devnet-network-config.py", "devnet-lib.sh",
                            "benchmark/tests/fixtures/network-config"),
}

# Long anchors, each one line of its file verbatim; the mutants below change one piece of it.
TUNNEL_GIVE_UP = ('    [ "${fails}" -lt "${BENCH_TUNNEL_MAX_FAILS:-5}" ] || { echo "tunnel: giving up after ${fails} '
                  'consecutive failures at $(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit 1; }')
STOCKOUT_ONLY = ('bench_is_stockout "$(cat "${clog}")" || bench_die "${name}: create failed for another reason '
                 'than a stockout (${clog})"')
ZONES_COUNT = ('[ "${#_bench_zarr[@]}" -eq "${#INSTANCE_NAMES[@]}" ] || { echo "❌ benchmark/config.sh: '
               '${BENCH_RESULTS_DIR}/zones.env lists ${#_bench_zarr[@]} zone(s), INSTANCE_NAMES has '
               '${#INSTANCE_NAMES[@]}." >&2; exit 1; }')
CHAOS_SESSION = ('    out="$(TN_IAP_RETRIES=0 tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}" | tee -a '
                 '"${BENCH_RESULTS_DIR}/chaos-remote.log")" || rc=$?')
ROTATED_PULL = ('        [ "${r}" -le 1 ] || echo "      ✗ ${inst}: rotated unit logs: not all pulled (rc ${r})" >&2\n'
                '        _bench_pull_rc "${r}"\n')
OBS_RUN_MATCH = ('        if ! printf \'%s\' "${j}" | jq -e --arg run "${BENCH_RUN_ID}" \'(.tags.items // []) == ["bench-obs"] '
                 'and .labels.benchmark == "1" and .labels["bench-run"] == $run\' >/dev/null; then')
OBS_MEM_ABORT = ('                record_abort "obs-memory" "${BENCH_OBS_INSTANCE}" "${BENCH_OBS_INSTANCE} memory ${mem}% > '
                 '${BENCH_ABORT_OBS_MEM_PCT}%"')
OBS_GATE_ROW = ('[ "${OBS_UP}" -ne 1 ] || GATE_IDS="${GATE_IDS}${OBS_CAND} $(inst_id "${OBS_CAND%% *}" '
                '"${OBS_CAND#* }")"$\'\\n\'\n')
REAUTH = ('    grep -Eq -- "${TN_IAP_REAUTH_PAT:-Reauthentication failed|There was a problem refreshing your '
          'current auth tokens|invalid_grant}" "$2" && { echo reauth; return 0; }')

cases = [
    ("benchmark/recovery-schedule.py",
     'first_kill = info["epoch_start_unix"] + duration - before_close',
     "first_kill = earliest_kill + duration - before_close",
     "test_recovery.ScheduleTests.test_snapshot_pins_registry_read_and_resolves_closing_block"),
    ("benchmark/recovery-lib.sh", "else (($counts[$node] // 0) + 1)", "else 0",
     "test_recovery.WatcherTests.test_one_frozen_validator_while_peers_advance"),
    ("benchmark/node-sampler.sh", 'block="$(block_number)"', 'block=""',
     "test_recovery.SamplerTests.test_csv_upgrade_block_capture_and_minute_inventory"),
    ("benchmark/recovery-lib.sh", '! tar -tzf "${temporary}" >/dev/null', "false",
     "test_recovery.EvidenceTests.test_archive_bytes_preserved_and_invalid_stream_rejected"),
    # The merged window ends at the last generator's end, not the first one's.
    ("benchmark/report/windows.py", 'end = max(w["end_unix"] for w in mixed)',
     'end = min(w["end_unix"] for w in mixed)',
     "test_report_windows.WindowTests.test_merged_and_all_generators_differ"),
    # Step 9 accepts any boot sha.
    ("benchmark/benchmark-deploy.sh", '"${w_sha}"?*|"${w_sha}") ;;', "*) ;;",
     "test_node_image.Step9Tests.test_wrong_sha_on_first_node_stops_the_fleet"),
    # 10.x.y.z is no longer a private address.
    ("benchmark/report/scrub.py", '"' + "10." + '0.0.0/8", ', "",   # split: the hygiene test bans the literal
     "test_report_scrub.ScanTextTests.test_ten_slash_eight_is_private_ip"),
    # A line found in two files of a node counts twice.
    ("benchmark/tools/propose-latency.py", "if key in self._seen:", "if False:",
     "test_propose_latency.ProposeLatencyTests.test_one_node_over_overlapping_files_counts_each_event_once"),
    # Any admission mode reads as Closed, not just 2.
    ("benchmark/bench-lib.sh", '_bench_adm_closed(){ [ "${1:-}" = 2 ]; }', '_bench_adm_closed(){ [ -n "${1:-}" ]; }',
     "test_admission_gate.VerdictTests.test_grace_worker_is_not_closed"),
    # --stage-only no longer stops a node after finalize (the literal only: the line stays valid bash).
    ("devnet-finalize.sh", '_defer_stop "${inst}" "${zone}"', "true",
     "test_finalize_modes.StageOnlyTests.test_stage_only_stops_each_node_after_finalize"),
    # The legacy wrapper wins over the v2 start script when a node has both.
    ("benchmark/tools/params-apply.sh",
     'if [ -f "$START" ]; then L="$START"; elif [ -f "$LEGACY" ]; then L="$LEGACY"; fi',
     'if [ -f "$LEGACY" ]; then L="$LEGACY"; elif [ -f "$START" ]; then L="$START"; fi',
     "test_params_apply.LayoutTests.test_the_v2_start_script_is_read_when_both_launch_files_exist"),
    # Bench 4. A pull lands a cut gzip stream instead of retrying it.
    ("benchmark/pull-lib.sh", 'if ! gzip -t -- "${tmp}" 2>/dev/null; then', "if false; then",
     "test_pull_logs.StreamTests.test_partial_first_attempt_is_discarded_and_retried"),
    # The coverage gate passes a log whose first line comes after the coordinated start.
    ("benchmark/pull-lib.sh", '[ "${first_n}" -le "${due_n}" ] && [ "${last_n}" -ge "${end_n}" ] && ok=1', "ok=1",
     "test_pull_logs.CoverageTests.test_a_first_line_after_due_fails_the_gate"),
    # The tunnel supervisor never gives up.
    ("benchmark/bench-lib.sh", TUNNEL_GIVE_UP, TUNNEL_GIVE_UP.replace('"${BENCH_TUNNEL_MAX_FAILS:-5}" ]', "999999 ]"),
     "test_tunnel.SupervisorTests.test_gives_up_after_max_fails"),
    # A rotated unit log counts as a saved container log.
    ("benchmark/bench-lib.sh", "            unit-stdout.rotated-*.log.gz) ur=$((ur + 1)) ;;",
     "            unit-stdout.rotated-*.log.gz) saved=$((saved + 1)) ;;",
     "test_certification.CertificationTests.test_rotated_unit_logs_are_listed_for_a_failing_validator"),
    # The teardown deletes the fleet although a node's pulled log does not cover the run.
    ("benchmark/benchmark-teardown.sh", 'if [ "${cov_bad}" -gt 0 ] && [ "${SKIP_COVERAGE}" != "1" ]; then',
     "if false; then",
     "test_teardown_local_gate.TeardownLocalGateTests.test_coverage_short_log_stops_before_any_delete"),
    # A failed deploy's result line, status file and manifest lose its first error.
    ("benchmark/benchmark-deploy.sh", "first_error=\"$(grep -m1 -F '❌' \"${f}\" 2>/dev/null | cut -c1-300)\"",
     'first_error=""',
     "test_node_image.FleetCase.test_result_line_status_file_and_manifest_on_failure"),
    # A create failure that is not a stockout moves the node to a fallback zone instead of stopping.
    ("benchmark/benchmark-deploy.sh", STOCKOUT_ONLY,
     STOCKOUT_ONLY.replace('bench_is_stockout "$(cat "${clog}")"', "true"),
     "test_node_image.ZoneFallbackTests.test_a_non_stockout_failure_still_stops"),
    # config.sh takes a zones.env whose zone count differs from INSTANCE_NAMES.
    ("benchmark/config.sh", ZONES_COUNT,
     ZONES_COUNT.replace('[ "${#_bench_zarr[@]}" -eq "${#INSTANCE_NAMES[@]}" ]', "true"),
     "test_node_image.ConfigTests.test_zones_env_is_validated"),
    # The refreshed kill lands after the closing epoch's end instead of before it.
    ("benchmark/recovery-schedule.py", '    kill = info["epoch_start_unix"] + info["duration_secs"] - before_close',
     '    kill = info["epoch_start_unix"] + info["duration_secs"] + before_close',
     "test_recovery.ScheduleTests.test_refresh_uses_the_opened_epochs_start"),
    # The chaos kill session is retried on a transport fault (it could run twice).
    ("benchmark/benchmark-blast.sh", CHAOS_SESSION, CHAOS_SESSION.replace("TN_IAP_RETRIES=0", "TN_IAP_RETRIES=2"),
     "test_recovery.ChaosTimingTests.test_chaos_sessions_never_retry_the_transport"),
    # An expired gcloud login is retried as a transport fault instead of being named.
    ("devnet-lib.sh", REAUTH, "    false && { echo reauth; return 0; }",
     "test_iap_retry.ReauthTests.test_reauth_is_not_retried_and_named"),
    # An unresolvable internal IP aborts the whole finalize under set -e instead of failing that node.
    ("devnet-finalize.sh", '    intIP="$(tn_node_int_ip "${inst}" "${zone}")" || intIP=""',
     '    intIP="$(tn_node_int_ip "${inst}" "${zone}")"',
     "test_finalize_modes.StageOnlyTests.test_unresolvable_internal_ip_fails_that_node_only"),
    # Keygen reuses a node keyed for another validator address.
    ("devnet-keygen.sh", '[ "${have_addr}" = "${addr}" ] && [ "${have_info}" = 1 ] || return 1', "true || return 1",
     "test_keygen.ReuseTests.test_reuse_refuses_another_address"),
    # --trust-observers-everywhere no longer makes a validator trust every observer.
    ("devnet-network-config.py", "        if self.trust_everywhere and name in self.validators:",
     "        if False and self.trust_everywhere and name in self.validators:",
     "test_network_config.TrustTests.test_observer_is_trusted_by_every_validator_with_the_flag"),
    # NETCFG_FAST writes a network-config that has not changed.
    ("devnet-network-config.sh", '    if cmp -s "${merged}" "${existing}"; then', "    if false; then",
     "test_network_config.FastTests.test_unchanged_file_is_read_once_and_not_written"),
    # A listed node without a start line passes the provenance check.
    ("benchmark/report/provenance.py", "    for inst in sorted(expected_instances - started):",
     "    for inst in sorted(set()):",
     "test_report_provenance.CheckTests.test_a_listed_node_without_a_start_is_a_problem"),
    # A node whose rotated unit logs did not all land still gets a marker (the status is printed, not
    # folded into the node's result). Also killed by
    # test_certification.NodePullTests.test_a_failed_rotated_pull_fails_the_node.
    ("benchmark/bench-lib.sh", ROTATED_PULL, ROTATED_PULL.split("\n")[0] + "\n",
     "test_teardown_local_gate.TeardownLocalGateTests.test_a_failed_rotated_pull_leaves_no_marker_and_deletes_nothing"),
    # Bench 4, obs wave. An existing bench-obs VM tagged as a node passes the ownership check, so the
    # bench would adopt a VM it did not create.
    ("benchmark/obs-lib.sh", OBS_RUN_MATCH, OBS_RUN_MATCH.replace('== ["bench-obs"]', '== ["bench-node"]'),
     "test_obs.ExistingVmTests.test_a_vm_of_another_run_is_refused"),
    # Step 8 restarts every node's Alloy although bench-obs does not answer its ready probe.
    ("benchmark/benchmark-deploy.sh",
     'curl -sf --max-time 5 "http://${ip}:9090/-/ready" >/dev/null || fail "bench-obs unreachable"',
     'curl -sf --max-time 5 "http://${ip}:9090/-/ready" >/dev/null || true',
     "test_node_image.ObsScriptTests.test_unreachable_obs_fails_before_alloy_restarts"),
    # A Prometheus query goes through the Grafana proxy (and reads its admin secret) by default.
    ("benchmark/bench-lib.sh", '    if [ "${BENCH_PROM_AUTH:-0}" = 0 ]; then', '    if [ "${BENCH_PROM_AUTH:-0}" = 1 ]; then',
     "test_tunnel.PromQueryTests.test_no_auth_path_never_reads_a_secret"),
    # The log-filter sweep moves on to the next node after one was deferred or failed.
    ("devnet-log-filter.sh", '    [ "${st}" = ok ] || { lf_stop "${k}"; break; }',
     '    true || [ "${st}" = ok ] || { lf_stop "${k}"; break; }',
     "test_log_filter.SweepTests.test_a_deferred_node_stops_the_sweep"),
    # The obs-memory abort names obs-devnet's instance variable instead of bench-obs.
    ("benchmark/benchmark-blast.sh", OBS_MEM_ABORT,
     OBS_MEM_ABORT.replace('"${BENCH_OBS_INSTANCE}"', '"${OBS_INSTANCE_NAME}"', 1),
     "test_recovery.BenchObsTests.test_obs_memory_abort_records_the_bench_obs_instance"),
    # bench-obs never gets a gate row, so the teardown leaves the run's metrics VM running.
    ("benchmark/benchmark-teardown.sh", OBS_GATE_ROW, "",
     "test_teardown_local_gate.TeardownLocalGateTests.test_bench_obs_is_deleted_after_the_gate"),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def build(tree, module):
    """Copy <module>'s test file and everything it reads into <tree>, in the repo's layout."""
    for rel in suites[module] + ("benchmark/tests/%s.py" % module,):
        source = repo / rel
        if rel.startswith(SUBMODULES) and not source.exists():
            continue
        files = sorted(p for p in source.rglob("*") if p.is_file()) if source.is_dir() else [source]
        for path in files:
            if "__pycache__" in path.parts:
                continue
            target = tree / path.relative_to(repo)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if digest(path) != digest(target):
                raise RuntimeError(f"source changed while copying {path.relative_to(repo)}")


def run(tree, test, timeout=900):
    """Run one test in <tree>, in a session of its own: whatever it leaves running is killed after."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen(["python3", "-m", "unittest", "-v", test], cwd=tree / "benchmark" / "tests", env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        stderr += f"\n(killed after {timeout} s)"
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def tail(text, lines=40):
    return "\n".join(text.rstrip("\n").splitlines()[-lines:])


def check(name, original, mutant, test):
    """(result, detail): result is killed, survived, broken (the test fails unmutated), anchor (the
    original is not in the file exactly once) or syntax (the mutant is not valid bash)."""
    module, _, label = test.partition(".")
    with tempfile.TemporaryDirectory(prefix="benchmark-mutation-") as directory:
        pristine, mutated = Path(directory) / "pristine", Path(directory) / "mutated"
        build(pristine, module)
        result = run(pristine, test)
        if result.returncode != 0:
            return "broken", f"{label} fails without the mutation:\n{tail(result.stderr)}"
        build(mutated, module)
        target = mutated / name
        text = target.read_text(encoding="utf-8")
        if text.count(original) != 1:
            return "anchor", f"the original is in {name} {text.count(original)} times, not once"
        target.write_text(text.replace(original, mutant), encoding="utf-8")
        if name.endswith(".sh"):
            syntax = subprocess.run(["bash", "-n", str(target)], capture_output=True, text=True)
            if syntax.returncode != 0:
                return "syntax", f"mutated {name} is not valid bash:\n{tail(syntax.stderr)}"
        result = run(mutated, test)
        if result.returncode == 0 or "AssertionError" not in result.stderr:
            return "survived", f"{label} did not reject the mutation at its assertion:\n{tail(result.stderr)}"
    return "killed", ""


def main():
    results = []
    for name, original, mutant, test in cases:
        outcome, detail = check(name, original, mutant, test)
        label = test.partition(".")[2]
        print(label + (": mutation rejected by assertion" if outcome == "killed" else f": {outcome}: {detail}"),
              flush=True)
        results.append((outcome, name, test))
    killed = sum(1 for outcome, _, _ in results if outcome == "killed")
    print(f"\n{killed} of {len(results)} mutations killed")
    for outcome, name, test in results:
        print(f"  {outcome:<9} {name:<34} {test}")
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
