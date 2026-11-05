# Bench 4 obs wave — rules for every implementation agent (addendum to tasks/bench4-agent-rules.md)

Repo: /home/drtnarg/coding/telcoin/devnet-genesis (main @ 28c7623). Everything in tasks/bench4-agent-rules.md applies
(HARD RULES, VERIFY, HAND BACK) with these substitutions:
- Your contract is tasks/checkpoint-bench4-design.md, section "D-A / D-B / D-C" (the owner table, then your unit's
  paragraph). Read that section FIRST and implement it exactly; deviations go in the hand-back, never into the file.
- The frozen facts about the live fleet (obs-devnet, the devnet nodes, bench ↔ obs touchpoints with file:line) are in
  the plan the orchestrator holds; the file:line anchors in your contract paragraph were verified against HEAD today.
  Locate with `grep -n` before editing — do not trust a line number blindly.
- You NEVER touch the fleet: no gcloud against a real project, no ssh, no docker against a remote host. Offline only.
- You never edit `tn-node-deployment/**`, `common/create-instances.sh`, `common/create-obs-instance.sh`,
  `benchmark/pull-lib.sh`, `benchmark/report/*.py`, `devnet-lib.sh`, root `config.sh`, or any file outside your row.
- Hygiene (benchmark/tests/test_repo_hygiene.py): no literal IPv4 except 0.0.0.0/127.0.0.1 and the documentation
  nets; never write the GCP project name as a literal (the test forbids "tn-" + "devnet"); placeholder host for the
  obs VM's internal IP is `bench-obs-internal-ip.invalid`; no absolute home paths.
- Checkpoint: tasks/checkpoint-bench4-<unit>.md (status header + completed sections, rewritten after each section;
  on start read it and resume). Scratch files only under the session scratchpad, in a subdirectory named after your
  unit (the scratchpad is shared by every agent).
- Budget < 250k tokens: read big files in ranges, locate with grep. Hand back a SUMMARY (files, +/- lines, test names,
  suite tail, anchor line verbatim, deviations, cross-unit needs, resume point) — never file dumps.
- Shell is bash-3.2 portable; python 3.9 grammar; `set -e` + command substitution: `x="$(fn)" || x=""`.
- Prose only in comments and messages; no Claude/AI attribution anywhere.
