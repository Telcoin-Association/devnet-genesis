# Sources: bench6-epoch-record-collector-gaps.md (not for posting)

Private abbreviations: E4 = benchmark/private/bench6-r20261113-1351/E-4/findings.md; DRE = benchmark/private/bench7-prep/DR-E/findings.md; R6 = tasks/bench6-report-r20261113-1351.md; VS = benchmark/private/bench6-r20261113-2118/A3a/vs-always-on.md; M = telcoin-network 45dce8947 (`git show 45dce8947:<path>`).

| claim / figure | source |
|---|---|
| every running node held every certified record within seconds | E4 "The answer" (:8-16), §2 (:114-121) |
| G1/G2 never reached, read from code | E4 :17-19, "Not known" (:222); DRE §5-§6 re-read on M |
| 7 of 10 (super-quorum) | M epoch_votes.rs:102 (`epoch_rec.super_quorum()`); R6 :414 ("at least 7 members") |
| vote window about 65 s | M epoch_votes.rs:27-34 (2.5 s wait; doc: up to MAX_EPOCH_VOTE_TIMEOUTS + 2 = 26 windows), :152-157; consistent with the measured 64.5-65.0 s (E4 :118). Bench-6 docs say "about 62.5 s" (E-2 :111); main's own doc and the measurement give 26 x 2.5 s = 65 s |
| collector stops at K, never asks K+1; startup sync same walk; restart no help | M state-sync/src/epoch.rs:228-370 (:243-264, :343-345), :391-419, :94-211; DRE §5 (:88-89); E4 :180-183 |
| peers serve a record only with its certificate | M consensus/primary/src/network/handler.rs:1909-1919 (own read) |
| validator still gets later certs through own rounds; node with no round (observer behind) or failed fetch gets none | E4 §4 (:181-183), §3 "P1/P2" rows (:133-134); M epoch_votes.rs:230-323 |
| K re-voted once more at close K+1; at restart only while latest | M epoch_votes.rs:483-502, :563-578 (own read); DRE §4 (:84), §6 (:105) |
| main's comment: "N certified, N-1 uncertified" not healed | M epoch_votes.rs:552-558 (own read) |
| fresh node: established (collector stops at K; full pack needs stored record; partial pack needs record K+j-1) / undetermined (header walk) | DRE §6 (:96-105), "Could not determine" (:159-160); M state-sync/src/consensus.rs:302-354 (own read) |
| execution does not need K's certificate | DRE §6 (:98) |
| G2: refused, logged at error, asked again each pass; node runs on | M state-sync/src/epoch.rs:279-285, :216-218; storage/src/epoch_records.rs:2707, :2721-2727 (own read); DRE §5 (:90); E4 §3 (:144-146) |
| vote-round recovery stops the node on other digest | M epoch_votes.rs:279-289 (own read) |
| three runs, ten validators + observer; arm walk nine configurations | R6 :96-98; E4 :11 |
| bench-6 collector walk/refusal = main's; #1841 removed the pass gate | DRE Q4/Q5 (:18-19), §4 (:80); M epoch.rs:392-399 comment |
| 403 of 407 cells; 373 own round, 28 collector (14+14), 2 startup sync; 4 = v01-v04 stopped before r20261112-1520's last close | E4 :11-13, :122 |
| longest lack 5.47 s (observer, run 1 epoch 4); 3.86 s runs 2 and 2b | E4 :120 |
| adaptive runs: all eleven nodes held every record | VS :37 (run 3), :124 (run 3b) |
| r20261113-1630 18:22:19 close exactly 7 votes, one down, two 13-15 s late | E4 :179; R6 :404, :407 |
| r20261114-0000 epoch 7 first quorum on exactly 7 | VS :122 ("loaded closes whose first quorum formed on exactly 7 votes ... 1 (epoch 7)") |
| no metric reports certificates held | E4 :192 |
| tests :651, :798 pin G2; no test leaves an epoch uncertified | DRE §5 (:90), §7 (:114); M state-sync/src/epoch.rs:651, :700, :798 (grep) |
| fix shape (walk past own uncertified K + retry list; protocol decision for nodes without K; re-certify with kept votes; G2 fail-stop + counter; gauge + serving peer; switches for the first three) | design-epoch-record-hardening.md §B (:61-102); DRE "Changes to the design" E2-E4 (:129-153), switch recommendation (:153); tasks/bench7/briefs/e2.md items 1-2 |
| gauge within ~10 s of first quorum as a check | E4 Options 3 (:229) |

Dropped for length: the collector cadence (1,412-1,592 and 5,382-5,683 `failed to retrieve epoch from a peer` lines, median gap 5.39 s; E4 :124); the absent-string list (E4 :123).

## Revision after the figure-check (tasks/bench7/figcheck-UI1.md, text 2)

| changed sentence | source |
|---|---|
| title / H1: "An epoch the network never certifies stops every record collector there; a conflicting certified record is only logged" (118 chars; coordinator wording) | every epoch is uncertified until its first quorum (1.2-34.9 s after the close, E4 :173) and the walk moves on once a peer holds it (M state-sync/src/epoch.rs:243-262); it stays stopped only for an epoch never certified (DRE :105; E4 :143); figcheck :59-62 |
| "No test leaves an epoch uncertified across the network; tests at `state-sync/src/epoch.rs:651` and `:798` pin G2." | the :651 test leaves the node's own record uncertified (E4 :146); no test withholds votes (DRE §7 :114); figcheck :66 |
| Related: "A separate issue covers the check before a node saves its own record." (placeholder removed: this issue is created first) | coordinator instruction 3; figcheck :76 |
| evidence: "an arm walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by rolling restart; it has no public page)" | R6 :89, :99; figcheck :34, :67; coordinator instruction 5 |
