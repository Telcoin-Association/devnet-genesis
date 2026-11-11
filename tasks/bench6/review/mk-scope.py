#!/usr/bin/env python3
"""mk-scope.py — write the review scope file of one bench-6 topic group from the integration branch's commit footers.

usage: mk-scope.py <name>            (a key of SPECS below)   |   mk-scope.py --topics   (list topics and sizes)
A commit belongs to a topic by the last `Topic: <slug>` line of its message (git's %(trailers) misses footers that follow a
`Refs #n` line, so the message is parsed here). The branch range is BASE..<branch head>, or STACK_BASE..<stack tip> for a
spec with "range".
"""
import collections, re, subprocess, sys
REPO = "/home/drtnarg/coding/telcoin/telcoin-network-b6"
BASE = "165e3fe01"
OUT = "/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/review/"
T = "/home/drtnarg/coding/telcoin/devnet-genesis/tasks/"
C = "`" + T + "bench6-contract.md`"
G = "`" + T + "bench6-g1-notes.md`"
I = T + "issue-bodies/"
P = "/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/"

def git(*a):
    return subprocess.run(["git", "-C", REPO] + list(a), capture_output=True, text=True, check=True).stdout

def commits(rng):
    out = []
    for h in git("rev-list", "--reverse", rng).split():
        body = git("log", "-1", "--format=%B", h)
        topic = (re.findall(r"^Topic:\s*(\S+)\s*$", body, flags=re.M) or ["(none)"])[-1]
        stat = git("show", "--format=", "--numstat", h)
        ins = sum(int(l.split("\t")[0]) for l in stat.splitlines() if l and l.split("\t")[0].isdigit())
        files = sorted({l.split("\t")[2] for l in stat.splitlines() if l})
        out.append(dict(h=h[:9], s=body.splitlines()[0], t=topic, ins=ins, files=files))
    return out

SPECS = {
 "mdbx-advice": dict(topics=["mdbx-advice"], issue="#1802 (and #1800)", switch="`mdbx_random_advice` (bool; default false)",
  claims=[C + ": the switch table row and the three `mdbx-advice` rows under \"Node log lines and metrics\" (the fields added to `persisted output`, the gauges, the page-operation counter, which fields are left off).",
          G + ", section \"From U3\" (as built; D17: a prefault-off switch is NOT built) and the I-1 / I-1r sections (what the local probe showed and did not show).",
          "The issue body `" + I + "bench5-persist-fsync-amplification.md` and the investigation verdicts `" + P + "I-1/verdict.md`, `" + P + "I-1r/verdict.md`.",
          "Unit checkpoint `" + T + "checkpoint-bench6-u3.md`."],
  questions=["The one `unsafe` block (the `madvise` call in `crates/tn-reth/src/env/mdbx_advice.rs`): is the address range always a live mapping of this process for the whole call, including while libmdbx remaps or grows the map on another thread? What does the code do if the mapping set changes between reading `/proc/self/maps` and the call?",
             "The file identity is taken from the maps line that holds the address of a record read in a short read transaction. Can that pick a mapping of a DIFFERENT file (another MDBX environment in the process, a static file, a second env of the same path)? What if the process has several environments?",
             "Failure handling: every `/proc` read and the advice itself can fail (permissions, a container without `/proc`, a non-Linux build). Confirm that no failure can fail the database open, block a persist, or panic; and that the non-Linux build compiles the feature out.",
             "The per-persist counters run on the persist path of every node, switch on or off (about 115 µs measured). Is anything in that path able to block (a read transaction that waits, a `/proc` read on a process with thousands of threads) or to fail the persist?",
             "The standing operational rule of this program is that nothing but the node opens a live node's database. Does this change itself open a second handle or transaction that could alter libmdbx's read-ahead or prefault state?"]),
 "inflight-bound": dict(topics=["inflight-bound"], issue="none (a bench-6 measure against the execution queue seen in bench 5)", switch="`rpc_admission_backlog_outputs` (count; default 0 = no bound; the benchmark uses 2, or 3 with pipelined persist)",
  claims=[C + ": the switch table row and the row `inflight-bound` under \"Node log lines and metrics\" (who is gated, the JSON-RPC error a refused client gets, close and reopen rule, what the counter counts).",
          G + ", section \"From U11\" (as built; D47-D50: what the arm looks like under saturation, gates closing together, limits above 73 never close, observers not gated) and D9/D52 in \"From U12b\".",
          "Unit checkpoint `" + T + "checkpoint-bench6-u11.md`; the types under review: `crates/types/src/execution_backlog.rs` (`ExecutionBacklog`, `AdmissionGate`)."],
  questions=["The gate reads three relaxed atomics that the node's forwarder and the engine write from other threads. Find an interleaving in which the gate stays closed forever although the engine is idle (for example: forwarded recorded, the engine crashes or the epoch ends before `record_executed`; a restart; replayed outputs after a restart whose numbers are below the last recorded one).",
             "The gate state changes only when an active validator's RPC receives a submission. Is there any state in which no submission can arrive to reopen it, or in which it reopens while execution is still far behind?",
             "A client refused with -32003: TN's own observer forwarder treats it as try-next and requeues. Can a refused transaction be lost, duplicated, or make the forwarder spin (cost per refused hop; all validators closed at once)?",
             "RPC abuse: does the refusal path do any work before the check that an attacker could make expensive? Is the check before decoding and signature recovery on both methods (`eth_sendRawTransaction`, `eth_sendRawTransactionSync`)? Any method that reaches the pool without the gate that a client can call?",
             "Epoch boundary: what do `last_forwarded` and `last_executed` read across an epoch close and the next epoch's first outputs; can the backlog read huge or wrap?"]),
 "vote-starvation": dict(topics=["quorum-exec-block", "voter-lock"], issue="#1804", switch="`quorum_exec_block` (bool), `quorum_exec_block_starved_rounds` (count; 0 = the rule on every header, 4 in the benchmark = own tip by default and the quorum rule for 4 rounds after an own header was cancelled uncertified, doubling up to 128), `vote_queue_fix` (bool)",
  claims=[C + ": the three switch table rows and the rows `quorum-exec-block` and `voter-lock` / `vote-queue` under \"Node log lines and metrics\" (`header proposed` fields `exec_block`, `exec_tip`, `exec_basis`, `exec_policy`; `vote path timing`).",
          G + ", sections \"From I-4\", \"From U1\" and \"From U2\" (design D and why it has two policies: applied to every header it settles 8 outputs behind the tip; D1, D2, D29, D30, D34).",
          "The issue body `" + I + "bench5-execution-behind-vote-starvation.md`, the design `" + P + "I-4/unit-specs.md` (§U1, §U2) and the unit checkpoints `" + T + "checkpoint-bench6-u1.md`, `…-u2.md`.",
          "The e2e result for these fixes, if it exists when you start: `" + T + "checkpoint-bench6-st-a.md`."],
  questions=["The header's execution reference (`exec_block`) is what other validators check before they vote. With the rule on, the proposer names an OLDER executed block than its own tip. Read the vote handler: is a header that names a block the voter has executed, but that is older than the voter expects, always acceptable? Is there a lower bound a voter enforces that the floor rule could fall below (stale reference, epoch boundary, a block before the epoch's first)?",
             "Safety of the reference: can the rule ever make a proposer name a block it has NOT executed, or a block on a different fork than a quorum holds? What does the code use as evidence of what a quorum has executed, and can a Byzantine minority skew it (downward: stall freshness; upward: make honest headers unvotable)?",
             "The adaptive policy keeps per-node state (starved rounds K, doubling to 128, reset rule D29). Find a sequence in which K never resets, or resets every round, and say what the fleet then looks like. Does the state survive an epoch change or a restart, and should it?",
             "`vote_queue_fix` changes how the voter orders or bounds waiting votes (the `prelock_wait_ms` path). Can a vote for a valid header now be dropped or answered late enough to be useless where before it would have been cast? Can one peer's headers starve another's under the new order?",
             "Mixed fleet is the central risk for this topic: proposers with the rule on, voters with it off, and the reverse. Walk both directions."]),
 "sealed-keep": dict(topics=["sealed-keep"], issue="#1807", switch="`sealed_tx_keep` (bool; default false)",
  claims=[C + ": the switch table row and the rows `sealed-keep (pool side)` and `sealed-keep (builder side)` under \"Node log lines and metrics\".",
          G + ", sections \"From U6a\", \"From U6b\" (as built; the node wiring commit; residuals D51: fee-bump replacement, uncertified header holding marks, non-validator orphan branch, marks in memory) and D12-D14.",
          "The issue body `" + I + "bench5-sealed-tx-invisible-drops-and-duplicates.md`, the cases `" + P + "I-2/sealed-keep-test-cases.md`, the node design `" + P + "design/design-node-fixes-for-bench-6.md` §B topic 4 (with its \"Design correction to the issue\").",
          "Unit checkpoints `" + T + "checkpoint-bench6-u6a.md`, `…-u6b.md`, and the e2e result if it exists when you start: `" + T + "checkpoint-bench6-st-b.md`."],
  questions=["Exactly-once: find any sequence in which a marked transaction executes twice, or never (stuck marked forever, so that selection skips it and no path clears the mark). Walk: quorum ack then the batch never certifies; the header is cancelled and its digests re-queued; the batch is orphaned at an epoch close; the node restarts; the mark task fails; the transaction is evicted from the pool while marked; a replacement by fee bump.",
             "The ticket taken before sealing exists to close a race between a late mark and an early execution of the same batch. Is the race closed for every ordering of ack, canonical update and mark? What if two batches hold the same transaction?",
             "Pool accounting with the switch on: marked transactions stay in the pending pool. Can they exhaust per-sender or global pool limits, so that a sender is refused new transactions (or other senders' are evicted) because of transactions that are already sealed? Can a client exploit that to pin pool space?",
             "The nonce view: with the switch off the builder advances the pool's nonce optimistically at the ack; with it on nothing is advanced until execution. What does `eth_getTransactionCount(pending)` answer in between, and can a correct client be led to reuse a nonce?",
             "The orphan pass clears marks on every pool before recovery runs. If recovery then fails partway, are the unmarked transactions safe to be selected again?"]),
 "recovery-pool": dict(topics=["recovery-pool"], issue="#1805", switch="`recovery_threads` (count; default 0 = the global rayon pool as before; 3 in the benchmark)", review_only=True,
  claims=[C + ": the switch table row and the `recovery-pool` rows.", G + ", sections \"From I-3\" and \"From U4a\" / \"From U4b\" (D36: no Criterion; the contention bench is a plain binary whose full run is still owed).",
          "Unit checkpoints `" + T + "checkpoint-bench6-u4a.md`, `…-u4b.md`."],
  questions=["A dedicated rayon pool is created per engine: lifetime, thread count bounds (a huge value in the file), what happens if the pool cannot be built, and whether a panic in a recovery job can take the engine down differently than before.",
             "Signer recovery results feed execution: any ordering or completeness difference between the dedicated pool and the global one?"]),
 "tracker-drain": dict(topics=["tracker-drain"], issue="#1806", switch="`epoch_close_task_drain` (bool), `epoch_record_state_check` (bool); both default false", review_only=True,
  claims=[C + ": the two switch table rows and the `tracker-drain` rows.", G + ", sections \"From I-6\" / \"From I-6b\" and \"From U5\" (D42: the halt does not survive a restart; D43: the 200-ms grace does not read the channel; D44 done).",
          "The issue body `" + I + "bench5-loaded-epoch-boundary-drain.md`; unit checkpoint `" + T + "checkpoint-bench6-u5.md`."],
  questions=["`track_while(fut)` drains the task-tracking channel while the close runs and must never cancel or drop the close future: verify for every exit (a critical task ending, failing, panicking; shutdown).",
             "The state check HALTS a validator. Can a correct node be made to halt by anything other than a real divergence (a record stored for a different epoch, the empty-ring case, a peer's record arriving before this node's closing block is executed)?"]),
 "plumbing": dict(topics=["bench6-switches", "bench6-obs", "bench6-e2e-scaffold", "pipelined-persist"], issue="none (#1819 review note for the digest wait)", switch="all twelve (the plumbing that carries them; no fix here)", review_only=True,
  claims=[C + ": the switch table, the `switches` row (`node switches` line, `tn_node_switch` gauge) and the obs rows.", "`" + T + "bench6/briefs/u0c-api.md` (what the plumbing landed)."],
  questions=["A switch at its default must not be written to a `parameters.yaml` (a genesis ceremony's file must hold the same keys as before): verify the serde attributes for every field and the guard test.",
             "An unknown or mistyped key in `parameters.yaml`: is it rejected or silently ignored? A benchmark arm that misspells a switch must not run as a control arm unnoticed."]),
 "pipelined-persist": dict(topics=None, range=("dc7855cc6", "b6/pipe-stack"), issue="#1800 (execution ceiling)", switch="`pipelined_persist` (bool; default false)",
  claims=["The design `" + P + "I-5/design.md` (§2 state machine, §3 invariants with their enforcing sites, §4 crash and failure matrix, §6.5 go/no-go).",
          G + ", sections \"From U12a\", \"From U12b\", \"From ST-U12a\" (as built; D45, D52-D56) and the API note `" + T + "bench6/briefs/u12a-api.md`.",
          "Unit checkpoints `" + T + "checkpoint-bench6-u12a.md`, `…-u12b.md`, `…-st-u12a.md`, and the e2e result if it exists: `…-st-u12b.md`."],
  questions=["Invariant I3 (one pinned read snapshot per output for every state root of N+1): find any read during N+1's build that could see N's commit half-applied or a later snapshot.",
             "Durability before visibility: is anything that consensus, a peer or the epoch record can see (engine updates, `recent_blocks`, canonical head, the execution backlog) ever ahead of what is durable? RPC `latest` is known to be (D53).",
             "Crash matrix: a SIGKILL at every point between build start of N+1 and commit end of N. Does restart always find a consistent database and replay to the same chain? What about a persist error that is NOT a crash (the pipeline refuses and drains)?",
             "Epoch close: the closing output is a barrier in the engine and the forwarder sends nothing past a close. Can the next epoch's first output ever build on a closing block that is not durable, or with base fees or gas accounting from the wrong epoch?",
             "Two threads touch reth's in-memory chain (the build task and the commit task). Find a data race or an ordering in which the commit removes blocks the build still needs."]),
}

def main():
    if sys.argv[1:] == ["--topics"]:
        by = collections.OrderedDict()
        for c in commits(BASE + "..HEAD"):
            by.setdefault(c["t"], []).append(c)
        for t, cs in by.items():
            print("%-22s commits=%2d +%d" % (t, len(cs), sum(c["ins"] for c in cs)))
        return
    name = sys.argv[1]; sp = SPECS[name]
    if sp.get("range"):
        lo, hi = sp["range"]
        cs = commits(lo + ".." + hi) if False else commits(git("merge-base", lo, hi).strip() + ".." + hi)
        head = git("rev-parse", "--short=9", hi).strip()
        where = "branch `%s` (the integration branch plus the held pipelined-persist commits); read it with `git show <commit>` and `git show %s:<path>` — it is NOT the checked-out branch of the worktree" % (hi, hi)
    else:
        cs = [c for c in commits(BASE + "..HEAD") if c["t"] in sp["topics"]]
        head = git("rev-parse", "--short=9", "HEAD").strip()
        where = "the checked-out branch `bench/bench6-2026-11`"
    files = sorted({f for c in cs for f in c["files"]})
    out = ["# Review scope — %s\n" % name,
           "Upstream issue: %s. Switch: %s." % (sp["issue"], sp["switch"]),
           "Where: %s, head %s. Size: %d commits, +%d lines (tests included).%s\n" % (
               where, head, len(cs), sum(c["ins"] for c in cs),
               " This group gets the code review only: skip the security evaluation unless the review turns up something that calls for it." if sp.get("review_only") else ""),
           "## Commits (the diff under review, in branch order)"]
    out += ["- `%s` %s" % (c["h"], c["s"]) for c in cs]
    out += ["\n## Files touched"] + ["- `%s`" % f for f in files]
    out += ["\n## Where the topic's claims and known residuals are written (read these before the code)"] + ["- " + x for x in sp["claims"]]
    out += ["\n## Questions specific to this topic (2g)"] + ["%d. %s" % (i + 1, q) for i, q in enumerate(sp["questions"])]
    out += ["\n## Your files\n- Report: `%s%s-report.md`\n- Checkpoint: `%scheckpoint-bench6-review-%s.md`\n" % (OUT, name, T, name)]
    open(OUT + name + ".scope.md", "w").write("\n".join(out))
    print(name, len(cs), "commits", sum(c["ins"] for c in cs), "lines", len(files), "files ->", OUT + name + ".scope.md")

if __name__ == "__main__":
    main()
