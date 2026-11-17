# l2-shim: rehearse the launch-2 deploy on this machine

`run.sh` runs `./devnet-deploy.sh --yes` for a step range against a fake outside world, so that a
driver mistake (a wrong flag, host, order or index) shows up before the real fleet is touched.
Nothing in a rehearsal can reach GCP, a VM, a registry or a chain.

```
tasks/l2-shim/run.sh --to 3                                  # fresh fake cloud, steps 1..3
tasks/l2-shim/run.sh --to 8 --state /tmp/shim-a              # keep the state ...
tasks/l2-shim/run.sh --from 9 --to 10 --state /tmp/shim-a    # ... and widen from it
tasks/l2-shim/run.sh --only 10 --state /tmp/shim-a --sig pending   # must stop: exit 3 at step 10
tasks/l2-shim/run.sh --only 10 --state /tmp/shim-a --sig ok        # the shim signs with a throwaway key
```
Exit 0 only when the range ran clean: deploy exit 0 (or, with `--sig pending` and step 10 in range,
exit 3 at step 10 with `RELEASE_SIG_PENDING`), no finding, no sentinel hit, no real-gcloud log, no
Python traceback from the shim. The report lists the step reached, remote commands per step and
per instance, and every finding.

## How it works
- **Snapshot.** The worktree (without `.git`, `tasks/`, `.secrets/`, `logs/`, `benchmark/` and the
  `tn-node-deployment/` submodule) is copied to `STATE/repo`, and the drivers run from there. The
  deploy's own log (`${REPO_DIR}/logs/…`, devnet-deploy.sh) and `common/genesis.sh`'s
  `./logs/genesis-deployment/` cannot be moved by environment, so this is the only way to keep the
  worktree's `genesis/`, `releases/` and `logs/` untouched. A later run on the same state refreshes
  the drivers and keeps `genesis/` and `releases/`.
- **Config.** `CONFIG_FILE=STATE/config-shim.sh` sources the snapshot's `config.sh`, then sets
  `TN_NODE_SCRIPTS_REF` (HEAD of the tn-node-deployment branch whose flags are checked) and
  `RELEASE_KEYS_DIR` (the throwaway key). `config.sh` itself is never edited. The fake BLS
  passphrase comes from `TN_BLS_PASSPHRASE_FILE`; the fake secrets are in the fake Secret Manager.
- **Initial cloud** (as the teardown leaves it): none of the seven fleet VMs; the five old nodes'
  static addresses reserved; the obs VM, its address and its data disk kept (the teardown never
  deletes them); no load balancer; secrets `obs-ingest-token`, `obs-grafana-admin`,
  `devnet-admin-dashboard-password`, `devnet-admin-dashboard-hash`, `devnet-contracts-admin-pk`,
  `devnet-txgen-age-key` with fake values.
- **Step 4** runs on a pseudo-terminal: the shim creates exactly the A records the step printed (in
  `STATE/dns.json`, answered by the fake `dig`) and presses ENTER. So it proves the records are
  consistent with the VMs, not that they are the right records.
- **Signature.** `--sig ok`: once the deploy reaches step 7, the shim signs
  `releases/<RELEASE_TAG>/SHA256SUMS` with a throwaway ed25519 key generated in `STATE/gnupg`, whose
  public key is the only one in `RELEASE_KEYS_DIR`. `TN_SKIP_RELEASE_SIG` is never used (it is unset).

## What is faked (fakes.py; standard library only)
Operator side (`bin/`, first on PATH):
- `gcloud`: compute instances create/describe/list/delete/add-tags/remove-tags/get-serial-port-output,
  addresses, firewall-rules, disks, ssh, scp; secrets (access/add/create/describe/IAM binding);
  `services enable`; `auth print-access-token`; `config get-value`. `beta`/`alpha` prefixes are
  stripped. `--format` json, `value(...)`, `value[separator=...]`, `csv`, projections `a.b[0]`, `a[].b`,
  `.basename()`, `.list()`, `.map().firewall_rule()`; `--filter` with `=`, `:`, `~`.
  A VM created with `startup-script` and `tn-scripts-ref` metadata "boots": its serial console ends
  in the startup marker, docker/ufw/nftables units exist, and `/opt/telcoin-node-scripts/<script>`
  holds one fake per script of the tn-node-deployment branch.
- `docker run … telcoin genesis`: writes `genesis/committee.yaml` from `genesis/validators/*.yaml` and
  the three delays into `parameters.yaml`; `genesis/genesis.yaml` is kept as it is (template).
- `cast`: only offline conversions pass to the real cast (`CAST_OFFLINE`); anything else is a finding.
- `dig +short`: answers from `STATE/dns.json`. `ssh`, `scp`, `curl` on the operator side: findings.

Remote side: `gcloud compute ssh <vm> --command=C` runs C locally in a sandbox. Paths under `/etc
/var /opt /tmp /home /root /run /srv /mnt /usr/local /lib/systemd` are rewritten into
`STATE/hosts/<vm>/root/` (also inside a `bash -s` script read from stdin); any other absolute path
(`/usr/bin/…`, `/proc`, `/dev/…` except null/std streams) refuses the command. PATH holds only
`remote-bin/` (fakes: `sudo systemctl stat chown chgrp install mountpoint whoami id hostname` plus
strict stubs `journalctl ss curl ufw docker getent ip git`) and `STATE/sandbox-real/` (links to
plain tools: coreutils, grep, sed, awk, jq, python3, …). A command found nowhere fails with 127 and
is a finding. Ownership is modelled in `STATE/hosts/<vm>/owners.json` (default root:root; scp
uploads tnadmin; the data dir telcoin) and read back by the fake `stat`. Unit state is in
`units.json`; a `systemctl restart telcoin` of a stopped unit is listed as SUSPECT.
tn-node-deployment: `tnd <script>` first checks every flag against `STATE/flags.json`, generated on
each run from the real argument parsers of `L2_SHIM_TND` (`fakes.py gen-flags <dir>`: every
`--flag` in a case pattern); then the script's emulator runs. Emulated so far: `setup-node.sh
--json --phase=keygen` (node-keys, a node-info.yaml of the real shape with libp2p-consistent fake
keys, `.node-meta` keys, the done event). Everything else is a finding until it has an emulator.

## Sentinel and its blind spots
`sentinel/` comes right after `bin/` on PATH: network tools without a fake (`forge sops age gsutil
wget nc socat …`) land there, are logged to `STATE/sentinel.log` and refused (exit 99). A real
binary reached by an absolute path or a reset PATH finds a poisoned environment: `CLOUDSDK_CONFIG`
is an empty directory (no account; any real gcloud call would also leave a log file there, which
the report counts), `DOCKER_HOST` is a missing socket, `HTTP(S)_PROXY`/`ALL_PROXY` and
`ETH_RPC_URL` point at a closed local port. Not caught: a driver calling `/usr/bin/ssh` directly
(ssh ignores those variables). run.sh lists every driver line with an absolute tool path or a PATH
assignment (today only `devnet-txgen.sh:311`, which prepends `~/.cargo/bin`).

## Logs in the state directory
- `calls.log`: `ts  step=N  tool  instance  command  [<stdin N bytes>]` for every gcloud/ssh/scp/dig/
  docker/cast call (stdin is never stored); `operator` lines for the DNS answer and the signing.
- `findings.log`: `KIND  step=N  instance  detail  command  fatal|note`; KIND is UNRECOGNISED (no
  emulator), FLAGCHECK (a flag the real script lacks), UNSAFE (outside the fake filesystem, a wrong
  project, an unpinned image), SUSPECT (listed, not fatal).
- `remote-detail.log`: every fake called inside a host sandbox. `deploy-output.log`: the deploy's
  terminal. Earlier runs' logs move to `previous-runs/<stamp>/`.

## What it cannot prove
It does not run the real tn-node-deployment scripts, Caddy, ufw, docker, a node or a chain; it does
not check DNS, certificates, IAP, timing or quorum. A fake answers what the emulator says the real
command answers, so a wrong emulator hides a wrong driver: emulators follow the contract and the
fact sheets, not the drivers. `genesis.yaml` is not regenerated. Step 4's records are the printed ones.

## Adding an emulator
- gcloud verb: a function `gc_x(pos, fl, cmdline)` and an entry in `GCLOUD`.
- remote tool: `ln -s ../bin/_dispatch remote-bin/<tool>`, then a branch in `r_simple` (or its own
  function, dispatched in `main`). Remote fakes read and write the host through `host()`,
  `units_path()`, `set_owner`/`get_owner`.
- tn-node-deployment mode: a function in `TND` (`TND["setup-gateway.sh"] = tnd_setup_gateway`); emit
  the events and the done line of the contract (`emit(event="done", ok=…)`).
- operator tool: `ln -s _dispatch bin/<tool>` and an entry in the `main` table.
Then re-run from the failing step with `--state DIR --from N`.
