# E5a — the test hook that leaves one epoch's record uncertified on demand (`TN_TEST_WITHHOLD_EPOCH_VOTE`)

Unit: `E5a` (node unit, opus). Rules: `tasks/bench7-agent-rules.md` (all of "Node units", plus the common sections). Checkpoint: `tasks/checkpoint-bench7-E5a.md`. Budget: under 100k tokens.
Worktree: `/home/drtnarg/coding/telcoin/tn-b7-e5a`, branch `b7/e5a`, base = the integration head with the re-certify unit's commits in it (the orchestrator creates it; `crates/node/src/manager/epoch_votes.rs` there carries two earlier units' work: the observability unit and the re-certify unit; you are its third writer). Domains: `tn-domain-epoch`. Topic slug: `epoch-record-collector-hardening`. `Refs #1850`.

## Why

The collector hardening (the walk past an own uncertified epoch; the re-certify path) fixes what happens when the WHOLE network leaves one epoch's record uncertified. A local four-validator test cannot produce that reliably by slowing members down: the record needs 3 of 4 votes, and a slowed member still votes in time or the round's recovery fetches the certificate.
Bench 6's test used the node's existing hook `TN_TEST_EXIT_BEFORE_EPOCH_RECORD` (stop two members before the record): it works but takes about ten minutes and two restarts per attempt (`benchmark/private/bench7-prep/design/design-epoch-record-hardening.md` §C, "e2e, fifth test").
The design recommends a second hook instead: two of four validators withhold their own vote for ONE chosen epoch, so that epoch's record gets 2 of 4 votes and stays uncertified on every node, deterministically, with no stall and no restart.

## What to build

In main's own test-hook pattern (`crates/types/src/test_hooks.rs`: read how the existing hooks are declared, read from the environment, cached, listed, and how production is protected from a set hook; `TN_TEST_EXIT_BEFORE_EPOCH_RECORD` is the closest model; another unit is adding a different hook to that file at the same time: add yours as its own constants, reader and list entries, nothing else):
- `TN_TEST_WITHHOLD_EPOCH_VOTE=<epoch>`: this node does NOT publish its own vote for the record of that one epoch, in the ORIGINAL round at that epoch's close only. Everything else is unchanged: it builds and saves its own record, collects others' votes, runs the round's recovery, and votes normally for every other epoch.
- The hook must NOT silence the later rounds that the fixes add or that main already runs for that record: the N−1 failsafe at the next close on main (so on main with the hook on two members, does the record certify one close later? establish it from the code and say so: the e2e test's timeline depends on it), and the re-certify round behind `epoch_record_recertify`. If withholding only the first round would let main's own failsafe certify the record at the next close, add a second, explicit form so a test can choose: `TN_TEST_WITHHOLD_EPOCH_VOTE=<epoch>` (first round only) and `TN_TEST_WITHHOLD_EPOCH_VOTE_ROUNDS=<n>` (withhold in the first n rounds this node would vote in for that record, default 1; a large value keeps the record uncertified until the hook's node is restarted without it). Keep it as small as the e2e test needs: read `tasks/bench7/briefs/e3.md` and `e4.md` (what the walk and the re-certify do) and the design's §C to see which timelines the test wants: (i) record K uncertified forever on a fleet with both switches off (documents the gap), (ii) the walk on: later records certified and collected past K while K stays uncertified, (iii) re-certify on: K certified at a later close.
- One info line when a vote is withheld: message `test hook: withholding own epoch vote`, fields `epoch`, `round` (which of this node's rounds for that record), target as the file's other lines.
- Unset: byte-identical behaviour (no branch beyond reading a cached `Option`).

## Files you own

`crates/types/src/test_hooks.rs` (your constants, reader and list entries only), `crates/node/src/manager/epoch_votes.rs` (the read site(s) where this node publishes its own vote, and tests at the END of its test module under `// ---- bench7 epoch-record-collector-hardening: withhold hook ----`).
Nothing else: no e2e module (the e2e unit uses your hook), no `handler.rs`, no `crates/state-sync`.

## Tests

Unit tests beside the vote-round tests: with the hook unset, main's tests pass untouched; with it set for epoch K, the round for K sends no own vote and still counts others'; a round for K±1 votes normally; the rounds form; the re-certify round for K (switch on) is NOT withheld beyond the configured rounds; the info line.
Follow main's way of testing an environment-read hook without racing other tests.
Whole-package nextest for the node and types packages (mind the tn-types quirk in the rules); each new test three times by name.

## Gates and review

As the rules say; one `tn-domain-reviewer` (opus) on your diff, domain epoch: can the hook, when unset, change anything; can a set hook make a node sign something it would not otherwise sign or accept something it would not otherwise accept (it must only withhold).

## Hand back

As the rules say, plus: the variables' exact grammar; which rounds exist for a record K on main and with the re-certify switch on, and which of them the hook silences in each form; the three timelines (i) to (iii) as a four-validator test would see them, with the close at which each assertion becomes true; how production is protected from a set hook, in main's terms.
