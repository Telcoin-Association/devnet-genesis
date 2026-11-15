# W-N — the pull-request texts brought to the stack on today's main (33b727fce)

Units: `W-N03` (PR text 03), `W-N04` (PR text 04), `W-NRM` (PR texts 00, 01, 02 and the epoch-loop text): writers, opus; load `human-writing`. Your launch prompt says which you are. Rules: `tasks/bench7-agent-rules.md` (the common sections), then `tasks/bench7/briefs/u-common.md` (all of it, with ONE change: "main" is now **33b727fcea4f6004d4b0cd2bd7923258e081e94f**, written `33b727fce`; where a text says "on main at 45dce8947", the statement is re-checked at 33b727fce and restated for it). Checkpoint: `tasks/checkpoint-bench7-<unit>.md` (a `status:` header and finished sections, rewritten after each section or text; on start read it and continue). Budget: under 150k tokens.
You own exactly the PR text files your prompt names under `tasks/pr-bodies/` and one sources note per text under `tasks/pr-bodies/notes/` (`bench6-<NN>.n-sources.md`: every statement about code → `path:line` at a named commit; every figure → the log or file it comes from). You post nothing; no `gh` write; git read commands only (never check out, switch, build or fetch); no cargo.

## What happened

The six texts were written for the stack on upstream `main` at 45dce8947. Main moved to 33b727fce (#1848, #1849, #1855), and the repository owner decided: the stack moves onto today's main before any pull request opens; head 04 drops its switch `epoch_record_conflict_halt` and the signer threshold, because #1849 now stops a node unconditionally on a conflicting certified epoch record; head 04 keeps an evidence log line and a counter in front of that stop. The stack is now on 33b727fce as new commits (same subjects unless noted), in repository `/home/drtnarg/coding/telcoin/tn-b7-p2`, local branches:

| PR | head branch (as it will be pushed) | local mark | tip | commits over main | over the head below |
|---|---|---|---|---|---|
| 00 | `feat/bench6-switches-obs` | `b7/n2-00` | b29d59bef | 12 | 12 |
| 01 | `test/bench6-e2e-scaffold` | `b7/n2-01` | 87be96651 | 20 | 8 |
| 02 | `fix/1804-vote-queue` | `b7/n2-02` | 17327280d | 30 | 10 |
| 03 | `fix/epoch-record-closing-block-check` | `b7/n2-03` | c2f266b9c | 33 | 3 |
| 04 | `fix/epoch-record-collector-hardening` | `b7/n2-04` | ff877fb0e | 60 | 27 |
| epoch-loop | `fix/epoch-loop-output-drop` | `b7/n2-xf` | f5f7589f5 | 68 | 8 |

Two later heads exist and are NOT sent yet: `fix/1804-quorum-exec-block` (`b7/n2-05`, 38f00e88e) and `fix/1807-digest-order-hold` (`b7/n2-06`, 500e21afa).
The six pull requests go into `staging/benchmark-bench6-2026-11`, which is fast-forwarded to 33b727fce before they open. Merge order: 00, 01, 02, 03, 04, epoch-loop. Each text says "PR k of 6" and keeps the request to merge with a merge commit.
The old series' commits (for mapping old ids in the texts to new ones by subject): the same branch names WITHOUT the `b7/n2-` mark point at the old base's series (`git log --reverse --format='%h %s' 45dce8947..fix/epoch-record-collector-hardening`, and so on).

## What every text needs

1. Base and stack paragraph: main at 33b727fce; "PR k of 6"; the compare link `https://github.com/Telcoin-Association/telcoin-network/compare/<full sha of the head below>...<full sha of this head>` with the right commit count (PR 00's lower end is 33b727fce's full sha).
2. Every commit id in the text is one of the new series (`git merge-base --is-ancestor <id> b7/n2-06` must hold), with its exact subject. Ids kept on purpose from outside the series: `2df831e3c` (bench 6's build) and, only where the text speaks of the benchmark image, `91a15e223`.
3. Every statement about main is re-checked at 33b727fce and cites `path:line` there. Every statement about what the head does is checked against the code at the head's tip. What the unit hand-backs found untrue at today's main is listed for PR 03 in `tasks/pr-bodies/notes/bench6-03.n-delta.md` and for PR 04 in `tasks/pr-bodies/notes/bench6-04.n-delta.md` (both are reader's notes: verify, then write).
4. Testing section: what ran ON THIS HEAD at its new tip, from the logs (paths in `tasks/checkpoint-bench7-BF-03.md`, `-BF-04a.md` (four parts), `-BF-04b.md`; for heads 00-02 and the epoch-loop head: `tasks/bench7/gate-n1-02.log` (heads 00-02 at 17327280d: workspace check, 1,825 tests) and `tasks/bench7/gate-n1-xf.log` (the epoch-loop head before a comment-only commit below it: workspace check, 2,048 tests)). Results that were measured only on the old base's cut are either dropped or kept with the words "on the stack's earlier cut on main at 45dce8947". Do not carry a number you cannot find in a log.
5. The paragraph that starts `Stack-wide gates` and everything up to the next `## ` heading is replaced by EXACTLY one line: `Stack-wide gates: to be filled in when the gates on the top of the stack have finished.` (the orchestrator replaces it).
6. The benchmark: no fleet has run these heads. A benchmark of the stack's earlier form on main at 45dce8947 (bench 7) is running; state no result of it. Bench 6's measurements stay as the texts have them.
7. `{{slug}}` placeholders stay as they are. `Fixes` / `Refs` lines stay unless a fact changed (#1850's second gap is fixed on main by #1849: PR 04 says so and does not claim it).
8. Lint: `bash tasks/bench7/orch-gh-post.sh lint <file>` prints `LINT-OK` for each of your texts (run from `/home/drtnarg/coding/telcoin/devnet-genesis`; it posts nothing).

## Per unit

- **W-N03**: `tasks/pr-bodies/bench6-03-closing-block-check.md`. Besides the notes: the summary names the three stored-record paths the check now covers (a reused record, this node's own uncertified record 0, the entry); "What changes for every node" says when a close checks twice; the limits name the restored floor block as traced, with the three existing restore tests named as not yet run on this head unless the stack-wide gates run them (leave that to the gates line).
- **W-N04**: `tasks/pr-bodies/bench6-04-collector-hardening.md`. A rewrite of every part that spoke of the halt: two switches; what a conflict does now (the evidence line's exact text and fields, the two counters, main's stop, a restart stops again); the re-certify round's stop through main's recovery; ONE unconditional behaviour (the newest close's vote rounds are never evicted); the walk can reach conflicts a node with the walk off never asks for; what is dropped against the earlier form and why (#1849). Read `tasks/checkpoint-bench7-BF-04a.md` ("Names at the tip", the old → new tables) and the review `tasks/bench7/review/n34-reshaped-heads-report.md` (verdict and findings only). Title proposal if the old one no longer fits (it named the conflict halt): give it in your hand-back; the file `tasks/pr-bodies/STACK-bench6.tsv` is not yours.
- **W-NRM**: `tasks/pr-bodies/bench6-00-switches-obs.md`, `bench6-01-e2e-scaffold.md`, `bench6-02-vote-queue.md`, `bench6-xf-epoch-loop-output-drop.md`. These heads are the old ones picked over (head 00 with one hand-resolved hunk in a test module; the epoch-loop head with one in an e2e helper file); the work is items 1-8: ids, links, counts, every `path:line` at main re-read at 33b727fce (#1848 changed `crates/config/src/node.rs`; #1849 changed `close_epoch.rs`, `state-sync/src/epoch.rs`, tn-lmdb; #1855 changed `crates/node/src/manager/node.rs`, `start_epoch.rs`, the consensus packs), every "on main" sentence, and sentences that name the stack's switches (PR 00 lists the later PRs' switches: head 04 has two now). The epoch-loop text: "Stacked on `fix/epoch-record-collector-hardening`", PR 6 of 6; its recovery advice and README reference re-read at 33b727fce (#1849 rewrote that README section).

## Hand back

Per text: path, word count, lint result; what changed (five lines at most); statements you could not verify and left out; a proposed title if it must change; anything in another unit's text that contradicts yours.
