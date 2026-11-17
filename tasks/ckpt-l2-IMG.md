status: done (node + gateway built and probed; node-record-api blocked by a source compile error)
unit: IMG (devnet launch 2 image build)
updated: 2026-11-17T19:47:27Z
completed sections: 1 Preflight, 2 Build (node + gateway OK; nra FAILED: source error), 3 Probes (node+gateway; nra n/a), 4 Smoke (gateway: stays up, /health 200, /ready 503, RPC 502 -32001) -> facts/image-probes.md
current: none. recursive submodule update finished rc=0 (all nested tn-contracts/lib submodules clean); no containers left
build results: node exit=0 19:32:21Z-19:35:25Z (3m04s) id sha256:0aec3e7cd145...; gateway exit=0 19:32:52Z-19:37:15Z (4m23s) id sha256:8b887098f5cc...; nra exit=1 19:37:25Z-19:40:33Z: tn-network-types fails E0277 SealedHeader: serde::Serialize/Deserialize not satisfied at crates/network-types/src/notify.rs:87-90 when built alone (cargo build -p tn-node-record-api); likely tn-types' reth-primitives-traits dep lacks the serde feature (crates/types/Cargo.toml:18), masked by feature unification in node builds (hypothesis, not verified)

## 1. Preflight (facts so far)
- worktree HEAD = 5533ff73addac1f823ef37881a3907c67f54506e (verified)
- df -h /home: 914G size, 273G avail (69% used)
- no other cargo/buildx build running at start
- docker 29.9.3, buildx builder "default" (docker driver, buildkit v0.34.2, linux/amd64): --load is native
- tn-contracts at 70ad96cc6 checked out; recursive lib/* submodules (forge-std, OZ, safe, solady, v4-core, v4-periphery) were still cloning (slow; the Rust build only reads tn-contracts/artifacts + deployments/genesis)
- node Dockerfile takes CARGO_FEATURES and GIT_SHA; gateway and node-record-api Dockerfiles take NO build args
- launch-1 faucet probe: grep -c 'grantMintRole: expected 32 bytes' /usr/local/bin/telcoin (faucet is a precompile, not an RPC method)

## Build commands (run from /home/drtnarg/coding/telcoin/tn-l2-img)
node:    docker buildx build -f etc/Dockerfile --build-arg CARGO_FEATURES= --build-arg GIT_SHA=5533ff73addac1f823ef37881a3907c67f54506e --platform linux/amd64 --load -t us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.3.0-devnet .
gateway: docker buildx build -f bin/worker-gateway/Dockerfile --platform linux/amd64 --load -t us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway:v0.3.0-devnet .
nra:     docker buildx build -f bin/node-record-api/Dockerfile --platform linux/amd64 --load -t node-record-api:l2 .
pids/logs: devnet-genesis/tasks/l2/img-{node,gateway,nra}.{pid,log}
note: node+gateway share the cache mounts (target=./target, sharing=locked), so their cargo steps serialize
