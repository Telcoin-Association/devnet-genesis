# Bench-6 issue titles

Creation order, slug, and the title passed to `gh issue create --title` by `tasks/bench7/orch-gh-post.sh issue <slug>`.
Bodies: `tasks/issue-bodies/bench6-<slug>.md`. Every title is the body's H1 and at most 120 characters.

| order | slug | title | length |
|---|---|---|---|
| 1 | epoch-record-collector-gaps | An epoch the network never certifies stops every record collector there; a conflicting certified record is only logged | 118 |
| 2 | epoch-record-closing-block-check | An epoch record is saved and voted with no check that its final_state is the block that ran the closing calls | 109 |
| 3 | false-quorum-error-on-epoch-close | A node logs "failed to reach quorum on epoch close" as an error about 65 s after it already holds the certificate | 113 |
| 4 | execute-and-persist-in-series | Execute and persist run in series, so off the disk's write limit the persist is part of the throughput ceiling | 110 |
| 5 | inflight-bound-measurements | RPC admission ignores the execution backlog, so under load transactions queue behind the engine, not at the sender | 114 |
| 6 | restart-between-closing-block-and-record | A node stopped after executing epoch 0's closing block and before writing record 0 cannot restart from that datadir | 115 |
| 7 | rejoin-under-sustained-load | A validator restarted under sustained load stayed inactive until the load ended: it replays at about the network's rate | 119 |
| 8 | newepoch-event-not-readable-over-rpc | The registry's NewEpoch event never reaches eth_getLogs, and the docs do not say so | 83 |

## Cross-references between bodies

- epoch-record-closing-block-check references {{epoch-record-collector-gaps}} (created before it).
- inflight-bound-measurements references {{execute-and-persist-in-series}} (created before it).
- The comment on #1806 references {{epoch-record-closing-block-check}}, {{epoch-record-collector-gaps}} and {{false-quorum-error-on-epoch-close}}; the write-up `tasks/bench6-not-carried-writeup.md` references {{epoch-record-closing-block-check}} and {{execute-and-persist-in-series}}.
