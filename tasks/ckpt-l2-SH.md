status: in-progress (partial: steps 1..8 clean; 9 and 10 blocked on shim emulators, class a)
updated: 2026-11-17T20:56Z

# unit SH checkpoint (shim harness, dg-l2/tasks/l2-shim/)

## Completed sections
- harness: tasks/l2-shim/{fakes.py (1478), run.sh (156), README.md (106), bin/_dispatch + 7 links,
  remote-bin/ 17 links, sentinel/_sentinel + 18 links}
- steps 1..8 CLEAN in one fresh run (state /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/SH/final): deploy rc 0, 0 findings, 0 sentinel hits, 0 real-gcloud logs
- signature gate: --only 10 --sig pending -> deploy exit 3 at step 10, RELEASE_SIG_PENDING, nothing staged (report CLEAN);
  --sig ok -> VALIDSIG by the throwaway key, verify passes, finalize starts
- strictness self-test (/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/SH/selftest): unknown remote command, unknown setup-node flag, path outside the fake fs,
  sentinel tool (forge) -> all recorded; report NOT CLEAN rc 1 even with driver rc 0
- gates: bash -n 0, shellcheck -x 0 (run.sh, _dispatch, _sentinel), py_compile 0, check-bash-portability 0

## Findings (class b)
- none in steps 1..8; step-10 finalize argv (seen before the emulator gap) matches contract 9/Z1

## Shim gaps (class a, next agent)
- step 9 (common/create-obs-instance.sh --wipe-data, kept obs VM): the stack script (sudo VAR=.. bash -s) returned 0
  with no docker call (not verified why); wipe then fails at cd /opt/obs (the kept obs VM in the fake has no /opt/obs).
  Needs: obs VM seeded with /opt/obs + a remote docker compose emulator (down/up/ps).
- step 10: setup-node.sh --phase=finalize emulator (unit file, node.env, start script, .node-meta service keys incl.
  ADMISSION_MODE/BOOTSTRAP_PEERS_FILE/TRUSTED_NODES_FILE, started + enabled), systemctl show, journalctl -n 1
  --no-pager --show-cursor -o cat, then stage-only stop; curl 127.0.0.1:43174 for wait_healthy; ss -ltn.

## Blocked (class c)
- none observed: every driver of steps 1..10 ran (working-tree versions, incl. uncommitted keygen/genesis-build/
  network-config/finalize/release-sign edits)

## Next
- resume: tasks/l2-shim/run.sh --state /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/SH/final --from 9 (or --from 10 --sig ok) and add the emulators above
