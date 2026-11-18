# setup-node.sh cannot check a digest-pinned image against the admission floor, so it writes the settings unchecked

`setup-node.sh` checks the node release against `MIN_ADMISSION_VERSION` before it writes the admission settings, but a digest-pinned image carries no version it can read, so the check only warns.
Every validator operator who pins the image by digest meets it; the floor itself, `0.17.0`, is marked `TODO(node team): confirm`.

## What happens

On validator-1-devnet finalize printed (the run's notes mark the wording as not verified):

```
[WARN] Could not tell whether the image …adiri@sha256:0aec3e7c… is release 0.17.0 or later, which --admission needs (an older release ignores the admission settings); writing them anyway.
[OK] Admission settings written to /var/lib/telcoin/network-config (mode Closed)
```

The same warning appeared on all six hosts. On the devnet the image was new enough, so nothing went wrong.

The check exists for the case the code's comment names: "A floor too low would pass a release that drops the keys without a word while the host looks configured."
With a digest-pinned image the check never decides, so a release older than the floor would get settings it ignores, behind one warning line. Inferred from the warning text and the comment; not tried with an older image.

The floor was set ahead of any release: "No release tag contained that merge when this floor was set; the newest, v0.16.0, ignores the keys, so the floor is the next minor release."

## Evidence

- Live run on 2026-11-18, finalize from 00:42 to 00:56 UTC, on a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis).
- devnet-genesis `tasks/l2/w3/d3a/as-run.md:7` (validator-1-devnet, both lines above) and `:9` ("the release-floor [WARN] on all five (as on node1)").
- What `setup-node.sh` does with an unknown version on mainnet was not run.

## Where in the code

The same lines at tn-node-deployment `origin/main` (2813343) and PR #68's head (79fb24e) unless two are given.

- `lib/common.sh:2768-2769`: `# TODO(node team): confirm` and `readonly MIN_ADMISSION_VERSION="0.17.0"`, with the reasoning in the comment above (`:2762-2767`, read at main).
- `lib/common.sh:2771-2793` (main): `tn_node_supports_admission` judges an image "on the part after its last ":"" and returns 2, "the answer is unknown, which is not a no", for anything that is not a release version. For `…@sha256:<hex>` that part is the digest.
- `setup-node.sh:2637`: the "Could not tell whether … is release ${MIN_ADMISSION_VERSION} or later" warning; `:2620` documents the stop for a release known to be older.
- `edit-config.sh:1650` (main) / `:1679` (PR): the same warning when admission is edited later.

## What is not known

- Whether setup refuses an unknown version on mainnet or only warns, as on devnet (the branch around `setup-node.sh:2637` was not read past the warning).
- Which release first carries the admission keys, and so whether `0.17.0` is right.
- How the operator is meant to learn the version of the image a digest names.

## What could be done (suggestions, none tried)

- Record the release version beside the pinned digest (a flag or a `.node-meta` key), and check that version; or read it from the image itself before writing.
- Off devnet and testnet, refuse when the answer is unknown unless the operator overrides it explicitly.
- Confirm the floor once a release that contains the admission keys is tagged, and drop the TODO.

## Related

- {{healthcheck-bare-port-binds-loopback}}: the scripts need the image's version there too, to choose the `--healthcheck` form.
- Row 14 of the same run also notes that `install.sh` and `update-scripts.sh` cannot install a PR head; that part is not drafted here.
