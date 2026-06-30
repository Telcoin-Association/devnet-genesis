# Lessons

## Operator-self-sufficiency: RPC edge + node-info advertise, three reusable patterns (2026-06-30)

Shipped the public-RPC feature into `install-caddy.sh` (operator repo) + UI parity. Three patterns worth reusing:

- **Single managed config, multiple toggleable blocks → fence + preserve-the-other verbatim.**
  `/etc/caddy/Caddyfile` now hosts a dashboard vhost AND an RPC vhost, each between `# >>> tn-<name> >>>`/`# <<< tn-<name> <<<` markers, first line still `CADDY_MARKER`. Toggling one block extracts the OTHER block's bytes with `awk '$0==b{f=1;next} $0==e{f=0;next} f'` and re-composes — so the dashboard's bcrypt `$2a$…` hash is NEVER re-parsed (the L411 trap, structurally avoided). Proven byte-stable: extract→recompose→extract is a fixed point, and `caddy validate`+`caddy fmt` are clean on the dual-vhost output. Generalizes to any single-file config with independently-managed sections (validate the COMPOSED file on a temp path before `mv`, so a bad compose never clobbers the live file).

- **Editing one sibling in a structured config: indent-scope it, and test against the REAL serialized form.** The node-info.yaml writer must touch ONLY the *worker* `P2pNode` (the 2nd), never *primary*. A python3 stdlib line editor locates `p2p_info:`(ind 0)→`worker:`(ind 2)→its `rpc:`(ind 4) by indentation, replacing the rpc line + its indent≥6 continuation. Critical: the real keygen emits `rpc: ~` (YAML null tilde), NOT the `rpc: null` the plan assumed — so the null detector must accept `~`/`null`/empty (L538 again). A 43-assertion harness drove it across `~`/null/absent/multiline + worker-at-EOF + **primary-already-has-a-block** (the case that catches "edited the wrong sibling"). Idempotent set AND clear (byte-identical re-run) is the invariant that makes it safe to call from both CLI and a UI button.

- **A config the node validates at boot needs a brick guard, not just a writer.** An invalid `worker.rpc` crash-loops reth (`Restart=on-failure`,`StartLimitBurst=5`). Guard = validate-the-URL-before-writing (regex: scheme + bare host + ≤2048) → back up to `.tn-bak` → write → `systemctl restart` → bounded poll that **fast-fails on `systemctl is-failed`** (catches the crash-loop in ~12s) and rolls back the `.tn-bak`, vs. a slow DB-replay (neither up nor failed) which is non-fatal "advertises once started". Edit the host file for BOTH binary and docker installs (the datadir is bind-mounted). The Caddy vhost is left up on rollback (harmlessly 502s) — decouple the edge from the advertise.

**Orchestration:** lock the producer's interface before launching the consumer. I wrote `install-caddy.sh` myself (the novel/risky piece) to FREEZE its JSON contract (`--json --phase=rpc-{status,check-dns,enable,disable}` + `--rpc-domain`), THEN handed that exact contract to the UI subagent so its helper wrappers + routes mirrored it with zero integration drift. Parallel subagents (migrate+docs, add-ons) ran on disjoint file sets meanwhile; the UI agent (shared `ui/*`) ran solo. Memory: [[bump-version-on-gated-file-edit]], [[two-deploy-paths-ui-and-scripts]].

## Bash ERR-trap rollback needs `set -E` (errtrace), not just `set -e` (2026-06-25)

**Symptom (self-caught in review):** `migrate-node-naming.sh` runs every mutation
step inside a function (`relocate_dir`, `rewrite_unit`, `start_and_verify`, ...)
under `set -euo pipefail` with `trap on_error ERR` to roll back on failure. But a
command failing INSIDE a function would exit the script **without** firing the ERR
trap — so a half-migrated node would NOT be rolled back.

**Root cause:** `set -e` (errexit) DOES abort inside functions, but the ERR *trap*
is "not inherited by shell functions, command substitutions, or subshells unless
`-E` (errtrace) is set." `set -euo pipefail` does not include `-E`. So the in-
function failure aborted via errexit and skipped the trap entirely. Proven:
`set -euo pipefail` → trap never fires for an in-function `false`; `set -Eeuo
pipefail` → it fires.

**Fix / rule:** Any node script that relies on a `trap … ERR` handler (rollback,
cleanup) MUST `set -E`. Add it after sourcing `lib/common.sh` (whose own
`set -euo pipefail` does not clear `-E`). Verify by forcing a failure inside a
step and asserting the handler ran. Related: make the script source-safe
(`if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then main "$@"; fi`) so the step
functions can be unit-tested without executing the migration.
Memory: [[bash-scripts-mac-linux-portable]], [[devnet-on-node-scripts-are-git-clone]].

## Editing a version-gated tn-node-deployment file → bump its version constant (2026-06-25)

**Symptom:** Changed `ui/server.py` (the R1/R2 hardening) but left `UI_VERSION`
untouched. `update-scripts.sh` gates each file on a version constant, so an
unchanged version means the updater reports "Up to date" and the edit never
reaches the nodes.

**Root cause:** `update-scripts.sh` compares local-vs-remote of a per-file
version var (the `SCRIPTS` array: `local_path:remote_path:version_var`). It does
NOT diff content. No version bump → no detection → no redeploy.

**Fix / rule:**
- After editing any file listed in `update-scripts.sh`'s `SCRIPTS` array, bump
  that file's version constant. Key mappings: `ui/server.py` → `UI_VERSION`;
  most `*.sh` → their own `readonly SCRIPT_VERSION`; `lib/common.sh` →
  `COMMON_VERSION`; `lib/observability.sh` → `OBSERVABILITY_VERSION`;
  `lib/testnet-addons.env` → `TESTNET_ADDONS_VERSION`.
- Bumping `UI_VERSION` is the single gate for the WHOLE UI bundle — it triggers
  fetching `server.py` + `UI_BUNDLE` companions + `install-ui.sh --update`. UI
  companion files (static, helper, .service, requirements) have NO version of
  their own; they ride along on the `UI_VERSION` bump.
- If you edit `update-scripts.sh` itself (e.g. add a file to `SCRIPTS`/
  `UI_BUNDLE`), bump ITS `SCRIPT_VERSION` too, or `self_bootstrap` won't pull the
  new list onto nodes.
- Files NOT in `SCRIPTS`/any bundle (e.g. `README.md`, dev-only tests) are not
  shipped by `update-scripts.sh` and need no bump — keep prod-only runtime files
  in the bundle, dev/CI artifacts out.

**Why it matters:** a silent no-propagation looks like "I shipped the fix" when
the nodes still run the old code — exactly the failure mode the updater exists to
prevent.


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

## Devnet observability rollout (step 9): a "running" report that lied + a cap-drop trap (2026-06-19)

Bringing the per-node Alloy sidecar online surfaced four traps:

- **`setup-observability.sh` prints "Telemetry shipper running (telcoin-alloy.service)" without actually
  checking the service is healthy.** The canary reported success while Alloy was crash-looping (systemd had
  given up after 5 restarts). NEVER trust a setup script's own "running" line — verify `systemctl is-active
  <unit>` == active, `docker ps` shows the container Up, and it's *shipping* (`loki_write_sent_bytes_total`
  on 127.0.0.1:12345/metrics > 0, queryable in Loki). Same shape as the obs-recovery lesson: the first green
  signal is not success.
- **`--cap-drop=ALL` + a bind mount UNDER an image-owned dir = unwritable even as container-root.** The
  grafana/alloy docker unit mounted the data dir at `/var/lib/alloy/data`; the image owns `/var/lib/alloy`
  as user 473:473 mode 0770. `--cap-drop=ALL` strips CAP_DAC_OVERRIDE, so container-root (uid 0, "other"
  on that dir) can't traverse it → `Error: failed to create the remotecfg service: mkdir /var/lib/alloy/data:
  permission denied`. Fix = mount + `--storage.path` at a path whose parents are root-traversable
  (`/var/lib/telcoin-alloy`, parent `/var/lib` is root:root) — keeps every hardening flag. Diagnose by
  reproducing the EXACT `docker run` flags WITH and WITHOUT `--cap-drop=ALL` (`--entrypoint /bin/sh -c
  'touch …'`): `id` alone shows root and misleads; the cap-drop toggle is the tell. The native (non-docker)
  install path was unaffected (it writes the host dir directly).
- **Same credential, two routes, different verdict → the gap is SERVER-side.** `/loki/api/v1/push` accepts
  the OBS_INGEST_TOKEN (204) but `/api/v1/write` (Prometheus remote-write) 401s it ("Invalid API key").
  config.alloy sends `bearer_token = sys.env("OBS_INGEST_TOKEN")` for BOTH and is byte-identical to adiri's
  working agent → the node is correct; obs-devnet's metrics route auth is misconfigured. Don't chase a
  node-side fix when one of two sibling routes works with the same token.
- **A label that should vary was hardcoded.** `obs_label_sourcing` pinned `TN_CHAIN="adiri"` even though
  config.alloy reads it via `sys.env("TN_CHAIN")`; devnet telemetry landed under `chain="adiri"`. Map
  identity labels from the active NETWORK, keeping the existing value for the established network
  (testnet→adiri) so its telemetry stays byte-identical. Grep a "fixed to X" comment as a smell.
- **reth can emit a single ~1.1MB log line** (> Loki's 256KB `max_entry_size`) → Loki 400s just that entry;
  normal lines still ship. Surfaces as scary-looking errors in the Alloy journal that are NOT a config break.

## BLS Docker LoadCredential: a one-line goal with three cascading gotchas (2026-06-19)

Goal: stop baking `-e "TN_BLS_PASSPHRASE=<cleartext>"` into the docker systemd unit (visible in
`systemctl cat` — a live validator's unit literally showed the passphrase). Mirror the source path's
LoadCredential wrapper for docker. Applying it to LIVE validators surfaced three traps the plan missed:

- **`--phase=finalize` does NOT restart an already-running service — it runs `systemctl start` (a no-op
  when active).** So finalize rewrites the unit file + `daemon-reload`, but the RUNNING process keeps the
  OLD unit until something actually restarts it. Verify the new unit by reading the FILE
  (`systemctl cat`), not `systemctl show` (loaded/in-memory), and plan an explicit restart to activate it.
- **Re-finalize silently DROPS obs reth flags.** `ENABLE_OBSERVABILITY/METRICS/HEALTHCHECK_MONITOR` are
  hardcoded false and only set by interactive-testnet `prompt_testnet_addons` — json `--phase=finalize`
  can't enable them, so `tn_node_launch_flags` returns empty and the regenerated unit loses
  `--log.file.format json`/`--metrics`/`--healthcheck`. Re-run `setup-observability.sh` AFTER finalize to
  re-inject them (its `obs_ensure_reth_flags` appends to the `--http` line). Net effect: finalize's no-op
  `start` + obs's real `restart` = ONE restart that activates LoadCredential AND the obs flags together.
- **Moving `docker run` into a wrapper breaks in-place obs flag injection.** `tn_node_launch_target`
  returned the UNIT for docker (that's where `docker run`/`--http` used to live); the wrapper relocates it,
  so injection finds no `--http` target. Companion fix: return the wrapper for docker when it exists. Any
  change that relocates the launch line must update everything that patches that line.
- **Process for a security-critical live change:** render the generated unit+wrapper from the edited
  heredocs with realistic values and assert on them (LoadCredential present, no embedded value, wrapper
  reads `$CREDENTIALS_DIRECTORY`, `-e NAME` name-only) BEFORE touching a node. Heredoc `\<newline>` is
  removed in unquoted heredocs (per bash manual) → backslash-continued `docker run` collapses to a valid
  one-liner. **A healthy node that rejoins consensus after the restart is the end-to-end proof LoadCredential
  delivered the right passphrase** — a wrong/missing one fails BLS-key decrypt and the node crashes.
- **Provide a secret to a driver without logging it:** read it from the node's own mode-600 file into a
  shell var in the SAME invocation that uses it (`PASS="$(... sudo cat .../bls-passphrase)"; export …`),
  never echo it; the driver passes it via `sudo env VAR=…` and logs only the redacted twin.

## reth `--instance` port math: HTTP down by 1, WS up by 2 — and both bind loopback by default (2026-06-20)

**Context:** enabling reth `--ws` on devnet + teaching Caddy each node's WS backend port. The plan
hypothesized the observer (`--instance 5`) WS port was `8546 + (instance-1)` = 8550. **Wrong.**

**Actual derivation** (reth `RpcServerArgs::adjust_instance_ports`, `crates/node/core/src/args/rpc_server.rs`):
- `http_port -= instance - 1`   → instance 1 = 8545, instance 5 (observer) = **8541**
- `ws_port   += instance*2 - 2` → instance 1 = 8546, instance 5 (observer) = **8554** (NOT 8550)
- `auth_port += instance*100 - 100`

WS moves UP at 2× step while HTTP moves DOWN at 1× — they are NOT mirror images. Compute
`WS_PORT=$(( 8546 + (instance*2 - 2) ))`, persist to `.node-meta` for config-caddy to read, and still
confirm the live bind with `ss -tlnp` (a fork could change the formula).

**Also:** telcoin's `crates/tn-reth/src/rpc_server_args.rs` defaults BOTH `http_addr` and `ws_addr` to
`Ipv4Addr::LOCALHOST`. So devnet RPC was **already loopback-only** (never publicly exposed) — the public
`tcp:8545` in the VPC `devnet-allow-web` rule was dead weight, safe to drop. Explicit `--http.addr/--ws.addr
127.0.0.1` is defensive (pins intent, survives a default change), not a behavior change for HTTP.

**Why it matters:** the 8550 guess would have pointed Caddy's wss:// proxy at a dead port on the observer
and the WSS-101 handshake would fail with no obvious cause. Reading the actual `adjust_instance_ports`
source — not reth docs, not the plan — is the only reliable way ("measure before trusting", fork edition).

## Loki's per-line cap is `max_line_size`; bind-mounted config needs an explicit reload after `compose up -d` (2026-06-20)

**Two obs server-side traps, both checked against the deployed versions (Loki 3.3.2; obs-vm/docker-compose.yml):**

- **The Loki key is `max_line_size`** (default `262144` = 256 KB) under `limits_config` — the plan said
  `max_entry_size`, which is NOT a Loki key. A wrong key either silently no-ops (reth's ~1.1 MB lines keep
  400-dropping) or trips Loki's strict config parse and crash-loops the container. Set `max_line_size:
  2097152` (2 MiB); leave `max_line_size_truncate` off so long lines stay whole. Verify the key against the
  Loki config reference for the deployed version, not memory.
- **The metrics 401 was NOT a missing Caddy route.** The committed Caddyfile already had the token-gated
  `/api/v1/write` block. The LIVE Caddy ran a STALE config: `docker compose up -d` does NOT recreate a
  container when only a *bind-mounted file's contents* changed (it diffs the service spec, not mount
  contents), so a redeploy kept the old Caddyfile → metrics fell through to the Grafana catch-all →
  Grafana's "Invalid API key". Fix: after `up -d`, explicitly reload each config-bearing service —
  `caddy reload` (graceful), `compose kill -s SIGHUP prometheus`, `restart loki` (no live reload). Applies
  to ANY bind-mounted config: editing the file + redeploying is a no-op until the process re-reads it.

**Why it matters:** both present as "committed config is correct but the live system disagrees" — the gap is
the redeploy mechanics, not the config. Chasing the (correct) committed config never finds it.

## Render-verifying setup-script heredocs by sourcing the real function: three traps (2026-06-20)

**Goal:** prove the generated wrapper/unit/.node-meta from the EDITED `step_create_service` heredocs
(validator+observer × docker+native) without hand-copying them (drift-proof). Source the real `setup-*.sh`
(with `main "$@"` stripped) and call `step_create_service`. Three traps cost iterations:

- **Top-level default assignments clobber pre-source env.** `INSTALL_METHOD=""`, `INSTALL_DIR=/opt/telcoin`
  run at source time, overwriting vars exported BEFORE sourcing. Set the test globals AFTER `source`.
- **`readonly` consts abort reassignment under `set -e`.** `lib/common.sh` marks `DEFAULT_INSTALL_DIR` (etc.)
  readonly; reassigning it errors and, under the script's `set -euo pipefail`, kills the subshell before the
  render runs. Don't touch readonlys (use the writable twin `INSTALL_DIR`), and `set +e +u +o pipefail`
  after sourcing so `:-`-guarded unset vars don't abort.
- **A stripped temp copy misresolves `lib/common.sh`.** `setup-*.sh` sources `${SCRIPT_DIR}/lib/common.sh`
  with `SCRIPT_DIR=$(dirname BASH_SOURCE)`; a copy under the scratchpad makes that path absent, so the real
  `apply_kuma_rule`/`allow_overlay_ssh` are undefined and silently skipped — which made a firewall call-order
  test LOOK like a lockout bug. `sed` the `source` line to the real absolute path in the temp copy.

**Bonus:** `grep -c '--http ${launch_flags}'` returns 0 — `$`/`{` are regex metacharacters (BSD grep treats
a mid-pattern `$` as an anchor). Use `grep -F` for literal flag/port strings. (Bit me twice this session.)

**Why it matters:** a faithful render is the gate before touching a live validator (a malformed wrapper
crash-loops the node). These traps make the harness silently render the WRONG thing — or look like a code
bug — while the code is fine. Recognizing them keeps the gate trustworthy.

## Phase 4 live rollout (RPC edge): six surprises the plan didn't predict (2026-06-20)

Driving the devnet Phase 4 rollout over the overlay surfaced these — each cost a detour:

- **"Client IAP is broken" was an EXPIRED gcloud token.** The finalize driver's `tn_node_int_ip`
  (`gcloud compute instances describe`) failed with "Reauthentication failed. cannot prompt during
  non-interactive execution." The overlay (SSH/SCP) worked fine; only the gcloud REST surface was dead.
  After the operator ran `gcloud auth login`, IAP-to-obs ALSO worked (the prior "IAP broken" belief was
  partly stale auth). **Check `gcloud auth print-access-token` before blaming the transport** — an expired
  token reads as a hang/transport failure across every gcloud REST/IAP call.
- **A validator `--phase=finalize` exits rc=1 *benignly*.** It writes the unit/wrapper/.node-meta and the
  service runs + RPC responds, then exits 1 only because the post-start on-chain check sees an empty
  `VALIDATOR_ADDRESS` (finalize passes no `--validator-address`). Observers return ok:true (no address).
  Drivers under `set -e` abort on this. **Verify the actual finalize RESULT (wrapper has `--ws`, .node-meta
  ports written, service active) instead of trusting the rc.**
- **reth's WS port is empirically 8554 on the observer** (`--instance 5`) — `ss -tlnp` confirmed
  `127.0.0.1:8554`, matching `8546 + instance*2-2` from source, NOT the plan's 8550. The formula-from-source
  beat the formula-from-the-plan.
- **config-caddy derived the cert domain from bash `$HOSTNAME`** — the GCP kernel hostname, inconsistent
  across a fleet (some boxes resolve it to the full `…c.<proj>.internal` FQDN). Certs were requested for
  garbage domains. Fix: dns.sh passes the fleet `NODE_NAME`; config-caddy prefers it, else the SHORT
  hostname. Then `node{N}.<suffix>` certs issued immediately (the `node{N}` DNS already resolved).
- **config-caddy never opened the host firewall, so the RPC edge was dead behind ufw.** After
  `firewall-setup.sh --enable`, external :80/:443 were dropped (verified: external POST to a node :80 timed
  out) and the LB health probe on :43174 was blocked. The plan *claimed* config-caddy "already runs ufw
  allow 80/443" — it didn't. A locked-down host firewall and a public edge must be reconciled explicitly:
  config-caddy now opens 80/443 + :43174-from-LB-ranges when ufw is active.
- **`--healthcheck 43174` binds NOTHING** — `ss -tlnp` shows no :43174 listener at all (so the kuma uptime
  monitor's :43174 probes have been hitting a closed port too). The GCP LB health check must target a port
  the node actually serves: switched it to the real backend port **:80** (Caddy) → backends went HEALTHY.
  Flag for the team: reth's `--healthcheck` flag (or the deployment's assumption about it) is broken.
- **The LB managed cert + `rpc.<suffix>` are the one operator-only step.** `devnet.telcoin.network` is not
  in a Cloud-DNS zone this account can reach (API off on tn-devnet; only adiri's zone elsewhere), yet
  `node{N}.devnet…` already resolved (pre-created records). The aggregate `rpc.devnet.telcoin.network` →
  LB-IP A-record must be created by whoever owns that DNS; the Google-managed LB cert only provisions after
  it resolves. Everything else (per-node HTTPS+WSS) is fully self-service over the overlay.

## Render-gating a Caddyfile feature: prove byte-identical-when-off, and inject `$`-secrets via ENV not a sourced assignment (2026-06-25)

Adding the OPTIONAL admin-dashboard vhost to `config-caddy.sh` (gated `TN_ADMIN_DASHBOARD=1`,
`basic_auth` with a bcrypt hash). The live RPC path is sacred, so the gate was: render the Caddyfile from
the REAL old (`git show HEAD:…`) and new scripts with the flag OFF, `diff` must be empty.

- **A gated append can be made byte-identical-when-off WITHOUT needing `caddy fmt`.** Splicing `${ADMIN_BLOCK}`
  (empty when off) onto its own line in the heredoc, replacing the existing blank line, renders the exact same
  bytes as before — `}\n` + `\n` (empty expansion) + `# next` = the original `}\n\n# next`. So the RPC-safety
  `diff` is empty even pre-`fmt`, provable on a box with no `caddy` installed. Design the off-path to collapse
  to the original whitespace and the gate needs no external tool.
- **`common/` is a SUBMODULE — `git show HEAD:common/config-caddy.sh` from the parent fails** ("exists on disk,
  but not in HEAD"). Read the baseline from the submodule's own git: `git -C common show HEAD:config-caddy.sh`.
- **When render-testing a value that contains `$` (bcrypt `$2a$14$…`, a password), inject it via the
  ENVIRONMENT, never as a line in a sourced harness.** A sourced `TN_ADMIN_AUTH_HASH=$2a$14$abc` line is
  re-parsed by bash: `$2`/`$1`/`$abc` expand to empty → the hash silently became `a4`. That is a HARNESS bug,
  not a code bug — the production path passes the hash as a `sudo env` value, and a *variable's value is never
  re-expanded* (which is exactly why the feature is safe). Mirror that in the test: `export VAR='$2a$14$…';
  bash harness` (or run under the var), and assert with `grep -F` against a saved file (nested `case`/`"..."`
  patterns re-mangle the `$`). Bit me on two separate assertions this session before I switched to env+grep -F.
- **A plan's `: "${SECRET:=$(fetch)}"` one-liner hides a fail-open.** Under `set -e`, a failed command-sub
  inside `${:=}` does NOT abort — a failed/empty Secret-Manager fetch silently yields an empty hash, and the
  builder's "basic_auth only if hash non-empty" guard then drops auth entirely → a PUBLIC unauthenticated
  dashboard. Resolve secrets explicitly and fail loud on fetch-error AND on empty, when the whole point of the
  step is to gate access. The verification expecting `401` is the tell that empty-hash is never the intended path.
## CORRECTION: `--healthcheck 43174` is NOT broken — it was never being EMITTED on devnet (2026-06-20)

Supersedes the earlier entry above ("`--healthcheck 43174` binds NOTHING … the flag is broken").
That was a **misdiagnosis**. Source-level ground truth (telcoin-network):

- `--healthcheck <PORT>` is a real telcoin-network **node CLI** arg (`Option<u16>`,
  `crates/telcoin-network-cli/src/node.rs`, `env=HEALTHCHECK_TCP_PORT`, `global=true`). It IS NOT a
  reth flag. The listener spawn is gated only by `if let Some(port) = self.builder.healthcheck`
  (`crates/node/src/manager/node.rs`). So passing `--healthcheck 43174` DOES bind a :43174 listener.

Why `ss -ltnp` showed no :43174 listener on devnet: the flag was **never on the command line**. The
deploy path bakes it via `tn_node_launch_flags()` (`tn-node-deployment/lib/common.sh`), which had TWO
independent suppressors on devnet:
  1. `is_testnet || return ""` — strict (testnet-only) gate returned empty BEFORE checking the
     healthcheck opt-in. (Sibling `is_testnet_like` = testnet OR devnet already existed for this.)
  2. `ENABLE_HEALTHCHECK_MONITOR` defaults false and `--json`/finalize skips `prompt_testnet_addons`,
     so nothing turned it on.
→ node launched with NO `--healthcheck` → closed port → Kuma AND the LB health check both failed.

**Fix shipped this session:** gate → `is_testnet_like`; add `--enable-healthcheck-monitor` to
setup-{validator,observer}.sh parsers; pass it from devnet-finalize.sh. Render-test PROVES devnet+opt-in
→ `--healthcheck 43174`, devnet+default → empty, testnet unaffected, mainnet still gated off.

**Lesson:** "flag present in the command we *intended* + no listener" ≠ "flag is broken." FIRST prove the
flag is actually on the live `telcoin node …` argv (`ps`/the rendered wrapper/systemd unit) before blaming
the binary. A gate upstream of the flag can silently drop it. And before rollout, run the preflight
(`docker run --rm <DOCKER_IMAGE> node --help | grep -- --healthcheck`) — the only real residual risk now is
an image too old to know the flag (it would crash-loop), which the staggered abort-on-first-failure catches.

**Also corrected:** the earlier workaround repointed the GCP LB health check to :80 (Caddy). With :43174
now actually served, the LB's *original* 43174 TCP check (`common/setup-load-balancer.sh`) is correct again
— but a host-ufw rule was missing: `apply_kuma_rule` admits only the Kuma VM, not the Google HC ranges, so
LB backends stay unhealthy at the ufw layer even with the listener up. Added `apply_lb_hc_rule`
(`TN_LB_HC_RANGES`, driven by devnet-firewall.sh from `GOOGLE_HC_RANGES`) to the lockout-safe enable.

## `--no-wipe` re-finalize must RESTART; gate on health, not finalize rc; portability audit (2026-06-20)

Driving `devnet-update.sh --no-wipe` (chain-preserving healthcheck rollout) surfaced three things:

- **`--no-wipe` finalize writes the wrapper but does NOT apply it.** `setup-*.sh --phase=finalize`
  writes `/opt/telcoin/start-<svc>.sh` + the unit, then `systemctl start` — which is a **no-op when
  the service is already running**. So after a no-wipe finalize the node KEPT running the OLD
  container (old image, no `--healthcheck`) even though the wrapper now had the new image + flag.
  Verified live: service `active`, wrapper had `--healthcheck 43174`, but `ss` showed NO :43174 and
  `docker ps` showed the OLD image. Fix: under `--no-wipe`, `redeploy_one` now `docker pull`s then
  `systemctl restart`s to swap in the new wrapper. (The wipe path gets a fresh start for free.)
- **The benign validator finalize rc=1 aborts the rollout.** As in the Phase-4 lesson, a validator
  `--phase=finalize` exits rc=1 (post-start on-chain address check, no `--validator-address`) even
  though the service runs + RPC responds. `devnet-update.sh`/`reset-network.sh` aborted on it before
  `wait_healthy` ran. Fix: do NOT abort on the finalize rc — `wait_healthy` (active + :43174) is the
  real gate. `devnet-finalize.sh`'s own summary still prints "failed (1): nodeN" for the benign case;
  that's cosmetic — trust the health gate.
- **Bash portability (macOS bash 3.2):** `mapfile` (bash-4) under `#!/bin/bash` killed
  `devnet-finalize.sh` on the Mac (macOS `/bin/bash`=3.2.57). Fixed the 3 operator `mapfile` sites
  (env-bash shebang + portable `while read` loop), normalized operator-driver shebangs to
  `#!/usr/bin/env bash`, and added `tasks/check-bash-portability.sh` (lint: ERROR on bash-4 under
  `#!/bin/bash`). tn-node-deployment GNU/bash-4 usages are node-side (Linux) — latent, see
  `tasks/bash-portability-audit.md`. Memory: [[bash-scripts-mac-linux-portable]],
  [[devnet-on-node-scripts-are-git-clone]], [[devnet-ssh-helpers-need-bash-not-zsh]].
- **Re-preflight when `DOCKER_IMAGE` changes mid-task.** It changed `v0.11.0-devnet` →
  `v0.11.1-devnet-pop` between preflight and rollout; both happen to support `--healthcheck`
  (re-verified), but always re-check `docker run <img> telcoin node --help | grep healthcheck`.

## Version-bump blind spot when delegating gated-file edits (2026-06-26)

**Symptom (self-caught in final verification):** Collapsed observer/validator across
tn-node-deployment using 4 subagents + my own Phase 1 edits. I explicitly instructed each
subagent to bump its files' version constants — and then forgot to bump the THREE files I
edited *directly myself* (`firewall-setup.sh`, `lib/common.sh`, `lib/fallback.sh`). Caught
only by a version-audit pass at the end (grep each gated file's version, compare to HEAD).
Without the bump, `update-scripts.sh` would not have propagated the resolver/firewall/hardware
changes to nodes — a silent no-op deploy (see [[bump-version-on-gated-file-edit]]).

**Why:** Asymmetric attention. The act of writing "bump your version" into delegation prompts
made me police the *subagents'* bumps while going blind to my *own* directly-edited files.

**How to apply:** After ANY multi-file change, run one mechanical audit before committing:
for every changed file listed in `update-scripts.sh`'s `SCRIPTS` array (or UI bundle), assert
its version constant is strictly greater than `git show HEAD:<file>`'s. Don't trust per-file
memory across a long session — audit the whole set in one pass. Applies doubly when some edits
were delegated and some were direct.

## Two deploy paths: a UI-invoked script needs install-ui.sh too, not just SCRIPTS (2026-06-26)

**Symptom (self-caught):** Added a new top-level `setup-node.sh` and registered it in
`update-scripts.sh`'s `SCRIPTS` manifest. But the UI's setup dispatch execs setup scripts from
`/opt/telcoin-ui-update/`, which is populated by a FIXED file list in `ui/install-ui.sh`
(`for s in firewall-setup.sh remove-node.sh setup-observer.sh setup-validator.sh ...`), NOT by
the SCRIPTS manifest. The deprecated shims (`setup-observer.sh`/`setup-validator.sh`) exec the
sibling `setup-node.sh`; without adding it to that loop, the shim would exec a missing file in
the UI path. Fixed by adding `setup-node.sh` to the install-ui.sh copy loop.

**Why:** There are TWO independent deploy paths in this repo:
- `update-scripts.sh` → `~/telcoin-node-scripts/` (the CLI scripts dir), gated by `SCRIPTS`.
- `ui/install-ui.sh` → `/opt/telcoin-ui-update/` (root-owned, for the privileged UI helper),
  gated by a hardcoded list + the whole-bundle `UI_VERSION`.
A script used by BOTH (or by a UI-invoked shim) must be present in BOTH.

**How to apply:** When adding a script the UI helper invokes — or that a UI-dispatched shim
execs — add it to the `ui/install-ui.sh` `/opt/telcoin-ui-update` copy loop AND the
`update-scripts.sh` SCRIPTS manifest. The install-ui.sh edit rides on the `UI_VERSION` bump.

## Migration scripts must be tested against REAL deployed artifacts, not assumed formats (2026-06-26)

**Symptom (caught in live staggered rollout, not review):** `migrate-node-naming.sh`'s
`rewrite_wrapper` aborted on the devnet observer (node5) -- "Normalized wrapper still
contains --observer." Its `--observer`-strip `sed` only deleted a line that is *only*
`--observer \` (the multi-line heredoc wrapper produced by setup-observer.sh >= v1.2.22).
But node5 was deployed by setup-observer.sh **v1.2.21**, whose wrapper is a SINGLE LINE:
`exec docker run ... telcoin node --datadir /home/nonroot --observer --instance 5 ...`
-- `--observer` is INLINE. The whole-line delete never matched, the flag survived, and the
post-condition guard correctly failed + rolled back (node5 was fine throughout).

**Root cause:** version skew. The migration (and its Phase-4 fixture test) was written/verified
against the *current* wrapper format, while the *deployed* nodes run an older format. "Confirmed
byte-for-byte against setup-observer.sh" confirmed against the wrong version.

**Fix:** handle BOTH shapes -- keep the own-line delete, ADD an inline token-strip
`s/(^|[[:space:]])--observer([[:space:]]|$)/\2/g`. Verified read-only against node5's AND a
validator's actual wrapper using the node's own GNU sed (operating on a /tmp copy).

**How to apply:**
- For any in-place migration/rewrite, fetch a REAL target artifact from a live node and test the
  transform against IT (with the node's own tool versions -- GNU vs BSD sed differ), before rollout.
  `cat -A` to reveal hidden whitespace/CRLF.
- Don't trust "matches the current generator" -- deployed fleets lag the generator by versions.
  Grep the `# Auto-generated by <script> v<X>` header on a node to see what actually produced it.
- Two good defenses held here: a strict post-condition guard, and self-rollback. A migration that
  mutates in place should always (a) verify its own output and (b) roll back on any guard failure.
