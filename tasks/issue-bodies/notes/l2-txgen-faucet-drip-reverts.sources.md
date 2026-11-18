# Sources: l2-txgen-faucet-drip-reverts

| Item in the draft | Source | Status |
|---|---|---|
| Revert in `eth_estimateGas`, `LowLevelCallFailure(bytes)`, empty data, selector 0x37f33ed8, tn-contracts error; WARN + `outcome="err"` per drip; image without `faucet` (decision 3), cause not verified | `tasks/challenges-l2.md` row 63; report section 4 line 254 ("Every drip is a WARN") | taken from the row, source not re-read |
| Log line: timestamp `2026-11-18T02:15:52.095139Z`, WARN, `tx submit failed`, label `faucet_drip:native:635271581257683523wei`, `fill tx (nonce / gas / 1559 caps)`, `error code 3: execution reverted, data: "0x37f33ed8…0020…` | `grep -nE 'LowLevelCallFailure\|0x37f33ed8' tasks/l2/w3/d3b/s17-19-excerpts.txt` -> line 35 (`9197:` prefix), cut at 400 chars | checked (bytes length word beyond the cut: taken from the row) |
| Selector 0x37f33ed8 = `LowLevelCallFailure(bytes)` | row 63 | not recomputed; taken from the row |
| Generator code, drip target contract/account | source not on this host | not verifiable here |
