# Bench 7 analysis: decisions the orchestrator took on the units' questions (read by the comparison units and the report writers)

Each line: the question, the decision, who asked. Nothing here is a figure; figures are cited from the units' files.

- Arms summary rows (KPI analysis, run 7a): `arms.json` has no row for blast 1 when no second of it has all ten generators in their mixed phase, and its blast-2 row ends at the kill. No row is added and the tool is not changed during the analysis; a unit that needs blast 1 or the part of blast 2 after the kill extracts it itself and says so.
- Rejoin mark of validator-05 (certification analysis, run 7a): the certification analysis keeps its own mark (the first `cvv_active` sample of `tn_node_mode`); the recovery analysis's `recovery.json` is the source for the rejoin time itself wherever a text states it. In run 7a both fall after blast 2's end, so no blast-2 figure depends on the choice.
- "First 120 s" of blast 2 (certification analysis, run 7a): the comparison of run 7a with run 7b uses the common brief's definition (from the start of the mixed phase); the comparison with bench 6 uses bench 6's definition (from the start of the warm-up), because bench 6's figures were made that way. Each table names which one it uses.
- Budget: the first units used 260-270k tokens against a 200k budget. Later units reuse the first run's script copies; a unit past 200k finishes its current question, checkpoints and hands back.
