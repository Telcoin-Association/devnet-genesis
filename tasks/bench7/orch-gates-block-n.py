#!/usr/bin/env python3
"""orch-gates-block-n.py — bench 7, orchestrator only: replace the 'Stack-wide gates' paragraph of each PR text
with the gate results of the stack's top on upstream main 33b727fce (500e21afa).
Idempotent: everything from the line that starts 'Stack-wide gates' up to the next '## ' heading is replaced.

  orch-gates-block-n.py [--x3 <result>] [--upgrade <result>] [--restore <result>] <file>...

The cargo gates and the four sets that ran are fixed text (tasks/bench7/gate-top-n.log,
tasks/bench7/orch-top-e2e-500e21afa.log). The three results still open when this was written are arguments;
a line whose argument is absent is left out, so the text never states a run that was not read from its log:
  --x3       the 13 e2e tests the stack adds, three runs each     e.g. "all passed"
  --upgrade  make test-upgrade, previous binary main 33b727fce    e.g. "passed with every switch off and with the six on"
  --restore  state_export_import's three restore tests            e.g. "passed"
"""
import sys

args = sys.argv[1:]
opts = {}
files = []
i = 0
while i < len(args):
    if args[i] in ("--x3", "--upgrade", "--restore"):
        opts[args[i][2:]] = args[i + 1]
        i += 2
    elif args[i].startswith("--"):
        sys.exit(f"unknown option {args[i]}")
    else:
        files.append(args[i])
        i += 1
if not files:
    sys.exit(__doc__)


def block() -> list[str]:
    out = [
        "Stack-wide gates ran before these PRs were opened, on the top of the full stack: `fix/1807-digest-order-hold` at `500e21afa`, "
        "103 commits on main at 33b727fce, carries the code of the six heads sent as pull requests and of two later heads not sent yet "
        "(`fix/1804-quorum-exec-block`, `fix/1807-digest-order-hold`).",
        "- `cargo +nightly-2026-03-20 fmt --all -- --check`: clean.",
        "- `./etc/ci-lanes.sh clippy`: passed.",
        "- `cargo nextest run --locked --workspace`: 5,624 passed, 149 skipped.",
        "- Every one of the 103 commits compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied).",
        "- `make test-restarts` 11/11, `make test-epochs` 11/11, `make test-sigkill` 12/12 and `make test-e2e-resync` 1/1, "
        "once with every switch off and once with the full stack's six switches on.",
    ]
    if "upgrade" in opts:
        out.append("- `make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time): "
                   + opts["upgrade"] + ".")
    if "x3" in opts:
        out.append("- The 13 e2e tests the full stack adds, three runs each: " + opts["x3"] + ".")
    if "restore" in opts:
        out.append("- The three `state_export_import` tests, which restore a node from an exported state: " + opts["restore"] + ".")
    # tasks/bench7/orch-merge-check-c1b1eb9fe.log (the local trial merge cf2d13b8e = 500e21afa + c1b1eb9fe).
    out.append("- Against a later main, c1b1eb9fe (#1859): the top merges without conflict, and the merged tree passes "
               "`cargo check --locked --workspace --all-targets` with warnings denied and "
               "`cargo nextest run --locked --no-fail-fast -p tn-primary -p tn-node -p tn-storage` (1,764 passed, 21 skipped).")
    out.append("")
    return out


for p in files:
    lines = open(p, encoding="utf-8").read().split("\n")
    starts = [k for k, l in enumerate(lines) if l.startswith("Stack-wide gates")]
    if len(starts) != 1:
        sys.exit(f"{p}: {len(starts)} 'Stack-wide gates' lines")
    a = starts[0]
    b = next(k for k in range(a + 1, len(lines)) if lines[k].startswith("## "))
    lines[a:b] = block()
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    print(f"{p}: lines {a + 1}..{b} replaced")
