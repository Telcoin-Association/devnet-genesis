# Topic review: mdbx-advice (#1802, #1800; switch `mdbx_random_advice`)

Reviewed 2026-11-11 against `bench/bench6-2026-11` in `/home/drtnarg/coding/telcoin/telcoin-network-b6`. The scope named head
`dc7855cc6`; the branch moved to `ae62cc47a` during the review, and no commit after `dc7855cc6` touches this topic's files.
The diff is `git show --format= de08ef7f1 f22362090 dddccd4a6 dc7855cc6` (4 commits, +1398 lines with tests). Line numbers
are at head (`execution.rs:477` is the `begin_persist` call, `env/mod.rs:253` the `MdbxAdvice::open` call); `mdbx_advice.rs`
is unchanged since the topic commit. `reth_switches` (node.rs:2105) has gained other topics' fields at head; the
`mdbx_random_advice` line (node.rs:2110) is unchanged.

## Verdict: APPROVE WITH FOLLOW-UPS

Nothing is Critical, High or Medium, and no code has to change before the benchmark image. The review found 2 Low and
9 Info findings (confirmed or plausible), plus 5 unverified Info observations. One pre-existing issue outside this diff is
listed separately.

- **Switch off:** no data, error or consensus path changes. What now runs with the switch off is the per-persist counters
  (by design, about 115 µs per persist) and, at open, a read transaction and `/proc/self/maps` scan whose result is never
  used unless the switch is on (finding 7).
- **Mixed fleet:** cannot fork, cannot make validators reject each other, cannot stall. The switch changes only this
  process's VMA flags, its page-cache behaviour, its metrics and a debug line.
- **The `unsafe` block:** sound. No Rust-level UB, and on the node the range stays a live mapping for the whole call.
- **Before the image (harness and readout only, no code):**
  - (a) Confirm each node's arm from `mdbx_advised_bytes` / `tn_reth_mdbx_random_advice_bytes`, not from the
    `node switches` line or the "advice applied" log (finding 3).
  - (b) Read per-node refaults (`workingset_refault_file`, `pgmajfault` from `/proc/vmstat`) beside the persist CSV, or
    confirm the `mdbx.dat` working set stays under MemAvailable. With the switch on, reclaim treats the newly advised range
    differently (finding 1).
- **Before the upstream PR:** correct three doc sentences (finding 2), then the small code and test cleanups (findings 3-11).

### How the review ran
- **Code review:** the repository's `tn-review` method, run as one agent. Its `findings-verifier` confirmed 7 findings and
  rejected none.
- **Security evaluation:** `tn-security-eval` with five evaluators:
  - state transitions;
  - DoS;
  - determinism, which also took the mixed-fleet question;
  - the nemesis logic audit, run as a general-purpose agent because no dedicated agent type exists;
  - STRIDE.

  Its verifier confirmed or finalised 6 items and rejected none. DREAD was not started: no finding reached Medium, so there
  was nothing to score.
- **Not started:**
  - contract safety: no Solidity;
  - dependency audit: the only Cargo change is one Linux-only `libc = { workspace = true }` edge on tn-reth. libc is already
    a workspace dependency (`Cargo.toml:105`) with one locked version, already used by `telcoin-network-cli`;
  - crypto correctness: no cryptography;
  - consensus safety: no consensus message is touched, and 2b went to the determinism evaluator.
- **Merge:** `findings-verifier` in merge mode deduplicated the two reports and spot-checked findings 2, 3 and 8.
- **Verification caveat:** none of the three verifiers could start isolated per-finding agents; each checked the claims
  itself. To make up part of that, I checked these directly against code or headers:
  - findings 2, 3 (the F7 half) and 7;
  - the kernel function behind finding 1;
  - the pre-existing stat race's code path;
  - the `libc` edge.

## Findings (most severe first)

### 1. With the switch on, reclaim stops counting recent access on the newly advised range (Low, CONFIRMED)
- **Ids:** nem-1.
- **Where:** `mdbx_advice.rs:22-26` (module doc: the advice "closes the mmap read-around and nothing else"),
  `mdbx_advice.rs:488-492`, `config/src/node.rs:354-357`.
- **What:** on Linux 6.3 and later, `vma_has_recency()` returns false for a `VM_RAND_READ` mapping. I checked this in the
  7.0 headers: `/usr/src/linux-headers-7.0.0-38-generic/include/linux/mm_inline.h:610-619`. Reclaim then ignores the PTE
  accessed bits of pages reached only through that mapping. The callers in `rmap.c` and `vmscan.c` are cited from knowledge,
  not read.
- **What the switch adds:** libmdbx already advises `[0, used)` at open and at each growth step (`mdbx.c:20225`, `:20618`,
  `:19936-19943`). The switch adds `[used at open, limit)`, which is exactly where a re-opened node allocates every page it
  writes during the run.
- **Sequence:**
  1. A node re-opens its database with the switch on.
  2. The run writes gigabytes of new pages into the newly advised range.
  3. The page cache comes under pressure, as bench 5's late re-reads did.
  4. Reclaim treats those mmap-hot pages as unreferenced and evicts them sooner than on an "off" node.
  5. The next access refaults each one at order 0. There is no write amplification, but there is extra read I/O on the
     execute and persist path.

  The "off" arm keeps recency until it crosses a growth step; then libmdbx advises the same range itself and the arms
  converge.
- **Same mechanism in the local probe:** the local probe's arm 8 fits it. The advised arm fell from 5.10 to 1.00 under
  pressure, the unadvised arm only to 4.3. Under pressure, part of the fix's benefit comes through reclaim, and part of its
  cost may too. Bench 5's fleet ran kernel 7.0.0-1017-gcp (G1 note D23), so this applies to the fleet.
- **Fix:**
  - Before the image, no code: add `workingset_refault_file` and `pgmajfault` per node to the readout (or confirm the
    `mdbx.dat` working set stays under MemAvailable) and record the kernel. If the working set exceeds memory, treat this as
    a confound when reading the arm; for interpreting the result it is then worth Medium.
  - Before the PR: document it next to the "nothing else" sentence.
- **When:** before the image (readout only); before the upstream PR (doc).

### 2. The switch's docs misdescribe both arms (Low, CONFIRMED)
- **Ids:** F5 + nem-4.
- **Where:** `config/src/node.rs:354-357`; `mdbx_advice.rs:17-18`.
- **What the docs say against the code:**
  - The config doc says the advice is applied "again when the database grows". The code re-applies only when
    `Info::map_size` changes. That is the map's upper limit (`dxb_mmap.limit`, `mdbx.c:10058`), and growth inside the limit
    never remaps (`mdbx.c:19789-19793`); the module's own doc says so at `:15`.
  - The config doc says the default "keeps the kernel's default advice". Under `NORDAHEAD`, libmdbx advises `[0, used)`
    itself (`mdbx.c:20618`), so the off arm is "libmdbx's own advice over the pages in use at open and at each growth step".
  - The module doc says the re-check re-applies "to any mapping it has not advised yet". `apply()` re-advises every current
    mapping (`:238-243`).
- **Scenario:** an operator reading `parameters.yaml` docs, or the bench write-up, describes the control arm as "kernel
  default" and expects re-advice on growth. Neither is true.
- **Fix:** rewrite the three sentences. The bench write-up should describe the off arm as libmdbx's own `[0, used)` advice.
- **When:** before the upstream PR (and before the bench write-up).

### 3. Nothing in the logs proves the advice is in force (Info; CONFIRMED / UNVERIFIED halves)
- **Ids:** F7 + stride-1.
- **Where:** `mdbx_advice.rs:121-132` (the gate at `:125`); the `node switches` line and the `tn_node_switch` gauge.
- **Sequence:**
  1. The switch is on and every `madvise` fails (EPERM under a seccomp sandbox, or ENOMEM).
  2. `apply()` still returns the mapping count (`:248`), so `mappings > 0` holds.
  3. "mdbx random-access advice applied" is logged with `advised_bytes=0`, beside the one warn line.
  4. The `node switches` line and the gauge show the configured value, so they say "on" either way.
- **Fix:**
  - Code (before the PR): log "applied" only when `advised_bytes() > 0`.
  - Harness (before the image): label each node's arm by `mdbx_advised_bytes` on `persisted output` (or the gauge) and by
    the absence of the warn line. On: above 0 and equal to the map's upper limit. Off: 0.

### 4. The probe's cost lands inside `save_blocks_ms` and `markers_ms` (Info, CONFIRMED)
- **Ids:** F1.
- **Where:** `execution.rs:475-490`; the `PersistPhases` doc at `:785-788`.
- **What:** `begin_persist` (`:477`) runs after the `open` lap (`:475`) and before the `save_blocks` lap, and
  `before_commit` (`:489`) runs before the `markers` lap (`:490`). Their `info()` call and `/proc` reads (tens of µs) count
  in `save_blocks_ms`, `tn_reth.persist_save_blocks_seconds` and `markers_ms`.
- **Effect:** both arms pay it, so the A/B comparison is unaffected. Only comparisons with bench 5's histogram shift slightly.
- **Fix:** reset the stamp after `begin_persist`; call `before_commit` after the `markers` lap and reset again. The
  measuring window is unchanged.
- **When:** before the PR.

### 5. The non-Linux `advise_random` stub reports success (Info, CONFIRMED)
- **Ids:** F3.
- **Where:** `mdbx_advice.rs:501-505`.
- **Scenario:** where a Linux-format `/proc/self/maps` exists on a non-`linux` target (Android, FreeBSD with linprocfs),
  `apply()` counts the bytes as advised, sets the gauge and logs "applied" although nothing was advised.
- **Fix:** return `Err(io::ErrorKind::Unsupported.into())`.
- **When:** before the PR.

### 6. Weak test assertions (Info, CONFIRMED)
- **Ids:** F6.
- **Gaps:**
  - `test_probe_deltas_cover_the_window` (`mdbx_advice.rs:814-853`) never asserts the commit thread's share: summing only
    the persist thread's `wchar` would still pass.
  - The `recheck` branch where the map size changed but the mapping set is equal (`:265-267`) is untested. Finding 8's fix
    removes that branch.
  - The used-size check (`env/mod.rs:1067-1085`) repeats the production formula, so it catches only a lost `+1`.
- **Fix:** assert the sum through a pure helper, and take the used size from an independent source.
- **When:** before the PR.

### 7. With the switch off, `file_id` does work nobody uses (Info, CONFIRMED)
- **Ids:** F2.
- **Where:** `mdbx_advice.rs:115` (and `:467-481`).
- **What:** every `RethEnv` construction runs a read transaction, a cursor-first on the main table and a full
  `/proc/self/maps` parse (about 0.9 ms). The result `file` is read only at `:229` (`apply`) and `:259` (`recheck`, after
  the switch-off return at `:256`). This is the one switch-off addition that serves nothing when the switch is off.
- **Fix:** `file: random_advice.then(|| file_id(db)).flatten()`.
- **When:** before the PR.

### 8. A mapping that appears during `apply()` is recorded as advised and never advised (Info, CONFIRMED, unreachable in the node)
- **Ids:** nem-2.
- **Where:** `mdbx_advice.rs:233`, `:246`, `:264-267`.
- **What:** `apply()` advises the ranges from its first maps read and records the ranges from a second read. A mapping that
  appears between the two reads is recorded but not advised, and `recheck`'s equal-set shortcut never advises it later.
- **Why unreachable:** it needs a change of the map limit. That never happens in the node: under NOSTICKYTHREADS, an
  implicit resize keeps the limit and skips the remap branch (`mdbx.c:19789-19793`, `:19817-19866`).
- **Fix:** drop `Advised::ranges` and re-apply on any `map_size` change; `madvise` is idempotent.
- **When:** before the PR.

### 9. The env-level `stat()` at open would read a live write transaction if one existed (Info, CONFIRMED, unreachable here)
- **Ids:** state-1.
- **Where:** `mdbx_advice.rs:114`.
- **Path:** `mdbx_env_stat_ex(env, NULL)` calls `env_owned_wrtxn`, which under NOSTICKYTHREADS returns any open write
  transaction whatever thread owns it (`mdbx.c:20992-20999`). `stat_acc` then runs on that transaction from this thread
  (`:10723-10726`).
- **Why unreachable:** `MdbxAdvice::open` runs at `env/mod.rs:253`, before `init_provider_factory` and before any writer
  exists.
- **Fix:** take the page size from a read transaction's `db_stat_with_dbi`, as `gc_stat` already does (`:220-223`);
  `mdbx_dbi_stat` sets `ms_psize = env->ps` (`mdbx.c:9246`).
- **When:** before the PR.

### 10. Test helpers used only by Linux tests are not gated (Info, CONFIRMED)
- **Ids:** F4.
- **Where:** `test_support::Mapping` (`mdbx_advice.rs:606-615`); `env_with_advice`, `create_and_close` and `gauge_value`
  (`env/mod.rs:890`, `:901`, `:908`).
- **Effect:** a non-Linux test build warns about dead code, and fails under `-D warnings`. CI runs on Linux only.
- **Fix:** add `#[cfg(target_os = "linux")]`.
- **When:** before the PR.

### 11. `env_info`'s snapshot loop has no cap (Info, PLAUSIBLE)
- **Ids:** dos-1.
- **Where:** `mdbx_advice.rs:120`, `:160`, `:171`, reaching `mdbx.c:10131-10140`.
- **What:** the loop repeats until two snapshots match. In `begin_persist` this thread holds the write lock; in
  `finish_persist` only reader churn can cause a repeat, and that settles. reth's own scrape hook calls the same function.
- **Fix:** none needed (an optional comment).
- **When:** before the PR.

### Unverified Info observations (carried as reported, not counted)
- **stride-2:** with the switch on, cold RPC reads in the newly advised range lose read-around.
- **dos-2:** each `/proc/self/io` read walks every thread. That costs about 0.25-0.5 ms at 5,000 threads and runs twice per
  persist; the node has about 76 threads.
- **state-2:** nothing guards against `FileId{0,0}` reaching `madvise`, but it cannot occur.
- **nem-3:** the SAFETY comment is correct but incomplete. It does not say that the `Arc` and NOSTICKYTHREADS keep the base
  mapping in place, or that a partly unmapped range is advised in its mapped parts while the call returns ENOMEM.
- **nem-5:** btrfs subvolumes can share `dev:ino` in `/proc/self/maps`. That matters only in a process with several
  environments.

### Pre-existing, outside this diff (not counted in the verdict; file its own issue)
- **Path:** on every Prometheus scrape:
  1. The scrape hook (`node.rs:950-953`) calls `tn_reth::report_db_metrics`.
  2. That reaches reth `gauge_metrics`, which calls the env-level `self.stat()`
     (`vendor/reth/crates/storage/db/src/implementation/mdbx/mod.rs:348`).
  3. The call takes the same `env_owned_wrtxn` path as finding 9.

  A scrape that overlaps a persist therefore runs `stat_acc` on the persist's live write transaction from the metrics
  thread, racing the writer.
- **Status:** I verified the code path. I did not assess the consequence; benches 3-5 ran with scrapes and no crash is
  recorded.
- **What this diff changes:** nothing on this path. Its own env-level `stat()` runs only at open (finding 9). Its
  per-persist `info()` runs either on the thread that is using the write transaction (`begin_persist`) or after the commit
  (`finish_persist`).
- **Fix:** take `db.page_size` from the per-table stats the hook already reads.

## Answers to 2a-2g

### 2a. Switch off = before
Nothing that writes data, returns an error, or feeds consensus changes. The lines that now run with the switch off:

**At open:** once per process, through `node.rs:915` → `create_engine` → `env/mod.rs:253` → `mdbx_advice.rs:100-142`.
- `describe_mdbx_series` (`metrics.rs:781-830`).
- `txn_manager_io()`: a `/proc/self/task/*/comm` scan (`:104`, `:571-585`), plus one possible info line (`:106-109`).
- `db.stat()` for the page size (`:114`).
- `file_id` (`:115`): a read transaction, a cursor-first and a `/proc/self/maps` parse. Its result is unused with the
  switch off (finding 7).
- `db.info()` and three metric records (`:120`, `:134-140`); the advised-bytes gauge is set to 0.
- An `Arc` clone of the database (`:112`). It lives in `RethEnvInner` next to the provider factory, so the database's
  lifetime does not change.

**Per persist** (`execution.rs:477`, `:489`, `:497` → `mdbx_advice.rs:158-205`):
- two `info()` calls;
- `/proc/self/io` twice, `/proc/thread-self/io` twice, and the transaction-manager thread's `io` twice;
- `gc_stat`: a read transaction plus `mdbx_dbi_stat` of the GC table (`:220-224`);
- the metric records (`:181-186`);
- `recheck`, which returns at once (`:256`);
- 14 new fields on the `persisted output` debug line (target `engine`, `execution.rs:861-874`).

**Effect:**
- No new code writes to the database: it opens read transactions only.
- Nothing can fail: all three probe functions are infallible and called without `?`. Nothing can panic either; arithmetic
  saturates and there is no unwrap or indexing.
- Timing: about 115 µs per persist on the execution thread. Part of it falls inside the `save_blocks` and `markers` laps
  (finding 4). Part falls between the durable commit and the return (`finish_persist`), which delays the executed-output
  announcement by that share.
- The counters and fields are accepted by the contract row. The metrics registration and the log fields cannot change
  behaviour.

### 2b. Mixed fleet
- **No fork, no rejection, no stall.** The switch is read only at `mdbx_advice.rs:121` and `:256`.
- **Path:** `config/src/node.rs:359` → `reth_switches` (`node.rs:2110`) → `new_with_switches` → `env/mod.rs:253`.
  `Parameters::switches()` feeds only the `node switches` info line and the `tn_node_switch` gauge.
- `Parameters` is not hashed, signed, gossiped or compared between validators.
- The new code writes nothing to MDBX: it uses read transactions, `info`, `stat` and `madvise` only. No header, vote,
  certificate, batch, block, receipt or state root can differ. Another validator sees only this node's I/O speed.
- The advice is per-process VMA state, and no lock-file bit is written, so a rolling restart leaves nothing behind.

### 2c. Liveness under the switch
- **No.** `MdbxAdvice::open` cannot fail (`mdbx_advice.rs:100-142`), and `begin_persist`, `before_commit` and
  `finish_persist` return no `Result`.
- The persist retry loop (`crates/engine/src/payload_builder.rs:617-638`) sees exactly the errors it saw before. Each
  attempt builds its own probe after its own write-transaction open, and a failed attempt drops its probe.
- `finish_persist` runs after the durable commit and adds about 100 µs before `Ok`.
- Nothing is dropped, deferred or left without a retry.

### 2d. Byzantine or merely slow peers, and clients
- **Peers:** nothing new. State growth stays inside the map limit, so it never triggers a re-check or a maps scan.
- **RPC clients:**
  - They can hold reader slots. That adds contention on libmdbx's reader-table lock once per persist (µs, when `gc_stat`
    binds a slot, `mdbx.c:36363`).
  - If they fill the reader table, `gc_stat` returns None and the GC fields drop off the line (`mdbx_advice.rs:221`); the
    persist continues.
  - A raised reader count lengthens `env_info`'s reader scan, at most about 1-2 ms per persist at 32,000 slots.
  - With the switch on, their cold reads in the newly advised range get no read-around (stride-2).
- **Bound:** a constant cost per persist, about once a second. No peer or client can force a remap or a maps scan.

### 2e. Restart and epoch boundary
- **State in memory** (`mdbx_advice.rs:74-91`), built once at `env/mod.rs:253` and held in `RethEnvInner`:
  - an `Arc` of the database, the switch value and the page size;
  - the file's device and inode;
  - the transaction-manager thread's `io` path;
  - the `Advised` record (map size, ranges, bytes) under a mutex;
  - the `warned` flag.
- **Epoch change:** `create_engine` runs once, outside the epoch loop (`node.rs:915`). Nothing re-runs or resets, and the
  kernel-side advice (a VMA flag) lasts for the life of the process.
- **Restart:**
  - The mappings and their advice die with the process. Page-cache folios keep their size (an accepted residual).
  - On re-open, libmdbx advises only the pages in use. With the switch on, `MdbxAdvice::open` advises the whole map again
    before genesis or anything else is written; with it off, only libmdbx's own advice applies.
  - `warned` resets, so there is one warning per process, and the thread id is resolved again.
  - libmdbx's page-operation counters live in the lock file, which the first opener re-initialises, so
    `tn_reth_mdbx_page_ops_total` restarts (it is set with `absolute()`). The per-persist deltas are unaffected.
  - The thread id cannot be reused while `MdbxAdvice` lives, because its `Arc` keeps the environment and its
    transaction-manager thread alive.

### 2f. Determinism
- **Nothing consensus-visible.** `PersistStorage` goes only to the debug line and to metrics (`execution.rs:497-502`,
  `:835-875`; `metrics.rs:816-829`).
- The new code uses no `HashMap`, `SystemTime`, `rand` or parallel iterator; floats appear only in metric sinks.
- The order of the `read_dir` listing does not matter, because more than one match returns None (`mdbx_advice.rs:578-580`).
- MDBX file contents and page numbers do not depend on residency. Prefault only decides whether a new page is written first.

### 2g. Topic questions
1. **The `unsafe` madvise (`mdbx_advice.rs:483-499`): the range stays a live mapping for the whole call.**
   - Under NOSTICKYTHREADS, `dxb_resize` skips the remap and move branch (`mdbx.c:19817-19866`). Every runtime caller passes
     an implicit mode that keeps the limit (`:19789-19793`), and with the limit unchanged `osal_mresize` only truncates the
     file (`:30086-30087`). Growth adds no mapping (the test at `env/mod.rs` "holds while the database grows" checks this).
   - `MdbxAdvice` holds an `Arc` of the environment (`:76`, `:112`), so the map cannot be closed under it.
   - At open, nothing else uses the environment.
   - If the mapping set did change between the maps read and the call: an unmapped part makes Linux advise the parts still
     mapped and return ENOMEM, which the code warns about once without counting those bytes (`:239-241`). A reused address
     gets only `VM_RAND_READ`; its contents are untouched.
   - There is no Rust-level UB. The pointer is never dereferenced, no reference is created, and the length uses
     `saturating_sub`. The SAFETY comment's argument is correct but incomplete (nem-3).
2. **The file identity cannot pick another file, except for the btrfs case.**
   - reth-db builds libmdbx with `return-borrowed`, and a read transaction reads straight from the map. The key is
     therefore `Cow::Borrowed` and lies inside this environment's `mdbx.dat` mapping, so the `Owned` arm at `:473` cannot
     run.
   - The address is used only while the transaction is open (`:468-481`), and maps lines are compared only with maps lines.
   - Static files, `mdbx.lck` and other environments have different inodes, and each environment derives its own identity.
   - A second handle on the same file would be advised too, which is harmless; its bytes would double-count in the gauge.
   - The exception is nem-5 (btrfs subvolumes sharing `dev:ino`, which matters only in multi-environment processes). The
     node runs one MDBX environment: its consensus DB is tndb (`crates/storage/Cargo.toml:65`), and `create_engine` builds
     the only `RethEnv`.
3. **Failure handling: confirmed.** No failure can fail the open, fail or block a persist, or panic.
   - Each source falls back to "not available":
     - `/proc` reads: `.ok()?`, `unwrap_or_default` or `let Ok(..) else continue` (`:517`, `:552`, `:573-576`);
     - read transactions: `.ok()?` at every step (`:221-222`, `:468-471`);
     - `info()` and `stat()`: `.ok()` (`:114`, `:120`, `:160`, `:171`);
     - `madvise`: `warn_once` (`:239-241`).
   - A container without `/proc` leaves the fields off and logs one warning when the switch is on.
   - The non-Linux build compiles the feature out: `libc` is a Linux-only target dependency (`tn-reth/Cargo.toml:114-116`)
     used only inside the `cfg(target_os = "linux")` `advise_random`, and every test that needs Linux is gated. Two caveats:
     the stub claims success (finding 5), and some test helpers are not gated (finding 10).
4. **Nothing on the per-persist path blocks without bound or can fail the persist.**
   - `gc_stat`'s read transaction binds a reader slot under the blocking reader-table lock (`mdbx.c:36363` → `:25178`),
     which is held for a scan of microseconds. It could block for long only if an external process stalled while holding
     it, and that would already block every reader. A full reader table maps to None.
   - The `env_info` loop settles (finding 11).
   - `/proc/self/io` is O(threads) under the signal-stats seqlock (dos-2): about 15 µs at the 76 threads measured.
   - The maps scan and `madvise` (mmap write lock, held for microseconds) run only at open and on a remap.
   - No `/proc` read is made on a path that waits on the write transaction.
5. **No second handle, and no change to read-ahead or prefault state.**
   - The code uses the node's own `RethDb` (an `Arc` clone) and opens no environment.
   - The shared lock file's `readahead_anchor` is written only at `mdbx.c:20154`, inside `dxb_set_readahead`. Its live
     callers are `dxb_resize` (`:19943`) and the environment open (`:20618`). Under `NORDAHEAD`, `readahead` is false at both
     (`:19936-19937`, `:20334-20335`).
   - The `mincore` cache is written only on the write-transaction prefault path (`:22360`, `:22371`).
   - A read transaction reaches `dxb_resize` only if the used size exceeds the mapped size (`:36621-36634`), which cannot
     happen within the process.
   - `info`, `dbi_stat` and cursor-first are read-only.
   - libmdbx issues `MADV_NORMAL` or `MADV_WILLNEED` only when read-ahead is enabled (`:20081-20132`), so it cannot undo the
     whole-map advice.

### Known residuals: none is worse than stated
- **`prefault_wchar_bytes`:** it is left off when there is not exactly one transaction-manager thread at open. That
  includes zero, not only "more than one environment". On the node the read-write environment has exactly one, so nothing
  changes in practice.
- **"Prefault on ⇔ Δ`page_prefault` ≈ Δ`mdbx_last_pgno`":** the test is one-sided. A multi-page prefault counts once
  (`mdbx_advice.rs:359-360`), so Δprefault falling below Δlast_pgno does not by itself mean prefault is off; I-1r already
  says "slightly under when multi-page calls exist". Read it together with `prefault_wchar_bytes`.
- **The ≈115 µs cost** grows with the thread count through `/proc/self/io`. It was measured at about 76 threads, the node's
  normal count.

## Note for the benchmark (inference, not verified)
- **Finding 1:** the fix arm differs from the control arm in reclaim as well as in folio size. If run 1's control arm shows
  pressure (refaults, majfaults), part of any commit-cost change on the fix arm may come from reclaim. The local probe's
  arm 8 points the same way. Record refaults per node so the two effects can be told apart.
- **Labelling arms:** label each node's arm from the advised bytes, not from the switches line (finding 3). A node where
  `madvise` failed is a control node whatever its `parameters.yaml` says.

## Not examined
- **Tests:** none were run (no cargo). In particular, I did not confirm that `create_and_close` closes the environment
  before the re-open.
- **Kernel source:** only the headers. `vma_has_recency` was checked there, but its callers in `rmap.c` and `vmscan.c`,
  `do_io_accounting`'s cost, `madvise`'s ENOMEM handling and the btrfs device in maps are from knowledge.
- **reth and libmdbx:**
  - the spawn site of the persist (that it runs on a blocking thread rests on the comment at `payload_builder.rs:606-608`);
  - whether reth builds libmdbx with read-transaction timeouts;
  - `save_blocks` past line 623.
- **Elsewhere:** RPC read paths; the harness code that labels arms; other topics' commits on the branch. I also did not
  assess the consequence of the pre-existing scrape race.
