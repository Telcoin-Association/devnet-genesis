# Nearest validators by UDP RTT — layout `final`

run 20261007T025234Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

Validators (10): us-west2-a, europe-west2-b, australia-southeast1-c, asia-northeast1-b, northamerica-northeast1-b, europe-west4-a, asia-southeast1-b, asia-east2-a, asia-northeast3-a, asia-south1-c

With 10 validators (f = 3) a quorum is 2f+1 = 7 votes: a validator's own vote plus 6 from peers, so its 6th-nearest peer bounds the vote round trip. The 5th and 6th nearest are shown.

Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost).

| zone | validators | 5th nearest | 6th nearest |
|---|---:|---|---|
| us-west2-a | 1 | 137.94 (australia-southeast1-c) | 143.14 (asia-east2-a) |
| europe-west2-b | 1 | 167.40 (asia-southeast1-b) | 200.40 (asia-east2-a) |
| australia-southeast1-c | 1 | 165.74 (asia-southeast1-b) | 233.51 (northamerica-northeast1-b) |
| asia-northeast1-b | 1 | 111.44 (australia-southeast1-c) | 123.98 (asia-south1-c) |
| northamerica-northeast1-b | 1 | 200.53 (asia-northeast3-a) | 224.62 (asia-south1-c) |
| europe-west4-a | 1 | 162.98 (asia-southeast1-b) | 197.85 (asia-east2-a) |
| asia-southeast1-b | 1 | 162.98 (europe-west4-a) | 165.74 (australia-southeast1-c) |
| asia-east2-a | 1 | 143.14 (us-west2-a) | 151.54 (australia-southeast1-c) |
| asia-northeast3-a | 1 | 127.03 (us-west2-a) | 127.70 (australia-southeast1-c) |
| asia-south1-c | 1 | 142.70 (europe-west2-b) | 147.22 (europe-west4-a) |

## Every zone, ascending

- **us-west2-a** (x1): northamerica-northeast1-b 74.56 · asia-northeast1-b 100.58 · asia-northeast3-a 127.03 · europe-west2-b 137.26 · australia-southeast1-c 137.94 · asia-east2-a 143.14 · europe-west4-a 149.20 · asia-southeast1-b 165.78 · asia-south1-c 221.83
- **europe-west2-b** (x1): europe-west4-a 10.86 · northamerica-northeast1-b 100.31 · us-west2-a 137.26 · asia-south1-c 142.70 · asia-southeast1-b 167.40 · asia-east2-a 200.40 · asia-northeast1-b 253.68 · asia-northeast3-a 262.61 · australia-southeast1-c 287.87
- **australia-southeast1-c** (x1): asia-northeast1-b 111.44 · asia-northeast3-a 127.70 · us-west2-a 137.94 · asia-east2-a 151.54 · asia-southeast1-b 165.74 · northamerica-northeast1-b 233.51 · asia-south1-c 241.13 · europe-west2-b 287.87 · europe-west4-a 312.44
- **asia-northeast1-b** (x1): asia-northeast3-a 32.99 · asia-east2-a 57.88 · asia-southeast1-b 66.74 · us-west2-a 100.58 · australia-southeast1-c 111.44 · asia-south1-c 123.98 · northamerica-northeast1-b 166.72 · europe-west2-b 253.68 · europe-west4-a 259.35
- **northamerica-northeast1-b** (x1): us-west2-a 74.56 · europe-west2-b 100.31 · europe-west4-a 101.32 · asia-northeast1-b 166.72 · asia-northeast3-a 200.53 · asia-south1-c 224.62 · asia-east2-a 224.76 · australia-southeast1-c 233.51 · asia-southeast1-b 254.29
- **europe-west4-a** (x1): europe-west2-b 10.86 · northamerica-northeast1-b 101.32 · asia-south1-c 147.22 · us-west2-a 149.20 · asia-southeast1-b 162.98 · asia-east2-a 197.85 · asia-northeast3-a 231.38 · asia-northeast1-b 259.35 · australia-southeast1-c 312.44
- **asia-southeast1-b** (x1): asia-east2-a 30.75 · asia-south1-c 57.57 · asia-northeast1-b 66.74 · asia-northeast3-a 70.60 · europe-west4-a 162.98 · australia-southeast1-c 165.74 · us-west2-a 165.78 · europe-west2-b 167.40 · northamerica-northeast1-b 254.29
- **asia-east2-a** (x1): asia-southeast1-b 30.75 · asia-northeast3-a 36.90 · asia-northeast1-b 57.88 · asia-south1-c 86.73 · us-west2-a 143.14 · australia-southeast1-c 151.54 · europe-west4-a 197.85 · europe-west2-b 200.40 · northamerica-northeast1-b 224.76
- **asia-northeast3-a** (x1): asia-northeast1-b 32.99 · asia-east2-a 36.90 · asia-southeast1-b 70.60 · asia-south1-c 121.99 · us-west2-a 127.03 · australia-southeast1-c 127.70 · northamerica-northeast1-b 200.53 · europe-west4-a 231.38 · europe-west2-b 262.61
- **asia-south1-c** (x1): asia-southeast1-b 57.57 · asia-east2-a 86.73 · asia-northeast3-a 121.99 · asia-northeast1-b 123.98 · europe-west2-b 142.70 · europe-west4-a 147.22 · us-west2-a 221.83 · northamerica-northeast1-b 224.62 · australia-southeast1-c 241.13

Slowest validator's 6th-nearest: **233.51 ms** (australia-southeast1-c); median over validators 158.64 ms; slowest 5th-nearest 200.53 ms.
