#!/usr/bin/env python3
"""orch-keepboth.py — bench 7, orchestrator only: resolve git conflict hunks in ONE file by keeping both sides.

    tasks/bench7/orch-keepboth.py <file> [--theirs-first]

For hunks where two topics ADDED different lines at the same place (two switch fields in a marked block).
It is NOT safe where the two sides share trailing lines that git kept outside the hunk (two test blocks
appended at a file's end both ending in `Ok(())` / `}`): there, take each block whole from its own branch.
Always run `cargo +$(cat rust-nightly) fmt --all -- --check` right after (it parses the tree) and compile.
Prints each hunk's sizes; a blank line is put between the sides when either holds a `///` doc line.
"""
import sys

def main():
    path = sys.argv[1]
    theirs_first = "--theirs-first" in sys.argv[2:]
    out, ours, theirs, state, n = [], [], [], None, 0
    for line in open(path).read().split("\n"):
        if line.startswith("<<<<<<< "):
            state, ours, theirs = "ours", [], []
            n += 1
            continue
        if line == "=======" and state == "ours":
            state = "theirs"
            continue
        if line.startswith(">>>>>>> ") and state == "theirs":
            first, second = (theirs, ours) if theirs_first else (ours, theirs)
            out.extend(first)
            if any(x.strip().startswith("///") for x in ours + theirs) and first and first[-1].strip():
                out.append("")
            out.extend(second)
            print("hunk %d: ours %d lines, theirs %d lines" % (n, len(ours), len(theirs)))
            state = None
            continue
        (ours if state == "ours" else theirs if state == "theirs" else out).append(line)
    if state is not None:
        sys.exit("unterminated conflict hunk in %s" % path)
    open(path, "w").write("\n".join(out))
    print("resolved %d hunk(s) in %s" % (n, path))

if __name__ == "__main__":
    main()
