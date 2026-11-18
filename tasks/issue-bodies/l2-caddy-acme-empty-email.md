# install-caddy.sh sets no ACME email, so Caddy's Let's Encrypt account has no contact and a failed renewal alerts no one

The Caddyfile that `install-caddy.sh` writes has a global block with `admin` only, so Caddy registers its ACME account with `"email":""`.
Every operator whose host runs Caddy from these scripts meets it: the dashboard and public RPC sites on `main`, and the worker gateway site PR #68 adds.

## What happens

When the worker gateway's Caddy site was installed on validator-1-devnet, Caddy's journal logged, twice at 01:14:07 UTC:

```
"msg":"creating new account because no account for configured email is known to us","email":"","ca":"https://acme-v02.api.letsencrypt.org/directory"
```

followed by `"msg":"certificate obtained successfully"` for the host's public name, issuer `acme-v02.api.letsencrypt.org-directory`.

The certificate was issued. The account behind it has no contact address, and nothing in the scripts checks how long a served certificate has left.
A renewal that fails would show only in Caddy's journal on that host.

## Evidence

- Live run on 2026-11-18, 01:13-01:16 UTC, on a devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis).
- Host: validator-1-devnet, a genesis validator with its worker gateway on the same host, installed by `setup-gateway.sh --enable --yes --json --mode same-host --network devnet … --front caddy`.
  `setup-gateway.sh` is not on `main`, so this ran PR #68's code; the exact commit installed was not re-read here.
- Journal excerpt: devnet-genesis `tasks/l2/w3/d3a/s13-node1-caddy.txt` (three lines); the step: `tasks/l2/w3/d3a/as-run.md:19`.
- Seen on one host. The journals of the other Caddy hosts (the second gateway host, the public RPC node) were not read.

## Where in the code

- `origin/main` (2813343), `install-caddy.sh:815` `caddy_write_managed`: the global options block is written at `:824-827` as `{`, `admin ${CADDY_ADMIN_ADDR}`, `}`.
- PR #68's head (79fb24e), the same function at `:882`, the same global block at `:891-894`; the PR adds a third, gateway block after the RPC block.
- `git grep -i email` finds no line in `install-caddy.sh` at either commit.
- At `main`, `check-node.sh`, `install-caddy.sh` and `lib/common.sh` have no certificate expiry check (`git grep -i -E "cert.*expir|notAfter|enddate"`: no hit). Not checked at the PR head.

## What is not known

- Whether an email would bring a warning at all: Let's Encrypt announced the end of its expiry notification emails in 2025 (outside knowledge, not verified here). If so, an email gives the account a contact for policy and revocation notices, and an expiry warning has to come from the host.
- Whether Caddy would add a second issuer once an email is set (not checked).
- What Caddy logged on the other hosts.

## What could be done (suggestions, none tried)

- Take an email in `install-caddy.sh` (flag and prompt) and write `email <address>` into the global block beside `admin`; refuse to continue without one off devnet.
- Add a check to `check-node.sh` that reads the served certificate's expiry and warns some days ahead, so a failed renewal is seen before the certificate lapses.

## Related

- PR #68 writes the worker gateway's site into the same Caddyfile through `caddy_write_managed` and leaves the global block as it is.
- {{healthcheck-bare-port-binds-loopback}}: another case where the host's own view says all is well while outside callers fail.
