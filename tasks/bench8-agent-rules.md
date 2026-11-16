# Bench 8 program — rules for every agent (removal units, reviewers, writers, figure-checks, analysis, harness)

Written 2026-11-16 (xerxes) by the orchestrator, its only writer.
Read this file first, then the sections of `tasks/bench7-agent-rules.md` it names, then your own brief.
Where this file and the bench 7 rules differ, this file wins.

## What changed against bench 7

- **Upstream code carries no bench switch.** Bench 7's rule "every behaviour change sits behind its switch" is reversed for everything that targets `main`: a removal unit deletes the switch and keeps the on arm as the only behaviour. Switches stay only on `bench/bench8-2026-11`.
- Checkpoints: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench8-<unit>.md` (shape as in bench 7: `status:`, `updated:` from `date -u`, `completed:`, `remaining:`, `notes:`), rewritten after EACH section. On start, read your own checkpoint and continue from the first unfinished section.
- Scratch: `/home/drtnarg/.claude/jobs/e50668f4/tmp/<unit>/` (create it). Bigger data: `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/work/bench8-scratch/<unit>/` (gitignored). Never `/tmp`.
- **Budget, enforced by you:** at most 35 tool calls in all, and at most about 120 printed lines per call (pipe through `head`, `tail`, `cut -c1-220`, `grep -c`; write long output to a file in your scratch and read the part you need). Finish only the section you are in when you reach 30 calls, rewrite the checkpoint, and hand back partial with the exact resume point. Do not explore past your read list.
- If a Write is refused, do not work around it: return the complete text in your final answer between `===== BEGIN <path> =====` and `===== END <path> =====`.

## Unchanged from `tasks/bench7-agent-rules.md` (read these sections there)

- "What nobody but the orchestrator does": no push, no `gh` write, no cloud, no image; no attribution of any kind; one writer per file; `tn-node-deployment/` and `common/` never edited; no stash, reset, rebase, `checkout -- <file>`, force or branch deletion; absolute paths and `git -C <dir>`; never kill a process you did not start.
- "Node units": code quality rules, log and metric rules, the build environment, **every compiling cargo call through `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh cargo <args>`**, package-scoped builds, real exit codes captured to a log (`<cmd> > "$LOG" 2>&1; echo "EXIT=$?" >> "$LOG"`), commits staged by path, every commit compiles alone, conventional subject, 3-8 line prose body. (The switch rule in that section is the one this file reverses.)
- "Test units": the genesis clock trap; **every `-p e2e-tests` command through `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane2.sh <cmd…>`**, one e2e job on the machine at a time.
- "Harness units", "Delta reads, writers and figure-checks, analysis units", "HAND BACK".

## Repos and worktrees of this program

- devnet-genesis: `/home/drtnarg/coding/telcoin/devnet-genesis`.
- telcoin-network upstream `main` on 2026-11-16: **0554efd4f** (#1859, #1861). The stack, bottom to top, each PR targeting the branch before it: #1862 `feat/bench6-switches-obs` (base `main`) · #1863 `test/bench6-e2e-scaffold` · #1864 `fix/1804-vote-queue` · #1865 `fix/epoch-record-closing-block-check` · #1866 `fix/epoch-record-collector-hardening` · #1867 `fix/epoch-loop-output-drop` · #1868 `fix/1804-quorum-exec-block` · #1869 `fix/1807-digest-order-hold` = **500e21afa** (read-only worktree `/home/drtnarg/coding/telcoin/tn-b7-ngate`).
- The removal worktree: `/home/drtnarg/coding/telcoin/tn-b8-uc`, branch `refactor/remove-bench-switches`, from 500e21afa. One removal unit works there at a time.
- Bench 8's node tree: `/home/drtnarg/coding/telcoin/tn-b8-bench`, branch `bench/bench8-2026-11`, from 91a15e223 (bench 7's image commit; read-only copy `/home/drtnarg/coding/telcoin/tn-b7-stack`).
- Every other worktree under `/home/drtnarg/coding/telcoin/` is read-only for you or not yours at all.

## Removal units (R1-R5)

- Read first: Skill `tn-rust-skills`, then the `tn-domain-*` skills your brief names.
- You delete a switch and everything that exists only for its off arm (or, for R3, the adaptive arm). **No statement on a kept path changes**, except that the `if switch { … }` wrapper around it goes and its body is de-indented. A reviewer will check exactly this with `git diff -w`.
- Line numbers in briefs are from 500e21afa before any removal unit ran: `grep -n` first, always.
- Tests: an off-arm test, a twin test and a test parameter that selects the arm are deleted; a test of the kept behaviour stays and loses its switch plumbing. Do not weaken an assertion of the kept behaviour. If a kept test can no longer be expressed, stop that item and say so.
- Docs and comments that describe the switch are rewritten to describe the behaviour, in present tense, without "switch", "on", "off", "default".
- `crates/config/src/node.rs`: you remove exactly your own field(s), their docs, defaults and their `runtime_switches!` entries. R5 removes the machinery.
- Gates you run yourself (through the slot wrapper): `cargo check --locked --all-targets -p <touched crates>`; `cargo +$(cat rust-nightly) fmt --all -- --check`; `cargo +$(cat rust-nightly) clippy --locked --all-targets -p <touched crates> -- -D warnings`; `cargo nextest run --locked -p <touched crates>` (never `-p e2e-tests` here; e2e modules you edited are compiled with `cargo check --locked --all-targets -p e2e-tests` and run by the orchestrator). One long cargo call per tool call, output to a log, then read the tail.
- Commits: in `tn-b8-uc`, staged by path, each compiles alone. Subject `refactor(<crate>): …` or `test(<crate>): …`. Body: what goes and what stays, in plain words; no bench figure unless your brief gives it with its source; no private label (unit names, finding ids, review names). `Refs #<issue>` where your brief names one. Last line: `Topic: remove-bench-switches`.
- Hand back: tip sha, `git log --oneline <base>..HEAD`, files with +/- counts, every deleted test by name, every kept test you had to edit by name and why, every log message / field / metric you removed verbatim, gates with `EXIT=` and log paths, anything you kept that the brief said to delete (and why), anything you found that the next unit needs.

## Reviewers of a removal unit

- You did not write the unit. Read the diff (`git -C /home/drtnarg/coding/telcoin/tn-b8-uc diff <base>..<tip>`, in ranges, and `git diff -w` for the kept paths), the brief, and the `tn-domain-*` skill your brief names.
- Answer four questions, each with file:line evidence: (1) is anything of the off arm (or adaptive arm) left; (2) did any statement on a kept path change; (3) was a test of the kept behaviour deleted or weakened; (4) does any comment, doc or log text still speak of the switch.
- Verdict: approve / approve with follow-ups / request changes; findings by severity (Critical, High, Medium, Low). You change no file but your report and checkpoint.

## Writers and figure-checks

- Load the `human-writing` skill first. Read `tasks/bench7/briefs/u-common.md` ("Rules for every text") and, for a figure-check, `tasks/bench7/briefs/figcheck.md`.
- Every PR body carries a section headed `## Limits and what a reviewer should look at`.
- Never in posted text: unit names, private paths, host names, the cloud project id, IP addresses, a run nickname without its run id, any mention of an assistant, an agent or a tool.

## Analysis units (N1-N5 and bench 8's analyses)

- Read-only on results and on earlier analyses. Write only under your own output directory and your checkpoint.
- Every figure names its window, its counting unit and the file (and key or line) it came from. Say plainly what you could not measure. A timing fit is not a mechanism. One run per configuration: say so.
- Scripts you write are saved beside your output (`<out>/scripts/`), so a figure-check can re-run them.
