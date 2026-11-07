# UDP vs TCP per zone pair

run 20261107T145111Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost). Delta = UDP - TCP (percent of TCP). UDP loss is the worse direction.

Paths: the UDP probe keeps one socket per peer, so each direction is one flow on one ECMP path, as a QUIC connection would be (`a→b / b→a` shows the two). Every TCP connect uses a fresh source port, so the TCP min–max spans the paths between the two zones. A UDP-over-TCP flag with a wide TCP range usually means the UDP flow was hashed onto a slower path, not that UDP is treated differently.

0 of 45 pairs flagged (UDP median more than 10% above TCP, or any UDP loss).

| pair | UDP ms | UDP a→b / b→a | TCP ms | TCP min–max | delta ms | delta % | UDP loss % | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| europe-west2-b ↔ europe-west4-a | 12.60 | 13.52 / 11.67 | 12.01 | 8.91–15.06 | +0.59 | +4.91% | 0 |  |
| asia-southeast1-b ↔ asia-east2-a | 30.80 | 30.68 / 30.93 | 30.63 | 30.30–31.95 | +0.17 | +0.57% | 0 |  |
| asia-northeast1-b ↔ asia-northeast3-a | 32.10 | 31.97 / 32.22 | 31.96 | 31.64–33.39 | +0.13 | +0.42% | 0 |  |
| asia-east2-a ↔ asia-northeast3-a | 36.64 | 37.71 / 35.58 | 35.84 | 34.93–37.23 | +0.81 | +2.25% | 0 |  |
| asia-northeast1-b ↔ asia-east2-a | 55.61 | 55.56 / 55.66 | 51.62 | 46.88–55.58 | +3.99 | +7.72% | 0 |  |
| asia-southeast1-b ↔ asia-south1-c | 56.30 | 55.40 / 57.19 | 57.25 | 54.96–59.58 | -0.95 | -1.67% | 0 |  |
| us-west2-a ↔ us-east4-b | 62.12 | 61.82 / 62.43 | 61.81 | 59.73–65.75 | +0.31 | +0.51% | 0 |  |
| asia-northeast1-b ↔ asia-southeast1-b | 65.70 | 65.63 / 65.78 | 65.47 | 64.91–67.07 | +0.24 | +0.36% | 0 |  |
| asia-southeast1-b ↔ asia-northeast3-a | 69.14 | 67.60 / 70.68 | 68.66 | 65.48–73.18 | +0.48 | +0.70% | 0 |  |
| asia-east2-a ↔ asia-south1-c | 85.58 | 85.48 / 85.68 | 86.24 | 85.10–87.84 | -0.66 | -0.77% | 0 |  |
| europe-west2-b ↔ us-east4-b | 87.45 | 87.70 / 87.19 | 91.56 | 86.95–96.16 | -4.12 | -4.50% | 0 |  |
| us-east4-b ↔ europe-west4-a | 87.93 | 88.45 / 87.40 | 88.05 | 87.23–94.27 | -0.12 | -0.14% | 0 |  |
| australia-southeast1-c ↔ asia-southeast1-b | 92.77 | 92.77 / 92.77 | 92.60 | 92.45–94.11 | +0.17 | +0.19% | 0 |  |
| us-west2-a ↔ asia-northeast1-b | 99.90 | 99.69 / 100.11 | 99.70 | 99.16–102.07 | +0.20 | +0.20% | 0 |  |
| australia-southeast1-c ↔ asia-northeast1-b | 106.08 | 106.72 / 105.44 | 109.47 | 105.11–119.56 | -3.39 | -3.10% | 0 |  |
| asia-northeast1-b ↔ asia-south1-c | 119.50 | 119.46 / 119.53 | 121.72 | 119.25–124.51 | -2.22 | -1.82% | 0 |  |
| asia-northeast3-a ↔ asia-south1-c | 122.04 | 122.58 / 121.51 | 121.63 | 120.85–123.51 | +0.42 | +0.34% | 0 |  |
| australia-southeast1-c ↔ asia-east2-a | 122.19 | 122.75 / 121.63 | 121.25 | 119.74–123.35 | +0.94 | +0.78% | 0 |  |
| us-west2-a ↔ asia-northeast3-a | 126.85 | 126.80 / 126.90 | 126.62 | 126.16–128.96 | +0.23 | +0.18% | 0 |  |
| australia-southeast1-c ↔ asia-northeast3-a | 127.97 | 128.02 / 127.92 | 127.54 | 126.94–128.78 | +0.43 | +0.34% | 0 |  |
| us-west2-a ↔ europe-west2-b | 137.08 | 136.75 / 137.41 | 136.08 | 134.97–139.81 | +1.00 | +0.74% | 0 |  |
| us-west2-a ↔ australia-southeast1-c | 138.32 | 138.03 / 138.61 | 138.06 | 137.42–174.62 | +0.26 | +0.19% | 0 |  |
| europe-west4-a ↔ asia-south1-c | 142.78 | 142.75 / 142.80 | 142.96 | 142.52–157.24 | -0.18 | -0.13% | 0 |  |
| us-west2-a ↔ asia-east2-a | 143.18 | 143.25 / 143.12 | 142.94 | 142.52–144.56 | +0.24 | +0.17% | 0 |  |
| australia-southeast1-c ↔ asia-south1-c | 148.69 | 147.73 / 149.65 | 149.53 | 147.33–151.59 | -0.84 | -0.56% | 0 |  |
| us-west2-a ↔ europe-west4-a | 148.74 | 149.37 / 148.10 | 147.96 | 147.20–149.48 | +0.78 | +0.53% | 0 |  |
| europe-west2-b ↔ asia-south1-c | 153.69 | 153.74 / 153.63 | 142.75 | 139.36–154.43 | +10.93 | +7.66% | 0 |  |
| us-west2-a ↔ asia-southeast1-b | 160.17 | 160.06 / 160.29 | 159.93 | 159.59–162.74 | +0.25 | +0.15% | 0 |  |
| europe-west4-a ↔ asia-southeast1-b | 161.26 | 161.21 / 161.30 | 163.11 | 160.74–165.89 | -1.85 | -1.14% | 0 |  |
| asia-northeast1-b ↔ us-east4-b | 163.66 | 162.92 / 164.41 | 163.61 | 161.04–166.41 | +0.05 | +0.03% | 0 |  |
| europe-west2-b ↔ asia-southeast1-b | 166.00 | 166.97 / 165.04 | 167.28 | 164.67–170.13 | -1.28 | -0.76% | 0 |  |
| us-east4-b ↔ asia-northeast3-a | 172.01 | 171.05 / 172.98 | 172.94 | 170.77–176.58 | -0.93 | -0.53% | 0 |  |
| europe-west2-b ↔ asia-east2-a | 197.22 | 198.75 / 195.69 | 198.75 | 195.74–201.24 | -1.53 | -0.77% | 0 |  |
| europe-west4-a ↔ asia-east2-a | 197.63 | 196.60 / 198.67 | 196.36 | 193.23–200.98 | +1.27 | +0.65% | 0 |  |
| us-east4-b ↔ asia-east2-a | 209.89 | 209.71 / 210.07 | 209.88 | 208.37–211.92 | +0.01 | +0.01% | 0 |  |
| us-east4-b ↔ asia-south1-c | 214.11 | 221.16 / 207.07 | 220.42 | 206.73–221.87 | -6.30 | -2.86% | 0 |  |
| australia-southeast1-c ↔ us-east4-b | 214.20 | 236.04 / 192.35 | 219.73 | 192.13–236.08 | -5.54 | -2.52% | 0 |  |
| us-west2-a ↔ asia-south1-c | 217.56 | 217.90 / 217.21 | 218.31 | 216.80–221.19 | -0.76 | -0.35% | 0 |  |
| us-east4-b ↔ asia-southeast1-b | 217.72 | 222.70 / 212.74 | 222.72 | 212.26–225.08 | -5.00 | -2.24% | 0 |  |
| europe-west4-a ↔ asia-northeast3-a | 225.62 | 226.09 / 225.14 | 228.11 | 224.86–232.49 | -2.50 | -1.09% | 0 |  |
| europe-west2-b ↔ asia-northeast3-a | 235.03 | 233.56 / 236.49 | 233.81 | 230.30–237.32 | +1.21 | +0.52% | 0 |  |
| europe-west2-b ↔ asia-northeast1-b | 249.23 | 249.45 / 249.01 | 249.10 | 248.17–251.06 | +0.13 | +0.05% | 0 |  |
| asia-northeast1-b ↔ europe-west4-a | 253.72 | 257.61 / 249.83 | 253.67 | 249.11–258.26 | +0.04 | +0.02% | 0 |  |
| australia-southeast1-c ↔ europe-west4-a | 254.99 | 253.51 / 256.47 | 255.37 | 253.02–259.39 | -0.38 | -0.15% | 0 |  |
| europe-west2-b ↔ australia-southeast1-c | 301.56 | 301.32 / 301.79 | 301.08 | 275.99–326.82 | +0.48 | +0.16% | 0 |  |
