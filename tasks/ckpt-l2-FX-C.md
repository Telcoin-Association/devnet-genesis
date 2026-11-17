status: done
unit: FX-C
updated: 2026-11-17T21:12:23Z
completed sections:
- M1 finalize (FX-C/fin out/m1-norpc-*, full-*)
- M2 finalize _maps_fresh (out/m2-stale.*, full-*)
- L6 finalize header
- finalize bench cmp out/bench-* same
- M3 network-config (FX-C/nc out/m3-*)
- L4 network-config --verify scratch render (out/l4-*)
- network-config bench cmp b1..b5 same
- L1 keygen rpc branch (FX-C/kg gw0/dev/bench)
- L5 release-sign TN_GATEWAY_ENABLE (FX-C/rs/t.sh)
- L3 left (not one line; header documents the own count)
- gates: bash -n 0, shellcheck before/after 0/0,0/0,1/1,0/0, portability 0 x4
- bench unittests: test_finalize_modes, test_network_config, test_keygen all exit 0
pending: none (hand-back sent)
