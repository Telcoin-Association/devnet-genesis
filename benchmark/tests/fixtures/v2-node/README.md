# v2 node fixture (shared by the bench tests)

The files a tn-node-deployment v2 docker install leaves on a bench node after `devnet-finalize.sh
--stage-only` (unit installed, enabled, stopped), laid out under their absolute paths:

| file | written by (tn-node-deployment at d9446f7) |
|---|---|
| `etc/telcoin/.node-meta` | `write_node_meta` / `meta_set`, setup-node.sh:2504-2534 |
| `etc/telcoin/node.env` | `_tn_node_env_text` (lib/common.sh:3208), via `tn_write_node_env` (setup-node.sh:2451) |
| `usr/local/libexec/telcoin/tn-start-docker` | `_tn_start_script_text` (lib/common.sh:3247-3300; docker line 3283), node arguments from setup-node.sh:2467 |
| `etc/systemd/system/telcoin.service` | `_tn_node_unit_text` (lib/common.sh:3343), docker form |

The three rendered files are the real renderers' output, not hand-typed: lib/common.sh sourced with
`TN_ROOT_PREFIX=<this dir>` (so the renderers read this `.node-meta`), `SERVICE_NAME=telcoin`,
`DEVNET_RPC_URL=http://127.0.0.1:9`, and the library's own fixture overrides `TN_DOCKER_IDS=998:998`
and `TN_MEMINFO` (a MemTotal of 32873892 kB, so `--memory 28893m`); docker client `/usr/bin/docker`.
Each file is the renderer's text plus one newline, as `tn_write_root_file <<< "$text"` writes it.
The start script is what `_tn_start_script_checked docker <image> <args>` prints (it passes `bash -n`
and the launch parser finds its node line), with args
`--datadir /home/nonroot --log.stdout.format log-fmt -vvv --http --http.addr 127.0.0.1 --ws --ws.addr 127.0.0.1`
(setup-node.sh:2467 with an empty launch tail: no add-on is on at finalize; step 8 adds metrics).

Made-up or stand-in values: the image digest (one made-up sha256, on the public repository
`us-docker.pkg.dev/telcoin-network/tn-public/adiri`), the container uid:gid, the memory cap, and the
listener addresses (`/ip4/0.0.0.0/...`, where a real node has its internal NIC address).

`.node-meta` holds only the keys the bench reads or the renderers take, in the order v2 leaves them
(`meta_set` moves a key to the end of the file on every write, so the order is that of each key's last
write). A real file has more keys (the rest of the setup-node.sh:2504 block, CREDENTIAL_KEY,
BOOTSTRAP_PEERS_FILE, STATE_EXPORT). `NODE_LOG_DIR` is here because bench contract C8 lists it; a
docker install does not write it (only a binary install with log shipping does), and the docker
unit ignores it. The node's log is the unit's `StandardOutput=append:/var/log/telcoin/telcoin.log`.

`.gitignore` here re-includes paths named `telcoin`, which the repo root ignores (the node binary).

Used by `benchmark/tests/test_v2_launch_edit.py` (the launch-flag edits of the bench pre-start step)
and by the other bench tests that need a v2 node tree.
