# External vs internal UDP RTT per ordered pair

run 20261107T145111Z · probe VMs e2-small · addresses both (PREMIUM tier) · 10 zones

One row per direction a → b: the median of that flow's UDP echoes to the peer's internal IP and to its external IP. Both targets were probed from the same VM in the same seconds, so the two columns differ only by path. Delta = external - internal; ratio = external / internal. `via us-west2-a` = external RTT(a, us-west2-a) + external RTT(us-west2-a, b), each the direction-averaged cell of `matrix-udp-external.csv`: what a → b would measure if its external path went through us-west2-a (`—` for pairs that include it). UDP loss is a → b only, internal / external. `—` = no data.

1 of 90 ordered pairs flagged: external median more than 25 % or more than 30 ms above internal; 0 of them within 10 % of the via-us-west2-a sum.
- us-west2-a → australia-southeast1-c: internal 138.03, external 173.58 (+35.55 ms, x1.26), via us-west2-a —

| pair | internal ms | external ms | delta ms | ratio | via us-west2-a ms | ext - via ms | UDP loss % int / ext | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| us-west2-a → europe-west2-b | 136.75 | 137.56 | +0.82 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → australia-southeast1-c | 138.03 | 173.58 | +35.55 | 1.26 | — | — | 0 / 0 | external > internal |
| us-west2-a → asia-northeast1-b | 99.69 | 100.41 | +0.72 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → us-east4-b | 61.82 | 62.82 | +1.00 | 1.02 | — | — | 0 / 0 |  |
| us-west2-a → europe-west4-a | 149.37 | 150.11 | +0.74 | 1.00 | — | — | 0 / 0 |  |
| us-west2-a → asia-southeast1-b | 160.06 | 160.61 | +0.55 | 1.00 | — | — | 0 / 0 |  |
| us-west2-a → asia-east2-a | 143.25 | 144.27 | +1.03 | 1.01 | — | — | 0 / 0 |  |
| us-west2-a → asia-northeast3-a | 126.80 | 127.35 | +0.56 | 1.00 | — | — | 0 / 0 |  |
| us-west2-a → asia-south1-c | 217.90 | 220.06 | +2.16 | 1.01 | — | — | 0 / 0 |  |
| europe-west2-b → us-west2-a | 137.41 | 136.72 | -0.69 | 0.99 | — | — | 0 / 0 |  |
| europe-west2-b → australia-southeast1-c | 301.32 | 275.09 | -26.24 | 0.91 | 293.12 | -18.03 | 0 / 0 |  |
| europe-west2-b → asia-northeast1-b | 249.45 | 219.56 | -29.89 | 0.88 | 237.42 | -17.86 | 0 / 0 |  |
| europe-west2-b → us-east4-b | 87.70 | 77.26 | -10.44 | 0.88 | 198.88 | -121.61 | 0 / 0 |  |
| europe-west2-b → europe-west4-a | 13.52 | 11.56 | -1.96 | 0.85 | 287.85 | -276.29 | 0 / 0 |  |
| europe-west2-b → asia-southeast1-b | 166.97 | 168.74 | +1.77 | 1.01 | 297.54 | -128.80 | 0 / 0 |  |
| europe-west2-b → asia-east2-a | 198.75 | 198.50 | -0.25 | 1.00 | 281.09 | -82.59 | 0 / 0 |  |
| europe-west2-b → asia-northeast3-a | 233.56 | 235.21 | +1.64 | 1.01 | 264.39 | -29.18 | 0 / 0 |  |
| europe-west2-b → asia-south1-c | 153.74 | 141.61 | -12.14 | 0.92 | 357.32 | -215.72 | 0 / 0 |  |
| australia-southeast1-c → us-west2-a | 138.61 | 138.37 | -0.23 | 1.00 | — | — | 0 / 0 |  |
| australia-southeast1-c → europe-west2-b | 301.79 | 273.37 | -28.42 | 0.91 | 293.12 | -19.75 | 0 / 0 |  |
| australia-southeast1-c → asia-northeast1-b | 106.72 | 110.31 | +3.58 | 1.03 | 256.25 | -145.94 | 0 / 0 |  |
| australia-southeast1-c → us-east4-b | 236.04 | 198.87 | -37.17 | 0.84 | 217.71 | -18.84 | 0 / 0 |  |
| australia-southeast1-c → europe-west4-a | 253.51 | 258.76 | +5.25 | 1.02 | 306.68 | -47.92 | 0 / 0 |  |
| australia-southeast1-c → asia-southeast1-b | 92.77 | 94.69 | +1.92 | 1.02 | 316.37 | -221.68 | 0 / 0 |  |
| australia-southeast1-c → asia-east2-a | 122.75 | 122.67 | -0.08 | 1.00 | 299.92 | -177.25 | 0 / 0 |  |
| australia-southeast1-c → asia-northeast3-a | 128.02 | 128.69 | +0.67 | 1.00 | 283.22 | -154.52 | 0 / 0 |  |
| australia-southeast1-c → asia-south1-c | 147.73 | 154.15 | +6.42 | 1.04 | 376.15 | -222.00 | 0 / 0 |  |
| asia-northeast1-b → us-west2-a | 100.11 | 100.14 | +0.03 | 1.00 | — | — | 0 / 0 |  |
| asia-northeast1-b → europe-west2-b | 249.01 | 216.75 | -32.27 | 0.87 | 237.42 | -20.67 | 0 / 0 |  |
| asia-northeast1-b → australia-southeast1-c | 105.44 | 107.39 | +1.96 | 1.02 | 256.25 | -148.86 | 0 / 0 |  |
| asia-northeast1-b → us-east4-b | 162.92 | 148.88 | -14.04 | 0.91 | 162.01 | -13.13 | 0 / 0 |  |
| asia-northeast1-b → europe-west4-a | 257.61 | 225.86 | -31.75 | 0.88 | 250.98 | -25.12 | 0 / 0 |  |
| asia-northeast1-b → asia-southeast1-b | 65.63 | 65.76 | +0.13 | 1.00 | 260.68 | -194.92 | 0 / 0 |  |
| asia-northeast1-b → asia-east2-a | 55.56 | 48.96 | -6.60 | 0.88 | 244.22 | -195.26 | 0 / 0 |  |
| asia-northeast1-b → asia-northeast3-a | 31.97 | 32.29 | +0.32 | 1.01 | 227.52 | -195.24 | 0 / 0 |  |
| asia-northeast1-b → asia-south1-c | 119.46 | 124.17 | +4.70 | 1.04 | 320.45 | -196.29 | 0 / 0 |  |
| us-east4-b → us-west2-a | 62.43 | 60.65 | -1.78 | 0.97 | — | — | 0 / 0 |  |
| us-east4-b → europe-west2-b | 87.19 | 76.51 | -10.68 | 0.88 | 198.88 | -122.37 | 0 / 0 |  |
| us-east4-b → australia-southeast1-c | 192.35 | 199.57 | +7.21 | 1.04 | 217.71 | -18.14 | 0 / 0 |  |
| us-east4-b → asia-northeast1-b | 164.41 | 148.08 | -16.34 | 0.90 | 162.01 | -13.93 | 0 / 0 |  |
| us-east4-b → europe-west4-a | 88.45 | 88.82 | +0.37 | 1.00 | 212.44 | -123.62 | 0 / 0 |  |
| us-east4-b → asia-southeast1-b | 222.70 | 208.86 | -13.84 | 0.94 | 222.13 | -13.27 | 0 / 0 |  |
| us-east4-b → asia-east2-a | 209.71 | 186.78 | -22.93 | 0.89 | 205.68 | -18.90 | 0 / 0 |  |
| us-east4-b → asia-northeast3-a | 171.05 | 174.02 | +2.98 | 1.02 | 188.98 | -14.96 | 0 / 0 |  |
| us-east4-b → asia-south1-c | 221.16 | 220.73 | -0.42 | 1.00 | 281.91 | -61.18 | 0 / 0 |  |
| europe-west4-a → us-west2-a | 148.10 | 151.30 | +3.19 | 1.02 | — | — | 0 / 0 |  |
| europe-west4-a → europe-west2-b | 11.67 | 13.26 | +1.59 | 1.14 | 287.85 | -274.58 | 0 / 0 |  |
| europe-west4-a → australia-southeast1-c | 256.47 | 254.62 | -1.84 | 0.99 | 306.68 | -52.05 | 0 / 0 |  |
| europe-west4-a → asia-northeast1-b | 249.83 | 225.28 | -24.55 | 0.90 | 250.98 | -25.70 | 0 / 0 |  |
| europe-west4-a → us-east4-b | 87.40 | 89.29 | +1.89 | 1.02 | 212.44 | -123.14 | 0 / 0 |  |
| europe-west4-a → asia-southeast1-b | 161.21 | 162.83 | +1.62 | 1.01 | 311.10 | -148.27 | 0 / 0 |  |
| europe-west4-a → asia-east2-a | 196.60 | 197.29 | +0.69 | 1.00 | 294.65 | -97.36 | 0 / 0 |  |
| europe-west4-a → asia-northeast3-a | 226.09 | 230.98 | +4.89 | 1.02 | 277.95 | -46.97 | 0 / 0 |  |
| europe-west4-a → asia-south1-c | 142.75 | 144.58 | +1.83 | 1.01 | 370.88 | -226.31 | 0 / 0 |  |
| asia-southeast1-b → us-west2-a | 160.29 | 160.19 | -0.10 | 1.00 | — | — | 0 / 0 |  |
| asia-southeast1-b → europe-west2-b | 165.04 | 168.54 | +3.50 | 1.02 | 297.54 | -129.00 | 0 / 0 |  |
| asia-southeast1-b → australia-southeast1-c | 92.77 | 94.65 | +1.88 | 1.02 | 316.37 | -221.72 | 0 / 0 |  |
| asia-southeast1-b → asia-northeast1-b | 65.78 | 65.71 | -0.07 | 1.00 | 260.68 | -194.97 | 0 / 0 |  |
| asia-southeast1-b → us-east4-b | 212.74 | 209.89 | -2.85 | 0.99 | 222.13 | -12.24 | 0 / 0 |  |
| asia-southeast1-b → europe-west4-a | 161.30 | 165.37 | +4.07 | 1.02 | 311.10 | -145.74 | 0 / 0 |  |
| asia-southeast1-b → asia-east2-a | 30.68 | 34.38 | +3.70 | 1.12 | 304.34 | -269.96 | 0 / 0 |  |
| asia-southeast1-b → asia-northeast3-a | 67.60 | 70.30 | +2.70 | 1.04 | 287.64 | -217.34 | 0 / 0 |  |
| asia-southeast1-b → asia-south1-c | 55.40 | 61.90 | +6.50 | 1.12 | 380.58 | -318.68 | 0 / 0 |  |
| asia-east2-a → us-west2-a | 143.12 | 143.62 | +0.50 | 1.00 | — | — | 0 / 0 |  |
| asia-east2-a → europe-west2-b | 195.69 | 203.03 | +7.34 | 1.04 | 281.09 | -78.06 | 0 / 0 |  |
| asia-east2-a → australia-southeast1-c | 121.63 | 121.74 | +0.11 | 1.00 | 299.92 | -178.18 | 0 / 0 |  |
| asia-east2-a → asia-northeast1-b | 55.66 | 48.69 | -6.97 | 0.88 | 244.22 | -195.53 | 0 / 0 |  |
| asia-east2-a → us-east4-b | 210.07 | 185.81 | -24.26 | 0.89 | 205.68 | -19.87 | 0 / 0 |  |
| asia-east2-a → europe-west4-a | 198.67 | 194.52 | -4.15 | 0.98 | 294.65 | -100.13 | 0 / 0 |  |
| asia-east2-a → asia-southeast1-b | 30.93 | 35.01 | +4.09 | 1.13 | 304.34 | -269.33 | 0 / 0 |  |
| asia-east2-a → asia-northeast3-a | 37.71 | 35.74 | -1.97 | 0.95 | 271.19 | -235.45 | 0 / 0 |  |
| asia-east2-a → asia-south1-c | 85.48 | 88.08 | +2.60 | 1.03 | 364.12 | -276.04 | 0 / 0 |  |
| asia-northeast3-a → us-west2-a | 126.90 | 127.14 | +0.24 | 1.00 | — | — | 0 / 0 |  |
| asia-northeast3-a → europe-west2-b | 236.49 | 232.62 | -3.87 | 0.98 | 264.39 | -31.77 | 0 / 0 |  |
| asia-northeast3-a → australia-southeast1-c | 127.92 | 128.99 | +1.07 | 1.01 | 283.22 | -154.23 | 0 / 0 |  |
| asia-northeast3-a → asia-northeast1-b | 32.22 | 32.32 | +0.10 | 1.00 | 227.52 | -195.20 | 0 / 0 |  |
| asia-northeast3-a → us-east4-b | 172.98 | 175.69 | +2.71 | 1.02 | 188.98 | -13.29 | 0 / 0 |  |
| asia-northeast3-a → europe-west4-a | 225.14 | 229.62 | +4.49 | 1.02 | 277.95 | -48.32 | 0 / 0 |  |
| asia-northeast3-a → asia-southeast1-b | 70.68 | 66.11 | -4.57 | 0.94 | 287.64 | -221.53 | 0 / 0 |  |
| asia-northeast3-a → asia-east2-a | 35.58 | 37.57 | +2.00 | 1.06 | 271.19 | -233.62 | 0 / 0 |  |
| asia-northeast3-a → asia-south1-c | 122.58 | 123.94 | +1.35 | 1.01 | 347.42 | -223.49 | 0 / 0 |  |
| asia-south1-c → us-west2-a | 217.21 | 220.29 | +3.08 | 1.01 | — | — | 0 / 0 |  |
| asia-south1-c → europe-west2-b | 153.63 | 154.14 | +0.51 | 1.00 | 357.32 | -203.18 | 0 / 0 |  |
| asia-south1-c → australia-southeast1-c | 149.65 | 154.45 | +4.80 | 1.03 | 376.15 | -221.70 | 0 / 0 |  |
| asia-south1-c → asia-northeast1-b | 119.53 | 125.75 | +6.21 | 1.05 | 320.45 | -194.71 | 0 / 0 |  |
| asia-south1-c → us-east4-b | 207.07 | 209.61 | +2.54 | 1.01 | 281.91 | -72.30 | 0 / 0 |  |
| asia-south1-c → europe-west4-a | 142.80 | 156.12 | +13.32 | 1.09 | 370.88 | -214.76 | 0 / 0 |  |
| asia-south1-c → asia-southeast1-b | 57.19 | 65.01 | +7.82 | 1.14 | 380.58 | -315.57 | 0 / 0 |  |
| asia-south1-c → asia-east2-a | 85.68 | 87.68 | +2.00 | 1.02 | 364.12 | -276.44 | 0 / 0 |  |
| asia-south1-c → asia-northeast3-a | 121.51 | 122.33 | +0.83 | 1.01 | 347.42 | -225.09 | 0 / 0 |  |
