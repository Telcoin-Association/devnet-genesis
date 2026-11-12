"""L1c mutation anchors: each mutation of benchmark/benchmark-deploy.sh must fail the named test(s).

Usage: python3 L1c-mutate.py <tree>   (a copy of the repo subset the deploy tests need, benchmark/tests inside it;
no .git, so the tests that compare with the harness base skip and none is used as an anchor).
The named tests must pass on the unmutated copy first. Each anchor occurs exactly once; the file is restored after
each case and checked at the end.
"""
import subprocess
import sys
from pathlib import Path

LD = "test_local_ssd_deploy."
MUTATIONS = [
    ("step 3's knob-off early return dropped",
     '    [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ] || return 0\n    local nodes jobs log i inst out rec mk n=0 nd=0 nk=0 nr=0 failed=""\n',
     '    local nodes jobs log i inst out rec mk n=0 nd=0 nk=0 nr=0 failed=""\n',
     [LD + "KnobUnsetTests.test_step_3_is_the_serial_markers_alone"]),
    ("a failed LSSD_MOUNT line does not stop step 3",
     '    [ -z "${failed}" ] || bench_die "step 3: the data directory is not on the local SSD of${failed}',
     '    [ -z "${failed}" ] || bench_warn "step 3: the data directory is not on the local SSD of${failed}',
     [LD + "OptionEStep3Tests.test_a_lost_node_stops_the_step_naming_it_and_the_others_are_kept"]),
    ("the local-SSD check after the probes instead of before",
     '{ [ -z "${chk}" ] || printf \'%s\\n\' "${chk}"; bench_fsync_probe_script "${inst}"; bench_host_probe_script "${inst}"; bench_prestart_script "${inst}"; }',
     '{ bench_fsync_probe_script "${inst}"; bench_host_probe_script "${inst}"; [ -z "${chk}" ] || printf \'%s\\n\' "${chk}"; bench_prestart_script "${inst}"; }',
     [LD + "OptionEStep7Tests.test_the_check_comes_first_on_the_six_and_nowhere_else"]),
    ("the local-SSD check on the boot-disk nodes too",
     '    if [ "${NODE_DATADIR_LSSD[$1]}" = 1 ]; then\n        chk=',
     '    if [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ]; then\n        chk=',
     [LD + "OptionEStep7Tests.test_the_check_comes_first_on_the_six_and_nowhere_else"]),
    ("data_disk written under instances[].disks",
     "'map(.data_disk = $m[.name])'",
     "'map(.disks = [$m[.name]])'",
     [LD + "OptionEStep2Tests.test_every_instance_gets_its_data_disk_and_none_under_disks"]),
    ("the live guard before the mount session removed",
     '    [ "${BENCH_APPLY}" = "1" ] || return 0\n    bench_lssd_mount_script "${inst}"',
     '    bench_lssd_mount_script "${inst}"',
     [LD + "OptionEStep3Tests.test_the_live_guard_keeps_a_dry_mount_session_from_any_call"]),
    ("step 2's data_disk written with the knob off",
     '    if [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ]; then\n        dd="$(data_disk_plan)"',
     '    if true; then\n        dd="$(data_disk_plan)"',
     [LD + "KnobUnsetTests.test_step_2_writes_no_data_disk"]),
    ("a resumed node counted as done",
     ' resumed) nr=$((nr + 1)) ;; esac',
     ' resumed) nd=$((nd + 1)) ;; esac',
     [LD + "OptionEStep3Tests.test_a_rerun_keeps_and_resumes"]),
    ("--print-lssd-mount does not refuse a boot-disk node",
     '    [ "${NODE_DATADIR_LSSD[$_i]}" = 1 ] || bench_die',
     '    true || bench_die',
     [LD + "DryPathTests.test_print_lssd_mount_refuses_a_boot_disk_node_and_a_stranger"]),
    ("the plan's step-3 lines with the knob off",
     '    [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ] || return 0\n    local i names="" dirs',
     '    local i names="" dirs',
     [LD + "DryPathTests.test_a_lssd_node_with_the_knob_off_is_refused"]),
    ("a node's record not merged into instances[].data_disk",
     '.instances |= map(if .name == $n then .data_disk = ((.data_disk // {}) + $o) else . end)',
     '.instances |= map(if .name == $n then . else . end)',
     [LD + "OptionEStep3Tests.test_the_six_are_mounted_recorded_and_summed"]),
]


def run(tree, tests):
    return subprocess.run([sys.executable, "-m", "unittest"] + tests, cwd=str(tree / "benchmark" / "tests"),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=900)


def main():
    tree = Path(sys.argv[1]).resolve()
    script = tree / "benchmark" / "benchmark-deploy.sh"
    orig = script.read_text()
    bad = 0
    anchored = sorted({t for m in MUTATIONS for t in m[3]})
    p = run(tree, anchored)
    if p.returncode != 0 or "skipped" in p.stdout.splitlines()[-1]:
        print(p.stdout[-3000:])
        print("BASELINE FAILED")
        print("EXIT=1")
        return 1
    print("BASELINE ok: %d anchored tests pass unmutated" % len(anchored))
    try:
        for name, old, new, tests in MUTATIONS:
            n = orig.count(old)
            if n != 1:
                print("ANCHOR %s: found %d times" % (name, n))
                bad += 1
                continue
            script.write_text(orig.replace(old, new))
            p = run(tree, tests)
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
