# Launch 2 image probes (unit IMG, 2026-11-17T19:42:02Z)

Source: telcoin-network 5533ff73addac1f823ef37881a3907c67f54506e (worktree tn-l2-img, detached), built on xerxes,
`docker buildx` builder `default` (docker driver, buildkit v0.34.2), `--platform linux/amd64 --load`, no push.
NODE=sha256:0aec3e7cd1457488ed052a3cff8371a235f213f57e9fc727a3a62fb7abad11c1  (us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.3.0-devnet)
GW=sha256:8b887098f5cc5cb5ebc591bc82b1347513b23ae3ecca4f22787b2e4204f8c231    (us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway:v0.3.0-devnet)
node-record-api:l2: NOT BUILT (source compile error, see build log tasks/l2/img-nra.log)

## Build commands (cwd /home/drtnarg/coding/telcoin/tn-l2-img)
```
docker buildx build --progress=plain -f etc/Dockerfile --build-arg CARGO_FEATURES= --build-arg GIT_SHA=5533ff73addac1f823ef37881a3907c67f54506e --platform linux/amd64 --load -t us-docker.pkg.dev/telcoin-network/tn-public/adiri:v0.3.0-devnet .
  # exit=0, 19:32:21Z -> 19:35:25Z (3m04s; cargo 2m37s, incremental on the shared target cache mount)
docker buildx build --progress=plain -f bin/worker-gateway/Dockerfile --platform linux/amd64 --load -t us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway:v0.3.0-devnet .
  # exit=0, 19:32:52Z -> 19:37:15Z (4m23s; cargo 1m34s; rustup downloaded the 1.94 channel toolchain at build time)
docker buildx build --progress=plain -f bin/node-record-api/Dockerfile --platform linux/amd64 --load -t node-record-api:l2 .
  # exit=1, 19:37:25Z -> 19:40:33Z: error[E0277] SealedHeader: serde::Serialize / Deserialize not satisfied,
  # crates/network-types/src/notify.rs:87-90; "could not compile tn-network-types (lib) due to 4 previous errors"
```

## a. node version, user, entrypoint
```
$ docker run --rm $NODE telcoin --version
telcoin-network-cli Version: 0.1.0
Commit SHA: 5533ff73addac1f823ef37881a3907c67f54506e
Build Timestamp: 2026-11-17T19:32:48.016402852Z
Build Features: 
Build Profile: release
Reth Database: tn-lmdb
$ docker image inspect --format 'user={{.Config.User}} entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}} ports={{json .Config.ExposedPorts}}' $NODE
user=nonroot entrypoint=null cmd=["telcoin","node"] ports=null
```
User is the NAME `nonroot` (uid 1101 inside the image, etc/Dockerfile:76-80), not numeric. No ENTRYPOINT; CMD `telcoin node`.

## b. node: no faucet
```
$ docker run --rm --entrypoint sh $NODE -c "grep -c 'grantMintRole: expected 32 bytes' /usr/local/bin/telcoin"
0          (grep rc=1; launch 1's faucet build printed 1 — the same probe)
$ docker run --rm $NODE telcoin --help | grep -ci faucet      -> 0
$ docker run --rm $NODE telcoin node --help | grep -ci faucet -> 4
```
The 4 hits are the `--allow-faucet-on-chain` guard flag (env TN_ALLOW_FAUCET_ON_CHAIN), present in every build: it only lets
a faucet-built binary start; it is not a faucet. "Build Features:" is empty. The faucet in this codebase is the mint
precompile (crates/tn-reth/src/evm/tel_precompile/faucet.rs), not an RPC method; there is no `faucet_*` RPC method string.

## c. node: tn_admissionSnapshot
```
$ docker run --rm --entrypoint sh $NODE -c "grep -c 'tn_admissionSnapshot' /usr/local/bin/telcoin"
1
```

## d. gateway
```
$ docker image inspect --format 'user={{.Config.User}} entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}} ports={{json .Config.ExposedPorts}}' $GW
user=1101:1101 entrypoint=["worker-gateway"] cmd=null ports={"8545/tcp":{},"8546/tcp":{}}
$ docker run --rm $GW --version
tn-worker-gateway 0.1.0
$ docker run --rm $GW --help > facts/gateway-help.txt     (rc=0, 326 lines)
```
--version carries no commit SHA (the gateway Dockerfile takes no GIT_SHA arg).

## e. node help files
- facts/node-help.txt: `telcoin node --help` (rc=0, 581 lines; has --http.addr at line 98, --healthcheck at line 475)
- facts/keytool-help.txt: `telcoin keytool generate validator --help` and `... observer --help` (both rc=0, 354 lines)

## f. node-record-api
Not built; no help file.

## g. image list
```
$ docker image ls --digests --no-trunc
us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway  v0.3.0-devnet  sha256:8b887098f5cc5cb5ebc591bc82b1347513b23ae3ecca4f22787b2e4204f8c231  IMAGE ID same
us-docker.pkg.dev/telcoin-network/tn-public/adiri           v0.3.0-devnet  sha256:0aec3e7cd1457488ed052a3cff8371a235f213f57e9fc727a3a62fb7abad11c1  IMAGE ID same
$ docker image inspect --format '{{.Id}} {{.Size}}'
adiri:v0.3.0-devnet           sha256:0aec3e7cd1457488ed052a3cff8371a235f213f57e9fc727a3a62fb7abad11c1 227674459   (228MB)
worker-gateway:v0.3.0-devnet  sha256:8b887098f5cc5cb5ebc591bc82b1347513b23ae3ecca4f22787b2e4204f8c231 138003749   (138MB)
node-record-api:l2            No such image
```
The local DIGEST is the local index (manifest list incl. a buildkit attestation manifest); the registry digest after the
operator's push is not verified here.

## Smoke: gateway with nothing upstream (section 4, 60 s, loopback only)
```
docker run -d --name l2-img-gw-smoke --network=host --user 1101:1101 --read-only --cap-drop ALL $GW \
  --listen-addr 127.0.0.1:8655 --probe-addr 127.0.0.1:8656 --metrics 127.0.0.1:9655 \
  --upstream-rpc-url http://127.0.0.1:18545 --upstream-readiness-url http://127.0.0.1:18551/health/workers \
  --redirect-queries http://rpc.l2-smoke.invalid:8545
```
(nothing listened on 18545/18551; `.invalid` never resolves). Probed at t=5 s and t=60 s; full transcript:
```
start=2026-11-17T19:42:23Z
ae2ac1315401393ff257f24bbc5184adae67cf07474b95cde5f11b4b8c70da47
run rc=0
--- t=5s state: running running=true exit=0 restarts=0
GET http://127.0.0.1:8655/health -> 200 body=
GET http://127.0.0.1:8655/ready -> 503 body={"ready":false}
GET http://127.0.0.1:8655/ready/any -> 503 body={"ready":false,"submissions":false,"queries":false}
GET http://127.0.0.1:8656/health -> 200 body=
GET http://127.0.0.1:8656/ready -> 503 body={"ready":false}
GET http://127.0.0.1:8656/ready/any -> 503 body={"ready":false,"submissions":false,"queries":false}
POST eth_blockNumber -> 502 time=0.000670s body={"error":{"code":-32001,"message":"upstream unreachable"},"id":1,"jsonrpc":"2.0"}
POST tn_nodeMode -> 502 time=0.000589s body={"error":{"code":-32001,"message":"upstream unreachable"},"id":1,"jsonrpc":"2.0"}
GET metrics 9655 -> 200
--- t=60s state: running running=true exit=0 restarts=0
GET http://127.0.0.1:8655/health -> 200 body=
GET http://127.0.0.1:8655/ready -> 503 body={"ready":false}
GET http://127.0.0.1:8655/ready/any -> 503 body={"ready":false,"submissions":false,"queries":false}
GET http://127.0.0.1:8656/health -> 200 body=
GET http://127.0.0.1:8656/ready -> 503 body={"ready":false}
GET http://127.0.0.1:8656/ready/any -> 503 body={"ready":false,"submissions":false,"queries":false}
POST eth_blockNumber -> 502 time=0.000916s body={"error":{"code":-32001,"message":"upstream unreachable"},"id":1,"jsonrpc":"2.0"}
POST tn_nodeMode -> 502 time=0.000942s body={"error":{"code":-32001,"message":"upstream unreachable"},"id":1,"jsonrpc":"2.0"}
GET metrics 9655 -> 200
--- logs (stdout+stderr)
2026-11-17T19:42:23.765981Z  WARN gateway: --redirect-queries uses plain http to a host that is not a loopback, private, CGNAT or link-local address; reads and their answers cross the network unencrypted upstream=http://rpc.l2-smoke.invalid:8545
2026-11-17T19:42:23.816608Z  INFO gateway: starting worker gateway listen_addr=127.0.0.1:8655 upstreams=1 redirect_queries=http://rpc.l2-smoke.invalid:8545 redirect_queries_header=false recent_submission_ttl=Some(60s) shutdown_delay=0ns graceful_shutdown_timeout=45s cors="off"
2026-11-17T19:42:23.816626Z  INFO gateway: edge protections configured rate_limiting=true trusted_proxies=0 proxy_protocol=false submission_budget=false rate_limit_per_ip_max_entries=Some(100000) max_connections_per_ip=Some(32) rate_limit_v4_prefix=32 rate_limit_v6_prefix=64 max_request_bytes=1048576 max_batch_len=Some(50) max_inflight_submissions=256 max_inflight_queries=256 max_upstream_inflight
2026-11-17T19:42:23.817326Z  INFO tn::listener: operator listener bound listener="metrics" listen_on=127.0.0.1:9655 exposure=loopback
2026-11-17T19:42:23.817335Z  INFO tn::metrics: prometheus metrics endpoint listening listen_on=127.0.0.1:9655
2026-11-17T19:42:23.817354Z  INFO gateway: metrics endpoint listening bound=127.0.0.1:9655
2026-11-17T19:42:23.817463Z  INFO gateway::server: worker gateway listening local_addr=127.0.0.1:8655
2026-11-17T19:42:23.817462Z  INFO gateway::server: probe listener listening local_addr=127.0.0.1:8656
2026-11-17T19:42:23.818494Z  INFO gateway: could not compare the chain ids of --redirect-queries and the worker; continuing without the check worker="error sending request: client error (Connect): tcp connect error: Connection refused (os error 111)" query="error sending request: client error (Connect): dns error: dns lookup failed: failed to lookup address information: Name or service not known" 
2026-11-17T19:42:23.818585Z  INFO gateway::readiness: upstream worker not ready since startup worker_id=0 upstream=http://127.0.0.1:18545 readiness=http://127.0.0.1:18551 cause=connection error (connect)
2026-11-17T19:42:28.824849Z  WARN gateway::proxy: forwarding to upstream failed err=UpstreamUnreachable route="query" upstream=http://rpc.l2-smoke.invalid:8545 cause=error sending request: client error (Connect): dns error: dns lookup failed: failed to lookup address information: Name or service not known suppressed=0
2026-11-17T19:42:43.818360Z  WARN gateway::proxy: warnings suppressed since the last line site="forward_failure_query" suppressed=1
2026-11-17T19:43:18.923233Z  WARN gateway::proxy: forwarding to upstream failed err=UpstreamUnreachable route="query" upstream=http://rpc.l2-smoke.invalid:8545 cause=error sending request: client error (Connect): dns error: dns lookup failed: failed to lookup address information: Name or service not known suppressed=0
--- ss listeners
LISTEN 0      128        127.0.0.1:9655       0.0.0.0:*   
LISTEN 0      128        127.0.0.1:8655       0.0.0.0:*   
LISTEN 0      128        127.0.0.1:8656       0.0.0.0:*   
rm rc=0
--- docker ps -a | grep l2-img-gw-smoke:
0
end=2026-11-17T19:43:19Z
```
Findings: the process stays up for the full 60 s (running, exit 0, 0 restarts) and binds all three listeners;
`/health` = 200 (empty body) on both listeners; `/ready` = 503 `{"ready":false}` and `/ready/any` = 503
`{"ready":false,"submissions":false,"queries":false}`; POST eth_blockNumber and tn_nodeMode both = HTTP 502
`{"error":{"code":-32001,"message":"upstream unreachable"},"id":1,"jsonrpc":"2.0"}` in under 1 ms (both go the
`route="query"` path to the --redirect-queries target, DNS failure; the second log line is rate-suppressed);
metrics 200. So a unit that is enabled and started while the node is down comes up live-but-not-ready and does not
crash-loop. Container removed (`docker rm -f`), `docker ps -a` shows no l2-img-gw-smoke.
