#!/usr/bin/env python3
"""orch-save-handback.py — bench 8 program, orchestrator only: save a file an agent returned in its hand-back
between `===== BEGIN <path> =====` and `===== END <path> =====` (its own Write was refused), without printing it.

  orch-save-handback.py <agent transcript .output> <marker path as the agent wrote it> <destination>...

Takes the longest text found between the two markers anywhere in the transcript's JSON lines, drops a uniform
two-space indent if every line has one, writes it to each destination, and prints only sizes and the first and
last line."""
import json, os, sys

src, marker, dests = sys.argv[1], sys.argv[2], sys.argv[3:]
B = f"===== BEGIN {marker} ====="
E = f"===== END {marker} ====="
best = None


def walk(o):
    global best
    if isinstance(o, str):
        if B in o and E in o:
            t = o.split(B, 1)[1].split(E, 1)[0]
            if best is None or len(t) >= len(best):
                best = t
    elif isinstance(o, dict):
        for v in o.values():
            walk(v)
    elif isinstance(o, list):
        for v in o:
            walk(v)


with open(src, encoding="utf-8", errors="replace") as f:
    for line in f:
        if B not in line:
            continue
        try:
            walk(json.loads(line))
        except ValueError:
            pass
if not best:
    sys.exit(f"markers for {marker} not found in {src}")
text = best.strip("\n") + "\n"
ls = text.split("\n")
if all(l.startswith("  ") or not l.strip() for l in ls):
    text = "\n".join(l[2:] if l.startswith("  ") else l for l in ls)
for d in dests:
    os.makedirs(os.path.dirname(d), exist_ok=True)
    open(d, "w", encoding="utf-8").write(text)
ls = [l for l in text.split("\n") if l.strip()]
print(f"{marker}: {len(text.splitlines())} lines, {len(text)} chars -> {len(dests)} file(s)")
print("  FIRST:", ls[0][:110])
print("  LAST :", ls[-1][:110])
