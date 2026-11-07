# Nearest zones by UDP RTT

run 20261107T145111Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

For each zone, the other zones in this table ordered by UDP echo RTT (ms). The 5th and 6th nearest set the vote-quorum window for a 10-validator committee with one validator per zone. Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost).

| zone | 5th nearest | 6th nearest |
|---|---|---|
| us-west2-a | 138.32 (australia-southeast1-c) | 143.18 (asia-east2-a) |
| europe-west2-b | 166.01 (asia-southeast1-b) | 197.22 (asia-east2-a) |
| australia-southeast1-c | 138.32 (us-west2-a) | 148.69 (asia-south1-c) |
| asia-northeast1-b | 106.08 (australia-southeast1-c) | 119.50 (asia-south1-c) |
| us-east4-b | 172.01 (asia-northeast3-a) | 209.89 (asia-east2-a) |
| europe-west4-a | 161.26 (asia-southeast1-b) | 197.63 (asia-east2-a) |
| asia-southeast1-b | 92.77 (australia-southeast1-c) | 160.17 (us-west2-a) |
| asia-east2-a | 122.19 (australia-southeast1-c) | 143.18 (us-west2-a) |
| asia-northeast3-a | 126.85 (us-west2-a) | 127.97 (australia-southeast1-c) |
| asia-south1-c | 142.77 (europe-west4-a) | 148.69 (australia-southeast1-c) |

## Every zone, ascending

- **us-west2-a**: us-east4-b 62.12 · asia-northeast1-b 99.90 · asia-northeast3-a 126.85 · europe-west2-b 137.08 · australia-southeast1-c 138.32 · asia-east2-a 143.18 · europe-west4-a 148.74 · asia-southeast1-b 160.17 · asia-south1-c 217.56
- **europe-west2-b**: europe-west4-a 12.60 · us-east4-b 87.45 · us-west2-a 137.08 · asia-south1-c 153.69 · asia-southeast1-b 166.01 · asia-east2-a 197.22 · asia-northeast3-a 235.02 · asia-northeast1-b 249.23 · australia-southeast1-c 301.56
- **australia-southeast1-c**: asia-southeast1-b 92.77 · asia-northeast1-b 106.08 · asia-east2-a 122.19 · asia-northeast3-a 127.97 · us-west2-a 138.32 · asia-south1-c 148.69 · us-east4-b 214.20 · europe-west4-a 254.99 · europe-west2-b 301.56
- **asia-northeast1-b**: asia-northeast3-a 32.10 · asia-east2-a 55.61 · asia-southeast1-b 65.70 · us-west2-a 99.90 · australia-southeast1-c 106.08 · asia-south1-c 119.50 · us-east4-b 163.66 · europe-west2-b 249.23 · europe-west4-a 253.72
- **us-east4-b**: us-west2-a 62.12 · europe-west2-b 87.45 · europe-west4-a 87.93 · asia-northeast1-b 163.66 · asia-northeast3-a 172.01 · asia-east2-a 209.89 · asia-south1-c 214.11 · australia-southeast1-c 214.20 · asia-southeast1-b 217.72
- **europe-west4-a**: europe-west2-b 12.60 · us-east4-b 87.93 · asia-south1-c 142.77 · us-west2-a 148.74 · asia-southeast1-b 161.26 · asia-east2-a 197.63 · asia-northeast3-a 225.62 · asia-northeast1-b 253.72 · australia-southeast1-c 254.99
- **asia-southeast1-b**: asia-east2-a 30.80 · asia-south1-c 56.30 · asia-northeast1-b 65.70 · asia-northeast3-a 69.14 · australia-southeast1-c 92.77 · us-west2-a 160.17 · europe-west4-a 161.26 · europe-west2-b 166.01 · us-east4-b 217.72
- **asia-east2-a**: asia-southeast1-b 30.80 · asia-northeast3-a 36.64 · asia-northeast1-b 55.61 · asia-south1-c 85.58 · australia-southeast1-c 122.19 · us-west2-a 143.18 · europe-west2-b 197.22 · europe-west4-a 197.63 · us-east4-b 209.89
- **asia-northeast3-a**: asia-northeast1-b 32.10 · asia-east2-a 36.64 · asia-southeast1-b 69.14 · asia-south1-c 122.04 · us-west2-a 126.85 · australia-southeast1-c 127.97 · us-east4-b 172.01 · europe-west4-a 225.62 · europe-west2-b 235.02
- **asia-south1-c**: asia-southeast1-b 56.30 · asia-east2-a 85.58 · asia-northeast1-b 119.50 · asia-northeast3-a 122.04 · europe-west4-a 142.77 · australia-southeast1-c 148.69 · europe-west2-b 153.69 · us-east4-b 214.11 · us-west2-a 217.56
