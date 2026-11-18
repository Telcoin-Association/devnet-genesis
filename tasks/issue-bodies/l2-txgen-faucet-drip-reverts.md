# The generator's native faucet drip reverts in eth_estimateGas with LowLevelCallFailure on an image without `faucet`

Every native faucet drip the generator tried failed while it filled in gas: the node answered `execution reverted` with the tn-contracts error `LowLevelCallFailure(bytes)` and empty bytes.
Whoever runs the generator with drips against a node built like mainnet meets it; whether the missing `faucet` build feature is the cause is not verified.

## What happens

The setting is a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis). Its node image is built without the `faucet` cargo feature, as mainnet's would be.

The generator logs each drip failure as a WARN, and its metrics count it with `outcome="err"`. One of them, as logged:

```
{"timestamp":"2026-11-18T02:15:52.095139Z","level":"WARN","fields":{"message":"tx submit failed","label":"faucet_drip:native:635271581257683523wei","e":"fill tx (nonce / gas / 1559 caps)\n\nCaused by:\n    server returned an error response: error code 3: execution reverted, data: \"0x37f33ed8000…0020000…
```

- `0x37f33ed8` is the selector of `LowLevelCallFailure(bytes)`, an error defined in tn-contracts; the next word is the offset `0x20` of the bytes argument, and the row records the bytes as empty, so the reverted inner call returned no reason.
- The failure happens in the fill step (nonce, gas, EIP-1559 caps), that is in `eth_estimateGas`, before anything is sent.

## Evidence

- devnet-genesis `tasks/l2/w3/d3b/s17-19-excerpts.txt` line 35, which is line 9197 of the generator's log for the run's steps 17-19, checked (the line is cut above).
- "Each one is logged as a WARN and counted `outcome="err"`", the empty bytes, and `eth_estimateGas` as the call: row 63 of the run's challenge list, open; taken from the row, not re-read.
- The image built without `faucet`: the run's plan decision, as row 63 states it. Whether that is the cause is not verified.
- Seen in one run.

## What is not known

- The generator's source is not on the host this was written from, so "Where in the code" is left out: which contract and function the drip calls, and from which account.
- Whether the revert is caused by the missing `faucet` feature (for example a faucet precompile or contract the drip calls through that the image does not provide) or by something else, such as the faucet's balance or role. Not verified.
- The selector-to-error mapping is taken from the row; it was not recomputed here.

## What could be done (suggestions, none tried)

- In the generator: check at start that the faucet path exists on the target chain (one `eth_call`), and turn drips off with one clear line when it does not, rather than a WARN per drip.
- In the generator's logs: decode known tn-contracts errors, so the line says `LowLevelCallFailure("")` instead of raw data.
- To settle the cause: send the same drip against an image built with `faucet`, or trace the call (`debug_traceCall`) on this chain.

## Related

- {{txgen-amount-in-metric-label}}: the same generator and run; the drip's label carries the amount too.
- tn-contracts defines the error; telcoin-network's `faucet` feature is the suspected cause (not verified).
