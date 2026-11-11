# H1a blaster create path — original brief (as sent to the first agent; recovered from the session transcript 2026-11-11)

You are harness unit **H1a (blaster create path)** of the bench-6 program. Read /home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md first (all sections except "Node units", "Test units", "Investigations"), then the three older rule files it names for harness units, and follow them exactly. Repo: /home/drtnarg/coding/telcoin/devnet-genesis. Checkpoint: /home/drtnarg/coding/telcoin/devnet-genesis/tasks/checkpoint-bench6-H1a.md (on start, read it and continue from the first unfinished section). You do not commit.

## Why
In three benchmark runs in a row a `gcloud compute instances create` for a load generator ("blaster") hit the compute API's 300-s timeout; the driver aborted or, worse, started that blaster minutes late without saying so, and bench 5 lost a clean load window to it. These are harness defects D36, D37, D39 and D48.

## Spec
Harness design §1 (rows D36 (+D37, D39) and D48, and the bullet list under the table): /home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-harness--arms-and-runs.md. Background on what happened: /home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench5-r20261107-1504/A4o/defects.md (grep the D-numbers). Plan row: /home/drtnarg/.claude/plans/i-want-to-run-groovy-grove.md, section "W2b", row H1 and the "Order and splits" paragraph (you are H1a; H1b follows you in the same files).
Frozen names you must use and never rename: /home/drtnarg/coding/telcoin/devnet-genesis/benchmark/arms/MANIFEST-FIELDS.md (`blasters[].created_at`, `create_secs`, `attempts`, `late_secs`; `abort.reason` values `create_failed` and `late_create` with `abort.node`, `abort.detail`, `abort.unsent`) and the knobs in `benchmark/config.sh` (read-only for you; `BENCH_LIGHT_START_DELAY_SECS` exists now).

## You own
`benchmark/benchmark-blast.sh` — ONLY the create path: `create_vm`, the run loop around the creates, `on_run_exit`, `prev_attempt_unsent`, `node_url` and the URL resolution — and `benchmark/blaster-startup.sh`, plus the fake-gcloud cases in `benchmark/tests/test_blast_argv.py`. The follow-up unit H1b owns the rest of benchmark-blast.sh (the resume line D38, completion polling and deletes D40, phases D42, `blasts[].kind/arm` D45, D46, D47, the tail-scan plumbing, pool state at blast start): do not touch those parts, and keep your edits local so its diff applies cleanly on top of yours.

## Deliver (checkpoint after each)
1. **D36 (+D37, D39)**: after a create call that failed or timed out, `describe` the instance before deciding (the API often created it anyway); one retry at most; a 60-s client timeout under a 90-s alarm around each call; a late-start guard — a blaster whose start would be later than the allowed delay is not started: the run aborts with `abort.reason=late_create` and deletes the blasters that have not sent anything (record `abort.unsent`); a create that truly failed aborts with `create_failed`. Record `created_at`, `create_secs`, `attempts` per blaster as soon as its create is known.
2. **D48**: node URLs are resolved once, before the loop, from the manifest (one `instances list` at most as the design says); `blasters[].late_secs` records how late each blaster started against the common start time.
3. Every live create/delete sits behind an explicit dry-run guard on the line before it, and the dry branch returns; add a shim test (a fake `gcloud` on PATH that prints `REACHED` and exits 9) proving the dry run makes zero live calls.
4. Byte identity: with a create that succeeds first time and on time, the commands sent and the manifest are what bench 5 produced, apart from the new fields (pin with the existing fake-gcloud harness in `test_blast_argv.py`).

## Tests and gates
New fake-gcloud cases: create times out but the instance exists (no second create, blaster used); create fails and the retry succeeds; both fail (`create_failed`, unsent blasters deleted); a create that returns too late (`late_create`); the shim test. `bash -n`, `shellcheck -S warning`, the bash 3.2 portability check (`tasks/check-bash-portability.sh`), `python3 -m unittest` for `test_blast_argv` and any module that sources what you changed; mutation anchors applied by hand in a copied tree and reported verbatim (original line → mutant → killing test) for unit H8.

Hand-back: `git diff --stat` for your files, the functions you changed (so H1b knows where not to collide), every manifest field you write verbatim, gates with exit codes, mutation anchors, anything in the design that did not match the code.
