#!/usr/bin/env bash
#
# benchmark-probe.sh — the one-VM GCE probe: one VM of the bench fleet's exact shape (machine type,
# boot disk type, size, IOPS and throughput, the pinned boot image and so its kernel) runs the
# mdbx-writeback-probe arms of benchmark/private/bench6-prep/I-1r/gce-arms.md §2 (g0-g9, plus
# g5-7default-mrand), each beside the bench-6 persist sampler, and the results land in
# results/<run>/probe/. With --disks both the VM is a local-SSD shape and each arm runs on the Hyperdisk
# boot disk and then on the local NVMe SSD, so only the device differs. One driver creates the VM and
# deletes it again.
#
# Subcommands (all need --run-id or BENCH_RUN_ID):
#   plan     print every gcloud argv and every remote script the run would use; ZERO gcloud calls,
#            built from the configuration alone (benchmark/config.sh)
#   up       read-only preflight (credentials, the boot image, the machine type in the zone, the
#            region's CPU quota, no other bench resources in the project), then create the boot disk
#            and the VM, wait until IAP ssh answers (300 s)
#   run      upload the bundle, settle the VM, host probe, then each arm: set read_ahead_kb (16 for the
#            ra16 arm, the boot value for the rest), persist sampler, the probe in its own transient unit under a
#            watchdog, wait, stop the sampler, remove the arm's DB, tar and pull; the safety arm adds five
#            censuses against the live arm and five against the idle DB
#   collect  pull what run could not, write probe/manifest.json, probe/SUMMARY.txt and the run's index
#   down     delete the VM and its disk (only the names generated for this run id, labels checked
#            first) and verify both are gone; --keep prints the delete commands instead
#   all      up -> run -> collect -> down; down is attempted after a failed run, on INT/TERM/HUP and on
#            any exit once up has started (unless --keep)
#
# Options:
#   --run-id <id>             the run id (rYYYYMMDD-HHMM); names the results dir, the VM and its labels
#   --arms <list>             comma list of arm names, groups (g0..g9) or core, the eight arms never to
#                             cut (ARMS_CORE) [all 19 arms]
#   --bin <file>              the probe binary from tools/build-probe-bin.sh; build-info.txt beside it
#                             gives its sha256s (run and all need it unless --dry-run)
#   --zone <zone>             [validator-01's zone, ZONES[0]]
#   --fallback-zones <a,b>    zones tried in order after a stockout [us-west2-b,us-west2-c]
#   --deadline-min <n>        the whole run (up + run + collect) [120]
#   --arm-deadline-secs <n>   one arm's probe, enforced on the VM by a watchdog [900]
#   --dry-run                 any subcommand: print instead of calling gcloud (plan is always dry)
#   --keep                    down (and the end of all) deletes nothing and prints the commands
#   --allow-fleet             run although other bench resources exist in the project (never touches them)
#   --disks <hyperdisk|both>  hyperdisk: every arm on the boot disk, the fleet's shape [hyperdisk]. both: the
#                             VM is --lssd-machine-type, its first local NVMe SSD is made ext4 and mounted
#                             at /mnt/bench-probe-nvme, and each arm runs twice, as <arm>@hyperdisk (boot
#                             disk) then <arm>@nvme (local SSD); SUMMARY.txt pairs them (PAIR lines)
#   --lssd-machine-type <t>   the --disks both shape, a -lssd shape whose local SSDs come with the machine
#                             type [c3-standard-8-lssd: 8 vCPU, 32 GB, two 375 GiB local SSDs; the fleet's
#                             c3-highcpu-8 has 16 GB, so the two modes differ in RAM, never a pair's records]
#
# RUNBOOK (the orchestrator, from the repo root; RUN = a fresh run id such as r20261111-1800):
#   1. Build the binary. Local docker, about 5-15 min the first time: it pulls rust:1.94-bookworm, the
#      container installs libclang-dev (bindgen), and cargo fetches the reth git checkout Cargo.lock pins.
#      The crate is mounted read-only; cargo's home and target dir (1-2 GB) stay in the out dir.
#        benchmark/tools/build-probe-bin.sh --crate ../mdbx-writeback-probe --out benchmark/work/probe-bin
#      It prints BINARY_SHA256 and SOURCE_SHA256 and writes them to build-info.txt beside the binary, where
#      the driver checks the binary against them and copies them into the manifest. --print shows the
#      docker command and the container script without running anything.
#   2. Read the plan. It makes no gcloud call and writes nothing:
#        BENCH_RUN_ID=RUN benchmark/benchmark-probe.sh plan --bin benchmark/work/probe-bin/mdbx-writeback-probe
#   3. Run it from a shell that survives an hour (tmux), with fresh credentials (gcloud auth login), while
#      no bench fleet exists (the preflight refuses otherwise):
#        BENCH_RUN_ID=RUN benchmark/benchmark-probe.sh all --bin benchmark/work/probe-bin/mdbx-writeback-probe
#      The last line is DOWN_OK (the VM and its disk are gone) or DOWN_INCOMPLETE (the names left to delete;
#      `down` again deletes them). With --keep the VM stays up for a look; `down` deletes it afterwards.
#      Hyperdisk against the local NVMe SSD, the subset that says whether the fix (whole-map MADV_RANDOM)
#      helps or hurts on each device (a fresh RUN):
#        BENCH_RUN_ID=RUN benchmark/benchmark-probe.sh all --bin benchmark/work/probe-bin/mdbx-writeback-probe \
#            --disks both --arms g1-node,g5,g8-nowritemap
#   4. Read results/RUN/probe/SUMMARY.txt first. Its PROBE_RUN line names the mode, the shape and the
#      resident-page reader (fincore, or census: the census tool's --resident-only when the image has no
#      fincore). One PROBE_ARM line per arm (per record with --disks both, <arm>@hyperdisk and <arm>@nvme):
#        device/mdbx    device write bytes / MDBX-dirtied bytes per output: the amplification. Bench 5's
#                       nodes ran at 4.3x; g0 should read about 1.00x.
#        commit/mdbx    the same ratio over the commit window only (median)
#        process/mdbx   folio pages this process dirtied / MDBX-dirtied pages, free of device noise
#        past_used_end  pages resident past the allocation frontier at the end; readahead built them (R1)
#        prefault/grown prefault calls per grown page (summary-i1.csv); about 1.00 with prefault on
#        no_prefault_outputs  outputs that grew with no prefault at all (<arm>.csv); g6-peer's H2 signature
#      then the device writes (write_stats): per measured output the median write requests (wr_ops/out),
#      bytes per request (wr_kib_mean over the arm, wr_kib_p90 of the outputs), flushes, MDBX syncs, the
#      commit's write requests, MDBX's sync ms, the sampler's device ms per write and per flush, and the
#      arm's totals; n/a where the source has none. Its BIND line sets the commit's request and byte
#      rates against the device's provisioned IOPS and MiB/s and names the larger share (a local SSD has
#      no cap: n/a). With --disks both a PAIR line puts each arm's two devices side by side.
#      Then the SAFETY line of the safety arm (g9-sampler): PASS needs its ratio_proc_med and
#      prefault_per_grown within 0.02 of its reference arm (the same flags without --keep-db: g5-7default),
#      beyond_used_resident_max at most 8 pages above it, read_bytes of the census side loop at most 64 KiB
#      in each mode, quiet unchanged=5 of 5 (five censuses as root left the idle DB's residency as it was),
#      quiet steady=4 of 4 (the reader's back-to-back readings agree), and no output that grew without a
#      prefault. The tolerances are SAFE_* below; the line shows both
#      values of every comparison, so a reader can judge "within noise" again.
#      Per arm: arms/<arm>/ (probe.log, results/<arm>.summary.txt, .csv and summary-i1.csv, persist/ with
#      the sampler's CSV and folio census, cmd.txt, journal.txt) and arms/<arm>.status.json. manifest.json
#      has the VM's shape and image, the host probe, each arm's command, start, end, exit code, read_ahead_kb
#      step and its summary-i1.csv row (pwritev_*, gc_*, freelist_*, *_peer, prefault_per_grown, ...), the
#      safety verdict, and the sha256s of the binary, its sources and the bundle.
#   Duration: about 85 min: create and settle 5 min, 20 arms of 2.5-4 min (58 min of probe time) plus
#   about 40 s of sessions and pull each, collect 2 min. The run starts an arm only if it can end, at its
#   900-s watchdog plus 4 min, before --deadline-min (120): the last arm must start by minute 101, which
#   leaves about 25 min for slow quiet gates. `--arms core` (8 arms, about 25 min of probe time) is the
#   short run. down runs in any case.
#   Cost: one c3-highcpu-8 for about 1.5 h, and a 100 GB hyperdisk-balanced boot disk with 20,000 IOPS
#   and 800 MiB/s provisioned for the same time (provisioned IOPS and throughput bill by the hour on top
#   of the GB). No external IP, no bucket, nothing left after DOWN_OK.
#   --disks both with g1-node,g5,g8-nowritemap: 12 records, about 60 min (37 min of probe time, 8 of
#   sessions, the mkfs of the local SSD in setup); all 20 arms twice would pass the 120-min deadline, and
#   the arms that could not end in time are skipped. Cost: one c3-standard-8-lssd (its two 375 GiB local
#   SSDs included) and the same boot disk for about 1 h.
#
# Safety: every gcloud call, and every ssh/scp session, sits behind `[ "${DRY}" = "0" ] || return 0` on
# the line before it, so a dry run returns there. The driver deletes only bench-probe-<run-id> (instance
# and disk). It finds them by listing the whole kind and matching that exact name (no gcloud filter),
# checks the labels benchmark=1, bench-run=<run-id> and tn-role=probe before each delete, never deletes
# an attached disk, and lists again until both names are gone. It refuses to start while any other bench
# resource exists (instances or disks named bench-* or labelled benchmark=1, firewall rules named bench-*)
# unless --allow-fleet. The labels make the VM visible to bench_leftovers and the teardown.

set -uo pipefail

PROBE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

usage() { sed -n '3,/^# RUNBOOK/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "❌ benchmark-probe: $*" >&2; exit 2; }

SUB="${1:-}"
case "${SUB}" in
    plan|up|run|collect|down|all) shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "the first argument must be plan, up, run, collect, down or all" ;;
esac

ARMS_ARG="" BIN="" ZONE_ARG="" FALLBACK_ARG="us-west2-b,us-west2-c" DEADLINE_MIN=120 ARM_DEADLINE=900
DRY=0 KEEP=0 ALLOW_FLEET=0 DISKS=hyperdisk LSSD_TYPE=c3-standard-8-lssd
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --dry-run) DRY=1; shift; continue ;;
        --keep) KEEP=1; shift; continue ;;
        --allow-fleet) ALLOW_FLEET=1; shift; continue ;;
    esac
    [ $# -ge 2 ] || die "$1 needs a value"
    case "$1" in
        --run-id) BENCH_RUN_ID="$2" ;;
        --arms) ARMS_ARG="$2" ;;
        --bin) BIN="$2" ;;
        --zone) ZONE_ARG="$2" ;;
        --fallback-zones) FALLBACK_ARG="$2" ;;
        --deadline-min) DEADLINE_MIN="$2" ;;
        --arm-deadline-secs) ARM_DEADLINE="$2" ;;
        --disks) DISKS="$2" ;;
        --lssd-machine-type) LSSD_TYPE="$2" ;;
        *) die "unknown option '$1' (try --help)" ;;
    esac
    shift 2
done
[ "${SUB}" != plan ] || DRY=1
[ -n "${BENCH_RUN_ID:-}" ] || die "--run-id (or BENCH_RUN_ID) is required"
export BENCH_RUN_ID
case "${DEADLINE_MIN}" in ''|*[!0-9]*|0*) die "--deadline-min '${DEADLINE_MIN}' must be a positive integer" ;; esac
case "${ARM_DEADLINE}" in ''|*[!0-9]*|0*) die "--arm-deadline-secs '${ARM_DEADLINE}' must be a positive integer" ;; esac
[ "${ARM_DEADLINE}" -ge 120 ] || die "--arm-deadline-secs must be at least 120"
case "${DISKS}" in hyperdisk|both) ;; *) die "--disks '${DISKS}' must be hyperdisk or both" ;; esac
# A shape whose local SSDs come with the machine type (C3 offers them only on its -lssd standard shapes):
# the instance create needs no --local-ssd flag, and nothing but the instance holds them.
case "${LSSD_TYPE}" in
    *[!a-z0-9-]*|-*) die "--lssd-machine-type '${LSSD_TYPE}' is not a machine type name" ;;
    *-lssd) ;;
    *) die "--lssd-machine-type '${LSSD_TYPE}' is not a -lssd shape (local SSD bundled with the machine type)" ;;
esac

# shellcheck source=bench-lib.sh
source "${PROBE_DIR}/bench-lib.sh"

# --- names and shape (configuration only) ----------------------------------------------------------
INST="bench-probe-${BENCH_RUN_ID}"
DISK="${INST}"
bench_assert_bench_name instance "${INST}"
_bench_host_name_ok "${INST}" || die "'${INST}' is not a valid instance name"
# The fleet's labels (config.sh) and this VM's role: bench_leftovers and the teardown see it.
LABELS="${INSTANCE_LABELS},tn-role=probe"
case ",${LABELS}," in *",benchmark=1,"*",bench-run=${BENCH_RUN_ID},"*) ;; *) die "INSTANCE_LABELS '${INSTANCE_LABELS}' lacks benchmark=1 or bench-run=${BENCH_RUN_ID}" ;; esac
# --disks both: the -lssd shape (the fleet's c3-highcpu-8 has no local SSD, so the shape, and with it the
# RAM, differs from the fleet's: a confound between the two modes, never inside one run's pairs) and
# the one host-maintenance policy every local-SSD shape takes.
MAINT=MIGRATE
if [ "${DISKS}" = both ]; then MACHINE_TYPE="${LSSD_TYPE}"; MAINT=TERMINATE; fi
PD="${BENCH_RESULTS_DIR}/probe"
STATE="${PD}/probe-state.txt"
REL_PD="${PD#"${REPO_ROOT}/"}"
case "${IMAGE}" in */family/*) die "IMAGE '${IMAGE}' is an image family; the probe boots a pinned image" ;; esac
IMAGE_PROJECT="$(printf '%s' "${IMAGE}" | awk -F/ '$1 == "projects" { print $2 }')"
IMAGE_NAME="${IMAGE##*/}"
[ -n "${IMAGE_PROJECT}" ] && [ -n "${IMAGE_NAME}" ] || die "IMAGE '${IMAGE}' is not projects/<project>/global/images/<name>"

zone_ok() { [[ "${1:-}" =~ ^[a-z]+-[a-z]+[0-9]+-[a-z]$ ]]; }
ZONE="${ZONE_ARG:-${ZONES[0]}}"
zone_ok "${ZONE}" || die "zone '${ZONE}' is not a zone name"
FALLBACK_ZONES=()
for z in $(printf '%s' "${FALLBACK_ARG}" | tr ',' ' '); do
    zone_ok "${z}" || die "fallback zone '${z}' is not a zone name"
    [ "${z}" = "${ZONE}" ] || FALLBACK_ZONES+=("${z}")
done

# Remote layout (root-owned, on the boot disk like the nodes' /var/lib/telcoin).
RB=/var/lib/bench-probe
# --disks both: the local SSD's mount point; the nvme records keep their DBs under ${RNV}/data.
RNV=/mnt/bench-probe-nvme
RBUNDLE=/tmp/bench-probe-bundle.tar.gz
# What setup requires on the VM, beyond bash and coreutils (Essential), with the Ubuntu 24.04 package
# each comes from: python3 (python3), systemd-run/systemctl/journalctl (systemd), findmnt/lsblk
# (util-linux), timeout/sha256sum/stat (coreutils), tar (tar), gzip (gzip, for tar -z), awk (mawk; the
# sampler). The census and the host probe import only the standard library (libpython3.12-stdlib).
# --disks both adds mkfs.ext4 (e2fsprogs), mount/umount (mount) and readlink (coreutils). fincore
# (util-linux-extra on 24.04, not on the image) is optional; curl (the sampler's gauge read) is unused here.
TOOLS_REQUIRED="python3 systemd-run systemctl journalctl findmnt lsblk timeout sha256sum stat tar gzip awk"
TOOLS_NVME="mkfs.ext4 mount umount readlink"
# The local SSD's file system, made as common/observability/obs-vm makes its data disk.
NVME_MKFS="-q -F -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard"
PY_MODULES="import argparse, array, collections, ctypes, ctypes.util, itertools, json, mmap, os, re, shlex, signal, subprocess, sys, time"
SSH_READY_SECS=300
DELETE_SECS=300
WAIT_CHUNK_SECS=300

# --- the arms (benchmark/private/bench6-prep/I-1r/gce-arms.md §2, in run order) ----------------------------
# Plus one arm that table lacks, g5-7default-mrand: the fix (whole-map MADV_RANDOM) on the node's own path
# with nothing broken (prefault on), the fourth cell of g5's prefault x MADV_RANDOM square; it says what
# the fix costs where it has nothing to fix, on each device.
# name|host step|sampler cadence|probe flags. Every arm also gets --tag <name> --data-dir --results-dir
# --disk and the quiet gate. The columns, never the name, drive the behaviour: host step ra16 runs the
# arm at read_ahead_kb 16 (every other arm at the boot value); cadence std = sampler row every 10 s, mdbx
# columns every 30 s, census every 60 s; safety = every 5 s plus the census side loop and the safety
# verdict, whose reference is the arm that runs the same probe flags without --keep-db.
A7="--arm 7 --preload-gb 0.05 --txs 2000 --outputs 240 --warmup 40 --pause-ms 500 --reader-hold 10"
A7N="--arm 7 --preload-gb 0.05 --txs 6500 --outputs 150 --warmup 30 --pause-ms 1000 --reader-hold 20"
P6="--preload-gb 6 --outputs 40 --warmup 3"
QUIET="--quiet-secs 10 --quiet-max-mbps 2 --quiet-retries 6 --quiet-wait-secs 20 --require-quiet"
ARMS_ALL=(
    "g0-baseline|-|std|--arm 1 ${P6}"
    "g1-node|-|std|${A7N} --overflow-per-tx 0.05"
    "g2-readall|-|std|--arm 1 ${P6} --cache-prep readused"
    "g3-ra16-readall|ra16|std|--arm 1 ${P6} --cache-prep readused"
    "g4-mrand|-|std|--arm 5 ${P6}"
    "g4-mrand-readall|-|std|--arm 5 ${P6} --cache-prep readused"
    "g5-7default|-|std|${A7}"
    "g5-7pfoff|-|std|${A7} --prefault-off"
    "g5-7pfoff-mrand|-|std|${A7} --prefault-off --madvise-random"
    "g5-7default-mrand|-|std|${A7} --madvise-random"
    "g6-peer|-|std|${A7} --peer-open-at 60"
    "g6-peer-nr|-|std|${A7} --peer-open-at 60 --peer-nordahead"
    "g6-peer-mrand|-|std|${A7} --peer-open-at 60 --madvise-random"
    "g7-ovf64|-|std|${A7} --overflow-per-tx 0.001 --overflow-value 258000"
    "g7-ovf64-mrand|-|std|${A7} --overflow-per-tx 0.001 --overflow-value 258000 --madvise-random"
    "g7-ovf8|-|std|${A7} --overflow-per-tx 0.01 --overflow-value 30000"
    "g7-longreader|-|std|${A7} --overflow-per-tx 0.05 --long-reader-at 60 --long-reader-for 60"
    "g8-nowritemap|-|std|--arm 3 ${P6}"
    "g8-nowritemap-readall|-|std|--arm 3 ${P6} --cache-prep readused"
    "g9-sampler|-|safety|${A7} --keep-db"
)
# The eight arms gce-arms.md §2 says never to cut. `--arms core` runs them alone, for when the VM time must
# be shortened; it combines with names and groups (`--arms core,g2-readall`). Cut first, in this order:
# g8-nowritemap-readall, g4-mrand, g7-ovf8, g6-peer-mrand, g3-ra16-readall, g7-ovf64-mrand.
ARMS_CORE="g0-baseline g1-node g5-7default g5-7pfoff g6-peer g6-peer-nr g7-ovf64 g9-sampler"
for want in ${ARMS_CORE}; do
    hit=0; for e in "${ARMS_ALL[@]}"; do [ "${e%%|*}" != "${want}" ] || hit=1; done
    [ "${hit}" = 1 ] || die "ARMS_CORE names '${want}', which is not in ARMS_ALL"
done
ARMS=()
if [ -z "${ARMS_ARG}" ]; then
    ARMS=("${ARMS_ALL[@]}")
else
    WANT=" $(printf '%s' "${ARMS_ARG}" | tr ',' ' ') "
    WANT="${WANT// core / ${ARMS_CORE} }"
    for want in ${WANT}; do
        hit=0
        for e in "${ARMS_ALL[@]}"; do
            n="${e%%|*}"
            if [ "${n}" = "${want}" ] || [ "${n%%-*}" = "${want}" ]; then hit=1; fi
        done
        [ "${hit}" = 1 ] || die "--arms: '${want}' is not an arm, a group (g0..g9) or core"
    done
    for e in "${ARMS_ALL[@]}"; do
        n="${e%%|*}"
        for want in ${WANT}; do
            if [ "${n}" = "${want}" ] || [ "${n%%-*}" = "${want}" ]; then ARMS+=("${e}"); break; fi
        done
    done
fi
arm_field() { printf '%s' "$1" | cut -d'|' -f"$2"; }

# The records the run makes, in order. --disks hyperdisk: one per selected arm, the arm's own entry
# (its name is the record's name and key). --disks both: two per arm, the Hyperdisk boot disk first,
# then the local SSD, each entry `<arm>_<dev>|<host step>|<cadence>|<flags>|<dev>|<arm>`: the key
# `<arm>_<dev>` names the arm's files, units, tag and tarball (no `@`: systemd reads it as a template
# instance), the record's name in the manifest and SUMMARY.txt is `<arm>@<dev>`.
records_of() {
    local e
    for e in "$@"; do
        if [ "${DISKS}" = both ]; then
            printf '%s\n' "${e%%|*}_hyperdisk|${e#*|}|hyperdisk|${e%%|*}" "${e%%|*}_nvme|${e#*|}|nvme|${e%%|*}"
        else
            printf '%s\n' "${e}"
        fi
    done
}
RECS=()
while IFS= read -r r; do RECS+=("${r}"); done < <(records_of ${ARMS[@]+"${ARMS[@]}"})
ALL_RECS=()
while IFS= read -r r; do ALL_RECS+=("${r}"); done < <(records_of "${ARMS_ALL[@]}")
rec_key() { arm_field "$1" 1; }
rec_dev() { local d; d="$(arm_field "$1" 5)"; printf '%s' "${d:-hyperdisk}"; }
rec_arm() { local a; a="$(arm_field "$1" 6)"; printf '%s' "${a:-$(arm_field "$1" 1)}"; }
rec_name() { if [ "${DISKS}" = both ]; then printf '%s@%s' "$(rec_arm "$1")" "$(rec_dev "$1")"; else rec_key "$1"; fi; }
# rec_data <entry> — the record's data dir on the VM; rec_data_ref the same as the scripts write it where
# they have $B (the boot disk's text stays as it always was).
rec_data() { if [ "$(rec_dev "$1")" = nvme ]; then printf '%s' "${RNV}/data"; else printf '%s' "${RB}/data"; fi; }
rec_data_ref() { if [ "$(rec_dev "$1")" = nvme ]; then printf '%s' "${RNV}/data"; else printf '%s' '$B/data'; fi; }
# rec_by_key <key> — the record (of ALL_RECS) with that key, "" when none.
rec_by_key() { local s; for s in "${ALL_RECS[@]}"; do [ "${s%%|*}" != "$1" ] || { printf '%s' "${s}"; return 0; }; done; }

# --- output helpers ---------------------------------------------------------------------------------
exec 3>&1
log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&3; }
# show <tag> <argv...> — "+ <tag> <argv>" on the plan stream (fd 3 = stdout, also inside $(...)); the argv
# shell-quoted (copy-pasteable), local paths under the repo shown relative to its root.
show() {
    local a
    { printf '  + %s' "$1"; shift
      for a in "$@"; do printf ' %q' "${a//"${REPO_ROOT}/"/}"; done; printf '\n'; } >&3
}
now() { date -u +%s; }
# shellcheck disable=SC2086  # the tool and its flags, one word each
sha256_file() { local c; c="$(_bench_sha256_cmd)" || return 1; ${c} "$1" | awk '{ print $1 }'; }
state_get() { [ -r "${STATE}" ] && sed -n "s/^$1=//p" "${STATE}" | tail -n 1; }
state_set() { printf '%s=%s\n' "$1" "$2" >> "${STATE}"; }

# kill_tree <pid> — TERM a process and every descendant.
kill_tree() {
    local c
    for c in $(pgrep -P "$1" 2>/dev/null); do kill_tree "${c}"; done
    kill -TERM "$1" 2>/dev/null || true
}

# with_deadline <secs> <out-file> <stdin-text> <cmd...> — <cmd> (function or binary) in the background,
# <stdin-text> on its stdin, stdout and stderr to <out-file>; after <secs> it and its children get TERM.
# Returns the command's status, 124 at the deadline.
with_deadline() {
    local secs="$1" out="$2" text="$3" pid waited=0 rc=0
    shift 3
    printf '%s\n' "${text}" | "$@" > "${out}" 2>&1 &
    pid=$!
    while kill -0 "${pid}" 2>/dev/null; do
        if [ "${waited}" -ge "${secs}" ]; then
            kill_tree "${pid}"
            wait "${pid}" 2>/dev/null
            echo "with_deadline: ${secs} s passed; stopped" >> "${out}"
            return 124
        fi
        sleep 1
        waited=$((waited + 1))
    done
    wait "${pid}" || rc=$?
    return "${rc}"
}

# --- the only places that reach GCP ------------------------------------------------------------------
# gc <secs> <gcloud args...> — one gcloud call under an alarm, stdin closed. Read-only or not, it is
# printed first and a dry run returns before it.
gc() {
    local secs="$1"
    shift
    show "[alarm ${secs}s]" gcloud "$@"
    [ "${DRY}" = "0" ] || return 0
    perl -e 'alarm shift; exec @ARGV' "${secs}" gcloud "$@" </dev/null
}

# remote <label> <secs> <out-file> <generator> [args...] — one IAP session: the generator's script on
# stdin to `sudo bash -s` on the VM (tn_iap_ssh_stdin, transport faults retried), under a local deadline.
# The plan prints the script; a live run keeps a copy in probe/scripts/<label>.sh.
remote() {
    local label="$1" secs="$2" out="$3" text
    shift 3
    text="$("$@")" || { echo "❌ cannot render the ${label} script" >&2; return 1; }
    show "[alarm ${secs}s]" gcloud compute ssh "${INST}" --zone="${ZONE}" --project="${PROJECT_ID}" "${TN_SSH_FLAGS[@]}" \
        --ssh-flag=-T --command="sudo bash -s" "<${label}.sh"
    if [ "${DRY}" = 1 ]; then
        printf -- '----- remote script %s -----\n%s\n----- end %s -----\n' "${label}" "${text}" "${label}" >&3
    fi
    [ "${DRY}" = "0" ] || return 0
    with_deadline "${secs}" "${out}" "${text}" tn_iap_ssh_stdin "${INST}" "${ZONE}"
    local rc=$?
    printf '%s\n' "${text}" > "${PD}/scripts/${label}.sh"
    return "${rc}"
}

# upload <local-file> <remote-path> — scp to the VM (tn_iap_scp, retried), 300 s.
upload() {
    show "[alarm 300s]" gcloud compute scp "$1" "${INST}:$2" --zone="${ZONE}" --project="${PROJECT_ID}" \
        --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
    [ "${DRY}" = "0" ] || return 0
    with_deadline 300 "${PD}/sessions/upload.out" "" tn_iap_scp "$1" "${INST}" "${ZONE}" "$2"
}

# pull <remote-path> <local-file> — scp from the VM (bench_iap_scp_down: 300-s alarm per attempt, IAP
# refusals retried), the whole pull under 1000 s.
pull() {
    show "[alarm 300s x3]" gcloud compute scp "${INST}:$1" "$2" --zone="${ZONE}" --project="${PROJECT_ID}" \
        --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
    [ "${DRY}" = "0" ] || return 0
    with_deadline 1000 "${PD}/sessions/pull-$(basename "$2").out" "" bench_iap_scp_down "${INST}" "${ZONE}" "$1" "$2"
}

# --- labels -------------------------------------------------------------------------------------------
# ours <json object> — rc 0 when it is this run's probe resource: the generated name and the three labels.
ours() {
    printf '%s' "$1" | jq -e --arg n "${INST}" --arg r "${BENCH_RUN_ID}" '
        .name == $n and (.labels.benchmark // "") == "1" and (.labels["bench-run"] // "") == $r
        and (.labels["tn-role"] // "") == "probe"' >/dev/null 2>&1
}

# find_named <instances|disks> <name> — the one resource of that exact name in the project as compact
# JSON ("" when there is none); rc 1 when the list failed or is not a JSON array. The whole kind is
# listed and the name matched here, exactly: "not there" never rests on gcloud's filter semantics.
find_named() {
    local out
    out="$(gc 120 compute "$1" list --project="${PROJECT_ID}" --format=json)" || return 1
    [ "${DRY}" = "0" ] || return 0
    printf '%s' "${out}" | jq -e 'type == "array"' >/dev/null 2>&1 || return 1
    printf '%s' "${out}" | jq -c --arg n "$2" '[.[] | select(.name == $n)] | .[0] // empty' 2>/dev/null || return 1
}

# --- preflight (read-only) ----------------------------------------------------------------------------
# other_bench_resources — one line per bench resource that is not this probe's (bench_leftovers'
# selection, minus buckets), failing closed: a list that cannot be read is an error, never "clean".
other_bench_resources() {
    local kind out
    for kind in instances disks; do
        out="$(gc 120 compute "${kind}" list --project="${PROJECT_ID}" --format=json)" || { echo "UNREADABLE ${kind}"; continue; }
        [ "${DRY}" = "0" ] || continue
        printf '%s' "${out}" | jq -r --arg k "${kind%s}" --arg n "${INST}" '
            .[]? | select(((.name | test("^bench-")) or ((.labels.benchmark // "") == "1")) and .name != $n)
            | $k + " " + .name' 2>/dev/null || echo "UNREADABLE ${kind}"
    done
    out="$(gc 120 compute firewall-rules list --project="${PROJECT_ID}" --format=json)" || { echo "UNREADABLE firewall-rules"; return 0; }
    [ "${DRY}" = "0" ] || return 0
    printf '%s' "${out}" | jq -r '.[]? | select(.name | test("^bench-")) | "firewall-rule " + .name' 2>/dev/null \
        || echo "UNREADABLE firewall-rules"
}

preflight() {
    local tok img st dep z mt vcpu metric region json have others
    echo "-- preflight (read-only): credentials, boot image, machine type, CPU quota, other bench resources" >&3
    tok="$(gc 60 auth print-access-token)" || tok=""
    img="$(gc 60 compute images describe "${IMAGE_NAME}" --project="${IMAGE_PROJECT}" --format=json)" || img=""
    mt="$(gc 60 compute machine-types describe "${MACHINE_TYPE}" --zone="${ZONE}" --project="${PROJECT_ID}" --format='value(guestCpus)')" || mt=""
    region="$(tn_region_from_zone "${ZONE}")"
    json="$(gc 60 compute regions describe "${region}" --project="${PROJECT_ID}" --format=json)" || json=""
    others="$(other_bench_resources)"
    [ "${DRY}" = "0" ] || return 0
    [ -n "${tok}" ] || die "no gcloud credentials (gcloud auth print-access-token failed): run gcloud auth login"
    st="$(printf '%s' "${img}" | jq -r '.status // empty' 2>/dev/null)" || st=""
    dep="$(printf '%s' "${img}" | jq -r '.deprecated.state // "ACTIVE"' 2>/dev/null)" || dep=""
    [ "${st}" = READY ] || die "boot image ${IMAGE} is not READY (status '${st:-unreadable}')"
    case "${dep}" in OBSOLETE|DELETED) die "boot image ${IMAGE} is ${dep}" ;; esac
    printf '%s\n' "${img}" > "${PD}/image.json"
    vcpu="${mt%%[!0-9]*}"
    [ -n "${vcpu}" ] || die "${MACHINE_TYPE} is not offered in ${ZONE} (machine-types describe gave '${mt}')"
    metric="$(bench_cpu_quota_metric "${MACHINE_TYPE}")"
    have="$(printf '%s' "${json}" | jq -r --arg q "${metric}" '[.quotas[]? | select(.metric == $q) | (.limit - .usage) | floor][0] // empty' 2>/dev/null)" || have=""
    if [ -z "${have}" ]; then
        bench_warn "${region}: ${metric} quota not readable; the create will say if it is short"
    elif [ "${have}" -lt "${vcpu}" ]; then
        die "${region}: ${metric} headroom ${have} < ${vcpu} vCPUs"
    fi
    if [ -n "${others}" ]; then
        if [ "${ALLOW_FLEET}" = 1 ]; then
            bench_warn "other bench resources exist (--allow-fleet: going on; none of them is touched):"
            printf '%s\n' "${others}" | sed 's/^/      /' >&2
        else
            die "other bench resources exist in the project; the probe runs before or after a fleet, never beside it (--allow-fleet to override):
$(printf '%s\n' "${others}" | sed 's/^/      /')"
        fi
    fi
    log "preflight ok: image ${IMAGE_NAME} READY (${dep}), ${MACHINE_TYPE} (${vcpu} vCPU) in ${ZONE}, ${metric} headroom ${have:-?}"
}

# --- up -----------------------------------------------------------------------------------------------
create_disk() {   # create_disk <zone>
    gc 300 compute disks create "${DISK}" --project="${PROJECT_ID}" --zone="$1" \
        --image="${IMAGE}" --type="${NODE_DISK_TYPE}" --size="${NODE_DISK_SIZE}GB" \
        ${NODE_DISK_IOPS:+--provisioned-iops="${NODE_DISK_IOPS}"} \
        ${NODE_DISK_THROUGHPUT:+--provisioned-throughput="${NODE_DISK_THROUGHPUT}"} \
        --labels="${LABELS}" --description="bench one-VM probe ${BENCH_RUN_ID}"
}

# create_vm <zone> — the VM on the boot disk create_disk made. Its only disk flag is that boot disk
# (auto-delete=yes): with --disks both the local SSDs come with the -lssd machine type, no flag asks for
# them and no disk resource holds them (gcloud compute disks never lists them), so deleting the instance
# releases them and down's two deletes cover everything the run created.
create_vm() {
    gc 300 compute instances create "${INST}" --project="${PROJECT_ID}" --zone="$1" \
        --machine-type="${MACHINE_TYPE}" \
        --network-interface="network-tier=PREMIUM,subnet=default,nic-type=GVNIC,stack-type=IPV4_ONLY,no-address" \
        --disk="name=${DISK},device-name=${DISK},boot=yes,auto-delete=yes,mode=rw" \
        --maintenance-policy="${MAINT}" --provisioning-model=STANDARD \
        --no-service-account --no-scopes --tags=bench-probe --labels="${LABELS}" \
        --description="bench one-VM probe ${BENCH_RUN_ID}" \
        --no-shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring --reservation-affinity=any
}

script_ssh_ready() { echo 'echo PROBE_SSH_READY'; }

wait_ssh() {
    local start out
    start="$(now)"
    out="${PD}/sessions/ssh-ready.out"
    echo "-- wait for IAP ssh: one session every 10 s, ${SSH_READY_SECS} s deadline" >&3
    while :; do
        TN_IAP_RETRIES=0 remote ssh-ready 60 "${out}" script_ssh_ready
        [ "${DRY}" = "0" ] || return 0
        if grep -q '^PROBE_SSH_READY' "${out}" 2>/dev/null; then
            log "ssh ready on ${INST} after $(( $(now) - start )) s"
            return 0
        fi
        [ $(( $(now) - start )) -lt "${SSH_READY_SECS}" ] || { echo "❌ ${INST}: no ssh within ${SSH_READY_SECS} s" >&2; return 1; }
        sleep 10
    done
}

cmd_up() {
    local zones z json djson out rc reuse=0
    echo "== up: ${INST} (${MACHINE_TYPE}, ${NODE_DISK_TYPE} ${NODE_DISK_SIZE} GB, ${IMAGE_NAME}) in ${ZONE}" >&3
    [ "${DRY}" = 1 ] || mkdir -p "${PD}/sessions" "${PD}/scripts" "${PD}/arms" || return 1
    preflight
    if json="$(find_named instances "${INST}")"; then :; else echo "❌ cannot list instances" >&2; return 1; fi
    if [ -n "${json}" ]; then
        ours "${json}" || { echo "❌ an instance named ${INST} exists without this run's probe labels: not touching it" >&2; return 1; }
        ZONE="$(printf '%s' "${json}" | jq -r '.zone | split("/") | last')"
        log "${INST} already exists in ${ZONE} with this run's labels: reusing it"
        grep -q "^zone=${ZONE}$" "${STATE}" 2>/dev/null || state_set zone "${ZONE}"
        wait_ssh
        return
    fi
    zones=("${ZONE}" ${FALLBACK_ZONES[@]+"${FALLBACK_ZONES[@]}"})
    if djson="$(find_named disks "${DISK}")"; then :; else echo "❌ cannot list disks" >&2; return 1; fi
    if [ -n "${djson}" ]; then
        ours "${djson}" || { echo "❌ a disk named ${DISK} exists without this run's probe labels: not touching it" >&2; return 1; }
        [ "$(printf '%s' "${djson}" | jq '.users // [] | length')" = 0 ] || { echo "❌ disk ${DISK} is attached: not touching it" >&2; return 1; }
        zones=("$(printf '%s' "${djson}" | jq -r '.zone | split("/") | last')")
        reuse=1
        log "disk ${DISK} already exists in ${zones[0]} with this run's labels: the VM boots from it"
    fi
    echo "-- create the boot disk and the VM (stockout: next zone of ${zones[*]})" >&3
    for z in "${zones[@]}"; do
        rc=0
        out=""
        [ "${reuse}" = 1 ] || out="$(create_disk "${z}" 2>&1)" || rc=$?
        [ "${DRY}" = "0" ] || out="$(create_vm "${z}")"
        [ "${DRY}" = "0" ] || break
        printf '%s\n' "${out}" > "${PD}/sessions/create-disk-${z}.out"
        if [ "${rc}" -ne 0 ]; then
            bench_is_stockout "${out}" && { log "${z}: disk stockout, next zone"; continue; }
            echo "❌ disks create in ${z} failed (rc ${rc}): ${out}" >&2
            return 1
        fi
        state_set disk_zone "${z}"
        rc=0
        out="$(create_vm "${z}" 2>&1)" || rc=$?
        printf '%s\n' "${out}" > "${PD}/sessions/create-vm-${z}.out"
        if [ "${rc}" -eq 0 ]; then
            ZONE="${z}"
            state_set zone "${z}"
            state_set created_unix "$(now)"
            state_set boot_read_ahead_kb ""
            [ "${DISKS}" != both ] || state_set boot_read_ahead_kb_nvme ""
            log "created ${INST} in ${z}"
            wait_ssh
            return
        fi
        echo "❌ instances create in ${z} failed (rc ${rc}): ${out}" >&2
        ZONE="${z}"
        delete_disk || return 1
        bench_is_stockout "${out}" || return 1
        log "${z}: stockout, next zone"
    done
    if [ "${DRY}" = 1 ]; then wait_ssh; return 0; fi
    echo "❌ no zone of ${zones[*]} could host ${MACHINE_TYPE}" >&2
    return 1
}

# --- remote scripts -------------------------------------------------------------------------------------
script_setup() {
    cat <<EOS
# setup: settle the fresh VM, unpack and check the bundle, check the tools the arms use
set -u
B=${RB}
fail(){ echo "SETUP_FAIL \$*"; exit 1; }
r=0; timeout 300 cloud-init status --wait >/dev/null 2>&1 || r=\$?
echo "SETUP_NOTE cloud-init rc=\$r"
s="\$(timeout 300 systemctl is-system-running --wait 2>/dev/null)" || true
echo "SETUP_NOTE system=\${s:-unknown}"
# The arms need a disk-quiet VM: the package timers would write during an arm.
for u in apt-daily.timer apt-daily-upgrade.timer apt-daily.service apt-daily-upgrade.service unattended-upgrades.service; do
    systemctl stop "\$u" >/dev/null 2>&1 || true
done
mkdir -p "\$B/bin" "\$B/data" "\$B/arms" || fail "mkdir \$B"
tar -xzf ${RBUNDLE} -C "\$B/bin" || fail "cannot unpack ${RBUNDLE}"
( cd "\$B/bin" && sha256sum -c --quiet SHA256SUMS ) || fail "bundle checksums differ"
chmod 0755 "\$B/bin/mdbx-writeback-probe" "\$B/bin/node-persist-sampler.sh"
# Every tool the remote scripts and the sampler need (TOOLS_REQUIRED: all from Ubuntu 24.04's base
# packages) and every module the census and the host probe import. fincore is optional: Ubuntu 24.04
# moved it to util-linux-extra, which the image lacks. Without it, residency comes from the bundled
# census tool's --resident-only (mincore over a map nothing reads), here and in the sampler.
for t in ${TOOLS_REQUIRED}; do command -v "\$t" >/dev/null 2>&1 || fail "no \$t"; done
python3 -c '${PY_MODULES}' >/dev/null 2>&1 || fail "python3 cannot import every module the census and the host probe use"
timeout 60 python3 "\$B/bin/folio-census.py" --file "\$B/bin/folio-census.py" --resident-only >/dev/null 2>&1 || fail "the census tool's --resident-only does not run here"
if command -v fincore >/dev/null 2>&1; then rr=fincore; else rr=census; fi
"\$B/bin/mdbx-writeback-probe" --help >/dev/null 2>&1 || fail "the probe binary does not start here (glibc?)"
EOS
    [ "${DISKS}" != both ] || script_setup_nvme
    echo 'echo "SETUP_OK kernel=$(uname -r) resident_reader=$rr"'
}

# script_setup_nvme — (--disks both) the local SSD: the first of the shape's local NVMe SSDs
# (google-local-nvme-ssd-0) made ext4 the way the obs VM makes its data disk (no lazy init: its
# background zeroing would write during the arms), mounted at ${RNV} with the options the image's fstab
# gives / (the fleet's data dir, /var/lib/telcoin, lives on /), so the two devices differ in the device
# only. A run again on the same VM keeps the mount it finds. Anything else fails the setup, and the run
# with it: an nvme record never runs on the boot disk.
script_setup_nvme() {
    cat <<EOS
N=${RNV}
for t in ${TOOLS_NVME}; do command -v "\$t" >/dev/null 2>&1 || fail "no \$t"; done
L=/dev/disk/by-id/google-local-nvme-ssd-0
# The guest environment's udev rules name the local SSDs; without them, the first disk whose model is
# GCE's local NVMe SSD (nvme_card; a Hyperdisk or PD reads nvme_card-pd).
[ -e "\$L" ] || L="\$(lsblk -dnpo NAME,MODEL 2>/dev/null | awk '\$2 == "nvme_card" { print \$1; exit }')"
[ -n "\$L" ] && [ -e "\$L" ] || fail "nvme: no google-local-nvme-ssd-0 and no nvme_card disk (${MACHINE_TYPE} without a local SSD?)"
NV="\$(readlink -f "\$L")"
case "\$NV" in /dev/nvme[0-9]*n[0-9]*) ;; *) fail "nvme: \$L is '\$NV', not an NVMe namespace" ;; esac
case "\$(findmnt -no SOURCE --target /)" in "\$NV"|"\$NV"p*) fail "nvme: \$NV holds /" ;; esac
O="\$(findmnt -s -no OPTIONS --mountpoint / 2>/dev/null | head -n 1)"
[ -n "\$O" ] || fail "nvme: no fstab options for /"
if [ "\$(findmnt -no SOURCE --mountpoint "\$N" 2>/dev/null)" = "\$NV" ]; then
    mk=kept
else
    m="\$(findmnt -no TARGET --source "\$NV" 2>/dev/null | head -n 1)"
    if [ -n "\$m" ]; then umount "\$NV" || fail "nvme: \$NV is mounted on \$m and does not unmount"; echo "SETUP_NOTE nvme: unmounted \$NV from \$m"; fi
    timeout 600 mkfs.ext4 ${NVME_MKFS} "\$NV" || fail "nvme: mkfs.ext4 \$NV failed"
    mkdir -p "\$N" || fail "nvme: mkdir \$N"
    mount -t ext4 -o "\$O" "\$NV" "\$N" || fail "nvme: mount \$NV on \$N failed"
    mk=done
fi
[ "\$(findmnt -no SOURCE --mountpoint "\$N" 2>/dev/null)" = "\$NV" ] || fail "nvme: \$N is not \$NV after the mount"
mkdir -p "\$N/data" || fail "nvme: mkdir \$N/data"
echo "SETUP_NVME dev=\$NV mount=\$N mkfs=\$mk fstab_root_options=\$O options=\$(findmnt -no OPTIONS --mountpoint "\$N") root_options=\$(findmnt -no OPTIONS --mountpoint /)"
EOS
}

script_host_probe() {
    echo "mkdir -p ${RB}/data"
    echo "# >>> bench-lib: bench_host_probe_script"
    bench_host_probe_script "${INST}" "${RB}/data"
    echo "# <<< bench-lib: bench_host_probe_script"
}

# script_host_probe_nvme — (--disks both) the host probe of the local SSD's data dir: its disk, its
# read_ahead_kb (the value the nvme records put back) and its mount. Never a mkdir: a data dir that is
# not on the local SSD's mount gives probe_failed, so no nvme record can fall back to the boot disk.
script_host_probe_nvme() {
    echo "# host probe of ${RNV}/data, the local SSD"
    echo "[ \"\$(findmnt -no TARGET --target ${RNV}/data 2>/dev/null)\" = ${RNV} ] || { echo \"HOST_PROBE ${INST} probe_failed ${RNV}/data is not on the local SSD mount\"; exit 0; }"
    echo "# >>> bench-lib: bench_host_probe_script"
    bench_host_probe_script "${INST}" "${RNV}/data"
    echo "# <<< bench-lib: bench_host_probe_script"
}

# arm_unit_script <key> <cadence> <flags> <data dir> — the unit's script (written on the VM by the start
# session): the probe under a watchdog of ARM_DEADLINE s; probe.pid for the sampler; rc, timed_out,
# start, probe_end (the probe's exit: the end of its measured outputs, for the sampler's window), end, done.
arm_unit_script() {
    local name="$1" cad="$2" flags="$3" dd="$4" a="${RB}/arms/$1"
    cat <<EOS
#!/bin/bash
# probe arm ${name}: run by systemd-run as bench-probe-arm-${name}; \$1 = the disk under ${dd}
A=${a}
cd "\$A" || exit 1
date +%s > "\$A/start"
${RB}/bin/mdbx-writeback-probe ${flags} ${QUIET} --tag ${name} --data-dir ${dd} --results-dir \$A/results --disk "\$1" > "\$A/probe.log" 2>&1 &
p=\$!
echo "\$p" > "\$A/probe.pid"
( sleep ${ARM_DEADLINE}; if kill -0 "\$p" 2>/dev/null; then echo 1 > "\$A/timed_out"; kill -TERM "\$p"; sleep 30; kill -KILL "\$p" 2>/dev/null; fi ) &
w=\$!
EOS
    if [ "${cad}" = safety ]; then
        echo "bash \"\$A/safety.sh\" live \"\$p\" > \"\$A/census-safety.txt\" 2>&1 &"
        echo 's=$!'
    fi
    cat <<'EOS'
rc=0
wait "$p" || rc=$?
date +%s > "$A/probe_end"
kill "$w" 2>/dev/null
EOS
    if [ "${cad}" = safety ]; then
        echo 'wait "$s"'
        echo "bash \"\$A/safety.sh\" quiet >> \"\$A/census-safety.txt\" 2>&1"
    fi
    cat <<'EOS'
date +%s > "$A/end"
echo "$rc" > "$A/rc"
touch "$A/done"
EOS
}

# arm_safety_script <key> <data dir> — the safety arm's census check: five folio censuses as root, each
# between two readings of mdbx.dat's resident pages; `live` against the running arm (from 60 s after the
# file appears), `quiet` after it ended (the DB is kept: residency must not move at all). The reader is
# fincore when the VM has it, else the census tool's --resident-only (setup checked it runs). Neither can
# move what it reads: both map the file PROT_NONE and ask mincore, which never faults a page in, and the
# census opens it O_NOATIME and never reads it. The arm checks that rather than trusting it: read_bytes
# is the side loop's own block reads, its reaped children (the reader, the census) included, so a page
# any of them pulled into the cache is counted there (and is bounded by SAFE_MAX_READ_BYTES); `steady`
# counts the readings that agree with the reading just before them with nothing between (quiet: 4 of
# 4), which a reader that moved residency could not give; `reader` names it.
arm_safety_script() {
    local name="$1" dd="$2"
    cat <<EOS
#!/bin/bash
F=${dd}/${name}/mdbx.dat
C=${RB}/bin/folio-census.py
A=${RB}/arms/${name}
EOS
    cat <<'EOS'
mode="$1"; p="${2:-}"
if command -v fincore >/dev/null 2>&1; then
    reader=fincore; resof() { timeout 20 fincore -n -r -o PAGES "$1" 2>/dev/null | tr -d ' '; }
else
    reader=census; resof() { timeout 20 python3 "$C" --file "$1" --resident-only 2>/dev/null | tr -d ' '; }
fi
res() { resof "$F"; }
rb() { local k v; while read -r k v; do if [ "$k" = read_bytes: ]; then echo "$v"; return; fi; done < "/proc/$$/io"; echo 0; }
# Warm-up outside the count: python3, the census's modules and the reader come off the disk once here (a
# census of the census script itself and a reading of it), so read_bytes below is what the censuses of mdbx.dat read.
timeout 60 python3 "$C" --file "$C" --header >/dev/null 2>&1; resof "$C" >/dev/null
if [ "$mode" = live ]; then
    n=0; while [ ! -e "$F" ] && [ "$n" -lt 300 ]; do sleep 5; n=$((n + 5)); done
    sleep 60
fi
io0="$(rb)"; runs=0; same=0; steady=0; prev=""
for i in 1 2 3 4 5; do
    if [ "$mode" = live ] && ! kill -0 "$p" 2>/dev/null; then echo "CENSUS_SAFETY $mode i=$i writer_gone"; break; fi
    b="$(res)"
    if [ -n "$prev" ] && [ "$prev" = "$b" ]; then steady=$((steady + 1)); fi
    if [ "$mode" = live ]; then
        timeout 60 python3 "$C" --file "$F" --pid "$p" --header > "$A/census-$mode-$i.txt" 2>&1; crc=$?
    else
        timeout 60 python3 "$C" --file "$F" --header > "$A/census-$mode-$i.txt" 2>&1; crc=$?
    fi
    a="$(res)"
    prev="$a"
    runs=$((runs + 1))
    if [ -n "$b" ] && [ "$b" = "$a" ]; then same=$((same + 1)); fi
    echo "CENSUS_SAFETY $mode i=$i res_before=${b:--} res_after=${a:--} census_rc=$crc"
    if [ "$mode" = live ]; then sleep 10; fi
done
io1="$(rb)"
echo "CENSUS_SAFETY_IO $mode runs=$runs unchanged=$same read_bytes=$((io1 - io0)) steady=$steady reader=$reader"
EOS
}

script_arm_start() {
    local e="$1" name step cad flags a iv me ce ra ral dd ddr
    name="$(rec_key "${e}")"; step="$(arm_field "${e}" 2)"; cad="$(arm_field "${e}" 3)"; flags="$(arm_field "${e}" 4)"
    dd="$(rec_data "${e}")"; ddr="$(rec_data_ref "${e}")"
    a="${RB}/arms/${name}"
    if [ "${cad}" = safety ]; then iv=5 me=5 ce=5; else iv=10 me=30 ce=60; fi
    cat <<EOS
# arm ${name}: start (returns at once; the arm runs in its own unit)
set -u
B=${RB}
A=${a}
if [ -e "\$A/started" ]; then echo "ARM_START ${name} already"; exit 0; fi
mkdir -p "\$A/results" "\$A/persist" || { echo "ARM_START ${name} failed mkdir"; exit 1; }
EOS
    # An nvme record runs only on the local SSD's mount: never on a data dir that fell back to the boot disk.
    if [ "$(rec_dev "${e}")" = nvme ]; then
        echo "[ \"\$(findmnt -no TARGET --target ${dd} 2>/dev/null)\" = ${RNV} ] || { echo \"ARM_START ${name} failed ${dd} is not on the local SSD mount\"; exit 1; }"
    fi
    cat <<EOS
DEV="\$(findmnt -no SOURCE --target "${ddr}")"
DISK="\$(lsblk -no PKNAME "\$DEV" 2>/dev/null | head -n 1)"
[ -n "\$DISK" ] || DISK="\${DEV#/dev/}"
case "\$DISK" in ''|*[!a-z0-9]*) echo "ARM_START ${name} failed disk '\$DISK'"; exit 1 ;; esac
EOS
    # Every arm sets the read_ahead_kb it runs with (16 with host step ra16, else the boot value of its
    # device), so an ra16 arm whose finish could not put the boot value back never leaves a later arm at
    # 16. No boot value known (the host probe failed): no arm sets it, and run_arm skips the ra16 arm.
    if [ "${step}" = ra16 ]; then ra=16; ral=16; else ra="$(rec_boot_ra "${e}")"; ral="<boot value>"; fi
    if [ -n "${ra}" ]; then
        echo "# >>> bench-lib: bench_host_step_script read-ahead-kb ${ral}"
        bench_host_step_script "${INST}" read-ahead-kb "${ra}" "${dd}" || return 1
        echo "# <<< bench-lib: bench_host_step_script"
        echo "[ \"\$HOST_STEP_RC\" = 0 ] || { echo \"ARM_START ${name} failed host step\"; exit 1; }"
    fi
    echo "cat > \"\$A/unit.sh\" <<'PROBE_UNIT'"
    arm_unit_script "${name}" "${cad}" "${flags}" "${dd}"
    echo "PROBE_UNIT"
    if [ "${cad}" = safety ]; then
        echo "cat > \"\$A/safety.sh\" <<'PROBE_SAFETY'"
        arm_safety_script "${name}" "${dd}"
        echo "PROBE_SAFETY"
    fi
    cat <<EOS
echo "${RB}/bin/mdbx-writeback-probe ${flags} ${QUIET} --tag ${name} --data-dir ${dd} --results-dir \$A/results --disk \$DISK" > "\$A/cmd.txt"
systemd-run --unit=bench-probe-sampler-${name} --collect --quiet -p RuntimeMaxSec=$((ARM_DEADLINE + 600)) \\
    /usr/bin/env PERSIST_PID_FILE=\$A/probe.pid PERSIST_MDBX_FILE=${dd}/${name}/mdbx.dat PERSIST_DATA_DIR=${dd} \\
    PERSIST_OUT_DIR=\$A/persist PERSIST_HOST=${name} PERSIST_INTERVAL_SECS=${iv} PERSIST_MDBX_EVERY_SECS=${me} \\
    PERSIST_CENSUS_EVERY_SECS=${ce} PERSIST_CENSUS=${RB}/bin/folio-census.py PERSIST_METRICS_URL=http://127.0.0.1:9/metrics \\
    /bin/bash ${RB}/bin/node-persist-sampler.sh || { echo "ARM_START ${name} failed sampler"; exit 1; }
systemd-run --unit=bench-probe-arm-${name} --collect --quiet -p RuntimeMaxSec=$((ARM_DEADLINE + 300)) \\
    /bin/bash "\$A/unit.sh" "\$DISK" || { systemctl stop bench-probe-sampler-${name}; echo "ARM_START ${name} failed unit"; exit 1; }
date +%s > "\$A/started"
echo "ARM_START ${name} ok disk=\$DISK unix=\$(cat "\$A/started")"
EOS
}

# script_arm_wait <name> — waits on the VM up to WAIT_CHUNK_SECS for the arm's done file, a line every
# 30 s so the session never idles: ARM_DONE (rc, timed_out, start, end), ARM_WAIT (still running) or
# ARM_LOST (no unit, no done file).
script_arm_wait() {
    local name="$1"
    cat <<EOS
# arm ${name}: wait (at most ${WAIT_CHUNK_SECS} s in this session)
A=${RB}/arms/${name}
t0=\$(date +%s); k=0
while :; do
    if [ -e "\$A/done" ]; then
        echo "ARM_DONE ${name} rc=\$(cat "\$A/rc" 2>/dev/null) timed_out=\$(cat "\$A/timed_out" 2>/dev/null || echo 0) start=\$(cat "\$A/start" 2>/dev/null) end=\$(cat "\$A/end" 2>/dev/null)"
        exit 0
    fi
    if ! systemctl is-active --quiet bench-probe-arm-${name}; then
        sleep 2; [ -e "\$A/done" ] && continue
        echo "ARM_LOST ${name}"; exit 0
    fi
    e=\$(( \$(date +%s) - t0 ))
    [ "\$e" -lt ${WAIT_CHUNK_SECS} ] || { echo "ARM_WAIT ${name} running"; exit 0; }
    k=\$((k + 1)); [ \$(( k % 6 )) -ne 0 ] || echo "ARM_WAIT ${name} elapsed=\$e"
    sleep 5
done
EOS
}

# script_arm_finish <entry> — stop a late arm and the sampler, keep the units' journal, remove the arm's
# DB, put read_ahead_kb back after an ra16 arm, tar the arm dir for the pull. The probe removes its DB when it ends
# well; a stopped, failed or --keep-db arm leaves it (up to 6 GB on disk and in the page cache, which the
# next arm would compete with), so the finish removes the probe's files by name (never a tree).
script_arm_finish() {
    local e="$1" name step dd ddr
    name="$(rec_key "${e}")"; step="$(arm_field "${e}" 2)"; dd="$(rec_data "${e}")"; ddr="$(rec_data_ref "${e}")"
    cat <<EOS
# arm ${name}: finish (stop a late arm and the sampler, remove the DB,$([ "${step}" = ra16 ] && echo ' put read_ahead_kb back,') tar for the pull)
set -u
B=${RB}
A=${RB}/arms/${name}
D=${dd}/${name}
if systemctl is-active --quiet bench-probe-arm-${name}; then systemctl stop bench-probe-arm-${name}; echo "ARM_FINISH ${name} stopped the running arm"; fi
systemctl stop bench-probe-sampler-${name} >/dev/null 2>&1 || true
mkdir -p "\$A"
journalctl -u bench-probe-sampler-${name} -u bench-probe-arm-${name} --no-pager -o short-iso > "\$A/journal.txt" 2>&1 || true
rm -f -- "\$D/mdbx.dat" "\$D/mdbx.lck" "\$D/probe-meta.txt" "${ddr}/${name}.appender.log"
rmdir -- "\$D" 2>/dev/null || true
if [ -e "\$D/mdbx.dat" ]; then echo "ARM_FINISH ${name} could not remove \$D/mdbx.dat"; fi
EOS
    if [ "${step}" = ra16 ]; then
        echo "# >>> bench-lib: bench_host_step_script read-ahead-kb <boot value>"
        bench_host_step_script "${INST}" read-ahead-kb "$(rec_boot_ra "${e}")" "${dd}"
        echo "# <<< bench-lib: bench_host_step_script"
    fi
    cat <<EOS
T=/var/tmp/bench-probe-${name}.tar.gz
tar -C "\$B/arms" -czf "\$T" ${name} || { echo "ARM_TAR ${name} failed"; exit 1; }
chmod 0644 "\$T"
echo "ARM_TAR ${name} bytes=\$(stat -c %s "\$T") sha256=\$(sha256sum "\$T" | cut -d' ' -f1)"
EOS
}

# --- run ------------------------------------------------------------------------------------------------
BOOT_RA_KB=""
BOOT_RA_KB_NV=""
# rec_boot_ra <entry> — the read_ahead_kb its device booted with (the host probe of its data dir).
rec_boot_ra() { if [ "$(rec_dev "$1")" = nvme ]; then printf '%s' "${BOOT_RA_KB_NV}"; else printf '%s' "${BOOT_RA_KB}"; fi; }

# kv <line> <key> — the value of key=<v> in a space-separated line.
kv() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p" | tail -n 1; }

# summary_field <summary.txt> <line prefix> <token> — the field after <token> on the first line that
# starts with <prefix> ("" when absent).
summary_field() {
    [ -r "$1" ] || return 0
    awk -v p="$2" -v t="$3" 'index($0, p) == 1 { for (i = 1; i < NF; i++) if ($i == t) { v = $(i + 1); break }; print v; exit }' "$1" \
        | tr -d ',;[]'
}

# i1_row <summary-i1.csv> — the probe's own per-arm summary (header and one row: every arm has its own
# results dir) as one JSON object under the probe's column names; numbers as numbers, anything else
# ("NaN", "ReadUsed") as text; {} when the file is absent. Nothing the probe did not print is invented.
i1_row() {
    [ -r "$1" ] || { echo '{}'; return 0; }
    awk -F, 'NR == 1 { for (i = 1; i <= NF; i++) h[i] = $i; n = NF } NR == 2 { for (i = 1; i <= n; i++) print h[i] "\t" $i; exit }' "$1" \
        | jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t")
            | {(.[0]): (.[1] // "" | if test("^-?[0-9]+(\\.[0-9]+)?([eE][-+]?[0-9]+)?$") then tonumber else . end)}) | add // {}' \
            2>/dev/null || echo '{}'
}

# no_prefault <arm.csv> — "<outputs> <first idx|->" from the probe's per-output CSV: the outputs that grew
# (grown_pages > 0) without a single prefault call (pg_prefault 0), which is what an env opened with
# read-ahead does to the writer (gce-arms.md §4); nothing when the file or a column is missing.
no_prefault() {
    [ -r "$1" ] || return 0
    awk -F, 'NR == 1 { for (i = 1; i <= NF; i++) c[$i] = i
                       if (!("grown_pages" in c) || !("pg_prefault" in c) || !("idx" in c)) exit
                       ok = 1; g = c["grown_pages"]; p = c["pg_prefault"]; x = c["idx"]; next }
             ok && $g > 0 && $p == 0 { n++; if (f == "") f = $x }
             END { if (ok) print n + 0, (f == "" ? "-" : f) }' "$1"
}

# The safety arm's verdict (gce-arms.md §4) against its reference arm. "Within noise" made concrete; the
# SAFETY line prints both values of every comparison, so the tolerances can be judged again.
SAFE_TOL_RATIO=0.02          # |ratio_proc_med| and |prefault_per_grown| difference
SAFE_TOL_PAST_USED=8         # beyond_used_resident_max may exceed the reference by this many pages
SAFE_MAX_READ_BYTES=65536    # the census side loop's own read_bytes, per mode (half a read-ahead window)

# safety_ref <entry> — the reference of a safety arm: the arm that runs the same probe flags without
# --keep-db (g5-7default for g9-sampler); rc 1 when the table has none.
safety_ref() {
    local f s
    f="$(arm_field "$1" 4)"; f="${f/ --keep-db/}"
    for s in "${ARMS_ALL[@]}"; do
        if [ "$(arm_field "${s}" 3)" != safety ] && [ "$(arm_field "${s}" 4)" = "${f}" ]; then printf '%s' "${s%%|*}"; return 0; fi
    done
    return 1
}

# write_stats <arm.csv> <persist.csv> <probe_end unix> — the arm's device writes as one JSON object, from
# the probe's per-output CSV over its measured outputs (warm 0) and the sampler's diskstats rows. The
# probe's fs_* columns are /proc/diskstats deltas of the device holding the data dir (the device the
# device/mdbx ratio reads): fs_wios_* completed write requests, fs_wb_* bytes, fs_flush_cycle flush
# requests; *_cycle spans the output (puts, commit, pause), *_commit the commit alone. Per output, the
# median (the probe's own: the middle of the sorted values, the upper one of an even count); p90 is the
# probe's too. diskstats gives counts and bytes, never one request's size, so the write size is bytes
# per request: its mean over the arm and the p90 of the per-output means. mdbx syncs are MDBX's own
# msync + fsync calls (pg_msync + pg_fsync). The per-output CSV has no device write time; the sampler's
# disk_wr_ticks_ms_total does, read over the rows inside the measured outputs' span (probe_end minus their
# summed cycle_ms, up to probe_end) when two rows cover at least half of it. A column, a file or a span
# that is missing gives null, never 0 (SUMMARY.txt prints n/a).
write_stats() {
    local per="" f="$1" out
    [ -r "${f}" ] || f=/dev/null
    [ -r "$2" ] && per="$(cat "$2")"
    out="$(jq -R -s -c --arg pe "$3" --arg per "${per}" '
        def num: if type == "string" and test("^-?[0-9]+(\\.[0-9]+)?([eE][-+]?[0-9]+)?$") then tonumber else null end;
        def rnd($k): if . == null then null else (. * $k | round) / $k end;
        def div($a; $b): if $a == null or $b == null or $b == 0 then null else $a / $b end;
        def table: split("\n") | map(select(length > 0) | split(","))
                   | {c: ((.[0] // []) | to_entries | map({(.value): .key}) | add // {}), rows: .[1:]};
        table as $t
        | (if $t.c.warm == null then [] else $t.rows | map(select(.[$t.c.warm] == "0")) end) as $m
        | def vals($k): if $t.c[$k] == null or ($m | length) == 0 then null
                        else ($m | map(.[$t.c[$k]] | num)) | (if any(. == null) then null else . end) end;
          def med: if . == null then null else sort | .[length / 2 | floor] end;
          def p90: if . == null or length == 0 then null else sort | .[(length - 1) * 0.9 | round] end;
          def tot: if . == null then null else add end;
          (vals("fs_wios_cycle")) as $ops | (vals("fs_wb_cycle")) as $by
        | (if vals("pg_msync") == null or vals("pg_fsync") == null then null
           else [vals("pg_msync"), vals("pg_fsync")] | transpose | map(add) end) as $sy
        | (if $ops == null or $by == null then null
           else [$by, $ops] | transpose | map(select(.[1] > 0) | .[0] / .[1] / 1024) end) as $kib
        | ($ops | tot) as $opt | ($by | tot) as $byt
        | (vals("fs_wios_commit") | tot) as $cop | (vals("fs_wb_commit") | tot) as $cby
        | (vals("commit_ms") | tot | div(.; 1000)) as $cs | (vals("cycle_ms") | tot | div(.; 1000)) as $ys
        | ($pe | num) as $we
        | ($per | table) as $s
        | (if $we == null or $ys == null or $ys <= 0 then null
           else [$s.rows[] | {t: (.[$s.c.ts_unix // -1] // "" | num), wi: (.[$s.c.disk_wr_ios_total // -1] // "" | num),
                              wt: (.[$s.c.disk_wr_ticks_ms_total // -1] // "" | num),
                              fi: (.[$s.c.disk_flush_ios_total // -1] // "" | num),
                              ft: (.[$s.c.disk_flush_ticks_ms_total // -1] // "" | num)}
                 | select(.t != null and .t >= $we - $ys and .t <= $we)] | sort_by(.t) end) as $w
        | (if $w == null or ($w | length) < 2 or (($w[-1].t - $w[0].t) < ([1, $ys / 2] | max)) then null
           else {a: $w[0], b: $w[-1]} end) as $win
        | {outputs_measured: (if $t.c.warm == null then null else ($m | length) end),
           write_ops_med: ($ops | med), write_bytes_med: ($by | med),
           write_kib_mean: (div($byt; $opt) | div(.; 1024) | rnd(10)), write_kib_p90: ($kib | p90 | rnd(10)),
           flush_ops_med: (vals("fs_flush_cycle") | med), mdbx_syncs_med: ($sy | med),
           commit_write_ops_med: (vals("fs_wios_commit") | med), commit_write_bytes_med: (vals("fs_wb_commit") | med),
           sync_ms_med: (vals("lat_sync_ms") | med),
           write_ops_total: $opt, write_bytes_total: $byt, flush_ops_total: (vals("fs_flush_cycle") | tot),
           mdbx_syncs_total: ($sy | tot), commit_write_ops_total: $cop, commit_write_bytes_total: $cby,
           commit_secs_total: ($cs | rnd(1000)), cycle_secs_total: ($ys | rnd(1000)),
           commit_iops: (div($cop; $cs) | rnd(1)), commit_mibps: (div($cby; $cs) | div(.; 1048576) | rnd(10)),
           cycle_iops: (div($opt; $ys) | rnd(1)), cycle_mibps: (div($byt; $ys) | div(.; 1048576) | rnd(10)),
           device_write_ms_per_op: (if $win == null or $win.a.wi == null or $win.b.wi == null or $win.a.wt == null or $win.b.wt == null
                                    then null else div($win.b.wt - $win.a.wt; $win.b.wi - $win.a.wi) | rnd(1000) end),
           device_flush_ms_per_op: (if $win == null or $win.a.fi == null or $win.b.fi == null or $win.a.ft == null or $win.b.ft == null
                                    then null else div($win.b.ft - $win.a.ft; $win.b.fi - $win.a.fi) | rnd(1000) end),
           sampler_window_secs: (if $win == null then null else $win.b.t - $win.a.t end)}' "${f}" 2>/dev/null)" || out='{}'
    [ -n "${out}" ] || out='{}'
    printf '%s\n' "${out}"
}

# binding <writes json> <device> — the binding constraint on the record's device: the commit window's
# write requests per second against the provisioned IOPS and its MiB/s against the provisioned
# throughput (the commit is when the writes are issued and what the writer waits on; a rate held at a
# cap reads near 100 %). binds names the larger share; null for a device with no provisioned cap (the
# local SSD) or without the rates.
binding() {
    local ic="" tc=""
    if [ "$2" = hyperdisk ]; then ic="${NODE_DISK_IOPS:-}"; tc="${NODE_DISK_THROUGHPUT:-}"; fi
    printf '%s' "$1" | jq -c --arg dev "$2" --arg ic "${ic}" --arg tc "${tc}" '
        def n: if . == "" then null else (tonumber? // null) end;
        def pct($r; $c): if $r == null or $c == null or $c == 0 then null else ($r / $c * 100 | round) end;
        {device: $dev, iops_cap: ($ic | n), mibps_cap: ($tc | n), commit_iops, commit_mibps, cycle_iops, cycle_mibps}
        | .iops_pct = pct(.commit_iops; .iops_cap) | .mibps_pct = pct(.commit_mibps; .mibps_cap)
        | .binds = (if .iops_pct == null or .mibps_pct == null then null
                    elif .iops_pct >= .mibps_pct then "iops" else "throughput" end)' 2>/dev/null || echo 'null'
}

# write_status <key> <result> — arms/<key>.status.json from what the record left locally; for an arm with
# sampler cadence safety, also its verdict against the reference arm's status file on the same device
# (when that ran).
write_status() {
    local name="$1" result="$2" e step cad flags d s st en rc to amp cw pr pu cm q l np ref rk base rn dev arm ws
    e="$(rec_by_key "${name}")"; rn="$(rec_name "${e}")"; dev="$(rec_dev "${e}")"; arm="$(rec_arm "${e}")"
    step="$(arm_field "${e}" 2)"; cad="$(arm_field "${e}" 3)"; flags="$(arm_field "${e}" 4)"
    d="${PD}/arms/${name}"
    s="${d}/results/${name}.summary.txt"
    st="$(cat "${d}/start" 2>/dev/null)"; en="$(cat "${d}/end" 2>/dev/null)"
    rc="$(cat "${d}/rc" 2>/dev/null)"; to="$(cat "${d}/timed_out" 2>/dev/null)"
    amp="$(summary_field "${s}" "ratios:" "device/mdbx-dirtied")"
    pr="$(summary_field "${s}" "ratios:" "process-dirtied/mdbx-dirtied")"
    cw="$(awk 'index($0, "per-commit device/mdbx-dirtied:") == 1 { for (i = 1; i < NF; i++) if ($i == "median") { print $(i + 1); exit } }' "${s}" 2>/dev/null)"
    pu="$(sed -n 's/.*resident past used: end \([0-9][0-9]*\) pages.*/\1/p' "${s}" 2>/dev/null | head -n 1)"
    cm="$(summary_field "${s}" "commit ms:" "median")"
    q="$(grep '^CENSUS_SAFETY' "${d}/census-safety.txt" 2>/dev/null)" || q=""
    l="$(grep -h "^HOST_STEP ${INST} " "${PD}/sessions/arm-${name}-start.out" "${PD}/sessions/arm-${name}-finish.out" 2>/dev/null)" || l=""
    np="$(no_prefault "${d}/results/${name}.csv")" || np=""
    ws="$(write_stats "${d}/results/${name}.csv" "${d}/persist/${name}.persist.csv" "$(cat "${d}/probe_end" 2>/dev/null)")" || ws='{}'
    base="$(jq -n -c --arg name "${rn}" --arg group "${arm%%-*}" --arg step "${step}" --arg cad "${cad}" --arg flags "${flags}" \
        --arg cmd "$(cat "${d}/cmd.txt" 2>/dev/null)" --arg result "${result}" --arg st "${st}" --arg en "${en}" \
        --arg rc "${rc}" --arg to "${to:-0}" --arg amp "${amp}" --arg cw "${cw}" --arg pr "${pr}" --arg pu "${pu}" \
        --arg cm "${cm}" --arg q "${q}" --argjson hs "$(printf '%s\n' "${l}" | bench_host_step_record "${INST}")" \
        --argjson i1 "$(i1_row "${d}/results/summary-i1.csv")" --arg np "${np}" --arg arm "${arm}" --arg dev "${dev}" \
        --argjson ws "${ws}" --argjson bind "$(binding "${ws}" "${dev}")" '
        def n: if . == "" then null else (tonumber? // null) end;
        def iso: if . == null then null else todate end;
        {name: $name, group: $group, host_step: (if $step == "-" then null else $step end), sampler_cadence: $cad,
         probe_flags: $flags, command: (if $cmd == "" then null else $cmd end), result: $result,
         start_unix: ($st | n), end_unix: ($en | n), start_utc: ($st | n | iso), end_utc: ($en | n | iso),
         exit_code: ($rc | n), timed_out: ($to == "1"), host_steps: $hs,
         device_per_mdbx: ($amp | n), commit_window_device_per_mdbx: ($cw | n), process_per_mdbx: ($pr | n),
         resident_past_used_end_pages: ($pu | n), commit_ms_median: ($cm | n),
         outputs_grown_without_prefault: (if $np == "" then null else ($np | split(" ")[0] | n) end),
         first_output_grown_without_prefault: (if $np == "" then null else ($np | split(" ")[1] | n) end),
         i1: $i1, census_safety: ($q | split("\n") | map(select(length > 0))),
         arm: $arm, device: $dev, writes: $ws, binding: $bind}')" || return 1
    if [ "${cad}" = safety ]; then
        # The reference arm on the same device: its record's key and name.
        ref="$(safety_ref "${e}")" || ref=""
        rk="${ref}"; [ -z "${ref}" ] || [ "${DISKS}" != both ] || rk="${ref}_${dev}"
        [ -z "${rk}" ] || ref="$(rec_name "$(rec_by_key "${rk}")")"
        base="$(printf '%s' "${base}" | jq -c --arg ref "${ref}" --argjson tr "${SAFE_TOL_RATIO}" \
            --argjson tp "${SAFE_TOL_PAST_USED}" --argjson mb "${SAFE_MAX_READ_BYTES}" \
            --slurpfile r <(cat "${PD}/arms/${rk:-none}.status.json" 2>/dev/null || echo null) '
            def num: if type == "number" then . else null end;
            (.i1) as $me | (($r[0] // {}) | .i1 // {}) as $ri
            | ([.census_safety[] | select(startswith("CENSUS_SAFETY_IO ")) | split(" ")
                | {(.[1]): (.[2:] | map(split("=") | {(.[0]): (.[1] | tonumber? // null)}) | add)}] | add // {}) as $io
            | def near($a; $b; $t): if ($a | num) == null or ($b | num) == null then null
                                     else (($a - $b) | if . < 0 then -. else . end) <= $t end;
            {reference: (if $ref == "" then null else $ref end), reference_ran: ($r[0] != null),
             ratio_proc_med: [$me.ratio_proc_med, $ri.ratio_proc_med],
             prefault_per_grown: [$me.prefault_per_grown, $ri.prefault_per_grown],
             beyond_used_resident_max: [$me.beyond_used_resident_max, $ri.beyond_used_resident_max],
             read_bytes: {live: $io.live.read_bytes, quiet: $io.quiet.read_bytes},
             quiet_unchanged: $io.quiet.unchanged, quiet_runs: $io.quiet.runs,
             outputs_grown_without_prefault: .outputs_grown_without_prefault,
             tolerances: {ratio: $tr, past_used_pages: $tp, read_bytes: $mb},
             quiet_steady: $io.quiet.steady,
             reader: ([.census_safety[] | select(startswith("CENSUS_SAFETY_IO quiet ")) | capture(" reader=(?<r>[a-z]+)") | .r][0] // null)} as $s
            | ($s | {ratio_proc_med: near(.ratio_proc_med[0]; .ratio_proc_med[1]; $tr),
                     prefault_per_grown: near(.prefault_per_grown[0]; .prefault_per_grown[1]; $tr),
                     beyond_used_resident_max: (if (.beyond_used_resident_max[0] | num) == null or (.beyond_used_resident_max[1] | num) == null
                                                then null else .beyond_used_resident_max[0] <= .beyond_used_resident_max[1] + $tp end),
                     read_bytes: (if (.read_bytes.live | num) == null or (.read_bytes.quiet | num) == null
                                  then null else (.read_bytes.live <= $mb and .read_bytes.quiet <= $mb) end),
                     quiet_unchanged: (if .quiet_runs == null then null else (.quiet_runs == 5 and .quiet_unchanged == 5) end),
                     prefault_never_dropped: (if (.outputs_grown_without_prefault | num) == null then null
                                              else .outputs_grown_without_prefault == 0 end),
                     reader_steady: (if (.quiet_runs | num) == null or (.quiet_steady | num) == null then null
                                     else (.quiet_runs == 5 and .quiet_steady == 4) end)}) as $c
            | .safety = ($s + {checks: $c,
                 pass: (if ([$c[]] | any(. == false)) then false elif ([$c[]] | any(. == null)) then null else true end)})')" \
            || return 1
    fi
    printf '%s\n' "${base}" | jq . > "${PD}/arms/${name}.status.json"
}

# finish_and_pull <entry> — the record's finish session, then its tarball pulled, checked against the sha256
# the finish printed, and unpacked into arms/; rc 0 when arms/<name>/ came over whole.
finish_and_pull() {
    local e="$1" name out tgz line sha got
    name="$(arm_field "${e}" 1)"
    out="${PD}/sessions/arm-${name}-finish.out"
    tgz="${PD}/arms/${name}.tar.gz"
    remote "arm-${name}-finish" 300 "${out}" script_arm_finish "${e}"
    pull "/var/tmp/bench-probe-${name}.tar.gz" "${tgz}"
    [ "${DRY}" = "0" ] || return 0
    line="$(grep "^ARM_TAR ${name} " "${out}" | tail -n 1)"
    sha="$(kv "${line}" sha256)"
    got=""; [ -s "${tgz}" ] && got="$(sha256_file "${tgz}")"
    if [ -n "${sha}" ] && [ "${got}" = "${sha}" ] && tar -xzf "${tgz}" -C "${PD}/arms"; then
        rm -f "${tgz}"
        return 0
    fi
    mkdir -p "${PD}/arms/${name}"
    return 1
}

# run_arm <entry> <run deadline unix> — one record (an arm on one device); never stops the loop. rc 0 =
# done with rc 0 and pulled.
run_arm() {
    local e="$1" dl="$2" name out line result="" t0
    name="$(arm_field "${e}" 1)"
    out="${PD}/sessions/arm-${name}"
    echo "== arm ${name}: $(arm_field "${e}" 4)" >&3
    if [ "${DRY}" = "0" ] && [ $(( $(now) + ARM_DEADLINE + 240 )) -gt "${dl}" ]; then
        log "arm ${name}: skipped, the run deadline is too close"
        mkdir -p "${PD}/arms/${name}"; write_status "${name}" "skipped: run deadline"
        return 1
    fi
    if [ "$(arm_field "${e}" 2)" = ra16 ] && [ "${DRY}" = "0" ] && [ -z "$(rec_boot_ra "${e}")" ]; then
        log "arm ${name}: skipped, the host probe gave no read_ahead_kb to restore"
        mkdir -p "${PD}/arms/${name}"; write_status "${name}" "skipped: no boot read_ahead_kb"
        return 1
    fi
    remote "arm-${name}-start" 180 "${out}-start.out" script_arm_start "${e}"
    if [ "${DRY}" = "0" ]; then
        line="$(grep "^ARM_START ${name} " "${out}-start.out" | tail -n 1)"
        case "${line}" in
            "ARM_START ${name} ok"*|"ARM_START ${name} already") log "arm ${name}: started (${line#ARM_START "${name}" })" ;;
            # No line at all: the session failed, maybe after the unit started. The wait finds out (a unit
            # that never started reads ARM_LOST at once).
            "") log "arm ${name}: the start session printed no ARM_START line; asking the VM" ;;
            *) result="start failed: ${line}" ;;
        esac
    fi
    t0="$(now)"
    while [ -z "${result}" ]; do
        remote "arm-${name}-wait" $((WAIT_CHUNK_SECS + 120)) "${out}-wait.out" script_arm_wait "${name}"
        [ "${DRY}" = "0" ] || break
        line="$(grep -E "^ARM_(DONE|LOST|WAIT) ${name}" "${out}-wait.out" | tail -n 1)"
        case "${line}" in
            "ARM_DONE "*) result="done"; log "arm ${name}: ${line#ARM_DONE "${name}" }" ;;
            "ARM_LOST "*) result="lost: the unit ended without a done file" ;;
            "") sleep 10 ;;   # the session failed (IAP): back off before the next one
        esac
        if [ -z "${result}" ] && [ $(( $(now) - t0 )) -ge $(( ARM_DEADLINE + 300 )) ]; then result="wait deadline"; fi
    done
    finish_and_pull "${e}" || result="${result:-?}; pull failed"
    [ "${DRY}" = "0" ] || return 0
    write_status "${name}" "${result}"
    log "arm ${name}: ${result}, rc $(jq -r '.exit_code // "-"' "${PD}/arms/${name}.status.json"), device/mdbx $(jq -r '.device_per_mdbx // "-"' "${PD}/arms/${name}.status.json")"
    [ "${result}" = "done" ] && [ "$(jq -r '.exit_code' "${PD}/arms/${name}.status.json")" = 0 ]
}

# make_bundle <dir> — the files the VM gets, and their SHA256SUMS, in <dir>; prints the tarball path.
make_bundle() {
    local d="$1" f
    cp "${BIN}" "${d}/mdbx-writeback-probe" && cp "${PROBE_DIR}/tools/folio-census.py" "${d}/folio-census.py" \
        && cp "${PROBE_DIR}/node-persist-sampler.sh" "${d}/node-persist-sampler.sh" || return 1
    : > "${d}/SHA256SUMS"
    for f in mdbx-writeback-probe folio-census.py node-persist-sampler.sh; do
        printf '%s  %s\n' "$(sha256_file "${d}/${f}")" "${f}" >> "${d}/SHA256SUMS" || return 1
    done
    tar -C "${d}" -czf "${d}.tar.gz" mdbx-writeback-probe folio-census.py node-persist-sampler.sh SHA256SUMS || return 1
    printf '%s\n' "${d}.tar.gz"
}

check_bin() {
    local info want got
    [ -n "${BIN}" ] || { echo "❌ --bin <probe binary> is required (benchmark/tools/build-probe-bin.sh builds it)" >&2; return 1; }
    [ -f "${BIN}" ] && [ -x "${BIN}" ] || { echo "❌ ${BIN} is not an executable file" >&2; return 1; }
    info="$(dirname "${BIN}")/build-info.txt"
    [ -r "${info}" ] || { echo "❌ ${info} is missing: build the binary with tools/build-probe-bin.sh" >&2; return 1; }
    want="$(sed -n 's/^binary_sha256=//p' "${info}" | tail -n 1)"
    got="$(sha256_file "${BIN}")"
    [ -n "${want}" ] && [ "${want}" = "${got}" ] || { echo "❌ ${BIN} sha256 ${got} is not build-info's ${want:-?}" >&2; return 1; }
}

cmd_run() {
    local dl="$1" work bundle e fails=0 ok=0 n=0 out r
    echo "== run: ${#RECS[@]} arm(s)$([ "${DISKS}" = both ] && echo " (${#ARMS[@]} on each of hyperdisk and nvme)"), each under a ${ARM_DEADLINE}-s watchdog; the run ends by $([ "${DRY}" = 1 ] && echo "start + ${DEADLINE_MIN} min" || bench_iso_from_unix "${dl}")" >&3
    if [ "${DRY}" = "0" ]; then
        check_bin || return 1
        mkdir -p "${PD}/sessions" "${PD}/scripts" "${PD}/arms" || return 1
        cp "$(dirname "${BIN}")/build-info.txt" "${PD}/build-info.txt" || return 1
        work="$(mktemp -d "${TMPDIR:-/tmp}/bench-probe.XXXXXX")" || return 1
        mkdir "${work}/bundle" || return 1
        bundle="$(make_bundle "${work}/bundle")" || { echo "❌ cannot build the bundle" >&2; return 1; }
        cp "${work}/bundle/SHA256SUMS" "${PD}/bundle-SHA256SUMS"
    else
        bundle="<bundle: ${BIN:-<--bin>}, tools/folio-census.py, node-persist-sampler.sh, SHA256SUMS>.tar.gz"
    fi
    echo "-- upload the bundle and settle the VM" >&3
    r=0
    upload "${bundle}" "${RBUNDLE}" || r=$?
    [ "${DRY}" = "0" ] && [ -n "${work:-}" ] && rm -f "${bundle}" "${work}"/bundle/* && rmdir "${work}/bundle" "${work}"
    [ "${r}" -eq 0 ] || { echo "❌ the bundle upload failed (rc ${r}); see ${REL_PD}/sessions/upload.out" >&2; return 1; }
    remote setup 900 "${PD}/sessions/setup.out" script_setup
    if [ "${DRY}" = "0" ] && ! grep -q '^SETUP_OK' "${PD}/sessions/setup.out"; then
        echo "❌ setup failed: $(grep '^SETUP_FAIL' "${PD}/sessions/setup.out" | tail -n 1)" >&2
        return 1
    fi
    if [ "${DRY}" = "0" ]; then
        # Which reader gave resident pages (fincore or the census), and the local SSD as setup made it.
        r="$(kv "$(grep '^SETUP_OK' "${PD}/sessions/setup.out" | tail -n 1)" resident_reader)" || r=""
        state_set resident_reader "${r}"
        log "setup: resident pages from ${r:-?}$([ "${r}" = census ] && echo ' (no fincore on the image: the census tool'"'"'s --resident-only)')"
        if [ "${DISKS}" = both ]; then
            r="$(grep '^SETUP_NVME ' "${PD}/sessions/setup.out" | tail -n 1)" || r=""
            [ -n "${r}" ] || { echo "❌ setup printed no SETUP_NVME line: no local SSD to run on" >&2; return 1; }
            state_set nvme_setup "${r#SETUP_NVME }"
            log "setup: local SSD ${r#SETUP_NVME }"
        fi
    fi
    echo "-- host probe (bench_host_probe_script)" >&3
    remote host-probe 120 "${PD}/sessions/host-probe.out" script_host_probe
    if [ "${DRY}" = "0" ]; then
        bench_host_probe_record "${INST}" < "${PD}/sessions/host-probe.out" > "${PD}/host-probe.json"
        BOOT_RA_KB="$(jq -r '.read_ahead_kb // empty' "${PD}/host-probe.json" 2>/dev/null)" || BOOT_RA_KB=""
        case "${BOOT_RA_KB}" in *[!0-9]*) BOOT_RA_KB="" ;; esac
        # The boot value is the first run's reading on this VM (up clears it): a later run's host probe
        # could read a value an interrupted ra16 arm left behind.
        r="$(state_get boot_read_ahead_kb)" || r=""
        case "${r}" in
            ''|*[!0-9]*) [ -z "${BOOT_RA_KB}" ] || state_set boot_read_ahead_kb "${BOOT_RA_KB}" ;;
            *) [ "${r}" = "${BOOT_RA_KB}" ] || log "host probe: read_ahead_kb ${BOOT_RA_KB:-?} now; the arms use ${r}, this VM's first reading"
               BOOT_RA_KB="${r}" ;;
        esac
        log "host probe: kernel $(jq -r '.kernel // "-"' "${PD}/host-probe.json"), read_ahead_kb ${BOOT_RA_KB:-?}, disk $(jq -r '.disk // "-"' "${PD}/host-probe.json")"
    else
        # The plan renders the restore with 128 in place of the host probe's read_ahead_kb.
        BOOT_RA_KB=128
    fi
    if [ "${DISKS}" = both ]; then
        echo "-- host probe of the local SSD (bench_host_probe_script, ${RNV}/data)" >&3
        remote host-probe-nvme 120 "${PD}/sessions/host-probe-nvme.out" script_host_probe_nvme
        if [ "${DRY}" = "0" ]; then
            bench_host_probe_record "${INST}" < "${PD}/sessions/host-probe-nvme.out" > "${PD}/host-probe-nvme.json"
            BOOT_RA_KB_NV="$(jq -r '.read_ahead_kb // empty' "${PD}/host-probe-nvme.json" 2>/dev/null)" || BOOT_RA_KB_NV=""
            case "${BOOT_RA_KB_NV}" in *[!0-9]*) BOOT_RA_KB_NV="" ;; esac
            r="$(state_get boot_read_ahead_kb_nvme)" || r=""
            case "${r}" in
                ''|*[!0-9]*) [ -z "${BOOT_RA_KB_NV}" ] || state_set boot_read_ahead_kb_nvme "${BOOT_RA_KB_NV}" ;;
                *) BOOT_RA_KB_NV="${r}" ;;
            esac
            log "host probe (nvme): read_ahead_kb ${BOOT_RA_KB_NV:-?}, disk $(jq -r '.disk // "-"' "${PD}/host-probe-nvme.json"), mount $(jq -r '.datadir_mount_options // "-"' "${PD}/host-probe-nvme.json")"
        else
            BOOT_RA_KB_NV=128
        fi
    fi
    for e in ${RECS[@]+"${RECS[@]}"}; do
        n=$((n + 1))
        if run_arm "${e}" "${dl}"; then ok=$((ok + 1)); else fails=$((fails + 1)); fi
    done
    [ "${DRY}" = "0" ] || return 0
    out="$(printf 'RUN_SUMMARY arms=%s ok=%s failed=%s' "${n}" "${ok}" "${fails}")"
    log "${out}"
    [ "${fails}" -eq 0 ]
}

# --- collect --------------------------------------------------------------------------------------------
# summary_lines — SUMMARY.txt: a PROBE_RUN line (the device mode, the shape, which reader gave resident
# pages, the local SSD as setup made it), then in the table's run order one PROBE_ARM line per record with
# a status file (its device writes appended to the bytes ratio and commit time), its BIND line (the
# binding constraint on its device), the safety arm's census totals and its SAFETY verdict; with
# --disks both a PAIR line after each arm's nvme record sets the two devices side by side. A value a
# source lacks reads n/a in the columns this added, "-" in the older ones.
summary_lines() {
    local e f key arm h
    jq -r -n --arg d "${DISKS}" --arg mt "${MACHINE_TYPE}" --arg rr "$(state_get resident_reader)" --arg nv "$(state_get nvme_setup)" '
        "PROBE_RUN disks=\($d) machine_type=\($mt) resident_reader=\(if $rr == "" then "n/a" else $rr end)"
        + (if $nv == "" then "" else " nvme: \($nv)" end)'
    for e in "${ALL_RECS[@]}"; do
        key="${e%%|*}"
        f="${PD}/arms/${key}.status.json"
        [ -r "${f}" ] || continue
        jq -r 'def na: if . == null then "n/a" else . end;
               def mib: if . == null then "n/a" else ((. / 1048576 * 10 | round) / 10) end;
               "PROBE_ARM \(.name) result=\(.result | gsub(" "; "_")) rc=\(.exit_code // "-") device/mdbx=\(.device_per_mdbx // "-")"
               + " commit/mdbx=\(.commit_window_device_per_mdbx // "-") process/mdbx=\(.process_per_mdbx // "-")"
               + " past_used_end=\(.resident_past_used_end_pages // "-") commit_ms=\(.commit_ms_median // "-")"
               + " prefault/grown=\(.i1.prefault_per_grown // "-") past_used_max=\(.i1.beyond_used_resident_max // "-")"
               + " no_prefault_outputs=\(.outputs_grown_without_prefault // "-")"
               + " outputs=\(.writes.outputs_measured | na) wr_ops/out=\(.writes.write_ops_med | na)"
               + " wr_kib_mean=\(.writes.write_kib_mean | na) wr_kib_p90=\(.writes.write_kib_p90 | na)"
               + " flushes/out=\(.writes.flush_ops_med | na) syncs/out=\(.writes.mdbx_syncs_med | na)"
               + " commit_wr_ops/out=\(.writes.commit_write_ops_med | na) sync_ms=\(.writes.sync_ms_med | na)"
               + " dev_ms/wr=\(.writes.device_write_ms_per_op | na) dev_ms/flush=\(.writes.device_flush_ms_per_op | na)"
               + " wr_ops=\(.writes.write_ops_total | na) wr_mib=\(.writes.write_bytes_total | mib)"
               + " flushes=\(.writes.flush_ops_total | na) syncs=\(.writes.mdbx_syncs_total | na)"' "${f}"
        jq -r 'def na: if . == null then "n/a" else . end;
               def pc: if . == null then "n/a" else "\(.)%" end;
               (.binding // {}) as $b
               | "BIND \(.name) device=\(.device // "hyperdisk") commit_iops=\($b.commit_iops | na)/\($b.iops_cap | na) (\($b.iops_pct | pc))"
               + " commit_mibps=\($b.commit_mibps | na)/\($b.mibps_cap | na) (\($b.mibps_pct | pc))"
               + " cycle_iops=\($b.cycle_iops | na) cycle_mibps=\($b.cycle_mibps | na) -> "
               + (if $b.binds != null then $b.binds
                  elif $b.commit_iops == null or $b.commit_mibps == null then "n/a (no commit-window rates)"
                  else "n/a (no provisioned cap)" end)' "${f}"
        jq -r '.census_safety[]' "${f}" | grep '^CENSUS_SAFETY_IO' | sed "s/^/  $(jq -r '.name' "${f}") /"
        jq -r 'select(.safety != null) | .safety as $s | ($s.checks | to_entries) as $c
            | def pair(k): "\($s[k][0] // "-")/\($s[k][1] // "-")";
            "SAFETY \(.name) ref=\($s.reference // "none") ratio_proc_med=\(pair("ratio_proc_med"))"
            + " prefault_per_grown=\(pair("prefault_per_grown")) past_used_max=\(pair("beyond_used_resident_max"))"
            + " read_bytes_live=\($s.read_bytes.live // "-") read_bytes_quiet=\($s.read_bytes.quiet // "-")"
            + " quiet_unchanged=\($s.quiet_unchanged // "-")/\($s.quiet_runs // "-")"
            + " no_prefault_outputs=\($s.outputs_grown_without_prefault // "-")"
            + " reader=\($s.reader // "n/a") quiet_steady=\($s.quiet_steady // "n/a")/\(if $s.quiet_runs == null then "n/a" else $s.quiet_runs - 1 end) -> "
            + (if $s.pass == true then "PASS"
               elif $s.pass == false then "FAIL (\([$c[] | select(.value == false) | .key] | join(",")))"
               else "INCOMPLETE (not measured: \([$c[] | select(.value == null) | .key] | join(",")))" end)' "${f}"
        [ "${DISKS}" = both ] && [ "$(rec_dev "${e}")" = nvme ] || continue
        arm="$(rec_arm "${e}")"
        h="${PD}/arms/${arm}_hyperdisk.status.json"
        [ -r "${h}" ] || continue
        jq -r -n --arg arm "${arm}" --slurpfile h "${h}" --slurpfile v "${f}" '
            def na: if . == null then "n/a" else . end;
            def both(f): "\($h[0] | f | na)/\($v[0] | f | na)";
            "PAIR \($arm) hyperdisk/nvme device/mdbx=\(both(.device_per_mdbx)) wr_ops/out=\(both(.writes.write_ops_med))"
            + " wr_kib_mean=\(both(.writes.write_kib_mean)) commit_ms=\(both(.commit_ms_median)) sync_ms=\(both(.writes.sync_ms_med))"
            + " commit_iops=\(both(.writes.commit_iops)) binds=\(both(.binding.binds))"'
    done
}

cmd_collect() {
    local e name zone_now info
    echo "== collect: ${REL_PD}/ (manifest.json, SUMMARY.txt, arms/), then the run's INDEX.md" >&3
    # An arm whose run reached the pull and lost it gets one more finish and pull (a skipped arm never ran).
    for e in ${RECS[@]+"${RECS[@]}"}; do
        name="$(arm_field "${e}" 1)"
        [ "${DRY}" = "0" ] || continue
        jq -e '.result | endswith("; pull failed")' "${PD}/arms/${name}.status.json" >/dev/null 2>&1 || continue
        log "collect: ${name} was not pulled; trying again"
        if finish_and_pull "${e}"; then
            write_status "${name}" "$(jq -r '.result | sub("; pull failed$"; "")' "${PD}/arms/${name}.status.json")"
        fi
    done
    if [ "${DRY}" = 1 ]; then
        echo "  (dry run) would write ${REL_PD}/manifest.json and SUMMARY.txt, then INDEX.md and CHECKSUMS.sha256 of the run" >&3
        return 0
    fi
    mkdir -p "${PD}" || return 1
    # A safety verdict reads its reference arm's status: write it again now that every arm that ran has one.
    for e in "${ALL_RECS[@]}"; do
        [ "$(arm_field "${e}" 3)" = safety ] || continue
        name="${e%%|*}"
        [ ! -r "${PD}/arms/${name}.status.json" ] || write_status "${name}" "$(jq -r '.result' "${PD}/arms/${name}.status.json")"
    done
    zone_now="$(state_get zone)"
    info="${PD}/build-info.txt"
    jq -n --arg run "${BENCH_RUN_ID}" --arg inst "${INST}" --arg zone "${zone_now:-${ZONE}}" --arg mt "${MACHINE_TYPE}" \
        --arg dt "${NODE_DISK_TYPE}" --arg ds "${NODE_DISK_SIZE}" --arg di "${NODE_DISK_IOPS:-}" --arg dp "${NODE_DISK_THROUGHPUT:-}" \
        --arg image "${IMAGE}" --arg labels "${LABELS}" --arg created "$(state_get created_unix)" \
        --arg deleted "$(state_get deleted_unix)" --arg ad "${ARM_DEADLINE}" --arg rd "${DEADLINE_MIN}" \
        --slurpfile img <(cat "${PD}/image.json" 2>/dev/null || echo null) \
        --slurpfile host <(cat "${PD}/host-probe.json" 2>/dev/null || echo null) \
        --arg info "$(cat "${info}" 2>/dev/null)" --arg sums "$(cat "${PD}/bundle-SHA256SUMS" 2>/dev/null)" \
        --slurpfile arms <(cat "${PD}"/arms/*.status.json 2>/dev/null) \
        --arg disks "${DISKS}" --arg maint "${MAINT}" --arg rr "$(state_get resident_reader)" --arg nv "$(state_get nvme_setup)" \
        --arg mkfs "${NVME_MKFS}" --slurpfile hostnv <(cat "${PD}/host-probe-nvme.json" 2>/dev/null || echo null) '
        def n: if . == "" then null else (tonumber? // null) end;
        def kvs: split("\n") | map(select(test("^[a-z0-9_]+=")) | capture("^(?<k>[a-z0-9_]+)=(?<v>.*)$")) | map({(.k): .v}) | add // {};
        {schema: "bench-probe/v1", run_id: $run,
         vm: {instance: $inst, disk: $inst, zone: $zone, machine_type: $mt, disk_type: $dt, disk_size_gb: ($ds | n),
              disk_provisioned_iops: ($di | n), disk_provisioned_throughput_mibps: ($dp | n), boot_image: $image,
              boot_image_record: ($img[0] | if . == null then null else {name, status, archiveSizeBytes, creationTimestamp,
                                   deprecated: (.deprecated.state // "ACTIVE"), family, licenses} end),
              labels: $labels, created_unix: ($created | n), deleted_unix: ($deleted | n), maintenance_policy: $maint},
         deadlines: {arm_secs: ($ad | n), run_min: ($rd | n)},
         binary: ($info | kvs), bundle_sha256: ($sums | split("\n") | map(select(length > 0) | split("  ") | {(.[1]): .[0]}) | add // {}),
         host_probe: $host[0], arms: $arms,
         disks: $disks, resident_reader: (if $rr == "" then null else $rr end),
         local_ssd: (if $disks != "both" then null
                     else {machine_type: $mt, mkfs_options: $mkfs}
                          + ($nv | split(" ") | map(capture("^(?<k>[a-z_]+)=(?<v>.*)$")) | map({(.k): .v}) | add // {}) end),
         host_probe_nvme: $hostnv[0]}' > "${PD}/manifest.json.tmp" && mv -f "${PD}/manifest.json.tmp" "${PD}/manifest.json" \
        || { echo "❌ could not write ${PD}/manifest.json" >&2; return 1; }
    summary_lines > "${PD}/SUMMARY.txt"
    cat "${PD}/SUMMARY.txt" >&3
    BENCH_APPLY=1 bench_local_index || bench_warn "the run's INDEX.md/CHECKSUMS.sha256 could not be written"
}

# --- down -----------------------------------------------------------------------------------------------
# gone_within <instances|disks> <name> <secs> — poll (every 15 s) until the name is not listed.
gone_within() {
    local start json
    start="$(now)"
    while :; do
        if json="$(find_named "$1" "$2")"; then
            [ -n "${json}" ] || return 0
        fi
        [ $(( $(now) - start )) -lt "$3" ] || return 1
        sleep 15
    done
}

delete_instance() {
    local json out rc=0
    if json="$(find_named instances "${INST}")"; then :; else echo "❌ cannot list instances" >&2; return 1; fi
    if [ "${DRY}" = "0" ] && [ -z "${json}" ]; then log "instance ${INST}: not there"; return 0; fi
    if [ "${DRY}" = "0" ] && ! ours "${json}"; then
        echo "❌ instance ${INST} does not carry benchmark=1, bench-run=${BENCH_RUN_ID}, tn-role=probe: NOT deleting it" >&2
        return 1
    fi
    [ "${DRY}" = "0" ] && ZONE="$(printf '%s' "${json}" | jq -r '.zone | split("/") | last')"
    out="$(gc "${DELETE_SECS}" compute instances delete "${INST}" --zone="${ZONE}" --project="${PROJECT_ID}" --quiet 2>&1)" || rc=$?
    [ "${DRY}" = "0" ] || return 0
    printf '%s\n' "${out}" > "${PD}/sessions/delete-instance.out"
    [ "${rc}" -eq 0 ] || bench_warn "instances delete ${INST}: rc ${rc} (verifying anyway): ${out}"
    gone_within instances "${INST}" "${DELETE_SECS}" && log "instance ${INST}: deleted"
}

# attached <disk json> — rc 0 when the disk lists a user (an instance it is attached to).
attached() { [ "$(printf '%s' "$1" | jq '.users // [] | length' 2>/dev/null)" != 0 ]; }

# delete_disk [after-instance] — the disk, when it is this run's and attached to nothing. Right after
# down deleted the instance (after-instance), its boot disk (auto-delete=yes) may still be listed,
# attached: then it waits (15-s polls, DELETE_SECS) for the disk to go with the instance or come free.
# Otherwise an attached disk is refused at once.
delete_disk() {
    local settle="${1:-}" json dz out rc=0 start
    if json="$(find_named disks "${DISK}")"; then :; else echo "❌ cannot list disks" >&2; return 1; fi
    if [ "${DRY}" = "0" ] && [ -z "${json}" ]; then log "disk ${DISK}: not there"; return 0; fi
    if [ "${DRY}" = "0" ] && ! ours "${json}"; then
        echo "❌ disk ${DISK} does not carry benchmark=1, bench-run=${BENCH_RUN_ID}, tn-role=probe: NOT deleting it" >&2
        return 1
    fi
    start="$(now)"
    while [ "${DRY}" = "0" ] && attached "${json}"; do
        if [ "${settle}" != after-instance ] || [ $(( $(now) - start )) -ge "${DELETE_SECS}" ]; then
            echo "❌ disk ${DISK} is attached: NOT deleting it" >&2
            return 1
        fi
        sleep 15
        if json="$(find_named disks "${DISK}")"; then :; else echo "❌ cannot list disks" >&2; return 1; fi
        if [ -z "${json}" ]; then log "disk ${DISK}: deleted with the instance"; return 0; fi
        ours "${json}" || { echo "❌ disk ${DISK} lost this run's probe labels: NOT deleting it" >&2; return 1; }
    done
    dz="${ZONE}"
    [ "${DRY}" = "0" ] && dz="$(printf '%s' "${json}" | jq -r '.zone | split("/") | last')"
    out="$(gc "${DELETE_SECS}" compute disks delete "${DISK}" --zone="${dz}" --project="${PROJECT_ID}" --quiet 2>&1)" || rc=$?
    [ "${DRY}" = "0" ] || return 0
    printf '%s\n' "${out}" > "${PD}/sessions/delete-disk.out"
    [ "${rc}" -eq 0 ] || bench_warn "disks delete ${DISK}: rc ${rc} (verifying anyway): ${out}"
    gone_within disks "${DISK}" "${DELETE_SECS}" && log "disk ${DISK}: deleted"
}

# cmd_down — DOWN_DONE turns 1 only once a down has run to its end, so a down cut short by a signal is
# run again by on_exit (every step of it is safe to repeat).
DOWN_DONE=0
cmd_down() {
    local r=0
    down_once || r=$?
    DOWN_DONE=1
    return "${r}"
}

down_once() {
    local left=""
    echo "== down: delete ${INST} and its disk (labels checked first), then verify both are gone (${DELETE_SECS} s each)" >&3
    if [ "${KEEP}" = 1 ]; then
        echo "--keep: nothing is deleted. Delete later with:" >&3
        echo "  BENCH_RUN_ID=${BENCH_RUN_ID} benchmark/benchmark-probe.sh down" >&3
        return 0
    fi
    [ "${DRY}" = 1 ] || mkdir -p "${PD}/sessions"
    if delete_instance; then
        delete_disk after-instance || left="${left} disk"
    else
        left="${left} instance"
        delete_disk || left="${left} disk"
    fi
    [ "${DRY}" = "0" ] || return 0
    if [ -z "${left}" ]; then
        state_set deleted_unix "$(now)"
        # After a collect: stamp the deletion into the manifest, then index again (CHECKSUMS.sha256 covers
        # the manifest and the state file this just changed).
        if [ -r "${PD}/manifest.json" ]; then
            manifest_stamp_deleted || bench_warn "could not stamp vm.deleted_unix into ${REL_PD}/manifest.json"
            BENCH_APPLY=1 bench_local_index >/dev/null || bench_warn "the run's INDEX.md/CHECKSUMS.sha256 could not be rewritten"
        fi
        log "DOWN_OK ${INST}: no instance and no disk of that name left"
        return 0
    fi
    echo "❌ DOWN_INCOMPLETE ${INST}:${left} may remain; check: gcloud compute instances list / disks list --filter=name=${INST}" >&2
    return 3
}

# manifest_stamp_deleted — the deletion time into probe/manifest.json (vm.deleted_unix).
manifest_stamp_deleted() {
    jq --arg d "$(state_get deleted_unix)" '.vm.deleted_unix = ($d | tonumber? // null)' "${PD}/manifest.json" \
        > "${PD}/manifest.json.tmp" && mv -f "${PD}/manifest.json.tmp" "${PD}/manifest.json"
}

# --- all, plan ------------------------------------------------------------------------------------------
UP_STARTED=0
on_exit() {
    local rc=$? j
    trap - EXIT INT TERM HUP
    for j in $(jobs -p); do kill_tree "${j}"; done
    if [ "${UP_STARTED}" = 1 ] && [ "${DOWN_DONE}" = 0 ]; then
        echo "⚠ benchmark-probe: leaving early (rc ${rc}); deleting ${INST} first" >&2
        cmd_down || rc=3
    fi
    exit "${rc}"
}

cmd_all() {
    local dl rc=0 r
    dl=$(( $(now) + DEADLINE_MIN * 60 ))
    trap on_exit EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
    UP_STARTED=1
    cmd_up; r=$?
    if [ "${r}" -eq 0 ]; then
        cmd_run "${dl}" || rc=1
        cmd_collect || rc=1
    else
        rc=1
    fi
    cmd_down || rc=3
    return "${rc}"
}

print_header() {
    local e
    echo "== benchmark-probe ${SUB}$([ "${DRY}" = 1 ] && echo ' (dry run: no gcloud call is made)'): run ${BENCH_RUN_ID}"
    echo "   instance ${INST}, disk ${DISK}, zone ${ZONE} (stockout fallback: ${FALLBACK_ZONES[*]:-none}), project ${PROJECT_ID}"
    echo "   shape ${MACHINE_TYPE}, ${NODE_DISK_TYPE} ${NODE_DISK_SIZE} GB (iops ${NODE_DISK_IOPS:-default}, throughput ${NODE_DISK_THROUGHPUT:-default} MiB/s), image ${IMAGE}"
    echo "   labels ${LABELS}; results ${REL_PD}/"
    echo "   deadlines: run ${DEADLINE_MIN} min, arm ${ARM_DEADLINE} s, ssh ready ${SSH_READY_SECS} s, delete ${DELETE_SECS} s each"
    echo "   read_ahead_kb: each arm sets it before it starts (the value the VM booted with; 16 for host step ra16, put back after)"
    if [ "${DISKS}" = both ]; then
        echo "   disks: both: each arm runs on the ${NODE_DISK_TYPE} boot disk (<arm>@hyperdisk, ${RB}/data), then on the local SSD"
        echo "   (<arm>@nvme, ${RNV}/data: google-local-nvme-ssd-0, mkfs.ext4 ${NVME_MKFS}, mounted with /'s fstab options);"
        echo "   host maintenance ${MAINT}; the local SSD goes with the instance"
    fi
    echo "   arms (${#ARMS[@]}):"
    for e in ${ARMS[@]+"${ARMS[@]}"}; do
        printf '     %-22s %s%s\n' "$(arm_field "${e}" 1)" "$(arm_field "${e}" 4)" \
            "$([ "$(arm_field "${e}" 2)" = ra16 ] && echo ' [read_ahead_kb 16]')"
    done
}

if [ "${DRY}" = "0" ] && [ "${SUB}" != up ] && [ "${SUB}" != all ]; then
    z="$(state_get zone)"
    if [ -n "${z}" ] && zone_ok "${z}"; then ZONE="${z}"; fi
fi
print_header >&3
case "${SUB}" in
    plan) cmd_all; rc=$?; echo "== plan complete: nothing was contacted or changed" >&3; exit "${rc}" ;;
    up) cmd_up ;;
    run) cmd_run $(( $(now) + DEADLINE_MIN * 60 )) ;;
    collect) cmd_collect ;;
    down) cmd_down ;;
    all) cmd_all ;;
esac
