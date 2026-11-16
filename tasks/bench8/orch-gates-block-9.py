#!/usr/bin/env python3
"""orch-gates-block-9.py — bench 8 program, orchestrator only: write the gates block of the ninth pull request's
text (tasks/pr-bodies/bench6-09-*.md): everything from the line that starts 'Stack-wide gates' up to the next
'## ' heading is replaced. Idempotent.

  orch-gates-block-9.py --tip <sha> --commits <n> [--<gate> <result>]... <file>

A gate whose result is given gets a bullet with that result; a gate without one is listed in a last bullet as
not finished, so the text never states a run that was not read from its log. Gates, in the order they print:
  --fmt       cargo +nightly fmt --all -- --check                      e.g. "clean"
  --clippy    ./etc/ci-lanes.sh clippy                                 e.g. "passed"
  --nextest   cargo nextest run --locked --workspace                   e.g. "5,601 passed, 149 skipped"
  --alone     every commit compiles alone                              e.g. "all 19"
  --sets      make test-restarts / test-epochs / test-sigkill / test-e2e-resync   e.g. "11/11, 11/11, 12/12, 1/1"
  --x3        the e2e tests the stack adds, three runs each            e.g. "all passed"
  --upgrade   make test-upgrade, previous binary main at 33b727fce     e.g. "passed"
  --restore   the three state_export_import tests                      e.g. "passed"
  --hunt      the order hold's 100,000-case model hunt                 e.g. "no counterexample"
  --own       what the commits' own checks covered (the whole sentence; default below)
  --pending   the words in front of the list of gates without a result (default: "Not finished when ... are:")
  --headnote  the words in the brackets after the head's commit (default: "<n> commits on `500e21afa`")
"""
import sys

GATES = [
    ("fmt", "`cargo +nightly-2026-03-20 fmt --all -- --check`"),
    ("clippy", "`./etc/ci-lanes.sh clippy`"),
    ("nextest", "`cargo nextest run --locked --workspace`"),
    ("alone", "Every commit of this PR compiles alone (`cargo check --locked --workspace --all-targets`, warnings denied)"),
    ("sets", "`make test-restarts`, `make test-epochs`, `make test-sigkill` and `make test-e2e-resync`"),
    ("x3", "The e2e tests the stack adds (`exec_block`, `epoch_close_forms`, `epoch_record_walk`, `digest_order_hold`), three runs each"),
    ("upgrade", "`make test-upgrade` with main at 33b727fce as the previous binary (four validators upgraded in place, one at a time)"),
    ("restore", "The three `state_export_import` tests, which restore a node from an exported state"),
    ("hunt", "The order hold's model hunt, 100,000 cases"),
]
OWN_DEFAULT = ("The checks made with each group of commits passed: `cargo check --locked --all-targets`, fmt, clippy with "
               "warnings denied and `cargo nextest run` for the crates the commits touch.")

args = sys.argv[1:]
opts, files = {}, []
names = {g for g, _ in GATES} | {"tip", "commits", "own", "pending", "headnote"}
i = 0
while i < len(args):
    if args[i].startswith("--"):
        key = args[i][2:]
        if key not in names or i + 1 >= len(args):
            sys.exit(f"unknown or incomplete option {args[i]}")
        opts[key] = args[i + 1]
        i += 2
    else:
        files.append(args[i])
        i += 1
if not files or "tip" not in opts or "commits" not in opts:
    sys.exit(__doc__)


def block() -> list[str]:
    done = [(g, text) for g, text in GATES if g in opts]
    left = [text[0].lower() + text[1:] for g, text in GATES if g not in opts]
    headnote = opts.get("headnote", f"{opts['commits']} commits on `500e21afa`")
    out = [f"Stack-wide gates for this PR run on its head, `refactor/remove-bench-switches` at `{opts['tip']}` "
           f"({headnote}), each once: no off arm is left to run them against."]
    out.append("- " + opts.get("own", OWN_DEFAULT))
    for g, text in done:
        out.append(f"- {text}: {opts[g]}.")
    if left:
        out.append("- " + opts.get("pending", "Not finished when this text was last updated, and added here when they are:")
                   + " " + "; ".join(left) + ".")
        if any(g not in opts for g in ("sets", "x3")):
            out.append("- Until the e2e gates above have run, the e2e tests this PR changes have been compiled and not run.")
    out.append("")
    return out


for p in files:
    lines = open(p, encoding="utf-8").read().split("\n")
    starts = [k for k, l in enumerate(lines) if l.startswith("Stack-wide gates")]
    if len(starts) != 1:
        sys.exit(f"{p}: {len(starts)} 'Stack-wide gates' lines")
    a = starts[0]
    b = next((k for k in range(a + 1, len(lines)) if lines[k].startswith("## ")), None)
    if b is None:
        sys.exit(f"{p}: no '## ' heading after the gates line")
    lines[a:b] = block()
    open(p, "w", encoding="utf-8").write("\n".join(lines))
    print(f"{p}: lines {a + 1}..{b} replaced ({len(opts) - 2} results given)")
