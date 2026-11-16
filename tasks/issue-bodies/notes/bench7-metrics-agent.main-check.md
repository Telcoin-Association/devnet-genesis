# Main check: bench7-metrics-agent-network-relabel.md against tn-node-deployment `main`

Unit: FC-DR2 (bench 8). Checked 2026-11-16. Read-only. No gh write was run.

**Verdict: FIX (minor).** All four corrected citations are right. Every statement about the file holds on `main`. One lint item is weak ("bench 7" without a run id). There is one optional addition (the checksum file).

**Counts:** 25 checked / 24 ok / 0 wrong / 1 weak (+1 optional observation, not counted).

## Sources

- `main` head today: `b89ada4997113e9394b263e552ace99624d89d80`, 2026-11-10T17:00:26Z, "release: scripts-v2.1.0 (#65)". The repository is public and its default branch is `main`.
- `observability/config.alloy` at `main`: 164 lines, indented with tabs (91 tab lines, no space-indented lines). sha256 `3fa52661…5200db7`, which matches `observability/config.alloy.sha256` on `main`.
- Path history (newest first): `a2162b6` 2026-11-04 ("observability: the vendored config.alloy names deploy-networks-common main 18f8485"), `a739c04` 2026-11-03, `6d5401f` 2026-11-03.
- `compare/a2162b6...b89ada4`: status `ahead`, 148 ahead and 0 behind, so a2162b6 is an ancestor of the head. config.alloy is not among the changed files.
- Tree of `main` (recursive, not truncated): under `observability/` there are only `config.alloy` and `config.alloy.sha256`. There is no dashboard file (`node-metrics.json` or any `dashboard` path) in the repository.
- Public node names: `validator-09`, `validator-05` and `observer` appear in the published bench 7 page backfills (`benchmark/report/backfill/2026-11-15-bench7-*-20k.json`).

## A. The four corrected citations

| # | statement | draft | source on main | verdict |
|---|---|---|---|---|
| 1 | the `network` rule is at "lines 143-146" | l.5 | 143-146: `rule { target_label = "network" / replacement = sys.env("TN_CHAIN") }` | ok |
| 2 | "on main at b89ada4" | l.5 | head of `main` is b89ada4997… (2026-11-10) | ok |
| 3 | "the file last changed in a2162b6" | l.5 | newest path commit a2162b6 (2026-11-04), an ancestor of b89ada4 with no later change to the file | ok |
| 4 | "the comment at lines 121-122" (dashboard `$network`) | l.74 | 121-122: "`network` is added because node-metrics.json's $network template var = label_values(.., network)." | ok |
| 5 | "The `chain` rule just above it (lines 138-141)" | l.77 | 138-141: `rule { target_label = "chain" / replacement = sys.env("TN_CHAIN") }`. Line 142 is blank and the `network` rule starts at 143. | ok |
| 6 | "the file's header comment, lines 8-18, says so" | l.80 | 8-10: "CANONICAL COPY. The log-shipping AND metrics blocks below are kept BYTE-IDENTICAL to the core team's node agent". 12 names the upstream path. 17-18: "If you edit the blocks, mirror the change in adiri-genesis and keep the diff clean". | ok |

## B. Other statements about the file or the repository

| # | statement | draft | source on main | verdict |
|---|---|---|---|---|
| 7 | the first `alloy` block is the file's rule | l.7-12 | Byte-identical to 143-146, tabs included (checked with `cat -A`) | ok |
| 8 | the suggested `alloy` block fits the file's style | l.66-71 | Tab indentation and `=` aligned within the rule, as at 144-145. `source_labels` and `target_label` are valid `rule` attributes. The draft says to place it before the `network` rule, which is needed because rules apply in order. | ok |
| 9 | "the file's `prometheus.remote_write` block sets no queue options" | l.51 | 154-164: `endpoint { url, bearer_token_file, tls_config }` only. "queue" has 0 hits in the file. | ok |
| 10 | the `chain` rule "already writes the same value, `sys.env("TN_CHAIN")`" | l.77 | 140 `replacement  = sys.env("TN_CHAIN")` = 145 | ok |
| 11 | "the dashboard's `$network` variable" exists and reads `network` | l.74 | 121-122 (see #4). Note: the dashboard file is not in this repository, only the comment names it. The draft cites the comment, not a path, so this is not an error. | ok |
| 12 | with the fix, "`network` still carries the chain's name" | l.74 | The fix adds a rule and leaves 143-146 unchanged | ok |
| 13 | the blocks are "kept byte-identical with an upstream copy" | l.80 | 8-10 (see #6). "functional blocks" = the file's "log-shipping AND metrics blocks". The draft does not name the upstream repository, which is right for a public post. | ok |
| 14 | "so the change goes there too" | l.80 | 17-18 "mirror the change in adiri-genesis" | ok |
| 15 | path `observability/config.alloy` exists on `main` | l.5 | Present (164 lines). It is the only path in that repository the draft names. | ok |
| 16 | the file "sets `network` to the chain's name on every series it scrapes from the node" and so overwrites the node's label (title, l.5) | title, l.5 | 107-116: the scrape forwards everything to `prometheus.relabel.tn` (115). The rule at 143-146 has no `source_labels` or `regex`, so the default `replace` sets `network` on every series without condition. | ok |
| 17 | the agent's configuration: "scrape the node, set `network` to the chain's name, remote-write" | l.25 | Pipeline 107-119 → 154. Whether the fleet's agent ran exactly `main`'s copy can't be checked from `main` and is out of scope. | ok |
| 18 | default `replace` action, regex `(.*)`, replacement `$1`; an empty result sets no label | l.73 | Not a statement about the file. These are Alloy `rule` defaults and Prometheus relabel semantics (an empty `replace` result deletes the target label). The draft hedges it with "not tested". | ok |

## C. Lint for a public post

| # | check | draft | finding | verdict |
|---|---|---|---|---|
| 19 | private paths (`benchmark/private`, `tasks/…`) | whole text | none | ok |
| 20 | host names, IP addresses, cloud project id | whole text | none. `validator-0N` and `observer` are node labels already on the published pages. | ok |
| 21 | unit names (A1-A10, HB-n, FC-, R1-R5, N1-N5) | whole text | none | ok |
| 22 | mention of an assistant, agent (AI) or tool | whole text | none. "the agent" always means the metrics collector, and "as we read" is the author's voice. | ok |
| 23 | person's name | whole text | none | ok |
| 24 | run ids given for each run | l.25, 33 | r20261115-1131, r20261115-1450, r20261115-1653 | ok |
| 25 | run nickname without a run id | l.46 | "are not new in bench 7". "bench 7" is a program nickname a public reader can't resolve, and the rules ban a run nickname without its run id. | weak |

## Replacements (apply mechanically)

**#25 (weak), line 46:**

- old: `nodes that lost no batch included, and are not new in bench 7.`
- new: `nodes that lost no batch included, and were already there before these runs.`

## Optional observation (not counted; apply only if wanted)

`main` keeps `observability/config.alloy.sha256`, which matches the file today and last changed together with it in a2162b6. Any fix to the file also has to regenerate that checksum. The draft's fix section does not say so. Suggested addition, line 80:

- old: `so the change goes there too.`
- new: ``so the change goes there too; `observability/config.alloy.sha256` holds the file's checksum and changes with it.`` (the double backticks only delimit the string here, and the inner single backticks are part of it)
