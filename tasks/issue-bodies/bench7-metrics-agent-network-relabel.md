# The metrics agent overwrites the node's own `network` label, so some nodes lose one remote-write batch per scrape

## What happens

`observability/config.alloy` sets `network` to the chain's name on every series it scrapes from the node (lines 126-129 on main; the file last changed in af97ae7):

```alloy
	rule {
		target_label = "network"
		replacement  = sys.env("TN_CHAIN")
	}
```

The node already sets its own `network` label, `primary` or `worker-0`, on its per-network series.
Once the rule replaces it, about 910 pairs of series share one label set and timestamp, about 110 of them with different values (the `tn_network_*` per-network counters).
On every node those pairs collapse into one series in Prometheus, so no per-network figure can be read there.
On some nodes the remote write also has one batch rejected on every scrape, and the series in that batch are missing from Prometheus while that lasts: on one validator for a whole run, on others from mid-run, on one only for three scrapes at start-up.

What it costs: on three bench fleets on 2026-11-15, series were missing from healthy validators, `up` among them.
The benchmark's idle check stops its step sequence before the blast when a node's `up` is missing; it did so on all three fleets, each time on nodes that were otherwise healthy, and each blast was then launched by hand.
Figures taken from Prometheus covered fewer validators.

## What was read on a live node

On validator-09 during [r20261115-1131](https://benchmark.telcoin.network/runs/r20261115-1131/), the agent ran this configuration: scrape the node, set `network` to the chain's name, remote-write.
Its remote write logged a rejected batch on every scrape: `duplicate sample for timestamp …; overrides not allowed: existing 0, new value 1`.
It lost about 737 samples every 15 s, 102,244 of 658,244 (15.5 %).
Restarting the agent at 12:37:50 changed nothing.
On validator-08 a batch was rejected three times at start-up and then never.

## What was measured on the three fleets

The fleets of r20261115-1131, of an earlier, lost attempt at the adaptive run (r20261115-1450, not published), and of [r20261115-1653](https://benchmark.telcoin.network/runs/r20261115-1653/); one run each, times in UTC.

| run | node | missing from Prometheus | when |
|---|---|---|---|
| r20261115-1131 | validator-09 | `up`, `scrape_*` and thirteen more series (engine root, executor output transactions, vote stage, uncertified-report drops, persist save, the consensus store's write stall, worker batch, reth provider and trie series) | whole run |
| earlier attempt | validators 01, 05, 09, 10 | 01 and 05 three of the benchmark's must-have series each, 09 two; 09 and 10 `up` | idle phase |
| r20261115-1653 | validator-01 | four series, among them `tn_engine_persist_duration_seconds` and the consensus store's write stall | whole run |
| r20261115-1653 | validator-05 | `up`, `tn_reth_persist_save_blocks_seconds`, `tn_executor_output_transactions` | until 18:40:00; whole after its restart |
| r20261115-1653 | validator-08 | `tn_engine_queue_wait_seconds`, `tn_executor_output_transactions`, its write stall and three other executor or reth series | stop at 18:29:45 |
| r20261115-1653 | observer | save, commit, persist-duration and write-stall series | stop at 18:58:45 |

The idle check stopped the benchmark's step sequence (the blockchain kept running) at 12:30:02 (`up` missing for validator-09), at 16:04:23 (the earlier attempt; `up` missing for validators 09 and 10) and at 17:45:57 (`up` missing for validator-05).
Validator-05 is killed and restarted by design in the load blast; its missing series came back after the restart.
The collapsed per-network series were seen on every node in both runs, nodes that lost no batch included, and are not new in bench 7.

## The explanation (inferred, not reproduced)

Inside one remote-write request, Prometheus drops the second sample of such a pair silently.
When a pair with different values straddles the boundary between two 2,000-sample batches (the file's `prometheus.remote_write` block sets no queue options), the later request meets a sample already committed with another value, and Prometheus rejects that whole batch, on every scrape.
Which batch is hit depends on the order in which the node process exposes its series, hash order per process, so it changes when the node restarts and not when the agent does.
That fits validator-05's series coming back after its restart, and validator-09's agent restart changing nothing.
A series the node registers mid-run can move the boundary, which would fit the series that stop mid-run.

## What stood in

The node's own metrics endpoint keeps its `network` label, so both series of each pair are there.
In r20261115-1653 each node's endpoint was read every 60 s (94 rounds, about 5,100 series a node); in r20261115-1131 only end-of-run snapshots of validators 09 and 08 exist.
Where Prometheus held a validator whole in r20261115-1653, the engine figures taken from the samples (executed transactions per second, busy time, persist mean) agreed with it within about 1 % over whole windows and up to about 5 % in 300 s buckets; a gauge's average and the vote stage's wait means did not agree as well.

## A suggested fix (not tested)

Keep the node's value under another name before the `network` rule overwrites it, for example:

```alloy
	rule {
		source_labels = ["network"]
		target_label  = "tn_network"
	}
```

With the default `replace` action (regex `(.*)`, replacement `$1`) this should copy `primary` or `worker-0` to `tn_network`; for a series without a `network` label the result is empty, and as we read Prometheus's relabelling an empty result sets no label (not tested).
`network` still carries the chain's name, so the dashboard's `$network` variable (the comment at lines 104-105) and queries on `network="<chain>"` keep working.

The other way is to drop the `network` rule and keep the node's label.
The `chain` rule just above it (lines 121-124) already writes the same value, `sys.env("TN_CHAIN")`.
The dashboard's variable and every query that selects the chain by `network`, such as the benchmark harness's `network="bench"` selectors, would then have to move to `chain`.

Either way the file's functional blocks are kept byte-identical with an upstream copy (the sync note in `docs/testnet-addons.md`), so the change goes there too.

## How to verify

On a node with the change, the agent logs no `duplicate sample for timestamp` error, and Prometheus holds each `tn_network_*` counter once per network, as the node's own endpoint does.
