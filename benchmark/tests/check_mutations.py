"""Reject four broken recovery paths in checked temporary copies of the source."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

source = Path(__file__).resolve().parents[1]
cases = [
    ("recovery-schedule.py", 'first_kill = info["epoch_start_unix"] + duration - before_close',
     "first_kill = earliest_kill + duration - before_close",
     "ScheduleTests.test_snapshot_pins_registry_read_and_resolves_closing_block"),
    ("recovery-lib.sh", "else (($counts[$node] // 0) + 1)", "else 0",
     "WatcherTests.test_one_frozen_validator_while_peers_advance"),
    ("node-sampler.sh", 'block="$(block_number)"', 'block=""',
     "SamplerTests.test_csv_upgrade_block_capture_and_minute_inventory"),
    ("recovery-lib.sh", '! tar -tzf "${temporary}" >/dev/null', "false",
     "EvidenceTests.test_archive_bytes_preserved_and_invalid_stream_rejected"),
]
for name, original, mutant, test in cases:
    with tempfile.TemporaryDirectory(prefix="benchmark-mutation-") as directory:
        overlay = Path(directory) / "benchmark"
        (overlay / "tests").mkdir(parents=True)
        for path in ("recovery-schedule.py", "recovery-lib.sh", "node-sampler.sh",
                     "benchmark-blast.sh", "tests/test_recovery.py"):
            shutil.copy2(source / path, overlay / path)
            if hashlib.sha256((source / path).read_bytes()).digest() != \
                    hashlib.sha256((overlay / path).read_bytes()).digest():
                raise RuntimeError(f"source changed while copying {path}")
        target = overlay / name
        text = target.read_text()
        if text.count(original) != 1:
            raise RuntimeError(f"ambiguous mutation in {name}")
        target.write_text(text.replace(original, mutant))
        result = subprocess.run(["python3", "-m", "unittest", "-v", "test_recovery." + test],
                                cwd=overlay / "tests", capture_output=True, text=True)
        if result.returncode == 0 or "AssertionError" not in result.stderr:
            raise RuntimeError(f"{test} did not reject the mutation at its assertion:\n{result.stderr}")
        print(test + ": mutation rejected by assertion")
