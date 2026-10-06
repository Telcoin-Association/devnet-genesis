# gs://tn-devnet-benchmark-archive vs local results

Generated 2026-10-06T18:00:49Z by tasks/archive/verify.sh (read-only). Local root: `/Users/grant/coding/telcoin/devnet-genesis/benchmark/results`.

**Verdict:** SAFE TO DELETE: all 319 archive objects have an identical local copy (size and MD5).

| count | what |
|---:|---|
| 319 | objects in the bucket (505878751 bytes, 482.4 MiB; runs: r20261006-0458) |
| 319 | matched: local file of the same size and MD5 |
| 0 | size mismatch |
| 0 | MD5 mismatch (same size) |
| 0 | missing locally |
| 0 | object outside runs/<run>/results or runs/<run>/bucket |
| 0 | local-only (in results/<run>/, not in the archive) |
| 20 | local-only that the archive's exclude rule never took (genesis*/, tunnel.pid, dot-files) |

`gcloud storage ls -r -l` agrees (319 objects).

## Local-only, never archived by rule

- `r20261006-0458/.DS_Store`
- `r20261006-0458/blast-1-20261006T060052Z/.DS_Store`
- `r20261006-0458/meta/.DS_Store`
- `r20261006-0458/blast-0-20261006T055536Z/.DS_Store`
- `r20261006-0458/funder-0-20261006T055335Z/.DS_Store`
- `r20261006-0458/funder-1-20261006T055856Z/.DS_Store`
- `r20261006-0458/genesis/.DS_Store`
- `r20261006-0458/genesis/genesis.yaml`
- `r20261006-0458/genesis/committee.yaml`
- `r20261006-0458/genesis/validators/bench01.yaml`
- `r20261006-0458/genesis/validators/bench06.yaml`
- `r20261006-0458/genesis/validators/bench10.yaml`
- `r20261006-0458/genesis/validators/bench07.yaml`
- `r20261006-0458/genesis/validators/bench04.yaml`
- `r20261006-0458/genesis/validators/bench08.yaml`
- `r20261006-0458/genesis/validators/bench09.yaml`
- `r20261006-0458/genesis/validators/bench05.yaml`
- `r20261006-0458/genesis/validators/bench02.yaml`
- `r20261006-0458/genesis/validators/bench03.yaml`
- `r20261006-0458/genesis/observers/bench11.yaml`

## Buckets in the project

```
NAME                         LOCATION  LABELS
tn-devnet-benchmark-archive  US-WEST2  {'purpose': 'bench-archive', 'retain': 'true'}
tn-devnet_cloudbuild         US
```
