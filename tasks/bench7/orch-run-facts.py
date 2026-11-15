#!/usr/bin/env python3
"""orch-run-facts.py — bench 7, orchestrator only: the run facts of one bench 7 run, for §1 of
tasks/bench7/briefs/a-common.md, read from the run's manifest and the deploy log. Prints markdown; the
orchestrator appends what no file holds (the idle check's stop, the export's check lines, the teardown and the
archive lines, what went wrong) under "By hand".

  tasks/bench7/orch-run-facts.py <run> [<deploy12 log>] > tasks/bench7/<run>/run-facts.md
"""
import json
import re
import sys

run = sys.argv[1]
deploy_log = sys.argv[2] if len(sys.argv) > 2 else None
m = json.load(open(f"benchmark/results/{run}/manifest.json"))
ts = m.get("timestamps", {})
out = []
w = out.append
w(f"# Run facts: {run} (from benchmark/results/{run}/manifest.json; cite, do not re-derive)")
w("")
w(f"- Node image: `{m.get('node_image_ref')}`, digest `{m.get('node_image_digest')}`, pinned={m.get('node_image_pinned')}; "
  f"node commit `{m.get('node_git_sha')}`, version `{m.get('node_version')}`; build features `{(m.get('node_probe') or {}).get('build_features')}`.")
w(f"- Storage engine named in the manifest: `{m.get('storage_engine')}`.")
w(f"- Generator image digest `{m.get('txgen_image_digest')}`, commit `{m.get('txgen_git_sha')}`.")
w(f"- Machine `{m.get('machine_type')}`; node disk {json.dumps(m.get('node_disk'))}; boot image `{m.get('node_boot_image')}`.")
h = m.get("harness") or {}
w(f"- Harness at deploy: `{str(h.get('sha'))[:12]}` (dirty={h.get('dirty')}; the dirt is under tasks/, benchmark/ was at its last commit).")
w(f"- Deploy: start {ts.get('deploy_start')}, nodes healthy {ts.get('nodes_healthy')}, contracts done {ts.get('contracts_done')}, "
  f"step 12 done {ts.get('step_12_done')}; coordinated start {json.dumps(m.get('coordinated_start'))}.")
for a in m.get("param_arms") or []:
    w(f"- Arm `{a.get('name')}` ({a.get('file')}, sha256 `{a.get('sha256')}`), applied {a.get('begin')} via {a.get('via')}: "
      + ", ".join(f"`{k}`={v}" for k, v in (a.get("switches") or {}).items()) + ".")
w(f"- Funding: {ts.get('fund_start')} to {ts.get('fund_end')}.")
w("")
w("## Blasts (real phases, `manifest.blasts[].phases`)")
w("")
w("| blast | kind | senders × window | started | ended | rc | preamble | warmup | mixed | cooldown |")
w("|---|---|---|---|---|---|---|---|---|---|")
for b in m.get("blasts") or []:
    ph = {p["name"]: f"{p['start'][11:19]}–{p['end'][11:19]}" for p in b.get("phases") or []}
    w(f"| {b.get('index')} | {b.get('kind')} | {b.get('senders')} × {b.get('window')} | {b.get('started')} | {b.get('ended')} | {b.get('rc')} | "
      + " | ".join(ph.get(k, "-") for k in ("preamble", "warmup", "mixed", "cooldown")) + " |")
w("")
w("Times of day are UTC on the run's date; every figure's window comes from these, not from the planned phases.")
w("")
w("## Chaos (`manifest.chaos`)")
w("")
for c in m.get("chaos") or []:
    extra = {k: c[k] for k in ("planned", "crossed_boundary", "late_secs") if k in c}
    w(f"- {c.get('ts')} `{c.get('node')}`: {c.get('action')} (rc {c.get('rc')}) {json.dumps(extra) if extra else ''}".rstrip())
w("")
w("## End of the run")
w("")
fr = m.get("fleet_ready") or {}
w(f"- Fleet ready check `{fr.get('label')}` at {fr.get('ts')}: ok={fr.get('ok')}, modes: "
  + ", ".join(f"{k[-2:]}={v}" for k, v in sorted((fr.get("modes") or {}).items())) + ".")
w(f"- Deploy result: {json.dumps(m.get('deploy_result'))}.")
w(f"- Abort: {json.dumps(m.get('abort'))}.")
w(f"- Prometheus window in the manifest: {json.dumps(m.get('prom_window'))}.")
w(f"- Log coverage: {json.dumps(m.get('log_coverage'))[:600]}.")
w(f"- Archive: {json.dumps(m.get('archive'))[:400]}.")
if deploy_log:
    pat = re.compile(r"HOST_PROBE_SUMMARY|FSYNC_PROBE|fsync probe|BENCH_BLAST_DONE|BENCH_DEPLOY_RESULT")
    seen = []
    for line in open(deploy_log, errors="replace"):
        if pat.search(line):
            s = line.strip()[:300]
            if s not in seen:
                seen.append(s)
    w("")
    w(f"## Lines of {deploy_log}")
    w("")
    for s in seen[:30]:
        w(f"- `{s}`")
w("")
w("## By hand (the orchestrator)")
w("")
print("\n".join(out))
