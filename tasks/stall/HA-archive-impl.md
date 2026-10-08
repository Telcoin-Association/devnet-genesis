status: complete
completed: [0-read, 1-config, 2-lib-archive, 5-iap-retry, 3-teardown-gate, 4-deploy, 7-report-scrub, 8-tests, 6-readme, 9-verify]
pending: []

# HA archive implementation — checkpoint

## 0. Read audit A/D, lessons, bench-lib/teardown/config — DONE
- Bucket name tn-devnet-benchmark-archive does not match startswith("tn-devnet-bench-") (char after "bench" is "m"), and gets no benchmark= label.

## 1. config.sh — DONE (Edit only)
- After BENCH_RESULTS_DIR: BENCH_ARCHIVE_{BUCKET,LOCATION,LABELS,PREFIX,TIMEOUT_SECS}, BENCH_TEARDOWN_SKIP_ARCHIVE, BENCH_COLLECT_ARCHIVE.
- Self-checks after the INSTANCE_TAGS check: bucket name charset, not tn-devnet-bench-*, labels lack benchmark=/bench-run=, 0|1 knobs, timeout positive int.
- Deviation: BENCH_IAP_RETRIES default lives in bench_iap_scp_down (${BENCH_IAP_RETRIES:-3}), not config.sh (fewer edits to the shared file).

## 2. bench-lib.sh archive — DONE
- New section before leftovers: BENCH_ARCHIVE_EXCLUDE='^(genesis[^/]*/|(.*/)?tunnel\.pid$|(.*/)?\.)' (gcloud uses re.match on the path relative to the source; checked in SDK regex_util.Patterns.match; --exclude is comma-split so no commas).
- bench_archive_ensure (describe 120s alarm; only 'not found'/404 => create --location --uniform-bucket-level-access --public-access-prevention, then update --update-labels; other describe errors => rc 1).
- bench_archive_results [bucket...] (rsync -r results -> PREFIX/results with --exclude; each bucket -> PREFIX/bucket/<b>; all via bench_run perl alarm ... </dev/null; tries all; never --delete-unmatched).
- bench_archive_manifest (cp manifest.json alone, 300s alarm).
- bench_archive_verify (one `gcloud storage ls -l` of PREFIX/results/manifest.json + logs/**; name+size compare of logs/*.log.gz, *.pulled, *.pulled-*, *-recovery-*.tgz, manifest.json; prints count; dry run prints argv + required count).
- bench_bucket_names: jq select(.name != $archive) exclusion by name.
## 5. IAP retry — DONE
- bench_iap_scp_down: BENCH_IAP_RETRIES (default 3, in-function), .part + mv -f, 300s alarm, </dev/null, stderr to temp file then cat; retry only on '\[(4003|4033|4047): '; sleep try*10.

## 3. teardown gate — DONE
- Header comment documents: log gate -> evidence -> ARCHIVE GATE -> deletes -> provenance -> final sync.
- archive_gate between recovery-evidence loop and `# === delete` (tunnel kill is the first delete). Manifest writes only under BENCH_APPLY=1 (dry run prints them).
- Failure: --yes => "❌ archive of ... failed — NOTHING was deleted." + override cmd, exit 1; SKIP=1 => warn, .archive.status="unverified", note; dry run => "✗ with --yes the teardown stops here".
- archive_final_sync after node_startup_check (.archive.final_sync_at + manifest re-upload); left-nothing informational archive object count.
- Deviation (stated): BENCH_TEARDOWN_SKIP_ARCHIVE=1 still ATTEMPTS the archive and continues on failure (same semantic as BENCH_TEARDOWN_SKIP_LOGS); it does not skip the attempt.
- shellcheck -S warning (CI file list, no -x) clean; renamed verify arrays (ls_urls/need_files) because CI passes all files at once and `urls` clashed with blast's local string.
### Dry run (benchmark/benchmark-teardown.sh --run r20261006-0053, rc=0, results tree sha256-identical before/after)
```
>>> node logs -> /Users/grant/coding/telcoin/devnet-genesis/benchmark/results/r20261006-0053/logs (nothing is deleted until these are saved)
    - bench-validator-01: instance gone — no log to pull
    ...

>>> archive -> gs://tn-devnet-benchmark-archive/runs/r20261006-0053/ (persistent; nothing is deleted until the copy is verified)
    archive bucket gs://tn-devnet-benchmark-archive absent — would be created in us-west2 (the harness never deletes it)
    + perl -e alarm\ shift\;\ exec\ @ARGV 120 gcloud storage buckets create gs://tn-devnet-benchmark-archive --project=tn-devnet --location=us-west2 --uniform-bucket-level-access --public-access-prevention
      (dry run — not executed)
    + perl -e alarm\ shift\;\ exec\ @ARGV 120 gcloud storage buckets update gs://tn-devnet-benchmark-archive --project=tn-devnet --update-labels=purpose=bench-archive\,retain=true
      (dry run — not executed)
    (dry run) manifest .archive = {uri: "gs://tn-devnet-benchmark-archive/runs/r20261006-0053", status: "pending"}
    + perl -e alarm\ shift\;\ exec\ @ARGV 1800 gcloud storage rsync -r --exclude=\^\(genesis\[\^/\]\*/\|\(.\*/\)\?tunnel\\.pid\$\|\(.\*/\)\?\\.\) --project=tn-devnet /Users/grant/coding/telcoin/devnet-genesis/benchmark/results/r20261006-0053 gs://tn-devnet-benchmark-archive/runs/r20261006-0053/results
      (dry run — not executed)
    + perl -e alarm\ shift\;\ exec\ @ARGV 300 gcloud storage ls -l gs://tn-devnet-benchmark-archive/runs/r20261006-0053/results/manifest.json gs://tn-devnet-benchmark-archive/runs/r20261006-0053/results/logs/\*\* --project=tn-devnet
      (dry run — not listed; with --yes it requires 58 file(s) there at their local sizes: 35 log(s), 11 pull marker(s), 11 recovery archive(s), manifest.json)
    (dry run) manifest .archive.status = "verified-before-delete", .archive.verified_at = <now>
    + perl -e alarm\ shift\;\ exec\ @ARGV 300 gcloud storage cp --project=tn-devnet /Users/grant/coding/telcoin/devnet-genesis/benchmark/results/r20261006-0053/manifest.json gs://tn-devnet-benchmark-archive/runs/r20261006-0053/results/manifest.json
      (dry run — not executed)

>>> plan / execution
    (orphan disks are re-listed after the instances; only unattached ones labelled bench-run=r20261006-0053 are deleted)
    + git -C /Users/grant/coding/telcoin/tn-contracts-devnet-relaunch worktree prune
      (dry run — not executed)

>>> node startup provenance (informational — never blocks the teardown)
    + python3 /Users/grant/coding/telcoin/devnet-genesis/benchmark/report/provenance.py --run-dir /Users/grant/coding/telcoin/devnet-genesis/benchmark/results/r20261006-0053 --update-manifest
      (dry run — not executed)

>>> archive final sync -> gs://tn-devnet-benchmark-archive/runs/r20261006-0053/results (informational — never blocks the teardown)
    + perl -e alarm\ shift\;\ exec\ @ARGV 1800 gcloud storage rsync -r --exclude=\^\(genesis\[\^/\]\*/\|\(.\*/\)\?tunnel\\.pid\$\|\(.\*/\)\?\\.\) --project=tn-devnet /Users/grant/coding/telcoin/devnet-genesis/benchmark/results/r20261006-0053 gs://tn-devnet-benchmark-archive/runs/r20261006-0053/results
      (dry run — not executed)

>>> left-nothing checks (current state — dry run deleted nothing)
    · archive (kept; cleaned by hand once the results are qualified): 0 object(s) under gs://tn-devnet-benchmark-archive/runs/r20261006-0053/
```

## 4. deploy — DONE
- step_12: bench_archive_ensure || bench_die (with --from 12 resume hint) after the run bucket labels.
- step_15: after metrics block, if BENCH_COLLECT_ARCHIVE=1: ensure && bench_archive_results BENCH_BUCKET -> manifest .archive {uri, collect_sync_at} + bench_archive_manifest; else bench_warn (non-fatal).
- print_plan rows 12 and 15 mention the archive. Plan dry run renders (BENCH_RUN_ID=r20991231-0000, no results dir created).

## 7. report scrub — DONE
- scrub.py scrub_manifest: `_drop(out, "archive", "manifest.archive", ctx)` (uri carries the private project + bucket; the DENYLIST 'internal-name' + manifest-name rules would also flag it).
- test_report_scrub.py (Edit only): ARCHIVE_BUCKET split literal, synthetic manifest gains .archive, expected dropped list + key set, manifest-name rule fires for the archive bucket. 35 tests OK; mutation (drop line removed in a temp copy) fails 4 tests. make_bundle.py needs no change (it reads named fields only).

## 8a. tests/test_teardown_archive.py — DONE (21 tests, ~10 s)
- fixtures/teardown/: fake-gcloud.py (dir-backed GCS + instances, logs argv+stdin, re.match exclude, FAKE_FAIL/FAKE_TRUNCATE/FAKE_DESCRIBE_ERR/FAKE_SCP), stub-perl.sh (records alarm secs, execs), stub-sleep.sh, stub-pgrep.sh (so an APPLY test never kills a real local tunnel). Dir named teardown/ because .gitignore ignores any `archive` path.
- Helper tests cut functions out of bench-lib.sh by regex; teardown e2e runs the real script in a sandbox copy (TREE) against the fake: happy path ordering (evidence ssh < rsync < ls -l < first delete; bucket rsync < storage rm), archive contents/exclusions, manifest .archive, labels, count line; copy failure / verify failure => rc 1 + nothing deleted; SKIP=1 => deletes + note + status unverified; dry run => gate between node logs and plan, no mutation, results tree unchanged; config self-check refusals.
- Mutation run (8 mutations in temp copies: drop </dev/null, add --delete-unmatched, drop name exclusion, verify always passes, weaken exclude, ignore verify rc, drop exit 1, treat any describe error as absent): all caught.

## 8b. tests/test_collect_retry.py — DONE (6 tests, ~2 s)
- Cuts bench_warn + bench_iap_scp_down; fake gcloud FAKE_SCP outcomes; asserts attempts, .part target, stdin empty, alarms 300, sleeps 10/20, no retry on non-IAP failure, budget knob + bogus fallback, earlier complete copy never replaced. 5 mutations caught.
## 6. README — DONE
- Runbook: archive note on teardown + override command + rule (never deletes a node log; archive cleaned by hand after qualification).
- Step table 12 (ensure archive, stops on access failure) and 15 (IAP retry; BENCH_COLLECT_ARCHIVE).
- Outputs: logs/, bucket/, archive layout, manifest.archive fields, scrub drops it.
- Teardown guarantees: archive never a candidate, three gates in order, override semantics, alarms/no-delete copies, final sync, dry-run behaviour.

## 9. verify — DONE
- bash -n: config.sh, bench-lib.sh, benchmark-teardown.sh, benchmark-deploy.sh, 3 stub scripts: ok. py_compile + 3.9 grammar on new/edited Python: ok.
- shellcheck: docker koalaman/shellcheck:v0.9.0 -S warning on the CI file list + stubs: rc 0. Local shellcheck default severity vs HEAD: only new info notes SC2016 (jq filters in single quotes) and SC2015 (intended `a && b || warn`).
- python3 -m unittest benchmark.tests.test_teardown_archive benchmark.tests.test_collect_retry: 27 OK. Full suite discover -s benchmark/tests: 238 OK (46 s). check_mutations.py: all 7 existing mutations rejected.
- Deploy step 15 archive branch exercised ad hoc (success records .archive{uri,collect_sync_at}; ensure/results failure => warn, rc 0). Plan dry run renders rows 12/15.
- Teardown dry run on r20261006-0053: see section 3 (results tree unchanged). Nothing run with --yes.
