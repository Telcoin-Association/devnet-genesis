# Figure-check — re-derive every figure of a public text from its sources

Unit: `FC-<text>` (read-only checker, opus). Rules: `tasks/bench7-agent-rules.md` ("What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Delta reads, writers …", "HAND BACK"). Checkpoint: `tasks/checkpoint-bench7-FC-<text>.md`. Budget: under 150k tokens.
You edit NOTHING but your checkpoint and your one output file. You do not fix the text: you list what is wrong, exactly, so the orchestrator can.

## Method

You did not write the text and you do not trust the writer's source notes: they tell you where to look, not what is true.
For every figure, date, time, count, percentage, run id, commit, issue number, switch name, validator name and quoted log message in the text:
1. Find it in the sources your launch prompt names (the writer's per-figure notes in its checkpoint point at file and line; open the line yourself).
2. Compare value, unit, rounding, and above all **what it counts** (the same window, the same definition, the same run, the same validator). A right number under a wrong label is an error.
3. Where the text derives a figure (a difference, a ratio, "about", "more than half"), redo the arithmetic.
4. Where the text states a relation ("held", "lost", "no longer binds", "confirmed", "not decided"), check that the source says it in that strength, and for that run.
5. Check every claim about code or upstream state the text makes in the present tense against what the sources say (not against the code: say "not checkable from the allowed sources" where that is so).
Also check the text against its own rules: no unit names (A2, I-10, E-3, r3-A7a …), no private paths outside a `_comment` field, no host or person names, no "run 2 / 2b / 3 / 3b" nickname without its run id nearby, no attribution of any tool or assistant, nothing the sources' own "contradictions between units" section rules against.
Cross-check between texts where your prompt names several: the same quantity must read the same everywhere.

## Output

One file (path in your launch prompt), one sentence per line:
- **Verdict line**: `PASS` (nothing to fix), `FIX` (errors listed), or `BLOCK` (an error that changes a conclusion).
- **Errors**: a numbered list; each: where (file, key or section, the phrase), what the text says, what the source says (file:line), the exact replacement text.
- **Not traceable**: figures or statements you could not find in the allowed sources (the text's own claim, where you looked).
- **Weak**: statements stronger than their source, with the source's wording.
- **Rule breaches**: unit names, private paths, nicknames, etc., with the phrase.
- **Counts**: figures checked / matched / wrong / untraceable.
If a Write is refused, return the text in your final answer between `===== BEGIN <path> =====` and `===== END <path> =====`.

## Hand back

The verdict line, the counts, the errors list in full (it is short or the text is in trouble), the output path.
