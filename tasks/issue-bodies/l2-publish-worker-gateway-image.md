# No CI job builds or publishes the worker-gateway image, and the binary's --version reports no commit.

Nothing in this repository builds or publishes the `worker-gateway` image, and an image built from `bin/worker-gateway/Dockerfile` cannot say which commit it holds, so deployment scripts that pin the gateway by digest have nothing to pin.
A second, separable point (a node image cannot be shown faucet-free from `--help`) is the last item of "What happens"; it could be left out or filed on its own.

## What happens

- A devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis) ran on 2026-11-17 from images built by hand from 5533ff73a, outside CI.
- The gateway image's `--version` prints `tn-worker-gateway 0.1.0` and nothing more.
  The node image built from the same commit prints `Commit SHA: 5533ff73a…`, a build timestamp and a `Build Features:` line.
- `bin/worker-gateway/Dockerfile` takes no `GIT_SHA` build argument and sets `RUSTUP_TOOLCHAIN=1.94`, a channel: rustup downloaded the 1.94 channel toolchain during the build, so the compiler patch release depends on the build date. The base images are pinned by digest.
- No workflow under `.github/workflows/` and no `Makefile` target names the gateway's Dockerfile or binary.
- The deployment scripts (tn-node-deployment PR #68, open) start a gateway only from a digest. Their testnet and mainnet pins are empty, so `setup-gateway.sh --enable` there refuses with `this scripts release pins no worker-gateway image for <network>`.
  The standalone gateway is the only mainnet layout, so the launch team meets this first and then every validator operator at install time.
- Separable point: a "no faucet" check on `telcoin node --help` cannot pass. `grep -ci faucet` counts 4 on a build without the faucet feature, all from the guard flag `--allow-faucet-on-chain`, which every build lists.
  The devnet probed the binary for a faucet-only string instead (`grantMintRole: expected 32 bytes`: 0 hits; 1 hit on an earlier faucet build).

## Evidence

- Gateway build: 2026-11-17, 19:32:52 to 19:37:15 UTC, on the operator's build host, `docker buildx build -f bin/worker-gateway/Dockerfile --platform linux/amd64 --load .` at 5533ff73a, exit 0. Image `sha256:8b887098f5cc…`.
  `--version`, user and entrypoint were probed on the local image at 19:42 UTC and again by registry digest after the push at 19:48 UTC, with the same output.
  Recorded in devnet-genesis `tasks/l2/facts/image-probes.md` (build commands and section d) and `tasks/l2/image-digests.md`.
- The toolchain download is noted beside the build command in `tasks/l2/facts/image-probes.md`.
- CI and Makefile: `git grep -n -iE 'gateway|node-record' 5533ff73a -- .github/ Makefile` finds one comment, `Makefile:191`, about the gateway's log tests, and no build. Read from code, not run.
- Pins and refusal: tn-node-deployment `lib/gateway.sh:60`, `:62` and `:463` at PR #68's head 79fb24e. Read from code; not run against testnet or mainnet.
- Faucet probes: `tasks/l2/facts/image-probes.md` section b, on the node image of the same build.

## Where in the code

At 5533ff73a:

- `bin/worker-gateway/Dockerfile:30` pins `rust:1.94-slim-bookworm` by digest; `:32` sets `ENV RUSTUP_TOOLCHAIN=1.94`; `:73` runs `cargo build --locked -p tn-worker-gateway --bin worker-gateway --release`. The file declares no `ARG` for a commit.
- `bin/worker-gateway/src/cli.rs:62`: `#[command(author, version, about, long_about = None)]`, so `--version` is the crate version, which `bin/worker-gateway/Cargo.toml:3` takes from the workspace.
- The guard flag is documented at `crates/telcoin-network-cli/README.md:374`: it lets a faucet build start on a chain other than adiri or mainnet. It is not a faucet.

## What is not known

- Whether a release process outside this repository builds the gateway. None was found in `.github/` or the `Makefile`.
- Whether the workspace CI lanes compile and test the gateway crate (not checked). They would not produce an image either way.
- Whether the node's `Build Features:` line, empty in this build, is meant to serve as the "no faucet" signal. Not checked.

## What could be done (suggestions, none tried)

- A release job that builds `bin/worker-gateway/Dockerfile` for each release tag and publishes the image, so the digest can be pinned in a signed scripts release.
- Take `GIT_SHA` as a build argument, as `etc/Dockerfile` does for the node, and print it in the gateway's `--version`.
- Set `RUSTUP_TOOLCHAIN` to an exact release so a rebuild uses the same compiler as the pinned base image.
- For the node: state in the CLI docs that `Build Features:` in `--version` is how to tell a faucet build, or print a dedicated line for it.

## Related

- {{node-record-api-standalone-build}}: the other image under `bin/` with no build in CI; it does not build at this commit.
- {{forwarder-one-client-per-rpc-node}} and {{gateway-keepalive-close-after-429}}: gateway behaviour seen with this image.
- tn-node-deployment PR #68 (open): runs the gateway only from a digest; its testnet and mainnet pins wait for a published image.
