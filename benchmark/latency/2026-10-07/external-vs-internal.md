# External vs internal UDP RTT per ordered pair

run 20261007T025234Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

One row per direction a → b: the median of that flow's UDP echoes to the peer's internal IP and to its external IP. Both targets were probed from the same VM in the same seconds, so the two columns differ only by path. Delta = external - internal; ratio = external / internal. `via us-west2-a` = external RTT(a, us-west2-a) + external RTT(us-west2-a, b), each the direction-averaged cell of `matrix-udp-external.csv`: what a → b would measure if its external path went through us-west2-a (`—` for pairs that include it). UDP loss is a → b only, internal / external. `—` = no data.

0 of 90 ordered pairs flagged: external median more than 25 % or more than 30 ms above internal; 0 of them within 10 % of the via-us-west2-a sum.

| pair | internal ms | external ms | delta ms | ratio | via us-west2-a ms | ext - via ms | UDP loss % int / ext | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| us-west2-a → europe-west2-b | 137.04 | 138.12 | +1.08 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → australia-southeast1-c | 137.93 | 139.06 | +1.13 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → asia-northeast1-b | 100.48 | 101.33 | +0.84 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → northamerica-northeast1-b | 74.23 | 73.93 | -0.30 | 1.00 | — | — | 0 / 0 |  |
| us-west2-a → europe-west4-a | 149.07 | 149.47 | +0.40 | 1.00 | — | — | 0 / 0 |  |
| us-west2-a → asia-southeast1-b | 164.00 | 168.84 | +4.84 | 1.03 | — | — | 0 / 0 |  |
| us-west2-a → asia-east2-a | 142.96 | 143.94 | +0.98 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → asia-northeast3-a | 127.07 | 128.08 | +1.01 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → asia-south1-c | 220.81 | 218.18 | -2.63 | 0.99 | — | — | 0 / 0 |  |
| europe-west2-b → us-west2-a | 137.48 | 137.31 | -0.17 | 1.00 | — | — | 0 / 0 |  |
| europe-west2-b → australia-southeast1-c | 275.42 | 276.02 | +0.61 | 1.00 | 276.74 | -0.71 | 0 / 0 |  |
| europe-west2-b → asia-northeast1-b | 257.02 | 238.90 | -18.12 | 0.93 | 238.83 | +0.07 | 0 / 0 |  |
| europe-west2-b → northamerica-northeast1-b | 93.42 | 79.16 | -14.26 | 0.85 | 212.93 | -133.77 | 0 / 0 |  |
| europe-west2-b → europe-west4-a | 12.11 | 10.74 | -1.37 | 0.89 | 287.20 | -276.46 | 0 / 0 |  |
| europe-west2-b → asia-southeast1-b | 166.18 | 169.17 | +2.98 | 1.02 | 307.04 | -137.87 | 0 / 0 |  |
| europe-west2-b → asia-east2-a | 198.87 | 202.14 | +3.27 | 1.02 | 281.73 | -79.59 | 0 / 0 |  |
| europe-west2-b → asia-northeast3-a | 261.84 | 265.21 | +3.37 | 1.01 | 265.65 | -0.44 | 0 / 0 |  |
| europe-west2-b → asia-south1-c | 144.62 | 154.29 | +9.67 | 1.07 | 356.63 | -202.33 | 0 / 0 |  |
| australia-southeast1-c → us-west2-a | 137.94 | 138.97 | +1.03 | 1.01 | — | — | 0 / 0 |  |
| australia-southeast1-c → europe-west2-b | 300.33 | 276.27 | -24.06 | 0.92 | 276.74 | -0.46 | 0 / 0 |  |
| australia-southeast1-c → asia-northeast1-b | 108.53 | 105.44 | -3.09 | 0.97 | 240.13 | -134.69 | 0 / 0 |  |
| australia-southeast1-c → northamerica-northeast1-b | 220.94 | 213.84 | -7.10 | 0.97 | 214.23 | -0.39 | 0 / 0 |  |
| australia-southeast1-c → europe-west4-a | 311.74 | 313.11 | +1.37 | 1.00 | 288.50 | +24.62 | 0 / 0 |  |
| australia-southeast1-c → asia-southeast1-b | 182.40 | 151.42 | -30.98 | 0.83 | 308.34 | -156.91 | 0 / 0 |  |
| australia-southeast1-c → asia-east2-a | 151.56 | 122.37 | -29.19 | 0.81 | 283.03 | -160.66 | 0 / 0 |  |
| australia-southeast1-c → asia-northeast3-a | 127.92 | 128.27 | +0.35 | 1.00 | 266.95 | -138.68 | 0 / 0 |  |
| australia-southeast1-c → asia-south1-c | 240.78 | 208.45 | -32.32 | 0.87 | 357.93 | -149.47 | 0 / 0 |  |
| asia-northeast1-b → us-west2-a | 100.68 | 100.90 | +0.22 | 1.00 | — | — | 0 / 0 |  |
| asia-northeast1-b → europe-west2-b | 250.33 | 236.35 | -13.98 | 0.94 | 238.83 | -2.48 | 0 / 0 |  |
| asia-northeast1-b → australia-southeast1-c | 114.34 | 108.30 | -6.04 | 0.95 | 240.13 | -131.83 | 0 / 0 |  |
| asia-northeast1-b → northamerica-northeast1-b | 163.14 | 175.99 | +12.85 | 1.08 | 176.33 | -0.34 | 0 / 0 |  |
| asia-northeast1-b → europe-west4-a | 260.61 | 250.16 | -10.45 | 0.96 | 250.59 | -0.43 | 0 / 0 |  |
| asia-northeast1-b → asia-southeast1-b | 67.01 | 75.40 | +8.39 | 1.12 | 270.43 | -195.03 | 0 / 0 |  |
| asia-northeast1-b → asia-east2-a | 56.70 | 50.23 | -6.47 | 0.89 | 245.13 | -194.90 | 0 / 0 |  |
| asia-northeast1-b → asia-northeast3-a | 32.82 | 33.37 | +0.55 | 1.02 | 229.04 | -195.67 | 0 / 0 |  |
| asia-northeast1-b → asia-south1-c | 124.66 | 132.62 | +7.96 | 1.06 | 320.02 | -187.40 | 0 / 0 |  |
| northamerica-northeast1-b → us-west2-a | 74.89 | 76.50 | +1.60 | 1.02 | — | — | 0 / 0 |  |
| northamerica-northeast1-b → europe-west2-b | 107.20 | 78.71 | -28.49 | 0.73 | 212.93 | -134.22 | 0 / 0 |  |
| northamerica-northeast1-b → australia-southeast1-c | 246.09 | 212.86 | -33.23 | 0.86 | 214.23 | -1.37 | 0 / 0 |  |
| northamerica-northeast1-b → asia-northeast1-b | 170.30 | 174.78 | +4.48 | 1.03 | 176.33 | -1.54 | 0 / 0 |  |
| northamerica-northeast1-b → europe-west4-a | 101.31 | 86.57 | -14.74 | 0.85 | 224.69 | -138.12 | 0 / 0 |  |
| northamerica-northeast1-b → asia-southeast1-b | 254.04 | 233.91 | -20.12 | 0.92 | 244.53 | -10.62 | 0 / 0 |  |
| northamerica-northeast1-b → asia-east2-a | 224.62 | 198.82 | -25.80 | 0.89 | 219.23 | -20.41 | 0 / 0 |  |
| northamerica-northeast1-b → asia-northeast3-a | 200.35 | 201.49 | +1.14 | 1.01 | 203.15 | -1.66 | 0 / 0 |  |
| northamerica-northeast1-b → asia-south1-c | 219.62 | 229.90 | +10.28 | 1.05 | 294.12 | -64.22 | 0 / 0 |  |
| europe-west4-a → us-west2-a | 149.34 | 149.49 | +0.15 | 1.00 | — | — | 0 / 0 |  |
| europe-west4-a → europe-west2-b | 9.62 | 10.71 | +1.09 | 1.11 | 287.20 | -276.49 | 0 / 0 |  |
| europe-west4-a → australia-southeast1-c | 313.14 | 328.01 | +14.87 | 1.05 | 288.50 | +39.51 | 0 / 0 |  |
| europe-west4-a → asia-northeast1-b | 258.10 | 249.51 | -8.59 | 0.97 | 250.59 | -1.08 | 0 / 0 |  |
| europe-west4-a → northamerica-northeast1-b | 101.33 | 86.59 | -14.75 | 0.85 | 224.69 | -138.11 | 0 / 0 |  |
| europe-west4-a → asia-southeast1-b | 161.64 | 167.35 | +5.70 | 1.03 | 318.80 | -151.45 | 0 / 0 |  |
| europe-west4-a → asia-east2-a | 199.38 | 196.25 | -3.12 | 0.98 | 293.49 | -97.24 | 0 / 0 |  |
| europe-west4-a → asia-northeast3-a | 230.09 | 227.00 | -3.09 | 0.99 | 277.41 | -50.41 | 0 / 0 |  |
| europe-west4-a → asia-south1-c | 148.34 | 155.96 | +7.62 | 1.05 | 368.39 | -212.43 | 0 / 0 |  |
| asia-southeast1-b → us-west2-a | 167.57 | 169.80 | +2.23 | 1.01 | — | — | 0 / 0 |  |
| asia-southeast1-b → europe-west2-b | 168.63 | 168.19 | -0.44 | 1.00 | 307.04 | -138.85 | 0 / 0 |  |
| asia-southeast1-b → australia-southeast1-c | 149.07 | 151.30 | +2.23 | 1.01 | 308.34 | -157.04 | 0 / 0 |  |
| asia-southeast1-b → asia-northeast1-b | 66.47 | 74.98 | +8.51 | 1.13 | 270.43 | -195.45 | 0 / 0 |  |
| asia-southeast1-b → northamerica-northeast1-b | 254.55 | 232.59 | -21.95 | 0.91 | 244.53 | -11.94 | 0 / 0 |  |
| asia-southeast1-b → europe-west4-a | 164.31 | 165.01 | +0.70 | 1.00 | 318.80 | -153.79 | 0 / 0 |  |
| asia-southeast1-b → asia-east2-a | 30.78 | 32.08 | +1.29 | 1.04 | 313.33 | -281.25 | 0 / 0 |  |
| asia-southeast1-b → asia-northeast3-a | 69.83 | 68.64 | -1.19 | 0.98 | 297.25 | -228.61 | 0 / 0 |  |
| asia-southeast1-b → asia-south1-c | 57.55 | 62.19 | +4.64 | 1.08 | 388.23 | -326.04 | 0 / 0 |  |
| asia-east2-a → us-west2-a | 143.32 | 144.09 | +0.77 | 1.00 | — | — | 0 / 0 |  |
| asia-east2-a → europe-west2-b | 201.93 | 207.25 | +5.32 | 1.03 | 281.73 | -74.48 | 0 / 0 |  |
| asia-east2-a → australia-southeast1-c | 151.51 | 122.29 | -29.22 | 0.81 | 283.03 | -160.74 | 0 / 0 |  |
| asia-east2-a → asia-northeast1-b | 59.06 | 50.41 | -8.65 | 0.85 | 245.13 | -194.72 | 0 / 0 |  |
| asia-east2-a → northamerica-northeast1-b | 224.90 | 199.02 | -25.89 | 0.89 | 219.23 | -20.21 | 0 / 0 |  |
| asia-east2-a → europe-west4-a | 196.32 | 195.41 | -0.91 | 0.99 | 293.49 | -98.08 | 0 / 0 |  |
| asia-east2-a → asia-southeast1-b | 30.72 | 33.88 | +3.16 | 1.10 | 313.33 | -279.45 | 0 / 0 |  |
| asia-east2-a → asia-northeast3-a | 36.30 | 36.06 | -0.25 | 0.99 | 271.95 | -235.89 | 0 / 0 |  |
| asia-east2-a → asia-south1-c | 87.78 | 87.47 | -0.31 | 1.00 | 362.92 | -275.45 | 0 / 0 |  |
| asia-northeast3-a → us-west2-a | 126.98 | 127.78 | +0.80 | 1.01 | — | — | 0 / 0 |  |
| asia-northeast3-a → europe-west2-b | 263.38 | 265.61 | +2.23 | 1.01 | 265.65 | -0.04 | 0 / 0 |  |
| asia-northeast3-a → australia-southeast1-c | 127.48 | 128.25 | +0.76 | 1.01 | 266.95 | -138.71 | 0 / 0 |  |
| asia-northeast3-a → asia-northeast1-b | 33.16 | 33.76 | +0.60 | 1.02 | 229.04 | -195.29 | 0 / 0 |  |
| asia-northeast3-a → northamerica-northeast1-b | 200.71 | 201.54 | +0.83 | 1.00 | 203.15 | -1.60 | 0 / 0 |  |
| asia-northeast3-a → europe-west4-a | 232.66 | 229.20 | -3.47 | 0.98 | 277.41 | -48.22 | 0 / 0 |  |
| asia-northeast3-a → asia-southeast1-b | 71.37 | 70.06 | -1.31 | 0.98 | 297.25 | -227.19 | 0 / 0 |  |
| asia-northeast3-a → asia-east2-a | 37.49 | 37.98 | +0.49 | 1.01 | 271.95 | -233.97 | 0 / 0 |  |
| asia-northeast3-a → asia-south1-c | 121.02 | 122.68 | +1.66 | 1.01 | 346.84 | -224.16 | 0 / 0 |  |
| asia-south1-c → us-west2-a | 222.85 | 219.64 | -3.21 | 0.99 | — | — | 0 / 0 |  |
| asia-south1-c → europe-west2-b | 140.78 | 144.32 | +3.54 | 1.02 | 356.63 | -212.31 | 0 / 0 |  |
| asia-south1-c → australia-southeast1-c | 241.48 | 208.84 | -32.64 | 0.86 | 357.93 | -149.09 | 0 / 0 |  |
| asia-south1-c → asia-northeast1-b | 123.29 | 134.53 | +11.23 | 1.09 | 320.02 | -185.50 | 0 / 0 |  |
| asia-south1-c → northamerica-northeast1-b | 229.61 | 220.09 | -9.52 | 0.96 | 294.12 | -74.03 | 0 / 0 |  |
| asia-south1-c → europe-west4-a | 146.09 | 146.98 | +0.89 | 1.01 | 368.39 | -221.41 | 0 / 0 |  |
| asia-south1-c → asia-southeast1-b | 57.59 | 61.99 | +4.41 | 1.08 | 388.23 | -326.24 | 0 / 0 |  |
| asia-south1-c → asia-east2-a | 85.69 | 88.11 | +2.42 | 1.03 | 362.92 | -274.82 | 0 / 0 |  |
| asia-south1-c → asia-northeast3-a | 122.95 | 122.46 | -0.49 | 1.00 | 346.84 | -224.38 | 0 / 0 |  |
