# Sources: l2-checksum-sidecar-rule-conflict

| Item in the draft | Source | Status |
|---|---|---|
| Claim row 22, cited `tools/gen-checksums.sh:11-13` and `AGENTS.md:335` | `tasks/challenges-l2.md` row 22 | checked against code (both match) |
| Quote of `tools/gen-checksums.sh:11-13` | `git -C tn-node-deployment show <ref>:tools/gen-checksums.sh \| sed -n '11,13p'` at both refs (identical) | checked |
| Quote of `AGENTS.md:335` | `git show <ref>:AGENTS.md \| sed -n '335p'` at both refs (identical) | checked |
| main sidecar `6e7ec83c7908…`, file `970e7eeb2a92…`; PR head both `970e7eeb2a92…` | `git show <ref>:ui/requirements.txt.sha256 \| cut -c1-12`; `git show <ref>:ui/requirements.txt \| sha256sum` | checked |
| Claim row 46: dependabot bump of `click` (#63) changed the file not its sidecar; CI checksums job fails on any PR; fixed in PR #68 | `tasks/challenges-l2.md` row 46 (unit F2, 2026-11-17) | taken from the row, source not re-read |
| Title / consequence | `tasks/challenges-l2-report.md` section 4 line 251 | checked |
| CI workflow behaviour (`.github/workflows/ci.yml`) | not opened | not verifiable here |
