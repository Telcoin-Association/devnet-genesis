"""report/scrub.py: the harness-side input scrubber and leak scan.

Every sensitive-looking value (IPs, instance ids, the project, bucket and Grafana names, local
paths, secrets) is assembled at run time from pieces, so this file and the committed fixtures in
fixtures/report/scrub-samples/ scan clean themselves. The synthetic manifest mirrors the shape of
a real tn-bench-manifest/v1: instances carry internal/external IPs and instance ids, blasters
carry an instance id and a node_url.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = Path(__file__).resolve().parent
BENCH = TESTS.parent
SCRUB_PY = BENCH / "report" / "scrub.py"
SPEC = importlib.util.spec_from_file_location("report_scrub", SCRUB_PY)
scrub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scrub)

SAMPLES = TESTS / "fixtures" / "report" / "scrub-samples"
CLEAN = SAMPLES / "clean"
SAMPLER_CSV = SAMPLES / "sampler" / "val-1.csv"


def ip(*octets):
    return ".".join(str(o) for o in octets)


# Seeded values, never literal in this file.
INT_V1, EXT_V1 = ip(10, 0, 0, 7), ip(34, 120, 7, 21)
INT_V2, EXT_V2 = ip(10, 0, 0, 8), ip(35, 200, 1, 9)
INT_O1 = ip(10, 0, 0, 9)
INT_B1 = ip(10, 0, 1, 5)
UNMAPPED_PRIVATE = ip(192, 168, 3, 4)
UNMAPPED_PUBLIC = ip(8, 8, 4, 4)
ID_V1, ID_V2, ID_O1, ID_B1 = ("88" + "1234567890123401", "88" + "1234567890123402",
                              "88" + "1234567890123403", "88" + "1234567890123404")
PROJECT = "acme" + "-bench-" + "proj"
PRIVATE_PROJECT = "tn-" + "devnet"
BUCKET = "acme" + "-bench-" + "results"
ARCHIVE_BUCKET = PRIVATE_PROJECT + "-bench" + "mark-archive"
GS = "gs" + "://"
GRAFANA_HOST = "obs." + "acme-bench.example.net"
USERS = "/" + "Users/"
HOME = "/" + "home/"


def synthetic_manifest():
    return {
        "schema": "tn-bench-manifest/v1",
        "run_id": "r20260101-0000",
        "fleet": "three validators",
        "machine_type": "n2-standard-4",
        "docker_image": "us-docker.pkg.dev/%s/images/node:v1" % PRIVATE_PROJECT,
        "txgen_image": "us-docker.pkg.dev/%s/images/txgen:v2" % PROJECT,
        "project": PROJECT,
        "prometheus": {"grafana_url": "https://%s/d/x" % GRAFANA_HOST, "datasource_uid": "prom1",
                       "network_label": "bench"},
        "timestamps": {"deploy_start": "2026-01-01T00:00:00Z", "blast_end": "2026-01-01T01:00:00Z"},
        "phases": [{"name": "mixed", "start": "2026-01-01T00:10:00Z", "end": "2026-01-01T00:50:00Z"}],
        "chaos": [{"ts": "2026-01-01T00:20:00Z", "node": "val-2", "action": "docker kill",
                   "note": "outage", "rc": 0}],
        "instances": [
            {"name": "val-1", "role": "validator", "zone": "us-west2-a", "instance_id": ID_V1,
             "machine_type": "n2-standard-4", "vcpus": 4, "memory_mb": 16384,
             "internal_ip": INT_V1, "external_ip": EXT_V1},
            {"name": "val-2", "role": "validator", "zone": "us-east1-b", "instance_id": ID_V2,
             "machine_type": "n2-standard-4", "vcpus": 4, "memory_mb": 16384,
             "internal_ip": INT_V2, "external_ip": EXT_V2},
            {"name": "obs-1", "role": "observer", "zone": "us-west2-a", "instance_id": ID_O1,
             "internal_ip": INT_O1, "external_ip": "0.0.0.0"},
        ],
        "blasters": [
            {"name": "load-1", "zone": "us-west2-a", "instance_id": ID_B1, "target": "val-1",
             "node_url": "http://%s:8545" % INT_V1, "senders": 10, "rc": 0},
        ],
        "abort": None,
        "notes": ["results copied to %s%s/run" % (GS, BUCKET)],
        "fund": {"run_index": 0, "bucket_prefix": "%s%s/fund" % (GS, BUCKET)},
        "blast": {"run_index": 0, "chaos": 1, "bucket_prefix": "%s%s/blast" % (GS, BUCKET)},
        "archive": {"uri": "%s%s/runs/r20260101-0000" % (GS, ARCHIVE_BUCKET), "status": "verified-before-delete",
                    "verified_at": "2026-01-01T02:00:00Z"},
    }


def synthetic_metrics():
    return {
        "schema": "tn-bench-gcp-metrics/v1",
        "project": PROJECT,
        "window": {"start": "2026-01-01T00:10:00Z", "end": "2026-01-01T00:50:00Z", "align_secs": 60},
        "instances": [
            {"name": "val-1", "zone": "us-west2-a", "instance_id": ID_V1, "machine_type": "n2-standard-4",
             "vcpus": 4, "memory_mb": 16384, "role": "validator",
             "disks": [{"name": "val-1-data", "size_gb": 100, "type": "pd-ssd", "boot": False}]},
        ],
        "prometheus": {"url": "http://%s:9090" % GRAFANA_HOST, "step_secs": 15},
        "series": {"cpu": {"val-1": [[1767225600, 0.5]]}},
    }


def synthetic_combined():
    return {
        "schema": "tn-blast-combined/v2",
        "run": {"args": {
            "nodes": ["val-1=http://%s:8545" % INT_V1],
            "deployments_path": "/etc/txgen/deployments.json",
            "out": "/var/lib/bench/out/load-1.json",
            "nodes_file": USERS + "alice/bench/nodes.txt",
            "scratch": "/tmp/" + "bench-x/state.json",
        }},
        "nodes": [
            {"label": "val-1", "url": "http://%s:8545" % INT_V1},
            {"label": "?", "url": "http://%s:8545" % UNMAPPED_PRIVATE},
            {"label": "val-2", "url": "http://val-2:8546"},
            {"label": "x", "url": "http://some-host:8545"},
            {"label": "obs-1", "url": "http://%s" % INT_O1},
        ],
        "totals": {"landed_chain": 10},
    }


def synthetic_sizing():
    return {"schema": "tn-bench-sizing/v1", "notes": ["probe ran against %s" % INT_V2],
            "per_node": {"val-1": {"disk_gb": 1.5}}}


class IpLabelMapTests(unittest.TestCase):
    def test_instances_and_blasters(self):
        m = synthetic_manifest()
        m["blasters"][0]["internal_ip"] = INT_B1
        m["instances"].append({"role": "validator", "internal_ip": ip(10, 9, 9, 9)})  # no name
        m["instances"].append({"name": "val-9", "peer_ips": [ip(10, 9, 9, 10), "0.0.0.0"],
                               "internal_ip": INT_V1})  # INT_V1 already mapped: first wins
        self.assertEqual(scrub.ip_label_map(m), {
            INT_V1: "val-1", EXT_V1: "val-1", INT_V2: "val-2", EXT_V2: "val-2", INT_O1: "obs-1",
            INT_B1: "load-1", ip(10, 9, 9, 10): "val-9"})

    def test_node_url_and_ids_are_not_ip_sources(self):
        m = synthetic_manifest()
        ipmap = scrub.ip_label_map(m)
        self.assertNotIn(ID_B1, ipmap)
        self.assertNotIn("0.0.0.0", ipmap)
        self.assertEqual(set(ipmap.values()), {"val-1", "val-2", "obs-1"})

    def test_empty(self):
        self.assertEqual(scrub.ip_label_map(None), {})
        self.assertEqual(scrub.ip_label_map({}), {})


class ReplaceIpsTests(unittest.TestCase):
    def setUp(self):
        self.ipmap = scrub.ip_label_map(synthetic_manifest())

    def test_mapped_unmapped_and_allowed(self):
        doc = {"a": "peer %s and %s" % (INT_V1, EXT_V2),
               "b": [UNMAPPED_PRIVATE, {"c": UNMAPPED_PUBLIC}],
               "d": "bind 0.0.0.0 and 127.0.0.1",
               INT_O1: 5, "n": 3, "f": 1.5, "z": None, "t": True}
        before = copy.deepcopy(doc)
        out = scrub.replace_ips(doc, self.ipmap)
        self.assertEqual(out, {"a": "peer val-1 and val-2",
                               "b": [scrub.REDACTED_IP, {"c": scrub.REDACTED_IP}],
                               "d": "bind 0.0.0.0 and 127.0.0.1",
                               "obs-1": 5, "n": 3, "f": 1.5, "z": None, "t": True})
        self.assertEqual(doc, before, "input must not be mutated")
        self.assertEqual(scrub.REDACTED_IP, "redacted-ip")

    def test_glued_quads_are_not_ips(self):
        self.assertEqual(scrub.replace_ips(["v1.2.3", "1.2.3.4.5", "a" + INT_V1], self.ipmap),
                         ["v1.2.3", "1.2.3.4.5", "a" + INT_V1])

    def test_scalars(self):
        self.assertEqual(scrub.replace_ips(INT_V2, self.ipmap), "val-2")
        self.assertEqual(scrub.replace_ips(7, self.ipmap), 7)


class ScrubManifestTests(unittest.TestCase):
    def setUp(self):
        self.raw = synthetic_manifest()
        self.before = copy.deepcopy(self.raw)
        self.ipmap = scrub.ip_label_map(self.raw)
        self.ctx = scrub._Ctx(self.ipmap, [self.raw["project"]])
        self.out = scrub.scrub_manifest(self.raw, self.ipmap, ctx=self.ctx)

    def test_drops_exactly_the_documented_keys(self):
        self.assertEqual(sorted(self.ctx.dropped), sorted([
            "manifest.project", "manifest.notes", "manifest.archive",
            "manifest.instances[].instance_id", "manifest.instances[].internal_ip",
            "manifest.instances[].external_ip",
            "manifest.blasters[].instance_id", "manifest.blasters[].node_url",
            "manifest.prometheus.grafana_url", "manifest.fund.bucket_prefix", "manifest.blast.bucket_prefix"]))
        self.assertEqual(len(self.ctx.dropped), len(set(self.ctx.dropped)))
        self.assertEqual(set(self.out), set(self.raw) - {"project", "notes", "archive"})
        for got, raw in zip(self.out["instances"], self.raw["instances"]):
            self.assertEqual(set(got), set(raw) - {"instance_id", "internal_ip", "external_ip"})
        self.assertEqual(self.out["blasters"], [{"name": "load-1", "zone": "us-west2-a", "target": "val-1",
                                                 "senders": 10, "rc": 0}])
        self.assertEqual(self.out["prometheus"], {"datasource_uid": "prom1", "network_label": "bench"})
        self.assertEqual(self.out["fund"], {"run_index": 0})
        self.assertEqual(self.out["blast"], {"run_index": 0, "chaos": 1})

    def test_keeps_run_shape(self):
        for key in ("chaos", "phases", "timestamps", "schema", "run_id", "fleet", "machine_type", "abort"):
            self.assertEqual(self.out[key], self.raw[key], key)
        self.assertEqual([(i["name"], i["zone"], i["role"]) for i in self.out["instances"]],
                         [("val-1", "us-west2-a", "validator"), ("val-2", "us-east1-b", "validator"),
                          ("obs-1", "us-west2-a", "observer")])
        self.assertEqual(self.out["instances"][0]["vcpus"], 4)

    def test_registry_prefix_removed(self):
        self.assertEqual(self.out["txgen_image"], "txgen:v2")      # the manifest's own project
        self.assertEqual(self.out["docker_image"], "node:v1")      # the built-in private project
        self.assertEqual(self.ctx.rewritten_images, 2)

    def test_input_untouched_and_output_clean(self):
        self.assertEqual(self.raw, self.before)
        text = json.dumps(self.out, indent=1)
        self.assertEqual(scrub.scan_text(text, "manifest.json", manifest=self.raw), [])


class ScrubMetricsTests(unittest.TestCase):
    def test_drops_project_instance_id_and_prometheus_url(self):
        raw = synthetic_metrics()
        before = copy.deepcopy(raw)
        ctx = scrub._Ctx({}, [PROJECT])
        out = scrub.scrub_metrics(raw, {}, ctx=ctx)
        self.assertEqual(sorted(ctx.dropped), ["metrics.instances[].instance_id", "metrics.project",
                                               "metrics.prometheus.url"])
        self.assertEqual(set(out), set(raw) - {"project"})
        self.assertEqual(set(out["instances"][0]), set(raw["instances"][0]) - {"instance_id"})
        self.assertEqual(out["instances"][0]["disks"], raw["instances"][0]["disks"])
        self.assertEqual(out["prometheus"], {"step_secs": 15})
        self.assertEqual(out["series"], raw["series"])
        self.assertEqual(raw, before)


class ScrubCombinedTests(unittest.TestCase):
    def setUp(self):
        self.ipmap = scrub.ip_label_map(synthetic_manifest())
        self.raw = synthetic_combined()
        self.out = scrub.scrub_combined(self.raw, self.ipmap)

    def test_node_urls_pinned(self):
        self.assertEqual([n["url"] for n in self.out["nodes"]], [
            "http://val-1:8545", "http://redacted-ip:8545", "http://val-2:8546",
            "http://redacted-ip:8545", "http://obs-1:8545"])

    def test_paths_and_args(self):
        args = self.out["run"]["args"]
        self.assertEqual(args["nodes"], ["val-1=http://val-1:8545"])
        self.assertEqual(args["nodes_file"], "nodes.txt")
        self.assertEqual(args["scratch"], "state.json")
        self.assertEqual(args["out"], "/var/lib/bench/out/load-1.json")
        self.assertEqual(args["deployments_path"], "/etc/txgen/deployments.json")
        self.assertEqual(self.raw, synthetic_combined(), "input must not be mutated")

    def test_drop_keys_anywhere(self):
        raw = synthetic_combined()
        raw["run"]["args"]["node" + "_url"] = "http://%s:8545" % INT_V1
        raw["nodes"][0]["instance" + "_id"] = ID_V1
        ctx = scrub._Ctx(self.ipmap)
        out = scrub.scrub_combined(raw, self.ipmap, ctx=ctx)
        self.assertNotIn("node" + "_url", out["run"]["args"])
        self.assertNotIn("instance" + "_id", out["nodes"][0])
        self.assertEqual(sorted(ctx.dropped), ["combined.nodes[].instance_id", "combined.run.args.node_url"])

    def test_single_blast_doc_without_nodes(self):
        self.assertEqual(scrub.scrub_combined({"schema": "tn-blast/v2", "x": INT_V2}, self.ipmap),
                         {"schema": "tn-blast/v2", "x": "val-2"})


class ScrubSizingTests(unittest.TestCase):
    def test_string_rewrites_only(self):
        ipmap = scrub.ip_label_map(synthetic_manifest())
        out = scrub.scrub_sizing(synthetic_sizing(), ipmap)
        self.assertEqual(out, {"schema": "tn-bench-sizing/v1", "notes": ["probe ran against val-2"],
                               "per_node": {"val-1": {"disk_gb": 1.5}}})


class ScanTextTests(unittest.TestCase):
    def rules(self, text, manifest=None):
        findings = scrub.scan_text(text, "f.json", manifest=manifest)
        for f in findings:
            self.assertTrue(f.startswith("f.json:"), f)
        return [f.rsplit(": ", 1)[1] for f in findings]

    def assertFires(self, sample, rule, manifest=None):
        text = "prefix %s suffix" % sample
        self.assertIn(rule, self.rules(text, manifest), sample)
        for f in scrub.scan_text(text, "f.json", manifest=manifest):
            self.assertNotIn(sample, f, "a finding must not echo the matched value")

    def test_ten_slash_eight_is_private_ip(self):
        # Pins PRIVATE_NETS: without the 10/8 network this address would be reported as "ipv4".
        self.assertEqual(scrub.scan_text("peer %s" % ip(10, 1, 2, 3), "x"), ["x:1: private-ip"])
        self.assertEqual(scrub.scan_text(ip(10, 255, 255, 254), "x"), ["x:1: private-ip"])

    def test_other_private_ranges_and_public(self):
        for addr in (ip(172, 16, 0, 1), ip(192, 168, 1, 1), ip(100, 64, 0, 1), ip(169, 254, 1, 1)):
            self.assertEqual(self.rules(addr), ["private-ip"], addr)
        self.assertEqual(self.rules(UNMAPPED_PUBLIC), ["ipv4"])
        self.assertEqual(self.rules(ip(172, 32, 0, 1)), ["ipv4"])

    def test_denylist_rules_fire(self):
        cases = [
            ("tn-" + "devnet", "internal-name"),
            (GS + "some-bucket/x", "internal-name"),
            ("obs." + "devnet.example", "internal-name"),
            ("bench-" + "txgen-01", "internal-name"),
            ("internal" + "_ip", "internal-name"),
            ("ops" + "@" + "example.org", "email"),
            (USERS + "alice/x", "local-path"),
            (HOME + "bob/x", "local-path"),
            ("/private" + "/tmp/x", "local-path"),
            ("C:\\" + "Users\\x", "local-path"),
            ("-----" + "BEGIN PRIVATE KEY", "private-key"),
            ("passphrase" + ": x", "secret-assignment"),
            ("\"mnemonic\"" + " = y", "secret-assignment"),
            ("claude" + ".ai/x", "artifact-runtime"),
            ("vm-1.c." + "some-proj" + ".internal", "gcp-internal-dns"),
            ("metadata.google" + ".internal", "gcp-internal-dns"),
            ("0x" + "ab" * 32, "hex64"),
            ("ghp_" + "A1" * 12, "token"),
            ("AKIA" + "ABCDEFGHIJKLMNOP", "token"),
        ]
        for sample, rule in cases:
            self.assertFires(sample, rule)
        self.assertEqual({r for r, _ in scrub.DENYLIST} - {r for _, r in cases}, set(),
                         "every DENYLIST rule needs a sample here")

    def test_manifest_rules(self):
        m = synthetic_manifest()
        self.assertFires(EXT_V1, "manifest-ip", manifest=m)
        self.assertFires(EXT_V1, "ipv4", manifest=m)
        self.assertFires(ID_V2, "manifest-instance-id", manifest=m)
        self.assertFires(ID_B1, "manifest-instance-id", manifest=m)
        self.assertFires(PROJECT, "manifest-name", manifest=m)
        self.assertFires(BUCKET, "manifest-name", manifest=m)
        self.assertFires(ARCHIVE_BUCKET, "manifest-name", manifest=m)
        self.assertFires(GRAFANA_HOST, "manifest-name", manifest=m)
        self.assertEqual(self.rules("id %s" % ID_V2), [], "an instance id is only a leak given the manifest")

    def test_manifest_from_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "manifest.json")
            with open(p, "w") as fh:
                json.dump(synthetic_manifest(), fh)
            self.assertIn("manifest-instance-id", self.rules(ID_O1, manifest=p))

    def test_non_findings(self):
        for text in ("node --bls-passphrase-source /etc/x", "bind 0.0.0.0:8545", "http://127.0.0.1:9090",
                     "icon@2x.png", "\"sha256\": \"0x%s\"" % ("cd" * 32), "/var/lib/bench/out.json",
                     "version v1.2.3", "1.2.3.4.5", "0x" + "ab" * 31):
            self.assertEqual(scrub.scan_text(text, "x"), [], text)

    def test_line_numbers_and_one_finding_per_rule_per_line(self):
        text = "ok\n%s %s\nok\n%s" % (ip(10, 0, 0, 1), ip(10, 0, 0, 2), "tn-" + "devnet")
        self.assertEqual(scrub.scan_text(text, "a/b.json"), ["a/b.json:2: private-ip", "a/b.json:4: internal-name"])


class ScanDirTests(unittest.TestCase):
    def test_committed_clean_samples(self):
        self.assertTrue(CLEAN.is_dir())
        self.assertEqual(scrub.scan_dir(str(CLEAN)), [])
        self.assertEqual(scrub.scan_dir(str(SAMPLES)), [])

    def test_clean_and_leaky_tree(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "series"))
            with open(os.path.join(d, "run.json"), "w") as fh:
                fh.write('{"ok": true}\n')
            with open(os.path.join(d, "series", "leaky.json"), "w") as fh:
                fh.write('{\n "a": 1,\n "peer": "%s"\n}\n' % INT_V2)
            findings = scrub.scan_dir(d)
            self.assertEqual(findings, [os.path.join("series", "leaky.json") + ":3: private-ip"])
            self.assertNotIn(INT_V2, findings[0])
            # A single file scans with its own name.
            self.assertEqual(scrub.scan_dir(os.path.join(d, "series", "leaky.json")), ["leaky.json:3: private-ip"])

    def test_manifest_literals_in_tree(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "report.html"), "w") as fh:
                fh.write("<p>instance %s</p>\n" % ID_V1)
            self.assertEqual(scrub.scan_dir(d), [])
            self.assertEqual(scrub.scan_dir(d, synthetic_manifest()), ["report.html:1: manifest-instance-id"])

    def test_unexpected_files(self):
        import gzip
        with tempfile.TemporaryDirectory() as d:
            with gzip.open(os.path.join(d, "x.json.gz"), "wb") as fh:
                fh.write(b"{}")
            with open(os.path.join(d, "notes.txt"), "w") as fh:
                fh.write("fine\n")
            with open(os.path.join(d, "bin.json"), "wb") as fh:
                fh.write(b"{\x00}")
            findings = scrub.scan_dir(d)
            self.assertIn("x.json.gz:0: unexpected-file", findings)
            self.assertIn("notes.txt:0: unexpected-file", findings)
            self.assertIn("bin.json:0: unexpected-file", findings)
            if hasattr(os, "symlink"):
                os.symlink("notes.txt", os.path.join(d, "link.json"))
                self.assertIn("link.json:0: symlink", scrub.scan_dir(d))


class ScrubInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tb2-scrub-")
        self.scratch = os.path.join(self.tmp, "scratch")
        self.out = os.path.join(self.tmp, "scratch", "scrubbed")
        os.makedirs(os.path.join(self.scratch, "sampler"))
        for name, doc in (("manifest.json", synthetic_manifest()), ("metrics.json", synthetic_metrics()),
                          ("combined.json", synthetic_combined()), ("sizing.json", synthetic_sizing())):
            with open(os.path.join(self.scratch, name), "w") as fh:
                json.dump(doc, fh)
        shutil.copyfile(str(SAMPLER_CSV), os.path.join(self.scratch, "sampler", "val-1.csv"))
        with open(os.path.join(self.scratch, "sampler", "README.txt"), "w") as fh:
            fh.write("not a csv: skipped\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_end_to_end(self):
        summary = scrub.scrub_inputs(self.scratch, self.out)
        self.assertEqual(summary["files"], ["manifest.json", "metrics.json", "combined.json", "sizing.json",
                                            "sampler/val-1.csv"])
        self.assertEqual(summary["ipmap_size"], 5)
        self.assertEqual(summary["rewritten_images"], 2)
        # nodes_file and scratch in combined.run.args.
        self.assertEqual(summary["replaced_paths"], 2)
        # manifest: none (all IP keys dropped); combined: args.nodes + 4 rewritten node urls
        # (val-2 keeps its name); sizing: 1.
        self.assertEqual(summary["replaced_ips"], 6)
        self.assertIn("manifest.blasters[].node_url", summary["dropped"])
        self.assertIn("metrics.prometheus.url", summary["dropped"])
        self.assertEqual(sorted(os.listdir(self.out)),
                         ["combined.json", "manifest.json", "metrics.json", "sampler", "sizing.json"])
        self.assertEqual(os.listdir(os.path.join(self.out, "sampler")), ["val-1.csv"])
        with open(os.path.join(self.out, "sampler", "val-1.csv"), "rb") as a, open(str(SAMPLER_CSV), "rb") as b:
            self.assertEqual(a.read(), b.read(), "sampler csv must be copied byte for byte")
        for name in ("manifest.json", "metrics.json", "combined.json", "sizing.json"):
            with open(os.path.join(self.out, name)) as fh:
                text = fh.read()
            self.assertTrue(text.endswith("}\n"), name)
            json.loads(text)
        self.assertEqual(scrub.scan_dir(self.out, os.path.join(self.scratch, "manifest.json")), [])
        self.assertNotEqual(scrub.scan_dir(self.scratch, os.path.join(self.scratch, "manifest.json")), [])

    def test_sizing_and_sampler_optional(self):
        os.remove(os.path.join(self.scratch, "sizing.json"))
        shutil.rmtree(os.path.join(self.scratch, "sampler"))
        summary = scrub.scrub_inputs(self.scratch, self.out)
        self.assertEqual(summary["files"], ["manifest.json", "metrics.json", "combined.json"])

    def test_required_inputs(self):
        os.remove(os.path.join(self.scratch, "combined.json"))
        with self.assertRaises(FileNotFoundError):
            scrub.scrub_inputs(self.scratch, self.out)

    def test_non_numeric_sampler_cell_fails_closed(self):
        with open(os.path.join(self.scratch, "sampler", "val-2.csv"), "w") as fh:
            fh.write("ts_unix,host\n1767225600,%s\n" % INT_V1)
        with self.assertRaises(ValueError) as cm:
            scrub.scrub_inputs(self.scratch, self.out)
        self.assertIn("val-2.csv:2", str(cm.exception))
        self.assertNotIn(INT_V1, str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.out, "sampler", "val-2.csv")))

    def test_bad_sampler_header_fails_closed(self):
        with open(os.path.join(self.scratch, "sampler", "val-2.csv"), "w") as fh:
            fh.write("ts unix,rss\n1,2\n")
        with self.assertRaises(ValueError):
            scrub.scrub_inputs(self.scratch, self.out)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(SCRUB_PY)] + list(args), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True, timeout=60)

    def test_scan_exit_codes(self):
        p = self.run_cli("scan", str(CLEAN))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("scan: clean", p.stdout)
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as m:
            with open(os.path.join(d, "leak.json"), "w") as fh:
                fh.write('"%s"\n' % EXT_V1)
            p = self.run_cli("scan", d)
            self.assertEqual(p.returncode, 1)
            self.assertIn("leak.json:1: ipv4", p.stdout)
            mpath = os.path.join(m, "manifest.json")
            with open(mpath, "w") as fh:
                json.dump(synthetic_manifest(), fh)
            p = self.run_cli("scan", d, "--manifest", mpath)
            self.assertEqual(p.returncode, 1)
            self.assertIn("leak.json:1: manifest-ip", p.stdout)
            self.assertNotIn(EXT_V1, p.stdout + p.stderr)

    def test_inputs_writes_scrubbed_dir(self):
        with tempfile.TemporaryDirectory() as d:
            scratch, out = os.path.join(d, "s"), os.path.join(d, "out")
            os.makedirs(scratch)
            for name, doc in (("manifest.json", synthetic_manifest()), ("metrics.json", synthetic_metrics()),
                              ("combined.json", synthetic_combined())):
                with open(os.path.join(scratch, name), "w") as fh:
                    json.dump(doc, fh)
            p = self.run_cli("inputs", scratch, out)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("scan: clean", p.stdout)
            self.assertEqual(sorted(os.listdir(out)), ["combined.json", "manifest.json", "metrics.json"])
            self.assertEqual(json.loads(p.stdout[:p.stdout.rindex("}") + 1])["files"],
                             ["manifest.json", "metrics.json", "combined.json"])

    def test_usage_error(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("scan").returncode, 2)


if __name__ == "__main__":
    unittest.main()
