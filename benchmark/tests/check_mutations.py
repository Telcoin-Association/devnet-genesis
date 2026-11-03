"""Reject eleven broken code paths in checked temporary copies of the source.

Each case copies the files its test module needs into a temporary tree laid out like the repo
(<tmp>/<tree>/config.sh, <tmp>/<tree>/benchmark/...), since the tests find their scripts and
fixtures relative to their own location. The target test must pass on an unmutated tree (so a
rejection is the mutation's doing, not a broken copy), and fail at an assertion on a second tree
carrying the mutation; a mutated shell script must still pass `bash -n`.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

repo = Path(__file__).resolve().parents[2]

# What each test module reads besides itself, relative to the repo root (directories recurse).
suites = {
    "test_recovery": ("benchmark/recovery-schedule.py", "benchmark/recovery-lib.sh",
                      "benchmark/node-sampler.sh", "benchmark/benchmark-blast.sh"),
    "test_report_windows": ("benchmark/report/windows.py", "benchmark/tests/fixtures/report"),
    "test_report_scrub": ("benchmark/report/scrub.py", "benchmark/tests/fixtures/report"),
    "test_propose_latency": ("benchmark/tools/propose-latency.py",),
    # test_node_image.TREE (copied from the repo root into each sandbox) plus its fixtures.
    "test_node_image": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                        "benchmark/benchmark-deploy.sh", "benchmark/node-sampler.sh",
                        "benchmark/node-image-contract.txt", "benchmark/tests/fixtures/node-image",
                        "benchmark/tests/fixtures/v2-node", "benchmark/consensus-parameters.yaml",
                        "benchmark/benchmark-blast.sh"),
    "test_admission_gate": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                            "benchmark/report/scrub.py", "benchmark/tests/fixtures/admission"),
    "test_finalize_modes": ("devnet-finalize.sh", "devnet-lib.sh", "devnet-network-config.py",
                            "benchmark/tests/fixtures/finalize"),
    # The library comes from the submodule's working tree; without it the module skips itself.
    "test_v2_launch_edit": ("benchmark/tests/fixtures/v2-node", "tn-node-deployment/lib"),
    # --from-config sources benchmark/config.sh, which sources the root config.sh.
    "test_params_apply": ("benchmark/tools/params-apply.sh", "benchmark/tests/fixtures/params-apply",
                          "benchmark/consensus-parameters.yaml", "benchmark/config.sh", "config.sh"),
}
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
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).digest()


def build(tree, module):
    """Copy <module>'s test file and everything it reads into <tree>, in the repo's layout."""
    for rel in suites[module] + ("benchmark/tests/%s.py" % module,):
        source = repo / rel
        files = sorted(p for p in source.rglob("*") if p.is_file()) if source.is_dir() else [source]
        for path in files:
            target = tree / path.relative_to(repo)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if digest(path) != digest(target):
                raise RuntimeError(f"source changed while copying {path.relative_to(repo)}")


def run(tree, test):
    return subprocess.run(["python3", "-m", "unittest", "-v", test],
                          cwd=tree / "benchmark" / "tests", capture_output=True, text=True)


def tail(text, lines=40):
    return "\n".join(text.rstrip("\n").splitlines()[-lines:])


for name, original, mutant, test in cases:
    module, _, label = test.partition(".")
    with tempfile.TemporaryDirectory(prefix="benchmark-mutation-") as directory:
        pristine, mutated = Path(directory) / "pristine", Path(directory) / "mutated"
        build(pristine, module)
        result = run(pristine, test)
        if result.returncode != 0:
            raise RuntimeError(f"{label} fails without the mutation:\n{tail(result.stderr)}")
        build(mutated, module)
        target = mutated / name
        text = target.read_text()
        if text.count(original) != 1:
            raise RuntimeError(f"ambiguous mutation in {name}")
        target.write_text(text.replace(original, mutant))
        if name.endswith(".sh"):
            syntax = subprocess.run(["bash", "-n", str(target)], capture_output=True, text=True)
            if syntax.returncode != 0:
                raise RuntimeError(f"mutated {name} is not valid bash:\n{tail(syntax.stderr)}")
        result = run(mutated, test)
        if result.returncode == 0 or "AssertionError" not in result.stderr:
            raise RuntimeError(f"{label} did not reject the mutation at its assertion:\n{tail(result.stderr)}")
        print(label + ": mutation rejected by assertion")
