# Validator execution-key provisioning

Every devnet validator has two kinds of keys. The BLS key signs consensus messages and is made on the node at keygen. The execution key is an ordinary secp256k1 account key that sends the validator's own ConsensusRegistry transactions. `devnet-validator-key.sh` creates execution keys: one command per node, the private key stored only in Secret Manager.

## Why each validator needs an execution key

Keygen (`devnet-keygen.sh`, which runs `setup-node.sh --phase=keygen` on the node) creates the node's BLS key and signs a proof of possession over the node's execution address, `config.sh` `EXECUTION_ADDRESSES[i]`. The proof goes into the node-info file that keygen pulls back: `genesis/validators/nodeN.yaml` for nodes 1-4, `genesis/observers/node5.yaml` for node 5. The proof binds the BLS key to that one address.

`stake()` checks the proof against the address that sends the transaction. If any other address sends it, the call reverts with `InvalidProofOfPossession`. `activate()` is also sent from the validator's address. Without the private key for `EXECUTION_ADDRESSES[i]`, the node can never become a validator after genesis.

The two kinds of keys live in different places. The BLS key, and the network keys the node derives from it, exist only on the node, as `node-keys/bls.kw` under the data dir, encrypted with the BLS passphrase (on the MC machine that passphrase is `.secrets/bls-passphrase`, gitignored). The execution key never touches the node. The MC machine fetches it from Secret Manager when a registry transaction has to be signed.

Node 5 is the case that matters today. Nodes 1-4 are seated by the genesis build, while node 5 joins after genesis through `devnet-stake-node5.sh`, which sends `stake()` and `activate()` from node 5's address.

## Where the key lives

| What | Where |
| --- | --- |
| Private key | Secret Manager, project `tn-devnet`, secret `devnet-<nodeN>-validator-pk`. The value is `0x` plus 64 lower-case hex characters, with no trailing newline. |
| Address | `config.sh` `EXECUTION_ADDRESSES[i]`, lower case. |
| Funding | `testnet_accounts.yaml`: `"<address>": # <nodeN> execution key (stake 1,000,000 TEL + gas)` with `balance: "0xd3c787962b1b04100000"`, which is 1,000,100 TEL in wei. |

`config.sh` also names node 5's secret in `NODE5_VALIDATOR_PK_SECRET`, which `devnet-stake-node5.sh` reads. It must be `devnet-node5-validator-pk`. The script refuses to run for node5 if it is anything else.

The key is not in the repo or in any keystore on disk, and no log has it. `tn_secret` reads the newest version (`latest`).

## What the script does

```bash
./devnet-validator-key.sh node5                    # create + store the key; show the file edits
./devnet-validator-key.sh node5 --apply            # create + store the key; make the file edits
./devnet-validator-key.sh node5 --rotate --apply   # the same, when the secret already exists
```

1. Preflight. The node must be in `NODE_NAMES`, and for node5 the secret name must match `NODE5_VALIDATOR_PK_SECRET`. If the secret already exists (`gcloud secrets describe` succeeds), the script stops unless `--rotate` is given. It then renders and checks both file edits with a stand-in address, so a malformed `EXECUTION_ADDRESSES` line or a conflicting accounts entry stops the run before any key exists.
2. Create and store. `cast wallet new --json` runs once. Its output stays in one unexported shell variable. The private key is cut out of it on a pipe that feeds `tn_secret_set` (gcloud `--data-file=-`), and the variable is unset.
3. Read back. `tn_secret <name> | python3 devnet-stake-node5.py import-key --expect <address>` imports the newest version into a throwaway keystore and checks that it opens to the new address. This is the same path `devnet-stake-node5.sh` uses, so a pass means the stake script will load this key.
4. Edits. The script replaces `EXECUTION_ADDRESSES[i]` (a placeholder or an old address) with the new address and adds or replaces the funding entry. Before writing anything it checks that the edited config passes `bash -n`, that it sources with only element `i` changed, and that the count of `PLACEHOLDER_` markers drops by one when a placeholder was replaced. For the accounts file it checks that the edited file parses to the old accounts plus the one new entry, and that `devnet-genesis-build.sh`'s own funding grep finds the address. With `--apply` it writes both files. Without it, it prints the diffs.

The script prints the new address and the secret name. It never prints the private key or the public key. It refuses to run under `set -x`, and checks again just before it creates the key, in case `config.sh` turned xtrace on.

Exit codes: 0 done; 1 refused or failed (the message says whether a key was stored); 2 usage (an unknown option or node). The preflight also refuses an `EXECUTION_ADDRESSES[i]` that is neither a placeholder nor a `0x` address.

An existing entry for the same address in `testnet_accounts.yaml` is left alone. An entry tagged `# <nodeN> execution key` for a different address stops the run, unless `--rotate` is given, in which case the entry is replaced.

A run without `--apply` still creates and stores a key; only the file edits are left undone. To finish, apply the printed diff by hand, or run `--rotate --apply`, which makes a newer key and supersedes the one just stored.

## How devnet-stake-node5.sh uses the key

`devnet-stake-node5.sh` loads the key in its `load_key` step:

```bash
tn_secret devnet-node5-validator-pk | python3 devnet-stake-node5.py import-key --dir <0700 tmp> --name node5 --expect <EXECUTION_ADDRESSES[4]>
```

The helper reads the key from stdin and types it into `cast wallet import -i` on a private pty, together with a random keystore password that it keeps in a 0600 file in the same 0700 directory. Then it opens the keystore and checks that the address matches. `cast send` signs with `--keystore <dir>/node5 --password-file <dir>/node5.pw`, and the directory is removed when the script exits. The key never appears on argv, where `ps` and `/proc` would show it. `cast send --private-key` would put it there. `cast wallet import` reads a key only from argv or `/dev/tty`, which is why the helper needs the pty.

Its preflight also checks that `EXECUTION_ADDRESSES[4]` equals the `execution_address` in `genesis/observers/node5.yaml`, and that the address holds the stake plus gas.

## Rotation

`--rotate` lets the script run when the secret already exists. The new key becomes the newest version, and `tn_secret` reads that one. Older versions stay enabled. Once the new key is in use, disable them:

```bash
gcloud secrets versions list devnet-node5-validator-pk --project=tn-devnet
gcloud secrets versions disable <N> --secret=devnet-node5-validator-pk --project=tn-devnet
```

What else a rotation needs depends on how far the devnet has got.

- Before keygen for that node: nothing else. The node has a new address, and keygen binds the proof of possession to it.
- After keygen, before launch: the node-info file holds a proof over the old address, so `stake()` would revert with `InvalidProofOfPossession`. Keygen refuses a node that already has keys, so the node needs a new VM (teardown, then deploy), a new keygen, a new genesis build, and a new network-config render.
- After launch: genesis cannot change. The old address keeps its genesis funding, and for nodes 1-4 it keeps the genesis committee seat. A new key here means a new validator. Fund the new address by transfer, run keygen on a new VM (a BLS key cannot be registered twice: `DuplicateBLSPubkey`), mint through the Safe, stake and activate, then exit the old validator. `devnet-stake-node5.sh` covers only node 5 (it reads `EXECUTION_ADDRESSES[4]`).

When a run replaces a real address rather than a placeholder, the script prints a warning: a genesis or node-info file built from the old address still funds and binds it.

## A new devnet, start to finish

The key has to exist before deploy step 5 (keygen binds the proof to `EXECUTION_ADDRESSES[i]`). It also has to exist before step 6: `devnet-genesis-build.sh` refuses to build when node 5's address is not funded in `testnet_accounts.yaml`.

```bash
./devnet-validator-key.sh node5 --apply            # first use of the secret
./devnet-validator-key.sh node5 --rotate --apply   # the secret is left from an earlier devnet
grep -n PLACEHOLDER_ config.sh                     # nothing: the image digest must be pinned too
./devnet-teardown.sh --yes                         # only if an old fleet is still up
./devnet-deploy.sh --yes
./devnet-stake-node5.sh                            # dry run, then --yes once node 5 syncs
```

Review the `config.sh` and `testnet_accounts.yaml` diff before committing it. It contains only the address and the balance. The same command works for node1 through node4. They are seated by the genesis build, so they do not use the stake part of the funding at launch.

## Agent checklist for future devnets

Run these from the repo root in bash. zsh arrays start at 1, so in zsh `${EXECUTION_ADDRESSES[4]}` is node 4. Set `i` to the node's index (node5 is 4).

```bash
source ./devnet-lib.sh
i=4
node="${NODE_NAMES[$i]}"; addr="${EXECUTION_ADDRESSES[$i]}"; secret="devnet-${node}-validator-pk"

# 1. The secret exists and its newest version is ENABLED.
gcloud secrets versions list "$secret" --project="$PROJECT_ID" </dev/null

# 2. The secret's key belongs to the config address. Prints the address on a match;
#    anything else ("belongs to 0x..., not the expected ...") is a mismatch.
d="$(mktemp -d)"
tn_secret "$secret" | python3 devnet-stake-node5.py import-key --dir "$d" --name check --expect "$addr"
rm -rf "$d"

# 3. The address is funded: one entry, balance 0xd3c787962b1b04100000.
grep -i -A1 "^\"$addr\":" "$GENESIS_WORKSPACE/testnet_accounts.yaml"

# 4. No placeholders left (the devnet-deploy.sh gate): prints 0.
grep -n PLACEHOLDER_ config.sh | grep -cv -E '^[0-9]+:[[:space:]]*#'

# 5. After keygen: the node-info binds the same address.
grep execution_address genesis/observers/node5.yaml      # nodes 1-4: genesis/validators/nodeN.yaml
```

If check 2 fails, the config and the secret disagree. Do not edit `config.sh` by hand to match: run `./devnet-validator-key.sh <nodeN> --rotate --apply`, which keeps the two in step. If check 5 shows an old address, keygen has not run since the key changed (see Rotation).

Rules for handling the key: never print it, never pass it on argv (`--private-key`), never export it or write it to a file. The only reader is the `tn_secret | devnet-stake-node5.py import-key` pipe.

## Related

- [`tasks/runbook-reset-2026-10-30.md`](../tasks/runbook-reset-2026-10-30.md) §3 has the manual version of this step, which the script replaces.
- [`release-signing-ceremony.md`](release-signing-ceremony.md)
- [`mainnet-simulation-plan.md`](mainnet-simulation-plan.md)
