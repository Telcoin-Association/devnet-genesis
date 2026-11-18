# Sources: l2-admission-version-floor-missing

TND = /home/drtnarg/coding/telcoin/tn-node-deployment, M = origin/main (2813343), P = 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (PR #68 head). DG = devnet-genesis.

| Item in the draft | Source | Status |
|---|---|---|
| Claims: `MIN_ADMISSION_VERSION` is a TODO (row 14, its admission part only); digest-pinned image cannot be checked, warns and writes (row 57) | `tasks/challenges-l2.md` rows 14, 57; report section 2.12 | checked; row 14's "still a TODO" is partly wrong: the floor is set to `0.17.0` with a `TODO(node team): confirm` comment |
| `[WARN] Could not tell whether the image …adiri@sha256:0aec3e7c… is release 0.17.0 or later, which --admission needs (an older release ignores the admission settings); writing them anyway.` | DG `tasks/l2/w3/d3a/as-run.md:7` (marked there "not verified wording") | checked (as quoted in the as-run, not in a raw log) |
| `[OK] Admission settings written to /var/lib/telcoin/network-config (mode Closed)` | same line | checked |
| Warning on all hosts: "the release-floor [WARN] on all five (as on node1)" | DG `tasks/l2/w3/d3a/as-run.md:9` | checked |
| 2026-11-18, 00:42-00:56 UTC | as-run `:7`, `:9` | checked |
| `lib/common.sh:2768` `# TODO(node team): confirm`, `:2769` `readonly MIN_ADMISSION_VERSION="0.17.0"` | `git show M:lib/common.sh \| sed -n '2762,2800p'`; P `:2769` by `git grep` | checked at M; `:2769` at P, `:2768` at P inferred |
| Comment quotes ("A floor too low …", "No release tag contained that merge …") `:2762-2767` | same `sed` at M | checked at M only |
| `tn_node_supports_admission` `:2771-2793`, "on the part after its last ":"", rc 2 "the answer is unknown, which is not a no" | same `sed` at M | checked at M only |
| For `…@sha256:<hex>` the part after the last ":" is the digest, so rc 2 | reading of the regex at M | inferred from code |
| `setup-node.sh:2637` warning, `:2620` stop comment | `git grep -n -E "MIN_ADMISSION_VERSION\|Could not tell whether"` at M and P | checked (both refs) |
| `edit-config.sh:1650` (M) / `:1679` (P) | same grep | checked (both refs) |
| Mainnet images are pinned by digest | report section 4 consequence column | taken from the row, source not re-read (not stated as fact in the draft) |
| Behaviour on mainnet with unknown version | not run, branch not read | not verifiable here |
| An older release would get settings it ignores | warning text + comment | inferred, not tried |
| Row 14's `install.sh` / `update-scripts.sh` part | row 14 | taken from the row, out of scope |
