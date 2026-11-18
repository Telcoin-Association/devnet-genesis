# Brief: unit VC, verification row 12 (the allowlist sync with the node down) on validator 2

Live GCP devnet (project tn-devnet), operator host xerxes, working directory
/home/drtnarg/coding/telcoin/devnet-genesis. Committee of epoch 4 (until 05:24:45Z) = validators 1-4; committee
of epoch 5 (from 05:24:45Z) = validators 1, 3, 4 and node 5: validator 2 (index i=1, `validator-2-devnet`)
leaves the committee at 05:24:45Z. That is why this test is on validator 2 and late in epoch 4: if the stop
costs it the rest of the epoch, the chain is on three of four for a few minutes only, and nothing carries
into epoch 5. Quorum is three: a second committee member out at the same time stalls the chain. You touch
validator 2 only, you first prove validators 1, 3 and 4 are healthy, and you stop at the first doubt.

What is tested: with the node stopped, the allowlist's sync unit cannot read the node's snapshot; it must
report a stale result and leave the firewall set as it was. Second question, recorded but not a pass/fail:
what a stop of about one minute costs a committee member (earlier tonight a 7 s restart of the same node
cost nothing: it was voting again within 21 s).

## On start
Read your checkpoint tasks/ckpt-l2-VC.md if it exists and continue from the first unfinished part. If it says
the stop sequence was STARTED, do NOT run it again: go straight to observing (and, only if the node's unit is
inactive more than 5 minutes after the recorded start, run `onhost 1 'sudo systemctl start telcoin'` once and
say so). Otherwise create it (`status:` header) and rewrite it after EACH part.

## What you may read
- tasks/runbook-l2-2026-11-17.md lines 14-51 (helpers and fleet index) and row 12 of the section 10 table.
- Your own outputs under tasks/l2/w3/vc/.
Nothing else. Hand back rather than explore.

## Hard rules
- The ONLY state-changing action: the one detached sequence of part B on validator 2, run once. No other
  systemctl action on any host (except the single recovery start named above), no ufw/nft/firewall-setup
  changes, no `./devnet-*.sh` except `./devnet-p2p-committee.sh --status`, no edits, no git, no gh.
- Time window for starting part B: not before 05:09:00Z and not after 05:15:00Z (check `date -u`). If you are
  early, wait with a background-free loop inside one shell call (`sleep` until the time; set the tool timeout
  accordingly). If you are late, do not run part B: hand back "too late".
- Before part B: `gcloud auth print-access-token >/dev/null && echo token-ok` (if it fails: hand back
  "credentials"); validators 1, 3, 4 "CvvActive"; public head rising. If not: do nothing, hand back
  "CHAIN AT RISK" as the first words.
- If at any later read one of validators 1, 3, 4 is not "CvvActive", or the public head stops for 60 s: write
  it in the checkpoint, do nothing to any host, hand back at once with "CHAIN AT RISK" first.
- Secrets never on argv, env or logs. At most 30 tool calls, about 120 printed lines per call; raw outputs
  under tasks/l2/w3/vc/. IAP prints a NumPy warning on stderr: add `2>/dev/null` to reads. The owner's login
  may end at any time after about 05:45Z: finish every read you need by 05:35Z.

## Helpers (paste at the top of each shell call)
```
cd /home/drtnarg/coding/telcoin/devnet-genesis && source ./devnet-lib.sh >/dev/null 2>&1; S=/opt/telcoin-node-scripts; RPC=https://rpc.devnet.telcoin.network
rpcj() { printf '{"jsonrpc":"2.0","id":1,"method":"%s","params":%s}' "$1" "${2:-[]}"; }
onhost() { local i="$1"; shift; tn_iap_ssh "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "$*"; }
nodecall() { onhost "$1" "curl -s -m 10 -X POST -H 'Content-Type: application/json' --data '$(rpcj "$2" "${3:-[]}")' http://127.0.0.1:8545"; }
pubcall() { curl -s -m 10 -X POST -H 'Content-Type: application/json' --data "$(rpcj "$2" "${3:-[]}")" "$1"; }
```
Known from tonight: the allowlist tool is `/usr/local/libexec/telcoin/tn-p2p-allow-sync` (not on sudo's PATH);
`status` and `check` are its subcommands; `check` printed `result=ok missing_total=0 mismatch_total=0` with rc 0
on a healthy host and exits 3 when it cannot judge. The table listing carries live packet counters, so compare
the STATELESS listing: `sudo nft -s list table inet tn_p2p_allow | md5sum` (it was `52227139a722a7c8e9418f120967d095`
on validator 2 at 04:15Z; the set may have changed since, so take your own baseline). The sync timer is
`telcoin-p2p-allow-sync.timer`; the service name `telcoin-p2p-allow-sync.service` is inferred from it: confirm
with `systemctl list-unit-files 'telcoin-p2p-allow*'` in part A. The node answers `tn_nodeMode` "CvvActive"
within seconds of starting, before it votes: voting shows in ITS log as `certificate committed` lines whose
`origin=` is its own key (`GgVKMyi7…` for validator 2), and a node that was demoted logs its mode change.
Heads read one host after another differ by the blocks made in between: compare a host with the public head
read just before it.

## Parts
A. Baseline (read-only, any time before 05:09Z). Validators 1-4: `tn_nodeMode`, `net_peerCount`. Public head
   twice 10 s apart. On validator 2: `systemctl list-unit-files 'telcoin-p2p-allow*'`; `systemctl show
   telcoin -p ActiveEnterTimestamp -p NRestarts`; the stateless md5; the element lines of the set (`sudo nft -s
   list table inet tn_p2p_allow | grep -E 'elements|[0-9]+\.[0-9]+'`); `status` and `check` of the tool with
   their rc (save the full `status` output: its fields are the evidence for "stale" later); the last three
   `certificate committed` lines with validator 2's origin from its log, with their times.

B. The sequence, detached on the host so that a lost ssh cannot leave the node stopped. Write "B STARTED
   <UTC>" in the checkpoint first. One ssh command that writes a script to /tmp/l2-row12.sh on validator 2 and
   starts it with `sudo nohup bash /tmp/l2-row12.sh > /tmp/l2-row12.log 2>&1 &`, the script being, in order,
   each step preceded by `date -u +%FT%T.%3NZ` and a label:
   1. the stateless md5 and the element lines;
   2. `systemctl stop telcoin`;
   3. `systemctl start <the sync service>`; then `systemctl show <the sync service> -p Result -p ExecMainStatus
      -p ActiveState`; the tool's `status` (full output) and `check`, each with its rc; the last 15 journal
      lines of the sync service;
   4. the stateless md5 and the element lines again;
   5. `sleep` so that the node has been stopped for 60 s in total, then `systemctl start telcoin`;
   6. `systemctl is-active telcoin`, and "DONE".
   The script must not use `set -e` (a failing read must not skip the start), and step 5's start must run
   whatever the earlier steps returned. Then poll /tmp/l2-row12.log until it shows DONE (about 70 s) and
   copy it to tasks/l2/w3/vc/row12.log.

C. Observe validator 2 until 05:24:00Z or until it is proven voting again, whichever is first: every 20 s for
   the first 3 minutes, then every 45 s: `systemctl is-active telcoin`, `tn_nodeMode`, `net_peerCount`, its
   head beside the public head, and the count of `certificate committed` lines with its own origin logged
   since its start (voting again = that count rising). Every third poll: validators 1, 3, 4 `tn_nodeMode`.
   Record: when the unit was active, when RPC answered, every `tn_nodeMode` value with its time, how far its
   head was behind and when it was level, when its first own certificate was committed after the start (or
   that none was by 05:24:00Z), and from its log since the start the lines matching
   `CvvInactive|CvvActive|too new|epoch_behind|node_mode|catching up|demot` (tail 15).
   Once, about 6 minutes after the start (after its sync timer has run): the tool's `status` and `check`
   (fresh again?), the stateless md5.

D. Closing read at about 05:26Z-05:30Z (after the epoch boundary, validator 2 is no longer a committee
   member): `tn_nodeMode` and `net_peerCount` on i=0..5 (validator 2's mode outside the committee is itself a
   result: record it as read), public head twice, `./devnet-p2p-committee.sh --status`.

## Record
tasks/l2/w3/vc/as-run.md: per part the commands, UTC times, the lines that show each transition, the row's
verdict in its own terms (result stale? set unchanged? node back?), the cost of the one-minute stop in
seconds or "the rest of the epoch", deviations, frictions an operator on mainnet would meet. Mark what you
did not check.

## Hand back
A summary, not file dumps: status (done / stopped at <part> and why / too late / CHAIN AT RISK), the row's
verdict with the tool's exact stale lines, the timeline of the stop and return in six to ten lines, the state
all six hosts were left in, frictions, not checked, absolute file paths.
