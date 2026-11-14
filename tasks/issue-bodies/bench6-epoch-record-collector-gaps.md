# An epoch the network never certifies stops every record collector there; a conflicting certified record is only logged

## What happens

In bench 6 every running node came to hold every certified record within seconds, signed by it or not.
This issue is about two paths the runs never reached, read from code on main at 45dce8947, not observed.

G1, an epoch the whole network leaves uncertified.
If fewer than 7 of 10 members vote for record K within the vote rounds' window (about 65 s), no node holds K's certificate.
Every node's collector then stops at K on every pass and never asks for K+1 or later; the startup sync runs the same walk, so a restart does not help.
A validator still gets later certificates through its own vote rounds; a node with no round at a close (an observer behind at it) or whose round's fetch misses gets none.
K is re-voted once more, at the close of K+1, and at a restart only while K is the latest record; if that round fails, K stays uncertified for good.

A fresh node is worse off.
Established: its records come only from the collector, which stops at K, and both pack paths need records it lacks, so it fetches no pack of K or later.
Undetermined: whether the consensus header walk carries it through K; we did not trace it.
Execution does not need K's certificate: a node that executed K builds its own record and crosses.

G2, a certified record that conflicts with the node's own.
The collector refuses a valid, anchored, certified peer record whose digest differs from the node's own, logs an error and asks again on every pass; the node runs on and gets no later certificate from it.
The vote round's recovery stops the node on the same evidence.

## Evidence

The normal path, measured in three bench-6 runs on ten validators and one observer: [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/), [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/) and an arm walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by rolling restart; it has no public page).
The build (`bench/bench6-2026-11` at `2df831e3c`) has main's collector walk and refusal handling; #1841 since removed a gate on when a pass runs.

- 403 of 407 node-epoch cells show the node holding the certified record, one hash per epoch: 373 through its own vote round, 28 through the collector, 2 through the startup sync after validator-05's kill. The other 4 are validators stopped for teardown before r20261112-1520's last close.
- The longest a running node lacked a certificate the network had was 5.47 s after the first quorum line (the observer, r20261112-1520 epoch 4); 3.86 s in the other two runs.
- The two adaptive-form runs, [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) and [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/): all eleven nodes held every record.

The closest call: r20261113-1630's 18:22:19 close certified with exactly 7 votes, one validator down and two 13-15 s late; r20261114-0000's epoch-7 close also first reached quorum on exactly 7.
No metric reports which certificates a node holds, so neither gap would show today.

## Where in the code

All on main at 45dce8947.

- `crates/state-sync/src/epoch.rs:228-370`: the walk skips epochs held certified (`:243-262`), asks for the next (`:264`) and ends at the first it cannot store (`:343-345`); the loop (`:391-419`) resumes there every 5 s or on a wake-up. The startup sync runs the same walk (`:94-211`).
- Peers serve a record only with its certificate (`crates/consensus/primary/src/network/handler.rs:1909-1919`).
- Re-vote: only N-1 at close N (`crates/node/src/manager/epoch_votes.rs:483-502`) and the latest record at startup (`:563-578`); the comment at `:552-558` says an "N certified, N-1 uncertified" gap is not healed.
- Packs: `request_epochs` (`state-sync/src/consensus.rs:302-354`) asks only for epochs whose record is stored.
- G2: the save fails at `state-sync/src/epoch.rs:279` and `stop_on_local_failure` (`:216-218`, `crates/storage/src/epoch_records.rs:2721-2727`) only logs the `ConflictingRecord`; the vote round's recovery stops the node instead (`epoch_votes.rs:279-289`).
- No test leaves an epoch uncertified across the network; tests at `state-sync/src/epoch.rs:651` and `:798` pin G2.

## What a fix could look like

- Walk past K only when the node holds its own record K uncertified, not the epoch-0 dummy: K+1 then anchors on a record from the node's own execution. Keep K on a retry list. A node without K cannot check K's `next_committee`, so letting it cross needs a protocol decision.
- Re-certify: former members holding K uncertified re-sign it at later closes over a bounded lookback, and verified votes are kept across rounds, so split votes add up. Only this reaches a fresh node.
- G2: stop the node on a conflicting certified record, as the vote round's recovery does, and count it.
- Always on: a gauge of the highest epoch through which every record is certified, and the serving peer on the `retrieved cert` lines.

The first three change network behaviour, so they go behind switches, off by default.
A fix along these lines is in preparation and will be proposed as a PR against the staging branch.

## How to verify

- e2e: withhold votes to leave epoch K uncertified. On main every collector stops at K and an observer started after K gets no later certificate; with the fix every node holds certificates past K, and K certifies once votes return.
- Unit: the collector retrying a gap from its timer alone; a conflicting certified record stopping the node (the two tests above change).
- A benchmark run: every node's gauge reaches the last closed epoch within about 10 s of the first quorum.

## Related

- A separate issue covers the check before a node saves its own record.
- #1806: a loaded close waits on the seventh-fastest member's backlog, which is how G1 would start.
