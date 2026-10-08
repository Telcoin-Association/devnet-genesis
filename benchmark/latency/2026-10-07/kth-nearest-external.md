# Nearest zones by UDP RTT — external IPs

run 20261007T025234Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

For each zone, the other zones in this table ordered by UDP echo RTT (ms). The 5th and 6th nearest set the vote-quorum window for a 10-validator committee with one validator per zone. Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost).

| zone | 5th nearest | 6th nearest |
|---|---|---|
| us-west2-a | 139.02 (australia-southeast1-c) | 144.01 (asia-east2-a) |
| europe-west2-b | 168.68 (asia-southeast1-b) | 204.69 (asia-east2-a) |
| australia-southeast1-c | 151.36 (asia-southeast1-b) | 208.65 (asia-south1-c) |
| asia-northeast1-b | 106.87 (australia-southeast1-c) | 133.57 (asia-south1-c) |
| northamerica-northeast1-b | 198.92 (asia-east2-a) | 201.52 (asia-northeast3-a) |
| europe-west4-a | 166.18 (asia-southeast1-b) | 195.83 (asia-east2-a) |
| asia-southeast1-b | 151.36 (australia-southeast1-c) | 166.18 (europe-west4-a) |
| asia-east2-a | 122.33 (australia-southeast1-c) | 144.01 (us-west2-a) |
| asia-northeast3-a | 127.93 (us-west2-a) | 128.26 (australia-southeast1-c) |
| asia-south1-c | 149.31 (europe-west2-b) | 151.47 (europe-west4-a) |

## Every zone, ascending

- **us-west2-a**: northamerica-northeast1-b 75.21 · asia-northeast1-b 101.11 · asia-northeast3-a 127.93 · europe-west2-b 137.72 · australia-southeast1-c 139.02 · asia-east2-a 144.01 · europe-west4-a 149.48 · asia-southeast1-b 169.32 · asia-south1-c 218.91
- **europe-west2-b**: europe-west4-a 10.72 · northamerica-northeast1-b 78.94 · us-west2-a 137.72 · asia-south1-c 149.31 · asia-southeast1-b 168.68 · asia-east2-a 204.69 · asia-northeast1-b 237.62 · asia-northeast3-a 265.41 · australia-southeast1-c 276.15
- **australia-southeast1-c**: asia-northeast1-b 106.87 · asia-east2-a 122.33 · asia-northeast3-a 128.26 · us-west2-a 139.02 · asia-southeast1-b 151.36 · asia-south1-c 208.65 · northamerica-northeast1-b 213.35 · europe-west2-b 276.15 · europe-west4-a 320.56
- **asia-northeast1-b**: asia-northeast3-a 33.57 · asia-east2-a 50.32 · asia-southeast1-b 75.19 · us-west2-a 101.11 · australia-southeast1-c 106.87 · asia-south1-c 133.57 · northamerica-northeast1-b 175.38 · europe-west2-b 237.62 · europe-west4-a 249.83
- **northamerica-northeast1-b**: us-west2-a 75.21 · europe-west2-b 78.94 · europe-west4-a 86.58 · asia-northeast1-b 175.38 · asia-east2-a 198.92 · asia-northeast3-a 201.52 · australia-southeast1-c 213.35 · asia-south1-c 225.00 · asia-southeast1-b 233.25
- **europe-west4-a**: europe-west2-b 10.72 · northamerica-northeast1-b 86.58 · us-west2-a 149.48 · asia-south1-c 151.47 · asia-southeast1-b 166.18 · asia-east2-a 195.83 · asia-northeast3-a 228.10 · asia-northeast1-b 249.83 · australia-southeast1-c 320.56
- **asia-southeast1-b**: asia-east2-a 32.98 · asia-south1-c 62.09 · asia-northeast3-a 69.35 · asia-northeast1-b 75.19 · australia-southeast1-c 151.36 · europe-west4-a 166.18 · europe-west2-b 168.68 · us-west2-a 169.32 · northamerica-northeast1-b 233.25
- **asia-east2-a**: asia-southeast1-b 32.98 · asia-northeast3-a 37.02 · asia-northeast1-b 50.32 · asia-south1-c 87.79 · australia-southeast1-c 122.33 · us-west2-a 144.01 · europe-west4-a 195.83 · northamerica-northeast1-b 198.92 · europe-west2-b 204.69
- **asia-northeast3-a**: asia-northeast1-b 33.57 · asia-east2-a 37.02 · asia-southeast1-b 69.35 · asia-south1-c 122.57 · us-west2-a 127.93 · australia-southeast1-c 128.26 · northamerica-northeast1-b 201.52 · europe-west4-a 228.10 · europe-west2-b 265.41
- **asia-south1-c**: asia-southeast1-b 62.09 · asia-east2-a 87.79 · asia-northeast3-a 122.57 · asia-northeast1-b 133.57 · europe-west2-b 149.31 · europe-west4-a 151.47 · australia-southeast1-c 208.65 · us-west2-a 218.91 · northamerica-northeast1-b 225.00
