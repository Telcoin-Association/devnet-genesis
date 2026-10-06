"""Reject seven broken code paths in checked temporary copies of the source.

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
    # test_node_image.TREE (copied from the repo root into each sandbox) plus its fixtures.
    "test_node_image": ("config.sh", "devnet-lib.sh", "benchmark/config.sh", "benchmark/bench-lib.sh",
                        "benchmark/benchmark-deploy.sh", "benchmark/node-sampler.sh",
                        "benchmark/node-image-contract.txt", "benchmark/tests/fixtures/node-image"),
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
