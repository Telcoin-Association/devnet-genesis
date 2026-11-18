# Sources: l2-node-record-api-standalone-build

| Item in the draft | Source | Status |
|---|---|---|
| Title, row 28 | `tasks/challenges-l2.md` row 28; report section 4 | checked |
| Build command, 19:37:25-19:40:33 UTC, exit 1 | `tasks/l2/facts/image-probes.md:15-17` | checked |
| Error lines `SealedHeader: serde::Serialize` at `notify.rs:87:24`, `Deserialize<'de>` at `:90:14` (x2) and `:87:35` | `grep -nE 'error\[\|-->' tasks/l2/img-nra.log` -> lines 1113-1114, 1144-1145, 1171-1172, 1198-1199 | checked |
| `could not compile tn-network-types (lib) due to 4 previous errors` | `tasks/l2/facts/image-probes.md:17` (quoted there from the log) | checked (not re-grepped in the log itself) |
| Node and gateway images built from the same tree without error | `tasks/l2/facts/image-probes.md:11-14` (both exit=0) | checked |
| `crates/network-types/src/notify.rs:87-90` derive + `pub tip: SealedHeader`; import at `:6` | `git -C telcoin-network show 5533ff73a:crates/network-types/src/notify.rs \| sed -n '80,92p'`; `git grep -n SealedHeader` | checked; row 28's `notify.rs:87-90` matches |
| `crates/network-types/Cargo.toml:19` `tn-types = { workspace = true }` | `git show 5533ff73a:crates/network-types/Cargo.toml \| grep -n` | checked |
| Root `Cargo.toml:144` `reth-primitives-traits = { path = "vendor/reth/crates/primitives-traits" }` | `git grep -nE '^reth-primitives-traits' 5533ff73a -- Cargo.toml` | checked |
| `bin/node-record-api/Dockerfile:48` `cargo build -p tn-node-record-api --bin node-record-api --release` | `git show 5533ff73a:bin/node-record-api/Dockerfile \| sed -n '44,50p'`; row 28 cites `:48` | checked; matches |
| No CI or Makefile names node-record-api | `git grep -n -iE 'gateway\|node-record' 5533ff73a -- .github/ Makefile` (only Makefile:191, gateway comment) | checked |
| `SealedHeader` is reth's, serde via a feature | inference from the compiler note "check whether the crate offers a `serde` feature flag" (`img-nra.log:1123`) | not verifiable here (not traced) |
