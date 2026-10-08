# Nearest validators by UDP RTT — layout `final`

run 20261006T175053Z · probe VMs e2-small · 10 zones

Validators (10): us-west2-a, europe-west2-b, australia-southeast1-c, asia-northeast1-b, northamerica-northeast1-b, europe-west4-a, asia-southeast1-b, asia-east2-a, asia-northeast3-a, asia-south1-a

With 10 validators (f = 3) a quorum is 2f+1 = 7 votes: a validator's own vote plus 6 from peers, so its 6th-nearest peer bounds the vote round trip. The 5th and 6th nearest are shown.

Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost).

| zone | validators | 5th nearest | 6th nearest |
|---|---:|---|---|
| us-west2-a | 1 | 137.85 (australia-southeast1-c) | 143.36 (asia-east2-a) |
| europe-west2-b | 1 | 166.40 (asia-southeast1-b) | 200.13 (asia-east2-a) |
| australia-southeast1-c | 1 | 174.15 (asia-southeast1-b) | 231.03 (asia-south1-a) |
| asia-northeast1-b | 1 | 117.03 (australia-southeast1-c) | 120.67 (asia-south1-a) |
| northamerica-northeast1-b | 1 | 199.51 (asia-northeast3-a) | 223.15 (asia-south1-a) |
| europe-west4-a | 1 | 163.94 (asia-southeast1-b) | 197.20 (asia-east2-a) |
| asia-southeast1-b | 1 | 163.88 (us-west2-a) | 163.94 (europe-west4-a) |
| asia-east2-a | 1 | 143.36 (us-west2-a) | 151.35 (australia-southeast1-c) |
| asia-northeast3-a | 1 | 126.77 (us-west2-a) | 127.68 (australia-southeast1-c) |
| asia-south1-a | 1 | 149.11 (europe-west2-b) | 152.08 (europe-west4-a) |

## Every zone, ascending

- **us-west2-a** (x1): northamerica-northeast1-b 75.11 · asia-northeast1-b 100.31 · asia-northeast3-a 126.77 · europe-west2-b 136.55 · australia-southeast1-c 137.85 · asia-east2-a 143.36 · europe-west4-a 148.78 · asia-southeast1-b 163.88 · asia-south1-a 216.27
- **europe-west2-b** (x1): europe-west4-a 13.15 · northamerica-northeast1-b 111.06 · us-west2-a 136.55 · asia-south1-a 149.11 · asia-southeast1-b 166.40 · asia-east2-a 200.13 · asia-northeast1-b 257.32 · asia-northeast3-a 261.33 · australia-southeast1-c 314.00
- **australia-southeast1-c** (x1): asia-northeast1-b 117.03 · asia-northeast3-a 127.68 · us-west2-a 137.85 · asia-east2-a 151.35 · asia-southeast1-b 174.15 · asia-south1-a 231.03 · northamerica-northeast1-b 232.83 · europe-west2-b 314.00 · europe-west4-a 314.93
- **asia-northeast1-b** (x1): asia-northeast3-a 32.45 · asia-east2-a 54.51 · asia-southeast1-b 66.38 · us-west2-a 100.31 · australia-southeast1-c 117.03 · asia-south1-a 120.67 · northamerica-northeast1-b 170.08 · europe-west2-b 257.32 · europe-west4-a 260.22
- **northamerica-northeast1-b** (x1): us-west2-a 75.11 · europe-west4-a 107.63 · europe-west2-b 111.06 · asia-northeast1-b 170.08 · asia-northeast3-a 199.51 · asia-south1-a 223.15 · asia-east2-a 224.48 · australia-southeast1-c 232.83 · asia-southeast1-b 251.00
- **europe-west4-a** (x1): europe-west2-b 13.15 · northamerica-northeast1-b 107.63 · us-west2-a 148.78 · asia-south1-a 152.08 · asia-southeast1-b 163.94 · asia-east2-a 197.20 · asia-northeast3-a 231.96 · asia-northeast1-b 260.22 · australia-southeast1-c 314.93
- **asia-southeast1-b** (x1): asia-east2-a 30.72 · asia-south1-a 58.59 · asia-northeast1-b 66.38 · asia-northeast3-a 70.63 · us-west2-a 163.88 · europe-west4-a 163.94 · europe-west2-b 166.40 · australia-southeast1-c 174.15 · northamerica-northeast1-b 251.00
- **asia-east2-a** (x1): asia-southeast1-b 30.72 · asia-northeast3-a 37.47 · asia-northeast1-b 54.51 · asia-south1-a 88.16 · us-west2-a 143.36 · australia-southeast1-c 151.35 · europe-west4-a 197.20 · europe-west2-b 200.13 · northamerica-northeast1-b 224.48
- **asia-northeast3-a** (x1): asia-northeast1-b 32.45 · asia-east2-a 37.47 · asia-southeast1-b 70.63 · asia-south1-a 120.71 · us-west2-a 126.77 · australia-southeast1-c 127.68 · northamerica-northeast1-b 199.51 · europe-west4-a 231.96 · europe-west2-b 261.33
- **asia-south1-a** (x1): asia-southeast1-b 58.59 · asia-east2-a 88.16 · asia-northeast1-b 120.67 · asia-northeast3-a 120.71 · europe-west2-b 149.11 · europe-west4-a 152.08 · us-west2-a 216.27 · northamerica-northeast1-b 223.15 · australia-southeast1-c 231.03

Slowest validator's 6th-nearest: **231.03 ms** (australia-southeast1-c); median over validators 158.01 ms; slowest 5th-nearest 199.51 ms.
