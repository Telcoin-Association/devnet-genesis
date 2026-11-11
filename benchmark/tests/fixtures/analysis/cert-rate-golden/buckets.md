# Certification rate

Logs: bench-validator-01 (bench-validator-01-telcoin.log.gz), bench-validator-02 (bench-validator-02-telcoin.log.gz).

- own cert % / own leader %: fair share is 100 / committee size; "not committed %" is own certificates formed in the window that the node never logged as committed (the default-filter proxy for orphans; see tools/ANALYSIS.md).

## 2026-10-06T06:00Z: 2026-10-06T06:00:00Z → 2026-10-06T06:10:00Z (600 s)

| node | authority | proposed | quorum | rate % | re-proposals | vote errors | canceled | could not form | subdags | certs committed | own cert % | own leader % | not committed % |
|------|-----------|---------:|-------:|-------:|-------------:|------------:|---------:|---------------:|--------:|----------------:|-----------:|-------------:|----------------:|
| bench-validator-01 | A1aaaaaa | 2 | 2 | 100.0 | 1 | 2 | 1 | 0 | 1 | 3 | 66.7 | 100.0 | 0.0 |
| bench-validator-02 | B2bbbbbb | 3 | 0 | 0.0 | 0 | 0 | 0 | 2 | 1 | 3 | 33.3 | 0.0 | – |
| **fleet** | | 5 | 2 | 40.0 | 1 | 2 | 1 | 2 | 2 | 3 | – | – | – |

Committee seen committing in this window: 2 authorities (fair share 50.0 %).

## 2026-10-06T06:10Z: 2026-10-06T06:10:00Z → 2026-10-06T06:20:00Z (600 s)

| node | authority | proposed | quorum | rate % | re-proposals | vote errors | canceled | could not form | subdags | certs committed | own cert % | own leader % | not committed % |
|------|-----------|---------:|-------:|-------:|-------------:|------------:|---------:|---------------:|--------:|----------------:|-----------:|-------------:|----------------:|
| bench-validator-01 | A1aaaaaa | 2 | 1 | 50.0 | 0 | 0 | 0 | 0 | 1 | 3 | 0.0 | 0.0 | 100.0 |
| bench-validator-02 | B2bbbbbb | 1 | 1 | 100.0 | 0 | 0 | 0 | 0 | 1 | 3 | 100.0 | 100.0 | 0.0 |
| **fleet** | | 3 | 2 | 66.7 | 0 | 0 | 0 | 0 | 2 | 3 | – | – | – |

Committee seen committing in this window: 1 authorities (fair share 100.0 %).

