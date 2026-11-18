# A fresh install warns twice that committee members cannot be counted, and install-ui.sh prints a curl error first

Two separate false alarms on every host of a new chain: `setup-observability.sh` warns, twice, that it could not count the committee members that are down, and `install-ui.sh` prints a `curl: (7)` error just before it reports the UI answering.
The launch team meets both at genesis, on every host, beside the warnings that matter. They could be filed apart; they share a cause (a probe that runs before its target can answer) and a fix pattern.

## What happens

The setting is a devnet in mainnet shape: four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis. The scripts were installed on six hosts before the chain's first start.

Part 1, `setup-observability.sh` (observability step, six hosts). The installer printed, twice per host:

```
[warn] could not count the committee members that are down (the committee could not be read; <public RPC URL> does not answer with chain 32285); going…
```

Before the chain's first start the public RPC URL serves nothing, so the count cannot succeed on a fresh launch. On the step's run over all hosts that followed, it came again twice on each of the five hosts that restarted. The installer's result was `done: ok` everywhere; the warning changed nothing.

Part 2, `install-ui.sh` (UI step, six hosts of six). Each host printed

```
curl: (7) Failed to connect to 127.0.0.1 port 8080 after 0 ms: Couldn't connect to server
```

just before the script's own `✅ … answering on 127.0.0.1:8080`: a first probe before the service listens, shown as an error.

## Evidence

- Part 1: live run, 2026-11-18, about 00:59-01:13 UTC, devnet-genesis `tasks/l2/w3/d3a/as-run.md` lines 15 (canary on validator-1-devnet, "The installer printed twice …") and 17 (all hosts, "The committee-down [warn] again twice per host on the five that restarted"). The URL is replaced by its role here.
- Part 2: live run, UI step on six of six hosts (row 64 of the run's challenge list); the line is taken from the row, its log was not re-read.

## Where in the code

- Part 1: `setup-observability.sh:761` names `tn_committee_down_guard` among the library functions it requires, at `origin/main` 2813343 (scripts 2.1.0) and PR #68's head 79fb24e (scripts 2.2.0). The guard's own lines and the reason it runs twice were not located.
- Part 2: not located. `git grep` for the probe and the `answering on` line in `install-ui.sh` found no match at either ref with the patterns tried, so the message may come from a library function.

Whether `main` prints the same was not run here; the guard is required there too.

## What is not known

- Why the warning prints twice in one run.
- Where `install-ui.sh`'s first probe is, and whether its stderr is shown on purpose.

## What could be done (suggestions, none tried)

- Part 1: skip the count, with one info line, when the chain has not started (no block from the node itself, or the public RPC refusing the connection), and print the warning once.
- Part 2: run the readiness probe with `curl -s` (or stderr to `/dev/null`) inside its retry loop, and print an error only when the last attempt fails.

## Related

- {{observability-scrape-gaps}}: the same observability setup.
- PR #68 does not change the committee-down guard's call (line 761 identical at both refs).
