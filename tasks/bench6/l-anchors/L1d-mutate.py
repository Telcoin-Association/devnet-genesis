"""L1d mutation anchors: each mutation of benchmark/benchmark-deploy.sh must fail the named test(s).

Usage: python3 mutate.py <tree>   (a copy of the repo subset; benchmark/tests/test_node_deploy.py inside it).
Each anchor occurs exactly once; the file is restored after each case and checked at the end.
"""
import subprocess
import sys
from pathlib import Path

ND = "test_node_deploy."
MUTATIONS = [
    ("machine_vcpus without the -lssd strip",
     '    local n t="${1%-lssd}"\n',
     '    local n t="${1}"\n',
     [ND + "QuotaTests.test_one_cpu_line_per_node_and_local_ssd"]),
    ("region_needs back to MACHINE_TYPE for every node",
     '        t="${NODE_MACHINE_TYPES[$i]}"\n        nc="$(machine_vcpus "${t}" "${z}")"\n',
     '        t="${MACHINE_TYPE}"\n        nc="$(machine_vcpus "${t}" "${z}")"\n',
     [ND + "QuotaTests.test_one_cpu_line_per_node_and_local_ssd"]),
    ("zone_fallback_check against MACHINE_TYPE",
     "            out=\"$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe \"${t}\" --zone=\"${z}\" \\\n",
     "            out=\"$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe \"${MACHINE_TYPE}\" --zone=\"${z}\" \\\n",
     [ND + "StockoutTests.test_a_fallback_zone_without_the_nodes_type_is_reported_by_step_0"]),
    ("bench_create_node with MIGRATE",
     "        --maintenance-policy=TERMINATE \\\n",
     "        --maintenance-policy=MIGRATE \\\n",
     [ND + "OptionETests.test_bench_argv_is_create_instances_argv_but_the_maintenance_policy"]),
    ("a -lssd type also sent through create-instances.sh",
     '                case "${t}" in *-lssd) continue ;; esac\n                echo "    + BENCH_CREATE_MACHINE_TYPE',
     '                echo "    + BENCH_CREATE_MACHINE_TYPE',
     [ND + "OptionETests.test_two_create_instances_calls_and_six_bench_creates"]),
    ("the live guard before the bench create removed",
     '    [ "${BENCH_APPLY}" = "1" ] || return 0\n    bench_run gcloud beta compute instances create',
     '    bench_run gcloud beta compute instances create',
     [ND + "OptionETests.test_the_live_guard_makes_a_dry_bench_create_print_and_call_nothing"]),
    ("zones.env not written up front with BENCH_NODE_ZONES",
     "        zone_overrides_record\n        zones_env_write\n",
     "        zone_overrides_record\n",
     [ND + "ZoneOverrideTests.test_overrides_are_recorded_once_and_zones_env_is_written"]),
    ("zone_fallback_record names MACHINE_TYPE",
     '    t="$(node_machine_type "$1")"\n    ZONES[$1]="$3"\n',
     '    t="${MACHINE_TYPE}"\n    ZONES[$1]="$3"\n',
     [ND + "StockoutTests.test_a_lssd_stockout_moves_that_node_alone"]),
    ("C4 metric checked like any other (L1b's quota_check hunk undone)",
     '            if [ -n "${why}" ] && [ -z "${have}" ]; then\n',
     '            if false; then\n',
     [ND + "QuotaTests.test_c4_cpus_are_not_checked_with_the_reason_and_never_stop"]),
    ("a headroom jq prints as 9.2e+18 compared as an integer",
     '                         | if . >= 9007199254740992 then "unlimited" else . end][0] // empty',
     '                         ][0] // empty',
     [ND + "QuotaTests.test_c4_cpus_are_not_checked_with_the_reason_and_never_stop"]),
    ("zone_overrides recorded again on a re-run",
     '    [ "$(jq -r \'has("zone_overrides")\' "$(bench_manifest)" 2>/dev/null || true)" != true ] || return 0\n',
     "",
     [ND + "ZoneOverrideTests.test_overrides_are_recorded_once_and_zones_env_is_written"]),
    ("the fleet line counts MACHINE_TYPE for every node",
     '    groups="$(machine_groups)"\n    case "${groups}" in\n',
     '    groups="${MACHINE_TYPE}"\n    case "${groups}" in\n',
     [ND + "OptionETests.test_plan_names_every_type_and_calls_nothing"]),
    ("bench_create_nodes does not skip a node that exists",
     "            echo \"Instance ${inst} already exists in ${ZONES[$i]} — skipping.\"\n            continue\n",
     "            echo \"Instance ${inst} already exists in ${ZONES[$i]} — skipping.\"\n",
     [ND + "OptionETests.test_a_rerun_skips_every_node_that_exists"]),
]


def main():
    tree = Path(sys.argv[1]).resolve()
    script = tree / "benchmark" / "benchmark-deploy.sh"
    orig = script.read_text()
    bad = 0
    try:
        for name, old, new, tests in MUTATIONS:
            n = orig.count(old)
            if n != 1:
                print("ANCHOR %s: found %d times" % (name, n))
                bad += 1
                continue
            script.write_text(orig.replace(old, new))
            p = subprocess.run([sys.executable, "-m", "unittest"] + tests, cwd=str(tree / "benchmark" / "tests"),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=900)
            killed = p.returncode != 0 and "FAILED" in p.stdout
            print("%s %s -> %s" % ("KILLED " if killed else "SURVIVED", name, ", ".join(tests)))
            bad += 0 if killed else 1
            script.write_text(orig)
    finally:
        script.write_text(orig)
    print("RESTORED" if script.read_text() == orig else "NOT RESTORED")
    print("EXIT=%d" % (1 if bad else 0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
