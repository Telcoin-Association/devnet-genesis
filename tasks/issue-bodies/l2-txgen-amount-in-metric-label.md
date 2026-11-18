# The transaction generator puts the transfer amount in its metrics' type label, so every transaction is a new series

The generator labels each transaction with a string that ends in its amount, for example `native_transfer:62744256131388wei`, and uses that string as the `type` label of its Prometheus metrics.
Whoever runs the generator with a metrics scrape meets it: series grow with every transaction, in the generator's memory and in Prometheus.

## What happens

The setting is a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis) with the generator sending native transfers through the public RPC node.

25 minutes after the generator started, its metrics endpoint served 7,930 lines beginning `txgen_`, with labels such as:

```
type="native_transfer:62744256131388wei"
```

Each transfer has its own amount, so each one opens a new series. Nothing bounds the count: it grows for as long as the generator runs, in the generator's registry and in every Prometheus that scrapes it.

The same per-transaction string appears as the `label` field of the generator's logs (`native_transfer:41932599727859wei`, and `faucet_drip:native:635271581257683523wei` for faucet drips), which suggests one string feeds both; that is inferred, not read from code.

## Evidence

- `curl 127.0.0.1:9090/metrics` on txgen-devnet (the generator's host), 2026-11-18 02:21:56 UTC: 7,930 `txgen_` lines and the label above (row 62 of the run's challenge list; taken from the row, the output was not re-read).
- Log labels: devnet-genesis `tasks/l2/w3/d3b/s17-19.log` lines 9192-9193 (`native_transfer:<amount>wei`) and `tasks/l2/w3/d3b/s17-19-excerpts.txt` (log line 9197, `faucet_drip:native:<amount>wei`), checked.
- Seen in one run.

## What is not known

- The generator's source is not on the host this was written from, so "Where in the code" is left out: which metric families carry `type`, and where the label is built.
- Whether the other kinds of transaction (contract calls, faucet drips) carry an amount in `type` too; the faucet's log label does.

## What could be done (suggestions, none tried)

- Keep `type` to the kind of transaction (`native_transfer`, `faucet_drip_native`, …) and record amounts in a histogram or a counter of wei sent.
- Keep the amount in the log line only.

## Related

- {{txgen-faucet-drip-reverts}}: the same generator, same run.
