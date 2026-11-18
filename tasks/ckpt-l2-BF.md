status: done
unit: BF (devnet launch 2) - basefee-check batch size 500 -> 100
completed sections:
- 1 fix: BATCH_SIZE 500 -> 100 (py :78, comment cites -32010 "Exceeded max limit of 100");
  _post comment "500-header ~0.5 s" -> "100-header ~0.3 s" (measured: 3 curl batches of 100 headers, 0.26-0.29 s);
  .sh header line 18 "500 per request" -> "100 per request: the RPC node's batch limit". timeout/retry unchanged (30 s x4 not tied to batch size).
- 2 gates: --self-test 6 tests OK rc 0; py_compile rc 0; bash -n rc 0; shellcheck -x rc 0; check-bash-portability rc 0 (no ERROR).
- 3 live run 2026-11-18T03:29:24Z -> 03:29:40Z (16 s), rc 0, output tasks/l2/w3/v/r10-basefee-2.txt:
  1->2  blocks 1244  gas 360424534  target 10000000  fee 7 -> exp 8 / act 8  PASS (blocks 2..1245)
  2->3  blocks 12720 gas 392086095  target 10000000  fee 8 -> exp 9 / act 9  PASS (blocks 1246..13965)
  summary: PASS 2 FAIL 0 SKIP 0 | 157 RPC requests, 16.0s wall; no [rpc] retries
sections: 1 fix | 2 self-tests and gates | 3 live run
