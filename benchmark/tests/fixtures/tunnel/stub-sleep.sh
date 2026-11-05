#!/usr/bin/env bash
# Stand-in for sleep (test_tunnel.py): returns at once, so the supervisor's 3-s restart delay and
# bench_tunnel_up's 3-s polls cost nothing. Each call is counted in $FAKE_ROOT/sleeps.
echo "$*" >> "${FAKE_ROOT:?}/sleeps"
exit 0
