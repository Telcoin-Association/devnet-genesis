# bin/node-record-api does not build on its own: SealedHeader is not serde::Serialize without feature unification.

At 5533ff73a, `cargo build -p tn-node-record-api` fails in `tn-network-types`, because a serde derive there needs `SealedHeader: Serialize`, which only another crate's feature provides.
Anyone building the node-record-api image meets it: `bin/node-record-api/Dockerfile` builds the package alone and stops with exit 1. The node build hides the missing bound, since its other crates turn the feature on.

## What happens

- `docker buildx build -f bin/node-record-api/Dockerfile --platform linux/amd64 --load .` at 5533ff73a failed after about three minutes:
  ```
  error[E0277]: the trait bound `SealedHeader: serde::Serialize` is not satisfied
      --> crates/network-types/src/notify.rs:87:24
  error[E0277]: the trait bound `SealedHeader: serde::Deserialize<'de>` is not satisfied
      --> crates/network-types/src/notify.rs:90:14
  ```
  Four errors in all (one `Serialize`, three `Deserialize`, at `:87:24`, `:87:35` and twice `:90:14`), ending with `could not compile tn-network-types (lib) due to 4 previous errors`.
- The node image (`etc/Dockerfile`) and the worker-gateway image built from the same tree, in the same session, without error.
- So no node-record-api image of this commit could be made for the devnet run.

## Evidence

- Build on 2026-11-17, 19:37:25 to 19:40:33 UTC, on the operator's build host, exit 1. Full log: devnet-genesis `tasks/l2/img-nra.log` (errors from line 1113); summary in `tasks/l2/facts/image-probes.md`.
- No CI workflow or `Makefile` target at 5533ff73a names `node-record-api` (`git grep -n -iE 'gateway|node-record' 5533ff73a -- .github/ Makefile`), so nothing in CI builds the package alone. Read from code, not run.
- `cargo build -p tn-network-types` alone was not run; the failure is shown only through the Dockerfile's build.

## Where in the code

At 5533ff73a:

- `crates/network-types/src/notify.rs:87-90`: `CanonicalUpdateMessage` derives `Serialize, Deserialize` and holds `pub tip: SealedHeader`, imported from `tn_types` (`:6`).
- `crates/network-types/Cargo.toml:19`: `tn-types = { workspace = true }`, with no feature that would bring serde support for `SealedHeader`.
- The root `Cargo.toml:144`: `reth-primitives-traits` is a path dependency on the vendored reth, with no features set there.
- `bin/node-record-api/Dockerfile:48`: `cargo build -p tn-node-record-api --bin node-record-api --release`, which resolves features for this package only.

## What is not known

- Which type `tn_types::SealedHeader` is, and which crate's feature makes it serde-capable in the node build. Inferred to be reth's sealed header with its `serde` feature; not traced.
- Whether `tn-network-types` fails on its own too (`cargo check -p tn-network-types`), or only in node-record-api's dependency set. Not run.
- Whether other packages under `bin/` have the same gap.

## What could be done (suggestions, none tried)

- Declare the feature where it is used: give `tn-network-types` (or `tn-types`) the dependency feature that makes `SealedHeader` serde-capable.
- Add a CI step that builds or checks each binary package alone (`cargo check -p <pkg>` for every package under `bin/`), so a bound that only unification satisfies fails in CI rather than in an image build.

## Related

- {{publish-worker-gateway-image}}: the other `bin/` image with no build in CI.
