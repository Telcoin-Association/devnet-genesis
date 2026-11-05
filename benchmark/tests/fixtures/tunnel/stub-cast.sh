#!/usr/bin/env bash
# Stand-in for foundry's cast (test_tunnel.py): `cast chain-id --rpc-url <url>` answers once
# $FAKE_TUNNEL_LOG holds a `tunnel: start` line (the tunnel is up), else fails as an unreachable
# RPC does. Anything else fails.
[ "${1:-}" = chain-id ] || { echo "stub cast: unexpected arguments: $*" >&2; exit 2; }
grep -q '^tunnel: start ' "${FAKE_TUNNEL_LOG:?}" 2>/dev/null || { echo "error sending request" >&2; exit 1; }
echo 2017
