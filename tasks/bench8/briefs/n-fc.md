# N-FC — figure-check of `tasks/bench8/no-run-findings.md`

Read `tasks/bench8-agent-rules.md` ("Writers and figure-checks", "Analysis units") and `tasks/bench7/briefs/figcheck.md` (the method and the output shape; it was written for public texts: this file is private, so paths and unit names in it are fine and are not rule breaches). Budget: 35 tool calls, about 120 printed lines per call. You did not write the text. You change nothing but your report and your checkpoint.

The text: `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench8/no-run-findings.md` (164 lines, seven sections). Your prompt names the sections that are yours.
Sources: the units' findings and, above them, their JSON files: `benchmark/private/bench8-prep/N0/plan-figures.md`, `N1/findings.md` + `N1/n1-figures.json`, `N2/findings.md` + `N2/n2-figures.json`, `N3/findings.md` + `N3/figures.json`, `N4/findings.md` + `N4/n4-figures.json` (+ `s1-*.json`, `s3-*.json`, `s5-spread.json`), `N5/findings.md` + `N5/n5-figures.json`. The summary cites `N<k>/<file> <key>` for each figure.

Method, in this order:
1. For every figure in your sections: find it in the unit's findings (same value, same run, same window, same counting unit). Then, for at least every figure that carries a conclusion (the ones in "the answer" sentences and in the tables of sections 4 and 5), open the JSON key and compare with the findings: a findings file can be wrong too. Do it with one small script per unit that prints the keys you need (never dump a JSON file).
2. Where the JSON and the findings disagree, or a key does not exist, re-run that unit's script if its docstring says how and it is quick (they take seconds; run with `python3 -I` from the devnet-genesis root, output to your scratch `/home/drtnarg/.claude/jobs/e50668f4/tmp/<your unit>/`, never over the unit's own files).
3. Redo every derived figure (points, ratios, "about", sums).
4. For every statement of what a finding "decides" or "argues": does the unit's own "what this decides" section say it in that strength? A summary that is stronger than its unit is a Weak item with the unit's wording.
5. [measured] / [inferred] marks: does each match the unit's mark?

Report: one file (path in your prompt), in the shape of figcheck.md: verdict line, errors (numbered; where, what the text says, what the source says with file and key, the EXACT replacement: old string → new string), not traceable, weak, counts. If a Write is refused, return it in your final answer between BEGIN/END markers.

Final answer: the verdict line, the counts, every error and weak item in two lines each, the report path.
