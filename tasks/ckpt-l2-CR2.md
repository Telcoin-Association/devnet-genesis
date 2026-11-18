status: done (unit CR2: report covers rows 1-84; consistency check PASS)
file: tasks/challenges-l2-report.md

Plan (decided):
- counts for 1-84: 7 fixed in PR #68; 10 worked around/fixed devnet side (25,30,31,32,34,37,48,66,78,84); 67 open (14 devnet-genesis follow-ups incl. 81; 1 operator host)
- section 2 new numbering: 2.7 restarting a validator (82,83) NEW; old 2.7-2.9 -> 2.8-2.10; 2.11 batch limit (80) NEW; old 2.10 -> 2.12 (+73,74,79); old 2.11-2.16 -> 2.13-2.18
- section 3: 3.1 +73,74,83 (39); 3.2 +75,76,77,80,82 (21); 3.3 +79 (2); 3.6 +78,81,84 (19)

Sections:
- [x] header+summary (rows 1-84, counts 7/10/67, 14 devnet + 1 host; bullets for 75 and 82-83 added; 67 bullet reworded)
- [x] section 2 (2.5 +76,77,verif rows 8,11; 2.6 +75; 2.7 NEW restart 82,83; 2.11 NEW batch 80; 2.12 +73,74,79; renumbered)
- [x] section 3 (3.1 +73,74,83; 3.2 +75,76,77,80,82, 35 and 67 cells; 3.3 +79; 3.4 also 81; 3.6 +78,81,84, 61/69/70 cells; heading counts 39/21/2/19)
- [x] section 4 (rewritten from TITLES-l2.md: 26 drafts table, not drafted, unnamed rows)
- [x] section 5 (25 line fixed; 78, 84 added)
- [x] consistency check (script in scratchpad cr2_check.py: rows 1-84 once each in section 3, 26/26 slugs, counts 84 = 7 + 10 + 67, 14 devnet + 1 host, 311 lines: PASS)
