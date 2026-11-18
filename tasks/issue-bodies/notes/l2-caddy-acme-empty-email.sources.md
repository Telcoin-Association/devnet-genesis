# Sources: l2-caddy-acme-empty-email

TND = /home/drtnarg/coding/telcoin/tn-node-deployment, M = origin/main (2813343), P = 79fb24e78356a93a9b48f3b472a4fc10e41bb1ee (PR #68 head). DG = devnet-genesis.

| Item in the draft | Source | Status |
|---|---|---|
| Claim: empty email, a failed renewal warns nobody | `tasks/challenges-l2.md` row 54; report section 2.7 | checked against the journal and code below; "warns nobody" qualified (see last rows) |
| Journal line `"msg":"creating new account because no account for configured email is known to us","email":"","ca":"https://acme-v02.api.letsencrypt.org/directory"`, twice | DG `tasks/l2/w3/d3a/s13-node1-caddy.txt` lines 1-2 (`grep -rn -F '"email":""' tasks/l2/`, `cut -c120-520`) | checked |
| 01:14:07 UTC on 2026-11-18 | same lines: syslog prefix `Nov 18 01:14:07`; JSON `ts` 1794964447.519 decoded with `date -u -d @1794964447` = Wed Nov 18 01:14:07 UTC 2026 | checked |
| `"msg":"certificate obtained successfully"`, issuer `acme-v02.api.letsencrypt.org-directory` | same file, line 3 | checked |
| Step window 01:13-01:16 UTC, `setup-gateway.sh --enable --yes --json --mode same-host --network devnet … --front caddy` | DG `tasks/l2/w3/d3a/as-run.md:19` (grep) | checked |
| `setup-gateway.sh` not on `main` | `git -C TND cat-file -e origin/main:setup-gateway.sh` fails | checked |
| Exact scripts commit installed on the devnet | not re-read | not verifiable here |
| `install-caddy.sh:815` `caddy_write_managed`, global block `:824-827` (M) | `git -C TND show M:install-caddy.sh \| sed -n '806,834p'`; line 818 anchored by `git grep` (`tmp="$(mktemp ...`) | checked |
| Same function `:882`, global block `:891-894` (P) | `git show P:install-caddy.sh \| sed -n '876,884p;888,906p'`; line 885 anchored by `git grep` | checked |
| No `email` line in `install-caddy.sh` at M or P | `git grep -n -i -E "email\|acme" <ref> -- install-caddy.sh` (only ACME comment lines and a note, no email) | checked (both refs) |
| No certificate expiry check in `check-node.sh`, `install-caddy.sh`, `lib/common.sh` (M) | `git grep -n -i -E "cert.*expir\|expir.*cert\|notAfter\|enddate" origin/main -- ...` (no hit) | checked at M only |
| Let's Encrypt ended expiry notification emails in 2025 | outside knowledge | not verifiable here |
| Other Caddy hosts' journals | not read | not verifiable here |
| Row 54 cites `install-caddy.sh` without a line | the managed Caddyfile is written by `caddy_write_managed` | checked |
