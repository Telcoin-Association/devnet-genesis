# RV — review of a removal unit's commits (you did not write them)

Read `tasks/bench8-agent-rules.md` first: the sections "What changed against bench 7", "Removal units (R1-R5)" (the contract the unit worked under) and "Reviewers of a removal unit" (your job). Budget: 30 tool calls, about 120 printed lines per call. Checkpoint `tasks/checkpoint-bench8-<your unit>.md`. You change no file but your report and your checkpoint; you run no cargo command.

The prompt that started you names: the unit's brief, the commit range, the domain skills to load, and your report's path.

How to read the diff inside the budget:
- `git -C /home/drtnarg/coding/telcoin/tn-b8-uc diff --stat <base>..<tip>` first, then per file `git diff -w <base>..<tip> -- <file>` in ranges of about 110 lines (`| sed -n 'A,Bp' | cut -c1-200`). `-w` hides the de-indentation of a removed `if` wrapper, so what is left on screen is what really changed.
- For every hunk on a KEPT path ask: is this only the wrapper, the switch read or a doc going, or did a statement, a condition, an argument, an order of calls, a log field, a metric or an error change? Quote the lines of anything that is more than plumbing.
- For every deleted test: was it a test of the off arm (fine), or did it also assert something about the kept behaviour that no other test asserts now? `git grep -n` the tip for a test that still covers it; name it.
- For every edited kept test: is the assertion as strong as before?
- `git -C … grep -n -w <switch name> <tip> -- crates docs` for each removed name: anything left?
- Commit messages (`git log --format='%h %s%n%b' <base>..<tip>`): no bench figure without a source, no private label, no attribution, `Topic: remove-bench-switches` last.

Report (the path your prompt names): verdict (approve / approve with follow-ups / request changes); the four answers of the rules file, each with file:line evidence; findings by severity (Critical, High, Medium, Low), each with the exact lines and what you would change; a list "checked and fine" in one line per file. 120 lines at most.

Final answer: verdict, counts by severity, each Critical / High / Medium finding in two lines, the report path.
