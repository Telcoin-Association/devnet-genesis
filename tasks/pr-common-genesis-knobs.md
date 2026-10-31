TITLE: genesis, create-instances: env-driven genesis timing and fee flags, optional tn-scripts-ref metadata

Adds six optional inputs. Every one defaults to today's arguments, so adiri and testnet, which set none of them, are unchanged.

`genesis.sh`, the `telcoin genesis` call. All four change the genesis hash.

- `MIN_HEADER_DELAY_MS` / `MAX_HEADER_DELAY_MS` feed `--min-header-delay-ms` / `--max-header-delay-ms`. Unset or empty falls back to the `1000` / `3000` that were hard-coded.
- `MAX_BATCH_DELAY_MS` adds `--max-batch-delay-ms`, and `WORKER_FEE_CONFIG` adds `--worker-fee-config` (one `WORKER_ID:STRATEGY:VALUE` entry). Each flag is passed only when its variable is non-empty, from an args array built next to `chainid_args` and expanded in the `${arr[@]+"${arr[@]}"}` form that is safe under `set -u` on bash 3.2.

`create-instances.sh`: `TN_NODE_SCRIPTS_REF` appends `tn-scripts-ref=<ref>` to `--metadata`, after the WireGuard attributes. It is computed above the loop, like `WG_META`, and adds nothing when unset or empty.

`genesis.sh` also takes `GENESIS_DOCKER_USER=<uid>:<gid>` (devnet exports `"$(id -u):$(id -g)"`), which adds `--user <uid>:<gid> -e HOME=/tmp` to the `docker run`, before the image. The image runs as `USER nonroot` (uid 1101) and the build writes `committee.yaml`, `genesis.yaml` and `parameters.yaml` into the bind-mounted workspace. Docker Desktop on macOS maps bind-mount ownership, so this never showed up there. On rootful Linux docker uid 1101 cannot write an operator-owned 0775 workspace, and the build fails with `Failed to open configuration file using OpenOptions ... Permission denied (os error 13)`. `HOME=/tmp` is needed because the operator's uid has no passwd entry in the image, and with `HOME=/` the binary aborts creating `/.cache/reth/logs`. The knob does not change the genesis hash. With the real `v0.2.0-devnet` image, a run with it and a run as uid 1101 in a 0777 workspace gave byte-identical `committee.yaml` and `parameters.yaml`, and the two `genesis.yaml` files differed only in the wall-clock `timestamp`. Unset or empty adds neither flag. The gate below covers it: argv and stdin match 4a2925c with it unset or empty, and with `1000:1000` the argv gains exactly those four arguments before the image.

Byte-identical gate. I put stub `docker`, `gcloud` and `mktemp` on `PATH`. The `docker` stub writes each argument on its own line and saves stdin, which is where the BLS passphrase is piped. The `gcloud` stub does the same for `beta compute instances create` and answers `instances describe` as not found. The `mktemp` stub returns a fixed path so `WG_KEYS_FILE` is the same on every run. The 4a2925c file and this branch's file were each copied to the same path and run under `env -i` with one dummy config. `genesis.sh` ran in `GENESIS_LIB_ONLY=1` mode under `set -u` and called `tn_genesis_build_committee`. Two instances went through `create-instances.sh`. The argv dumps were then diffed.

- `genesis.sh`: identical argv and stdin with everything unset, with `CHAIN_ID` set, with no passphrase, and with all the new variables set to empty strings.
- `create-instances.sh`: identical argv with the WireGuard hub off, with it on (the real `hub-coordinates.env`), and with the new variables empty.
- With `MIN_HEADER_DELAY_MS=350 MAX_HEADER_DELAY_MS=1000 MAX_BATCH_DELAY_MS=250 WORKER_FEE_CONFIG=0:0:10000000 TN_NODE_SCRIPTS_REF=deadbeef`, the genesis argv ends `--min-header-delay-ms 350 --max-header-delay-ms 1000 --max-batch-delay-ms 250 --worker-fee-config 0:0:10000000`. `--metadata` ends `...,WG_NODE_PUBLIC_SSH=1,tn-scripts-ref=deadbeef` with the hub on and `...,BASE_DOMAIN=<domain>,tn-scripts-ref=deadbeef` with it off. No other argument changes.

The flag names and the fee-config format match `crates/telcoin-network-cli/src/genesis/mod.rs` in telcoin-network.

Checked: `bash -n`. `shellcheck` finds the same findings as at 4a2925c, with none added (21 in genesis, 27 in create-instances). The bash portability lint is clean on `create-instances.sh`. It reports two errors on `genesis.sh` that 4a2925c already had (`${pull_pids[-1]}` and `${deploy_pids[-1]}`, bash 4.3+); this PR leaves them alone.
