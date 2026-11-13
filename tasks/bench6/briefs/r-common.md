# R units (harness fixes after run 1) — what every R unit reads first

Run 1 of bench 6 (r20261112-1520) exposed harness defects; the operations unit wrote each one up with file and line, the smallest fix, its tests and a mutation anchor:
`/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-r20261112-1520/A4o/defects.md` (read ONLY the section your brief names, after `grep -n '^###'`).
Rules: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md`, sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch (every agent)", "Harness and generator units", "HAND BACK", and through it the "Harness and txgen units" section of `tasks/bench5-agent-rules.md`.
Scratch: `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/ef19b04c-8e16-4dbc-9365-9cbe3d19bce9/scratchpad/<unit>/`.

## Every R unit
- Does not commit, does not run `gcloud`, ssh or docker, does not touch `tn-node-deployment/` or `common/`, does not edit a file outside its own list (stop and say so if it needs one).
- `benchmark/tests/check_mutations.py` is NOT yours: apply each mutation anchor by hand, see the named test fail, revert, and write the anchor verbatim (file, exact old text, exact new text, the failing test id) to `tasks/bench6/l-anchors/<unit>.md`. A later unit turns them into cases.
- With every knob unset and on every input the old code handled, the behaviour and every printed line stay as they were, and a test shows it.
- bash 3.2 portable; python 3.9 grammar; `bash -n`, `shellcheck -S warning <file>`, py_compile and the 3.9 grammar check on what you touched.
- Tests: your own module(s) with `python3 -m unittest discover -s benchmark/tests -p <module>.py`, each in the background with a log ending `EXIT=<rc>`; then the existing mutation cases of your module(s): `python3 benchmark/tests/check_mutations.py --modules <module> --jobs 2` (report the count killed). The whole-suite gate is the orchestrator's.
- New prose (comments, README sentences): load the `human-writing` skill first; one sentence per line in Markdown.
- Checkpoint `tasks/checkpoint-bench6-<unit>.md`, rewritten after each section with a `status:` header; on start read it and continue from the first unfinished section. If a Write is refused, do not work around it: return the text in your final answer.
- Final answer: at most 25 lines: status, files changed with +/- counts, every new log tag, manifest key or knob verbatim, each gate with its EXIT and counts, the anchors' path, deviations and open questions.
