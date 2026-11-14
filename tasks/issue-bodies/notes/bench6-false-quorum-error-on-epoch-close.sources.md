# Sources: bench6-false-quorum-error-on-epoch-close.md (not for posting)

Private abbreviations: E4 = benchmark/private/bench6-r20261113-1351/E-4/findings.md; R6 = tasks/bench6-report-r20261113-1351.md; A3a3 = benchmark/private/bench6-r20261113-2118/A3a/closes.md; DRE = benchmark/private/bench7-prep/DR-E/findings.md; M = telcoin-network 45dce8947 (`git show 45dce8947:<path>`).

| claim / figure | source |
|---|---|
| round ends without quorum after the collector stored the cert; handler drops further votes; gives up about 65 s later | E4 :14, :118; R6 :421-422; M handler.rs:866-915, epoch_votes.rs:27-34, :152-157 (own read) |
| 11 times: 7 in r20261112-1520 (observer e16 included), 3 in r20261113-1351, 1 in r20261113-1630 | E4 :14, :117; R6 :421 |
| collector stored the cert 0.1-4.5 s after the first quorum line; error 64.5-65.0 s after that; recovery fetched the same hash 0.07-0.29 s later | E4 :118 |
| adaptive runs: 3 in r20261113-2118, 1 in r20261114-0000, each after the node had fetched the certified record | A3a3 :125-128 (run 3: v03, v04, v05 at epoch 3, fetched at 15.1-16.1 s), :215-217 (run 3b: v04 at epoch 7, fetched at 13.59 s) |
| bench-6 build's vote round and vote-drop rule are main's | DRE Q5 (:19) "Unchanged in substance ... the false quorum error is raised at epoch_votes.rs:231-237"; bench-6 path E-2 :111-113, E4 :133 |
| error at epoch_votes.rs:231-237, no store check | M epoch_votes.rs:222-238 (own read); DRE §5 (:93) |
| signer gauge set at :238 (fn :622-624) | M epoch_votes.rs:238, :616-624 (own read) |
| 1 to 5 signers in the error lines | R6 :422 ("1-5 votes it had"); A3a3 :126 (4-5 signers), :217 (1 signer) |
| recovery fetch :239-323 | M epoch_votes.rs:239-324 (own read) |
| 26 timed-out 2.5 s waits | M epoch_votes.rs:27 (2500 ms), :34 (MAX_EPOCH_VOTE_TIMEOUTS = 24), :152-157 (break when timeouts > 24, else +1: 26th timeout breaks; the doc at :29-33 says up to +2 windows); error lines show timeouts=25 (A3a3 :126) |
| handler forwards only while record held uncertified | M consensus/primary/src/network/handler.rs:866-915 (own read) |
| cert_by_digest at epoch_records.rs:898 | `git grep -n "fn cert_by_digest" 45dce8947 -- crates/storage` |
| fix shape (check first, info + count, error unchanged otherwise) | tasks/bench7/briefs/e2.md item 3; design §B "Always on" (:99-102) |
| "the same check can skip the signer gauge" | own suggestion, not in E2's brief: flagged to the orchestrator |
| test_failed_round_sets_signer_gauge at :2225 | M epoch_votes.rs:2225 (grep); DRE §7 (:113) |

## Revision after the figure-check (tasks/bench7/figcheck-UI1.md, text 3)

| changed sentence | source |
|---|---|
| fix paragraph: "Whether the signer gauge at `:238` should also skip such a round is open: main sets it on every failed round by design (`:616-621`)." replaces "The same check can skip the signer gauge at `:238`." | M epoch_votes.rs:616-621 (doc: "A round that fails to reach quorum sets it too"); tasks/bench7/briefs/e2.md item 3 ("Nothing else in the vote round changes"); figcheck :92 |
| evidence: "7 in an arm walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by rolling restart; it has no public page), the observer's round among them" | R6 :89, :99; E4 :117 (observer e16); figcheck :34, :93; coordinator instruction 5 |

Cut for length (no new claims): the last "How to verify" sentence ("In a benchmark run, no such error appears for an epoch the network certified.").
