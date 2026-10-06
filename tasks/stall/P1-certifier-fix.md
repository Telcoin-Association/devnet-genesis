status: done
branch: fix/certifier-keep-inflight-on-repropose (from main d89566e1d) in /Users/grant/coding/telcoin/telcoin-network
commits (not pushed):
- 9b4bca750 fix(primary): keep vote collection when the same header is re-sent  (certifier.rs + certifier_tests.rs)
- 963b59980 fix(primary): log the max header delay in force  (proposer.rs)

completed sections:
- S0 setup, S1 read, S2 certifier fix, S3 proposer log (calc_max_delay), S4 tests (3 new, negative control fails w/o fix)
- S5 fmt --check OK (nightly-2026-03-20); clippy -p tn-primary --all-targets --all-features -D warnings clean;
  nextest -p tn-primary: 290 run, 290 passed (2 leaky under load, clean in isolation), 2 skipped.
- S6 committed; report returned to orchestrator
