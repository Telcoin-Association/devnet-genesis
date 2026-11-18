# setup-observability.sh scrapes neither the worker gateway's metrics nor the P2P allowlist's counters and sync timer

The observability setup collects the node's metrics and logs, but nothing from the two components a mainnet validator adds: the worker gateway and the committee P2P allowlist.
Every operator who monitors a validator with these scripts meets it: a stalled allowlist sync or a gateway refusing traffic shows nowhere.

## What happens

The setting is a devnet in mainnet shape: four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis.

Three sources have no native scrape:

- The worker gateway serves `GET /metrics` when started with `--metrics <addr>` (`WORKER_GATEWAY_METRICS_ADDR`; unset means no listener). Its series are `tn_worker_gateway_*`, for example `tn_worker_gateway_upstream_ready{worker_id,upstream}` and the in-flight gauges.
- The allowlist's nftables counters: `firewall-setup.sh --p2p-committee status` prints them (`accept=177128 drop=992` on validator-1-devnet 16 minutes after `on`), but no exporter reads them.
- The allowlist's sync: `telcoin-p2p-allow-sync.timer` and its service run `tn-p2p-allow-sync`; a failed or late run is visible only in the journal and in `status`.

So the drop rate of the allowlist, the age of its last good sync and the gateway's upstream readiness are not on any dashboard or alert.

## Evidence

- The gap was named in the run's plan; there is no run evidence of a missed incident (row 13 of the run's challenge list, open).
- Read from code: `git grep -c` for `worker_gateway`, `nft`, `p2p-allow` and `p2p_allow` in `setup-observability.sh` and `lib/observability.sh` finds nothing at either ref.
- The gateway's metrics flag and series: devnet-genesis fact sheet `tasks/l2/facts/gateway-binary.md` (lines 53, 76-77, 196-198), from the telcoin-network source; taken from the sheet, not re-read.
- The allowlist units: fact sheet `tasks/l2/facts/tnd-firewall.md` line 61 (`firewall-setup.sh:65-67` on `main`); taken from the sheet.
- The counter values: live run 2026-11-18 02:44Z on validator-1-devnet (row 72).

## Where in the code

The allowlist part is on `origin/main` 2813343 (scripts 2.1.0) and on PR #68's head 79fb24e (scripts 2.2.0); the gateway part concerns PR #68's new gateway setup, since `main` has none.

- `setup-observability.sh` and `lib/observability.sh`: no target, job or log source for the gateway or the allowlist at either ref (grep above; the files were not read in full).

## What is not known

- Whether the gateway's setup in PR #68 passes `--metrics` at all; if not, there is nothing to scrape yet.
- Which collector the observability stack would use for nftables counters (a textfile written by the sync tool, or an nftables exporter).

## What could be done (suggestions, none tried)

- Start the gateway with `--metrics 127.0.0.1:<port>` and add that port to the node host's scrape list.
- Have `tn-p2p-allow-sync` write its counters and last-sync time to a textfile the existing collector reads, and alert when the last good sync is older than a few timer periods.

## Related

- {{allowlist-status-hides-sources}}: the same counters, which name no source.
- {{fresh-install-false-alarms}}: noise from the same observability setup.
- PR #68 adds the gateway without a scrape.
