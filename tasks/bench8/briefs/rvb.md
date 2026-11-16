# RVB — review of a chain of bench 8 node commits (you did not write them)

Read `tasks/bench8-agent-rules.md` ("What changed against bench 7") and `tasks/bench8/briefs/b8-common.md` (the contract the units worked under: what this build is, the rules for every B8 unit). Budget: 34 tool calls, about 120 printed lines per call. Checkpoint `tasks/checkpoint-bench8-<your unit>.md`, rewritten after each commit reviewed. You change no file but your report and your checkpoint; you run no cargo command.

The prompt that started you names the worktree, the commit range, the units' briefs, the skills to load and your report's path. What each commit claims to add is in `tasks/bench8/node-fields.md` (the orchestrator's verbatim record of the units' hand-backs): check the code against it and say where it is wrong.

This branch is a BENCH branch: it is never merged upstream, and it produces a measurement. So the questions are these, per commit, each with file:line evidence at the range's tip:

1. **No behaviour change.** With every parameter at its default, does anything but logging and metrics differ from the base: a header's contents, a vote's decision, a certificate's handling, the order or timing of sends, what is stored, an error returned? A moved read, a new clone on the hot path, a changed signature that reorders evaluation all count. (The one intended exception is the parameter `quorum_exec_block_floor_outputs` of the main chain, and only when it is not 8.)
2. **Is each logged value what its description says?** Read where each field is computed. Off-by-one, the wrong clock or instant, a value read after it changed, a count that double-counts, an `Option` that silently logs 0: quote the lines. Is every list bounded and deterministic in order (no HashMap/HashSet iteration unsorted)?
3. **Cost.** These lines run at about 25 headers a second per fleet, about 10 certificates and 9 vote answers per header per node, and one engine line per output (about 1.2 per second). Any lock taken on a hot path, a lock held across an `.await`, an allocation per transaction, a file read or syscall per header or per vote, a clone of a batch or a certificate? Estimate the added log bytes per second per node for the line that grows most.
4. **Tests.** Does a test pin each new field's VALUE (not only its presence)? Which field has no test of its value?
5. Code rules: no `unwrap()`/`expect()` outside tests, `///` docs on new items, no new dependency, commit messages without attribution or private labels, `Topic: bench8-obs` last.

Report (the path your prompt names), 130 lines at most: verdict (approve / approve with follow-ups / request changes); per commit the five answers in one or two lines each; findings by severity (Critical: the bench's result would be wrong or the node could misbehave; High: a field's value is wrong or a cost that changes what is measured; Medium; Low), each with the exact lines and the smallest fix; corrections to `tasks/bench8/node-fields.md` (old sentence → new sentence).

Final answer: verdict, counts by severity, each Critical / High / Medium finding in two or three lines, the Lows in one line each, the corrections to node-fields.md, the report path.
