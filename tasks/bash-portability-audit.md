# Bash portability audit — macOS (bash 3.2) ↔ Linux (bash 5 / GNU) — 2026-06-20

Triggered by `devnet-finalize.sh:69` (`mapfile`) dying on the operator Mac: macOS `/bin/bash`
is **3.2.57** (no bash-4 builtins, BSD coreutils); Linux is bash 4+/5 + GNU. A `#!/bin/bash`
shebang on macOS forces 3.2, so any bash-4 feature there breaks.

Method: a verified multi-agent scan of all 43 scripts in **devnet-genesis** (own) +
**tn-node-deployment** (43 scanners → independent re-verification). Key discriminator: **where
each script actually runs** — operator's Mac vs the Ubuntu nodes. GNU/bash-4 usage in code that
only runs on the Linux nodes is correct for its runtime (WARN, not a defect).

## Fixed now (operator scripts — run on the Mac, genuinely broke)
| script | issue | fix |
|---|---|---|
| `devnet-finalize.sh:69` | `mapfile` under `#!/bin/bash` → dies on macOS 3.2 | env-bash shebang **+** portable `while read` loop |
| `devnet-keygen.sh:76` | same `mapfile` | same |
| `reset-network.sh:63` | same `mapfile` (my addition) | same |
| 8 top-level drivers | `#!/bin/bash` (would break if bash-4 added later) | shebang → `#!/usr/bin/env bash` (prevention) |

All 11 verified: parse under `/bin/bash` 3.2 **and** bash 5; the read-loop runs under 3.2.

## Prevention
`tasks/check-bash-portability.sh` — a portable lint (runs on 3.2): **ERROR** on a bash-4 feature
under `#!/bin/bash` (the exact regression), **WARN** on GNU-only tools / bash-4 under any shebang.
Exits non-zero on ERROR — wire into CI / pre-commit. Operator scripts are currently ERROR-clean.

## Latent — NOT fixed (tn-node-deployment scripts run on the Ubuntu NODES, work today)
These manage Linux infra (systemd / ufw / `/proc` / `/etc/systemd`) and execute on the nodes
under bash 5 + GNU, so they are **not broken**. They WOULD break only if run locally on a Mac/BSD.
Listed for a deliberate hardening decision (separate shared-submodule change):

- **`edit-config.sh`** (7×) and **`ui/telcoin-ui-helper.sh`** (sed `-i` ×4, `stat -c` ×3,
  `hostname -I`) — GNU `sed -i` with no backup suffix (BSD consumes the next token as the
  suffix); some additionally use GNU-only BRE `\+` / `-E`-as-suffix. Real on BSD, fine on the nodes.
- **`check-node.sh`** — `df --output`/`-BG`, `/proc/meminfo` (÷0 → abort on macOS), `date -d`.
- **`lib/common.sh`** — `${response,,}` (bash-4 case-mod), `sed -i`, `df --output`, `hostname -I`, `nproc`.
- **`update-scripts.sh`** — `declare -gA` (bash-4.2 associative arrays; 2 are dead/never-read), `sha256sum`.
- **`remove-node.sh`** — `timeout`/`gtimeout` (absent on macOS), `pgrep -a`, `getent`.
- **`setup-validator.sh` / `setup-observer.sh` / `update-node.sh`** — `df -BG --output`, `lsblk` (guarded), `sha256sum`.

Recommended portable patterns (when hardened): `sed` via temp file (`t=$(mktemp); sed … > "$t" &&
cat "$t" > f`); `wc -c` for size (not `stat -c%s`); `df -Pk | awk` (not `--output`); guard
`/proc` blocks on `[[ -r /proc/meminfo ]]`; `command -v sha256sum || shasum -a 256`;
`nproc 2>/dev/null || sysctl -n hw.ncpu`. Raw scan: see the workflow output in the session tasks dir.

**Decision needed:** harden the tn-node-deployment node scripts for true Mac/BSD portability
(another submodule commit + node refresh), or leave as-is since they only run on the Ubuntu nodes?
`common/` (44 more scripts) was out of scope here — same call applies.
