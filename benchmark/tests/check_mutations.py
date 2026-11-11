"""Reject known-broken code paths, one per case below, in checked temporary copies of the source.

Each case copies the files its test module needs into a fresh temporary tree laid out like the repo
(<tmp>/<tree>/config.sh, <tmp>/<tree>/benchmark/...), since the tests find their scripts and
fixtures relative to their own location. The target test must pass on an unmutated tree (so a
rejection is the mutation's doing, not a broken copy), and fail at an assertion on a second tree
carrying the mutation; a mutated shell script must still pass `bash -n`.

No __pycache__ is copied and the tests run with PYTHONDONTWRITEBYTECODE=1: a mutant of a .py file
that keeps its size, written within the second its original was, would otherwise load the
original's cached bytecode and pass. Every case runs; the summary names each one's result, and the
exit status is 1 when any case was not killed.

usage: check_mutations.py [--list] [--modules a,b] [--jobs <n>]
--list prints the selected cases and runs nothing; --modules keeps the cases whose test is in one of the
named modules (test_x or x); --jobs checks that many cases at a time, each in trees of its own (the
per-case lines and the summary keep the case order). benchmark/tests/gate.sh runs it after the suite.
"""
import argparse
import concurrent.futures
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
# test_node_image.TREE (copied from the repo root into each sandbox) plus its fixtures. Bench 6 adds the switch
# table and the arm files (H0, H3), the frozen persist headers (H0), the arm tool deploy step 7 runs with
# --print-state, the persist sampler with its folio census (H3) and provenance.py, which a source test reads.
NODE_IMAGE = ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
              "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
              "benchmark/benchmark-deploy.sh", "benchmark/node-sampler.sh",
              "benchmark/node-image-contract.txt", "benchmark/tests/fixtures/node-image",
              "benchmark/tests/fixtures/v2-node", "benchmark/consensus-parameters.yaml",
              "benchmark/benchmark-blast.sh",
              # test_node_image.OBS_BUNDLE: the bench-obs bundle; the startup script and the
              # dashboards come from fixtures/node-image (no submodule needed)
              "benchmark/obs",
              "benchmark/arms", "benchmark/tools/persist-csv-header.txt", "benchmark/tools/folio-census-header.txt",
              "benchmark/tools/params-apply.sh", "benchmark/node-persist-sampler.sh", "benchmark/tools/folio-census.py",
              "benchmark/report/provenance.py", "common/create-instances.sh")
# test_host_probe imports test_node_image (its BashCase and TREE); test_params_apply imports test_host_probe.
HOST_PROBE = NODE_IMAGE + ("benchmark/tests/test_node_image.py", "benchmark/tests/fixtures/host-probe")
suites = {
    "test_recovery": ("benchmark/recovery-schedule.py", "benchmark/recovery-lib.sh",
                      "benchmark/node-sampler.sh", "benchmark/benchmark-blast.sh",
                      # the chaos kill runs through devnet-lib's real IAP wrappers
                      "devnet-lib.sh"),
    "test_report_windows": ("benchmark/report/windows.py", "benchmark/tests/fixtures/report"),
    "test_report_scrub": ("benchmark/report/scrub.py", "benchmark/tests/fixtures/report"),
    "test_propose_latency": ("benchmark/tools/propose-latency.py",),
    "test_node_image": NODE_IMAGE,
    "test_admission_gate": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                            "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                            "benchmark/report/scrub.py", "benchmark/tests/fixtures/admission"),
    # The gate's real validator (devnet-network-config.py) runs on U-H9's fleet in TrustEverywhereTests.
    "test_finalize_modes": ("devnet-finalize.sh", "devnet-lib.sh", "devnet-network-config.py",
                            "benchmark/tests/fixtures/finalize", "benchmark/tests/fixtures/network-config/fleet"),
    # The library comes from the submodule's working tree; without it the module skips itself.
    "test_v2_launch_edit": ("benchmark/tests/fixtures/v2-node", "tn-node-deployment/lib"),
    # --from-config sources benchmark/config.sh, which sources the root config.sh. Bench 6: the arm files and the
    # switch table (H5a), the report modules a manifest test loads, cert-rate.py, and the host-step functions the
    # hook reads out of bench-lib.sh by name (H5b), through test_host_probe.
    "test_params_apply": HOST_PROBE + ("benchmark/tools/params-apply.sh", "benchmark/tests/fixtures/params-apply",
                                       "benchmark/report", "benchmark/tools/cert-rate.py",
                                       "benchmark/tests/test_host_probe.py"),
    # test_teardown_local_gate.TREE (the teardown runs in a copy) plus its fixtures and the curl stub;
    # benchmark-deploy.sh and benchmark-blast.sh are read by source tests. Bench 6 (H6a): the log prefilter's
    # shapes, the archive tools and provenance.py.
    "test_teardown_local_gate": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                                 "benchmark/pull-lib.sh", "benchmark/obs-lib.sh", "benchmark/benchmark-teardown.sh",
                                 "benchmark/benchmark-deploy.sh", "benchmark/benchmark-blast.sh",
                                 "benchmark/recovery-lib.sh", "benchmark/tools/cert-rate.py",
                                 "benchmark/tools/block-rate.py", "benchmark/tools/log-shapes.txt",
                                 "benchmark/tools/archive-run.sh", "benchmark/tools/archive-verify.py",
                                 "benchmark/report/provenance.py", "benchmark/tests/fixtures/teardown",
                                 "benchmark/tests/fixtures/node-image/stub-curl-forbidden.sh"),
    "test_certification": ("benchmark/bench-lib.sh", "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                           "benchmark/benchmark-teardown.sh",
                           "benchmark/benchmark-blast.sh", "benchmark/config.sh", "benchmark/tools/cert-rate.py",
                           "benchmark/tests/fixtures/certification", "benchmark/tests/fixtures/teardown"),
    "test_collect_retry": ("benchmark/bench-lib.sh", "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                           "benchmark/tests/fixtures/teardown"),
    # BundleFloorTests load make_bundle.py, which imports provenance.py and scrub.py beside it.
    "test_report_kpis": ("benchmark/report/kpis.py", "benchmark/report/windows.py",
                         "benchmark/report/make_bundle.py", "benchmark/report/provenance.py",
                         "benchmark/report/scrub.py", "benchmark/tests/fixtures/report"),
    # Bench 6 (H7a): the switch check reads arms/switches.tsv.
    "test_report_provenance": ("benchmark/report/provenance.py", "benchmark/tests/fixtures/provenance",
                               "benchmark/arms"),
    # make_bundle.py imports kpis.py, provenance.py, scrub.py and windows.py beside it.
    "test_report_bundle": ("benchmark/report/make_bundle.py", "benchmark/report/kpis.py",
                           "benchmark/report/windows.py", "benchmark/report/provenance.py",
                           "benchmark/report/scrub.py", "benchmark/tests/fixtures/report",
                           # Bench 6 (H7a): the prestart arm row and the switch provenance read arms/switches.tsv.
                           "benchmark/arms"),
    # The fleet tests cut bench-lib.sh's pull functions and the teardown's pull call site out by name.
    # Bench 6 (H6a): the prefilter's shapes, cert-rate.py on the prefiltered logs, and the session library the
    # node-side tests source from the submodule when it is there.
    "test_pull_logs": ("benchmark/pull-lib.sh", "devnet-lib.sh", "benchmark/tests/fixtures/pull",
                       "benchmark/report/provenance.py", "benchmark/bench-lib.sh", "benchmark/obs-lib.sh",
                       "benchmark/benchmark-teardown.sh", "benchmark/tools/cert-rate.py",
                       "benchmark/tools/log-shapes.txt", "benchmark/tests/fixtures/analysis",
                       "benchmark/tests/fixtures/provenance", "tn-node-deployment/lib/common.sh"),
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
    # Bench 5. test_blast_argv.TREE (the blast driver and the startup script run in a copy) plus the goldens.
    "test_blast_argv": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                        "benchmark/pull-lib.sh", "benchmark/obs-lib.sh", "benchmark/recovery-lib.sh",
                        "benchmark/benchmark-blast.sh", "benchmark/blaster-startup.sh",
                        "benchmark/tests/fixtures/blast"),
    "test_stage_latency": ("benchmark/tools/stage-latency.py", "benchmark/tests/fixtures/stage-latency"),
    # test_txgen_probe.TREE (bench-lib.sh sourced from a copy) plus the fake docker and the help texts.
    "test_txgen_probe": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                         "benchmark/pull-lib.sh", "benchmark/obs-lib.sh", "benchmark/tests/fixtures/txgen-probe"),
    # Bench 6. H2: the host probe and host steps run from bench-lib.sh in test_node_image's sandbox.
    "test_host_probe": HOST_PROBE,
    # H4: the node-side sampler and the folio census against fake /proc trees and the frozen headers.
    "test_persist_sampler": ("benchmark/node-persist-sampler.sh", "benchmark/tools/folio-census.py",
                             "benchmark/tools/persist-csv-header.txt", "benchmark/tools/folio-census-header.txt"),
    # H6a: the archive tools run in a repo copy of their own (config.sh beside them).
    "test_archive": ("config.sh", "benchmark/tools/archive-run.sh", "benchmark/tools/archive-verify.py",
                     "benchmark/tests/fixtures/teardown/fake-gcloud.py",
                     "benchmark/tests/fixtures/teardown/stub-perl.sh"),
    # H6a: cert-rate.py on the analysis fixtures; a source test reads bench-lib.sh, an agreement test windows.py.
    "test_cert_rate": ("benchmark/tools/cert-rate.py", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh",
                       "benchmark/obs-lib.sh", "benchmark/report/windows.py", "benchmark/tests/fixtures/analysis"),
    # H7b: block-rate.py on the analysis fixtures.
    "test_block_rate": ("benchmark/tools/block-rate.py", "benchmark/tests/fixtures/analysis"),
    # H1b: the stall scan, and the blast driver's real-phase functions cut out of bench-lib.sh and the driver.
    "test_stall_scan": ("benchmark/stall-scan.py", "benchmark/tests/fixtures/stall-scan", "benchmark/benchmark-blast.sh",
                        "benchmark/bench-lib.sh", "benchmark/pull-lib.sh", "benchmark/obs-lib.sh"),
    # H7b: arms-summary.py loads the stage and cert tools, the shapes list and the persist header beside it, the
    # report's kpis.py and the switch table; the arm-window tests run block-rate.py and propose-latency.py.
    "test_arms_summary": ("benchmark/tools", "benchmark/report", "benchmark/arms", "benchmark/tests/fixtures/arms-summary",
                          "benchmark/tests/fixtures/analysis"),
    # H8: test_gate copies gate.sh beside stub modules; its --list tests run the real checker's --list.
    "test_gate": ("benchmark/tests/gate.sh", "benchmark/tests/check_mutations.py"),
    # H10: test_probe.Tree copies config.sh, devnet-lib.sh and the shell side of benchmark/ (no tests, report,
    # launch or obs); the hygiene rules come from test_repo_hygiene.py.
    "test_probe": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                   "benchmark/pull-lib.sh", "benchmark/obs-lib.sh", "benchmark/benchmark-probe.sh",
                   "benchmark/consensus-parameters.yaml",
                   "benchmark/node-persist-sampler.sh", "benchmark/tools", "benchmark/arms",
                   "benchmark/tests/test_repo_hygiene.py", "benchmark/tests/fixtures/probe"),
    # H11: the launchers, the arm files and .gitignore go into the test's own git tree (every driver is a fake);
    # a knob test reads config.sh and every top-level and tools/ shell script.
    "test_launch": ("benchmark/launch", "benchmark/arms", "benchmark/.gitignore", "benchmark/tests/fixtures/launch",
                    "benchmark/config.sh", "benchmark/bench-lib.sh", "benchmark/pull-lib.sh", "benchmark/obs-lib.sh",
                    "benchmark/recovery-lib.sh", "benchmark/benchmark-blast.sh", "benchmark/benchmark-deploy.sh",
                    "benchmark/benchmark-teardown.sh", "benchmark/benchmark-probe.sh", "benchmark/benchmark-firewall.sh",
                    "benchmark/blaster-startup.sh", "benchmark/node-sampler.sh", "benchmark/node-persist-sampler.sh",
                    "benchmark/tools"),
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
# Bench 5.
LIGHT_STOP = '        [ "${rc}" -eq 0 ] || light_stop run "${rc}" $(seq "${p}" $(( ${#LIGHT_IDX[@]} - 1 )))'
STARTUP_ARGS = ('    args+=(--nodes "${NODE_URLS}" --senders "${SENDERS}" --sender-start "${SENDER_START}" '
                '--window "${WINDOW}"')
LANDINGS_ARGS = ('    [ "${LANDINGS_SAMPLE}" = 0 ] || args+=(--landings-out "/out/landings-${LABEL}.ndjson.gz" '
                 '--landings-sample "${LANDINGS_SAMPLE}")')
DB_SYNC_FLAG = '[ -z "${dbs}" ] || printf \'setf --db.sync-mode %s\\n\' "${dbs}"'
FSYNC_PARSE = "p95_us=(0|[1-9][0-9]{0,11})$/\\1 \\2/p'"
THIS_INVOCATION = ('    elif [ "${mr}" = "${BENCH_RUN_ID}" ] && [ "${mp//[!0-9]/}" -ge "${TD_STARTED_ISO//[!0-9]/}" ]; '
                   'then echo "fresh:this-invocation"')
ARGV_FLAG_MATCH = '            grep -Eq -- "(^|[^A-Za-z0-9_-])${pat}([^A-Za-z0-9_-]|\\$)" "${help}" && continue'
BUCKET_MARKER = ('    m="$(_bench_write_marker "${dest}" "${inst}" "${id}" "${ident#* }" "${got}" ${new})" '
                 '|| return 1')
BUCKET_WAIT = '        if wait "${pids[$i]}"; then sent+=("${names[$i]}"); else failed="${failed} ${names[$i]}"; fi'
LANDINGS_PROBE = '    [ "${BENCH_LANDINGS_SAMPLE:-0}" = "0" ] || flags="${flags} --landings-out --landings-sample"'

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
    # Bench 5, U-H1. A light blast that fails no longer stops the sequence.
    ("benchmark/benchmark-blast.sh", LIGHT_STOP, '        [ "${rc}" -eq 0 ] || true',
     "test_blast_argv.SequenceTests.test_a_failed_light_blast_stops_the_sequence"),
    # The generator runs at --window 16 whatever BENCH_WINDOW says.
    ("benchmark/blaster-startup.sh", STARTUP_ARGS, STARTUP_ARGS.replace('--window "${WINDOW}"', "--window 16"),
     "test_blast_argv.WindowTests.test_window_reaches_the_generator_argv"),
    # The blasters never get the WINDOW metadata key.
    ("benchmark/benchmark-blast.sh",
     '    [ "${mode}" != blast ] || [ "${BENCH_WINDOW:-16}" = 16 ] || meta="${meta}##WINDOW=${BENCH_WINDOW}"',
     '    [ "${mode}" != blast ] || true || meta="${meta}##WINDOW=${BENCH_WINDOW}"',
     "test_blast_argv.WindowTests.test_window_reaches_the_generator_argv"),
    # LIGHT_LOAD_DONE reports a failed light blast as rc=0.
    ("benchmark/benchmark-blast.sh",
     '        [ "${LIGHT_KIND[$p]}" != light ] || [ "${BENCH_APPLY}" != "1" ] || echo "LIGHT_LOAD_DONE i=${LIGHT_IDX[$p]} rc=${rc}"',
     '        [ "${LIGHT_KIND[$p]}" != light ] || [ "${BENCH_APPLY}" != "1" ] || echo "LIGHT_LOAD_DONE i=${LIGHT_IDX[$p]} rc=0"',
     "test_blast_argv.SequenceTests.test_a_failed_light_blast_stops_the_sequence"),
    # A log rate exactly at BENCH_LOG_RATE_WARN_MB_MIN is a warning.
    ("benchmark/benchmark-blast.sh",
     '    elif awk -v m="${rate}" -v t="${BENCH_LOG_RATE_WARN_MB_MIN}" \'BEGIN { exit !(m > t) }\'; then',
     '    elif awk -v m="${rate}" -v t="${BENCH_LOG_RATE_WARN_MB_MIN}" \'BEGIN { exit !(m >= t) }\'; then',
     "test_blast_argv.LogRateTests.test_rate_at_the_threshold_is_not_a_warning"),
    # BENCH_LANDINGS_SAMPLE never reaches the generator's argv.
    ("benchmark/blaster-startup.sh", LANDINGS_ARGS, LANDINGS_ARGS.replace('[ "${LANDINGS_SAMPLE}" = 0 ]', "true"),
     "test_blast_argv.LandingsTests.test_landings_flags_only_when_sampled"),
    # Every light index runs at BENCH_WINDOW instead of its BENCH_LIGHT_WINDOWS entry.
    ("benchmark/benchmark-blast.sh", '        w="${ws[$k]:-${BENCH_WINDOW}}"; k=$((k + 1))',
     '        w="${BENCH_WINDOW}"; k=$((k + 1))',
     "test_blast_argv.LightPlanTests.test_light_blasts_then_the_configured_profile"),
    # U-H2. The pre-start script sets --db.sync-mode with the knob unset.
    ("benchmark/bench-lib.sh", DB_SYNC_FLAG,
     'printf \'setf --db.sync-mode %s\\n\' "${dbs:-durable}"',
     "test_node_image.PreStartKnobTests.test_knobs_unset_is_byte_identical_to_bench_4"),
    # A node 20-40 % over the fleet's median fsync p50 is not named slow.
    ("benchmark/bench-lib.sh", ".f.p50_us * 5 > $med * 6", ".f.p50_us * 5 > $med * 7",
     "test_node_image.FsyncProbeTests.test_summary_names_the_node_over_twenty_percent"),
    # The fsync probe's p50 and p95 are recorded swapped.
    ("benchmark/bench-lib.sh", FSYNC_PARSE, FSYNC_PARSE.replace("\\1 \\2", "\\2 \\1"),
     "test_node_image.FsyncProbeTests.test_record_from_a_session_output"),
    # U-H3a. A marker this teardown pulled is refused once its pull is older than the freshness window (D34).
    ("benchmark/benchmark-teardown.sh", THIS_INVOCATION, '    elif false; then echo "fresh:this-invocation"',
     "test_teardown_local_gate.ThisInvocationMarkerTests.test_a_marker_this_teardown_pulled_20_min_ago_is_accepted"),
    # A teardown re-run certifies again although the manifest holds the record (B9).
    ("benchmark/benchmark-teardown.sh",
     'if [ "${BENCH_TEARDOWN_RECERTIFY:-0}" != "1" ] && cert_at="$(cert_recorded_at)"; then', "if false; then",
     "test_teardown_local_gate.TeardownLocalGateTests.test_a_recorded_certification_is_not_run_again"),
    # The dry run's gcloud argv check passes a flag the SDK does not know (A10).
    ("benchmark/benchmark-teardown.sh", ARGV_FLAG_MATCH, "            continue",
     "test_teardown_local_gate.TeardownLocalGateTests.test_the_dry_run_reports_a_flag_the_sdk_does_not_know"),
    # U-H3b. The bucket transfer lands a node's logs without the marker the IAP pull writes.
    ("benchmark/pull-lib.sh", BUCKET_MARKER, '    m="${dest}/${inst}.pulled"',
     "test_pull_logs.BucketTransferTests.test_one_session_per_node_one_download_and_the_iap_pulls_files_and_markers"),
    # One node's failed upload session abandons every other node of the bucket transfer.
    ("benchmark/pull-lib.sh", BUCKET_WAIT, BUCKET_WAIT.replace('failed="${failed} ${names[$i]}"', "return 1"),
     "test_pull_logs.BucketTransferTests.test_a_node_whose_session_fails_is_recorded_and_the_others_complete"),
    # The default transfer goes through the bucket instead of bench 4's IAP pull.
    ("benchmark/benchmark-teardown.sh", '    if [ "${BENCH_LOG_TRANSFER:-iap}" = "bucket" ]; then', "    if true; then",
     "test_pull_logs.IapGoldenTests.test_the_default_transfer_is_the_bench_4_iap_pull_byte_for_byte"),
    # U-H4a. --exclude-boundaries keeps the blocks next to an epoch boundary.
    ("benchmark/tools/stage-latency.py", "        return not any(abs(float(j.ts) - b) <= bsecs for b in boundaries)",
     "        return True",
     "test_stage_latency.StageLatencyTests.test_window_filter_and_epoch_boundary_exclusion"),
    # A digest written in capitals no longer joins its batch.
    ("benchmark/tools/stage-latency.py", "    return m.group(1)[:16].lower() if m else None",
     "    return m.group(1)[:16] if m else None",
     "test_stage_latency.StageLatencyTests.test_the_digest_join_strips_0x_and_takes_16_lowercase_hex"),
    # A batch in the committing leader's own header gets no S6a (it waits for no later leader).
    ("benchmark/tools/stage-latency.py", '            j.put("S6a", 0.0, "leader_own_batch")', "            pass",
     "test_stage_latency.StageLatencyTests.test_markdown_blocks_and_max_lines"),
    # U-H4b. The corrected time to land loses the 0.5 s that the whole-second block timestamp cuts off.
    ("benchmark/report/kpis.py", 'value=lat["p50"] / 1000.0 + LAND_FLOOR_BIAS_S))', 'value=lat["p50"] / 1000.0))',
     "test_report_kpis.ComputeTests.test_all_fourteen_kpis_hand_computed"),
    # The floor KPIs lose the light blast's pooled histogram.
    ("benchmark/report/kpis.py", "hist = merge_hist([merge_hist(hs) for hs in by_type.values()])", "hist = None",
     "test_report_kpis.FloorKpiTests.test_pooled_matches_hand_computation"),
    # A light blast is read from an archive without its blasters' results.
    ("benchmark/report/windows.py", "return (full or dirs or [None])[-1]", "return (dirs or [None])[-1]",
     "test_report_kpis.LightWindowTests.test_light_blasts_from_manifest"),
    # The load blast counts as a light blast when chaos is off.
    ("benchmark/report/windows.py", 'if e.get("chaos") not in (0, False, None) or e.get("index") == top:',
     'if e.get("chaos") not in (0, False, None):',
     "test_report_kpis.LightWindowTests.test_light_blasts_from_manifest"),
    # --exclude-boundaries drops every epoch boundary's blocks, not just those inside the window.
    ("benchmark/report/windows.py", "cuts = [b for b in boundaries(docs) if span[0] - pad <= b < span[1] + pad]",
     "cuts = [b for b in boundaries(docs)]",
     "test_report_kpis.LightWindowTests.test_light_windows_sources_and_boundaries"),
    # The bundle drops the floor's caveats.
    ("benchmark/report/make_bundle.py", 'caveats = list(floor_caveats) + list(res["caveats"])',
     'caveats = list(res["caveats"])',
     "test_report_kpis.BundleFloorTests.test_kpis_step_with_the_floor"),
    # The light blast's copied files are missing from the bundle marker's input hashes.
    ("benchmark/report/make_bundle.py",
     'marker["inputs"] = (marker.get("inputs") or []) + [file_entry(p) for p in copied]',
     'marker["inputs"] = marker.get("inputs") or []',
     "test_report_kpis.BundleFloorTests.test_floor_copied_and_hashed_in_the_marker"),
    # A project name in the stage tool's markdown is published.
    ("benchmark/report/scrub.py", "return self._project_re.sub(self._project, s)", "return s",
     "test_report_scrub.StageLatencyScrubTests.test_markdown_is_rewritten"),
    # scrub_inputs() leaves a stage-latency.json in the scratch dir unscrubbed.
    ("benchmark/report/scrub.py", '("stage-latency.json", scrub_stage_latency, False),', "",
     "test_report_scrub.StageLatencyScrubTests.test_scrub_inputs_takes_an_optional_stage_latency_result"),
    # Bench 5, orchestrator. The blast --help probe passes a bench-4 image when the blasters export landings.
    ("benchmark/bench-lib.sh", LANDINGS_PROBE, '    [ "${BENCH_LANDINGS_SAMPLE:-0}" = "0" ] || true',
     "test_txgen_probe.TxgenProbeTests.test_sampled_landings_refuse_a_bench_4_image_naming_both_flags"),
    # U-Hfix (harness review). A re-run passes over a cert_failures entry that lists no log (S1).
    ("benchmark/benchmark-teardown.sh",
     "    jq -r '[(.cert_failures // [])[]? | objects | select(([(.logs // [])[]? | strings] | length) == 0)",
     "    jq -r '[(.cert_failures // [])[]? | objects | select(false)",
     "test_teardown_local_gate.TeardownLocalGateTests.test_a_skipped_certification_snapshots_an_entry_that_lists_no_log"),
    # Step 7 records every node as durable whatever its PRECFG_OK line's dbsync= says (S2).
    ("benchmark/benchmark-deploy.sh", '    ds="$(postcfg_field "${line}" dbsync)"; ds="${ds:-durable}"', '    ds="durable"',
     "test_node_image.Step7Tests.test_db_sync_mode_is_recorded_per_node"),
    # make_bundle publishes a safe-no-sync run without --allow-safe-no-sync (S2).
    ("benchmark/report/make_bundle.py", "    sync_mode_check(raw_manifest, a.allow_safe_no_sync)\n", "",
     "test_report_bundle.SafeNoSyncTests.test_main_refuses_before_provenance_and_writes_nothing"),
    # The stage tool keeps the blocks next to an epoch boundary in the light windows by default (S3).
    ("benchmark/tools/stage-latency.py", '    p.set_defaults(exclude_boundaries="light*")',
     "    p.set_defaults(exclude_boundaries=None)",
     "test_stage_latency.StageLatencyTests.test_window_filter_and_epoch_boundary_exclusion"),
    # windows.py --run-dir keeps the blocks next to an epoch boundary in the light windows by default (S3).
    ("benchmark/report/windows.py",
     "    excl = EXCLUDE_SECS if args.exclude_boundaries is None else args.exclude_boundaries",
     "    excl = args.exclude_boundaries",
     "test_report_kpis.LightWindowTests.test_cli_light_only_with_run_dir"),
    # Every "digests resent" line counts as cause unknown, so a cancel count includes the commit path (L7 S2).
    ("benchmark/tools/stage-latency.py", "            cause = f.get(\"cause\", \"\").strip('\"') or \"unknown\"",
     '            cause = "unknown"',
     "test_stage_latency.StageLatencyTests.test_digests_resent_split_by_cause"),
    # Only the first blast of the light-load arm measures LOG_RATE, not the loaded one (N5).
    ("benchmark/benchmark-blast.sh", '        light_child run "${p}" BENCH_LOG_RATE_CHECK=1 || rc=$?',
     '        light_child run "${p}" BENCH_LOG_RATE_CHECK=$(( p == 0 )) || rc=$?',
     "test_blast_argv.SequenceTests.test_markers_children_and_blasts_in_order"),
    # A dry run prints the LIGHT_LOAD_START marker a log watcher takes for a run (N7).
    ("benchmark/benchmark-blast.sh", '        elif [ "${BENCH_APPLY}" = "1" ]; then echo "LIGHT_LOAD_START i=',
     '        elif true; then echo "LIGHT_LOAD_START i=',
     "test_blast_argv.LightPlanTests.test_light_blasts_then_the_configured_profile"),
    # Under set -e a failed lookup aborts the bucket transfer's job or preflight without the node's ✗ line (N4).
    ("benchmark/pull-lib.sh", '    ident="$(_bench_instance_ident "${inst}" "${zone}")" || ident=""',
     '    ident="$(_bench_instance_ident "${inst}" "${zone}")"',
     "test_pull_logs.BucketTransferTests.test_a_failed_lookup_fails_that_node_with_its_message_under_set_e"),
    ("benchmark/pull-lib.sh", '    ident2="$(_bench_instance_ident "${inst}" "${zone}")" || ident2=""',
     '    ident2="$(_bench_instance_ident "${inst}" "${zone}")"',
     "test_pull_logs.BucketTransferTests.test_a_failed_lookup_fails_that_node_with_its_message_under_set_e"),
    ("benchmark/pull-lib.sh", '        json="$(bench_instance_json "${inst}" "${ZONES[$i]}" < /dev/null)" || json=""',
     '        json="$(bench_instance_json "${inst}" "${ZONES[$i]}" < /dev/null)"',
     "test_pull_logs.BucketTransferTests.test_a_failed_lookup_fails_that_node_with_its_message_under_set_e"),
    # Bench 6, H0. The knobs, the node switch table and the frozen persist headers.
    ('benchmark/config.sh',
     '    */family/*) echo "❌ benchmark/config.sh: BENCH_NODE_BOOT_IMAGE=\'${IMAGE}\' names an image family;',
     '    */nofamily/*) echo "❌ benchmark/config.sh: BENCH_NODE_BOOT_IMAGE=\'${IMAGE}\' names an image family;',
     'test_node_image.Bench6KnobTests.test_boot_image_pin_and_refusals'),
    ('benchmark/config.sh',
     'export IMAGE="${BENCH_NODE_BOOT_IMAGE:-projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-v20261105}"',
     'export IMAGE="${BENCH_NODE_BOOT_IMAGE:-${IMAGE}}"',
     'test_node_image.Bench6KnobTests.test_knobs_unset_keep_every_bench5_export'),
    ('benchmark/config.sh',
     '    *[!a-z0-9/.-]*|*//*|*/|projects/*/*/global/images/*|projects/*/global/images/*/*) _bench_bad=1 ;;',
     '    *[!a-z0-9/.-]*) _bench_bad=1 ;;',
     'test_node_image.Bench6KnobTests.test_boot_image_pin_and_refusals'),
    ('benchmark/config.sh',
     ' bool:pipelined_persist"\n',
     '"\n',
     'test_node_image.Bench6KnobTests.test_switch_keys_are_the_rows_of_switches_tsv'),
    ('benchmark/config.sh',
     'BENCH_NODE_PARAM_KEYS="${BENCH_NODE_PARAM_KEYS} ${BENCH_NODE_SWITCH_KEYS}"',
     'true',
     'test_node_image.Bench6KnobTests.test_switch_keys_pass_the_per_node_override_check'),
    ('benchmark/config.sh',
     '    *[!0-9]*|0?*) echo "❌ benchmark/config.sh: BENCH_NODE_READ_AHEAD_KB=',
     '    *[!0-9k]*|0?*) echo "❌ benchmark/config.sh: BENCH_NODE_READ_AHEAD_KB=',
     'test_node_image.Bench6KnobTests.test_bench6_knob_values'),
    ('benchmark/config.sh',
     'export BENCH_LIGHT_START_DELAY_SECS="${BENCH_LIGHT_START_DELAY_SECS:-${BENCH_START_DELAY_SECS}}"',
     'export BENCH_LIGHT_START_DELAY_SECS="${BENCH_LIGHT_START_DELAY_SECS:-150}"',
     'test_node_image.Bench6KnobTests.test_knobs_unset_keep_every_bench5_export'),
    ('benchmark/config.sh',
     '    if [ "${BENCH_NODE_EVICT_MDBX}" != "0" ] || [ -n "${BENCH_NODE_READ_AHEAD_KB}" ]; then',
     '    if false; then',
     'test_node_image.Bench6KnobTests.test_arm_file_knob'),
    ('benchmark/config.sh',
     '    benchmark-deploy.sh|benchmark-firewall.sh|benchmark-blast.sh|benchmark-teardown.sh|benchmark-probe.sh|\\',
     '    benchmark-deploy.sh|benchmark-firewall.sh|benchmark-blast.sh|benchmark-teardown.sh|\\',
     'test_node_image.Bench6KnobTests.test_the_probe_driver_may_load_the_profile'),
    ('benchmark/arms/switches.tsv',
     'pipelined_persist\tbool\tfalse\ttrue\tpipelined-persist\tyes',
     'pipelined_persist\tbool\tfalse\ttrue\tpipelined-persist\tno',
     'test_node_image.Bench6KnobTests.test_switch_keys_are_the_rows_of_switches_tsv'),
    ('benchmark/tools/persist-csv-header.txt',
     ',mdbx_dat_rr_bytes,',
     ',',
     'test_node_image.Bench6KnobTests.test_persist_headers_are_frozen'),
    # H1a. The blaster create path: describe and one retry, the start_at deadline, unsent deletes.
    ('benchmark/benchmark-blast.sh',
     '            case "${rc}:${out}" in 142:*|*"gcloud crashed"*|*ReadTimeout*|*ConnectionError*) transient=1 ;; esac',
     '            case "${rc}:${out}" in 142:*|*ConnectionError*) transient=1 ;; esac',
     'test_blast_argv.CreatePathTests.test_a_crashed_create_is_retried_once'),
    ('benchmark/benchmark-blast.sh',
     '            if [ -n "${found}" ]; then',
     '            if false; then',
     'test_blast_argv.CreatePathTests.test_a_crashed_create_whose_instance_exists_is_used'),
    ('benchmark/benchmark-blast.sh',
     '            if [ "${transient}" -eq 1 ] && [ "${retried}" -eq 0 ]; then',
     '            if [ "${transient}" -eq 1 ]; then',
     'test_blast_argv.CreatePathTests.test_two_failures_stop_the_run_and_delete_every_blaster_before_start_at'),
    ('benchmark/benchmark-blast.sh',
     '        if [ "${st}" = ok ] && [ "${end}" -le "${limit}" ]; then',
     '        if [ "${st}" = ok ]; then',
     'test_blast_argv.CreatePathTests.test_a_create_done_after_the_late_start_limit_stops_the_run_unsent'),
    ('benchmark/benchmark-blast.sh',
     '                if [ "${left}" -le 0 ]; then status=late; rc=142; break 2; fi\n                [ "${left}" -ge "${bound}" ] || bound="${left}"',
     '                if [ "${left}" -le 0 ]; then status=late; rc=142; break 2; fi',
     'test_blast_argv.CreatePathTests.test_no_call_outlasts_the_late_start_limit'),
    ('benchmark/benchmark-blast.sh',
     '         and (.abort.reason == "interrupted" or .abort.reason == "create_failed" or .abort.reason == "late_create")',
     '         and (.abort.reason == "interrupted" or .abort.reason == "create_failed")',
     'test_blast_argv.UnsentRetryTests.test_the_reasons_and_unsent'),
    ('benchmark/benchmark-blast.sh',
     '            [ "${UNSTARTED_DELETED}" -ne 1 ] || [ "$(bench_now_unix)" -ge "${RUN_START_AT}" ] || unsent=true ;;',
     '            [ "${UNSTARTED_DELETED}" -ne 1 ] || unsent=true ;;',
     'test_blast_argv.CreatePathTests.test_deletes_that_return_after_start_at_may_have_let_a_blaster_send'),
    ('benchmark/benchmark-blast.sh',
     '    [ "${failed}" -ne 0 ] || UNSTARTED_DELETED=1',
     '    UNSTARTED_DELETED=1',
     'test_blast_argv.CreatePathTests.test_a_blaster_whose_delete_failed_may_have_sent'),
    ('benchmark/benchmark-blast.sh',
     '    record_abort "${ABORT_REASON:-interrupted}" "${ABORT_NODE:-operator}" \\',
     '    record_abort "interrupted" "operator" \\',
     'test_blast_argv.CreatePathTests.test_two_failures_stop_the_run_and_delete_every_blaster_before_start_at'),
    ('benchmark/benchmark-blast.sh',
     '    if [ -n "${e}" ]; then printf \'%s\\n\' "${e}"; else tail -5 "$1" 2>/dev/null; fi',
     '    tail -5 "$1" 2>/dev/null',
     'test_blast_argv.CreatePathTests.test_two_failures_stop_the_run_and_delete_every_blaster_before_start_at'),
    ('benchmark/benchmark-blast.sh',
     '        name="$(blaster_name "$k")"\n        blaster_created "$k" || continue\n        try_up_to',
     '        name="$(blaster_name "$k")"\n        try_up_to',
     'test_blast_argv.CreatePathTests.test_a_failure_after_start_at_stops_only_the_blasters_that_exist'),
    ('benchmark/benchmark-blast.sh',
     '        blaster_created "$k" || continue\n        if [ -z "${DONE_LINE[k]:-}" ]; then',
     '        if [ -z "${DONE_LINE[k]:-}" ]; then',
     'test_blast_argv.CreatePathTests.test_a_failure_after_start_at_stops_only_the_blasters_that_exist'),
    ('benchmark/benchmark-blast.sh',
     '    elif [ "${BENCH_START_DELAY_SECS}" -ge "${CREATE_WORST_SECS}" ]; then printf \'%s\' "${BENCH_START_DELAY_SECS}"',
     '    elif true; then printf \'%s\' "${BENCH_START_DELAY_SECS}"',
     'test_blast_argv.CreatePathTests.test_the_lead_fits_two_create_calls_and_a_describe'),
    ('benchmark/benchmark-blast.sh',
     "            'first((.instances // [])[] | select(.name == $n and .zone == $z) | .internal_ip // empty)' \\",
     "            'first((.instances // [])[] | select(.name == $n and .zone == $z) | .external_ip // empty)' \\",
     'test_blast_argv.NodeUrlTests.test_node_urls_come_from_the_manifest_without_a_call'),
    ('benchmark/benchmark-blast.sh',
     '        late="$(awk -v p="${p}" -v s="$1" \'BEGIN { printf "%.1f", p - s }\')"',
     '        late="$(awk -v p="${p}" -v s="$1" \'BEGIN { printf "%.1f", s - p }\')"',
     'test_blast_argv.NodeUrlTests.test_late_secs_from_each_blasters_own_preamble'),
    ('benchmark/benchmark-blast.sh',
     '            [ "${BENCH_APPLY}" = "1" ] || return 0\n            out="$(bench_run perl',
     '            out="$(bench_run perl',
     'test_blast_argv.DryRunShimTests.test_each_live_create_and_delete_sits_behind_a_dry_run_guard'),
    ('benchmark/benchmark-blast.sh',
     'CREATE_ALARM_SECS=90; CREATE_HTTP_TIMEOUT_SECS=60; CREATE_DESCRIBE_ALARM_SECS=60; CREATE_LATE_LEAD_SECS=30',
     'CREATE_ALARM_SECS=600; CREATE_HTTP_TIMEOUT_SECS=60; CREATE_DESCRIBE_ALARM_SECS=60; CREATE_LATE_LEAD_SECS=30',
     'test_blast_argv.UnsetKnobTests.test_run_plan_and_generator_argv_equal_the_bench4_golden'),
    # H1b. Real phases, blast kinds, pool state, the tail scan and the background deletes.
    ('benchmark/benchmark-blast.sh',
     '    for q in "$@"; do echo "     $(light_env "${q}") BENCH_LOG_RATE_CHECK=1 ${cmd} run --yes --run ${BENCH_RUN_ID}" >&2; done',
     '    for q in "$@"; do echo "     $(light_env "${q}") ${cmd} run --yes --run ${BENCH_RUN_ID}" >&2; done',
     'test_blast_argv.SequenceTests.test_a_failed_light_blast_stops_the_sequence'),
    ('benchmark/benchmark-blast.sh',
     '    local collect="benchmark/benchmark-deploy.sh --yes --from 15 --to 15 --run ${BENCH_RUN_ID}"',
     '    local collect="benchmark/benchmark-deploy.sh --yes --from 14 --to 15 --run ${BENCH_RUN_ID}"',
     'test_blast_argv.SequenceTests.test_a_failed_light_blast_stops_the_sequence'),
    ('benchmark/benchmark-blast.sh',
     '        if [ -z "${DONE_LINE[k]:-}" ] && grep -qxF -- "${prefix}/${name}.json" <<< "${listing}"; then',
     '        if [ -z "${DONE_LINE[k]:-}" ] && grep -qF -- "${prefix}/${name}.json" <<< "${listing}"; then',
     'test_blast_argv.BucketCompletionTests.test_one_listing_per_check_and_a_serial_read_per_listed_result'),
    ('benchmark/benchmark-blast.sh',
     '    next_check="${due}"',
     '    next_check="$1"',
     'test_blast_argv.BucketCompletionTests.test_a_check_gives_way_to_a_chaos_action_and_runs_right_after_it'),
    ('benchmark/benchmark-blast.sh',
     '    delete_vms "$1" "$2" < /dev/null &',
     '    delete_vms "$1" "$2" < /dev/null; true &',
     'test_blast_argv.BackgroundDeleteTests.test_the_deletes_run_in_the_background_then_a_describe_loop'),
    ('benchmark/benchmark-blast.sh',
     '        if [ $(( $(bench_now_unix) - t0 )) -ge "${DELETE_WAIT_SECS}" ] || [ "${pass}" -ge "${passes}" ]; then',
     '        if [ $(( $(bench_now_unix) - t0 )) -ge "${DELETE_WAIT_SECS}" ] || [ "${pass}" -ge 1 ]; then',
     'test_blast_argv.BackgroundDeleteTests.test_the_deletes_run_in_the_background_then_a_describe_loop'),
    ('benchmark/benchmark-blast.sh',
     '        ( assert_load_vm "$(blaster_name "$k")" "${ZONES[$k]}" ) > "${f}" 2>&1 < /dev/null &',
     '        ( assert_load_vm "$(blaster_name "$k")" "${ZONES[$k]}" ) > "${f}" 2>&1 < /dev/null; true &',
     'test_blast_argv.ParallelRelabelTests.test_the_relabels_run_at_once_and_print_in_order'),
    ('benchmark/benchmark-blast.sh',
     '        \'(if has("phases_planned") then . else .phases_planned = (.phases // []) end) | .phases = $r | .notes += [$n]\' \\',
     "        '.phases_planned = (.phases // []) | .phases = $r | .notes += [$n]' \\",
     'test_blast_argv.RealPhasesTests.test_phases_become_the_blasters_own_and_the_plan_is_kept'),
    ('benchmark/benchmark-blast.sh',
     'start: (map(.start_unix) | min | floor | todate)',
     'start: (map(.start_unix) | max | floor | todate)',
     'test_stall_scan.RealPhasesTests.test_the_idle_tail_is_a_stall_under_the_plan_and_none_under_the_real_phases'),
    ('benchmark/benchmark-blast.sh',
     'select(type == "object" and (.begin | type) == "string" and .begin <= $t)]',
     'select(type == "object" and (.begin | type) == "string")]',
     'test_blast_argv.SequenceRecordTests.test_each_entry_carries_its_kind_its_arm_and_its_own_record'),
    ('benchmark/benchmark-blast.sh',
     'kind: $k, arm: (if $arm == "" then null else $arm end)}',
     'kind: "light", arm: (if $arm == "" then null else $arm end)}',
     'test_blast_argv.SequenceTests.test_markers_children_and_blasts_in_order'),
    ('benchmark/benchmark-blast.sh',
     '(if (.blast | has("pool_at_start")) then {pool_at_start: .blast.pool_at_start} else {} end)',
     '(if (.blast | has("pool")) then {pool_at_start: .blast.pool_at_start} else {} end)',
     'test_blast_argv.SequenceRecordTests.test_each_entry_carries_its_kind_its_arm_and_its_own_record'),
    ('benchmark/benchmark-blast.sh',
     '    [ "$(blast_caller)" = hand ] || return 0',
     '    [ "$(blast_caller)" != sequence ] || return 0',
     'test_blast_argv.BlastRunTests.test_the_deploy_the_sequence_and_a_dry_run_record_nothing'),
    ('benchmark/benchmark-blast.sh',
     '    if [ "${ACTION}" = run ] && [ "$1" -eq 0 ]; then bench_manifest_ts step_14_done || true; fi',
     '    if [ "${ACTION}" = run ]; then bench_manifest_ts step_14_done || true; fi',
     'test_blast_argv.BlastRunTests.test_a_failed_run_or_a_fund_sets_no_step_14'),
    ('benchmark/benchmark-blast.sh',
     '        elif ! mkdir -p "${dest}/$(dirname "${it}")" || ! mv "${r}/${it}" "${dest}/${it}"; then',
     '        elif ! mkdir -p "${dest}/$(dirname "${it}")" || ! cp -Rp "${r}/${it}" "${dest}/${it}"; then',
     'test_blast_argv.FunderSetAsideTests.test_the_previous_index_is_moved_not_copied'),
    ('benchmark/benchmark-blast.sh',
     '    if [ "${BENCH_BLAST_KIND:-load}" = light ]; then printf \'%s\' "${BENCH_LIGHT_START_DELAY_SECS}"',
     '    if false; then printf \'%s\' "${BENCH_LIGHT_START_DELAY_SECS}"',
     'test_blast_argv.LightLeadTests.test_a_light_blast_takes_its_own_lead_without_the_floor'),
    ('benchmark/benchmark-blast.sh',
     '    [ "${mode}" != blast ] || [ "${BENCH_TAIL_SCAN_SECS:-0}" = 0 ] || meta="${meta}##TAIL_SCAN_SECS=${BENCH_TAIL_SCAN_SECS}"',
     '    [ "${mode}" != blast ] || true || meta="${meta}##TAIL_SCAN_SECS=${BENCH_TAIL_SCAN_SECS}"',
     'test_blast_argv.TailScanTests.test_the_flag_reaches_every_blaster_only_when_set'),
    ('benchmark/blaster-startup.sh',
     '    [ "${TAIL_SCAN_SECS}" = 0 ] || args+=(--tail-scan-secs "${TAIL_SCAN_SECS}")',
     '    true || args+=(--tail-scan-secs "${TAIL_SCAN_SECS}")',
     'test_blast_argv.TailScanTests.test_the_flag_reaches_every_blaster_only_when_set'),
    ('benchmark/benchmark-blast.sh',
     '    [ "${BENCH_TAIL_SCAN_SECS:-0}" = 0 ] || BENCH_TXGEN_CONTRACT_FLAGS="${BENCH_TXGEN_CONTRACT_FLAGS} --tail-scan-secs"',
     '    true || BENCH_TXGEN_CONTRACT_FLAGS="${BENCH_TXGEN_CONTRACT_FLAGS} --tail-scan-secs"',
     'test_blast_argv.TxgenProbeTests.test_the_flag_is_required_only_with_the_tail_on'),
    ('benchmark/benchmark-blast.sh',
     '    [ "${BENCH_LANDINGS_SAMPLE:-0}" = 0 ] || x=$(( x + UNLANDED_LOOKUP_SECS ))',
     '    true || x=$(( x + UNLANDED_LOOKUP_SECS ))',
     'test_blast_argv.TailScanTests.test_every_done_wait_grows_by_the_tail_and_the_unlanded_lookups'),
    ('benchmark/benchmark-blast.sh',
     # H13 re-anchored: the line now goes on with the blast's type
     "                   tail_scan_secs: ($ts|tonumber), kind: $k,",
     "                   tail_scan_secs: 0, kind: $k,",
     'test_blast_argv.BlastRecordTests.test_tail_scan_secs_is_recorded_with_the_blast'),
    ('benchmark/blaster-startup.sh',
     '    [ "${f}" = "${RESULT}" ] || upload_out "${f}"',
     '    upload_out "${f}"',
     'test_blast_argv.TailScanTests.test_the_result_goes_up_last_and_the_unlanded_file_beside_the_landings'),
    ('benchmark/benchmark-blast.sh',
     'select((.value.queued // 0) > $w)',
     'select((.value.queued // 0) >= $w)',
     'test_blast_argv.PoolAtStartTests.test_each_node_at_start_and_a_warning_above_1000_queued'),
    ('benchmark/benchmark-blast.sh',
     '    off=$(( $(bench_now_unix) - at )); [ "${off}" -le 0 ] || o=" offset ${off}s"',
     '    off=$(( $(bench_now_unix) - at )); true || o=" offset ${off}s"',
     'test_blast_argv.PoolAtStartTests.test_a_late_read_still_asks_for_the_start_and_a_failed_one_records_nulls'),
    # H2. The host probe and the host steps (bench-lib.sh).
    ('benchmark/bench-lib.sh',
     '    if after:\n        raise StepFailed(',
     '    if after < 0:\n        raise StepFailed(',
     'test_host_probe.HostStepScriptTests.test_eviction_with_fincore'),
    ('benchmark/bench-lib.sh',
     '    if re.match(r"^[0-9]+$", out):',
     '    if False:',
     'test_host_probe.HostProbeScriptTests.test_probe_takes_fincore_count_and_a_given_datadir'),
    ('benchmark/bench-lib.sh',
     '    if after != kb:',
     '    if after is None:',
     'test_host_probe.HostPyTests.test_read_back_that_differs_fails_the_step'),
    ('benchmark/bench-lib.sh',
     '    h["khugepaged_defrag"] = active(',
     '    h["khugepaged"] = active(',
     'test_host_probe.HostProbeScriptTests.test_probe_reads_every_field_from_the_host_and_writes_nothing'),
    ('benchmark/bench-lib.sh',
     'elif $t == "i" then type == "number" and . == floor and . >= 0',
     'elif $t == "i" then true',
     'test_host_probe.HostProbeRecordTests.test_record_from_a_session_output'),
    ('benchmark/bench-lib.sh',
     '| (($ok | length) > 0 and ($differ | length) == 0) as $uni',
     '| (($differ | length) == 0) as $uni',
     'test_host_probe.HostProbeSummaryTests.test_no_node_probed_is_not_uniform'),
    ('benchmark/bench-lib.sh',
     'select(any($u[]; ($n.h[.] | tojson) != $common[.]))',
     'select(any($u[]; ($n.h[.] | tojson) != $common[.]) and false)',
     'test_host_probe.HostProbeSummaryTests.test_one_differing_node_is_named'),
    ('benchmark/bench-lib.sh',
     'first($c[] | select(.n == $top))',
     'last($c[] | select(.n == $top))',
     'test_host_probe.HostProbeSummaryTests.test_most_common_value_and_ties_go_to_the_fleet_order'),
    ('benchmark/bench-lib.sh',
     '    if [ "${ev}" = 1 ]; then',
     '    if [ "${ev}" != 1 ]; then',
     'test_host_probe.PrestartHostStepTextTests.test_knobs_unset_or_off_are_byte_identical_to_the_unmodified_script'),
    ('benchmark/bench-lib.sh',
     "    echo ') || HOST_STEP_RC=$?'",
     "    echo ')'",
     'test_host_probe.HostStepScriptTests.test_eviction_with_fincore'),
    # H3. Deploy wiring: the boot-image gate, the arm before the first start, the switch readback, the sampler.
    ('benchmark/benchmark-deploy.sh',
     'OBSOLETE|DELETED) bench_die',
     'OBSOLETE) bench_die',
     'test_node_image.BootImageGateTests.test_refusals_name_the_reason_and_create_nothing'),
    ('benchmark/benchmark-deploy.sh',
     '[ "${st}" = READY ] || bench_die',
     '[ "${st}" = READY ] || true',
     'test_node_image.BootImageGateTests.test_refusals_name_the_reason_and_create_nothing'),
    ('benchmark/benchmark-deploy.sh',
     '[ -z "${offimg}" ] || bench_die',
     '[ -z "${offimg}" ] || true',
     'test_node_image.Step2SourceImageTests.test_a_disk_from_another_image_refuses_the_fleet'),
    ('benchmark/benchmark-deploy.sh',
     'bench_host_probe_script "${inst}"; ',
     '',
     'test_node_image.Step7Tests.test_each_session_is_the_probe_then_the_pre_start_script'),
    ('benchmark/benchmark-deploy.sh',
     'host_steps: $hs}',
     'host_steps: []}',
     'test_node_image.Step7ArmTests.test_v_vote_writes_its_switches_runs_its_host_step_and_is_recorded'),
    ('benchmark/bench-lib.sh',
     'nov="$(( $(bench_node_overrides "${idx}" | grep -c . || true) + an ))"',
     'nov="$(( $(bench_node_overrides "${idx}" | grep -c . || true) ))"',
     'test_node_image.ArmStateTests.test_the_pre_start_script_writes_the_switches_and_runs_the_host_steps_last'),
    ('benchmark/benchmark-deploy.sh',
     'ready: $b}',
     'ready: null}',
     'test_node_image.Step7ArmTests.test_v_vote_writes_its_switches_runs_its_host_step_and_is_recorded'),
    ('benchmark/benchmark-deploy.sh',
     '[ "${rsha}" = "${BENCH_ARM_SHA256}" ] || bench_die',
     '[ "${rsha}" = "${BENCH_ARM_SHA256}" ] || true',
     'test_node_image.Step7ArmTests.test_a_rerun_keeps_the_recorded_arm_and_refuses_any_other'),
    ('benchmark/bench-lib.sh',
     'elif [ "${o}" = yes ] &&',
     'elif [ "${o}" = "${o}" ] &&',
     'test_node_image.ArmLibTests.test_switch_readback_compares_by_value'),
    ('benchmark/bench-lib.sh',
     '                 mul = (u == "ms") ? 1 : ((u == "s") ? 1000 : 60000)',
     '                 mul = 1',
     'test_node_image.ArmLibTests.test_switch_readback_compares_by_value'),
    ('benchmark/bench-lib.sh',
     '[ "${got}" = "${sha}" ] || {',
     'true || {',
     'test_node_image.ArmStateTests.test_print_state_output_the_deploy_refuses'),
    ('benchmark/benchmark-deploy.sh',
     'systemctl is-active --quiet bench-persist-sampler.service || fail',
     'true || fail',
     'test_node_image.Step9ArmTests.test_the_persist_sampler_is_installed_and_must_be_active'),
    ('benchmark/bench-lib.sh',
     'if ! compgen -G "${logs}/*.log.gz" >/dev/null && ',
     'if false && ',
     'test_node_image.ArmLibTests.test_certification_waits_for_the_teardown_pull'),
    ('benchmark/bench-lib.sh',
     ' && ! compgen -G "${logs}/*.pulled" >/dev/null',
     '',
     'test_node_image.ArmLibTests.test_certification_waits_for_the_teardown_pull'),
    ('benchmark/node-image-contract.txt',
     'require node switches\n',
     '',
     'test_node_image.NodeSwitchContractTests.test_an_image_without_the_switch_line_is_refused'),
    ('benchmark/bench-lib.sh',
     '[ "${rk}" != "${k}" ] ||',
     '[ "${rk}" = "${rk}" ] ||',
     'test_node_image.ArmStateTests.test_a_per_node_switch_beside_the_arm_is_refused'),
    # H4. The persist sampler and the folio census.
    ('benchmark/node-persist-sampler.sh',
     '    [ -n "${row}" ] || row="${ts},${pid}${BLANK_TAIL}"',
     '    [ -n "${row}" ] || row="${ts},${pid}"',
     'test_persist_sampler.SamplerTests.test_a_failing_reader_still_writes_a_full_row'),
    ('benchmark/node-persist-sampler.sh',
     '    if [ $(( n % MDBX_TICKS )) -eq 0 ]; then',
     '    if true; then',
     'test_persist_sampler.SamplerTests.test_mdbx_columns_only_on_their_cadence'),
    ('benchmark/node-persist-sampler.sh',
     '    if [ -n "${pid}" ] && in_container "${pid}" && cmd_matches "${pid}"; then return 0; fi',
     '    if [ -n "${pid}" ]; then return 0; fi',
     'test_persist_sampler.SamplerTests.test_pid_change_is_followed'),
    ('benchmark/node-persist-sampler.sh',
     '    [ -e "${sys}/partition" ] && sys="${sys%/*}"',
     '    :',
     'test_persist_sampler.SamplerTests.test_full_row'),
    ('benchmark/node-persist-sampler.sh',
     'cur && $1 == "VmFlags:" { for (i = 2; i <= NF; i++) if ($i == "rr") { rr += sz; break } }',
     'cur && $1 == "VmFlags:" { for (i = 2; i <= NF; i++) if ($i == "rd") { rr += sz; break } }',
     'test_persist_sampler.SamplerTests.test_full_row'),
    ('benchmark/node-persist-sampler.sh',
     '    cur = ($5 == ino && ($4 == dev || substr($6, length($6) - length(sfx) + 1) == sfx)); next',
     '    cur = ($5 == ino); next',
     'test_persist_sampler.SamplerTests.test_full_row'),
    ('benchmark/node-persist-sampler.sh',
     '            v["disk_wr_bytes_total"] = sprintf("%.0f", d[10] * 512); v["disk_wr_ticks_ms_total"] = d[11]',
     '            v["disk_wr_bytes_total"] = d[10]; v["disk_wr_ticks_ms_total"] = d[11]',
     'test_persist_sampler.SamplerTests.test_full_row'),
    ('benchmark/node-persist-sampler.sh',
     '!found && (index($0, "tn_reth_mdbx_used_bytes ") == 1 || index($0, "tn_reth_mdbx_used_bytes{") == 1) {',
     '!found && index($0, "tn_reth_mdbx_used_bytes ") == 1 {',
     'test_persist_sampler.SamplerTests.test_used_size_gauge_present'),
    ('benchmark/node-persist-sampler.sh',
     'END { if (found) printf "%.0f\\n", used }',
     'END { if (found) print used }',
     'test_persist_sampler.SamplerTests.test_used_size_gauge_present'),
    ('benchmark/node-persist-sampler.sh',
     '        used="$(timeout "${TO}" curl -s --max-time 3 "${METRICS_URL}" 2>/dev/null | awk "${USED_AWK}")" || used=""',
     '        used="$(timeout "${TO}" curl -s "${METRICS_URL}" 2>/dev/null | awk "${USED_AWK}")" || used=""',
     'test_persist_sampler.SamplerTests.test_used_size_endpoint_that_never_answers'),
    ('benchmark/node-persist-sampler.sh',
     '--resident-only --from-bytes "${used}" 2>/dev/null)" || out=""',
     '--resident-only 2>/dev/null)" || out=""',
     'test_persist_sampler.SamplerTests.test_used_size_gauge_present'),
    ('benchmark/node-persist-sampler.sh',
     '    [ -n "${_mp}" ] || _mp=9101',
     '    [ -n "${_mp}" ] || _mp=9102',
     'test_persist_sampler.SamplerTests.test_default_metrics_url_from_node_meta'),
    ('benchmark/node-persist-sampler.sh',
     'END { sub(/\\r$/, "", v); if (n == 1) print v }',
     'END { sub(/\\r$/, "", v); print v }',
     'test_persist_sampler.SamplerTests.test_default_metrics_url_from_node_meta'),
    ('benchmark/node-persist-sampler.sh',
     '; v["mdbx_dat_resident_past_used_pages"] = mpast',
     '',
     'test_persist_sampler.SamplerTests.test_full_row'),
    ('benchmark/node-persist-sampler.sh',
     '        M_SIZE=""; M_RES=""; M_VMA=""; M_RR=""; M_PAST=""',
     '        M_SIZE=""; M_RES=""; M_VMA=""; M_RR=""',
     'test_persist_sampler.SamplerTests.test_mdbx_columns_only_on_their_cadence'),
    ('benchmark/tools/folio-census.py',
     '        addr = _libc.mmap(None, length, PROT_NONE, MAP_PRIVATE, fd, first * ps)',
     '        addr = _libc.mmap(None, length, 1, MAP_PRIVATE | 0x8000, fd, first * ps)',
     'test_persist_sampler.RealFileSmokeTests.test_five_censuses_leave_residency_unchanged'),
    ('benchmark/tools/folio-census.py',
     '        ft = flags.get(head + (1 << order))',
     '        ft = flags.get(head + order + 1)',
     'test_persist_sampler.CensusFakeTreeTests.test_folio_orders_and_flags'),
    ('benchmark/tools/folio-census.py',
     '                        if f is None or not f & special or idx[k] < covered:',
     '                        if f is None or not f & special:',
     'test_persist_sampler.CensusFakeTreeTests.test_folio_orders_and_flags'),
    ('benchmark/tools/folio-census.py',
     '                        if f & special:',
     '                        if f & NOT_FILE:',
     'test_persist_sampler.CensusFakeTreeTests.test_folio_orders_and_flags'),
    ('benchmark/tools/folio-census.py',
     '                        dirty0 += k if f & KPF_DIRTY else 0',
     '                        dirty0 += k',
     'test_persist_sampler.CensusFakeTreeTests.test_single_page_folios_fast_path'),
    ('benchmark/tools/folio-census.py',
     '        return present, list(compress(memoryview(raw).cast("I")[0::2].tolist(), present))',
     '        return present, list(compress(memoryview(raw).cast("I")[1::2].tolist(), present))',
     'test_persist_sampler.CensusFakeTreeTests.test_single_page_folios_fast_path'),
    ('benchmark/tools/folio-census.py',
     '            if len(table) > flat_max:',
     '            if False:',
     'test_persist_sampler.CensusFakeTreeTests.test_block_reads_match_the_whole_table'),
    ('benchmark/tools/folio-census.py',
     '    if f is None or f & NOT_FILE:',
     '    if f is None:',
     'test_persist_sampler.CensusFakeTreeTests.test_folio_orders_and_flags'),
    ('benchmark/tools/folio-census.py',
     '                    unresolved = str(total - done)',
     '                    unresolved = str(total)',
     'test_persist_sampler.CensusFakeTreeTests.test_folio_orders_and_flags'),
    ('benchmark/tools/folio-census.py',
     '        if os.fstat(fd).st_size == 0:',
     '        if True:',
     'test_persist_sampler.CensusFakeTreeTests.test_out_appends_with_one_header'),
    ('benchmark/tools/folio-census.py',
     '        if (major, minor) != want_dev and not parts[5].endswith(suffix):',
     '        if (major, minor) != want_dev:',
     'test_persist_sampler.CensusFakeTreeTests.test_writer_mappings_match_rule'),
    # H5a. params-apply.sh applies a whole arm file: guard, epoch, unit, readback, record.
    # guard samples GT times before a deferral
    ('benchmark/tools/params-apply.sh',
     '        [ "$t" -lt "$GT" ] || return 1\n',
     '        return 1\n',
     'test_params_apply.GuardTests.test_refusals_are_resampled_until_one_passes'),
    # a blind pass counts as a refusal
    ('benchmark/tools/params-apply.sh',
     '        if [ "$g" = 0 ]; then case "${nl}${out}" in *"${nl}warn: "*) g=blind ;; esac; fi\n',
     '        if false; then g=blind; fi\n',
     'test_params_apply.GuardTests.test_refusals_are_resampled_until_one_passes'),
    # a deferral gets a second round of samples
    ('benchmark/tools/params-apply.sh',
     '    sleep "$GD"\n    guard_round && return 0\n',
     '    sleep "$GD"\n',
     'test_params_apply.GuardTests.test_two_deferrals_stop_the_run_before_the_node_is_touched'),
    # no stop within EM s after a boundary either
    ('benchmark/tools/params-apply.sh',
     '            if [ "$secs" -gt "$EM" ] && [ "$since" -ge "$EM" ]; then\n',
     '            if [ "$secs" -gt "$EM" ]; then\n',
     'test_params_apply.EpochTests.test_a_stop_waits_until_the_boundary_is_90_s_behind_and_takes_the_guard_again'),
    # the unit stops (not restarts) before the host steps
    ('benchmark/tools/params-apply.sh',
     'systemctl stop telcoin || s=$?\n',
     'systemctl restart telcoin || s=$?\n',
     'test_params_apply.UnitTests.test_stop_and_start_run_inside_one_transient_unit'),
    # a dry run never reaches gcloud
    ('benchmark/tools/params-apply.sh',
     '        return 0\n    fi\n    [ "${DRY}" = 0 ] || return 0\n    perl -e',
     '    fi\n    perl -e',
     'test_params_apply.DryRunTests.test_no_arm_file_reaches_gcloud_in_a_dry_run'),
    # an older start's line is stale
    ('benchmark/tools/params-apply.sh',
     '    if [ -n "${ts}" ] && [ -n "${stop}" ] && [[ "${ts}" < "${stop}" ]]; then\n',
     '    if false; then\n',
     'test_params_apply.ReadbackTests.test_an_older_start_s_line_is_not_a_readback'),
    # every switch value is compared
    ('benchmark/tools/params-apply.sh',
     '            [ "$(norm_val "${SW_T[$j]}" "${got}")" = "$(norm_val "${SW_T[$j]}" "${t}")" ] || echo "differs ${k} ${got} ${t}"\n',
     '            true\n',
     'test_params_apply.ReadbackTests.test_a_value_that_does_not_read_back_stops_the_run'),
    # an optional switch may be missing only at its default
    ('benchmark/tools/params-apply.sh',
     '        elif [ "${SW_O[$j]}" = yes ] && [ "$(norm_val "${SW_T[$j]}" "${t}")" = "$(norm_val "${SW_T[$j]}" "${SW_D[$j]}")" ]; then\n',
     '        elif [ "${SW_O[$j]}" = yes ]; then\n',
     'test_params_apply.ReadbackTests.test_an_optional_switch_the_image_lacks_passes_only_at_its_default'),
    # the arm file is the full state (unlisted = default)
    ('benchmark/tools/params-apply.sh',
     '        printf \'%s=%s\\n\' "${SW_K[$i]}" "${k:-${SW_D[$i]}}" >> "${WORK}/arm.target"\n',
     '        [ -z "${k}" ] || printf \'%s=%s\\n\' "${SW_K[$i]}" "${k}" >> "${WORK}/arm.target"\n',
     'test_params_apply.TargetStateTests.test_only_keys_that_differ_are_rewritten_and_back_to_default_writes_the_default'),
    # a key given twice refuses the arm file
    ('benchmark/tools/params-apply.sh',
     '                case "${seen}" in *" $2 "*) arm_refuse "${ln}" "switch \'$2\' is given twice" ;; esac\n',
     '',
     'test_params_apply.ArmFileParseTests.test_every_refusal_of_the_readme'),
    # a node restarts only when something differs
    ('benchmark/tools/params-apply.sh',
     '    if [ -n "${why}" ]; then PLAN+=("${i}"); else UNCHANGED+=("${i}"); fi\n',
     '    PLAN+=("${i}")\n',
     'test_params_apply.TargetStateTests.test_a_node_whose_running_switches_differ_restarts_without_a_rewrite'),
    # running switches that differ restart the node
    ('benchmark/tools/params-apply.sh',
     '            if has_line "${cmp}" "differs "; then why="${why:+${why},}live"; fi\n',
     '            if false; then :; fi\n',
     'test_params_apply.TargetStateTests.test_a_node_whose_running_switches_differ_restarts_without_a_rewrite'),
    # durations compare by value (0s = 0ms)
    ('benchmark/tools/params-apply.sh',
     '        dur) v="$(to_ms "$2")"; echo "${v:-?$2}" ;;\n',
     '        dur) echo "$2" ;;\n',
     'test_params_apply.TargetStateTests.test_a_duration_back_to_its_default_is_written_out_and_reads_back_as_0s'),
    # ready = last progress + the settle time
    ('benchmark/tools/params-apply.sh',
     "'$t | fromdateiso8601 + $s | todateiso8601'",
     "'$t'",
     'test_params_apply.ManifestAndHookTests.test_the_entry_has_every_frozen_field'),
    # H5b. params-apply.sh --print-state, the host-step hook and read-ahead as state.
    # print-state: an evict step prints its '-' value
    ('benchmark/tools/params-apply.sh',
     '        [ -z "${s}" ] || out="${out}${NL}ARM_HOST ${s} ${v:--}"\n',
     '        [ -z "${s}" ] || out="${out}${NL}ARM_HOST ${s} ${v}"\n',
     'test_params_apply.PrintStateTests.test_every_committed_arm_file'),
    # print-state: every refusal exits 1
    ('benchmark/tools/params-apply.sh',
     'for a in "$@"; do [ "${a}" != --print-state ] || DIE_RC=1; done\n',
     'for a in "$@"; do [ "${a}" != --print-state ] || DIE_RC=2; done\n',
     'test_params_apply.PrintStateTests.test_every_refusal_is_rc_1_with_nothing_on_stdout'),
    # print-state: the name note goes to stderr
    ('benchmark/tools/params-apply.sh',
     '            log "note: ${ARM_FILE}\'s name line says \'${ARM_FILE_NAME}\', not the file name" >&2\n',
     '            log "note: ${ARM_FILE}\'s name line says \'${ARM_FILE_NAME}\', not the file name"\n',
     'test_params_apply.PrintStateTests.test_a_name_line_other_than_the_file_name_is_a_note_on_stderr'),
    # host text: the datadir line becomes the remote D
    ('benchmark/tools/params-apply.sh',
     '    awk -v m="D=${HOST_D_MARK}" \'$0 == m { n++; print "D=\\"$D\\""; next } { print } END { exit (n == 1 ? 0 : 3) }\' "${WORK}/host.out" \\\n',
     '    awk -v m="D=${HOST_D_MARK}" \'$0 == m { n++; print; next } { print } END { exit (n == 1 ? 0 : 3) }\' "${WORK}/host.out" \\\n',
     'test_params_apply.HostStepTextTests.test_the_unit_runs_both_steps_between_the_stop_and_the_start'),
    # host lib: a missing function is named
    ('benchmark/tools/params-apply.sh',
     '            || { echo "${BENCH_LIB} has no single ${fn}() (the host steps and the host probe need it)" >&2; return 1; }\n',
     '            || true\n',
     'test_params_apply.ManifestAndHookTests.test_without_bench_lib_s_host_functions_an_arm_file_is_refused_before_any_node_is_contacted'),
    # host result: the step's rc must be 0
    ('benchmark/tools/params-apply.sh',
     '            if (n == 1 && rc == "0" && l !~ /^failed( |$)/) {\n',
     '            if (n == 1 && l !~ /^failed( |$)/) {\n',
     'test_params_apply.HostStepTextTests.test_every_step_line_becomes_one_result'),
    # host result: a backslash is escaped in JSON
    ('benchmark/tools/params-apply.sh',
     '                if (c == "\\\\" || c == "\\"") o = o "\\\\" c; else if (c == "\\t" || c == "\\r") o = o " "; else o = o c\n',
     '                if (c == "\\"") o = o "\\\\" c; else if (c == "\\t" || c == "\\r") o = o " "; else o = o c\n',
     'test_params_apply.HostStepTextTests.test_every_step_line_becomes_one_result'),
    # host steps: the first failed step ends them
    ('benchmark/tools/params-apply.sh',
     '        printf \'} | pa_host_result %s %s || return 1\\n\' "${s}" "${v:--}"\n',
     '        printf \'} | pa_host_result %s %s\\n\' "${s}" "${v:--}"\n',
     'test_params_apply.HostStepTextTests.test_a_failed_read_ahead_skips_the_eviction_and_the_node_still_starts'),
    # phase A carries the host probe (arm file)
    ('benchmark/tools/params-apply.sh',
     '        cat "${WORK}/probe.${N_NAME[$1]}" 2>/dev/null || echo "# no host probe: it could not be built (see the refusal after the plan)"\n',
     '        :\n',
     'test_params_apply.ReadAheadTests.test_listed_and_different_restarts_only_that_node'),
    # read-ahead: equal is no restart
    ('benchmark/tools/params-apply.sh',
     '        elif [ -n "${want}" ] && [ "${cur}" != "${want}" ]; then\n',
     '        elif [ -n "${want}" ]; then\n',
     'test_params_apply.ReadAheadTests.test_listed_and_equal_restarts_nothing'),
    # read-ahead: without the step the deploy value is the target
    ('benchmark/tools/params-apply.sh',
     '        elif [ -n "${rec}" ]; then\n            want="${rec}"\n',
     '        elif [ -n "${rec}" ]; then\n            want=""\n',
     'test_params_apply.ReadAheadTests.test_not_listed_and_drifted_is_restored_with_a_restart'),
    # read-ahead: a missing deploy value is named in the warning
    ('benchmark/tools/params-apply.sh',
     '            RA_NOREC="${RA_NOREC} ${n}"\n',
     '            :\n',
     'test_params_apply.ReadAheadTests.test_a_node_without_a_recorded_value_is_left_alone_with_one_warning'),
    # read-ahead: only a number is a deploy value
    ('benchmark/tools/params-apply.sh',
     '           | select(.value.host.read_ahead_kb | type == "number" and . >= 0 and . == floor) | "\\(.key) \\(.value.host.read_ahead_kb)"\' \\\n',
     '           | "\\(.key) \\(.value.host.read_ahead_kb)"\' \\\n',
     'test_params_apply.ReadAheadTests.test_a_node_without_a_recorded_value_is_left_alone_with_one_warning'),
    # read-ahead: an unreadable value with a target refuses the arm
    ('benchmark/tools/params-apply.sh',
     '        if [ -n "${want}" ] && [ "${DRY}" = 0 ] && [ -z "${cur}" ]; then\n',
     '        if false; then\n',
     'test_params_apply.ReadAheadTests.test_an_unreadable_read_ahead_refuses_the_arm_only_when_it_is_needed'),
    # read-ahead: a dry run takes the record's last value
    ('benchmark/tools/params-apply.sh',
     '        if [ "${DRY}" = 1 ]; then cur="$(ra_assumed "${n}")"; cur="${cur:-${rec}}"; else cur="$(ra_cur "${n}")"; fi\n',
     '        if [ "${DRY}" = 1 ]; then cur="${rec}"; else cur="$(ra_cur "${n}")"; fi\n',
     'test_params_apply.ReadAheadTests.test_a_dry_run_takes_the_value_the_record_last_left'),
    # evict-mdbx restarts every node
    ('benchmark/tools/params-apply.sh',
     '        if [ "${ARM_EVICT}" = 1 ]; then why="${why:+${why},}host" hs="${hs:+${hs}${NL}}evict-mdbx"; fi\n',
     '        if [ "${ARM_EVICT}" = 1 ]; then hs="${hs:+${hs}${NL}}evict-mdbx"; fi\n',
     'test_params_apply.DryRunTests.test_no_arm_file_reaches_gcloud_in_a_dry_run'),
    # H6a. The log prefilter, the kill filter, cert-rate's ready window, the archive.
    ('benchmark/tools/log-shapes.txt',
     'quorum reached\n',
     '',
     'test_pull_logs.ShapeCoverageTests.test_every_literal_a_reader_matches_is_a_shape'),
    ('benchmark/tools/archive-verify.py',
     'EXCLUDE = r"genesis',
     'EXCLUDE = r"^genesis',
     'test_archive.RuleTests.test_the_regex_is_a_value_gcloud_reads_as_one_rule'),
    ('benchmark/tools/archive-verify.py',
     '    if any(p.startswith(".") for p in parts):',
     '    if False:',
     'test_archive.RuleTests.test_the_gcloud_regex_and_the_plain_rule_agree'),
    ('benchmark/tools/archive-verify.py',
     '        elif not omd5:',
     '        elif False:',
     'test_archive.VerifyTests.test_object_without_md5'),
    ('benchmark/tools/archive-verify.py',
     '            problems.append("EXCLUDED FILE IN THE BUCKET (the rule keeps it out): %s" % rel)',
     '            pass',
     'test_archive.VerifyTests.test_an_excluded_file_in_the_bucket'),
    ('benchmark/tools/archive-run.sh',
     '"${VERIFY[@]}" --check-dry-run "${LOG}.dry" | sed \'s/^/    /\' || rc=$?',
     '"${VERIFY[@]}" --check-dry-run "${LOG}.dry" | sed \'s/^/    /\' || true',
     'test_archive.ArchiveRunTests.test_a_dry_run_listing_with_an_excluded_file_is_refused_before_any_upload'),
    ('benchmark/tools/archive-run.sh',
     'if [ "${DRY}" = "1" ]; then',
     'if [ "${DRY}" = "x" ]; then',
     'test_archive.ArchiveRunTests.test_the_dry_run_calls_no_gcloud'),
    ('benchmark/benchmark-teardown.sh',
     'elif ! td_archive; then',
     'elif ! td_archive && false; then',
     'test_teardown_local_gate.TeardownLocalGateTests.test_a_failed_archive_verify_stops_before_any_delete'),
    ('benchmark/benchmark-teardown.sh',
     '\'.archive = (if (.archive | type) == "object" then .archive else {} end) + {kind: "local", path: $p, verified_at: $t}\'',
     '\'.archive = {kind: "local", path: $p, verified_at: $t}\'',
     'test_teardown_local_gate.TeardownLocalGateTests.test_a_rerun_gate_merges_into_the_archive_record_and_keeps_remote'),
    ('benchmark/benchmark-teardown.sh',
     '        for tpid in ${TUNNEL_PIDS}; do ! kill -0 "${tpid}" 2>/dev/null || live="${live} ${tpid}"; done',
     '        for tpid in ${TUNNEL_PIDS}; do live="${live} ${tpid}"; done',
     'test_teardown_local_gate.TeardownLocalGateTests.test_a_tunnel_pid_already_stopped_is_not_killed_again'),
    ('benchmark/benchmark-teardown.sh',
     'bench_certification_record "${CERT_LOGS}" "$(bench_manifest)"',
     'bench_certification_record "${LOG_DIR}" "$(bench_manifest)"',
     'test_teardown_local_gate.TeardownLocalGateTests.test_certification_and_cert_rate_md_read_the_prefiltered_copy'),
    ('benchmark/tools/cert-rate.py',
     '            ready = w.get("ready") if key == "param_arms" else None',
     '            ready = None',
     'test_cert_rate.CertRateTests.test_an_arm_window_starts_at_ready'),
    ('benchmark/pull-lib.sh',
     '        [ "${s[0]}" -eq 0 ] && [ "${s[1]}" -le 1 ] && [ "${s[2]}" -eq 0 ] && mv -f -- "${tmp}" "${dst}" || rc=1',
     '        [ "${s[1]}" -le 1 ] && [ "${s[2]}" -eq 0 ] && mv -f -- "${tmp}" "${dst}" || rc=1',
     'test_pull_logs.PrefilterTests.test_a_cut_log_fails_the_pass_and_keeps_no_copy_of_it'),
    ('benchmark/pull-lib.sh',
     '        if [ "${same}" = "1" ] && [ -e "${out}/logs/${f##*/}" ] && [ "${out}/logs/${f##*/}" -nt "${f}" ]; then',
     '        if false; then',
     'test_pull_logs.PrefilterTests.test_a_second_pass_reads_only_new_logs_and_drops_copies_of_gone_ones'),
    ('benchmark/benchmark-teardown.sh',
     '        elif [ -s "${a}/certification.json" ] \\',
     '        elif false \\',
     'test_teardown_local_gate.TeardownLocalGateTests.test_certification_and_cert_rate_md_read_the_prefiltered_copy'),
    ('benchmark/pull-lib.sh',
     'pats="$(grep -v \'^#\' "${shapes}")"',
     'pats="$(cat "${shapes}")"',
     'test_pull_logs.PrefilterTests.test_comment_lines_are_no_pattern_and_new_shapes_redo_every_copy'),
    # H7a. Report windows by blast kind, arm windows, switch provenance, prestart arm rows.
    ('benchmark/report/windows.py',
     '    return [b for b in _light_entries(run_dir, manifest) if "kind" not in b or b["rc"] == 0]',
     '    return _light_entries(run_dir, manifest)',
     'test_report_windows.Bench6BlastTests.test_light_blasts_select_kind_light_and_rc_0'),
    ('benchmark/report/windows.py',
     '            if e["kind"] != "light":',
     '            if False:',
     'test_report_windows.Bench6BlastTests.test_light_blasts_select_kind_light_and_rc_0'),
    ('benchmark/report/windows.py',
     '            if e.get("kind") == "load" and e.get("rc") == 0 and e.get("index") != top]',
     '            if e.get("kind") == "load" and e.get("rc") == 0]',
     'test_report_windows.Bench6BlastTests.test_load_blasts_and_windows'),
    ('benchmark/report/windows.py',
     '                                    (blast.get("phases"), "blasts[].phases", "phases_planned" in blast),',
     '                                    (blast.get("phases"), "blasts[].phases", False),',
     'test_report_windows.Bench6BlastTests.test_light_windows_read_real_phases_before_planned_ones'),
    ('benchmark/report/windows.py',
     '    start, source = (ready, "ready") if ready is not None else (_unix(arm.get("begin")), "begin")',
     '    start, source = (_unix(arm.get("begin")), "begin")',
     'test_report_windows.Bench6BlastTests.test_arm_window_starts_at_ready'),
    ('benchmark/report/provenance.py',
     '_CANDIDATE_MARKERS = (b"starting", b"et to", b"ET TO", b"chedule", b"CHEDULE", b"node switches")',
     '_CANDIDATE_MARKERS = (b"starting", b"et to", b"ET TO", b"chedule", b"CHEDULE")',
     'test_report_provenance.SwitchParseTests.test_logfmt_json_and_plain_lines'),
    ('benchmark/report/provenance.py',
     '        allowed = [state] + ([allowed[0]] if arm.get("failed") else [])',
     '        allowed = [state]',
     'test_report_provenance.SwitchCheckTests.test_overrides_before_the_first_arm_and_a_failed_arm'),
    ('benchmark/report/provenance.py',
     '        begin = float("-inf") if arm.get("via") == "prestart" else ts_epoch(arm.get("begin"))',
     '        begin = ts_epoch(arm.get("begin"))',
     'test_report_provenance.SwitchCheckTests.test_a_prestart_arm_covers_the_first_start'),
    ('benchmark/report/provenance.py',
     '            if not (r["optional"] and exp == switch_value(kind, r["default"])):',
     '            if True:',
     'test_report_provenance.SwitchCheckTests.test_an_optional_switch_may_be_absent_only_at_its_default'),
    ('benchmark/report/provenance.py',
     '    required = switch_line_required(manifest)',
     '    required = False',
     'test_report_provenance.SwitchCheckTests.test_missing_line_fails_only_where_the_contract_requires_it'),
    ('benchmark/report/provenance.py',
     '        return True if text == "true" else (False if text == "false" else None)',
     '        return bool(text)',
     'test_report_provenance.SwitchParseTests.test_value_comparison_by_type'),
    ('benchmark/report/provenance.py',
     '    base = _switch_state(rows, {k: v for k, v in mine.items() if k in keys})',
     '    base = _switch_state(rows, {})',
     'test_report_provenance.SwitchCheckTests.test_overrides_before_the_first_arm_and_a_failed_arm'),
    ('benchmark/report/provenance.py',
     '            new = dict(allowed[0][1], **{k: str(v) for k, v in wrote.items()})',
     '            new = dict(allowed[0][1])',
     'test_report_provenance.SwitchCheckTests.test_a_set_arm_changes_only_the_switches_it_wrote_on_its_nodes'),
    ('benchmark/report/make_bundle.py',
     '        problems = [p for p in res["problems"] if p not in sw_problems]',
     '        problems = list(res["problems"])',
     'test_report_bundle.SwitchProvenanceStepTests.test_a_mismatch_refuses_unless_allowed_and_keeps_the_commit_verified'),
    ('benchmark/report/make_bundle.py',
     '        raise BundleError("node switch check failed (pass --allow-provenance-mismatch to publish with a "',
     '        warn("node switch check failed (pass --allow-provenance-mismatch to publish with a "',
     'test_report_bundle.SwitchProvenanceStepTests.test_a_mismatch_refuses_unless_allowed_and_keeps_the_commit_verified'),
    ('benchmark/report/make_bundle.py',
     '    return "all %d nodes: %s" % (n, ", ".join("%s=%s" % kv for kv in sorted(pairs)))',
     '    return ""',
     'test_report_bundle.PrestartArmAssemblyTests.test_without_a_consensus_block_a_caveat_states_them'),
    ('benchmark/report/make_bundle.py',
     '        if v is None or provenance.switch_value(r["type"], v) == provenance.switch_value(r["type"], r["default"]):',
     '        if v is None:',
     'test_report_bundle.PrestartArmTests.test_row_states_the_switches_away_from_their_default'),
    ('benchmark/report/make_bundle.py',
     '    if head_switches and consensus is None:',
     '    if False:',
     'test_report_bundle.PrestartArmAssemblyTests.test_without_a_consensus_block_a_caveat_states_them'),
    # H7b. Arm windows from ready in the stage, block and propose tools; the per-arm summary.
    ('benchmark/tools/arms-summary.py',
     '            amp["amp"] = round(dev / (pages * float(PAGE)), 3)',
     '            amp["amp"] = round(dev / (pages * float(PAGE // 2)), 3)',
     'test_arms_summary.ArmsSummaryTests.test_engine_and_amplification_arithmetic'),
    ('benchmark/tools/arms-summary.py',
     '        start = a.get(F["m_ready"]) or a.get(F["m_begin"]) or a.get(F["m_start"])',
     '        start = a.get(F["m_begin"]) or a.get(F["m_start"])',
     'test_arms_summary.ArmsSummaryTests.test_rows_windows_and_types'),
    ('benchmark/tools/arms-summary.py',
     'DRIFT_LIMIT = 0.15',
     'DRIFT_LIMIT = 0.35',
     'test_arms_summary.ArmsSummaryTests.test_drift_fit_and_correction'),
    ('benchmark/tools/arms-summary.py',
     '                m["commit_us_tx_corrected"] = r1(m["commit_us_tx"] - d["slope_us_tx_per_x"] * (m["drift_x"] - d["x_first"]))',
     '                m["commit_us_tx_corrected"] = r1(m["commit_us_tx"] + d["slope_us_tx_per_x"] * (m["drift_x"] - d["x_first"]))',
     'test_arms_summary.ArmsSummaryTests.test_drift_fit_and_correction'),
    ('benchmark/tools/arms-summary.py',
     'LANDING_CLIFF_MS = 300000',
     'LANDING_CLIFF_MS = 500000',
     'test_arms_summary.ArmsSummaryTests.test_certification_votes_generators'),
    ('benchmark/tools/arms-summary.py',
     '    validators = [n for n in nodes if F["v_validator"] in n]',
     '    validators = [n for n in nodes if "validator" in n]',
     'test_arms_summary.ArmsSummaryTests.test_field_names_live_only_in_the_table'),
    # H12. The per-arm summary on a tree of blasts run by hand (bench 6 run 1: no blasts[]): rc from blast_runs[]
    # or the archived manifest copy, the arm by its begin, the copy's real phases and chaos, a resumed arm's roles.
    ('benchmark/tools/arms-summary.py',
     '        entry[F["m_rc"]] = runs[g["idx"]]',
     '        entry[F["m_rc"]] = None',
     'test_arms_summary.ArmsSummaryTests.test_blasts_run_by_hand'),
    ('benchmark/tools/arms-summary.py',
     '        bad = [b.get(F["m_rc"]) for b in blasters if b.get(F["m_rc"]) not in (None, 0)]',
     '        bad = []',
     'test_arms_summary.ArmsSummaryTests.test_blasts_run_by_hand'),
    ('benchmark/tools/arms-summary.py',
     '        entry[F["m_phases"]], entry[F["m_planned"]] = bm.get(F["m_phases"]), bm[F["m_planned"]]',
     '        pass',
     'test_arms_summary.ArmsSummaryTests.test_blasts_run_by_hand'),
    ('benchmark/tools/arms-summary.py',
     '        cands = [a for a in arms if a["arm_t0"] <= t]',
     '        cands = [a for a in arms if a["from"] <= t]',
     'test_arms_summary.ArmsSummaryTests.test_blasts_run_by_hand'),
    ('benchmark/tools/arms-summary.py',
     '        if idx not in listed:      # a blast run by hand that left no blasters/ directory',
     '        if False:',
     'test_arms_summary.ArmsSummaryTests.test_blasts_run_by_hand'),
    ('benchmark/tools/arms-summary.py',
     '        events = chaos if g["bm"] is manifest else sorted(set(chaos) | set(chaos_times(g["bm"] or {})))',
     '        events = chaos',
     'test_arms_summary.ArmsSummaryTests.test_blasts_run_by_hand'),
    ('benchmark/tools/arms-summary.py',
     '            roles, control = set(arms[-1]["roles"]) - {CONTROL}, arms[-1]["control"]',
     '            roles, control = set(), arms[-1]["control"]',
     'test_arms_summary.ArmsSummaryTests.test_a_resumed_arm_keeps_its_roles'),
    ('benchmark/tools/block-rate.py',
     '            if key == "param_arms" and w.get("ready"):',
     '            if False:',
     'test_arms_summary.ArmWindowToolsTests.test_block_rate_arm_from_ready_and_marks'),
    ('benchmark/tools/propose-latency.py',
     '            if key == "param_arms" and w.get("ready"):',
     '            if False:',
     'test_arms_summary.ArmWindowToolsTests.test_propose_latency_arm_from_ready'),
    ('benchmark/tools/stage-latency.py',
     '        span = real_mixed(entry) or merged_phase(docs, "mixed")',
     '        span = merged_phase(docs, "mixed")',
     'test_stage_latency.StageLatencyTests.test_bench6_blasts_are_windows_by_arm_and_kind_on_their_real_phases'),
    ('benchmark/tools/stage-latency.py',
     '        s = next((v[k] for k in ("ready", "start", "start_utc", "start_unix", "begin") if v.get(k) is not None), None)',
     '        s = next((v[k] for k in ("start", "start_utc", "start_unix", "begin") if v.get(k) is not None), None)',
     'test_stage_latency.StageLatencyTests.test_a_manifest_as_windows_reads_its_arms_from_ready'),
    ('benchmark/tools/stage-latency.py',
     '        items.append((w.get("name"), {"begin": w.get("ready") or w.get("begin") or w.get("start"), "end": w.get("end")}))',
     '        items.append((w.get("name"), {"begin": w.get("begin") or w.get("start"), "end": w.get("end")}))',
     'test_stage_latency.StageLatencyTests.test_a_manifest_as_windows_reads_its_arms_from_ready'),
    # H10. The one-VM probe driver.
    # gc's dry guard
    ('benchmark/benchmark-probe.sh',
     '    show "[alarm ${secs}s]" gcloud "$@"\n    [ "${DRY}" = "0" ] || return 0\n',
     '    show "[alarm ${secs}s]" gcloud "$@"\n',
     'test_probe.DryRunTests.test_plan_and_every_dry_subcommand_reach_no_gcloud'),
    # plan is always dry
    ('benchmark/benchmark-probe.sh',
     '[ "${SUB}" != plan ] || DRY=1\n',
     '\n',
     'test_probe.DryRunTests.test_plan_and_every_dry_subcommand_reach_no_gcloud'),
    # ours checks the role label
    ('benchmark/benchmark-probe.sh',
     '        and (.labels["tn-role"] // "") == "probe"\' >/dev/null 2>&1',
     "        and true' >/dev/null 2>&1",
     'test_probe.LiveFakeTests.test_down_refuses_its_name_without_its_labels'),
    # exact-name match
    ('benchmark/benchmark-probe.sh',
     'jq -c --arg n "$2" \'[.[] | select(.name == $n)] | .[0] // empty\'',
     'jq -c --arg n "$2" \'[.[] | select(.name | startswith($n))] | .[0] // empty\'',
     'test_probe.LiveFakeTests.test_down_deletes_only_its_own_labelled_instance_and_disk'),
    # attached disk waited for, never deleted
    ('benchmark/benchmark-probe.sh',
     '    while [ "${DRY}" = "0" ] && attached "${json}"; do\n',
     '    while [ "${DRY}" = "0" ] && false; do\n',
     'test_probe.LiveFakeTests.test_down_waits_for_the_boot_disk_to_go_with_the_instance'),
    # down re-indexes after its stamp
    ('benchmark/benchmark-probe.sh',
     '            BENCH_APPLY=1 bench_local_index >/dev/null || bench_warn',
     '            true || bench_warn',
     'test_probe.LiveFakeTests.test_all_deletes_the_vm_after_a_failed_run'),
    # all runs its own down after a failed run
    ('benchmark/benchmark-probe.sh',
     '    cmd_down || rc=3\n    return "${rc}"\n',
     '    return "${rc}"\n',
     'test_probe.LiveFakeTests.test_all_deletes_the_vm_after_a_failed_run'),
    # the exit trap deletes after a TERM
    ('benchmark/benchmark-probe.sh',
     '    if [ "${UP_STARTED}" = 1 ] && [ "${DOWN_DONE}" = 0 ]; then\n',
     '    if [ "${UP_STARTED}" = 1 ] && [ "${DOWN_DONE}" = 1 ]; then\n',
     'test_probe.LiveFakeTests.test_all_deletes_the_vm_when_interrupted'),
    # every arm sets the boot read_ahead_kb
    ('benchmark/benchmark-probe.sh',
     '    if [ "${step}" = ra16 ]; then ra=16; ral=16; else ra="${BOOT_RA_KB}"; ral="<boot value>"; fi\n',
     '    if [ "${step}" = ra16 ]; then ra=16; ral=16; else ra=""; ral="<boot value>"; fi\n',
     'test_probe.DryRunTests.test_arm_commands'),
    # the finish removes the arm's DB
    ('benchmark/benchmark-probe.sh',
     'rm -f -- "\\$D/mdbx.dat" "\\$D/mdbx.lck" "\\$D/probe-meta.txt" "\\$B/data/${name}.appender.log"\n',
     '\n',
     'test_probe.DryRunTests.test_plan_matches_the_golden_file'),
    # the run deadline skips an arm
    ('benchmark/benchmark-probe.sh',
     '    if [ "${DRY}" = "0" ] && [ $(( $(now) + ARM_DEADLINE + 240 )) -gt "${dl}" ]; then\n',
     '    if [ "${DRY}" = "0" ] && [ $(( $(now) + ARM_DEADLINE + 240 )) -gt "$(( dl + 999999 ))" ]; then\n',
     'test_probe.LiveFakeTests.test_all_starts_no_arm_that_would_end_past_the_run_deadline'),
    # the amplification column
    ('benchmark/benchmark-probe.sh',
     'amp="$(summary_field "${s}" "ratios:" "device/mdbx-dirtied")"',
     'amp="$(summary_field "${s}" "ratios:" "device/logical")"',
     'test_probe.LiveFakeTests.test_all_runs_the_arms_and_writes_the_summary'),
    # a dropped start session goes to the wait
    ('benchmark/benchmark-probe.sh',
     '            "") log "arm ${name}: the start session printed no ARM_START line; asking the VM" ;;\n',
     '            "") result="start failed: no ARM_START line" ;;\n',
     'test_probe.LiveFakeTests.test_a_start_session_that_dropped_is_settled_by_the_wait'),
    # the census warm-up before the read_bytes count
    ('benchmark/benchmark-probe.sh',
     'timeout 60 python3 "$C" --file "$C" --header >/dev/null 2>&1; timeout 20 fincore',
     'timeout 20 fincore',
     'test_probe.DryRunTests.test_plan_matches_the_golden_file'),
    # core expands to the never-cut eight
    ('benchmark/benchmark-probe.sh',
     '    WANT="${WANT// core / ${ARMS_CORE} }"\n',
     '\n',
     'test_probe.DryRunTests.test_arm_selection'),
    # the safety reference is the same flags without --keep-db
    ('benchmark/benchmark-probe.sh',
     'f="$(arm_field "$1" 4)"; f="${f/ --keep-db/}"',
     'f="$(arm_field "$1" 4)"',
     'test_probe.LiveFakeTests.test_all_runs_the_arms_and_writes_the_summary'),
    # a prefault that dropped fails the safety arm
    ('benchmark/benchmark-probe.sh',
     'else .outputs_grown_without_prefault == 0 end)}) as $c',
     'else .outputs_grown_without_prefault >= 0 end)}) as $c',
     'test_probe.LiveFakeTests.test_the_safety_arm_fails_when_its_prefault_drops_and_is_incomplete_alone'),
    # a missing reference is incomplete, never a pass
    ('benchmark/benchmark-probe.sh',
     'elif ([$c[]] | any(. == null)) then null else true end',
     'else true end',
     'test_probe.LiveFakeTests.test_the_safety_arm_fails_when_its_prefault_drops_and_is_incomplete_alone'),
    # outputs that grew without a prefault are counted
    ('benchmark/benchmark-probe.sh',
     'ok && $g > 0 && $p == 0 { n++;',
     'ok && $g > 0 && $p < 0 { n++;',
     'test_probe.LiveFakeTests.test_the_safety_arm_fails_when_its_prefault_drops_and_is_incomplete_alone'),
    # summary-i1 numbers stay numbers
    ('benchmark/benchmark-probe.sh',
     'then tonumber else . end)}) | add // {}',
     'then . else . end)}) | add // {}',
     'test_probe.LiveFakeTests.test_all_runs_the_arms_and_writes_the_summary'),
    # the default run deadline
    ('benchmark/benchmark-probe.sh',
     'DEADLINE_MIN=120 ARM_DEADLINE=900',
     'DEADLINE_MIN=100 ARM_DEADLINE=900',
     'test_probe.DryRunTests.test_deadlines_in_the_rendered_scripts'),
    # H11. The launchers and the arm sequencer.
    ('benchmark/launch/launch.sh',
     '[ -z "${PLACEHOLDERS}" ] || refuse "placeholders not filled',
     'true || refuse "placeholders not filled',
     'test_launch.LaunchRefusalTests.test_every_shipped_env_file_is_refused_until_its_placeholders_are_filled'),
    ('benchmark/launch/launch.sh',
     '[ -z "${dirty}" ] || refuse "the harness tree is dirty',
     'true || refuse "the harness tree is dirty',
     'test_launch.LaunchRefusalTests.test_a_dirty_harness_tree'),
    ('benchmark/launch/launch.sh',
     " ':(exclude)benchmark/launch/bench5' ",
     ' ',
     'test_launch.LaunchRefusalTests.test_the_bench5_originals_and_ignored_dirs_do_not_count_as_dirty'),
    ('benchmark/launch/launch.sh',
     'bounded "${tsecs}" gcloud auth print-access-token >/dev/null 2>&1 \\',
     'true \\',
     'test_launch.LaunchRefusalTests.test_a_stale_token'),
    ('benchmark/launch/launch.sh',
     '--reindex); GCLOUD=0;',
     '--reindex);',
     'test_launch.LaunchRefusalTests.test_segments_without_gcloud_skip_the_token'),
    ('benchmark/launch/launch.sh',
     'echo "$$" > "${pidf}"',
     'echo "$PPID" > "${pidf}"',
     'test_launch.LaunchStartTests.test_the_pid_file_holds_the_detached_session'),
    ('benchmark/launch/launch.sh',
     '    kill -0 "${p}" 2>/dev/null || return 1',
     '    return 1',
     'test_launch.LaunchRefusalTests.test_a_segment_of_the_same_run_is_running'),
    ('benchmark/launch/launch.sh',
     '[ -z "${hits}" ] || refuse',
     'true || refuse',
     'test_launch.LaunchRefusalTests.test_a_driver_that_collides_is_running'),
    ('benchmark/launch/launch.sh',
     'then unset "${v}"; fi',
     'then :; fi',
     'test_launch.LaunchStartTests.test_the_segment_gets_the_env_file_and_nothing_inherited'),
    ('benchmark/launch/launch.sh',
     'case "${val}" in *\'$\'*|*\'`\'*|*\\\\*) refuse',
     'case "${val}" in *\'NEVER\'*) refuse',
     'test_launch.LaunchRefusalTests.test_env_lines_that_break_the_rules'),
    ('benchmark/launch/launch.sh',
     'if [ "${DRY}" = 1 ]; then\n    echo "DRY RUN',
     'if [ "${DRY}" = 9 ]; then\n    echo "DRY RUN',
     'test_launch.LaunchStartTests.test_the_dry_run_starts_nothing'),
    ('benchmark/launch/run-arms.sh',
     '    if grep -qE \'^[[:space:]]*(PA_FAIL|PARAMS_FAIL) \' "${out}"; then',
     '    if false; then',
     'test_launch.ArmsStopTests.test_a_node_that_fails_its_restart_or_readback'),
    ('benchmark/launch/run-arms.sh',
     '"${out}" || true)" -ge 2 ]',
     '"${out}" || true)" -ge 3 ]',
     'test_launch.ArmsStopTests.test_two_guard_deferrals'),
    ('benchmark/launch/run-arms.sh',
     '    sleep_until "${t}"\n    sig_point "${k}" 0 "${first}"\n}',
     '    : sleep_until "${t}"\n    sig_point "${k}" 0 "${first}"\n}',
     'test_launch.ArmsTimingTests.test_it_waits_until_the_arm_is_ready'),
    ('benchmark/launch/run-arms.sh',
     'while [ "${attempt}" -le 2 ]; do',
     'while [ "${attempt}" -le 1 ]; do',
     'test_launch.ArmsRetryTests.test_a_failed_blast_is_retried_once_under_the_next_index'),
    ('benchmark/launch/run-arms.sh',
     'while [ "${attempt}" -le 2 ]; do',
     'while [ "${attempt}" -le 3 ]; do',
     'test_launch.ArmsRetryTests.test_a_second_failure_stops_the_run'),
    ('benchmark/launch/run-arms.sh',
     'case "${HEALTH_ABORTS}" in *" ${reason} "*)',
     'case "${HEALTH_ABORTS}" in *" NEVER${reason} "*)',
     'test_launch.ArmsStopTests.test_a_blast_that_aborts_on_fleet_health_is_not_retried'),
    ('benchmark/launch/run-arms.sh',
     '[ "${top%% *}" -ge "${MAXQ}" ]',
     '[ "${top%% *}" -gt "${MAXQ}" ]',
     'test_launch.ArmsGateTests.test_the_pool_gate_stops_the_run_when_the_pools_stay_high'),
    ('benchmark/launch/run-arms.sh',
     '[ "${v}" = high ] && return 1',
     '[ "${v}" = high ] && return 0',
     'test_launch.ArmsGateTests.test_the_pool_gate_stops_the_run_when_the_pools_stay_high'),
    ('benchmark/launch/run-arms.sh',
     'SATURATED=" M4 M16 M16s "',
     'SATURATED=" M16 M16s "',
     'test_launch.ArmsGateTests.test_the_gate_runs_before_saturated_blasts_only_and_is_off_at_zero'),
    ('benchmark/launch/run-arms.sh',
     '[ "${dmax}" -le "${MAX_DISK}" ] || stop',
     'true || stop',
     'test_launch.ArmsStopTests.test_health_between_steps'),
    ('benchmark/launch/run-arms.sh',
     '[ "${fsum}" = 0 ] || stop',
     'true || stop',
     'test_launch.ArmsStopTests.test_health_between_steps'),
    ('benchmark/launch/run-arms.sh',
     'select((.secs // 0) > $s)',
     'select((.secs // 0) >= $s)',
     'test_launch.ArmsStopTests.test_a_commit_stall_after_a_blast'),
    ('benchmark/launch/run-arms.sh',
     'else printf \'%s\' "$((m + 1))"; fi',
     'else printf \'%s\' "${m}"; fi',
     'test_launch.ArmsResumeTests.test_the_next_index_follows_what_the_run_used'),
    ('benchmark/launch/run-arms.sh',
     'n=$((n + 1)); c="$1-r${n}"',
     'n=$((n + 1)); c="$1"',
     'test_launch.ArmsResumeTests.test_from_arm_starts_there_under_a_new_name_when_recorded'),
    ('benchmark/launch/run-arms.sh',
     'stop "${k}" "${st}" blast-failed-twice "${st}"',
     'stop "${k}" "${st}" blast-failed-twice "$((st + 1))"',
     'test_launch.ArmsResumeTests.test_the_last_line_is_the_resume_command'),
    ('benchmark/launch/run-arms.sh',
     'if [ "${DRY}" = 1 ]; then dry_walk; exit 0; fi',
     'if [ "${DRY}" = 9 ]; then dry_walk; exit 0; fi',
     'test_launch.ArmsWalkTests.test_the_dry_run_prints_the_walk_and_reaches_no_driver'),
    ('benchmark/launch/run-arms.sh',
     'lead=$(( off + wu + pre + delay ))',
     'lead=$(( off + wu + delay ))',
     'test_launch.ArmsTimingTests.test_an_epoch_aligned_blast'),
    ('benchmark/launch/run-arms.sh',
     'M16)  kind=load  snd=600 win=16 wu=120 mix=480 cd=180;',
     'M16)  kind=load  snd=600 win=16 wu=120 mix=300 cd=180;',
     'test_launch.ArmsWalkTests.test_the_default_plan_walk'),
    ('benchmark/launch/run-arms.sh',
     'rc=0; "${PA}" --arm-file "${A_FILE[$k]}" --print-state > "${TMP}/state" 2>&1 || rc=$?',
     'rc=0; true || rc=$?',
     'test_launch.ArmsStopTests.test_an_arm_file_the_tool_refuses'),
    # H13. The driver gaps of the run-1 rehearsal: a hand run's blasts[] entry and blast type (D1, D2), the log path
    # the archive moves (D5), the walk's own log (D3); and two H11 anchors no test killed at an assertion.
    ('benchmark/launch/launch.sh',
     "    trap 'on_sig TERM 143' TERM\n",
     "",
     'test_launch.LaunchStartTests.test_the_rc_line_when_the_session_is_killed'),
    ('benchmark/launch/run-arms.sh',
     '[ "${wait}" -le "${READY_MAX}" ] || stop',
     'true || stop',
     'test_launch.ArmsTimingTests.test_a_ready_time_too_far_off'),
    ('benchmark/benchmark-blast.sh',
     '    if [ "${ACTION}" = run ] && [ "${BENCH_LIGHT_LOAD:-0}" != 1 ]; then',
     '    if [ "${ACTION}" = run ]; then',
     'test_blast_argv.BlastRunTests.test_the_light_load_arm_by_hand_leaves_blasts_to_its_sequence'),
    ('benchmark/benchmark-blast.sh',
     '    if [ "${ACTION}" = run ] && [ "${BENCH_LIGHT_LOAD:-0}" != 1 ]; then',
     '    if [ "${BENCH_LIGHT_LOAD:-0}" != 1 ]; then',
     'test_blast_argv.BlastRunTests.test_a_failed_hand_run_is_in_blasts_with_its_rc_and_a_fund_is_not'),
    ('benchmark/benchmark-blast.sh',
     '"${BLAST_RUN_STARTED}" "${ended}" "$1" "$(arm_in_force "${BLAST_RUN_STARTED}")"',
     '"${BLAST_RUN_STARTED}" "${ended}" "$1" ""',
     'test_blast_argv.BlastRunTests.test_a_hand_run_records_the_blasts_entry_a_sequence_blast_gets'),
    ('benchmark/benchmark-blast.sh',
     '"${BENCH_CHAOS:-}" "${BENCH_BLAST_KIND:-load}" \\',
     '"${BENCH_CHAOS:-}" load \\',
     'test_blast_argv.BlastRunTests.test_a_hand_run_records_the_blasts_entry_a_sequence_blast_gets'),
    ('benchmark/benchmark-blast.sh',
     "        'def num: if . == \"\" then null else (tonumber? // .) end;",
     "        'def num: .;",
     'test_blast_argv.BlastRunTests.test_a_hand_run_records_the_blasts_entry_a_sequence_blast_gets'),
    ('benchmark/benchmark-blast.sh',
     'tail_scan_secs: ($ts|tonumber), kind: $k, senders: ($sn|tonumber),',
     'tail_scan_secs: ($ts|tonumber), kind: "load", senders: ($sn|tonumber),',
     'test_blast_argv.BlastRecordTests.test_the_type_of_the_blast_is_recorded_with_it'),
    ('benchmark/benchmark-blast.sh',
     'cooldown_secs: ($cd|tonumber)}',
     'cooldown_secs: ($wu|tonumber)}',
     'test_blast_argv.BlastRecordTests.test_the_type_of_the_blast_is_recorded_with_it'),
    ('benchmark/benchmark-blast.sh',
     'and (.log as $l | $mv | index([$l])) != null then .log = $d + "/" + .log else . end) else . end',
     'and (.log as $l | $mv | index([$l])) != null then . else . end) else . end',
     'test_blast_argv.ArchiveLogPathTests.test_the_moved_log_is_pointed_at_where_it_went'),
    ('benchmark/benchmark-blast.sh',
     'and (.log as $l | $mv | index([$l])) != null then',
     'and true then',
     'test_blast_argv.ArchiveLogPathTests.test_the_moved_log_is_pointed_at_where_it_went'),
    ('benchmark/launch/run-arms.sh',
     'start_walk_log\necho "ARMS_START',
     'echo "ARMS_START',
     'test_launch.ArmsLogTests.test_the_retry_and_the_stop_are_in_the_results_log'),
    ('benchmark/launch/run-arms.sh',
     '    exec > "${TMP}/out" 2> "${TMP}/err"',
     '    exec 2> "${TMP}/err"; : > "${TMP}/out"',
     'test_launch.ArmsLogTests.test_the_retry_and_the_stop_are_in_the_results_log'),
    ('benchmark/launch/run-arms.sh',
     '    local n=0 seg="${LAUNCH_SEGMENT:-hand}"',
     '    local n=0 seg=hand',
     'test_launch.ArmsLogTests.test_a_launched_walk_names_its_segment_and_a_refusal_or_a_dry_run_writes_none'),
    ('benchmark/launch/run-arms.sh',
     '        for p in ${WALK_TEES}; do reap "${p}"; done',
     '        true',
     # H14a: launch.sh now also waits for the segment's process group (the tees are in it), so a hand walk carries this
     'test_launch.ArmsLogTests.test_a_hand_walk_exits_only_once_its_log_copy_is_whole'),
    # H14a. A stop signal never leaves a fleet action running unobserved: the walk lets a running driver call end and
    # starts nothing new, a wait between calls ends at once; launch.sh writes the rc line only once nothing of the
    # segment's process group runs.
    ('benchmark/launch/run-arms.sh',
     "trap 'on_signal TERM 143' TERM\n",
     "",
     'test_launch.LaunchSignalTests.test_a_term_to_the_arms_segment_lets_the_blast_end'),
    ('benchmark/launch/run-arms.sh',
     '    "$@" > "${TMP}/call" 2>&1 &\n    CHILD_PID=$!',
     '    "$@" > "${TMP}/call" 2>&1\n    CHILD_PID=$!',
     'test_launch.ArmsSignalTests.test_a_term_during_a_blast_lets_it_end_and_a_second_term_changes_nothing'),
    ('benchmark/launch/run-arms.sh',
     '    if [ -n "${SIG_NAME}" ]; then\n        echo "  run-arms: $1 again',
     '    if false; then\n        echo "  run-arms: $1 again',
     'test_launch.ArmsSignalTests.test_a_term_during_a_blast_lets_it_end_and_a_second_term_changes_nothing'),
    ('benchmark/launch/run-arms.sh',
     '    [ -n "${SIG_NAME}" ] || return 0\n    read -r -a w',
     '    return 0\n    read -r -a w',
     'test_launch.ArmsSignalTests.test_a_term_during_a_blast_lets_it_end_and_a_second_term_changes_nothing'),
    ('benchmark/launch/run-arms.sh',
     '        if [ -n "${SIG_NAME}" ]; then\n            step_line "${st}" "${t}" "$([ "${frc}" = 0 ]',
     '        if false; then\n            step_line "${st}" "${t}" "$([ "${frc}" = 0 ]',
     'test_launch.ArmsSignalTests.test_a_term_during_a_blast_lets_it_end_and_a_second_term_changes_nothing'),
    ('benchmark/launch/run-arms.sh',
     '    if [ -n "${NAP_PID}" ]; then kill "${NAP_PID}" 2>/dev/null || true; fi\n}',
     '    true\n}',
     'test_launch.ArmsSignalTests.test_a_term_between_calls_stops_at_once'),
    ('benchmark/launch/run-arms.sh',
     '[ "${d}" -le 30 ] || d=30; nap "${d}"; done; }',
     '[ "${d}" -le 30 ] || d=30; sleep "${d}"; done; }',
     'test_launch.ArmsSignalTests.test_a_term_between_calls_stops_at_once'),
    ('benchmark/launch/run-arms.sh',
     '        [ -z "${SIG_NAME}" ] || return 2',
     '        true',
     'test_launch.ArmsSignalTests.test_a_term_between_calls_stops_at_once'),
    ('benchmark/launch/run-arms.sh',
     '    [ -z "${SIG_NAME}" ] || cut=1',
     '    true',
     'test_launch.ArmsSignalTests.test_a_term_between_calls_stops_at_once'),
    ('benchmark/launch/run-arms.sh',
     'stop_rc() { if [ -n "${SIG_NAME}" ]; then echo "${SIG_RC}"; else echo 1; fi; }',
     'stop_rc() { echo 1; }',
     'test_launch.ArmsSignalTests.test_an_apply_runs_to_its_end_and_its_own_stop_keeps_its_reason'),
    ('benchmark/launch/run-arms.sh',
     '    sig_point "${k}" "${after}" "${at}"\n    if [ "${HEALTH_SECS}" = 0 ]',
     '    if [ "${HEALTH_SECS}" = 0 ]',
     'test_launch.LaunchSignalTests.test_a_term_to_the_arms_segment_lets_the_blast_end'),
    ('benchmark/launch/launch.sh',
     '        echo "== ${seg} signal $1 $(utc): passed to pid ${child}; the rc line follows once nothing of the segment runs"\n',
     '',
     'test_launch.LaunchSignalTests.test_a_term_to_another_segment_reaches_its_driver_as_before'),
    ('benchmark/launch/launch.sh',
     '    [ -z "${sig_name}" ] || echo "== ${seg} driver pid=${child} exit=${rc} after ${sig_name} $(utc)"',
     '    true',
     'test_launch.LaunchSignalTests.test_a_term_to_another_segment_reaches_its_driver_as_before'),
    ('benchmark/launch/launch.sh',
     '            [ "${pg}" = "$$" ] && [ "${pid}" != "$$" ]',
     '            [ "${pg}" = "NEVER" ] && [ "${pid}" != "$$" ]',
     'test_launch.LaunchSignalTests.test_a_process_that_outlives_the_driver_holds_the_rc_line_back'),
    ('benchmark/launch/launch.sh',
     '    while [ -n "${LEFT}" ] && [ "$(date +%s)" -lt "${deadline}" ]; do',
     '    while false; do',
     'test_launch.LaunchSignalTests.test_a_process_that_outlives_the_driver_holds_the_rc_line_back'),
    ('benchmark/launch/launch.sh',
     '    if [ -n "${LEFT}" ]; then\n        printf',
     '    if false; then\n        printf',
     'test_launch.LaunchSignalTests.test_a_process_left_running_is_named_instead_of_an_end'),
    ('benchmark/launch/launch.sh',
     '                [ "${what:-none}" = none ] || state="stopping after ${what}"',
     '                true',
     'test_launch.LaunchSignalTests.test_a_term_to_the_arms_segment_lets_the_blast_end'),
    ('benchmark/launch/launch.sh',
     '            "== "*" LEFT_RUNNING "*) state=',
     '            "== "*" NEVER "*) state=',
     'test_launch.LaunchSignalTests.test_a_process_left_running_is_named_instead_of_an_end'),
    # H8. The gate (tests/gate.sh) and this checker's --modules.
    # the gate lists its own subshells as load
    ('benchmark/tests/gate.sh',
     '        $1 == self || $2 == self { next }',
     '        $1 == self { next }',
     'test_gate.LoadTests.test_the_gate_never_lists_its_own_processes'),
    # a bench driver run by bash is not load
    ('benchmark/tests/gate.sh',
     '            s = (a1 ~ /^(bash|sh|dash|zsh|env|python|python3|python3\\.[0-9]+)$/) ? a2 : a1',
     '            s = a1',
     'test_gate.LoadTests.test_every_kind_of_load_refuses'),
    # a loaded host does not refuse the gate
    ('benchmark/tests/gate.sh',
     '[ "${LOAD}" = loaded ] && [ "${UNDER_LOAD}" != "1" ]; then',
     'false; then',
     'test_gate.LoadTests.test_a_cargo_build_refuses_the_gate_and_is_named'),
    # the suite runs unscaled
    ('benchmark/tests/gate.sh',
     'export BENCH_TEST_TIMEOUT_SCALE="${BENCH_TEST_TIMEOUT_SCALE:-3}"',
     'export BENCH_TEST_TIMEOUT_SCALE="${BENCH_TEST_TIMEOUT_SCALE:-1}"',
     'test_gate.OutcomeTests.test_all_green_on_a_quiet_host'),
    # a module that fails alone passes the gate
    ('benchmark/tests/gate.sh',
     '[ "${ISO_OK}" = "1" ] && [ "${MUT}" = "0" ] || exit 1',
     '[ "${MUT}" = "0" ] || exit 1',
     'test_gate.IsolatedFailTests.test_a_module_that_fails_alone_fails_the_gate_and_each_is_named'),
    # --modules does not narrow the mutation cases
    ('benchmark/tests/check_mutations.py',
     # split: the case's own literal must not be a second copy of the line it mutates
     '    chosen = [c for c in cases if not wanted or c[3].partition(".")[0] ' + 'in wanted]',
     '    chosen = list(cases)',
     'test_gate.RealCheckerListTests.test_list_narrowed_to_one_module'),
    # H14b. The readers after the hand-run blasts[] entries: a failed blast (rc not 0) is never a window and the
    # floor takes the last rc-0 entry of its index; the blast phases of the three window tools and cert-rate's marks;
    # two tests that let a mutant die in str.index or a BundleError now fail at an assertion.
    ('benchmark/tools/stage-latency.py',
     '        if failed(entry):',
     '        if False:',
     'test_stage_latency.StageLatencyTests.test_a_failed_blast_gets_no_window_and_is_listed_not_measured'),
    ('benchmark/tools/stage-latency.py',
     '        not_measured.extend("blast index %s (%s): rc %s" % (b["index"], blast_name(b), b["rc"]) for b in bad)',
     '        pass',
     'test_stage_latency.StageLatencyTests.test_a_failed_blast_gets_no_window_and_is_listed_not_measured'),
    ('benchmark/report/kpis.py',
     '    ok = [e for e in entries if e.get("rc") in (0, None)]',
     '    ok = list(entries)',
     'test_report_kpis.KpisCliTests.test_floor_blast_dir_takes_the_last_rc0_entry_of_its_index'),
    ('benchmark/report/kpis.py',
     '    e = ok[-1] if ok else {}',
     '    e = entries[0] if entries else {}',
     'test_report_kpis.KpisCliTests.test_floor_blast_dir_takes_the_last_rc0_entry_of_its_index'),
    ('benchmark/report/kpis.py',
     '        blast, floor_caveats = floor_from_dir(live, os.path.abspath(a.floor_blast_dir))',
     '        blast, floor_caveats = blast_from_dir(live, os.path.abspath(a.floor_blast_dir)), []',
     'test_report_kpis.KpisCliTests.test_floor_blast_dir_takes_the_last_rc0_entry_of_its_index'),
    ('benchmark/tools/cert-rate.py',
     '        if b.get("rc") not in (None, 0):',
     '        if False:',
     'test_cert_rate.CertRateTests.test_bench6_blast_phases_from_rc0_entries_and_the_idle_mark'),
    ('benchmark/tools/cert-rate.py',
     '        top_copied = top_copied or b["phases"] == m.get("phases")',
     '        top_copied = top_copied',
     'test_cert_rate.CertRateTests.test_bench6_blast_phases_from_rc0_entries_and_the_idle_mark'),
    ('benchmark/tools/cert-rate.py',
     '            out.extend(marks)\n    out.extend(blasts)\n',
     '    out.extend(blasts)\n',
     'test_cert_rate.CertRateTests.test_bench6_blast_phases_from_rc0_entries_and_the_idle_mark'),
    ('benchmark/tools/block-rate.py',
     '        if b.get("rc") not in (None, 0):',
     '        if False:',
     'test_block_rate.BlockRateTests.test_bench6_blast_phases_from_rc0_entries_only'),
    ('benchmark/tools/block-rate.py',
     '        top_copied = top_copied or b["phases"] == m.get("phases")',
     '        top_copied = top_copied',
     'test_block_rate.BlockRateTests.test_bench6_blast_phases_from_rc0_entries_only'),
    ('benchmark/tools/propose-latency.py',
     '        if b.get("rc") not in (None, 0):',
     '        if False:',
     'test_propose_latency.ProposeLatencyTests.test_bench6_blast_phases_from_rc0_entries_only'),
    ('benchmark/tools/propose-latency.py',
     '        top_copied = top_copied or b["phases"] == m.get("phases")',
     '        top_copied = top_copied',
     'test_propose_latency.ProposeLatencyTests.test_bench6_blast_phases_from_rc0_entries_only'),
    ('benchmark/report/make_bundle.py',
     '    return isinstance(arm, dict) and arm.get("via") == "prestart" and isinstance(arm.get("switches"), dict)',
     '    return False',
     'test_report_bundle.PrestartArmTests.test_row_states_the_switches_away_from_their_default'),
    ('benchmark/benchmark-probe.sh',
     '        echo "[ \\"\\$HOST_STEP_RC\\" = 0 ] || { echo \\"ARM_START ${name} failed host step\\"; exit 1; }"',
     '        echo "true"',
     'test_probe.DryRunTests.test_arm_commands'),
    # H14b, part 2: the arm summary's bench-6 inputs (storage incl. the measured advice state and refaults, sealed keep,
    # the admission bound, parent grace, the vote fix, cycle time); a field left off a line is n/a, never 0.
    ('benchmark/tools/arms-summary.py',
     '        if left_off:      # a field left off a line is unknown, never 0 (bench6-contract: unreadable source -> no field)',
     '        if False:',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '    vals = [p[3][k] for p in ps]\n',
     '    vals = [p[3][k] or 0 for p in ps]\n',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '            ratios[n] = round(sum(x for x, _ in pts[1:]) / float(pts[-1][1] - pts[0][1]), 3)',
     '            ratios[n] = round(sum(x for x, _ in pts) / float(pts[-1][1] - pts[0][1]), 3)',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '            refused = [t for t in nds[n].advice_refused if arm["arm_t0"] <= t < b]',
     '            refused = []',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '        off = [n for n in validators if seen[n] and any(v != F["v_true"] for v in seen[n])]',
     '        off = []',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     'for x in (nds[n].builders if n in nds else []) if arm["arm_t0"] <= x[0] < b])',
     'for x in (nds[n].builders if n in nds else []) if x[0] < b])',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '                if t is None or not (msg in anytime or self.inside(t)):',
     '                if t is None or not self.inside(t):',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '    inc = [max(0.0, y[1] - x[1]) for _, xs in pts or [] for x, y in zip(xs, xs[1:])]',
     '    inc = [max(0.0, y[1]) for _, xs in pts or [] for x, y in zip(xs, xs[1:])]',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '        waits = [x for x in graces if x > 0]',
     '        waits = list(graces)',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '    lag = [p[3] - p[4] for p in hdr if p[3] is not None and p[4] is not None]',
     '    lag = [p[4] - p[3] for p in hdr if p[3] is not None and p[4] is not None]',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '            if "proc_written_bytes" in e and switch_on(r["arm_rec"], F["sw_pipelined"]):',
     '            if False:',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '            amp[key] = r1((have[-1][k] - have[0][k]) * 60.0 / (have[-1]["c_ts"] - have[0]["c_ts"]))',
     '            amp[key] = r1((have[-1][k] - have[0][k]) * 30.0 / (have[-1]["c_ts"] - have[0]["c_ts"]))',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
    ('benchmark/tools/arms-summary.py',
     '            F["msg_grace_ended"], F["msg_builder"], F["msg_advice_refused"]]',
     '            F["msg_grace_ended"]]',
     'test_arms_summary.ArmsSummaryTests.test_bench6_arm_inputs'),
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
    # The persist sampler's smoke tests need a disk-backed directory; the copied tree lives on /tmp, a tmpfs
    # on some hosts, where they would skip. The repo's own scratch (gitignored) is one when nothing else is set.
    if not env.get("PERSIST_SMOKE_DIR") and (repo / "benchmark" / "work").is_dir():
        env["PERSIST_SMOKE_DIR"] = str(repo / "benchmark" / "work")
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


def module_names(spec):
    """{test_x, ...} from "a,test_b,c.py" (empty: every module)."""
    names = set()
    for m in (s.strip() for s in spec.split(",")):
        m = m[:-3] if m.endswith(".py") else m
        if m:
            names.add(m if m.startswith("test_") else "test_" + m)
    return names


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check that each listed mutation is killed by its test.")
    parser.add_argument("--list", action="store_true", help="print the selected cases (test, file) and exit")
    parser.add_argument("--modules", default="",
                        help="comma-separated test modules (test_x or x): only the cases whose test is in one")
    parser.add_argument("--jobs", type=int, default=1, help="cases checked at a time (each in its own trees)")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    wanted = module_names(args.modules)
    chosen = [c for c in cases if not wanted or c[3].partition(".")[0] in wanted]
    if args.list:
        for name, _, _, test in chosen:
            print(f"  {test}  {name}")
        print(f"{len(chosen)} mutation case(s)")
        return 0
    results = []
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        # map() yields in case order, so the per-case lines read the same at any --jobs.
        for (name, _, _, test), (outcome, detail) in zip(chosen, pool.map(lambda c: check(*c), chosen)):
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
