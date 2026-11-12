# L units (local-SSD deployment) — what every L unit reads first

The design is `/home/drtnarg/coding/telcoin/devnet-genesis/benchmark/private/bench6-prep/design/design-local-ssd-deployment.md` (L0, 538 lines: read ONLY the sections your brief names, by `grep -n '^#'` then ranges).
The rules are `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6-agent-rules.md` (sections "What nobody but the orchestrator does", "Checkpoint, budget, scratch", "Harness and generator units", "HAND BACK"; and through it `tasks/bench5-agent-rules.md` "Harness and txgen units").
Scratch: `/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/ef19b04c-8e16-4dbc-9365-9cbe3d19bce9/scratchpad/<unit>/`.
Harness base for "byte-identical with every knob unset": commit **ae43747** (`git show ae43747:<path>`); the design says ab7658c, and the files you own are the same at both except where your brief says otherwise.

## The orchestrator's decisions on the design (they override the design where they differ)
1. **Create path B.** A node whose machine type ends in `-lssd` is created by a bench-owned function in `benchmark-deploy.sh` with `--maintenance-policy=TERMINATE` (the flags the probe driver used live on `c3-standard-8-lssd`, `benchmark/benchmark-probe.sh:494-503`). Every other node goes through `common/create-instances.sh`, narrowed per machine type by `BENCH_CREATE_MACHINE_TYPE`. Nobody has tried `MIGRATE` on a local-SSD shape and the documentation could not be read, so path A is not built.
2. **No `blkid`.** The pinned boot image is proven to carry `findmnt`, `lsblk`, `mkfs.ext4`, `mount`, `umount`, `readlink`, `systemctl`, `stat`, `awk`, `python3` (the probe's `TOOLS_REQUIRED` and `TOOLS_NVME`, live run r20261112-0024). Read a file system's UUID with `lsblk -dno UUID <dev>` (or `findmnt -no UUID`), not with `blkid`.
3. **The unit split is finer than the design's §5** (agents overrun their estimates; one file has one writer at a time):

   | unit | wave | owns | from the design |
   |---|---|---|---|
   | L1a config | 1 | `benchmark/config.sh`, new `benchmark/tests/test_node_shapes.py` | all of §2.1: `BENCH_NODE_MACHINE_TYPES`, `BENCH_NODE_ZONES`, `BENCH_NODE_DATADIR_LSSD` (with the `BENCH_FLEET` rule), `BENCH_CREATE_MACHINE_TYPE`, the arrays `NODE_MACHINE_TYPES` and `NODE_DATADIR_LSSD`; the config half of §2.10 |
   | L1b lib | 1 | `benchmark/bench-lib.sh`, `benchmark/arms/MANIFEST-FIELDS.md`, new `benchmark/tests/test_local_ssd.py`, `benchmark/tests/test_host_probe.py`, `benchmark/tests/test_persist_sampler.py` | §2.4 (the three builders, the C4 quota metric), §2.5's two whole-disk test cases, §2.8's MANIFEST-FIELDS section |
   | L2 arm summary | 1 | `benchmark/tools/arms-summary.py`, `benchmark/tests/test_arms_summary.py`, fixtures it adds | §2.6 |
   | L1d deploy: shapes | 2 (after L1a, L1b) | `benchmark/benchmark-deploy.sh`, new `benchmark/tests/test_node_deploy.py` | §2.2 path B, §2.3 "Step 0 and the plan" and "Step 2" except `data_disk`; the deploy half of §2.10 |
   | L3 launch files | 2 (after L1a) | `benchmark/launch/bench6-run1-lssd.env`, `benchmark/launch/bench6-run1-lssd.plan`, `benchmark/launch/README.md`, `benchmark/tests/test_launch.py` | §4.1-4.3, §4.7, for option (e) |
   | L1c deploy: local SSD | 3 (after L1d) | `benchmark/benchmark-deploy.sh`, new `benchmark/tests/test_local_ssd_deploy.py` | §2.3 step 2's `data_disk`, step 3, step 7, the dry path and `--print-lssd-mount` |
   | L4 the sum | 4 | `benchmark/tests/check_mutations.py`, `benchmark/tests/test_run1_rehearsal.py` | §5's L4 row |

   `benchmark/tests/check_mutations.py` is written by L4 only: every other unit applies its mutation anchors by hand, reports each verbatim (file, the exact old and new text, the test that fails) and L4 turns them into cases.
4. **Names are frozen as the design gives them** (§2 table, §2.8): knobs `BENCH_NODE_MACHINE_TYPES`, `BENCH_NODE_ZONES`, `BENCH_NODE_DATADIR_LSSD`, `BENCH_CREATE_MACHINE_TYPE`; arrays `NODE_MACHINE_TYPES`, `NODE_DATADIR_LSSD`; builders `bench_lssd_mount_script`, `bench_lssd_mount_record`, `bench_lssd_check_script`; option `--print-lssd-mount`; log lines `LSSD_MOUNT …`, `LSSD_MOUNT_SUMMARY …`, `PRECFG_FAIL <inst> local SSD not mounted at <D>`; manifest `instances[].data_disk` (`class` is `"local-ssd"` or `"boot"`) and `zone_overrides[]`.

## Facts read from the cloud and from the probe on 2026-11-12 (use them; do not re-derive)
- `c3-standard-8-lssd`: 8 vCPU, 32 GiB, `bundledLocalSsds.partitionCount` 2 (two 375 GiB NVMe local SSDs: `/dev/disk/by-id/google-local-nvme-ssd-0` and `-1`). `c4-standard-8-lssd`: 8 vCPU, 30 GiB, partitionCount 1. `c3-standard-8` 32 GiB, `c4-standard-8` 30 GiB.
- Quota: `gcloud compute regions describe` lists `C3_CPUS` (100 to 300 per region) and `LOCAL_SSD_TOTAL_GB` (limit 9.2e18, in effect unlimited) but **no `C4_CPUS` metric**: C4's CPU quota is a per-VM-family quota (`CPUS-PER-VM-FAMILY-per-project-region`, 300 per region) that `regions describe` does not show. A C4 node's CPU quota must come out as "not checked" with that reason, never as a silent pass and never as a stop.
- On the probe's `c3-standard-8-lssd` VM: boot disk `nvme0n1`, the first local SSD `nvme1n1`; `read_ahead_kb` 128 on both; `max_sectors_kb` 256 (Hyperdisk) against 2048 (local SSD); `nr_requests` 511 against 1023; scheduler `none`; the root file system's fstab options `discard,commit=30,errors=remount-ro`, and the local SSD was mounted `rw,relatime,discard,errors=remount-ro,commit=30` after `mkfs.ext4 -q -F -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard`.
- The shape the env file will ask for (option e, the recommendation going to gate G2): validators 03, 04, 05, 06, 07, 10 (indices 2, 3, 4, 5, 6, 9) on `c3-standard-8-lssd` with the data directory on the local SSD; validators 01, 02, 08, 09 and the observer (indices 0, 1, 7, 8, 10) on `c3-standard-8` with the data directory on the Hyperdisk boot disk; no zone moved. The harness must still serve the other options (a mixed C3/C4 fleet, a moved validator), which is why `BENCH_NODE_ZONES` and the C4 handling are built.

## Every L unit
- Does not commit, does not run `gcloud`, does not touch `tn-node-deployment/` or `common/`, does not edit a file outside its own list (stop and say so if it needs to).
- Checkpoint `tasks/checkpoint-bench6-<unit>.md`: on start read your own checkpoint and continue from the first unfinished section; rewrite it after EACH section (`status:`, `updated:`, `completed:`, `remaining:`, `notes:`).
- Budget: hand back at about 180k tokens with the exact resume point, even if unfinished. Grep first; read ranges; never read `benchmark-deploy.sh` (2,548 lines) or `bench-lib.sh` whole.
- Other agents are editing other files of `benchmark/` at the same time: `git status` lines that are not yours are theirs. Run only your own test modules and the ones your brief lists; never `benchmark/tests/gate.sh`.
- Hand back: status and resume point; `git diff --stat` for your files; every new knob, variable, function, log line and manifest key verbatim; each gate with `EXIT=` and counts; your mutation anchors verbatim; anything another unit's file needs.
