# Plan: register `xerxes` as a maintainer peer on the WireGuard admin overlay (2026-10-09)

`xerxes` = Ubuntu 26.04 box (user `drtnarg`), reached from hannibal over the `xerxes-wg0`
tunnel at 10.10.10.1 (`ssh xerxes`). It becomes a second maintainer device for grant, at
the next free maintainer IP **10.100.9.7**. Private keys are minted ON xerxes and never leave it.

## Pre-flight facts (verified read-only before approval)
- Live hub has 21 peers == `origin/main` registry exactly. Local `common/` is 13 behind: a push
  from the stale registry would DROP validator-9-adiri + all 5 devnet nodes. → pull first.
- xerxes: wg-tools, git, gcloud present; no `~/.config/tnvpn`; sudo needs a password;
  runs its own `wg0` server on 10.10.10.0/24 — no overlap with 10.100.0.0/16 (routes checked).
  GitHub reachable from xerxes via forwarded agent.
- hannibal: `gcloud` token expired → `hub_redeploy` (IAP) needs `gcloud auth login` first.
- `/Users/grant/coding/telcoin/tn-node-deployment` (add-peer mirror target) is 65 behind.

## Steps
### Phase 0 — prerequisites (USER, interactive)
- [ ] U1 `gcloud auth login` on hannibal (browser)

### Phase 1 — sync (hannibal)
- [x] 1.1 `git -C common pull --ff-only` (already current — user had pulled)
- [x] 1.2 `git -C ../tn-node-deployment pull --ff-only` — untracked tasks/todo.md (35 unique local lines)
      collided with upstream's tracked file → moved to tasks/todo.local-2026-07-24.md, then ff to 9e97073
- [x] 1.3 re-diff live hub peers vs pulled registry → identical (21 == 21)
      (was BLOCKED 06:45: NordVPN connected 06:41, default route via utun8 swallowed both WG
      endpoints; user disconnected NordVPN, then 1.3 passed)

### Phase 2 — mint xerxes credentials (on xerxes, no sudo)
- [x] 2.1 clone deploy-networks-common → `~/coding/telcoin/deploy-networks-common`
- [x] 2.2 `wgvpn/dev-setup.sh --no-bringup --no-aliases` → WG keypair + dedicated SSH key + tn-wg0.conf (@IDX@)
- [x] 2.3 copy back the two PUBLIC keys only (WG uOv8lONi…UVA=, SSH SHA256:EjPkbL6H…ZBD4)

### Phase 3 — register (hannibal)
- [x] 3.1 `./common/wgvpn/add-peer.sh xerxes '<wg pub>' <ssh pub file>` → registry row + peers/ssh/xerxes.pub,
      IAP hub re-render (`wg syncconf`, no tunnel drop), key fan-out, mirror into tn-node-deployment.
      Fan-out: adiri 1–10 OK; 5 devnet nodes failed "REMOTE HOST IDENTIFICATION HAS CHANGED" (stale
      known_hosts from the 2026-09-17 rebuild). Verified each new ed25519 fingerprint out-of-band over
      IAP (all 5 matched the overlay-presented ones), backed up known_hosts to scratchpad,
      `ssh-keygen -R 10.100.2.{1..5}`, re-ran sync_keys_to_registry_nodes on the 5 → all OK (7 keys).
- [x] 3.2 verify hub: 22 peers, xerxes @ 10.100.9.7/32; hub tnadmin authorized_keys.tnvpn = 7 lines

### Phase 4 — commit + push (no Claude attribution, per lessons.md)
- [x] 4.1 deploy-networks-common dee644f "wgvpn: add maintainer xerxes (10.100.9.7)" → pushed main
- [x] 4.2 tn-node-deployment df82deb "wgvpn: vendor maintainer key xerxes" → pushed main
      (bash -n, bash-3.2 lint, shellcheck errors, checksum-freshness re-run all clean locally)
- [ ] 4.3 (optional) devnet-genesis: bump `common` submodule pointer — SKIPPED (not requested)

### Phase 5 — bring xerxes up
- [x] 5.1 on xerxes: `git pull` + `dev-setup.sh --no-bringup --install-aliases` → Address 10.100.9.7, helpers in ~/.bashrc
- [x] U2 USER (sudo pw on xerxes): install conf to /etc/wireguard + `systemctl enable --now wg-quick@tn-wg0`
- [x] 5.2 verify from xerxes: tn-wg0 10.100.9.7/32, unit enabled+active, 10.100/16 via tn-wg0 and
      10.10.10/24 still via wg0; ping 10.100.0.1 3/3; tn_ssh validator-8-adiri / validator-1-adiri /
      validator-1-devnet all OK (7 keys each); hub sees xerxes handshake (33s), 22 peers

## Rollback
- Before 3.1: nothing changed remotely (`git checkout` the registry if needed).
- After 3.1: `./common/wgvpn/remove-peer.sh xerxes` (re-renders hub + re-fans keys without xerxes).
- On xerxes: `sudo systemctl disable --now wg-quick@tn-wg0`; `rm -rf ~/.config/tnvpn`.

## Review
Done 2026-10-09. xerxes is a full maintainer peer at 10.100.9.7, persistent across reboots.
- The stale-registry trap was real: the local registry was 13 commits behind and would have dropped
  6 peers; the live-hub-vs-registry diff before any push is the gate that catches it.
- Two snags, both environmental: NordVPN auto-connect hijacked the default route mid-run (both WG
  endpoints went into it), and stale devnet host keys from the 2026-09-17 rebuild blocked the key
  fan-out to 5 nodes until re-pinned after IAP fingerprint verification.
- Side effect to remember: tn-node-deployment's untracked tasks/todo.md lives on as
  tasks/todo.local-2026-07-24.md.
