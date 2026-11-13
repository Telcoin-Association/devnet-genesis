"""benchmark-blast.sh fund (R1-D5): a prepare that timed out waiting for its top-ups is not a success.

In bench 6 run 1 the funds of indices 3 and 15 logged `prepare: timed out waiting for top-ups to land
still_short=2200` (and 1600), the funder still reported `BENCH_FUND_DONE rc=0 reason=ok`, and both blasts ran
with senders that had no balance. do_fund now reads the last still_short=<n> of the newest funder/*.txgen-*.log
after the copy; above 0 it warns, records .fund.still_short, runs the prepare once more and fails the step with
fund-short-<n> when that one is short too.

do_fund runs in bash with the driver's real functions and stubs for everything remote (the VM create, the serial
wait, the bucket copy, the delete). fixtures/fund-short/short-2200.txgen.log, short-1600.txgen.log and
healthy.txgen.log are the prepare lines of run 1's funder logs (indices 3, 15 and 2); retry-ok.txgen.log and
retry-short-700.txgen.log are second prepares in the same format. do_fund-4356229.sh is do_fund as run 1 had
it: on every input without a still_short above 0 the new one must print, record and call exactly what it did.
"""
import json
from pathlib import Path
import tempfile
import unittest

import test_blast_argv as tba

BENCH = tba.BENCH
FIX = Path(__file__).resolve().parent / "fixtures" / "fund-short"
SCRIPT = BENCH / "benchmark-blast.sh"
PREFIX = tba.GS + "bucket/rtest/index-%d/funder"
MANIFEST = {"fund": {"run_index": 2, "bucket_prefix": PREFIX % 2}, "notes": [], "timestamps": {}}

# Every remote step is a stub that logs to $WORK/calls. The k-th create's bucket copy brings $WORK/log-<k> into
# funder/ as the generator names it; COPY_FAIL lists the copies that fail.
HARNESS = r'''
set -euo pipefail
BENCH_RESULTS_DIR="$WORK/results"; BENCH_APPLY=1; BENCH_RUN_INDEX="${IDX:-3}"; KEEP="${KEEP:-0}"
BENCH_BUCKET=bucket; BENCH_RUN_ID=rtest; PROJECT_ID=project; FUNDER=bench-funder; ZONES=(zone-a)
VAL_COUNT=10; BENCH_SENDERS=600; FUND_COPIED=0
bench_now_iso() { echo 2026-01-01T00:00:00Z; }
calls() { echo "$*" >> "$WORK/calls"; }
preflight() { :; }
node_url() { echo http://node-01.invalid:8545; }
set_aside_prev_funder() { :; }
gcloud() { calls "gcloud $*"; }
bench_instance_json() { calls "describe $1"; if [ -f "$WORK/vm" ]; then echo '{"name": "bench-funder"}'; fi; }
create_vm() { calls "create $*"; echo x >> "$WORK/creates"; touch "$WORK/vm"; }
assert_load_vm() { calls "assert $1"; }
delete_vms() { calls "delete $2"; rm -f "$WORK/vm"; }
bench_serial_wait() { calls "wait $1"; echo "      ✓ $1: '$3' (after 0s)"; }
bench_serial_last() { echo "${MARKER:-BENCH_FUND_DONE rc=0 reason=ok}"; }
copy_prefix() {
    local k; k="$(wc -l < "$WORK/creates" | tr -d ' ')"
    calls "copy $1 #$k"
    case " ${COPY_FAIL:-} " in *" $k "*) bench_warn "copy of $1 failed"; return 1 ;; esac
    mkdir -p "${BENCH_RESULTS_DIR}/$2"
    [ ! -f "$WORK/log-$k" ] || cp "$WORK/log-$k" "${BENCH_RESULTS_DIR}/$2/bench-funder.txgen-2026010${k}T000000Z.log"
}
'''
LIB = tba.shell_functions(BENCH / "bench-lib.sh", "bench_die", "bench_warn", "bench_run", "bench_manifest",
                          "bench_manifest_jq", "bench_manifest_ts", "bench_manifest_note")
HELPERS = tba.shell_functions(SCRIPT, "marker_rc", "marker_reason", "bucket_prefix", "settle_load_vm")
NEW = tba.shell_functions(SCRIPT, "fund_wait", "fund_still_short", "fund_short_retry", "do_fund")
OLD = (FIX / "do_fund-4356229.sh").read_text()


def log(name):
    return (FIX / name).read_text()


def fund(logs, fns=NEW, manifest=None, before=None, **env):
    """do_fund with <logs>[k-1] as the k-th prepare's generator log (None: the copy brings none); <before> maps a
    path under results/ to the text it holds before the fund. A dict: rc, out, err, manifest, calls, creates,
    files (under results/)."""
    with tempfile.TemporaryDirectory(prefix="fund-short-") as directory:
        work = Path(directory)
        results = work / "results"
        results.mkdir()
        (results / "manifest.json").write_text(json.dumps(manifest or MANIFEST))
        for rel, text in (before or {}).items():
            (results / rel).parent.mkdir(parents=True, exist_ok=True)
            (results / rel).write_text(text)
        for k, text in enumerate(logs, 1):
            if text is not None:
                (work / ("log-%d" % k)).write_text(text)
        (work / "creates").write_text("")
        rc, out, err = tba.run_bash(HARNESS + LIB + HELPERS + fns + "do_fund\n", WORK=str(work), **env)
        norm = lambda text: text.replace(str(work), "<WORK>")
        calls = (work / "calls").read_text() if (work / "calls").exists() else ""
        return dict(rc=rc, out=norm(out), err=norm(err), manifest=json.loads((results / "manifest.json").read_text()),
                    calls=norm(calls).splitlines(), creates=len((work / "creates").read_text().splitlines()),
                    files=sorted(str(f.relative_to(results)) for f in results.rglob("*") if f.is_file()))


class FundShortTests(unittest.TestCase):

    def test_a_short_prepare_is_warned_recorded_and_run_once_more(self):
        run = fund([log("short-2200.txgen.log"), log("retry-ok.txgen.log")])
        self.assertEqual(run["rc"], 0, run["err"])
        self.assertEqual(run["creates"], 2)
        self.assertEqual(run["err"], "⚠ fund index 3: still_short=2200 of 6000 senders unfunded when the prepare "
                                     "stopped waiting (funder/ log); running the prepare once more\n")
        self.assertEqual(run["manifest"]["fund"], {"run_index": 3, "bucket_prefix": PREFIX % 3, "still_short": 2200,
                                                   "still_short_after_retry": 0})
        self.assertTrue(run["out"].endswith("    ✓ second prepare: every sender of index 3 funded (the first left 2200)\n"
                                            "    ✓ funded\n"), run["out"])
        self.assertEqual(run["manifest"]["notes"], [
            "fund: BENCH_FUND_DONE rc=0 reason=ok",
            "fund: index 3 still_short=2200 at 2026-01-01T00:00:00Z; the prepare runs once more",
            "fund: BENCH_FUND_DONE rc=0 reason=ok",
            "fund: the second prepare funded every sender of index 3 (the first left 2200)"])
        # the same prepare again, on a new funder, once the first one is gone; both logs stay in funder/
        creates = [c for c in run["calls"] if c.startswith("create ")]
        self.assertEqual(creates[0], creates[1])
        self.assertEqual(creates[0], "create bench-funder zone-a fund http://node-01.invalid:8545 6000 300000 ")
        self.assertEqual(run["calls"][run["calls"].index("copy %s #1" % (PREFIX % 3)):], [
            "copy %s #1" % (PREFIX % 3), "describe bench-funder", "delete bench-funder", "describe bench-funder",
            creates[0], "assert bench-funder", "wait bench-funder", "copy %s #2" % (PREFIX % 3),
            "describe bench-funder", "delete bench-funder"])
        self.assertEqual(run["files"], ["funder/bench-funder.txgen-20260101T000000Z.log",
                                        "funder/bench-funder.txgen-20260102T000000Z.log", "manifest.json"])

    def test_without_a_count_above_zero_the_fund_is_as_before(self):
        zero = log("short-2200.txgen.log").replace("still_short=2200", "still_short=0")
        short_before = {"funder/bench-funder.txgen-20260101T000000Z.log": log("short-2200.txgen.log")}
        cases = (("healthy", [log("healthy.txgen.log")], {}, None),
                 ("still_short=0", [zero], {}, None),
                 ("no generator log", [None], {}, None),
                 ("copy failed, an older short log in funder/", [log("short-1600.txgen.log")], {"COPY_FAIL": "1"},
                  short_before),
                 ("funder failed", [log("short-2200.txgen.log")], {"MARKER": "BENCH_FUND_DONE rc=3 reason=prepare"},
                  None))
        for name, logs, env, before in cases:
            with self.subTest(name):
                old = fund(logs, fns=OLD, before=before, **env)
                new = fund(logs, before=before, **env)
                self.assertEqual(new, old)
                self.assertEqual(new["creates"], 1)
                self.assertNotIn("still_short", json.dumps(new["manifest"]) + new["out"] + new["err"])
        self.assertEqual(old["rc"], 1)
        self.assertIn("❌ funding failed (BENCH_FUND_DONE rc=3 reason=prepare)", old["err"])

    def test_still_short_after_the_second_prepare_fails_the_step(self):
        run = fund([log("short-1600.txgen.log"), log("retry-short-700.txgen.log")], IDX="15")
        self.assertEqual(run["rc"], 1)
        self.assertEqual(run["creates"], 2)
        self.assertNotIn("✓ funded", run["out"])
        self.assertEqual(run["err"].splitlines(), [
            "⚠ fund index 15: still_short=1600 of 6000 senders unfunded when the prepare stopped waiting (funder/ log); "
            "running the prepare once more",
            "❌ funding failed (fund-short-700): the second prepare left 700 of 6000 senders unfunded (the first left 1600)"])
        self.assertEqual(run["manifest"]["fund"], {"run_index": 15, "bucket_prefix": PREFIX % 15, "still_short": 1600,
                                                   "still_short_after_retry": 700})
        self.assertEqual(run["manifest"]["notes"][-1], "fund: fund-short-700: the second prepare left 700 of 6000 "
                                                       "senders unfunded (the first left 1600)")

    def test_the_last_count_of_the_newest_log_is_read(self):
        # one prepare that logged the timeout twice: the later count is the one that stands
        twice = log("short-2200.txgen.log") + log("short-2200.txgen.log").splitlines(True)[-1].replace("=2200", "=40")
        run = fund([twice, log("retry-ok.txgen.log")])
        self.assertEqual(run["rc"], 0, run["err"])
        self.assertIn("still_short=40 of 6000", run["err"])
        self.assertEqual(run["manifest"]["fund"]["still_short"], 40)
        # a refund of the same index: the older short log stays in funder/, the newest one is healthy
        run = fund([log("healthy.txgen.log")], before={
            "funder/bench-funder.txgen-20251231T000000Z.log": log("short-2200.txgen.log"),
            "funder/bench-funder.txgen-20251231T000000Z.log.1": "still_short=9\n"})
        self.assertEqual((run["rc"], run["err"], run["creates"]), (0, "", 1))

    def test_a_kept_funder_gets_no_second_prepare(self):
        run = fund([log("short-2200.txgen.log"), log("retry-ok.txgen.log")], KEEP="1")
        self.assertEqual((run["rc"], run["creates"]), (1, 1))
        self.assertEqual(run["err"].splitlines()[-1], "❌ funding failed (fund-short-2200): bench-funder was not deleted "
                                                      "(--keep or a failed delete), so no second prepare ran")
        self.assertEqual(run["manifest"]["fund"]["still_short"], 2200)
        self.assertNotIn("still_short_after_retry", run["manifest"]["fund"])

    def test_a_second_prepare_whose_log_was_not_copied_keeps_the_first_count(self):
        run = fund([log("short-2200.txgen.log"), log("retry-ok.txgen.log")], COPY_FAIL="2")
        self.assertEqual((run["rc"], run["creates"]), (1, 2))
        self.assertEqual(run["err"].splitlines()[-1], "❌ funding failed (fund-short-2200): the second prepare's log was "
                                                      "not copied, so the first count stands")
        self.assertEqual(run["manifest"]["fund"], {"run_index": 3, "bucket_prefix": PREFIX % 3, "still_short": 2200,
                                                   "still_short_after_retry": None})


class DryFundTests(tba.SandboxCase):
    """A dry `fund` makes no live call, whatever funder/ holds: every gcloud verb that is not a read prints REACHED
    and exits 9."""

    def setUp(self):
        super(DryFundTests, self).setUp()
        reads = "".join('    "%s"*) exit 1 ;;\n' % r for r in tba.DryRunShimTests.READS[1:])
        shim = self.sb.bin / "gcloud"
        shim.write_text(tba.DryRunShimTests.SHIM.replace("@READS@", reads).replace("'%s'", "'gcloud'"))
        shim.chmod(0o755)

    def test_a_dry_fund_reaches_nothing(self):
        rc, out, calls = self.sb.blast("fund")
        self.assertEqual(rc, 0, out)
        self.assertEqual(tba.golden_text(rc, out, calls),
                         tba.bench6((tba.FIX / "golden-fund-plan.txt").read_text(), 1))
        results = self.sb.tree / "benchmark" / "results" / tba.RUN_ID
        (results / "funder").mkdir(parents=True)
        (results / "funder" / "bench-funder.txgen-20260101T000000Z.log").write_text(log("short-2200.txgen.log"))
        (results / "manifest.json").write_text(json.dumps({"fund": {"run_index": 0}, "notes": []}))
        rc, out, calls = self.sb.blast("fund")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("REACHED", out)
        self.assertNotIn("still_short", out)
        live = [c for c in calls.splitlines() if not any(c.startswith("gcloud " + r) for r in tba.DryRunShimTests.READS)]
        self.assertEqual(live, [])
        self.assertEqual(len(tba.create_lines(out, "bench-funder")), 1)
        self.assertIn("DRY RUN — re-run with --yes.", out)


if __name__ == "__main__":
    unittest.main()
