# Bench 6 — task list and dependencies (from the task-decomposer, 2026-11-10; the orchestrator keeps it)

The task tool was not available to the decomposer, so this file is the task list; ticks live in `tasks/plan.md`.
GP-rust = general-purpose opus agent that loads `tn-rust-skills` + domain skills, writes its row's unit tests, runs package gates,
spawns a `tn-domain-reviewer`. Checkpoints: `tasks/checkpoint-bench6-<unit>.md` (analysis units: `-r1-<unit>` / `-r2-<unit>`).

| unit | agent | blocked by |
|---|---|---|
| I-1 … I-6 | GP opus (+ domain skills; I-6 human-writing) | — (I-3 section 3b after U4b) |
| U0a, U0b, U8 | GP-rust | — |
| U0c | GP-rust | U0a |
| U1, U2, U7 | GP-rust | U0a (they read `parameters()` directly; no U0c needed) |
| U3, U4a, U5, U6a | GP-rust | U0c |
| U4b | GP-rust + tn-add-benchmark | U0c |
| U12a | GP-rust | I-5, U0c |
| U9 | GP-rust | U1, U2 |
| U11 | GP-rust | U5, U0c |
| U12b | GP-rust | U3, U4a, U12a (+U11 if the barrier needs `run_epoch.rs`) |
| U6b | GP-rust | U6a |
| U1v | GP-rust | U1, U2 |
| ST-U12a | tn-write-proptest-agent | U12a (+U12b for the on-vs-off differential; owns the `mod persist_pipeline;` line in `crates/engine/tests/it/main.rs`) |
| U10 | GP-rust | U9, U7 |
| ST-U1 / ST-U5 / ST-U11 | tn-write-e2e-agent | U1 / U5 / U11, each + U0b |
| ST-U6 | tn-write-e2e-agent | U6a, U6b, U0b |
| ST-U12b | tn-write-e2e-agent | U12b, ST-U12a, U0b |
| node integration | orchestrator | all W2a units (U12* droppable at the go/no-go) |
| H0 | GP opus | — |
| H1a, H2, H4, H5a, H6a, H7a, H7b | GP opus | H0 |
| H9a | GP opus | — (running) |
| H1b | GP opus | H1a |
| H3 | GP opus | H2, H5a |
| H5b | GP opus | H5a, H2 |
| H9b | GP opus | H9a |
| H10 | GP opus | H2, H4 |
| H11 | GP opus | H5a, H10 (it writes `bench6-probe.env` for H10's driver) |
| H6b, H8 (last, no cargo job running) | GP opus | every other H unit |
| GCE probe (+ I-1 verdict) | orchestrator | H0, H2, H4, H10, I-1 (+H11 if launched through `launch.sh`) |
| G1 (+ bench-5 republish) | orchestrator + user | I-1 … I-6, GCE probe, W0 archive verify |
| node gates + reviews | orchestrator; tn-review-agent per topic; tn-security-eval | node integration |
| image | orchestrator | node gates, G1 (it settles P3, `epoch_record_state_check`, `parent_grace` defaults), H9b |
| harness gate + dry runs | orchestrator | H6b, H8, image |
| G2 | orchestrator + user | G1, image, harness gate |
| run 1 → r1 A1, A2, A3, A4n-exec, A4n-persist, A5, A6, A7, A4o → r1-D1 → G3 | orchestrator / GP opus | G2 |
| run 2 (+ `final.arm`) → r2 units (no A7) → r2-D1 → report (GP opus + human-writing) → publish (push only after G4) → G4 | | G3 |
| U-STACK (GP-rust), U-TEXT, create issues/PRs, W9 | | G4 |

## Decomposer corrections folded in (orchestrator decisions)
1. GCE probe waits on I-1 (its arms). I-1 may implement the two new local probe arms in `mdbx-writeback-probe` (it is that crate's only
   writer); the memcg-pressure arm joins the GCE arm list if I-1 asks for it.
2. H11 after H10. ST-U12a after U12b for the differential (decided finally when I-5's design is in).
3. `tasks/bench6-contract.md` must carry the exact `node switches` line shape before U0c, H2, H3, H5a, H7a start, and U3's
   `persisted output` fields before H7b / A4n parse them.
4. If G1 picks the P3 no-WRITEMAP arm, a new unit builds the vendored switch before integration (not planned otherwise).
5. The site push (bench-5 republish and bench 6) waits for its gate (G1 / G4); bundles and gates run before.
6. Unassigned steps now owned: bench-5 republish (orchestrator, after G1), image rebuild + re-probe if G3 asks (orchestrator),
   `final.arm` (orchestrator, from G3's answer), the report (GP opus + human-writing).
