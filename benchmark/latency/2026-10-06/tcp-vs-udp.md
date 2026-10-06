# UDP vs TCP per zone pair

run 20261006T175053Z · probe VMs e2-small · 18 zones

Cells average both directions; `*` = one direction only; `—` = no data (not measured or every probe lost). Delta = UDP - TCP (percent of TCP). UDP loss is the worse direction.

Paths: the UDP probe keeps one socket per peer, so each direction is one flow on one ECMP path, as a QUIC connection would be (`a→b / b→a` shows the two). Every TCP connect uses a fresh source port, so the TCP min–max spans the paths between the two zones. A UDP-over-TCP flag with a wide TCP range usually means the UDP flow was hashed onto a slower path, not that UDP is treated differently.

5 of 153 pairs flagged (UDP median more than 10% above TCP, or any UDP loss).

- europe-west4-a ↔ europe-west3-a: UDP > TCP by >10%
- europe-west2-b ↔ europe-west3-a: UDP > TCP by >10%
- asia-northeast1-b ↔ asia-northeast1-c: UDP > TCP by >10%
- asia-southeast2-a ↔ asia-southeast1-b: UDP > TCP by >10%
- asia-northeast3-a ↔ asia-northeast3-b: UDP > TCP by >10%

| pair | UDP ms | UDP a→b / b→a | TCP ms | TCP min–max | delta ms | delta % | UDP loss % | flags |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| asia-northeast1-b ↔ asia-northeast1-c | 0.57 | 0.55 / 0.58 | 0.41 | 0.28–1.71 | +0.15 | +37.67% | 0 | UDP > TCP by >10% |
| asia-northeast3-a ↔ asia-northeast3-b | 0.84 | 0.80 / 0.88 | 0.72 | 0.58–1.83 | +0.12 | +16.90% | 0 | UDP > TCP by >10% |
| asia-northeast1-b ↔ asia-northeast2-a | 8.59 | 8.55 / 8.61 | 8.70 | 8.23–10.43 | -0.12 | -1.36% | 0 |  |
| asia-northeast2-a ↔ asia-northeast1-c | 8.77 | 8.74 / 8.79 | 8.45 | 8.19–9.62 | +0.31 | +3.71% | 0 |  |
| europe-west4-a ↔ europe-west2-b | 13.15 | 13.86 / 12.44 | 12.44 | 9.81–14.77 | +0.71 | +5.70% | 0 |  |
| australia-southeast1-c ↔ australia-southeast2-a | 15.37 | 15.16 / 15.58 | 15.25 | 14.50–19.25 | +0.12 | +0.78% | 0 |  |
| asia-southeast2-a ↔ asia-southeast1-b | 15.41 | 16.05 / 14.78 | 13.16 | 12.54–15.92 | +2.25 | +17.08% | 0 | UDP > TCP by >10% |
| europe-west2-b ↔ europe-west3-a | 20.94 | 19.52 / 22.36 | 18.82 | 13.84–24.96 | +2.12 | +11.25% | 0 | UDP > TCP by >10% |
| europe-west4-a ↔ europe-west3-a | 21.75 | 19.21 / 24.29 | 17.28 | 14.79–24.23 | +4.47 | +25.86% | 0 | UDP > TCP by >10% |
| asia-northeast2-a ↔ asia-northeast3-b | 28.44 | 28.47 / 28.41 | 31.03 | 27.89–34.74 | -2.59 | -8.34% | 0 |  |
| asia-east2-a ↔ asia-southeast1-b | 30.72 | 30.83 / 30.60 | 30.73 | 30.41–31.67 | -0.01 | -0.04% | 0 |  |
| asia-northeast1-b ↔ asia-northeast3-a | 32.45 | 32.43 / 32.46 | 32.56 | 32.13–33.23 | -0.11 | -0.35% | 0 |  |
| asia-northeast3-a ↔ asia-northeast1-c | 32.52 | 32.56 / 32.49 | 32.41 | 32.11–33.27 | +0.11 | +0.34% | 0 |  |
| asia-northeast1-c ↔ asia-northeast3-b | 32.53 | 32.52 / 32.54 | 32.15 | 31.61–33.17 | +0.38 | +1.17% | 0 |  |
| asia-northeast3-a ↔ asia-northeast2-a | 32.58 | 31.06 / 34.09 | 30.96 | 27.89–34.02 | +1.62 | +5.24% | 0 |  |
| asia-northeast1-b ↔ asia-northeast3-b | 33.02 | 33.32 / 32.73 | 32.56 | 32.00–33.74 | +0.46 | +1.42% | 0 |  |
| asia-east2-a ↔ asia-northeast3-b | 36.09 | 35.16 / 37.03 | 35.65 | 34.87–37.29 | +0.44 | +1.24% | 0 |  |
| asia-east2-a ↔ asia-northeast3-a | 37.47 | 37.49 / 37.45 | 36.29 | 35.03–38.44 | +1.18 | +3.25% | 0 |  |
| asia-southeast2-a ↔ asia-east2-a | 47.63 | 46.30 / 48.96 | 47.23 | 43.10–49.91 | +0.40 | +0.85% | 0 |  |
| asia-east2-a ↔ asia-northeast2-a | 50.09 | 52.91 / 47.26 | 49.80 | 43.51–55.55 | +0.29 | +0.58% | 0 |  |
| europe-west3-a ↔ me-west1-b | 53.67 | 53.92 / 53.42 | 53.86 | 53.04–55.26 | -0.19 | -0.35% | 0 |  |
| asia-northeast1-b ↔ asia-east2-a | 54.51 | 54.41 / 54.62 | 56.48 | 54.23–58.88 | -1.97 | -3.48% | 0 |  |
| europe-west2-b ↔ me-west1-b | 58.02 | 58.40 / 57.64 | 57.87 | 55.97–59.46 | +0.15 | +0.27% | 0 |  |
| asia-east2-a ↔ asia-northeast1-c | 58.26 | 57.23 / 59.29 | 58.15 | 54.27–59.90 | +0.11 | +0.19% | 0 |  |
| asia-south1-a ↔ asia-southeast1-b | 58.59 | 59.59 / 57.58 | 58.05 | 55.13–60.51 | +0.53 | +0.91% | 0 |  |
| europe-west4-a ↔ me-west1-b | 60.32 | 59.92 / 60.72 | 59.90 | 59.12–61.56 | +0.42 | +0.69% | 0 |  |
| asia-northeast1-b ↔ asia-southeast1-b | 66.38 | 66.99 / 65.77 | 66.28 | 65.49–68.00 | +0.10 | +0.15% | 0 |  |
| asia-southeast1-b ↔ asia-northeast1-c | 67.03 | 66.47 / 67.60 | 66.84 | 66.16–68.13 | +0.19 | +0.29% | 0 |  |
| asia-southeast1-b ↔ asia-northeast3-b | 69.46 | 69.33 / 69.58 | 68.70 | 65.71–71.33 | +0.76 | +1.10% | 0 |  |
| asia-northeast3-a ↔ asia-southeast1-b | 70.62 | 69.03 / 72.22 | 68.63 | 65.22–72.97 | +1.99 | +2.90% | 0 |  |
| asia-southeast2-a ↔ asia-south1-a | 72.85 | 72.64 / 73.06 | 71.96 | 67.28–78.21 | +0.90 | +1.24% | 0 |  |
| us-west2-a ↔ northamerica-northeast1-b | 75.11 | 74.78 / 75.44 | 74.39 | 72.59–75.86 | +0.72 | +0.97% | 0 |  |
| asia-southeast1-b ↔ asia-northeast2-a | 75.75 | 75.64 / 75.86 | 79.84 | 75.51–81.45 | -4.10 | -5.13% | 0 |  |
| asia-southeast2-a ↔ asia-northeast3-a | 81.05 | 81.90 / 80.19 | 82.02 | 78.99–84.79 | -0.97 | -1.18% | 0 |  |
| asia-southeast2-a ↔ asia-northeast3-b | 81.40 | 81.80 / 81.00 | 81.62 | 78.24–85.58 | -0.22 | -0.27% | 0 |  |
| asia-northeast1-b ↔ asia-southeast2-a | 86.88 | 87.37 / 86.39 | 88.02 | 85.53–91.61 | -1.14 | -1.29% | 0 |  |
| asia-southeast2-a ↔ asia-northeast1-c | 87.47 | 87.15 / 87.79 | 86.77 | 85.53–88.68 | +0.70 | +0.81% | 0 |  |
| asia-east2-a ↔ asia-south1-a | 88.16 | 89.12 / 87.20 | 87.40 | 85.10–89.42 | +0.76 | +0.87% | 0 |  |
| asia-southeast2-a ↔ asia-northeast2-a | 93.29 | 93.94 / 92.64 | 93.00 | 91.76–95.91 | +0.29 | +0.31% | 0 |  |
| northamerica-northeast1-b ↔ europe-west3-a | 100.27 | 101.11 / 99.44 | 118.67 | 99.34–137.42 | -18.39 | -15.50% | 0 |  |
| us-west2-a ↔ asia-northeast1-b | 100.31 | 100.50 / 100.13 | 100.15 | 99.75–101.44 | +0.16 | +0.16% | 0 |  |
| us-west2-a ↔ asia-northeast1-c | 100.34 | 100.38 / 100.29 | 100.16 | 99.70–101.44 | +0.17 | +0.17% | 0 |  |
| australia-southeast1-c ↔ asia-northeast2-a | 106.26 | 106.31 / 106.22 | 105.65 | 104.83–107.46 | +0.61 | +0.58% | 0 |  |
| us-west2-a ↔ asia-northeast2-a | 106.50 | 106.44 / 106.56 | 106.33 | 106.08–107.64 | +0.17 | +0.16% | 0 |  |
| northamerica-northeast1-b ↔ europe-west4-a | 107.63 | 108.00 / 107.26 | 103.07 | 98.82–113.95 | +4.56 | +4.43% | 0 |  |
| northamerica-northeast1-b ↔ europe-west2-b | 111.06 | 98.57 / 123.54 | 111.32 | 98.17–123.47 | -0.26 | -0.23% | 0 |  |
| asia-south1-a ↔ me-west1-b | 114.14 | 117.91 / 110.38 | 117.27 | 106.35–149.18 | -3.13 | -2.67% | 0 |  |
| australia-southeast1-c ↔ asia-northeast1-c | 115.58 | 110.02 / 121.13 | 116.21 | 108.00–121.21 | -0.64 | -0.55% | 0 |  |
| australia-southeast1-c ↔ asia-northeast1-b | 117.03 | 113.94 / 120.13 | 114.16 | 107.99–120.18 | +2.88 | +2.52% | 0 |  |
| asia-northeast1-b ↔ australia-southeast2-a | 117.18 | 118.84 / 115.52 | 117.21 | 115.39–121.68 | -0.03 | -0.02% | 0 |  |
| asia-northeast2-a ↔ australia-southeast2-a | 117.32 | 117.18 / 117.45 | 117.27 | 116.63–117.95 | +0.05 | +0.04% | 0 |  |
| australia-southeast2-a ↔ asia-northeast1-c | 119.46 | 118.15 / 120.77 | 118.75 | 115.70–122.20 | +0.72 | +0.60% | 0 |  |
| asia-south1-a ↔ asia-northeast3-b | 120.65 | 121.05 / 120.26 | 120.91 | 119.55–122.15 | -0.26 | -0.22% | 0 |  |
| asia-northeast1-b ↔ asia-south1-a | 120.67 | 120.79 / 120.55 | 121.58 | 120.27–124.08 | -0.91 | -0.75% | 0 |  |
| asia-northeast3-a ↔ asia-south1-a | 120.71 | 120.17 / 121.24 | 120.78 | 120.00–121.85 | -0.07 | -0.06% | 0 |  |
| asia-south1-a ↔ asia-northeast1-c | 122.12 | 122.84 / 121.40 | 122.63 | 120.79–125.27 | -0.51 | -0.42% | 0 |  |
| us-west2-a ↔ asia-northeast3-b | 126.34 | 126.42 / 126.26 | 126.21 | 125.95–127.45 | +0.13 | +0.10% | 0 |  |
| us-west2-a ↔ asia-northeast3-a | 126.77 | 126.74 / 126.80 | 126.47 | 126.04–127.65 | +0.30 | +0.24% | 0 |  |
| australia-southeast1-c ↔ asia-northeast3-a | 127.68 | 127.89 / 127.47 | 127.66 | 126.91–129.66 | +0.02 | +0.02% | 0 |  |
| australia-southeast1-c ↔ asia-northeast3-b | 127.89 | 127.91 / 127.87 | 127.49 | 126.88–128.98 | +0.40 | +0.31% | 0 |  |
| northamerica-northeast1-b ↔ southamerica-east1-a | 128.38 | 128.09 / 128.67 | 142.19 | 128.30–157.04 | -13.81 | -9.71% | 0 |  |
| northamerica-northeast1-b ↔ me-west1-b | 132.69 | 132.86 / 132.53 | 132.80 | 131.58–134.34 | -0.10 | -0.08% | 0 |  |
| asia-east2-a ↔ australia-southeast2-a | 134.26 | 134.81 / 133.71 | 133.95 | 133.03–135.41 | +0.31 | +0.23% | 0 |  |
| asia-south1-a ↔ asia-northeast2-a | 136.04 | 136.84 / 135.24 | 136.54 | 132.77–140.44 | -0.50 | -0.36% | 0 |  |
| us-west2-a ↔ europe-west2-b | 136.55 | 136.31 / 136.79 | 136.55 | 133.75–139.01 | +0.00 | +0.00% | 0 |  |
| us-west2-a ↔ australia-southeast1-c | 137.85 | 137.78 / 137.92 | 137.96 | 137.44–140.79 | -0.11 | -0.08% | 0 |  |
| australia-southeast2-a ↔ asia-northeast3-b | 139.51 | 139.57 / 139.46 | 139.59 | 138.83–142.04 | -0.08 | -0.06% | 0 |  |
| asia-south1-a ↔ europe-west3-a | 140.92 | 143.83 / 138.01 | 139.14 | 133.49–144.55 | +1.77 | +1.28% | 0 |  |
| asia-northeast3-a ↔ australia-southeast2-a | 141.28 | 140.06 / 142.51 | 139.93 | 139.01–142.82 | +1.35 | +0.97% | 0 |  |
| us-west2-a ↔ asia-east2-a | 143.36 | 143.34 / 143.38 | 143.14 | 142.79–144.18 | +0.22 | +0.15% | 0 |  |
| us-west2-a ↔ europe-west4-a | 148.78 | 149.04 / 148.53 | 149.28 | 146.72–151.38 | -0.50 | -0.33% | 0 |  |
| europe-west2-b ↔ asia-south1-a | 149.11 | 144.75 / 153.47 | 148.35 | 139.47–154.62 | +0.76 | +0.51% | 0 |  |
| us-west2-a ↔ australia-southeast2-a | 149.53 | 149.49 / 149.59 | 149.62 | 149.02–150.43 | -0.08 | -0.06% | 0 |  |
| us-west2-a ↔ europe-west3-a | 149.69 | 150.26 / 149.11 | 149.16 | 147.75–151.06 | +0.52 | +0.35% | 0 |  |
| australia-southeast1-c ↔ asia-east2-a | 151.35 | 151.46 / 151.25 | 174.56 | 127.72–175.49 | -23.21 | -13.30% | 0 |  |
| europe-west4-a ↔ asia-south1-a | 152.09 | 149.17 / 155.00 | 148.19 | 141.59–156.47 | +3.89 | +2.63% | 0 |  |
| asia-southeast1-b ↔ europe-west3-a | 158.30 | 157.27 / 159.33 | 157.03 | 154.39–159.42 | +1.27 | +0.81% | 0 |  |
| northamerica-northeast1-b ↔ asia-northeast1-c | 162.33 | 162.30 / 162.36 | 166.16 | 161.99–177.07 | -3.83 | -2.31% | 0 |  |
| australia-southeast1-c ↔ asia-southeast2-a | 163.10 | 163.11 / 163.08 | 165.42 | 161.55–174.43 | -2.33 | -1.41% | 0 |  |
| us-west2-a ↔ asia-southeast1-b | 163.88 | 163.89 / 163.88 | 165.65 | 163.18–168.52 | -1.77 | -1.07% | 0 |  |
| europe-west4-a ↔ asia-southeast1-b | 163.94 | 166.27 / 161.60 | 162.84 | 161.23–166.78 | +1.09 | +0.67% | 0 |  |
| us-west2-a ↔ southamerica-east1-a | 165.13 | 165.10 / 165.17 | 164.66 | 164.36–165.94 | +0.47 | +0.29% | 0 |  |
| asia-southeast1-b ↔ australia-southeast2-a | 165.39 | 162.96 / 167.81 | 162.87 | 161.26–172.91 | +2.52 | +1.54% | 0 |  |
| europe-west2-b ↔ asia-southeast1-b | 166.40 | 166.07 / 166.73 | 168.90 | 166.08–171.29 | -2.50 | -1.48% | 0 |  |
| asia-southeast2-a ↔ europe-west3-a | 169.37 | 169.08 / 169.65 | 168.66 | 166.51–171.77 | +0.70 | +0.42% | 0 |  |
| northamerica-northeast1-b ↔ asia-northeast1-b | 170.08 | 177.19 / 162.97 | 166.46 | 162.25–176.97 | +3.62 | +2.17% | 0 |  |
| us-west2-a ↔ asia-southeast2-a | 172.13 | 172.59 / 171.68 | 172.83 | 171.59–176.96 | -0.70 | -0.41% | 0 |  |
| asia-southeast2-a ↔ australia-southeast2-a | 174.13 | 174.08 / 174.17 | 174.86 | 173.34–176.98 | -0.73 | -0.42% | 0 |  |
| australia-southeast1-c ↔ asia-southeast1-b | 174.15 | 165.91 / 182.40 | 166.11 | 148.69–184.16 | +8.04 | +4.84% | 0 |  |
| europe-west4-a ↔ asia-southeast2-a | 175.30 | 176.21 / 174.40 | 175.78 | 173.56–178.12 | -0.48 | -0.27% | 0 |  |
| asia-southeast1-b ↔ me-west1-b | 176.25 | 177.88 / 174.63 | 170.46 | 161.91–179.39 | +5.79 | +3.40% | 0 |  |
| asia-southeast2-a ↔ me-west1-b | 179.15 | 180.86 / 177.44 | 180.90 | 174.27–192.75 | -1.75 | -0.97% | 0 |  |
| northamerica-northeast1-b ↔ asia-northeast2-a | 179.66 | 180.30 / 179.03 | 179.84 | 178.52–180.99 | -0.17 | -0.09% | 0 |  |
| europe-west2-b ↔ asia-southeast2-a | 180.34 | 180.29 / 180.39 | 180.62 | 177.81–183.86 | -0.28 | -0.15% | 0 |  |
| us-west2-a ↔ me-west1-b | 185.41 | 186.57 / 184.25 | 185.90 | 183.26–188.43 | -0.50 | -0.27% | 0 |  |
| asia-east2-a ↔ europe-west3-a | 188.32 | 185.86 / 190.77 | 187.83 | 185.19–194.20 | +0.49 | +0.26% | 0 |  |
| europe-west4-a ↔ asia-east2-a | 197.20 | 197.24 / 197.16 | 195.76 | 191.89–199.39 | +1.44 | +0.73% | 0 |  |
| asia-east2-a ↔ me-west1-b | 197.25 | 191.67 / 202.83 | 202.18 | 192.90–204.85 | -4.93 | -2.44% | 0 |  |
| northamerica-northeast1-b ↔ asia-northeast3-a | 199.51 | 199.31 / 199.70 | 199.78 | 198.72–200.93 | -0.27 | -0.14% | 0 |  |
| europe-west2-b ↔ asia-east2-a | 200.13 | 198.76 / 201.49 | 200.78 | 196.59–205.06 | -0.65 | -0.32% | 0 |  |
| northamerica-northeast1-b ↔ asia-northeast3-b | 200.15 | 199.81 / 200.49 | 199.80 | 198.85–200.92 | +0.35 | +0.17% | 0 |  |
| europe-west2-b ↔ southamerica-east1-a | 205.30 | 211.20 / 199.40 | 210.79 | 198.66–223.22 | -5.49 | -2.60% | 0 |  |
| europe-west4-a ↔ southamerica-east1-a | 214.84 | 213.62 / 216.07 | 211.24 | 199.91–216.14 | +3.60 | +1.70% | 0 |  |
| us-west2-a ↔ asia-south1-a | 216.27 | 216.00 / 216.54 | 218.79 | 213.47–227.05 | -2.52 | -1.15% | 0 |  |
| europe-west3-a ↔ asia-northeast3-b | 219.99 | 220.25 / 219.73 | 222.24 | 219.42–226.97 | -2.25 | -1.01% | 0 |  |
| asia-south1-a ↔ australia-southeast2-a | 220.00 | 220.23 / 219.78 | 218.73 | 216.89–220.41 | +1.28 | +0.58% | 0 |  |
| asia-northeast3-a ↔ europe-west3-a | 222.12 | 224.30 / 219.94 | 223.85 | 219.40–228.91 | -1.73 | -0.77% | 0 |  |
| northamerica-northeast1-b ↔ australia-southeast2-a | 222.79 | 222.39 / 223.20 | 222.69 | 221.75–224.11 | +0.11 | +0.05% | 0 |  |
| northamerica-northeast1-b ↔ asia-south1-a | 223.15 | 218.17 / 228.13 | 215.65 | 214.45–228.41 | +7.51 | +3.48% | 0 |  |
| northamerica-northeast1-b ↔ asia-east2-a | 224.48 | 224.44 / 224.53 | 224.47 | 224.05–226.91 | +0.01 | +0.01% | 0 |  |
| europe-west3-a ↔ southamerica-east1-a | 228.45 | 219.00 / 237.90 | 219.26 | 200.28–239.59 | +9.19 | +4.19% | 0 |  |
| europe-west4-a ↔ asia-northeast3-b | 230.69 | 229.79 / 231.60 | 230.59 | 226.77–233.83 | +0.10 | +0.04% | 0 |  |
| australia-southeast1-c ↔ asia-south1-a | 231.03 | 240.59 / 221.48 | 221.71 | 202.51–241.09 | +9.32 | +4.20% | 0 |  |
| europe-west4-a ↔ asia-northeast3-a | 231.96 | 229.01 / 234.90 | 231.52 | 226.28–235.02 | +0.43 | +0.19% | 0 |  |
| me-west1-b ↔ asia-northeast3-b | 232.82 | 228.17 / 237.48 | 227.94 | 224.77–239.28 | +4.88 | +2.14% | 0 |  |
| australia-southeast1-c ↔ northamerica-northeast1-b | 232.83 | 220.17 / 245.50 | 219.99 | 194.61–246.35 | +12.85 | +5.84% | 0 |  |
| asia-northeast3-a ↔ me-west1-b | 238.14 | 237.52 / 238.76 | 234.72 | 226.22–267.91 | +3.41 | +1.45% | 0 |  |
| southamerica-east1-a ↔ me-west1-b | 238.43 | 238.73 / 238.13 | 238.32 | 236.97–239.97 | +0.11 | +0.05% | 0 |  |
| europe-west2-b ↔ asia-northeast2-a | 241.66 | 241.50 / 241.83 | 242.10 | 240.22–245.23 | -0.43 | -0.18% | 0 |  |
| northamerica-northeast1-b ↔ asia-southeast2-a | 245.75 | 248.14 / 243.36 | 247.69 | 241.99–253.41 | -1.94 | -0.78% | 0 |  |
| asia-northeast1-b ↔ me-west1-b | 247.74 | 240.14 / 255.34 | 245.28 | 237.76–255.13 | +2.46 | +1.00% | 0 |  |
| northamerica-northeast1-b ↔ asia-southeast1-b | 251.00 | 254.38 / 247.63 | 250.72 | 246.40–254.20 | +0.29 | +0.12% | 0 |  |
| europe-west2-b ↔ asia-northeast1-c | 254.26 | 257.58 / 250.94 | 250.76 | 243.46–257.48 | +3.50 | +1.40% | 0 |  |
| europe-west4-a ↔ asia-northeast2-a | 255.17 | 255.15 / 255.20 | 253.56 | 252.31–255.92 | +1.62 | +0.64% | 0 |  |
| asia-northeast2-a ↔ europe-west3-a | 255.35 | 254.72 / 255.99 | 254.39 | 253.10–255.99 | +0.96 | +0.38% | 0 |  |
| europe-west2-b ↔ asia-northeast1-b | 257.32 | 257.04 / 257.59 | 250.40 | 242.83–257.88 | +6.92 | +2.76% | 0 |  |
| europe-west3-a ↔ asia-northeast1-c | 257.74 | 257.20 / 258.27 | 258.50 | 256.97–259.91 | -0.77 | -0.30% | 0 |  |
| asia-northeast1-b ↔ europe-west3-a | 257.87 | 257.60 / 258.15 | 257.78 | 257.13–258.64 | +0.10 | +0.04% | 0 |  |
| europe-west4-a ↔ asia-northeast1-b | 260.22 | 260.84 / 259.60 | 259.09 | 257.65–260.82 | +1.13 | +0.44% | 0 |  |
| europe-west4-a ↔ asia-northeast1-c | 260.50 | 259.41 / 261.58 | 258.65 | 257.80–261.53 | +1.85 | +0.71% | 0 |  |
| me-west1-b ↔ asia-northeast1-c | 261.07 | 242.34 / 279.80 | 242.97 | 236.20–279.76 | +18.10 | +7.45% | 0 |  |
| europe-west2-b ↔ asia-northeast3-a | 261.33 | 261.92 / 260.75 | 262.04 | 260.17–265.04 | -0.71 | -0.27% | 0 |  |
| europe-west2-b ↔ asia-northeast3-b | 263.74 | 263.23 / 264.25 | 261.70 | 259.61–266.00 | +2.04 | +0.78% | 0 |  |
| asia-northeast2-a ↔ me-west1-b | 265.40 | 243.78 / 287.02 | 248.03 | 242.12–288.23 | +17.37 | +7.00% | 0 |  |
| asia-northeast2-a ↔ southamerica-east1-a | 270.35 | 270.38 / 270.31 | 270.20 | 270.00–271.35 | +0.15 | +0.06% | 0 |  |
| asia-northeast1-b ↔ southamerica-east1-a | 279.21 | 279.05 / 279.37 | 279.03 | 276.19–286.40 | +0.18 | +0.07% | 0 |  |
| southamerica-east1-a ↔ asia-northeast1-c | 282.92 | 279.01 / 286.84 | 282.25 | 276.67–286.72 | +0.67 | +0.24% | 0 |  |
| southamerica-east1-a ↔ asia-northeast3-b | 290.28 | 290.26 / 290.31 | 290.23 | 289.76–291.38 | +0.06 | +0.02% | 0 |  |
| asia-northeast3-a ↔ southamerica-east1-a | 290.42 | 290.22 / 290.62 | 290.33 | 289.48–291.85 | +0.09 | +0.03% | 0 |  |
| australia-southeast1-c ↔ southamerica-east1-a | 304.57 | 304.56 / 304.59 | 332.90 | 304.10–363.23 | -28.32 | -8.51% | 0 |  |
| australia-southeast1-c ↔ europe-west3-a | 306.99 | 309.74 / 304.25 | 305.33 | 303.94–318.07 | +1.67 | +0.55% | 0 |  |
| australia-southeast2-a ↔ southamerica-east1-a | 313.78 | 314.05 / 313.51 | 313.63 | 312.79–314.80 | +0.15 | +0.05% | 0 |  |
| australia-southeast1-c ↔ europe-west2-b | 314.00 | 301.01 / 326.99 | 300.92 | 274.53–327.03 | +13.08 | +4.35% | 0 |  |
| australia-southeast1-c ↔ europe-west4-a | 314.93 | 313.35 / 316.50 | 312.42 | 310.08–319.78 | +2.51 | +0.80% | 0 |  |
| australia-southeast1-c ↔ me-west1-b | 316.08 | 316.11 / 316.06 | 320.21 | 311.62–352.77 | -4.13 | -1.29% | 0 |  |
| australia-southeast2-a ↔ europe-west3-a | 316.41 | 316.24 / 316.57 | 317.66 | 315.70–324.09 | -1.25 | -0.40% | 0 |  |
| europe-west4-a ↔ australia-southeast2-a | 323.89 | 323.12 / 324.65 | 325.63 | 322.68–334.59 | -1.74 | -0.53% | 0 |  |
| asia-south1-a ↔ southamerica-east1-a | 327.41 | 320.42 / 334.40 | 321.10 | 320.09–334.24 | +6.31 | +1.96% | 0 |  |
| australia-southeast2-a ↔ me-west1-b | 327.75 | 325.62 / 329.88 | 328.07 | 322.42–361.13 | -0.32 | -0.10% | 0 |  |
| europe-west2-b ↔ australia-southeast2-a | 330.95 | 333.53 / 328.38 | 331.55 | 326.60–340.27 | -0.60 | -0.18% | 0 |  |
| asia-east2-a ↔ southamerica-east1-a | 333.81 | 333.79 / 333.82 | 333.70 | 333.40–335.04 | +0.11 | +0.03% | 0 |  |
| asia-southeast2-a ↔ southamerica-east1-a | 341.50 | 339.50 / 343.50 | 338.04 | 335.31–343.40 | +3.46 | +1.02% | 0 |  |
| asia-southeast1-b ↔ southamerica-east1-a | 357.45 | 357.43 / 357.47 | 356.69 | 349.27–363.35 | +0.76 | +0.21% | 0 |  |
