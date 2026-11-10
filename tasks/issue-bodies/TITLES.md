# Bench-5 issue titles

Creation order, slug, and the title to pass to `gh issue create --title`. Five H1s are longer than the 120-character
limit; for those the title column is a shortened form and the verbatim H1 is listed under it. Lengths are in characters.

| order | slug | title | length |
|---|---|---|---|
| 1 | f1-commit-lag-demotion | A validator a few per cent slower at execution is demoted under load, because its commit waits on its own execution | 115 |
| 2 | f2-execution-ceiling | Engine execution caps chain throughput at about 215 µs per transaction | 70 |
| 3 | f3-rejoin-loop | A promoted validator cannot rebuild its DAG mid-epoch, so it loops between promotion and demotion until the next epoch | 118 |
| 4 | persist-fsync-amplification | MDBX WRITEMAP commit dirties whole large page-cache folios: about 4× bench 4's device bytes per transaction | 107 |
| 5 | far-validator-certificate-inclusion | At light load the two European validators drift behind the round and most of their certificates are never committed | 115 |
| 6 | execution-behind-vote-starvation | Under load the fastest executors' headers are refused as execution-behind, so up to f validators lose every certificate | 119 |
| 7 | execution-lag-feedback | A lagging node's signer-recovery jobs land on top of its own block builds, so the lag feeds itself | 98 |
| 8 | loaded-epoch-boundary-drain | A loaded epoch close waits for the seventh-fastest validator's execution backlog; slower members miss the epoch record | 118 |
| 9 | sealed-tx-invisible-drops-and-duplicates | A sealed transaction leaves the pool and the RPC, so a skipped one waits 5 minutes for a resend and a resend runs twice | 119 |

## Verbatim H1s that were shortened

- f1-commit-lag-demotion (139): A validator whose execution is a few per cent slower than the quorum's is demoted under load, because its commit waits on its own execution
- far-validator-certificate-inclusion (192): At light load the two European validators drift a little further behind the round every round, so most of their certificates are never committed and their users wait about 20 s per transaction
- execution-behind-vote-starvation (121): Under load the fastest executors' headers are refused as "execution behind", so up to f validators lose every certificate
- loaded-epoch-boundary-drain (229): A loaded epoch close waits for the seventh-fastest validator to drain its execution backlog; the slower members miss the epoch record, overflow the closing epoch's task tracker and enter the next epoch one round short of demotion
- sealed-tx-invisible-drops-and-duplicates (130): A sealed transaction leaves the pool and the RPC, so a skipped one waits five minutes for a resend and a resent one executes twice

## Cross-references between bodies

Forward references (a body naming a slug created later in the order): none. Every body can be created in one pass and
needs no second edit for its issue placeholders.

Backward references (resolved at creation time, since the target already exists):

| body | references |
|---|---|
| f1-commit-lag-demotion | none |
| f2-execution-ceiling | none |
| f3-rejoin-loop | none |
| persist-fsync-amplification | f2-execution-ceiling |
| far-validator-certificate-inclusion | none |
| execution-behind-vote-starvation | f3-rejoin-loop |
| execution-lag-feedback | execution-behind-vote-starvation, f2-execution-ceiling, persist-fsync-amplification |
| loaded-epoch-boundary-drain | f1-commit-lag-demotion (×2), f2-execution-ceiling, f3-rejoin-loop, execution-lag-feedback (×2) |
| sealed-tx-invisible-drops-and-duplicates | execution-behind-vote-starvation (×3) |
