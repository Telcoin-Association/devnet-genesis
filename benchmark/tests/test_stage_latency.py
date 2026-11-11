"""tools/stage-latency.py on a synthetic node log and generator file (fixtures/stage-latency/).

The fixture (T0 = 2026-11-06T10:00:00Z, times below are T0 + ms; header comment in the log):
  block 500  batch aa11.. built 1000 (pool age 40), sealed 1150 (quorum 148), reported 1155 (5);
  block 501  batch bb22.. built 1200 (60), sealed 1330 (128), reported 1336 (6);
             both in own header 9 (1500, quorum 1650); leader B2 round 10 created 1840, committed 2440;
             output 100: waited 1200, fetch 4, pack 3, forward 5 + queue 300, execute 80, persist 20 +
             announce 2, executed 4058; seen 4208.
  block 502  batch cc33.. built 2000 (30), sealed 2140 (138), reported 2145 (5), own header 11 (2200,
             quorum 2350);
  block 503  batch dd44.. built 2300 (50), sealed 2450 (140), reported 2454 (4), in own header 12 (2550,
             quorum 2700) = the leader's (this node, A1); sub-DAG 12 committed 3300; output 101: no
             waited line, fetch 3, pack 2, forward 4 + queue 352, execute 60, persist 15 + announce 1,
             executed 4136; seen 4336.
  block 504  not own, closes_epoch at T0 + 32 s; block 505 own, T0 + 200 s, no log lines.
Accept p50 6/7/5/4 ms; own_submit_p50_ms 3254/3075/2371/2090 (the last two hide a 400 ms wait the
log does not show, so coverage is 2 of 4).
"""
import gzip
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
TOOL = TESTS.parent / "tools" / "stage-latency.py"
FIX = TESTS / "fixtures" / "stage-latency"
LOG = "bench-validator-01-unit-stdout.log"
T1_COLUMNS = ("batch_index", "batch_digest_prefix", "seen_ms", "own_submit_min_ms", "own_submit_p50_ms",
              "own_submit_max_ms", "own_accept_p50_ms")
# The bench-4 (r20261105-0803) shape of each line the tool reads: the fields those builds log. Lines
# whose message is not here did not exist.
BENCH4_FIELDS = {
    "batch sealed": ("worker_id", "batch_size", "num_txs"),
    "header proposed": ("round", "epoch", "num_batches", "num_parents"),
    "quorum reached": ("round", "epoch", "voting_power", "quorum_threshold", "num_votes"),
    "certificate committed": ("round", "origin", "digest", "committed_round", "gc_round"),
    "subdag committed": ("subdag_index", "leader_round", "num_certificates", "min_round", "committed_round", "leader"),
    "consensus output ready": ("number", "leader_round", "num_certs", "num_batches", "total_txs", "authority"),
    "output execution task finished": ("consensus_number", "queue_wait_ms", "task_ms"),
    "output executed": ("consensus_number", "leader_round", "blocks", "batches", "execute_ms", "persist_ms",
                        "announce_ms", "epoch"),
    "next block executed": ("hash", "number", "epoch", "consensus_number", "parent_exec_number", "batches"),
}
MSG_RE = re.compile(r'message="([^"]*)"')
FIELD_RE = re.compile(r'(\w+)=(\[[^\]]*\]|"[^"]*"|\S+)')


def load_module():
    spec = importlib.util.spec_from_file_location("stage_latency", str(TOOL))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bench4_line(line):
    """The line as a bench-4 node logged it, or None when bench 4 had no such line."""
    m = MSG_RE.search(line)
    if not m:
        return line
    keep = BENCH4_FIELDS.get(m.group(1))
    if keep is None:
        return None
    fields = " ".join("%s=%s" % kv for kv in FIELD_RE.findall(line[m.end():]) if kv[0] in keep)
    return line[:m.end()] + " " + fields


class StageLatencyTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="stage-latency-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_run(self, line_filter=None, blaster_edit=None, name="r20261106-1000"):
        run = self.tmp / name
        (run / "logs").mkdir(parents=True)
        (run / "blasters").mkdir()
        lines = (FIX / LOG).read_text().splitlines(True)
        if line_filter:
            lines = [x for x in (line_filter(l) for l in lines) if x is not None]
            lines = [l if l.endswith("\n") else l + "\n" for l in lines]
        (run / "logs" / (LOG + ".gz")).write_bytes(gzip.compress("".join(lines).encode()))
        doc = json.loads((FIX / "bench-blaster-01.json").read_text())
        if blaster_edit:
            blaster_edit(doc)
        (run / "blasters" / "bench-blaster-01.json").write_text(json.dumps(doc))
        return run

    def run_tool(self, run, *args):
        return subprocess.run([sys.executable, str(TOOL), "--run-dir", str(run)] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def doc(self, run, *args, windows=True):
        out = self.tmp / ("out-%d.json" % len(list(self.tmp.glob("out-*.json"))))
        extra = ["--windows", str(FIX / "windows.json")] if windows else []
        p = self.run_tool(run, "--out-json", str(out), *(extra + list(args)))
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(out.read_text())

    def stages(self, table):
        return {s: (r["count"], r["p50_ms"], r["p95_ms"], r["unmeasured"]) for s, r in table.items()}

    # ------------------------------------------------------------------ the full chain
    def test_every_stage_p50_p95_against_hand_computed_values(self):
        doc = self.doc(self.make_run())
        expect = {"S0": (4, 5, 7, 0), "S1": (4, 40, 60, 0), "S2": (4, 138, 148, 0), "S3": (4, 5, 6, 0),
                  "S4": (4, 96, 345, 0), "S5": (4, 150, 150, 0), "S6a": (4, 190, 200, 0),
                  "S6b": (4, 600, 750, 0), "S7": (4, 0, 1200, 0), "S8": (4, 3, 4, 0), "S9": (4, 2, 3, 0),
                  "S10": (4, 305, 356, 0), "S11": (4, 60, 80, 0), "S12": (4, 16, 22, 0), "S13": (4, 150, 200, 0)}
        self.assertEqual(self.stages(doc["pooled"]["load"]), expect)
        self.assertEqual(self.stages(doc["nodes"]["bench-validator-01"]["load"]), expect)
        load = doc["pooled"]["load"]
        self.assertEqual(load["S4"]["basis"], {"batch_reported": 4})
        self.assertEqual(load["S6a"]["basis"], {"leader_created_at_ms": 3, "leader_own_batch": 1})
        self.assertEqual(load["S7"]["basis"], {"no_line_below_threshold": 2, "waited_line": 2})
        self.assertEqual(load["S10"]["basis"], {"forward+queue": 4})
        self.assertEqual(load["S13"]["basis"], {"output_executed": 4})
        aux = doc["aux"]["pooled"]["load"]
        self.assertEqual((aux["queued_before"]["p50"], aux["depth"]["p95"], aux["root_ms"]["p50"]), (2, 3, 15))
        src = doc["sources"]["bench-validator-01"]
        self.assertEqual((src["authority"], src["f1_build"], src["own_blocks"]), ("A1" + "a" * 30, True, 5))
        self.assertEqual(doc["events"]["bench-validator-01"]["load"],
                         {"digests_resent": {"lines": 1, "sum": 2, "by_cause": {"unknown": {"lines": 1, "sum": 2}}},
                          "header_uncertified": {"lines": 1, "sum": 1}})
        self.assertEqual(doc["run"], "r20261106-1000")

    def test_digests_resent_split_by_cause(self):
        # The fixture's line has no cause= (a build before L7): unknown. Beside it, one line per cause, quoted
        # and bare, and one outside the windows (only "all" counts it).
        extra = ('ts=2026-11-06T10:00:02.100000000Z level=info target=consensus::metrics message="digests resent" '
                 'count=3 from_round=9 round=11 cause="canceled"\n'
                 'ts=2026-11-06T10:00:03.200000000Z level=info target=consensus::metrics message="digests resent" '
                 'count=5 from_round=10 round=12 cause=committed\n'
                 'ts=2026-11-06T10:00:04.300000000Z level=info target=consensus::metrics message="digests resent" '
                 'count=4 from_round=11 round=13 cause=canceled\n'
                 'ts=2026-11-06T11:00:00.000000000Z level=info target=consensus::metrics message="digests resent" '
                 'count=7 from_round=90 round=92 cause=committed\n')

        def add(line):
            return line + extra if 'message="digests resent"' in line else line
        ev = self.doc(self.make_run(line_filter=add))["events"]["bench-validator-01"]
        self.assertEqual(ev["load"]["digests_resent"], {"lines": 4, "sum": 14, "by_cause": {
            "canceled": {"lines": 2, "sum": 7}, "committed": {"lines": 1, "sum": 5}, "unknown": {"lines": 1, "sum": 2}}})
        self.assertEqual(ev["all"]["digests_resent"]["by_cause"]["committed"], {"lines": 2, "sum": 12})
        self.assertEqual(ev["load"]["header_uncertified"], {"lines": 1, "sum": 1})

    def test_headline_sums_chain_and_generator(self):
        h = self.doc(self.make_run())["headline"]["load"]
        # chain per block: ts 884/705/583/444, commit 1484/1305/1333/1044, seen 3248/3069/1970/1681 ms
        self.assertEqual((h["ts_p50_s"], h["ts_p95_s"]), (0.583, 0.884))
        self.assertEqual((h["commit_p50_s"], h["commit_p95_s"]), (1.305, 1.484))
        self.assertEqual((h["seen_p50_s"], h["seen_p95_s"]), (1.97, 3.248))
        self.assertEqual(h["count"], {"ts": 4, "commit": 4, "seen": 4})
        self.assertNotIn("partial", h)
        g = h["from_generator"]
        # submit = seen_ms - own_submit_p50_ms = 954/1133/1965/2246: ts 886/707/585/304, commit 1486/1307/1335/1054
        self.assertEqual((g["ts_p50_s"], g["ts_p95_s"]), (0.585, 0.886))
        self.assertEqual((g["commit_p50_s"], g["commit_p95_s"]), (1.307, 1.486))
        self.assertEqual((g["seen_p50_s"], g["seen_p95_s"]), (2.371, 3.254))
        self.assertEqual(g["count"]["seen"], 4)

    def test_coverage_is_the_sum_of_stages_against_the_generator_seen(self):
        doc = self.doc(self.make_run(), "--exclude-boundaries")
        load = doc["coverage"]["pooled"]["load"]
        self.assertEqual((load["checked"], load["within"], load["pct"], load["diff_p50_ms"]), (4, 2, 50.0, -401))
        light = doc["coverage"]["pooled"]["light8"]
        self.assertEqual((light["checked"], light["within"], light["pct"]), (2, 2, 100.0))
        wide = self.doc(self.make_run(name="wide"), "--coverage-tolerance-ms", "410")["coverage"]["pooled"]["load"]
        self.assertEqual(wide["pct"], 100.0)

    # ------------------------------------------------------------------ windows
    def test_window_filter_and_epoch_boundary_exclusion(self):
        plain = self.doc(self.make_run(), "--keep-boundaries")
        self.assertEqual(plain["pooled"]["light8"]["S0"]["count"], 4)
        self.assertEqual(plain["pooled"]["all"]["S0"]["count"], 5)       # block 505 is outside both windows
        self.assertEqual(plain["pooled"]["all"]["S1"]["unmeasured"], 1)  # and has no log lines
        self.assertFalse(plain["windows"]["light8"]["boundaries_excluded"])
        # On by default for the light* windows only; --exclude-boundaries without a GLOB is the same.
        for name, args in (("default", ()), ("excl", ("--exclude-boundaries",))):
            with self.subTest(args=args):
                excl = self.doc(self.make_run(name=name), *args)
                self.assertTrue(excl["windows"]["light8"]["boundaries_excluded"])
                self.assertFalse(excl["windows"]["load"]["boundaries_excluded"])
                self.assertFalse(excl["windows"]["all"]["boundaries_excluded"])
                # the boundary is T0 + 32 s: blocks at T0 + 2 s (502, 503) are within 30 s, T0 + 1 s (500, 501)
                # are not
                self.assertEqual(self.stages(excl["pooled"]["light8"])["S4"], (2, 164, 345, 0))
                self.assertEqual(excl["pooled"]["load"]["S4"]["count"], 4)
                self.assertEqual(excl["pooled"]["all"]["S0"]["count"], 5)
                self.assertEqual(excl["headline"]["light8"]["seen_p50_s"], 3.069)
        narrow = self.doc(self.make_run(name="narrow"), "--boundary-secs", "29")
        self.assertEqual(narrow["pooled"]["light8"]["S4"]["count"], 4)
        every = self.doc(self.make_run(name="every"), "--exclude-boundaries", "*")
        self.assertEqual(every["pooled"]["load"]["S4"]["count"], 2)

    def test_windows_derived_from_the_light_blasts_and_the_manifest(self):
        run = self.make_run()
        blaster = json.loads((run / "blasters" / "bench-blaster-01.json").read_text())
        for i in range(3):
            d = run / ("blast-%d-20261106T09%02d00Z" % (i, i)) / "blasters"
            d.mkdir(parents=True)
            b = json.loads(json.dumps(blaster))
            for ph in b["run"]["phases"]:
                ph["start_unix"] -= 3600 - 600 * i
                ph["end_unix"] -= 3600 - 600 * i
            (d / "bench-blaster-01.json").write_text(json.dumps(b))
        (run / "manifest.json").write_text(json.dumps({"blasts": [
            {"index": 0, "senders": 8, "window": 16, "chaos": False}, {"index": 1, "senders": 16, "window": 16, "chaos": False},
            {"index": 2, "senders": 600, "window": 4, "chaos": False}, {"index": 3, "senders": 600, "window": 16, "chaos": True}]}))
        doc = self.doc(run, windows=False)
        self.assertEqual(list(doc["windows"]), ["light8", "light16", "light600x4", "load", "all"])
        self.assertEqual(doc["windows"]["load"]["start"], "2026-11-06T10:00:00Z")
        self.assertEqual(doc["windows"]["light8"]["end"], "2026-11-06T09:01:00Z")
        self.assertEqual(doc["pooled"]["load"]["S5"]["count"], 4)
        self.assertEqual(len(doc["sources"]["bench-validator-01"]["blasters"]), 4)
        plain = self.doc(self.make_run(name="plain"), windows=False)  # no blasts[]: the blast's own phases
        self.assertEqual(list(plain["windows"]), ["preamble", "mixed", "cooldown", "all"])

    # ------------------------------------------------------------------ absent lines and fields
    def test_a_dropped_line_type_is_unmeasured_and_the_sum_falls_back_to_a_tail(self):
        doc = self.doc(self.make_run(line_filter=lambda l: None if 'message="batch built"' in l else l))
        s1 = doc["nodes"]["bench-validator-01"]["load"]["S1"]
        self.assertEqual((s1["count"], s1["p50_ms"], s1["unmeasured"]), (0, None, 4))
        self.assertTrue(any("batch built" in why for why in s1["missing"]), s1["missing"])
        self.assertEqual(doc["pooled"]["load"]["S2"]["count"], 4)
        self.assertEqual(doc["aux"]["pooled"]["load"].get("queued_before"), None)
        h = doc["headline"]["load"]
        self.assertEqual((h["ts_p50_s"], h["seen_p50_s"], h["count"]["seen"]), (None, None, 0))
        # S2..S6a per block: 838/638/548/390 ms
        self.assertEqual(h["partial"]["ts"], {"from": "S2", "p50_s": 0.548, "p95_s": 0.838, "count": 4})
        self.assertEqual(doc["coverage"]["pooled"]["load"]["checked"], 0)

    def test_the_execution_wait_is_zero_without_its_line_only_on_a_build_that_logs_it(self):
        no_wait = self.doc(self.make_run(line_filter=lambda l: None if "waited for execution" in l else l))
        self.assertEqual(self.stages(no_wait["pooled"]["load"])["S7"], (4, 0, 0, 0))
        old = self.doc(self.make_run(name="old", line_filter=lambda l: None if (
            "waited for execution" in l or "subdag sequenced" in l) else l))
        s7 = old["nodes"]["bench-validator-01"]["load"]["S7"]
        self.assertEqual((s7["count"], s7["unmeasured"]), (0, 4))
        self.assertIn("pre-F1", " ".join(s7["missing"]))
        self.assertFalse(old["sources"]["bench-validator-01"]["f1_build"])
        self.assertEqual(old["pooled"]["load"]["S6b"]["count"], 4)

    def test_bench4_shapes_join_by_fifo_and_proxy(self):
        def strip_t1(doc):
            cols = doc["blocks"]["columns"]
            keep = [i for i, c in enumerate(cols) if c not in T1_COLUMNS]
            doc["blocks"]["columns"] = [cols[i] for i in keep]
            doc["blocks"]["rows"] = [[r[i] for i in keep] for r in doc["blocks"]["rows"]]
        doc = self.doc(self.make_run(line_filter=bench4_line, blaster_edit=strip_t1))
        st = self.stages(doc["pooled"]["load"])
        for s in ("S0", "S1", "S2", "S3", "S7", "S8", "S9", "S13"):
            self.assertEqual(st[s], (0, None, None, 4), s)
        # FIFO: header 9 took aa11/bb22 (sealed 1150/1330), header 11 cc33 (2140), header 12 dd44 (2450)
        self.assertEqual(st["S4"], (4, 100, 350, 0))
        self.assertEqual(st["S5"], (4, 150, 150, 0))
        # leader 10 (B2): this node's header 10 at 1850 is the proxy; leader 12 is this node (2550)
        self.assertEqual(st["S6a"], (4, 200, 200, 0))
        self.assertEqual(st["S6b"], (4, 590, 750, 0))
        load = doc["pooled"]["load"]
        self.assertEqual(load["S4"]["basis"], {"fifo_sealed": 4})
        self.assertEqual(load["S6a"]["basis"], {"leader_own_batch": 1, "own_header": 1, "proxy_own_header": 2})
        self.assertEqual((st["S10"], load["S10"]["basis"]), ((4, 300, 352, 0), {"queue_wait_ms only": 4}))
        self.assertEqual((st["S11"], st["S12"]), ((4, 60, 80, 0), (4, 16, 22, 0)))
        h = doc["headline"]["load"]
        self.assertEqual((h["ts_p50_s"], h["count"]["commit"]), (None, 0))
        # S4..S6a per block 700/520/410/250, S4..S6b 1290/1110/1160/850 ms
        self.assertEqual(h["partial"]["ts"], {"from": "S4", "p50_s": 0.41, "p95_s": 0.7, "count": 4})
        self.assertEqual(h["partial"]["commit"], {"from": "S4", "p50_s": 1.11, "p95_s": 1.29, "count": 4})
        self.assertNotIn("seen", h["partial"])
        self.assertEqual(h["from_generator"]["count"], {"ts": 0, "commit": 0, "seen": 0, "ts_read": 0})
        self.assertFalse(doc["sources"]["bench-validator-01"]["block_columns_t1"])

        def wrong_size(d):
            strip_t1(d)
            d["blocks"]["rows"][2][d["blocks"]["columns"].index("tx_count")] = 121   # block 501
        off = self.doc(self.make_run(name="off", line_filter=bench4_line, blaster_edit=wrong_size))
        self.assertEqual((off["pooled"]["load"]["S4"]["count"], off["pooled"]["load"]["S5"]["count"]), (3, 4))

    # ------------------------------------------------------------------ the digest key
    def test_the_digest_join_strips_0x_and_takes_16_lowercase_hex(self):
        mod = load_module()
        self.assertEqual(mod.digest_key("0xAA11AA11AA11AA11" + "F" * 48), "aa11aa11aa11aa11")
        self.assertEqual(mod.digest_key("aa11aa11aa11aa11"), "aa11aa11aa11aa11")
        self.assertIsNone(mod.digest_key("0" * 16))
        self.assertIsNone(mod.digest_key("5Hn3xyzBs58NotHex"))
        self.assertEqual(mod.pct([4, 5, 6, 7], 0.5), 5)
        self.assertEqual(mod.pct([4, 5, 6, 7], 0.95), 7)

        def upper(doc):
            i = doc["blocks"]["columns"].index("batch_digest_prefix")
            for r in doc["blocks"]["rows"]:
                r[i] = r[i].upper()
        self.assertEqual(self.doc(self.make_run(blaster_edit=upper))["pooled"]["load"]["S1"]["count"], 4)

        def no_prefix(doc):  # the node's "next block executed batch_digest=" stands in for the column
            i = doc["blocks"]["columns"].index("batch_digest_prefix")
            doc["blocks"]["columns"].pop(i)
            for r in doc["blocks"]["rows"]:
                r.pop(i)
        st = self.stages(self.doc(self.make_run(name="nop", blaster_edit=no_prefix))["pooled"]["load"])
        self.assertEqual((st["S1"], st["S4"]), ((4, 40, 60, 0), (4, 96, 345, 0)))

    # ------------------------------------------------------------------ CLI
    def test_help(self):
        p = subprocess.run([sys.executable, str(TOOL), "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        for word in ("--run-dir", "--windows", "--exclude-boundaries", "--keep-boundaries", "--max-lines", "--out-json", "--out-md",
                     "S6b", "waited for execution before assembling the output"):
            self.assertIn(word, p.stdout)

    def test_markdown_blocks_and_max_lines(self):
        run = self.make_run()
        md, blocks = self.tmp / "out.md", self.tmp / "blocks.ndjson"
        p = self.run_tool(run, "--windows", str(FIX / "windows.json"), "--out-md", str(md), "--out-blocks", str(blocks))
        self.assertEqual(p.returncode, 0, p.stderr)
        text = md.read_text()
        self.assertIn("| load | 0.583 | 0.884 | 1.305 | 1.484 | 1.970 | 3.248 |", text)
        self.assertIn("## light8: 2026-11-06T10:00:00Z → 2026-11-06T10:01:00Z, epoch boundaries excluded\n", text)
        self.assertIn("## load: 2026-11-06T10:00:00Z → 2026-11-06T10:01:00Z\n", text)
        self.assertIn("| S6a | own cert -> leader created | 4 | 190 | 200 | 0 |", text)
        rows = [json.loads(x) for x in blocks.read_text().splitlines()]
        self.assertEqual([r["number"] for r in rows], [500, 501, 502, 503, 505])
        self.assertEqual(rows[0]["stages"]["S4"], 345)
        # 503's batch rode in the committing leader's own header: no wait for a later leader, and the
        # commit counts from that header's quorum (3300 - 2700)
        self.assertEqual((rows[3]["stages"]["S6a"], rows[3]["stages"]["S6b"], rows[3]["basis"]["S6b"]),
                         (0, 600, "leader_own_batch"))
        self.assertEqual((rows[2]["stages"]["S6a"], rows[2]["stages"]["S6b"]), (200, 750))
        self.assertEqual(rows[4]["stages"], {"S0": 9})
        capped = self.doc(self.make_run(name="capped"), "--max-lines", "12")
        src = capped["sources"]["bench-validator-01"]
        self.assertEqual((src["lines_read"], src["truncated_at_max_lines"]), (12, True))
        self.assertEqual(capped["pooled"]["load"]["S5"]["count"], 0)
        p = self.run_tool(run, "--windows", str(FIX / "windows.json"))     # no --out-*: markdown on stdout
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("## Headline", p.stdout)

    def test_exit_codes(self):
        run = self.make_run()
        self.assertEqual(self.run_tool(run, "--node", "bench-validator-09").returncode, 2)
        bad = self.tmp / "bad-windows.json"
        bad.write_text(json.dumps({"windows": {"x": {"src": "no bounds"}}}))
        p = self.run_tool(run, "--windows", str(bad))
        self.assertEqual(p.returncode, 1)
        self.assertIn("no window", p.stderr)
        p = subprocess.run([sys.executable, str(TOOL), "--logs", str(run / "logs")], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertNotEqual(p.returncode, 0)
        p = subprocess.run([sys.executable, str(TOOL), "--logs", str(run / "logs"), "--blasters", str(run / "blasters"),
                            "--windows", str(FIX / "windows.json"), "--format", "json"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["run"], "r20261106-1000")

    # ---- bench6 arm windows ----
    def bench6_run(self, phases_planned=True, name="b6"):
        """The fixture's blast as blast index 1 of arm v (archived) and index 2 of arm a0b (the main
        blasters/), with bench-6 blasts[] entries; index 1's real mixed phase is 10:00:20-10:00:50."""
        run = self.make_run(name="%s-%d" % (name, len(list(self.tmp.glob(name + "-*")))))
        d = run / "blast-1-20261106T100500Z" / "blasters"
        d.mkdir(parents=True)
        shutil.copy(str(run / "blasters" / "bench-blaster-01.json"), str(d / "bench-blaster-01.json"))
        real = [{"name": "mixed", "start": "2026-11-06T10:00:20Z", "end": "2026-11-06T10:00:50Z"}]
        e1 = {"index": 1, "senders": 600, "window": 16, "chaos": 0, "kind": "load", "arm": "v", "rc": 0, "phases": real}
        if phases_planned:
            e1["phases_planned"] = [{"name": "mixed", "start": "2026-11-06T10:00:00Z", "end": "2026-11-06T10:08:00Z"}]
        e2 = {"index": 2, "senders": 8, "window": 16, "chaos": 0, "kind": "light", "arm": "a0b", "rc": 0}
        (run / "manifest.json").write_text(json.dumps({"blasts": [e1, e2], "param_arms": [
            {"name": "v", "begin": "2026-11-06T09:50:00Z", "ready": "2026-11-06T10:00:10Z", "end": "2026-11-06T10:00:40Z",
             "marks": [{"label": "idle", "begin": "2026-11-06T09:59:00Z", "end": "2026-11-06T09:59:30Z"}]}]}))
        return run

    def test_bench6_blasts_are_windows_by_arm_and_kind_on_their_real_phases(self):
        doc = self.doc(self.bench6_run(), windows=False)
        self.assertEqual(list(doc["windows"]), ["v/load600x16", "a0b/light8x16", "all"])
        self.assertEqual((doc["windows"]["v/load600x16"]["start"], doc["windows"]["v/load600x16"]["end"]),
                         ("2026-11-06T10:00:20Z", "2026-11-06T10:00:50Z"))
        self.assertEqual(doc["windows"]["a0b/light8x16"]["start"], "2026-11-06T10:00:00Z")   # no real phases: blasters'
        plan = self.doc(self.bench6_run(phases_planned=False), windows=False)  # phases without phases_planned are a plan
        self.assertEqual(plan["windows"]["v/load600x16"]["start"], "2026-11-06T10:00:00Z")
        only = self.doc(self.bench6_run(), "--only", "v/*", windows=False)
        self.assertEqual(list(only["windows"]), ["v/load600x16", "all"])
        p = self.run_tool(self.bench6_run(), "--only", "nothing*")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no window matches --only", p.stderr)
        self.assertNotIn("not_measured", doc)

    def test_a_failed_blast_gets_no_window_and_is_listed_not_measured(self):
        """rc != 0 means no window, even when the failed blast's blasters were archived (index 0 here); an index
        retried under itself (index 1: rc 2 first, then rc 0) is measured on its rc-0 entry."""
        run = self.bench6_run()
        d = run / "blast-0-20261106T095500Z" / "blasters"
        d.mkdir(parents=True)
        shutil.copy(str(run / "blasters" / "bench-blaster-01.json"), str(d / "bench-blaster-01.json"))
        m = json.loads((run / "manifest.json").read_text())
        e1 = m["blasts"][0]
        late = [{"name": "mixed", "start": "2026-11-06T10:01:00Z", "end": "2026-11-06T10:02:00Z"}]
        first_try = dict(e1, rc=2, phases=late)
        m["blasts"] = [dict(e1, index=0, rc=1, phases=late), first_try] + m["blasts"]
        (run / "manifest.json").write_text(json.dumps(m))
        doc = self.doc(run, windows=False)
        self.assertEqual(list(doc["windows"]), ["v/load600x16", "a0b/light8x16", "all"])
        self.assertEqual((doc["windows"]["v/load600x16"]["start"], doc["windows"]["v/load600x16"]["end"]),
                         ("2026-11-06T10:00:20Z", "2026-11-06T10:00:50Z"))
        self.assertEqual(doc.get("not_measured"), ["blast index 0 (v/load600x16): rc 1", "blast index 1 (v/load600x16): rc 2"])
        md = self.run_tool(run).stdout
        self.assertIn("- Not measured (failed, no window): blast index 0 (v/load600x16): rc 1; "
                      "blast index 1 (v/load600x16): rc 2.", md)

    def test_a_manifest_as_windows_reads_its_arms_from_ready(self):
        run = self.bench6_run()
        doc = self.doc(run, "--windows", str(run / "manifest.json"), windows=False)
        self.assertEqual(list(doc["windows"]), ["v", "v/idle", "all"])
        self.assertEqual((doc["windows"]["v"]["start"], doc["windows"]["v"]["end"]),
                         ("2026-11-06T10:00:10Z", "2026-11-06T10:00:40Z"))
        self.assertEqual(doc["windows"]["v/idle"]["start"], "2026-11-06T09:59:00Z")
        arms = self.tmp / "arms-list.json"                     # the param_arms[] list itself: `ready` starts it too
        arms.write_text(json.dumps(json.loads((run / "manifest.json").read_text())["param_arms"]))
        listed = self.doc(run, "--windows", str(arms), windows=False)
        self.assertEqual(listed["windows"]["v"]["start"], "2026-11-06T10:00:10Z")


if __name__ == "__main__":
    unittest.main()
