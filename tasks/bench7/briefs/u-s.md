# U-S — the script that posts issues, comments and PRs (dry run by default, shim-tested)

Unit: `U-S` (harness-style unit, opus). Rules: `tasks/bench7-agent-rules.md` ("Harness units" and the common sections). Checkpoint: `tasks/checkpoint-bench7-U-S.md`. Budget: under 120k tokens.
You write ONLY `tasks/bench7/orch-gh-post.sh`, `tasks/bench7/tests/test_gh_post.py` and fixtures under `tasks/bench7/tests/fixtures/gh-post/`. Nothing under `benchmark/`. No commits. **You never run a real `gh` write**: every test uses a fake `gh` on `PATH`.

## Why

The orchestrator posts, under the repository owner's account, texts written by other units: new issues (`tasks/issue-bodies/bench6-<slug>.md`), comments on existing issues (`tasks/issue-comments/bench6-<n>.md`), and pull requests (`tasks/pr-bodies/bench6-NN-<slug>.md`) into `Telcoin-Association/telcoin-network`.
A post cannot be taken back cleanly, so the script must make a wrong post hard: dry by default, a lint that refuses text that must not be public, no double post, a record of what was posted.

## `tasks/bench7/orch-gh-post.sh`

```
orch-gh-post.sh [--live] issue   <slug>            # body tasks/issue-bodies/bench6-<slug>.md, title from tasks/issue-bodies/TITLES-bench6.md
orch-gh-post.sh [--live] comment <issue-number>    # body tasks/issue-comments/bench6-<number>.md
orch-gh-post.sh [--live] pr      <NN>              # body tasks/pr-bodies/bench6-<NN>-*.md, head/base/title from tasks/pr-bodies/STACK-bench6.tsv
orch-gh-post.sh lint <file>…                       # the lint alone
orch-gh-post.sh status                             # what the record says was posted
```
- Repository in one variable at the top (`GH_REPO=Telcoin-Association/telcoin-network`), overridable by environment for the tests; roots (`POST_ROOT`) too.
- **Titles**: `TITLES-bench6.md` is a markdown table `| order | slug | title | length |` like `tasks/issue-bodies/TITLES.md` (read it for the shape); the title is the row's third column; refuse a title over 120 characters or a missing row. If the body's first line is an H1, it is dropped from the posted body when it equals the title or its long form (see how the bench-5 bodies and `TITLES.md` relate; keep the body otherwise unchanged).
- **Placeholders**: `{{slug}}` in a body is replaced by `#<number>` from the record (the issue created earlier under that slug); an unresolved placeholder refuses the post and names it.
- **PR stack file** `STACK-bench6.tsv`: tab-separated `NN  head-branch  base-branch  title` (the orchestrator writes it); `gh pr create --repo … --base <base> --head <head> --title <title> --body-file <tmp> --assignee grantkee --reviewer MavenRain --reviewer sstanfield`. Issues: `gh issue create --repo … --title … --body-file … --assignee grantkee`. Comments: `gh issue comment <n> --repo … --body-file …`. Bodies always go through a temp file made with `mktemp`, removed on exit; never through an argument.
- **The lint** (always runs; a failure refuses even a dry run with exit 3 and prints each hit with its line number): any of `Claude`, `Anthropic`, `Co-Authored`, `Generated with`, `🤖`, `AI-generated`, `assistant` as a word, `subagent`, `benchmark/private`, `/home/`, `tasks/` as a path prefix, `xerxes`, `tn-devnet` as a project id, an IPv4 literal other than 127.0.0.1 and the documentation nets, an unresolved `{{`, a `<<…>>` placeholder, a unit name (`\b(A[1-8][a-z]?|A4[eop]|I-[0-9]+[a-z]?|E-[1-4]|U[0-9]+[a-c]?|ST-[A-Z0-9a-z]+|H[0-9]+[a-c]?|r3-[A-Z0-9a-z]+|PT-[0-9]|HD-[0-9]|HB-[0-9])\b`; make the pattern a variable with a comment, and let a line carry an inline allow marker only in the TEST fixtures, never in real bodies), the nicknames `run 2b`, `run 3b`, `run 2`, `run 3`, `run 1` not followed within the same line by a run id `r20[0-9]{6}-[0-9]{4}`. Also: empty body, body over 60,000 characters, a title ending in a period.
- **Dry run (default)**: prints `DRY <kind> <key>`, the exact `gh` argv (shell-quoted), the title, the body's first 12 lines and its word count, the placeholder substitutions; runs no `gh` at all (not even a read).
- **Live** (`--live`): first one read to refuse a duplicate (`gh issue list --repo … --search "<title> in:title" --state all --json number,title` for issues; for a PR `gh pr list --head <head> --base <base> --state all --json number`; for a comment the record alone decides), then the create; parses the URL `gh` prints, writes the record, prints `POSTED <kind> <key> <url>`. The live side effect sits behind an explicit `[ "${LIVE}" = "1" ] || return 0` guard on the line before it; the dry branch returns before any `gh` call.
- **The record**: `tasks/bench7/gh-posted.tsv`, appended only: `UTC  kind  key  number  url  sha256-of-posted-body`. A key already in the record refuses a second post (exit 4) unless `--again` is given with `--live` (for a comment the orchestrator really wants twice; print a loud line).
- Exit codes: 0 ok, 2 usage or missing file, 3 lint, 4 duplicate, 5 `gh` failed (its stderr shown, nothing recorded).
- Bash 3.2 portable, `set -uo pipefail`, `shellcheck -S warning` clean.

## Tests (`tasks/bench7/tests/test_gh_post.py`, python 3.9 grammar, `unittest`, a sandbox root per test)

A fake `gh` on `PATH` that appends its argv to a log and, armed by an environment variable, prints a URL (`https://github.com/x/y/issues/123`) or fails; unarmed it prints `REACHED` and exits 9.
Cases at least: a dry run of each kind makes zero `gh` calls and prints the argv; each lint rule refuses (one fixture line per rule) and a clean body passes; the H1 drop; a placeholder resolved from the record and an unresolved one refused; a live issue post records number and URL and a second post is refused with exit 4; `--again`; a duplicate found by the pre-check refuses without creating; `gh` failing records nothing; the PR argv carries base, head, assignee and both reviewers; the body never appears in an argument.
Mutation anchors (apply by hand, report verbatim, each must fail a named test): invert the live guard; drop the lint call; drop the duplicate refusal; pass the body as `--body`.

## Gates

`bash -n`, `shellcheck -S warning`, `python3 -m py_compile`, `python3 -m unittest tasks/bench7/tests/test_gh_post.py -v` from the repo root.
Another unit is writing `tasks/bench7/tests/test_orch_scripts.py` at the same time: do not touch it; if you need a shared helper, keep your own copy inside your test file.

## Hand back

As the rules say, plus: the usage block as implemented; every lint rule's pattern; the record's format; the mutation anchors with the test each fails.
