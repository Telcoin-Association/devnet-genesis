# UDP vs TCP per zone pair

run 20261007T025234Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost). Delta = UDP - TCP (percent of TCP). UDP loss is the worse direction.

Paths: the UDP probe keeps one socket per peer, so each direction is one flow on one ECMP path, as a QUIC connection would be (`a→b / b→a` shows the two). Every TCP connect uses a fresh source port, so the TCP min–max spans the paths between the two zones. A UDP-over-TCP flag with a wide TCP range usually means the UDP flow was hashed onto a slower path, not that UDP is treated differently.

0 of 45 pairs flagged (UDP median more than 10% above TCP, or any UDP loss).

| pair | UDP ms | UDP a→b / b→a | TCP ms | TCP min–max | delta ms | delta % | UDP loss % | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| europe-west2-b ↔ europe-west4-a | 10.86 | 12.11 / 9.62 | 11.57 | 9.54–15.20 | -0.71 | -6.13% | 0 |  |
| asia-southeast1-b ↔ asia-east2-a | 30.75 | 30.78 / 30.72 | 30.71 | 30.27–31.47 | +0.04 | +0.14% | 0 |  |
| asia-northeast1-b ↔ asia-northeast3-a | 32.99 | 32.82 / 33.16 | 32.72 | 32.09–33.98 | +0.27 | +0.83% | 0 |  |
| asia-east2-a ↔ asia-northeast3-a | 36.90 | 36.30 / 37.49 | 35.87 | 34.76–38.31 | +1.03 | +2.87% | 0 |  |
| asia-southeast1-b ↔ asia-south1-c | 57.57 | 57.55 / 57.59 | 57.52 | 55.14–59.71 | +0.05 | +0.09% | 0 |  |
| asia-northeast1-b ↔ asia-east2-a | 57.88 | 56.70 / 59.06 | 56.76 | 54.45–59.83 | +1.12 | +1.98% | 0 |  |
| asia-northeast1-b ↔ asia-southeast1-b | 66.74 | 67.01 / 66.47 | 66.42 | 65.64–68.14 | +0.32 | +0.48% | 0 |  |
| asia-southeast1-b ↔ asia-northeast3-a | 70.60 | 69.83 / 71.37 | 70.09 | 65.53–72.92 | +0.51 | +0.72% | 0 |  |
| us-west2-a ↔ northamerica-northeast1-b | 74.56 | 74.23 / 74.89 | 74.44 | 73.09–75.72 | +0.12 | +0.16% | 0 |  |
| asia-east2-a ↔ asia-south1-c | 86.73 | 87.78 / 85.69 | 86.38 | 85.33–89.78 | +0.35 | +0.41% | 0 |  |
| europe-west2-b ↔ northamerica-northeast1-b | 100.31 | 93.42 / 107.20 | 100.22 | 93.21–107.61 | +0.10 | +0.10% | 0 |  |
| us-west2-a ↔ asia-northeast1-b | 100.58 | 100.48 / 100.68 | 100.49 | 99.86–101.74 | +0.09 | +0.09% | 0 |  |
| northamerica-northeast1-b ↔ europe-west4-a | 101.32 | 101.31 / 101.33 | 97.35 | 94.15–102.51 | +3.98 | +4.08% | 0 |  |
| australia-southeast1-c ↔ asia-northeast1-b | 111.44 | 108.53 / 114.34 | 114.03 | 108.07–119.90 | -2.60 | -2.28% | 0 |  |
| asia-northeast3-a ↔ asia-south1-c | 121.99 | 121.02 / 122.95 | 121.06 | 120.55–122.20 | +0.93 | +0.76% | 0 |  |
| asia-northeast1-b ↔ asia-south1-c | 123.98 | 124.66 / 123.29 | 122.74 | 121.07–124.77 | +1.24 | +1.01% | 0 |  |
| us-west2-a ↔ asia-northeast3-a | 127.03 | 127.07 / 126.98 | 126.55 | 126.25–128.00 | +0.48 | +0.38% | 0 |  |
| australia-southeast1-c ↔ asia-northeast3-a | 127.70 | 127.92 / 127.48 | 127.55 | 126.74–128.97 | +0.15 | +0.12% | 0 |  |
| us-west2-a ↔ europe-west2-b | 137.26 | 137.04 / 137.48 | 137.23 | 135.89–139.50 | +0.03 | +0.02% | 0 |  |
| us-west2-a ↔ australia-southeast1-c | 137.94 | 137.93 / 137.94 | 138.01 | 137.28–139.73 | -0.07 | -0.05% | 0 |  |
| europe-west2-b ↔ asia-south1-c | 142.70 | 144.62 / 140.78 | 141.92 | 140.07–153.92 | +0.78 | +0.55% | 0 |  |
| us-west2-a ↔ asia-east2-a | 143.14 | 142.96 / 143.32 | 143.23 | 142.80–144.82 | -0.09 | -0.06% | 0 |  |
| europe-west4-a ↔ asia-south1-c | 147.22 | 148.34 / 146.09 | 149.93 | 143.94–156.26 | -2.72 | -1.81% | 0 |  |
| us-west2-a ↔ europe-west4-a | 149.20 | 149.07 / 149.34 | 149.64 | 148.90–151.25 | -0.44 | -0.29% | 0 |  |
| australia-southeast1-c ↔ asia-east2-a | 151.54 | 151.56 / 151.51 | 145.50 | 127.49–174.74 | +6.04 | +4.15% | 0 |  |
| europe-west4-a ↔ asia-southeast1-b | 162.98 | 161.64 / 164.31 | 161.75 | 161.11–163.96 | +1.23 | +0.76% | 0 |  |
| australia-southeast1-c ↔ asia-southeast1-b | 165.74 | 182.40 / 149.07 | 165.86 | 148.55–182.67 | -0.12 | -0.07% | 0 |  |
| us-west2-a ↔ asia-southeast1-b | 165.78 | 164.00 / 167.57 | 166.04 | 163.44–1268.31 | -0.25 | -0.15% | 0 |  |
| asia-northeast1-b ↔ northamerica-northeast1-b | 166.72 | 163.14 / 170.30 | 164.94 | 162.37–177.37 | +1.78 | +1.08% | 0 |  |
| europe-west2-b ↔ asia-southeast1-b | 167.40 | 166.18 / 168.63 | 167.40 | 165.53–170.18 | +0.01 | +0.00% | 0 |  |
| europe-west4-a ↔ asia-east2-a | 197.85 | 199.38 / 196.32 | 195.82 | 193.01–199.57 | +2.02 | +1.03% | 0 |  |
| europe-west2-b ↔ asia-east2-a | 200.40 | 198.87 / 201.93 | 201.70 | 197.09–206.05 | -1.30 | -0.64% | 0 |  |
| northamerica-northeast1-b ↔ asia-northeast3-a | 200.53 | 200.35 / 200.71 | 200.50 | 199.70–201.29 | +0.03 | +0.02% | 0 |  |
| us-west2-a ↔ asia-south1-c | 221.83 | 220.81 / 222.85 | 221.75 | 214.85–228.75 | +0.07 | +0.03% | 0 |  |
| northamerica-northeast1-b ↔ asia-south1-c | 224.62 | 219.62 / 229.61 | 228.88 | 217.77–230.29 | -4.26 | -1.86% | 0 |  |
| northamerica-northeast1-b ↔ asia-east2-a | 224.76 | 224.62 / 224.90 | 224.66 | 224.04–226.15 | +0.11 | +0.05% | 0 |  |
| europe-west4-a ↔ asia-northeast3-a | 231.38 | 230.09 / 232.66 | 230.79 | 227.08–235.13 | +0.58 | +0.25% | 0 |  |
| australia-southeast1-c ↔ northamerica-northeast1-b | 233.51 | 220.94 / 246.09 | 220.70 | 194.69–246.91 | +12.81 | +5.81% | 0 |  |
| australia-southeast1-c ↔ asia-south1-c | 241.13 | 240.78 / 241.48 | 222.28 | 203.19–243.07 | +18.84 | +8.48% | 0 |  |
| europe-west2-b ↔ asia-northeast1-b | 253.68 | 257.02 / 250.33 | 255.33 | 240.84–258.92 | -1.66 | -0.65% | 0 |  |
| northamerica-northeast1-b ↔ asia-southeast1-b | 254.29 | 254.04 / 254.55 | 250.88 | 245.47–256.41 | +3.41 | +1.36% | 0 |  |
| asia-northeast1-b ↔ europe-west4-a | 259.35 | 260.61 / 258.10 | 260.02 | 257.74–263.17 | -0.67 | -0.26% | 0 |  |
| europe-west2-b ↔ asia-northeast3-a | 262.61 | 261.84 / 263.38 | 263.18 | 260.26–265.02 | -0.57 | -0.22% | 0 |  |
| europe-west2-b ↔ australia-southeast1-c | 287.88 | 275.42 / 300.33 | 287.61 | 273.99–327.82 | +0.27 | +0.09% | 0 |  |
| australia-southeast1-c ↔ europe-west4-a | 312.44 | 311.74 / 313.14 | 316.31 | 310.94–323.24 | -3.86 | -1.22% | 0 |  |
