# Bench 4 — rules for every harness implementation agent (devnet-genesis / tn-transaction-generator)

Repo: /home/drtnarg/coding/telcoin/devnet-genesis (main @ c0f3ca1; bash harness under `benchmark/`, root
drivers `devnet-*.sh`, python3 unittest under `benchmark/tests/`, fixtures under `benchmark/tests/fixtures/<area>/`).

READ FIRST, in this order (nothing else outside your own files unless your prompt names it):
1. tasks/checkpoint-bench4-design.md — section D3: your unit's row, "Contracts (frozen)", your rows in
   "Mutation anchors", and the Rules paragraph. The contracts are the interface the other units code
   against: implement them exactly. If you must deviate, say so in the hand-back; never edit that file.
2. benchmark/private/followups.md lines 900-983 (the bench-3 section): the defect descriptions
   (D-numbers, F-numbers, numbered items 24-40 are the harness defects).
3. tasks/lessons.md, the last ~120 lines: house rules (IAP retries live in devnet-lib, secrets on stdin
   only, `set -e` + command substitution traps, logrotate, parallel-batch cwd).
4. benchmark/tests/test_repo_hygiene.py (what the hygiene test enforces) and one existing test module near
   yours for the fixture style: fake gcloud scripts are python/bash files that dispatch on the remote
   session's first-line header comment; tests that count ssh sessions pin `TN_IAP_RETRIES=0`; fixtures are
   files, not inline heredocs, when longer than a few lines.

HARD RULES
- You are the SOLE writer of the files in your row. Do not edit any other file. If you need something in
  another unit's file, code against the contract and list the need in the hand-back. Shared helpers you
  depend on that have not landed yet (e.g. `tn_iap_fault_kind` from U-H6, `bench_pull_stream` from U-H1,
  `bench_is_stockout` from U-H2): your TEST harness may define a contract-faithful stub ONLY when the real
  function is absent (`declare -F name >/dev/null || name() { …; }` in the test's sourced shim, with a
  comment naming the owning unit); production code never defines a stand-in.
- NEVER run `git add`, `git commit`, `git push`, `git stash`, `git checkout -- <file>` or anything that
  changes the index or discards work. The orchestrator commits. Use `git diff`/`git status` freely.
- Every change to a root driver (`devnet-finalize.sh`, `devnet-keygen.sh`, `devnet-network-config.sh/.py`)
  or shared library is behind a knob whose default keeps today's behaviour byte-for-byte (stdout and the
  remote argv/stdin); a test asserts this where your row says so.
- Secrets only on stdin (`printf '%s\n' "$v" | …`); never argv, never exported, never `set -x`.
- Shell is bash-3.2 portable (no `mapfile`/`readarray`, no `${var,,}`/`${var^^}`, no associative arrays,
  no `|&`, no `${arr[-1]}`; follow the surrounding code). Python is 3.9 grammar (no `match`, no `X | Y`
  annotations, no `str.removeprefix` reliance on 3.9+ — it exists in 3.9, fine; no `tomllib`).
- `set -e` + command substitution: `x="$(fn)" || x=""` so a failing helper fails that node, not the run.
- Checkpoint file: tasks/checkpoint-bench4-<unit>.md. On start read it and resume from the first
  unfinished section. Rewrite it after EACH section with a `status:` header (in-progress|done|blocked) and
  the list of completed sections, including the verbatim mutation-anchor line(s) once they exist. If Write
  is refused, return the full text in your final answer.
- Budget: stay well under 250k tokens. Read big files in ranges (`sed -n 'a,bp'` / Read with offset+limit);
  `bench-lib.sh` is 2447 lines, `benchmark-deploy.sh` 1671, `benchmark-blast.sh` 1589, `make_bundle.py`
  1680, `devnet-finalize.sh` 1246. Locate with `grep -n` first. If you trend past the budget, checkpoint and
  hand back what you have with the remainder listed.
- Absolute paths and `git -C <dir>` everywhere; parallel tool calls share the shell cwd.
- Write comments and messages in plain prose; no Claude/AI attribution anywhere.

VERIFY before hand-back
- `bash -n` and `shellcheck -S warning` on every changed shell file (shellcheck is installed; respect the
  file's existing `# shellcheck disable` lines, add none without a reason in the hand-back).
- `python3 -m py_compile` on changed python; `python3 -W error -c "import ast,sys; ast.parse(open(sys.argv[1]).read(), feature_version=(3,9))" <file>` for 3.9 grammar.
- Your test module(s) green:
  `cd /home/drtnarg/coding/telcoin/devnet-genesis && python3 -m unittest discover -s benchmark/tests -p '<your test file>' -v`
- The whole suite still passes: `python3 -m unittest discover -s benchmark/tests 2>&1 | tail -5` (the only
  known environment failure is `test_slow_blast0_bundle`; it takes a few minutes — run it once at the end).
- Mutation check: apply each of your mutation anchors by hand (edit, run the named test, confirm it FAILS,
  restore the original line exactly, re-run green). Report the anchor line verbatim.
- `tasks/check-bash-portability.sh <file>` on changed shell files if it exists and runs.

HAND BACK (a summary, never file dumps): files changed with +/- line counts; new test names and the full
suite tail; each mutation-anchor line VERBATIM plus its killing test; contract deviations; cross-unit needs
(file, function, why); anything left undone with the exact resume point.
