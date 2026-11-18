# ckpt-l2-SKF — sync gate read-skew fix (devnet-stake-node5.sh)

status: DONE — sections 1-3 done; hand-back sent (no git add/commit/push; fleet untouched)

## Sections
- [x] 1 fix — sync_probe reads ref_head first, then node5_head; lag = h1 - h5 clamped at 0;
      status line "<REF> head h1, then node 5 head h5 (behind by lag), tn_nodeMode '<m>'";
      header item 4 + comment above sync_probe updated; step 4 header (lag <= N) left as is (still true).
      Unreachable check now per value (case "${h1}:${h5}" in :*|*:|*:*:*|*[!0-9:]*): the old
      concatenated check passed when one head was empty; with the clamp an unreadable reference
      would otherwise have counted as in sync. Diff +14/-9.
- [x] 2 test — tasks/l2/tests/stake_sync_probe_test.sh (stub CONFIG_FILE + stub PATH gcloud/ssh/
      curl/cast/... that record+fail + hook; script staged in a temp dir next to a devnet-lib.sh copy).
      Fixed file: 7/7 PASS, exit 0. Original (git show HEAD, scratch SKF/devnet-stake-node5.orig.sh):
      FAIL (a) lag 11, (f) order node5_head ref_head, (e)+(g) no "(unreachable?)" (old concatenated
      check); exit 1. Mutant (new order, old concatenated check): (g) rc 0 = in sync with the
      reference unreadable -> the per-value check is needed and (g) catches it.
- [x] 3 gates — devnet-stake-node5.sh: bash -n 0; shellcheck -x 0 findings before (HEAD) and
      after; portability rc 0. Test file: bash -n 0; shellcheck -x 0; portability rc 0.
      Not run under a real bash 3.2 binary (none found on PATH); portability lint only.

## Notes
