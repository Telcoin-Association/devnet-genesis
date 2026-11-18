# Sources: l2-publish-worker-gateway-image

| Item in the draft | Source | Status |
|---|---|---|
| Title, rows 2/29/30 scope, "who meets it" | `tasks/challenges-l2-report.md` section 2.1 and section 4 row `publish-worker-gateway-image` | checked |
| Images built by hand from 5533ff73a, outside CI, 2026-11-17 | `tasks/l2/facts/image-probes.md` lines 1-7 | checked |
| `tn-worker-gateway 0.1.0` from `--version` | `tasks/l2/facts/image-probes.md:55-56`; `tasks/l2/image-digests.md:17` | checked |
| Node `--version` has `Commit SHA`, timestamp, `Build Features:` | `tasks/l2/facts/image-probes.md` lines after "a. node version" (Commit SHA / Build Timestamp / Build Features lines) | checked |
| No `GIT_SHA` arg; `RUSTUP_TOOLCHAIN=1.94` channel | row 29; `git -C telcoin-network show 5533ff73a:bin/worker-gateway/Dockerfile` lines 30, 32, 73 | checked |
| "rustup downloaded the 1.94 channel toolchain" at build time | `tasks/l2/facts/image-probes.md:14` | checked |
| Build window 19:32:52-19:37:15 UTC, exit 0; digest 8b887098f5cc… | `tasks/l2/facts/image-probes.md:6,13-14` | checked |
| Probe at 19:42 UTC, by digest after push at 19:48 UTC | `tasks/l2/facts/image-probes.md:1`; `tasks/l2/image-digests.md:1,17` | checked |
| No workflow or Makefile target names the gateway | `git -C telcoin-network grep -n -iE 'gateway\|node-record' 5533ff73a -- .github/ Makefile` -> only `Makefile:191` (comment on log tests) | checked (read from code) |
| `bin/worker-gateway/src/cli.rs:62` `#[command(author, version, ...)]` | `git grep -nE 'version' 5533ff73a -- bin/worker-gateway/src` | checked |
| `bin/worker-gateway/Cargo.toml:3` `version.workspace = true` | same git grep | checked |
| `crates/telcoin-network-cli/README.md:374` guard flag doc | `git grep -nE 'allow-faucet-on-chain' 5533ff73a -- crates bin` | checked |
| `grep -ci faucet` on `node --help` = 4; guard flag in every build | `tasks/l2/facts/image-probes.md:38-42`; row 30 | checked |
| `grantMintRole: expected 32 bytes` count 0; 1 on launch 1's faucet build | `tasks/l2/facts/image-probes.md:36-37`; `tasks/l2/image-digests.md:14` | checked |
| PR #68 pins empty, refusal text | `git -C tn-node-deployment grep -nE 'GW_(TESTNET\|MAINNET)_IMAGE_PIN=\|pins no worker-gateway image' 79fb24e…` -> `lib/gateway.sh:60,62,463` | checked (read from code, not run) |
| Standalone gateway is the only mainnet layout | report section 2.1 | taken from the row, source not re-read |
| Workspace CI lanes may compile the crate | not checked | not verifiable here |
