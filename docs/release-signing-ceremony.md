# Release signing ceremony

This document is for the two people who handle the release signature in a devnet launch: the operator who runs `./devnet-deploy.sh` on the build host (xerxes), and the signer who holds the release key on a YubiKey.
It covers the `v0.2.0-devnet` launch.

The devnet launch rehearses the mainnet release signature.
It uses the same file shape, the same key and the node's `gpgv` verdict rules (made stricter, see below), and checks the signature at a different place: on the deploy host, before any node is finalized.

Script releases of tn-node-deployment (`MANIFEST.sig`, an `ssh-keygen -Y` signature over `MANIFEST`) are a separate signature and are out of scope here.

## How a mainnet node verifies a release

A node release is a GitHub release of telcoin-network.
Next to the binary tarball and `IMAGE_DIGEST`, it publishes two files that the node scripts check before they use anything else:

- `SHA256SUMS`: one `<64 hex>  <name>` line (two spaces) for each of exactly five files. They are `IMAGE_DIGEST`, the tarball `telcoin-network-<tag>-x86_64-unknown-linux-gnu.tar.gz`, and the network's `chain-configs/<dir>/committee.yaml`, `genesis.yaml` and `parameters.yaml`.
- `SHA256SUMS.asc`: an ASCII-armored detached GPG signature over `SHA256SUMS`.

`IMAGE_DIGEST` is one line, `<repo>@sha256:<64 hex>`.

The node builds a keyring from the public keys shipped in tn-node-deployment `lib/release-keys/*.asc`, dearmored into a throwaway GnuPG home, together with an allow list of each key's primary fingerprint.
It then runs:

```bash
gpgv --status-fd 1 --keyring <keyring> SHA256SUMS.asc SHA256SUMS
```

and judges the status lines (`_tn_gpg_status_verdict` in `lib/common.sh`):

- Accepted only when a `GOODSIG` is followed by a `VALIDSIG` whose last field, the primary key fingerprint, is on the allow list.
- Refused on a `BADSIG` by any key, and on `EXPKEYSIG`, `REVKEYSIG` or `EXPSIG`.
- Refused when no listed key made a good signature (the verdict is `NOSIG`).
- A further signature by a key that is not in the keyring (`NO_PUBKEY`) is not checked and only draws a warning.

After the signature, every file the node uses must match its `SHA256SUMS` line, the three chain-config hashes must equal the pins in the installed script release, and `IMAGE_DIGEST` must name a repository the scripts accept for the network.

The Docker image itself carries no signature (there is no cosign step).
It is bound to the release only through its digest: the signed `SHA256SUMS` covers `IMAGE_DIGEST`, the node pulls by that digest, and the scripts check that Docker holds the image under the same digest.

Since 2026-11-17 the devnet check reads the maintainers' keys from the `tn-release-signing` submodule (`keys/`, with the table and the rules in its `KEYS.md`), pinned at a commit of that repository's `main`.
At the pinned commit, 813fcf4, two keys are listed:

| handle | primary key fingerprint | expires |
|---|---|---|
| grantkee | `95A38484E1CBD31D773F6AF928FD56AD2F9FAE47` | 2028-11-16 |
| MavenRain | `32F886ADE9C3A88218E4B67CA0A69159FC76DBFD` | 2028-11-10 |

grantkee's earlier RSA key, `4E36D35A4AB61B589861D01AC7173F2377CA7573`, was rotated out on 2026-11-17 and the devnet check no longer accepts it.
tn-node-deployment still ships that RSA key in `lib/release-keys`, so a testnet or mainnet node verifies a release against it until the scripts take the new key; `lib/release-keys/README` there has the node's rules.
To take a later key change, move the submodule to the new commit of `tn-release-signing` and read the fingerprints against `KEYS.md`.

## What devnet does instead

A devnet node never verifies a release.
Under tn-node-deployment PR #52 (the lib/common 2.0.1 devnet rules, "PR 12" in the fleet notes) a devnet node:

- accepts a Docker image only as `<repo>@sha256:<64 hex>`, from the devnet repository allow list;
- refuses release tags, `-devnet` tags included, and never asks the registry to resolve one;
- never downloads `SHA256SUMS` (the release fetch returns before any download on devnet).

So the rehearsal moves the signature check to the deploy host.
`devnet-release-sign.sh` writes a `SHA256SUMS` of the mainnet shape, the signer signs it with the shipped release key, and deploy step 8 checks the signature with `gpgv` before it touches any node.
If the check fails, no node is started on that genesis.

The verdict is the node's, with two differences that only refuse more: a further signature by a key that is not on the keyring (`NO_PUBKEY`) fails, and `gpgv` itself must exit 0.

The devnet `SHA256SUMS` is the mainnet shape minus the tarball, since devnet nodes run only the Docker image.
It has four lines: `IMAGE_DIGEST`, `genesis.yaml`, `committee.yaml` and `parameters.yaml`.

What the rehearsal exercises: the release key on the YubiKey, the signer's procedure, the `SHA256SUMS` grammar and the `gpgv` verdict rules.
What it does not exercise: verification on each node, the tarball, the GitHub release page and the chain-config pins.

## Configuration

In `config.sh`:

| variable | this launch | meaning |
|---|---|---|
| `RELEASE_TAG` | `v0.2.0-devnet` | names the release directory, `releases/<tag>/` |
| `RELEASE_KEYS_DIR` | `tn-release-signing/keys` (default, the submodule) | the public keys `verify` accepts |
| `RELEASE_SIGNER_FPR` | `95A38484E1CBD31D773F6AF928FD56AD2F9FAE47` | the grantkee key the signer is expected to use; informational |

`verify` also loads `<repo>/release-keys/*.asc`, which holds no keys unless Path 3 is used.

Set per run, in the environment:

| variable | meaning |
|---|---|
| `RELEASE_SIGN_SSH_HOST` | the ssh host name for xerxes that `prepare` prints in the signer one-liner |
| `TN_SKIP_RELEASE_SIG=1` | operator-only bypass of the pending state (see [The bypass](#the-bypass)) |

The release files, under `releases/v0.2.0-devnet/`:

| file | written by | content |
|---|---|---|
| `IMAGE_DIGEST` | `prepare` | one line, `<repo>@sha256:<64 hex>`: the image the fleet runs (`DOCKER_IMAGE` in `config.sh`) |
| `SHA256SUMS` | `prepare` | four lines, over `IMAGE_DIGEST`, `genesis.yaml`, `committee.yaml` and `parameters.yaml` |
| `SHA256SUMS.asc` | the signer | detached armored signature over `SHA256SUMS` |

All three are committed to the fleet repo together with the genesis files they cover.

## Where it runs in the deploy

The steps of `./devnet-deploy.sh` that matter here:

| step | what runs | signing role |
|---|---|---|
| 5 | `./devnet-keygen.sh` | new keys change the genesis, so a re-run invalidates a signature |
| 6 | `./devnet-genesis-build.sh`, then `./devnet-release-sign.sh prepare` | writes `IMAGE_DIGEST` and `SHA256SUMS`, prints the signer one-liner |
| 7 | `./devnet-network-config.sh --yes` | runs while the signer signs |
| 8 | `./devnet-finalize.sh`, which runs `./devnet-release-sign.sh verify` first | the gate: no node is touched until it passes |

`verify` has four outcomes:

| rc | meaning | effect on the deploy |
|---|---|---|
| 0 | a good signature by a listed key, and every hash and the image digest match | prints the `VALIDSIG` line; finalize continues |
| 3 | `SHA256SUMS.asc` is missing; prints `RELEASE_SIG_PENDING` | the deploy stops before step 8 touches a node |
| 1 | a bad or unlisted signature, a signature file `gpgv` rejects, a missing manifest or key, or any hash or digest mismatch | the deploy stops; no flag gets past it |
| 2 | usage: `RELEASE_TAG` malformed, a config path unset, or `gpg`, `gpgv` or `sha256sum` missing | finalize treats it as a failure (exit 1); no flag gets past it |

The signer can sign as soon as step 6 prints the one-liner.
If `SHA256SUMS.asc` is in place when step 8 starts, the deploy does not stop.
If it stops with `RELEASE_SIG_PENDING`, sign (Path 1 below), then resume:

```bash
./devnet-release-sign.sh verify
./devnet-deploy.sh --yes --from 8
```

The first command is optional, since step 8 runs `verify` again, but it shows the result before the deploy resumes.

### The bypass

`TN_SKIP_RELEASE_SIG=1` lets step 8 continue past the pending state (rc 3) and prints a loud banner saying the release is unsigned.
It is for the operator only, in a devnet emergency such as a signer who cannot be reached while the fleet must come up.

```bash
TN_SKIP_RELEASE_SIG=1 ./devnet-deploy.sh --yes --from 8
```

It never applies to rc 1.
A failed verification means the signature is bad or not by a listed key, or the files on xerxes are not the ones that were signed.
The deploy must stop.

After a bypass, record it as a deviation in `tasks/verification/`, get the signature as soon as the signer is back, run `./devnet-release-sign.sh verify`, and commit `SHA256SUMS.asc`.

## The hosts and the key

xerxes, the build and deploy host, runs Linux with gpg 2.4.8 and `gpgv`.
It has no scdaemon or pcscd, no YubiKey attached, and an empty keyring.
It can verify a signature, since `gpgv` needs only public keys, but it cannot sign with the release key.

The signer's YubiKey holds the shipped release key (grantkee, primary `95A38484E1CBD31D773F6AF928FD56AD2F9FAE47`) in its OpenPGP applet.
Each signature needs the user PIN and a touch.

The signer's laptop runs macOS with GnuPG and the YubiKey plugged in.

That leaves three ways to get `SHA256SUMS.asc` onto xerxes.
Path 1 is the default.

## Path 1: sign on the laptop (default)

On the laptop, check that GnuPG sees the card:

```bash
gpg --card-status
```

It should print the card's serial number and a signature key.
If it reports no card, see [Troubleshooting](#troubleshooting).

Then run the one-liner that `prepare` printed in step 6.
Copy it from the deploy output, which has the real host name and repo path.
Its form is:

```bash
ssh <xerxes> 'cat <repo>/releases/v0.2.0-devnet/SHA256SUMS' > /tmp/SHA256SUMS && gpg --detach-sign --armor --local-user 95A38484E1CBD31D773F6AF928FD56AD2F9FAE47 --output /tmp/SHA256SUMS.asc /tmp/SHA256SUMS && scp /tmp/SHA256SUMS.asc <xerxes>:<repo>/releases/v0.2.0-devnet/SHA256SUMS.asc
```

gpg asks for the PIN on the laptop, then the YubiKey blinks until it is touched.
`<xerxes>` is the host name `prepare` printed: set `RELEASE_SIGN_SSH_HOST` before the deploy if the laptop's ssh config uses another name, or edit the name in the line.

The one-liner signs whatever xerxes serves.
A signer who wants to read the file first runs the parts separately:

```bash
ssh <xerxes> 'cat <repo>/releases/v0.2.0-devnet/SHA256SUMS' > /tmp/SHA256SUMS
ssh <xerxes> 'cat <repo>/releases/v0.2.0-devnet/IMAGE_DIGEST'
cat /tmp/SHA256SUMS
```

`SHA256SUMS` should have four lines, and `IMAGE_DIGEST` should name the digest pushed for this launch.
Then sign, check the signature locally, and copy it back:

```bash
gpg --detach-sign --armor --local-user 95A38484E1CBD31D773F6AF928FD56AD2F9FAE47 --output /tmp/SHA256SUMS.asc /tmp/SHA256SUMS
gpg --verify /tmp/SHA256SUMS.asc /tmp/SHA256SUMS
scp /tmp/SHA256SUMS.asc <xerxes>:<repo>/releases/v0.2.0-devnet/SHA256SUMS.asc
```

On xerxes, the operator checks it:

```bash
cd <repo>
./devnet-release-sign.sh verify
```

and resumes with `./devnet-deploy.sh --yes --from 8` if the deploy stopped.

### Why this is the mainnet shape

The private key never leaves the YubiKey, and the YubiKey never meets the build host.
xerxes sends a text file and receives a signature, so a compromised or misconfigured build host cannot make a release signature by itself.

The check on xerxes does not depend on the signing side.
`verify` runs `gpgv` against the public key files in `RELEASE_KEYS_DIR` and not against the signer's GnuPG setup or trust database. (Until 2026-11-17 these were the files a mainnet node uses, tn-node-deployment's `lib/release-keys`; they are now the maintainers' keys in `tn-release-signing`, which the node scripts have yet to take.)
That is the split mainnet relies on: the signer holds the key, and the verifier holds only the public key that ships with the node scripts.

## Path 2: gpg-agent forwarding (alternative)

This path is documented but is not the default.
ssh forwards the laptop's gpg-agent into a session on xerxes, and `gpg` on xerxes signs through it.
The YubiKey stays on the laptop, and the PIN and touch prompts appear there.

It costs more than Path 1:

- xerxes needs an sshd change, and the signature needs a live forwarded socket.
- While the forward is up, any process on xerxes running as that user can ask the laptop's agent for a signature. Each one still needs a touch, but the build host now chooses what is signed.

### One-time setup on xerxes

sshd must be allowed to replace an existing socket file at the forward's path.
`StreamLocalBindUnlink` is currently unset on xerxes, so add it in a drop-in and restart sshd:

```bash
echo 'StreamLocalBindUnlink yes' | sudo tee /etc/ssh/sshd_config.d/60-gpg-agent-forward.conf
sudo sshd -t && sudo systemctl restart ssh
```

Existing ssh sessions survive the restart.

Find the path of xerxes's agent socket, which the forward replaces:

```bash
gpgconf --list-dirs agent-socket
```

On xerxes this prints `/run/user/1000/gnupg/S.gpg-agent`.

gpg on xerxes needs the public key to know which key to ask the agent for.
Import it from the shipped key file, then either give it ownertrust or pass `--trust-model always` when signing:

```bash
cd <repo>
gpg --import tn-node-deployment/lib/release-keys/grantkee.asc
echo '95A38484E1CBD31D773F6AF928FD56AD2F9FAE47:6:' | gpg --import-ownertrust
```

### Each signing session

On xerxes, stop the local agent so it does not answer in place of the forwarded one:

```bash
gpgconf --kill gpg-agent
```

systemd's `gpg-agent.socket` keeps the socket file in place after the kill, which is why sshd needs `StreamLocalBindUnlink yes` to bind over it.
Do not run gpg on xerxes again until the forwarded session below is open.

On the laptop, find the agent's extra socket, which is the restricted socket meant for forwarding:

```bash
gpgconf --list-dirs agent-extra-socket
```

It prints `/Users/<u>/.gnupg/S.gpg-agent.extra`.
Connect with the forward (one line; the same `RemoteForward` line can go in `~/.ssh/config` instead):

```bash
ssh -o 'RemoteForward /run/user/1000/gnupg/S.gpg-agent /Users/<u>/.gnupg/S.gpg-agent.extra' <xerxes>
```

In that session, check the forward is live:

```bash
gpg --list-secret-keys 95A38484E1CBD31D773F6AF928FD56AD2F9FAE47
```

It should list the key.
If it prints nothing or `No secret key`, the forward is not live: disconnect, run `gpgconf --kill gpg-agent` on xerxes again, and reconnect.

Sign, and check:

```bash
cd <repo>/releases/v0.2.0-devnet
gpg --detach-sign --armor --local-user 95A38484E1CBD31D773F6AF928FD56AD2F9FAE47 SHA256SUMS
cd <repo>
./devnet-release-sign.sh verify
```

Add `--trust-model always` to the `gpg --detach-sign` line if you skipped the ownertrust import.
The signature lands in `SHA256SUMS.asc` next to `SHA256SUMS`.
Log out of the session when done, which removes the forward.

## Path 3: a devnet-only key

Use this when the shipped key cannot sign for this launch and a real signature check is still wanted.
It replaces the release key with a key made for devnet only.

Make the key on the laptop, not on xerxes, so that it stays off the build host, and export its public half:

```bash
gpg --quick-generate-key 'Telcoin devnet release signer (devnet only)' ed25519 sign 90d
gpg --list-keys --with-colons 'Telcoin devnet release signer' | awk -F: '$1 == "fpr" { print $10; exit }'
gpg --armor --export <devnet-fpr> > devnet-release.asc
ssh <xerxes> 'mkdir -p <repo>/release-keys'
scp devnet-release.asc <xerxes>:<repo>/release-keys/devnet-release.asc
```

`devnet-release-sign.sh` loads `<repo>/release-keys/*.asc` as well as `RELEASE_KEYS_DIR`, so `verify` accepts this key.
Sign as in Path 1, with `--local-user <devnet-fpr>` in place of the shipped fingerprint, and commit `release-keys/devnet-release.asc` with the release files so the check can be repeated later.

Never add a devnet key to tn-node-deployment `lib/release-keys`.
That directory is the key set shipped in signed script releases to testnet and mainnet nodes, and any key in it is accepted on real network releases.

This path loses fidelity.
The rehearsal no longer exercises the shipped key, the YubiKey or the signer's procedure, which are the parts mainnet depends on.
The `VALIDSIG` fingerprint will not be `RELEASE_SIGNER_FPR`.
The `SHA256SUMS` grammar and the `gpgv` verdict rules are still exercised.
Record the deviation and the devnet key's fingerprint in `tasks/verification/`.

## Re-signing

The signature covers `SHA256SUMS`, and `SHA256SUMS` covers the image digest and the three genesis files.
Anything that changes one of them needs a new signature:

- a re-run of keygen (step 5), since new keys change the genesis;
- a re-run of the genesis build (step 6);
- a different image digest in `config.sh`.

`prepare` refuses to overwrite a `SHA256SUMS` that has been signed unless it is given `--force`.
If step 6 runs again over a signed release and `prepare` refuses, the deploy stops at step 6, after the genesis build.
Confirm that the change was intended, then:

```bash
./devnet-release-sign.sh prepare --force
```

The signer runs the newly printed one-liner (Path 1).
On the laptop, remove the copies from the last signature first, or gpg stops to ask before it overwrites `/tmp/SHA256SUMS.asc`:

```bash
rm -f /tmp/SHA256SUMS /tmp/SHA256SUMS.asc
```

Then, on xerxes:

```bash
./devnet-release-sign.sh verify
./devnet-deploy.sh --yes --from 7
```

Do not edit `SHA256SUMS` by hand, and do not keep an old `SHA256SUMS.asc` next to new sums.
`--force` belongs to `prepare` only.
When `verify` reports a hash mismatch nobody expected, find out what changed before re-signing: a signature over an unexplained change defeats the check.

Commit the release files with the genesis they cover only after `verify` returns 0.

## Verification evidence

After `verify` returns 0, record the result under `tasks/verification/` (create the directory if it is missing):

```bash
mkdir -p tasks/verification
./devnet-release-sign.sh verify 2>&1 | tee -a tasks/verification/release-signature-v0.2.0-devnet.txt
sha256sum releases/v0.2.0-devnet/SHA256SUMS releases/v0.2.0-devnet/SHA256SUMS.asc | tee -a tasks/verification/release-signature-v0.2.0-devnet.txt
cat releases/v0.2.0-devnet/IMAGE_DIGEST | tee -a tasks/verification/release-signature-v0.2.0-devnet.txt
```

The record must hold:

- The `VALIDSIG` line, with its fingerprint and timestamp. Its form is `[GNUPG:] VALIDSIG <signing key fpr> <YYYY-MM-DD> <signature timestamp> <expire> <version> <reserved> <pubkey algo> <hash algo> <class> <primary key fpr>`. The last field must be `95A38484E1CBD31D773F6AF928FD56AD2F9FAE47`, or the devnet key for Path 3. The shipped key has no signing subkey (its primary key signs), so with it the first and last fields are the same. `date -u -d @<signature timestamp>` turns the timestamp into a date.
- The sha256 of `SHA256SUMS` and `SHA256SUMS.asc`, and the content of `IMAGE_DIGEST`.
- Which path was used, and any bypass or devnet key.
- The fleet repo commit that holds the release files.

For an independent check that does not use `devnet-release-sign.sh`, run plain `gpgv` the way a node does, in a throwaway GnuPG home:

```bash
cd <repo>
d="$(mktemp -d)"
for k in tn-node-deployment/lib/release-keys/*.asc; do GNUPGHOME="$d" gpg --dearmor < "$k"; done > "$d/release-keys.gpg"
GNUPGHOME="$d" gpgv --status-fd 1 --keyring "$d/release-keys.gpg" releases/v0.2.0-devnet/SHA256SUMS.asc releases/v0.2.0-devnet/SHA256SUMS
rm -rf "$d"
```

It must print `GOODSIG` and a `VALIDSIG` line ending in the listed primary fingerprint.
This checks only the signature; `verify` also checks the hashes and the digest.
For Path 3, add `release-keys/*.asc` to the loop.

## Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `verify` rc 3, `RELEASE_SIG_PENDING` | `SHA256SUMS.asc` is not on xerxes yet | sign (Path 1), then `./devnet-deploy.sh --yes --from 8` |
| `NO_PUBKEY <keyid>`, `verify` rc 1 | the signing key is not in `RELEASE_KEYS_DIR` (or, for a devnet key, not in `<repo>/release-keys/`) | check `RELEASE_KEYS_DIR` in `config.sh`; `gpg --show-keys --with-fingerprint <file>.asc` lists what a key file holds; for Path 3, copy the public key into `<repo>/release-keys/` |
| `BADSIG` | `SHA256SUMS` changed after it was signed, or the signer signed a different copy | find out what changed; never edit the file by hand; fetch it again and re-sign |
| "genesis changed since signing" | keygen or the genesis build ran again after the signature | confirm the change was intended, then `./devnet-release-sign.sh prepare --force` and re-sign (see [Re-signing](#re-signing)) |
| `prepare` refuses to overwrite signed sums | step 6 or `prepare` ran again over a signed release | see [Re-signing](#re-signing) |
| `EXPKEYSIG` or `REVKEYSIG` | the key expired (grantkee expires 2028-10-16) or was revoked | renew the key as `lib/release-keys/README` in tn-node-deployment describes |
| laptop: `gpg --card-status` finds no card, or signing fails with a card error | GnuPG on the laptop does not see the YubiKey | replug the YubiKey, run `gpgconf --kill scdaemon` to restart scdaemon, then `gpg --card-status` again |
| laptop: gpg asks whether to overwrite `/tmp/SHA256SUMS.asc` | a copy is left from an earlier signature | `rm -f /tmp/SHA256SUMS /tmp/SHA256SUMS.asc` and run the one-liner again |
| `ssh` or `scp` in the one-liner cannot reach the host | the laptop's ssh name for xerxes differs from the printed one | edit the host in the line (`RELEASE_SIGN_SSH_HOST` sets the name `prepare` prints) |
| Path 2: `remote port forwarding failed for listen path` | `StreamLocalBindUnlink yes` is not set in sshd | add it as in Path 2 and restart sshd |
| Path 2: `No secret key` on xerxes | the forward is not live, or a local agent answers in its place | disconnect, `gpgconf --kill gpg-agent` on xerxes, reconnect, and check with `gpg --list-secret-keys <fpr>` |
