# Sources: l2-admission-map-complex-keys

| Item in the draft | Source | Status |
|---|---|---|
| Claim, status "worked around (the devnet writes plain `key:` lines)", cited `lib/common.sh ~2882-2908` | `tasks/challenges-l2.md` row 32 | checked against code (matches) |
| Title and consequence | `tasks/challenges-l2-report.md` section 4, line 246 | checked |
| Message `does not start with a map keyed by BLS public key` | `tasks/l2/rh0-report.md` lines 12 and 96-97; code `lib/common.sh:2900` via `git grep -n` at both refs | checked |
| 147-character base58 BLS keys | `tasks/l2/rh0-report.md` line 96 | taken from the report, source not re-read |
| PyYAML `safe_dump` writes them as `? <key>` | `tasks/l2/rh0-report.md` line 96; local `python3 -I -c 'import yaml; ...safe_dump({"A"*128:1})...'` with 128 and 129 characters, both `'? AA'`, PyYAML 6.0.3 | checked |
| Workaround: top-level keys written by hand | `tasks/l2/rh0-report.md` line 98 (`$S/bin/maps.py`) | checked |
| `lib/common.sh:2882-2908` `nest()`; `:2899-2900` the three patterns; `out = out "\n  " s` | `git -C tn-node-deployment show origin/main:lib/common.sh \| sed -n '2880,2908p'` | checked |
| Identical at PR #68 head 79fb24e | `diff` of `sed -n '2870,2960p'` at both refs: identical | checked |
| Rehearsal date 2026-11-17 | brief / run date; rh0 is the local rehearsal before the live run | taken from the row, source not re-read |
| Node's handling of `? key` inside network-config; setup-node.sh's release parser check on such a map | none | not verifiable here |
