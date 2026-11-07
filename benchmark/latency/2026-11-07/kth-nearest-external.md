# Nearest zones by UDP RTT — external IPs

run 20261107T145111Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

For each zone, the other zones in this table ordered by UDP echo RTT (ms). The 5th and 6th nearest set the vote-quorum window for a 10-validator committee with one validator per zone. Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost).

| zone | 5th nearest | 6th nearest |
|---|---|---|
| us-west2-a | 143.94 (asia-east2-a) | 150.70 (europe-west4-a) |
| europe-west2-b | 168.64 (asia-southeast1-b) | 200.76 (asia-east2-a) |
| australia-southeast1-c | 154.30 (asia-south1-c) | 155.97 (us-west2-a) |
| asia-northeast1-b | 108.85 (australia-southeast1-c) | 124.96 (asia-south1-c) |
| us-east4-b | 174.86 (asia-northeast3-a) | 186.30 (asia-east2-a) |
| europe-west4-a | 164.10 (asia-southeast1-b) | 195.91 (asia-east2-a) |
| asia-southeast1-b | 94.67 (australia-southeast1-c) | 160.40 (us-west2-a) |
| asia-east2-a | 122.21 (australia-southeast1-c) | 143.94 (us-west2-a) |
| asia-northeast3-a | 127.25 (us-west2-a) | 128.84 (australia-southeast1-c) |
| asia-south1-c | 147.88 (europe-west2-b) | 150.35 (europe-west4-a) |

## Every zone, ascending

- **us-west2-a**: us-east4-b 61.73 · asia-northeast1-b 100.28 · asia-northeast3-a 127.25 · europe-west2-b 137.14 · asia-east2-a 143.94 · europe-west4-a 150.70 · australia-southeast1-c 155.97 · asia-southeast1-b 160.40 · asia-south1-c 220.18
- **europe-west2-b**: europe-west4-a 12.41 · us-east4-b 76.89 · us-west2-a 137.14 · asia-south1-c 147.88 · asia-southeast1-b 168.64 · asia-east2-a 200.76 · asia-northeast1-b 218.15 · asia-northeast3-a 233.91 · australia-southeast1-c 274.23
- **australia-southeast1-c**: asia-southeast1-b 94.67 · asia-northeast1-b 108.85 · asia-east2-a 122.21 · asia-northeast3-a 128.84 · asia-south1-c 154.30 · us-west2-a 155.97 · us-east4-b 199.22 · europe-west4-a 256.69 · europe-west2-b 274.23
- **asia-northeast1-b**: asia-northeast3-a 32.30 · asia-east2-a 48.82 · asia-southeast1-b 65.73 · us-west2-a 100.28 · australia-southeast1-c 108.85 · asia-south1-c 124.96 · us-east4-b 148.48 · europe-west2-b 218.15 · europe-west4-a 225.57
- **us-east4-b**: us-west2-a 61.73 · europe-west2-b 76.89 · europe-west4-a 89.06 · asia-northeast1-b 148.48 · asia-northeast3-a 174.86 · asia-east2-a 186.30 · australia-southeast1-c 199.22 · asia-southeast1-b 209.38 · asia-south1-c 215.17
- **europe-west4-a**: europe-west2-b 12.41 · us-east4-b 89.06 · asia-south1-c 150.35 · us-west2-a 150.70 · asia-southeast1-b 164.10 · asia-east2-a 195.91 · asia-northeast1-b 225.57 · asia-northeast3-a 230.30 · australia-southeast1-c 256.69
- **asia-southeast1-b**: asia-east2-a 34.70 · asia-south1-c 63.45 · asia-northeast1-b 65.73 · asia-northeast3-a 68.21 · australia-southeast1-c 94.67 · us-west2-a 160.40 · europe-west4-a 164.10 · europe-west2-b 168.64 · us-east4-b 209.38
- **asia-east2-a**: asia-southeast1-b 34.70 · asia-northeast3-a 36.66 · asia-northeast1-b 48.82 · asia-south1-c 87.88 · australia-southeast1-c 122.21 · us-west2-a 143.94 · us-east4-b 186.30 · europe-west4-a 195.91 · europe-west2-b 200.76
- **asia-northeast3-a**: asia-northeast1-b 32.30 · asia-east2-a 36.66 · asia-southeast1-b 68.21 · asia-south1-c 123.13 · us-west2-a 127.25 · australia-southeast1-c 128.84 · us-east4-b 174.86 · europe-west4-a 230.30 · europe-west2-b 233.91
- **asia-south1-c**: asia-southeast1-b 63.45 · asia-east2-a 87.88 · asia-northeast3-a 123.13 · asia-northeast1-b 124.96 · europe-west2-b 147.88 · europe-west4-a 150.35 · australia-southeast1-c 154.30 · us-east4-b 215.17 · us-west2-a 220.18
