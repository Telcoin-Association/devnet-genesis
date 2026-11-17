status: done
unit: OB2
completed:
- read (2026-11-17): agent-rules, contract §8/§10 OB/§11 step 12/A-7, ckpt-l2-OB, obs script, finalize stop model (_rs_stop/_defer_stop: stop + reset-failed), TND ranges.
- code (2026-11-17): dg-l2/devnet-observability.sh 612 lines (+267 -30): --staged = start-then-stop (tn_obs_stage_host), probe line __tn_obs_st
  (state/enabled/nrestarts/enter/alloy/container/sum/flags), stop once + poll OBS_STAGED_STOP_WAIT_SECS (90), OBS_STAGED line,
  sweep stops on first failure; --staged requires TN_SKIP_EPOCH_WAIT=1 (else exit 2). Normal-mode event/done judging
  moved into tn_obs_judge_run (same output). Launch file = /usr/local/libexec/telcoin/tn-start-docker. Health flag = --healthcheck.
- gates (2026-11-17): bash -n 0; shellcheck -x 0 (no findings); portability 0 (1 WARN sha256sum inside remote cmd).
- checks (2026-11-17T20:43:52Z): harness scratchpad/OB2/t2 (runcase.sh; t/ was a first run with a stub-order bug, discarded).
  staged_started rc0 30 calls 6 stops (1/host), 6 OBS_STAGED started_by_installer=yes; staged_notstarted rc0 18 calls 0 stops,
  started_by_installer=no; staged_active (validator-2 active) rc1, no run on v2, 4 untouched; staged_nostop (v3) rc1, 3 stops, 3 untouched;
  TN_SKIP_EPOCH_WAIT=0 --staged rc2; bad wait rc2; normal new vs HEAD: all ssh ARGV cmp rc0, output diff rc0 (stamp masked);
  fake token in calls/outputs/run logs: 0 hits; 28 stdin sha = token sha. Probe flag regex run locally on 3 sample files + missing file: ok.
next: hand-back sent.
