status: done (all drivers in scope reviewed; devnet-observability.sh --staged reviewed at 87ad798, which landed after 2f40489)

# Review R2b — launch 2 driver half (dg-l2 `l2/launch-2`, diff 884b760..HEAD)

Harnesses (throwaway, stub `gcloud` / stub `tn_iap_ssh`):
`/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/R2b/pc/` (p2p-committee),
`/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/R2b/td2/` (teardown).
Counts: High 1 · Medium 3 · Low 8.

## Findings

### H1 (High) devnet-p2p-committee.sh:508 with :450-471 — the "head advanced" baseline is the step-1 head, so a validator cut off by `on` passes step 5 and the sweep turns on the next validator
Scenario: deploy step 20 (txgen running), `P2P_COMMITTEE_REQUIRE_ADVANCE=1`. Step 1 reads head h (line 490). The snapshot
wait, `on` and `check` then take several IAP round trips. `pc_host_on` calls `pc_step5 "${i}" "${m}" "${h}" 1` with that
step-1 h, and `pc_whole` returns 0 on the FIRST round where `PC_ME_HEAD > h` and the spread is <= 5 (line 470: with
adv=1 the settle time is not waited). The head moved between step 1 and `on` anyway, and a node whose P2P was cut at
`on` lags its peers only by the blocks made since `on`, a few at "a block every few seconds", so round 0 passes and the
next validator is touched. With four validators that second filtered host stalls the chain.
Verified (harness `R2b/pc`; validator-1's head frozen at the moment `on` ran): step-1 head 103, then
`committee whole (0s): node1=CvvActive@107 node2=CvvActive@111 node3=…@111 node4=…@111`,
`P2P_COMMITTEE validator-1-devnet on … head=107`, and the driver went on to `>>> validator-2-devnet … --p2p-committee on`.
The tool's `check ok` (every committee address is in the set) is then the only guard; step 5 exists for the faults
`check` cannot see (a peer reaching the host from a source its record does not list) and does not catch them.
Why wrong: contract §10 PC: "the chain head must advance before the next host" — after the change took effect.
Fix: take the baseline after `pc_check` succeeds (one `pc_probe` of `me`, or the committee's max head from a first
`pc_whole` round) and require `PC_ME_HEAD` to exceed that max by at least one block while the spread stays <= LAG; in
other words, compare against a post-change reading, never the step-1 head. Same for `pc_host_off` (line 534).

### M1 (Medium) devnet-teardown.sh:304-312, 365-371, 476 — any failed `instances describe` reads as "ALREADY ABSENT": that VM is neither deleted nor reported, and the run ends "teardown complete"
Scenario A: a `gcloud crashed (ReadTimeout)` (the transient the lib's own comment records from bench 3) or an API 5xx
on validator-3's describe during the plan. Stderr is discarded, the VM is printed `ALREADY ABSENT — nothing to do`,
left out of `targets`, and rc stays 0. Deploy step 2 (`create-instances.sh` skips an existing instance) then keeps the
old VM and step 5 aborts on "node-keys already exist".
Scenario B: `--yes --keep-lb` (or an instance subset, DO_LB=0) with expired auth or a wrong `PROJECT_ID`: every
describe fails, every VM is "ALREADY ABSENT", and line 367 exits 0 "Nothing to delete — exiting cleanly." before the
`gcloud auth print-access-token` check at line 377. (A full run is saved only because the failed IG listing sets `?`.)
Verified (harness `R2b/td2`, stub gcloud): A: `validator-3-devnet … ALREADY ABSENT`, four VMs deleted, `teardown
complete. Next: ./devnet-deploy.sh --yes`, exit 0. B: seven `ALREADY ABSENT`, `Nothing to delete — exiting cleanly.`,
exit 0.
Fix: capture stderr and treat only a not-found answer ("was not found") as absent; any other failure goes to LEFT as
"state unknown, not deleted" with rc=1. Move the auth check before the plan. Same for `_lb_exists` (line 162, a failed
describe reads "absent, skipped") and the post-delete verification (line 476, a failed describe reads "gone").

### M2 (Medium) devnet-gateway.sh:359-387 — `--rpc-edge --yes` has no running-node guard; on a stopped fleet it starts rpc-6 alone
`install-caddy.sh --phase rpc-enable` restarts the node with `systemctl restart "$svc"` unconditionally
(tnd install-caddy.sh:2017), which starts an inactive unit. `devnet-gateway.sh --rpc-edge` checks nothing about the
unit. `./devnet-deploy.sh --only 15` (or `--from 15` after a step-14 failure that left nodes stopped, or a manual run
before step 14) starts rpc-6 by itself, outside the coordinated start the plan relies on. Traced (not run).
Fix: before the rpc-enable step, one read-only `systemctl is-active <unit>` on each rpc host; refuse (exit 1, nothing
changed) unless `active`, with "run after devnet-finalize.sh --start-all".

### M3 (Medium) devnet-deploy.sh:377-388 (step 15 -> 16) with devnet-postcheck.sh:243-253, 617-623 — step 16 can fail on a healthy fleet right after step 15
Step 15 restarts rpc-6, node 5's only peer (A-5 b). While it is down and until node 5's trusted dial backs off and
reconnects (45 s in the rehearsal), node 5's snapshot is Grace / Unresolved (A-5 c). Step 16 starts immediately; the
probe reads `tn_admissionSnapshot` and the heads at the start of each host's probe (before the gateway readiness loop),
so node 5's `admission` check reports "effective Grace, want Closed; fallback Unresolved, want null", and node 5's head
may be outside `POSTCHECK_HEAD_LAG`. The deploy stops at step 16; `--only 16` a minute later passes. Traced against
A-5 (not run on the image).
Fix: in step 15 (or the start of step 16), wait until node 5's snapshot is Closed with fallback null (bounded, e.g.
120 s) before the post-checks; or let the postcheck retry the admission/heads reads once after a settle delay.

### L1 (Low) devnet-p2p-committee.sh:544-547 with the main loop :672-688 — `--off --yes` with no targets stops before the culprit
The way back is gated by the committee-whole check. When validator-3's allowlist is the fault, `--off --yes` turns
validator-1 off, finds the committee not whole (because of validator-3) and stops; validator-3 is "untouched". The
printed kill switch names the single host and the header says to run it directly, so the documented path works.
Fix: for `off`, report a not-whole committee as a warning, continue to the next host, still exit 1.

### L2 (Low) devnet-p2p-committee.sh (no trap) — an interrupted run prints no kill switch
Between `on` (line 507) and the end of step 5 a Ctrl-C or a lost terminal leaves a host on and unverified, with nothing
printed. A re-run is correct (`already-on`, resync, check, step 5). Fix: an INT/TERM/HUP trap that prints
`pc_kill_switch` for the host in progress.

### L3 (Low) devnet-p2p-committee.sh:345-366 — after a transport re-send, "Nothing was changed" can be false
The lib re-sends `--p2p-committee on` on ssh rc 255. If the first copy got SIGHUP mid-run (firewall-setup.sh traps HUP,
exit 129, then undoes) or still holds the lock, the re-send can answer rc 1 (lock refused) and the driver prints
"Nothing was changed on <host>". Fix: when the log shows a transport retry (lib's "transport fault" line in the host
log), print the kill switch and "state unknown" instead.

### L4 (Low) devnet-dashboards.sh (whole file) — no refusal under `set -x`
`bash -x ./devnet-dashboards.sh` traces `v=<password>` (line 109), `DASH_PW=<password>` (line 122) and the lib's
`data=<password>x` (devnet-lib.sh:100) to stderr, and under devnet-deploy.sh's run log into `deploy.log` if an operator
exports SHELLOPTS. devnet-stake-node5.sh already refuses (`case $- in *x*`). Same for devnet-observability.sh's token.
Fix: the same three-line refusal at the top of both.

### L5 (Low) devnet-dashboards.sh:202-217, 300-305 — the before/after comparison covers only `enabled` and `domain`
The `enable` phase rewrites the whole Caddyfile; the comparison would not see a changed gateway `port` / `probe_port`
(A-6: present in `gateway-status`) or rpc `advertised_http/ws`. Step 16's post-checks run before step 17, so nothing
re-checks the gateway site after this rewrite. Fix: add those fields to `dash_caddy_state`'s summary.

### L6 (Low) devnet-firewall.sh (the `--enable` gateway note) — tells the operator to re-run `--enable` after step 13 to open 80/443; the deploy has no such step
install-caddy.sh:737-738 opens 80/443 itself when it publishes a site, so the note is probably stale (W3 canary
confirms on the VM). Fix: drop the note or point at install-caddy.sh.

### L7 (Low) README.md:110 — still lists `common/setup-load-balancer.sh` as a runbook step
No script calls it (see ruling below), but the README would lead an operator to rebuild the LB. Fix: remove the line.

### L8 (Low) devnet-stake-node5.sh:345-350 (`epoch_line`) — the per-epoch status is the last `getValidator` read, printed as current
Fix: label it "(status as of activation)" or re-read once per epoch (one `rd` call).

## What I checked and found sound
- devnet-teardown.sh: names come only from `INSTANCE_NAMES` (a subset is validated); the only pattern is the IG list
  `name~'^devnet-rpc-ig-'` (anchored; the bench's VMs are `bench-*`); every LEGACY_LB_* is set, so no empty name widens
  a call; LB delete order and blockers are right; the dry run runs only describe/list; the parallel delete and `wait`
  use `if` (no set -e sibling of the fixed defect); static IPs untouched; the txgen stop is idempotent under re-send.
- setup-firewall.sh: touches only `devnet-*` rules (`_fw_ours`) and only fleet VMs' tags, never `validator` (any
  IAP/SSH rule on it keeps applying; new VMs get it from create-instances.sh); order add tags -> rules -> remove tags ->
  delete (egress DENY before ALLOW) never drops allowed traffic; `allowed[].map().firewall_rule().list()` is gcloud's own
  default list projection (`udp:49590,udp:49594`), canonicalised by `_fw_norm_rules`; a re-run re-reads and converges.
- devnet-p2p-committee.sh: the snapshot judge matches the tool's authoritative rule (contract "The snapshot" 7-11);
  `check` accepted only on exit 0 AND `result=ok`; a lost sentinel after `on` is "unknown" with the kill switch first;
  the retry is bounded (8 x 15 s) and only on the three wait-able texts; `</dev/null` on the mutating call.
- devnet-gateway.sh: every value in a remote command is validated (image digest, URL, domain, IPv4, ports) and quoted;
  flags match setup-gateway.sh's parser (:611-650, :671-680) and install-caddy.sh's (:3857-3880); the standalone
  sequence on a stopped validator keeps it stopped (edit-config.sh:4004-4007); the plan is built before the first change.
- devnet-postcheck.sh: probes fail closed (empty listener sets, a missing done line, a non-numeric `issues`, a missing
  `reach_*` rc, an unread head are all FAIL); TLS is verified (no `-k`); the public identity check is decisive enough:
  a valid certificate binds the name to the host, and the key comparison catches a node answering for itself.
- devnet-deploy.sh: the dashboards preflight runs exactly when 17 is in range; the run-log `exec … tee` keeps stdin a
  TTY (step 4's pause works) and does not change exit codes; the DNS check uses `dig` (ignores /etc/hosts) and fails
  closed on a stale cache; `--from` past 9 skips the obs wipe and is warned when it includes it.
- devnet-stake-node5.sh: node 5 found by role (index 4; rpc-6 is `rpc`); the sync gate fails closed on any unreadable
  read; epoch reads are retried and validated at both guards; sends are guarded by fresh status reads, so a re-run does
  not resend; keys never on argv.
- devnet-dashboards.sh: the password goes builtin `printf` -> lib buffer -> gcloud stdin, never argv/env/log text.
- devnet-txgen.sh (VM-clock `since`, journal of this start only), devnet-startup.sh (same apt pattern as docker),
  devnet-observability.sh `--staged` (refuses an active node, stops a node the installer started, stops the sweep).

## Rulings on the open questions (-> R2b)
1. Lib re-send of changing commands (review-notes:70): acceptable as is. Each is safe to run twice:
   `setup-gateway.sh --enable` (idempotent install), `firewall-setup.sh --enable --gateway-from` (replaces the list),
   `edit-config.sh --set gateway_upstream=IP` (the "RPC already public" refusal is skipped once GATEWAY_UPSTREAM is
   recorded, edit-config.sh:2915-2921), `install-caddy.sh rpc-enable` (a second restart of rpc-6 only),
   `--p2p-committee on` (already-on = resync; but see L3 for the message), `systemctl stop`, the txgen restart (the
   second copy re-reads the clock), `install-caddy.sh --phase enable` and `setup-observability.sh` (stdin buffered by
   the lib and re-sent).
2. `--rpc-edge` before the start (73): defect to fix: M2.
3. setup-firewall.sh's format expression (79): acceptable (it is gcloud's own default projection); keep W3's read-only
   `--status` and dry run before step 8.
4. Delete + re-create on a direction/action change (80): acceptable: only a hand-edited rule takes that path, and at
   step 8 the fleet was just rebuilt; the gap is one API call.
5. `tn_nodeMode` as a plain string over loopback (85): fails closed either way (a quoted value never equals `Observer`,
   the sync gate dies after its timeout); W3's first IAP read settles it. The watch's status from the last read (86):
   acceptable, wording L8.
6. `--off --yes` stops at the first not-whole host (96): acceptable for the documented path (direct per-host command);
   recommended change L1.
7. No caller of `common/setup-load-balancer.sh` (101): confirmed, no script in dg-l2 outside `common/` calls it
   (grep); only README.md:110 and old records name it (L7).
