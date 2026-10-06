# Nearest validators by UDP RTT — layout `old`

run 20261006T175053Z · probe VMs e2-small · 5 zones

Validators (10): us-west2-a, us-west2-a, australia-southeast1-c, australia-southeast1-c, northamerica-northeast1-b, northamerica-northeast1-b, europe-west4-a, europe-west4-a, europe-west2-b, europe-west2-b

With 10 validators (f = 3) a quorum is 2f+1 = 7 votes: a validator's own vote plus 6 from peers, so its 6th-nearest peer bounds the vote round trip. The 5th and 6th nearest are shown.

Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost). `†` = two validators in one zone; intra-zone RTT was not measured and is assumed to be 1.00 ms.

| zone | validators | 5th nearest | 6th nearest |
|---|---:|---|---|
| us-west2-a | 2 | 136.55 (europe-west2-b) | 137.85 (australia-southeast1-c) |
| australia-southeast1-c | 2 | 232.83 (northamerica-northeast1-b) | 314.00 (europe-west2-b) |
| northamerica-northeast1-b | 2 | 107.63 (europe-west4-a) | 111.06 (europe-west2-b) |
| europe-west4-a | 2 | 107.63 (northamerica-northeast1-b) | 148.78 (us-west2-a) |
| europe-west2-b | 2 | 111.06 (northamerica-northeast1-b) | 136.55 (us-west2-a) |

## Every zone, ascending

- **us-west2-a** (x2): us-west2-a 1.00† · northamerica-northeast1-b 75.11 · northamerica-northeast1-b 75.11 · europe-west2-b 136.55 · europe-west2-b 136.55 · australia-southeast1-c 137.85 · australia-southeast1-c 137.85 · europe-west4-a 148.78 · europe-west4-a 148.78
- **australia-southeast1-c** (x2): australia-southeast1-c 1.00† · us-west2-a 137.85 · us-west2-a 137.85 · northamerica-northeast1-b 232.83 · northamerica-northeast1-b 232.83 · europe-west2-b 314.00 · europe-west2-b 314.00 · europe-west4-a 314.93 · europe-west4-a 314.93
- **northamerica-northeast1-b** (x2): northamerica-northeast1-b 1.00† · us-west2-a 75.11 · us-west2-a 75.11 · europe-west4-a 107.63 · europe-west4-a 107.63 · europe-west2-b 111.06 · europe-west2-b 111.06 · australia-southeast1-c 232.83 · australia-southeast1-c 232.83
- **europe-west4-a** (x2): europe-west4-a 1.00† · europe-west2-b 13.15 · europe-west2-b 13.15 · northamerica-northeast1-b 107.63 · northamerica-northeast1-b 107.63 · us-west2-a 148.78 · us-west2-a 148.78 · australia-southeast1-c 314.93 · australia-southeast1-c 314.93
- **europe-west2-b** (x2): europe-west2-b 1.00† · europe-west4-a 13.15 · europe-west4-a 13.15 · northamerica-northeast1-b 111.06 · northamerica-northeast1-b 111.06 · us-west2-a 136.55 · us-west2-a 136.55 · australia-southeast1-c 314.00 · australia-southeast1-c 314.00

Slowest validator's 6th-nearest: **314.00 ms** (australia-southeast1-c); median over validators 137.85 ms; slowest 5th-nearest 232.83 ms.
