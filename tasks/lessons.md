# Lessons

## gcloud: never put `gcloud alpha` in a non-interactive script (2026-06-10)

**Symptom:** `setup-obs-disk-alert.sh` hung silently at Step 3 after printing
">>> Step 3: create/replace alert policy". No error, just a hang.

**Root cause:** the `alpha` gcloud component was "Not Installed" on the operator's
machine. The first `gcloud alpha …` call stops to ask "install the alpha component?
(Y/n)" — an interactive prompt that reads as a hang in a script. (`beta` was
installed, so Step 1's `gcloud beta monitoring channels` worked — which made the
hang look mysterious.)

**Fix / rule:**
- Prefer the **GA** surface. Check with `gcloud <group> <cmd> --help`. Here GA
  `gcloud monitoring policies` exists; `gcloud monitoring channels` does NOT (still
  beta-only).
- Use `beta`/`alpha` only when there's no GA equivalent, and **document the required
  component** in the script + README (`gcloud components install beta`).
- When picking a surface, verify availability rather than copying from a plan:
  `gcloud components list --filter='id=alpha OR id=beta' --format='value(id,state.name)'`.
  Note state can be `Installed`, `Update Available`, or `Not Installed` — only
  `Not Installed` blocks; don't write a guard that treats `Update Available` as
  broken.

**Why it matters:** scripts that hang on a hidden prompt are worse than scripts that
fail loudly — they look like network/permission issues and waste debugging time.

## `sudo tee`/`cp` into /home/share fails EACCES even as root (fs.protected_regular) (2026-06-16)

**Symptom:** `regen-observer-node5.sh` step [4/6] died with
`tee: /home/share/genesis.yaml: Permission denied`, even though `sudo -n whoami`
returns `root` (NOPASSWD: ALL) and the file was mode `1777` (world-writable). New
files in the same dir wrote fine; only *overwriting pre-existing* files failed.

**Root cause:** `fs.protected_regular=1` (Debian 12 default). It forbids `O_CREAT`
opens of a regular file you don't own inside a **world-writable sticky directory**,
*unless the file is owned by the directory's owner* — and this applies to root too.
`/home/share` is `drwxrwxrwt root root` (sticky, from `chmod -R 1777` in startup.sh),
and the committee files were owned by `grant`/`tnadmin` (a prior pusher), not root.
So root's `tee`/`cp`/`scp` (all use `O_CREAT|O_TRUNC`) get EACCES. The *original*
deploy worked because each file was created by its owner (opener owns file → allowed),
not overwritten by a different user.

**Fix / rule:**
- When writing into a sticky, world-writable shared dir, **`sudo rm -f` the target
  first** (root bypasses the sticky-dir delete rule), then write a fresh root-owned
  file. Plain `sudo tee`/`sudo cp` over a not-owned existing file is NOT enough.
- Equivalent alternatives: `sudo chown` the file to the dir owner first, or write to
  a temp path and `sudo mv` over it (rename(2) isn't gated by protected_regular).
- Don't trust mode bits alone: `1777` looks writable but protected_regular gates it
  by *ownership*, and `sudo -l` showing `NOPASSWD: ALL` does not exempt root here.
- Diagnose ownership-vs-mode quickly: reproduce against a NEW filename (works) vs an
  EXISTING not-owned filename (fails) — the split is the tell for protected_regular.

**Why it matters:** the error reads like a privilege problem, but sudo/root is fine;
the gate is a kernel hardening sysctl keyed on file ownership, so chasing sudoers or
chmod wastes time. The same trap hits any repo script that re-pushes into /home/share
(genesis.sh, replace-genesis.sh) when ownership has drifted.

## devnet node ops + boot-disk resize (post-lockdown) — facts that save a round-trip (2026-06-18)

**Context:** the 4 validators all crashed on `No space left on device (os error 28)` (consensus-db/epochs
grew to ~89 GB on the 100 GB disks); chain halted ~2h. Recovered by expanding every boot disk 100→200 GB
online + `docker start telcoin`. Several operational surprises:

- **Reach the nodes via IAP, not VPN, when the tunnel is down.** Post the 2026-06-15 lockdown there is NO
  public :22; `wg-allow-iap-ssh` (35.235.240.0/20→tcp:22) is the always-on door. Use
  `gcloud compute ssh <n> --zone <z> --project=tn-devnet --tunnel-through-iap --ssh-flag="-o ConnectTimeout=20"`.
  Do **NOT** source `wgvpn/lib/wg-ssh-lib.sh` for the IAP path — its `TN_USE_VPN=1` shim *ignores*
  `--tunnel-through-iap` and forces the (down) overlay. `update-staggered.sh`/`wipe-*.sh` only work over a
  live VPN (they have no IAP flag); for IAP, replicate their staggering inline.
- **The Bash tool runs zsh; config.sh + `${!ARR[@]}` are bash.** Sourcing config.sh and looping arrays inline
  fails `bad substitution`. Put multi-node loops in a `#!/bin/bash` driver and run `bash tasks/<x>.sh`.
- **This Debian image (debian-12-bookworm-v20251111) ships NO partition editor** — no growpart/parted/sfdisk/
  sgdisk/fdisk; only `partx`, `resize2fs`, `e2fsck` are present (and they live in /usr/sbin, so a non-root
  `command -v` falsely reports MISSING — check with `sudo command -v`). Fix: `apt-get install -y
  cloud-guest-utils gdisk` (egress to deb.debian.org works; gdisk usually already installed), then
  `growpart /dev/sda 1` (relocates the GPT backup header, idempotent) → `resize2fs /dev/sda1`. Online, no reboot.
- **Root partition is `sda1` with `sda14`/`sda15` after it numerically but BEFORE it physically**, so sda1 is
  last on disk and growable. growpart reported `CHANGED ... new size` cleanly on all 5.
- **For a 0-byte-free wedged FS, `truncate -s 0` the telcoin json-log first** (frees blocks even at 100%, works
  on running or exited containers) so apt + resize2fs have scratch. The truncate guard MUST `sudo test -f`
  the /var/lib/docker path (root-only) — a non-root `[ -f ]` silently skips it.

**Measure before trusting a plan's root-cause hypothesis.** The approved plan blamed unbounded Docker logs
(missing OBS token) + dangling images. Phase 1 disproved both fleet-wide (token SET everywhere, LogConfig
bounded, images ~1 GB/0 reclaimable, kad 56K). Real cause was expected-but-unbounded chain data. Cleanup
would have reclaimed ~nothing; the disk expansion was the actual fix. Diagnose, then act.

**A validator that falls ≥3 epochs behind during a halt does NOT self-recover.** After restart val-4 was
pinned at epoch 233 while the network advanced to 236, rejecting every cert (`InvalidEpoch {theirs:236,
ours:233}`) and failing to retrieve newer epoch records; a clean restart didn't help. The disk fix restores
the node process, but epoch catchup is a separate consensus-layer problem (resync or a telcoin-network fix).

## Moving scripts out of the shared `common/` submodule — verify via config.sh env-var indirection, not grep alone (2026-06-19)

**Context:** moved 6 "adiri-only" node-start scripts (`start-validator-node.sh`,
`start-observer-node.sh`, `update.sh`, `update-staggered.sh`, `startup.sh`,
`config-apache.sh`) out of `common/` to the adiri repo root.

**What made it safe (and how to prove it):**
- A raw `grep -rn '<script>.sh' common/` returns dozens of hits, but ~all are **comments,
  README prose, or `echo` operator-guidance strings** — not invocations. Filter them: drop
  `:NNN:#`/`:NNN: #` comment lines, then eyeball each remaining `.sh` hit's context (most
  "real-looking" ones are `echo "  ./common/update-staggered.sh"` print statements).
- The ONLY thing that matters is whether a shared orchestrator **executes** the script. Here
  the consumers (`create-instances.sh`, `genesis.sh`, `update*.sh`) all reference them via
  **config.sh env vars** (`$STARTUP_SCRIPT_PATH`, `$START_VALIDATOR_NODE_SCRIPT`, …), never a
  hardcoded `common/<x>` path. That indirection is what lets the script relocate by editing
  only `config.sh`. Confirm by grepping `common/` for the VAR NAMES, not the file names.
- **Prove the move end-to-end by sourcing the edited config.sh and `[ -f "${!VAR}" ]` on every
  path var** — catches both a missed repoint (var still says `common/…`, now MISSING) and an
  over-eager edit (repointed a var whose script legitimately stayed in common, e.g.
  `CONFIG_CADDY_SCRIPT`/`UPLOAD_COMMITTEE_SCRIPT`).

**Sibling-checkout trap:** `adiri-genesis/common/` and `devnet-genesis/common/` are the SAME
submodule but **independent working trees** (different inodes; each has its own
`.git/modules/common`). `rm`-ing the 6 from the devnet checkout leaves the adiri checkout
untouched — verify both sides explicitly (`stat -f '%d:%i'` to confirm distinct inodes) so you
don't assume a delete propagated, or panic that it didn't.

**Copy fidelity:** use `cp -p` (preserve mode) then assert with BOTH `cmp -s` (byte-identical)
and `shasum -a 256` side-by-side AND `[ -x ]` (exec bit survived). `bash -n` each script at the
NEW location too — a relocated script should parse unchanged; if it doesn't, the copy is wrong.

## A correct-but-incomplete root cause: when the fix CHANGES the symptom, keep going (2026-06-18)

**Context:** obs.devnet.telcoin.network timed out. The plan's diagnosis (guest network-stack wedge: DHCP
lease lost + `169.254.169.254` metadata i/o timeout + Docker-bridge martian-source corruption) was CORRECT,
and `stop`/`start` fixed it. But the site then returned **502, not 200** — a *second, independent* root
cause the reboot couldn't touch: **`/mnt/obs-data` was 100% full** (`loki/chunks`=97G), so loki ("no space
left on device") and grafana ("database or disk is full") crash-looped.

**Rules:**
- **A timeout → connection-refused/502 transition is progress, not done.** Timeout = packets dropped
  (network dead); refused/502 = the host's TCP stack and reverse-proxy are alive but the app is down.
  When a fix flips the symptom, re-run end-to-end verification — the first green signal (curl no longer
  hangs) is not success.
- **On any "service down" box, check `df -h` early.** A full disk causes cascading, misleading failures
  (here it likely contributed to the net wedge too). It's the same failure mode as the validators — make
  it a standing triage step.
- **Loki disk-full is a deadlock, and retention alone won't save you.** `retention_period`(14d) was set with
  `compactor.retention_enabled`, but the disk filled in ~8d (< retention window) so nothing was eligible to
  delete, AND the compactor can't run on a full disk. Escape = grow the disk or drop in-window data. Size
  retention to the disk: `retention_period × ingest_rate` must stay under disk size (here ~12 GB/day × 14d
  ≈ 168 GB needs ≥200 GB). The data disk is `obs-devnet-data`, mounted **whole-disk ext4 at `/dev/sdb`
  (no partition table)** → online grow is just `gcloud compute disks resize` + `resize2fs /dev/sdb` (no
  growpart, unlike the validators' partitioned `sda1`).
- **After restarting single-binary Loki, ~30s of `empty ring` 500s on `/loki/api/v1/push` is NORMAL** — the
  ingester auto-joins the ring after a timeout (`msg="auto-joining cluster after timeout"`), then `/ready`
  flips to `ready` and pushes 204. Don't mistake the join window for a crash-loop. **`docker inspect loki
  --format '{{.RestartCount}} {{.State.OOMKilled}}'` is authoritative** over the `docker ps` "Up X minutes"
  string (which read stale here and falsely suggested an OOM restart). Loki also does NOT log successful
  (204) pushes at info level — prove ingest with a `count_over_time({job="..."}[2m])` query, not by grepping
  logs for "204".
- **Verifying "logs from all nodes" doubles as node-health monitoring.** The per-node fresh-ingest query
  surfaced that validator-3-devnet went silent (node-side), even though obs was fully healthy — a finding
  worth more than the pass/fail it was checking.

## tn-node-deployment migration: plan-vs-reality + secret/exec gotchas (2026-06-19)

Authoring the devnet→tn-node-deployment migration across 3 repos surfaced four traps worth remembering:

- **A plan that says "add config var X (default 1)" can collide with an existing X of the OPPOSITE meaning.**
  The plan said add `WG_NODE_ENFORCE` (default 1) gating *installation* of the wgvpn policy-drop nft table.
  But `WG_NODE_ENFORCE` ALREADY exists in `common/wgvpn/node/wg-node-bootstrap.sh` (default **0**, gating
  *activation* of an already-installed table), and `wgvpn/lockdown-firewall-gcp.sh` activates that dormant
  table directly over SSH — so reusing the name as written would leave adiri nodes with no table and
  **break adiri's lockdown**. Fix: a NEW switch `WG_NODE_FIREWALL` (default 1, byte-identical to today)
  gating the whole §5 block; devnet sets it 0. Always `grep` the target repo for a plan's "new" var name
  before defining it; if it exists, read every caller before reusing it.
- **`sudo VAR=val cmd` is NOT a reliable way to pass an env var to a root child; use `sudo env VAR=val cmd`.**
  Default sudoers `env_reset` may strip command-line env assignments (needs the `setenv` tag). `sudo env
  VAR=val cmd` is bulletproof because `env` sets it explicitly. Critical when a secret has NO CLI-flag
  fallback — `setup-validator.sh` reads `TN_BLS_PASSPHRASE` from env only, so a dropped var silently
  generates the BLS key under the wrong passphrase. (When a flag exists too, pass both env + flag.)
- **Sourcing a non-`set -e` library from a `set -euo pipefail` script changes its behavior.** `common/genesis.sh`
  has no `set -e`/`-u`/`pipefail` and captures `exit_code=$?` after `docker run`. Calling it from a strict
  script aborts on the first non-zero before its own error handling, diverging from adiri's proven path.
  Wrap the source+call in `set +e +u +o pipefail` … `set -euo pipefail` to match the library's native env.
- **OS-port a startup script before changing its image family.** Validators moved to Ubuntu 24.04, but the obs
  VM's `startup-obs.sh` hardcodes `download.docker.com/linux/debian` + `$VERSION_CODENAME` → on Ubuntu it
  expands to a nonexistent `/linux/debian noble` repo and docker-ce install fails. Kept `OBS_IMAGE` on Debian;
  only the validator `IMAGE` is Ubuntu. Two image families in one config is fine when their startups differ.
- **tn-node-deployment keygen `node-info.yaml` and `common/genesis.sh`'s committee input are the SAME
  `NodeInfo` struct** (both from the `telcoin` binary) — the migration's make-or-break integration point is a
  no-op rename: `cp <node>/node-info.yaml genesis/validators/nodeN.yaml`. No field transform.
