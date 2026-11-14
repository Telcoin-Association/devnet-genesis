# A node logs "failed to reach quorum on epoch close" as an error about 65 s after it already holds the certificate

## What happens

A node's own vote round for an epoch record can end without a quorum after the record collector has already stored the network's certificate.
Once the node holds it, its gossip handler drops further votes for that epoch, so the round hears nothing more and gives up about 65 s later.
It then logs `failed to reach quorum on epoch close` at error level, which an operator reads as a failed close, although the epoch certified normally.

## Evidence

In three bench-6 runs on ten validators and one observer, on a build whose vote round and vote-drop rule are main's, the error fired 11 times: 7 in an arm walk on the same fleet shape at 20,000 IOPS (r20261112-1520, nine configurations by rolling restart; it has no public page), the observer's round among them, 3 in [r20261113-1351](https://benchmark.telcoin.network/runs/r20261113-1351/) and 1 in [r20261113-1630](https://benchmark.telcoin.network/runs/r20261113-1630/).
In every case the collector had stored the certificate 0.1-4.5 s after the first quorum line on any node, the error came 64.5-65.0 s after that, and the recovery then fetched the same record hash 0.07-0.29 s later.
The adaptive-form runs logged 4 more of the same kind, each on a node that had already fetched the certified record: 3 in [r20261113-2118](https://benchmark.telcoin.network/runs/r20261113-2118/) and 1 in [r20261114-0000](https://benchmark.telcoin.network/runs/r20261114-0000/).

## Where in the code

On main at 45dce8947:

- `crates/node/src/manager/epoch_votes.rs:231-237` raises the error with no check of the store. It also sets `tn_node.epoch_record_signers` to the round's signer count (`:238`, `:622-624`; 1 to 5 in the error lines of these runs) and starts the recovery fetch (`:239-323`).
- The round ends after 26 timed-out 2.5 s waits (`:27-34`, `:152-157`).
- The handler forwards a vote only while the node holds the record uncertified (`crates/consensus/primary/src/network/handler.rs:866-915`).

## What a fix could look like

Before the error, check `cert_by_digest(epoch_hash)` (`crates/storage/src/epoch_records.rs:898`).
If the certificate is held, log at info and count it; otherwise keep the error exactly as it is.
Whether the signer gauge at `:238` should also skip such a round is open: main sets it on every failed round by design (`:616-621`).
Timeouts, recovery and the failsafe stay as they are.

A fix along these lines is in preparation and will be proposed as a PR against the staging branch.

## How to verify

A unit test beside `test_failed_round_sets_signer_gauge` (`epoch_votes.rs:2225`): a round that times out with the certificate stored logs info and counts; without it, the error stays.
