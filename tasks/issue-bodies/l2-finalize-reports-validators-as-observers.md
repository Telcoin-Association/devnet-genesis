# setup-node.sh's finalize JSON calls every node an observer, including genesis validators it has just read as Active

The `done` event of `setup-node.sh --json` finalize always says `"node_type":"observer"` and "following consensus as a full node; staking to validate is optional", whatever the on-chain check a few lines earlier found.
Every genesis validator operator reads it at install time, and a tool that reads the JSON gets a role the script has just seen to be wrong.

## What happens

On validator-1-devnet, a genesis validator, finalize printed:

```
>>> Checking validator on-chain status...
  [OK]  Status: Active (participating in consensus)
  ...
    json: {"event":"done","ok":true,"phase":"finalize","node_type":"observer","service":"telcoin","rpc_port":"8545",...
```

The same event carries the fixed message `"${SERVICE_NAME} finalized and started -- following consensus as a full node; staking to validate is optional (see docs)"`.
All six hosts got `"node_type":"observer"`: the four genesis validators, all `Status: Active`, a fifth node not yet staked and the public RPC node. For the last two the text fits.

The script's own comment says the value is deliberate: "Setup records no role: .node-meta carries no NODE_TYPE, and the "node_type":"observer" in the --json done events is only the Node Manager UI's presentation slot."
Neither the operator reading the message nor a JSON reader is told that.

## Evidence

- Live run on 2026-11-18, finalize on six hosts from 00:42 to 00:56 UTC, on a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis).
- validator-1-devnet: devnet-genesis `tasks/l2/w3/d3a/s10-canary-node1.log:81` (check), `:86` (`Status: Active`), `:100` (the JSON).
- The other five: `tasks/l2/w3/d3a/as-run.md:9` ("every host's closing JSON says `"node_type":"observer"` (5 of 5, validators included)"); `Status: Active` for other validators in `tasks/l2/w3/d3a/s10-only10.log:100` and `:190`.
- The message text is read from code; the logged JSON line was read only up to `host_baseline`.

## Where in the code

The same lines at `origin/main` (2813343) and PR #68's head (79fb24e); PR #68 does not change them.

- `setup-node.sh:3581`: the finalize `json_done` with the fixed `node_type` and `msg`.
- `setup-node.sh:3392`: the keygen `done` event, also `"node_type":"observer"`.
- `setup-node.sh:3231`: the plain-text path, "Your node is set up and will follow consensus as a full node."
- `setup-node.sh:222-226`: the comment quoted above.
- `lib/common.sh:5529` `print_validator_onchain_status` prints `Status: ${status_label}` (`:5631`); the "Checking validator on-chain status..." step is at `:5663`.
  Its header says `check-node.sh` and `update-node.sh` grep these labels, so they are stable.

## What is not known

- What the Node Manager UI does with `node_type` beyond choosing a view (PR #68's `ui/server.py:3205` routes `/api/status/<node_type>`; not read further).
- Whether any other tool reads the field.
- Whether finalize keeps the status it read in a variable the closing message could use (not read).

## What could be done (suggestions, none tried)

- Build the closing message from the status the script has just read: "Active, participating in consensus" for an active validator, the current text when no validator record exists.
- Add a field such as `"onchain_status":"Active"` to the `done` event, keep `node_type` for the UI, and say in the JSON contract that `node_type` is a UI slot, not the node's role.

## Related

- {{scripts-start-stopped-node}}: the same message says "started"; on the devnet finalize ran staged and the node was stopped again right after.
