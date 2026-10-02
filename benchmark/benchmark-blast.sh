#!/usr/bin/env bash
#
# benchmark-blast.sh — drive load against the bench fleet from per-zone COS VMs.
#
#   fund     one bench-funder VM in ZONES[0] runs `blast --prepare` for the whole sender
#            range [RUN_INDEX*100000, +10*BENCH_SENDERS) against bench-validator-01, waits for
#            BENCH_FUND_DONE on its serial console, copies its bucket prefix
#            gs://<bucket>/<run>/index-<RUN_INDEX>/funder/ into results/<run>/funder/, then
#            deletes the VM (unless --keep).
#   run      bench-blaster-01..10, one per validator in the validator's zone, all starting at
#            BENCH_START_AT=now+BENCH_START_DELAY_SECS. Reads the epoch boundary to schedule
#            a direct kill and a restart across it, then restarts the observer. The legacy
#            workload offsets remain available with BENCH_CHAOS_TIMING=mixed. It waits for every
#            BENCH_BLAST_DONE, copies gs://<bucket>/<run>/index-<RUN_INDEX>/blasters/ into
#            results/<run>/blasters/, deletes the blasters (unless --keep). BENCH_CHAOS=0 skips
#            the chaos schedule.
#            BENCH_LAG_INJECT=1 `docker pause`s bench-validator-03 (BENCH_LAG_IDX) at
#            mixed+BENCH_LAG_AT_SECS for BENCH_LAG_PAUSE_SECS, then unpauses it and reports its
#            node mode every poll while it catches up; the unpause is owed on any exit.
#            Before a container is killed, restarted or paused, its log is saved on the node.
#   collect  sampler CSVs from every bench node (IAP scp) into results/<run>/sampler/, and the
#            bucket prefixes of the blast and the funder output in results/<run>/ (manifest
#            .blast/.fund.bucket_prefix; without one, the old gs://<bucket>/<run>/blasters|funder/).
#   delete   delete every bench-blaster-* / bench-funder VM of the benchmark (label-guarded).
#   status   list the load VMs and the latest serial markers (read-only).
#
# Abort watchers (each sets manifest.abort and stops the blasters): any bench node's root
# disk > BENCH_ABORT_DISK_PCT, obs-devnet memory > BENCH_ABORT_OBS_MEM_PCT, a FatalDBFailure
# in any node's telcoin log (recorded as "batch-cache-cliff" — the batch-cache defect, NOT a
# hardware limit), or no chain progress for > BENCH_ABORT_STALL_SECS (quorum lost). They read
# the nodes' BENCH_STATUS serial lines (node-sampler.sh) and Cloud Monitoring — no IAP
# polling — every BENCH_POLL_SECS (>= 240 s, tasks/lessons.md IAP-throttling lesson).
#
# Usage: benchmark/benchmark-blast.sh {fund|run|collect|delete|status} [--yes] [--keep] [--run ID]
# Without --yes nothing is created, deleted or copied: the gcloud argv is printed instead.
# With --yes, a copy of everything printed goes to results/<run>/logs/blast-<action>-<UTC>.log.
#
# A second blast on the same fleet: `run` first moves the previous blast's outputs (blasters/,
# meta/bench-blaster-*, its create/run/collect logs, metrics.json) into
# results/<run>/blast-<its BENCH_RUN_INDEX>-<UTC>/ next to a copy of manifest.json, then resets
# the per-blast manifest keys. It refuses a BENCH_RUN_INDEX an earlier blast used (same
# senders): fund and run the second blast under a new one. The exception is a retry of an
# attempt that exited before its blasters' start time: allowed until 60 s before that time.
# `fund` under a new index first COPIES funder/ of the previous one into
# results/<run>/funder-<its index>-<UTC>/. Each index has its own bucket prefix
# (gs://<bucket>/<run>/index-<N>/), so no blast or fund reads another one's objects.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

ACTION=""; CONFIRM=0; KEEP=0
while [ $# -gt 0 ]; do
    case "$1" in
        fund|run|collect|delete|status) ACTION="$1" ;;
        --yes) CONFIRM=1 ;;
        --keep) KEEP=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}" ;;
        -h|--help) sed -n '2,46p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1'" >&2; exit 1 ;;
    esac
    shift
done
[ -n "${ACTION}" ] || { echo "❌ missing action: fund | run | collect | delete | status" >&2; exit 1; }
if [ -z "${BENCH_RUN_ID:-}" ]; then
    _latest="$(ls -1d "${DIR}"/results/r* 2>/dev/null | tail -1 || true)"
    BENCH_RUN_ID="${_latest:+$(basename "${_latest}")}"
fi
export BENCH_RUN_ID
if [ -z "${BENCH_TXGEN_SHA:-}" ] && [ -n "${BENCH_RUN_ID}" ] && [ -f "${DIR}/results/${BENCH_RUN_ID}/manifest.json" ]; then
    BENCH_TXGEN_SHA="$(jq -r '.txgen_git_sha // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    export BENCH_TXGEN_SHA
fi
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"
source "${DIR}/recovery-lib.sh"

DEPLOYMENTS_FILE="${BENCH_DEPLOYMENTS_JSON:-${BENCH_RESULTS_DIR}/deployments-bench.json}"
STARTUP="${DIR}/blaster-startup.sh"
FUNDER="bench-funder"
VAL_COUNT=0
for r in "${NODE_ROLES[@]}"; do [ "${r}" = "validator" ] && VAL_COUNT=$((VAL_COUNT + 1)); done
OBSERVER_IDX=""
for i in "${!NODE_ROLES[@]}"; do [ "${NODE_ROLES[$i]}" = "observer" ] && OBSERVER_IDX="$i"; done
CHAOS_KILL_IDX=4          # bench-validator-05
[ "${BENCH_POLL_SECS}" -ge 240 ] || bench_die "BENCH_POLL_SECS=${BENCH_POLL_SECS} < 240 (IAP/serial polling lesson)"

blaster_name() { printf 'bench-blaster-%02d' "$(( $1 + 1 ))"; }

# --- shared preflight ---------------------------------------------------------------
preflight() {
    echo ">>> preflight"
    bench_require_tools gcloud jq || exit 1
    [ -f "${STARTUP}" ] || bench_die "missing ${STARTUP}"
    if [ -f "${BENCH_TXGEN_CONFIG}" ]; then echo "    ✓ txgen config ${BENCH_TXGEN_CONFIG}"
    else bench_warn "txgen config ${BENCH_TXGEN_CONFIG} missing"; [ "${BENCH_APPLY}" = "1" ] && exit 1; fi
    if [ -f "${DEPLOYMENTS_FILE}" ]; then echo "    ✓ address book ${DEPLOYMENTS_FILE}"
    else bench_warn "address book ${DEPLOYMENTS_FILE} missing (benchmark-deploy.sh --with-contracts --only 11)"; [ "${BENCH_APPLY}" = "1" ] && exit 1; fi
    bench_require_txgen_image
    echo "    image ${BENCH_TXGEN_IMAGE}"
    local pinned; pinned="$(jq -r '.txgen_image // empty' "$(bench_manifest)" 2>/dev/null || true)"
    if [ -n "${pinned}" ] && [ "${pinned}" != "${BENCH_TXGEN_IMAGE}" ]; then
        bench_die "manifest pins ${pinned} but this run resolved ${BENCH_TXGEN_IMAGE} — set BENCH_TXGEN_SHA=${pinned##*blast-v2-}"
    fi
    if [ "${BENCH_APPLY}" = "1" ]; then
        [ -n "$(bench_txgen_image_digest)" ] || bench_die "image ${BENCH_TXGEN_IMAGE} not in the registry (benchmark-deploy.sh --only 1 builds it)"
        bench_txgen_cli_probe
        gcloud storage buckets describe "gs://${BENCH_BUCKET}" --format='value(name)' >/dev/null 2>&1 \
            || bench_die "bucket gs://${BENCH_BUCKET} missing (benchmark-deploy.sh step 12)"
        local s
        for s in "${BENCH_TXGEN_MASTER_SECRET}" "${BENCH_TXGEN_SEED_SECRET}"; do
            gcloud secrets get-iam-policy "${s}" --project="${PROJECT_ID}" --format=json 2>/dev/null \
                | jq -e --arg m "serviceAccount:${SERVICE_ACCOUNT}" \
                    '[.bindings[]? | select(.role == "roles/secretmanager.secretAccessor") | .members[]] | index($m)' >/dev/null \
                || bench_die "${SERVICE_ACCOUNT} cannot access secret ${s} (benchmark-deploy.sh step 12)"
        done
        echo "    ✓ image, bucket and secret access present"
    fi
}

# node_url <idx> — "<instance>=http://<internal-ip>:8545" (placeholder when absent, dry run).
node_url() {
    local ip; ip="$(tn_node_int_ip "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}" 2>/dev/null || true)"
    if [ -z "${ip}" ]; then
        [ "${BENCH_APPLY}" = "1" ] && bench_die "${INSTANCE_NAMES[$1]} has no internal IP — is the fleet up?"
        ip="<internal-ip-of-${INSTANCE_NAMES[$1]}>"
    fi
    printf '%s=http://%s:8545' "${INSTANCE_NAMES[$1]}" "${ip}"
}

# create_vm <name> <zone> <mode> <node-urls> <senders> <sender-start> <start-at> — one COS load VM.
create_vm() {
    local name="$1" zone="$2" mode="$3" urls="$4" senders="$5" start="$6" at="$7" mdir
    bench_assert_bench_name "instance" "${name}"
    case "${name}" in bench-blaster-*|bench-funder) ;; *) bench_die "load VM name ${name} is not bench-blaster-*/bench-funder" ;; esac
    # Free-form values travel as files so gcloud's k=v,k=v parsing can never split them.
    mdir="${BENCH_RESULTS_DIR}/meta/${name}"
    if [ "${BENCH_APPLY}" = "1" ]; then
        mkdir -p "${mdir}"; printf '%s' "${urls}" > "${mdir}/NODE_URLS"; printf '%s' "${BENCH_BLAST_ARGS:-}" > "${mdir}/BLAST_ARGS"
    fi
    local files="startup-script=${STARTUP},txgen-config=${BENCH_TXGEN_CONFIG},txgen-deployments=${DEPLOYMENTS_FILE},NODE_URLS=${mdir}/NODE_URLS"
    [ -n "${BENCH_BLAST_ARGS:-}" ] && files="${files},BLAST_ARGS=${mdir}/BLAST_ARGS"
    local meta="^##^BENCH_MODE=${mode}##TXGEN_IMAGE=${BENCH_TXGEN_IMAGE}##SENDERS=${senders}##SENDER_START=${start}"
    [ -n "${at}" ] && meta="${meta}##BENCH_START_AT=${at}"     # omitted for the funder: start now
    meta="${meta}##BENCH_BUCKET=${BENCH_BUCKET}##RUN_ID=${BENCH_RUN_ID}##RUN_INDEX=${BENCH_RUN_INDEX}##LABEL=${name}"
    meta="${meta}##MASTER_SECRET=${BENCH_TXGEN_MASTER_SECRET}##SEED_SECRET=${BENCH_TXGEN_SEED_SECRET}"
    meta="${meta}##WARMUP_SECS=${BENCH_WARMUP_SECS}##DURATION_SECS=${BENCH_DURATION_SECS}##COOLDOWN_SECS=${BENCH_COOLDOWN_SECS}"
    bench_run gcloud compute instances create "${name}" --project="${PROJECT_ID}" --zone="${zone}" \
        --machine-type="${BENCH_BLASTER_MACHINE_TYPE}" \
        --image-family=cos-stable --image-project=cos-cloud \
        --boot-disk-size=20GB --boot-disk-type=pd-balanced \
        --service-account="${SERVICE_ACCOUNT}" --scopes=cloud-platform \
        --tags=bench-blaster \
        --labels="${BENCH_LABELS},tn-role=blaster" \
        --metadata-from-file="${files}" \
        --metadata="${meta}"
}

# assert_load_vm <name> <zone> — created VM carries tag bench-blaster + label benchmark=1.
assert_load_vm() {
    [ "${BENCH_APPLY}" = "1" ] || return 0
    local j; j="$(bench_instance_json "$1" "$2")"
    [ -n "${j}" ] || bench_die "$1 not found after create"
    printf '%s' "${j}" | jq -e '(.tags.items // []) == ["bench-blaster"] and .labels.benchmark == "1"' >/dev/null \
        || bench_die "$1 lacks tag bench-blaster / label benchmark=1 — delete it: benchmark/benchmark-blast.sh delete --yes"
    bench_run gcloud compute disks add-labels "$1" --zone="$2" --project="${PROJECT_ID}" --labels="${BENCH_LABELS},tn-role=blaster" --format=none
}

delete_vms() { # <zone> <name...>
    local zone="$1"; shift
    [ $# -gt 0 ] || return 0
    local n; for n in "$@"; do bench_assert_bench_name "instance" "${n}"; done
    bench_run gcloud compute instances delete "$@" --zone="${zone}" --project="${PROJECT_ID}" --quiet
}

# Done markers from blaster-startup.sh: "<MARK> rc=N reason=R [...]". Only rc=0 reason=ok
# means the results are in the bucket; anything else leaves the VM holding the only copy.
# Serial-console lines end in CRLF: strip \r first or "reason=ok" compares as "ok\r".
marker_rc() { tr -d '\r' | sed -n "s/.*$1 rc=\([0-9][0-9]*\).*/\1/p" | tail -1; }
marker_reason() { tr -d '\r' | sed -n "s/.*$1 rc=[0-9][0-9]* reason=\([^ ]*\).*/\1/p" | tail -1; }

# settle_load_vm <name> <zone> <results-subdir> <done-line> <MARK> — delete the VM only when
# its results are safe: rc=0 reason=ok (uploaded), or an IAP scp of /var/lib/bench/out
# succeeded. Otherwise KEEP it and say so (it may hold the only copy). --keep never deletes.
settle_load_vm() {
    local name="$1" zone="$2" sub="$3" line="$4" mark="$5" rc reason dest
    if [ "${BENCH_APPLY}" = "1" ] && [ -z "$(bench_instance_json "${name}" "${zone}")" ]; then return 0; fi
    rc="$(printf '%s\n' "${line}" | marker_rc "${mark}")"
    reason="$(printf '%s\n' "${line}" | marker_reason "${mark}")"
    if [ "${rc}" = "0" ] && [ "${reason}" = "ok" ]; then
        [ "${KEEP}" -eq 1 ] || delete_vms "${zone}" "${name}" || true
        return 0
    fi
    bench_warn "${name}: '${line:-no ${mark} marker}' — fetching /var/lib/bench/out over IAP before any delete"
    # The fetch goes into a directory that holds no file yet, so the check below counts only
    # what this fetch brought: funder/ keeps an earlier index's scp-bench-funder/ (fund copies
    # funder/ aside, it does not move it).
    dest="${BENCH_RESULTS_DIR}/${sub}/scp-${name}"
    [ -z "$(find "${dest}" -type f 2>/dev/null | head -1)" ] || dest="${dest}-$(date -u +%Y%m%dT%H%M%SZ)"
    if [ "${BENCH_APPLY}" = "1" ]; then mkdir -p "${dest}"; fi
    if bench_run gcloud compute scp --recurse "${name}:/var/lib/bench/out" "${dest}/" --zone="${zone}" \
            --project="${PROJECT_ID}" --tunnel-through-iap --scp-flag="-o ConnectTimeout=20" \
       && { [ "${BENCH_APPLY}" != "1" ] || [ -n "$(find "${dest}" -type f 2>/dev/null | head -1)" ]; }; then
        bench_manifest_note "${name}: '${line:-no marker}' — results fetched over IAP into ${dest#"${BENCH_RESULTS_DIR}"/}/" || true
        [ "${KEEP}" -eq 1 ] || delete_vms "${zone}" "${name}" || true
    else
        echo "❌ ${name} KEPT: its results could not be fetched (${line:-no marker}). Recover by hand, then benchmark-blast.sh delete --yes" >&2
        bench_manifest_note "${name} kept: results not fetched (${line:-no marker})" || true
    fi
}

# bucket_prefix <blasters|funder> — where the load VMs of this BENCH_RUN_INDEX put their objects:
# gs://<bucket>/<run>/index-<N>/<sub>. create_vm passes the index as RUN_INDEX metadata and
# blaster-startup.sh builds the same path; a VM created without that key wrote to the old flat
# gs://<bucket>/<run>/<sub>, where every blast and fund of this run used to overwrite the last.
bucket_prefix() { printf 'gs://%s/%s/index-%s/%s' "${BENCH_BUCKET}" "${BENCH_RUN_ID}" "${BENCH_RUN_INDEX}" "$1"; }

# recorded_prefix <blast|fund> <blasters|funder> — the prefix the manifest recorded for the blast
# (.blast) or the funder output (.fund) in results/<run>/; the old flat one when none was.
recorded_prefix() {
    local p; p="$(jq -r --arg k "$1" '.[$k].bucket_prefix // empty' "$(bench_manifest)" 2>/dev/null || true)"
    printf '%s' "${p:-gs://${BENCH_BUCKET}/${BENCH_RUN_ID}/$2}"
}

copy_prefix() { # <gs-prefix> <results-subdir> — the prefix's objects -> results/<run>/<subdir>/; 1 when the copy failed
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/$2"
    bench_run gcloud storage cp -r "$1/*" "${BENCH_RESULTS_DIR}/$2/" && return 0
    bench_warn "copy of $1 failed"
    return 1
}

# --- script log + one blast per results dir --------------------------------------------
# results/<run>/ holds the fleet and ONE blast. Before `run` starts another, archive_prev_blast
# moves the previous blast's own outputs into results/<run>/blast-<its index>-<UTC>/ beside a
# COPY of manifest.json and resets the per-blast manifest keys. The fleet's files stay, and so
# do sampler/ (cumulative CSVs) and funder/ (`fund` for the new index ran before this `run`).
# Moves go into a directory mkdir just created: nothing is overwritten or deleted.
BLAST_LOG=""      # this invocation's copy of its output; never archived

# start_blast_log — with --yes, copy everything this invocation prints to
# logs/blast-<action>-<UTC>.log (a new file) while it still reaches the terminal. stdout and
# stderr keep separate tees. Both ignore HUP, INT (tee -i as well), TERM and PIPE, so they end
# only when the script closes their input: a Ctrl-C, a TERM to the process group, a closed
# terminal or a dead parent copy (deploy step 14) leaves the file copy running for the EXIT
# trap. A write to a gone terminal or parent then fails inside tee, which carries on with the
# file. A plan-only run creates nothing.
start_blast_log() {
    [ "${BENCH_APPLY}" = "1" ] || return 0
    local n=0
    mkdir -p "${BENCH_RESULTS_DIR}/logs"
    until BLAST_LOG="${BENCH_RESULTS_DIR}/logs/blast-${ACTION}-$(date -u +%Y%m%dT%H%M%SZ).log"; ( set -C; : > "${BLAST_LOG}" ) 2>/dev/null; do
        n=$((n + 1)); [ "${n}" -lt 5 ] || bench_die "no free log name in ${BENCH_RESULTS_DIR}/logs"
        sleep 1
    done
    exec > >(trap '' HUP INT TERM PIPE; exec tee -i -a "${BLAST_LOG}") \
        2> >(trap '' HUP INT TERM PIPE; exec tee -i -a "${BLAST_LOG}" >&2)
    echo ">>> ${ACTION}: output copied to ${BLAST_LOG}"
}

# prev_blast_index — BENCH_RUN_INDEX of the blast in the live manifest: .blast.run_index, else
# (manifests from before .blast) bench-blaster-01's sender_start / 100000, else "unknown".
prev_blast_index() {
    jq -r --arg b "$(blaster_name 0)" '(.blast.run_index
        // ((.blasters // [])[] | select(.name == $b) | .sender_start | select(type == "number" and . % 100000 == 0) | . / 100000)
        // "unknown") | tostring' "$(bench_manifest)" 2>/dev/null || echo unknown
}

# prev_blast_recorded — 0 when the manifest or the results dir shows a previous blast. Script
# logs and metrics.json alone do not count.
prev_blast_recorded() {
    local r="${BENCH_RESULTS_DIR}" m; m="$(bench_manifest)"
    if [ -f "${m}" ] && jq -e '(.blasters // []) != [] or (.chaos // []) != [] or .abort != null or (.phases // []) != []
            or .blast != null or .timestamps.blast_start_at != null or .timestamps.blast_end != null' "${m}" >/dev/null 2>&1; then
        return 0
    fi
    [ -n "$(find "${r}/blasters" -type f 2>/dev/null | head -1)" ] && return 0
    compgen -G "${r}/meta/bench-blaster-*" >/dev/null || compgen -G "${r}/logs/create-bench-blaster-*.log" >/dev/null
}

# blast_indices_used — BENCH_RUN_INDEX of the previous blast and of every archived one.
blast_indices_used() {
    local d
    if prev_blast_recorded; then prev_blast_index; fi
    for d in "${BENCH_RESULTS_DIR}"/blast-[0-9]*-*; do
        [ -d "${d}" ] || continue
        d="${d##*/blast-}"; printf '%s\n' "${d%%-*}"
    done
}

# prev_blast_items — what archive_prev_blast moves, relative to the results dir.
prev_blast_items() {
    local r="${BENCH_RESULTS_DIR}" f
    for f in "${r}/blasters" "${r}"/meta/bench-blaster-* "${r}"/logs/create-bench-blaster-*.log \
             "${r}"/logs/blast-run-*.log "${r}"/logs/blast-collect-*.log "${r}/metrics.json"; do
        [ -e "${f}" ] && [ "${f}" != "${BLAST_LOG}" ] && printf '%s\n' "${f#"${r}"/}"
    done
    return 0
}

# prev_attempt_unsent — 0 when the blast in the live manifest used this BENCH_RUN_INDEX but none of
# its senders can have sent: its run exited (the EXIT trap recorded .abort "interrupted") and
# .blast.start_at, the BENCH_START_AT its blasters sleep until, is still more than 60 s away (clock
# skew). do_run has already checked that no bench-blaster VM exists, so none can start later.
# Once that time has passed, a blaster left running (--keep, a failed delete) may have sent
# before someone deleted it, and the manifest records nothing that rules it out.
prev_attempt_unsent() {
    jq -e --arg i "${BENCH_RUN_INDEX}" --arg t "$(bench_iso_from_unix "$(( $(bench_now_unix) + 60 ))")" \
        '.blast.run_index == ($i|tonumber) and .abort.reason == "interrupted" and (.blast.start_at // "") > $t' \
        "$(bench_manifest)" >/dev/null 2>&1
}

# archive_prev_blast — see above. Stops before anything moves when an earlier blast (the previous
# or an archived one) used this BENCH_RUN_INDEX: its sender range would be reused. The one
# exception is a previous attempt that never sent (prev_attempt_unsent): it is archived like any
# blast and this run retries its index. Dry run: prints the plan, touches nothing.
archive_prev_blast() {
    local r="${BENCH_RESULTS_DIR}" prev dest it used next n=0 items=()
    case "${BENCH_RUN_INDEX}" in ''|*[!0-9]*|0?*) bench_die "BENCH_RUN_INDEX='${BENCH_RUN_INDEX}' must be a non-negative integer" ;; esac
    used="$(blast_indices_used)"
    if [ "$(grep -cx "${BENCH_RUN_INDEX}" <<< "${used}")" -eq 1 ] && prev_attempt_unsent; then
        echo "    the previous attempt under BENCH_RUN_INDEX=${BENCH_RUN_INDEX} exited before its blasters' start and none exists: retrying under the same index"
    elif grep -qx "${BENCH_RUN_INDEX}" <<< "${used}"; then
        next="$(grep -x '[0-9][0-9]*' <<< "${used}" | sort -n | tail -1)"
        bench_die "an earlier blast on this fleet used BENCH_RUN_INDEX=${BENCH_RUN_INDEX}, so this one would reuse its senders. Fund and run under a new index: BENCH_RUN_INDEX=$(( next + 1 )) benchmark/benchmark-blast.sh fund --yes, then run --yes. Nothing was moved."
    fi
    if ! prev_blast_recorded; then echo "    no previous blast in ${r} — nothing to archive"; return 0; fi
    prev="$(prev_blast_index)"
    [ "${prev}" != "unknown" ] || bench_warn "the previous blast recorded no BENCH_RUN_INDEX: make sure index ${BENCH_RUN_INDEX} was funded and never blasted"
    while IFS= read -r it; do items+=("${it}"); done < <(prev_blast_items)
    echo ">>> archive the previous blast (BENCH_RUN_INDEX ${prev}) into ${r}/blast-${prev}-<UTC>/ with a copy of manifest.json"
    # "${items[@]}" of an empty array is an unbound variable under bash 3.2 with set -u: a blast
    # the manifest records may have left no file (it failed before creating its blasters).
    if [ "${#items[@]}" -eq 0 ]; then echo "    (no per-blast file to move)"
    else for it in "${items[@]}"; do echo "    mv ${it}"; done; fi
    echo "    manifest: .blasters=[] .chaos=[] .abort=null .phases=[], drop .blast and timestamps blast_start_at/blast_end/collect_start/step_14_done/step_15_done"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — nothing moved)"; return 0; fi
    if [ "${#items[@]}" -eq 0 ] && [ ! -f "$(bench_manifest)" ]; then
        echo "    nothing to archive: no per-blast file and no manifest.json"; return 0
    fi
    until dest="${r}/blast-${prev}-$(date -u +%Y%m%dT%H%M%SZ)"; [ ! -e "${dest}" ] && mkdir "${dest}"; do
        [ -e "${dest}" ] || bench_die "cannot create ${dest} — nothing was moved; the blast has not started"
        n=$((n + 1)); [ "${n}" -lt 5 ] || bench_die "no free blast-${prev}-<UTC> name in ${r} — nothing was moved; the blast has not started"
        echo "    $(basename "${dest}") exists — trying a new timestamp"
        sleep 1
    done
    if [ -f "$(bench_manifest)" ]; then
        cp -p "$(bench_manifest)" "${dest}/manifest.json" || bench_die "cannot copy manifest.json into ${dest}/ — nothing was moved"
    fi
    [ "${#items[@]}" -eq 0 ] || for it in "${items[@]}"; do
        if [ -e "${dest}/${it}" ] || ! mkdir -p "${dest}/$(dirname "${it}")" || ! mv "${r}/${it}" "${dest}/${it}"; then
            bench_die "could not move ${it} into ${dest}/ — nothing was deleted and the blast has not started; what moved is in ${dest}/, the rest is still in place"
        fi
    done
    bench_manifest_jq '.blasters = [] | .chaos = [] | .abort = null | .phases = [] | del(.blast)
        | .timestamps |= del(.blast_start_at, .blast_end, .collect_start, .step_14_done, .step_15_done)' \
        || bench_die "outputs moved into ${dest}/ but manifest.json was not reset — the blast has not started"
    bench_manifest_note "blast index ${prev} archived into $(basename "${dest}")/ at $(bench_now_iso); earlier notes belong to it or to the fleet" || true
    echo "    ✓ previous blast archived: ${dest}/"
}

# record_blast <start_at-unix> — manifest.blast: the settings that tell one blast from another.
record_blast() {
    echo "    blast: BENCH_RUN_INDEX=${BENCH_RUN_INDEX} chaos=${BENCH_CHAOS} lag_inject=${BENCH_LAG_INJECT} (node idx ${BENCH_LAG_IDX}, mixed+${BENCH_LAG_AT_SECS}s for ${BENCH_LAG_PAUSE_SECS}s)"
    echo "    bucket prefix: $(bucket_prefix blasters)/"
    [ "${BENCH_APPLY}" = "1" ] || return 0
    bench_manifest_jq --arg i "${BENCH_RUN_INDEX}" --arg c "${BENCH_CHAOS}" --arg li "${BENCH_LAG_INJECT}" --arg lx "${BENCH_LAG_IDX}" \
        --arg la "${BENCH_LAG_AT_SECS}" --arg lp "${BENCH_LAG_PAUSE_SECS}" --arg s "$(bench_iso_from_unix "$1")" --arg bp "$(bucket_prefix blasters)" \
        '.blast = {run_index: ($i|tonumber), chaos: ($c|tonumber), lag_inject: ($li|tonumber), lag_idx: ($lx|tonumber),
                   lag_at_secs: ($la|tonumber), lag_pause_secs: ($lp|tonumber), start_at: $s, bucket_prefix: $bp}'
}

# ================================ fund ===============================================
# prev_funder_index — BENCH_RUN_INDEX of the output in results/<run>/funder/: .fund.run_index,
# recorded once `fund` has copied its objects there; "unknown" for output from before that key.
prev_funder_index() {
    jq -r '.fund.run_index // "unknown" | tostring' "$(bench_manifest)" 2>/dev/null || echo unknown
}

# set_aside_prev_funder — before `fund` writes anything, COPY the funder output of another index
# (funder/, meta/bench-funder/, manifest.json with its fund timestamps) into
# results/<run>/funder-<its index>-<UTC>/, a directory mkdir just created. A copy, not a move:
# the live files change only when the new fund overwrites them. Dry run: prints the plan.
set_aside_prev_funder() {
    local r="${BENCH_RESULTS_DIR}" prev dest it n=0 items=()
    [ -n "$(find "${r}/funder" -type f 2>/dev/null | head -1)" ] || return 0
    prev="$(prev_funder_index)"
    if [ "${prev}" = "${BENCH_RUN_INDEX}" ]; then
        echo "    funder/ holds the output of BENCH_RUN_INDEX ${prev}: funding it again overwrites it"; return 0
    fi
    for it in funder meta/bench-funder manifest.json; do [ -e "${r}/${it}" ] && items+=("${it}"); done
    echo ">>> copy the funder output of BENCH_RUN_INDEX ${prev} ($(find "${r}/funder" -type f | wc -l | tr -d ' ') files in funder/) into ${r}/funder-${prev}-<UTC>/"
    for it in "${items[@]}"; do echo "    cp ${it}"; done
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — nothing copied)"; return 0; fi
    until dest="${r}/funder-${prev}-$(date -u +%Y%m%dT%H%M%SZ)"; [ ! -e "${dest}" ] && mkdir "${dest}"; do
        [ -e "${dest}" ] || bench_die "cannot create ${dest} — nothing was copied; the fund has not started"
        n=$((n + 1)); [ "${n}" -lt 5 ] || bench_die "no free funder-${prev}-<UTC> name in ${r} — nothing was copied; the fund has not started"
        echo "    $(basename "${dest}") exists — trying a new timestamp"
        sleep 1
    done
    for it in "${items[@]}"; do
        if ! mkdir -p "${dest}/$(dirname "${it}")" || ! cp -Rp "${r}/${it}" "${dest}/${it}"; then
            bench_die "could not copy ${it} into ${dest}/ — the fund has not started and funder/ is unchanged"
        fi
    done
    bench_manifest_note "funder output of index ${prev} copied into $(basename "${dest}")/ at $(bench_now_iso); funder/ now receives index ${BENCH_RUN_INDEX}" || true
    echo "    ✓ funder output copied: ${dest}/"
}

do_fund() {
    preflight
    local zone="${ZONES[0]}" urls senders start rc line
    case "${BENCH_RUN_INDEX}" in ''|*[!0-9]*|0?*) bench_die "BENCH_RUN_INDEX='${BENCH_RUN_INDEX}' must be a non-negative integer" ;; esac
    urls="$(node_url 0)"
    senders=$(( VAL_COUNT * BENCH_SENDERS ))
    start=$(( BENCH_RUN_INDEX * 100000 ))
    echo ">>> fund: ${FUNDER} (${zone}) --prepare senders=${senders} sender-start=${start} against ${urls}"
    echo "    bucket prefix: $(bucket_prefix funder)/"
    if [ -n "$(bench_instance_json "${FUNDER}" "${zone}")" ]; then
        bench_die "${FUNDER} already exists — inspect/delete it first (benchmark-blast.sh delete --yes)"
    fi
    set_aside_prev_funder
    gcloud auth print-access-token >/dev/null
    bench_manifest_ts fund_start
    create_vm "${FUNDER}" "${zone}" fund "${urls}" "${senders}" "${start}" ""
    assert_load_vm "${FUNDER}" "${zone}"
    [ "${BENCH_APPLY}" = "1" ] || { echo "DRY RUN — re-run with --yes."; return 0; }
    bench_serial_wait "${FUNDER}" "${zone}" "BENCH_FUND_DONE rc=" "${BENCH_FUND_TIMEOUT_SECS:-3600}" "${BENCH_FUND_POLL_SECS:-60}" \
        || bench_die "funder did not finish; serial: gcloud compute instances get-serial-port-output ${FUNDER} --zone=${zone}"
    line="$(bench_serial_last "${FUNDER}" "${zone}" "BENCH_FUND_DONE rc=")"
    rc="$(printf '%s\n' "${line}" | marker_rc BENCH_FUND_DONE)"
    echo "    funder: ${line}"
    # .fund says funder/ holds this index's output: only a copy that succeeded may claim that.
    if copy_prefix "$(bucket_prefix funder)" funder; then
        bench_manifest_jq --arg i "${BENCH_RUN_INDEX}" --arg p "$(bucket_prefix funder)" '.fund = {run_index: ($i|tonumber), bucket_prefix: $p}'
    else
        bench_warn "funder/ does not hold index ${BENCH_RUN_INDEX}'s output and .fund is unchanged; copy it by hand: gcloud storage cp -r '$(bucket_prefix funder)/*' ${BENCH_RESULTS_DIR}/funder/"
        bench_manifest_note "fund: copy of $(bucket_prefix funder) into funder/ failed at $(bench_now_iso); .fund not updated" || true
    fi
    bench_manifest_ts fund_end
    bench_manifest_note "fund: ${line}"
    settle_load_vm "${FUNDER}" "${zone}" funder "${line}" BENCH_FUND_DONE
    [ "${rc:-1}" = "0" ] && [ "$(printf '%s\n' "${line}" | marker_reason BENCH_FUND_DONE)" = "ok" ] || bench_die "funding failed (${line})"
    echo "    ✓ funded"
}

# ================================ run ================================================
# Run state is GLOBAL (not local to do_run) so the EXIT trap can act on it.
ABORTED=""
RUN_CREATED=0; RUN_FINISHED=0; RUN_STOPPED=0; RUN_START_AT=0
RUN_DID_KILL=0; RUN_DID_BACK=0; RUN_DID_OBS=0
RUN_DID_PAUSE=0; RUN_DID_UNPAUSE=0; LAG_UNPAUSE_TS=0   # lag injection; an unpause is owed while PAUSE=1 UNPAUSE=0
CHAOS_RC=0        # rc of the last chaos_do
DONE_LINE=()      # per blaster index: its last "BENCH_BLAST_DONE rc=..." serial line
PREV_ROUNDS=""    # {"<node>": max tn_primary_round} from the previous poll (Prometheus)
STALL_POLLS=0; LAST_ADVANCE_TS=0
NODE_STALL_COUNTS="{}"

record_abort() { # <reason> <node> <detail>
    [ -n "${ABORTED}" ] && return 0
    ABORTED="$1"
    echo "❌❌ ABORT: $1 node=$2 — $3" >&2
    bench_manifest_jq --arg ts "$(bench_now_iso)" --arg r "$1" --arg n "$2" --arg d "$3" \
        '.abort = {ts: $ts, reason: $r, node: $n, detail: $d}' || true
}

record_chaos() { # <node> <action> <note> <rc>
    bench_manifest_jq --arg ts "$(bench_now_iso)" --arg n "$1" --arg a "$2" --arg note "$3" --arg rc "$4" \
        '.chaos += [{ts: $ts, node: $n, action: $a, note: $note, rc: ($rc|tonumber)}]' || true
}

# chaos_do <idx> <remote-cmd> <action-label> <note> — the ssh rc goes to the manifest and CHAOS_RC.
chaos_do() {
    local inst="${INSTANCE_NAMES[$1]}" zone="${ZONES[$1]}" rc=0
    bench_log "CHAOS ${inst}: $3"
    local remote_cmd="printf 'BENCH_CHAOS_BEGIN node=${inst} '; date -u +%s.%N; { $2; }; action_rc=\$?; printf 'BENCH_CHAOS_END node=${inst} rc=%s ' \"\$action_rc\"; date -u +%s.%N; exit \"\$action_rc\""
    tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}" \
        | tee -a "${BENCH_RESULTS_DIR}/chaos-remote.log" || rc=$?
    CHAOS_RC="${rc}"
    record_chaos "${inst}" "$3" "$4" "${rc}"
}

# chaos_restart_v05 <note> — the restart owed after the kill: on schedule, after an abort, at the
# end of the watch and from the EXIT trap. Until systemd confirms the unit active it stays owed
# (the watch loop tries again at each later poll), and the command to run by hand is printed.
chaos_restart_v05() {
    local inst="${INSTANCE_NAMES[$CHAOS_KILL_IDX]}" zone="${ZONES[$CHAOS_KILL_IDX]}"
    chaos_do "${CHAOS_KILL_IDX}" "sudo systemctl start telcoin && systemctl is-active telcoin" \
        "systemctl start telcoin" "$1"
    if [ "${CHAOS_RC}" -eq 0 ]; then RUN_DID_BACK=1; return 0; fi
    echo "❌ ${inst} may still be DOWN: restart not confirmed (rc=${CHAOS_RC}). Start it by hand:" >&2
    echo "    gcloud compute ssh ${inst} --zone=${zone} --project=${PROJECT_ID} --tunnel-through-iap --command='sudo systemctl start telcoin'" >&2
    bench_manifest_note "restart-not-confirmed: ${inst} at $(bench_now_iso) (rc=${CHAOS_RC}, $1); still owed" || true
    return 1
}

# save_log_first <idx> <label> — the container log onto the node before a step kills, restarts
# or pauses it (docker run --rm: a stopped container takes its log along). A failed save warns
# and leaves a manifest note; the step still goes ahead on schedule.
save_log_first() {
    bench_save_node_log "$1" "$2" && return 0
    bench_warn "${INSTANCE_NAMES[$1]}: container log not saved (${2}) — the ${2#pre-} goes ahead on schedule without it"
    bench_manifest_note "log-save-failed: ${INSTANCE_NAMES[$1]} ${2} at $(bench_now_iso); the ${2#pre-} went ahead without a saved log" || true
}

# Lag injection. docker pause freezes the container (no restart, no lost state), so the node
# falls behind while the fleet runs on, then must catch up. Each command confirms the state it
# set: the ssh fails unless docker reports State.Paused=true / false afterwards.
LAG_PAUSE_CMD="sudo docker pause telcoin; s=\$(sudo docker inspect telcoin --format '{{.State.Paused}}'); echo \"telcoin State.Paused=\$s\"; [ \"\$s\" = true ]"
LAG_UNPAUSE_CMD="sudo docker unpause telcoin; s=\$(sudo docker inspect telcoin --format '{{.State.Paused}}'); echo \"telcoin State.Paused=\$s\"; [ \"\$s\" = false ]"

# lag_unpause <note> — the unpause owed once a pause was attempted: on schedule, after an abort,
# at the end of the run and from the EXIT trap. Until docker confirms State.Paused=false it
# stays owed, and the command to run by hand is printed.
lag_unpause() {
    local inst="${INSTANCE_NAMES[$BENCH_LAG_IDX]}" zone="${ZONES[$BENCH_LAG_IDX]}"
    [ "${LAG_UNPAUSE_TS}" -gt 0 ] || LAG_UNPAUSE_TS="$(bench_now_unix)"
    chaos_do "${BENCH_LAG_IDX}" "${LAG_UNPAUSE_CMD}" "lag-unpause" "$1"
    if [ "${CHAOS_RC}" -eq 0 ]; then RUN_DID_UNPAUSE=1; LAG_UNPAUSE_TS="$(bench_now_unix)"; return 0; fi
    echo "❌ ${inst} may still be PAUSED: unpause not confirmed (rc=${CHAOS_RC}). Unpause it by hand:" >&2
    echo "    gcloud compute ssh ${inst} --zone=${zone} --project=${PROJECT_ID} --tunnel-through-iap --command='sudo docker unpause telcoin'" >&2
    return 1
}

# try_up_to <n> <cmd...> — cmd until it returns 0, at most n times, 5 s apart; its last rc. The
# EXIT trap gives each remote step 3 tries: INT and TERM stay ignored there, but gcloud compute ssh
# installs its own handlers for both, so a second ^C or TERM to the process group still ends the
# ssh in flight.
try_up_to() {
    local n="$1" i=1 rc; shift
    while :; do
        rc=0; "$@" || rc=$?
        { [ "${rc}" -ne 0 ] && [ "${i}" -lt "${n}" ]; } || return "${rc}"
        echo "    try ${i} of ${n} failed (rc=${rc}); trying again in 5s" >&2
        sleep 5; i=$((i + 1))
    done
}

# stop_blasters [tries] — docker stop txgen on every blaster, each up to <tries> times (default 1).
# 1 (and the names, each with the command to run by hand) when a stop was not confirmed; every
# blaster is tried either way.
stop_blasters() {
    local k name failed=""
    RUN_STOPPED=1
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"
        try_up_to "${1:-1}" tn_iap_ssh "${name}" "${ZONES[$k]}" "sudo docker stop -t 30 txgen >/dev/null 2>&1; true" && continue
        failed="${failed} ${name}"
        echo "❌ ${name}: docker stop txgen not confirmed. Stop it by hand:" >&2
        echo "    gcloud compute ssh ${name} --zone=${ZONES[$k]} --project=${PROJECT_ID} --tunnel-through-iap --command='sudo docker stop -t 30 txgen'" >&2
    done
    [ -n "${failed}" ] || return 0
    bench_warn "docker stop txgen not confirmed on:${failed}"
    return 1
}

# status_field <line> <key> — value of key=... in a BENCH_STATUS line.
status_field() { printf '%s' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p" | tail -1; }

# round_stall_check <now> <all_done> — quorum-lost watcher on CONSENSUS ROUNDS (Prometheus
# max by (node) (tn_primary_round{network="bench"})), not block height: an idle TN chain sits
# at block 0 (empty non-epoch-closing outputs are not executed), so blocks would "stall"
# through the pre-start sleep. A failed/empty query is UNKNOWN (never counts); quorum-lost
# needs two consecutive polls in which no node's round advanced.
round_stall_check() {
    local now="$1" done_all="$2" cur adv
    cur="$(bench_prom_rounds max)"
    if [ -z "${cur}" ] || [ "${cur}" = "{}" ]; then
        echo "    consensus rounds: unknown (Prometheus query failed/empty) — not counted"
        PREV_ROUNDS=""; STALL_POLLS=0; NODE_STALL_COUNTS="{}"
        return 0
    fi
    if [ -n "${PREV_ROUNDS}" ]; then
        adv="$(bench_rounds_advanced "${PREV_ROUNDS}" "${cur}" | jq -r 'length')"
        if [ "${adv:-0}" -gt 0 ]; then
            STALL_POLLS=0; LAST_ADVANCE_TS="${now}"
            echo "    consensus rounds: ${adv} node(s) advanced ($(printf '%s' "${cur}" | jq -r '[.[]] | (min|tostring) + ".." + (max|tostring)'))"
        else
            STALL_POLLS=$((STALL_POLLS + 1))
            echo "    ⚠ no node's consensus round advanced since the last poll (${STALL_POLLS} consecutive)"
        fi
    fi
    if [ -n "${PREV_ROUNDS}" ]; then
        local validators=() exempt=() i node validator_json exempt_json stalled
        for i in "${!INSTANCE_NAMES[@]}"; do
            [ "${NODE_ROLES[$i]}" != validator ] || validators+=("${INSTANCE_NAMES[$i]}")
        done
        if [ "${RUN_DID_KILL}" -eq 1 ] && [ "${RUN_DID_BACK}" -eq 0 ]; then
            exempt+=("${INSTANCE_NAMES[$CHAOS_KILL_IDX]}")
        fi
        if [ "${RUN_DID_PAUSE}" -eq 1 ] && [ "${RUN_DID_UNPAUSE}" -eq 0 ]; then
            exempt+=("${INSTANCE_NAMES[$BENCH_LAG_IDX]}")
        fi
        validator_json="$(printf '%s\n' "${validators[@]-}" | jq -Rsc 'split("\n") | map(select(length > 0))')"
        exempt_json="$(printf '%s\n' "${exempt[@]-}" | jq -Rsc 'split("\n") | map(select(length > 0))')"
        NODE_STALL_COUNTS="$(bench_node_stall_counts "${PREV_ROUNDS}" "${cur}" "${NODE_STALL_COUNTS}" "${validator_json}" "${exempt_json}")"
        if [ "${adv:-0}" -gt 0 ] && [ "${done_all}" -eq 0 ]; then
            stalled="$(printf '%s' "${NODE_STALL_COUNTS}" | jq -r 'to_entries[] | select(.value >= 2) | .key')"
            while IFS= read -r node; do
                [ -n "${node}" ] || continue
                for i in "${!INSTANCE_NAMES[@]}"; do
                    [ "${INSTANCE_NAMES[$i]}" != "${node}" ] || save_log_first "${i}" stalled
                done
                record_abort "node-stalled" "${node}" "unchanged epoch/round in two consecutive polls while peers advance"
            done <<< "${stalled}"
        fi
    fi
    PREV_ROUNDS="${cur}"
    if [ "${STALL_POLLS}" -ge 2 ] && [ $(( now - LAST_ADVANCE_TS )) -gt "${BENCH_ABORT_STALL_SECS}" ] && [ "${done_all}" -eq 0 ]; then
        record_abort "quorum-lost" "fleet" "no node's tn_primary_round advanced in ${STALL_POLLS} consecutive polls ($(( now - LAST_ADVANCE_TS ))s)"
    fi
}

# prom_get <json|""> <node> <absent> — the node's value; "?" when the query failed ("").
prom_get() { if [ -z "$1" ]; then printf '?'; else printf '%s' "$1" | jq -r --arg n "$2" --arg d "$3" '.[$n] // $d'; fi; }

# node_health_check <now> — per-node warnings from Prometheus; they inform, never abort: a
# validator whose tn_node_mode is not cvv_active (the observer's own mode is expected) and any
# node with > 20 failed batch reports in 5 min. From the lag unpause on, one line for the lag
# target every poll. No failure series is normal (the counter appears on its first failure).
node_health_check() {
    local l="${BENCH_PROM_NETWORK_LABEL}" modes fails failed="" i inst mode nf
    modes="$(bench_prom_query "tn_node_mode{network=\"${l}\"} == 1" 2>/dev/null \
        | jq -c 'select(.status == "success") | [.data.result[] | {key: .metric.node, value: (.metric.mode // "?")}] | from_entries' 2>/dev/null || true)"
    fails="$(bench_prom_query "sum by (node) (increase(tn_batch_builder_seal_failures_total{network=\"${l}\",reason=\"failed_to_report\"}[5m]))" 2>/dev/null \
        | jq -c 'select(.status == "success") | [.data.result[] | {key: .metric.node, value: (.value[1] | tonumber | round)}] | from_entries' 2>/dev/null || true)"
    if [ -z "${modes}" ] || [ "${modes}" = "{}" ]; then modes=""; failed="node mode"; fi
    [ -n "${fails}" ] || failed="${failed:+${failed} + }failed reports"
    [ -z "${failed}" ] || echo "    node health: Prometheus query failed or empty (${failed}) — no warning from it this poll"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        mode="$(prom_get "${modes}" "${inst}" absent)"; nf="$(prom_get "${fails}" "${inst}" 0)"
        if [ -n "${modes}" ] && [ "${NODE_ROLES[$i]}" = "validator" ] && [ "${mode}" != "cvv_active" ]; then
            echo "    ⚠ ${inst}: node mode ${mode}, not cvv_active"
        fi
        case "${nf}" in ''|*[!0-9]*) ;; *) [ "${nf}" -le 20 ] || echo "    ⚠ ${inst}: ${nf} failed batch reports in 5 min" ;; esac
    done
    if [ "${LAG_UNPAUSE_TS}" -gt 0 ]; then
        inst="${INSTANCE_NAMES[$BENCH_LAG_IDX]}"
        echo "    lag target ${inst}: mode=$(prom_get "${modes}" "${inst}" absent) failed_reports_5m=$(prom_get "${fails}" "${inst}" 0)," \
            "$(( $1 - LAG_UNPAUSE_TS ))s after the unpause$([ "${RUN_DID_UNPAUSE}" -eq 1 ] || echo ' (NOT confirmed — may still be paused)')"
    fi
    return 0
}

# poll_blasters — refresh DONE_LINE[]; returns 0 iff every blaster has reported.
poll_blasters() {
    local k name all=0
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        if [ -z "${DONE_LINE[k]:-}" ]; then
            name="$(blaster_name "$k")"
            DONE_LINE[k]="$(bench_serial_last "${name}" "${ZONES[$k]}" "BENCH_BLAST_DONE rc=" || true)"
            [ -n "${DONE_LINE[k]}" ] && echo "    ${name}: $(printf '%s' "${DONE_LINE[k]}" | sed 's/.*BENCH_BLAST_DONE/BENCH_BLAST_DONE/')"
        fi
        [ -n "${DONE_LINE[k]}" ] || all=1
    done
    return "${all}"
}

# settle_blasters — copy this index's bucket prefix, then delete each blaster whose results are safe.
settle_blasters() {
    local k
    copy_prefix "$(bucket_prefix blasters)" blasters || true
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        settle_load_vm "$(blaster_name "$k")" "${ZONES[$k]}" blasters "${DONE_LINE[k]:-}" BENCH_BLAST_DONE
    done
}

# exit_relay — the output path of on_run_exit. Its stdout is the stderr the cleanup started with
# (the output copy, or the terminal). Each line read goes there; from the first line that cannot
# be written, that line and the rest go to a new logs/blast-exit-<UTC>.log, named with the stamp
# of this invocation's blast-run-<UTC>.log, or nowhere when that file cannot be made. HUP INT TERM
# PIPE are ignored and no failed write ends the loop, so the relay stops only at EOF, once the
# script and every child holding the pipe have exited. There is no $(...) here: bash 3.2 keeps a
# failed write in its stdout buffer, and a subshell would flush it into its own output.
exit_relay() {
    trap '' HUP INT TERM PIPE
    exec >&2 2> /dev/null
    local line to=out base f n=0
    while IFS= read -r line || [ -n "${line}" ]; do
        printf '%s\n' "${line}" && continue
        [ "${to}" = out ] || continue                  # the fallback failed too: drop the line
        to="fallback"
        exec > /dev/null; printf '%s' ''               # discard the failed write bash 3.2 still buffers
        f="${BENCH_RESULTS_DIR}/logs/blast-exit-${BLAST_LOG##*-}"; base="${f%.log}"
        until [ -n "${BLAST_LOG}" ] && ( set -C; : > "${f}" ); do
            n=$((n + 1)); f="${base}-${n}.log"
            [ "${n}" -lt 5 ] || { f=/dev/null; break; }
        done
        exec >> "${f}"
        [ "${f}" = /dev/null ] || date -u "+# benchmark-blast.sh run (pid $$): its exit cleanup lost its output copy or terminal at %H:%M:%SZ; the rest of that output follows"
        printf '%s\n' "${line}"
    done
}

# exit_step <what> <cmd...> — one step of on_run_exit: run it, then print its outcome and note
# it in the manifest (when the manifest can be written). Always 0, so the next step runs.
exit_step() {
    local what="$1" rc=0 outcome=ok; shift
    "$@" || rc=$?
    if [ "${rc}" -eq 0 ]; then echo "    ✓ exit cleanup ${what}: done" >&2
    else outcome="FAILED rc=${rc}"; echo "❌ exit cleanup ${what}: FAILED (rc=${rc})" >&2; fi
    bench_manifest_note "exit cleanup $(bench_now_iso): ${what}: ${outcome}" || true
    return 0
}

exit_restart_v05() { # the owed restart; the ssh rc, with the command to run by hand, when not confirmed
    chaos_restart_v05 "owed restart, performed by the EXIT trap" || return "${CHAOS_RC}"
}

# delete_unstarted_blasters — before BENCH_START_AT the blasters hold no results, and left alone
# they would start blasting unwatched at that time. 1 when a delete failed.
delete_unstarted_blasters() {
    local k failed=0
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        [ -z "$(bench_instance_json "$(blaster_name "$k")" "${ZONES[$k]}")" ] || delete_vms "${ZONES[$k]}" "$(blaster_name "$k")" || failed=1
    done
    return "${failed}"
}

wait_blasters_done() { # <secs> — poll every 30 s until each blaster reported; 1 when <secs> ran out first
    local waited=0
    until poll_blasters; do
        [ "${waited}" -lt "$1" ] || return 1
        sleep 30; waited=$((waited + 30))
    done
}

# on_run_exit — EXIT trap for `run`: an exit anywhere (bench_die, set -e, Ctrl-C, TERM, a closed
# terminal, a lost output copy) between create and completion must not leave the lag target
# paused, bench-validator-05 stopped or blasters unwatched. The most harmful state goes first:
# (a) unpause, (b) restart v05, (c) stop the blasters, or delete them before their start time,
# (d) the abort record, the wait for their results, the copy and the deletes. A failed step
# never skips the next one.
on_run_exit() {
    local rc=$? started=1 wait_note=""
    trap - EXIT
    # Nothing may cut the cleanup short. INT TERM HUP PIPE stay ignored until the exit, and each
    # ssh and gcloud it starts inherits that, except gcloud compute ssh, which installs its own INT
    # and TERM handlers: a second signal can end the ssh in flight, so each ssh step gets 3 tries
    # (try_up_to). set -e and set -u are off.
    trap '' INT TERM HUP PIPE
    set +eu
    # From here every write, the cleanup's own and its children's, goes into exit_relay's pipe,
    # which cannot die. The output copy and the terminal can: a write into a dead pipe fails,
    # and gcloud or ssh may give up on it before they act. A hung-up terminal is not stdin either.
    # bash 3.2 keeps a write that failed in its stdout buffer, and the first $(...) would flush it
    # into its value: the printf sends it into the relay now.
    exec < /dev/null > >(exit_relay) 2>&1
    printf '%s' ''
    [ "$(bench_now_unix)" -lt "${RUN_START_AT}" ] && started=0   # unknown time: started, so nothing is deleted
    if [ "${RUN_FINISHED}" -eq 0 ]; then
        [ "${RUN_CREATED}" -eq 0 ] || [ "${KEEP}" -eq 1 ] || [ "${started}" -eq 0 ] \
            || wait_note=" up to ${BENCH_TRAP_WAIT_SECS}s of waiting for the blasters' results plus"
        echo "❌ run interrupted (exit ${rc}) — restoring the fleet and securing results. This takes${wait_note} a few minutes of ssh and gcloud calls; INT, TERM and HUP are ignored until it ends (kill -9 $$ stops it and leaves the fleet as it is)" >&2
    fi
    # (a) the lag target: paused, it falls further behind every second
    if [ "${RUN_DID_PAUSE}" -eq 1 ] && [ "${RUN_DID_UNPAUSE}" -eq 0 ]; then
        exit_step "(a) unpause ${INSTANCE_NAMES[$BENCH_LAG_IDX]}" try_up_to 3 lag_unpause "owed unpause, performed by the EXIT trap"
    fi
    [ "${RUN_FINISHED}" -eq 1 ] && exit "${rc}"
    # (b) the validator the chaos step killed
    if [ "${RUN_DID_KILL}" -eq 1 ] && [ "${RUN_DID_BACK}" -eq 0 ]; then
        exit_step "(b) restart ${INSTANCE_NAMES[$CHAOS_KILL_IDX]}" try_up_to 3 exit_restart_v05
    fi
    # (c) the blasters
    if [ "${RUN_CREATED}" -eq 1 ]; then
        if [ "${KEEP}" -eq 1 ]; then
            echo "    --keep: blasters left running; later: benchmark-blast.sh collect/delete" >&2
            bench_manifest_note "exit cleanup $(bench_now_iso): (c) --keep: blasters left running" || true
        elif [ "${started}" -eq 0 ]; then
            echo "    blast had not started — deleting the blasters (no results to lose)" >&2
            exit_step "(c) delete the blasters before their start time" delete_unstarted_blasters
        elif [ "${RUN_STOPPED}" -eq 0 ]; then
            exit_step "(c) stop the blasters (docker stop txgen)" stop_blasters 3
        fi
    fi
    # (d) everything else
    record_abort "interrupted" "operator" "benchmark-blast.sh run exited rc=${rc} before completing"
    if [ "${RUN_CREATED}" -eq 1 ] && [ "${KEEP}" -eq 0 ] && [ "${started}" -eq 1 ]; then
        exit_step "(d) wait up to ${BENCH_TRAP_WAIT_SECS}s for every blaster's done marker" wait_blasters_done "${BENCH_TRAP_WAIT_SECS}"
        exit_step "(d) copy the results, delete each blaster whose results are safe" settle_blasters
    fi
    echo "    exit cleanup finished — exit ${rc}" >&2
    exit "${rc}"
}

do_run() {
    preflight
    local k name zone urls start now start_at mixed_start deadline
    [ -n "${OBSERVER_IDX}" ] || bench_die "no observer in NODE_ROLES"
    now="$(bench_now_unix)"
    start_at=$(( now + BENCH_START_DELAY_SECS ))
    RUN_START_AT="${start_at}"
    mixed_start=$(( start_at + BENCH_PREAMBLE_SECS + BENCH_WARMUP_SECS ))
    deadline=$(( mixed_start + BENCH_DURATION_SECS + BENCH_COOLDOWN_SECS + 600 ))
    echo ">>> run ${BENCH_RUN_ID} index ${BENCH_RUN_INDEX}: ${VAL_COUNT} blasters x ${BENCH_SENDERS} senders, start_at $(bench_iso_from_unix "${start_at}")"
    echo "    phases (planned): preamble ${BENCH_PREAMBLE_SECS}s, warmup ${BENCH_WARMUP_SECS}s, mixed ${BENCH_DURATION_SECS}s, cooldown ${BENCH_COOLDOWN_SECS}s; wait deadline $(bench_iso_from_unix "${deadline}")"
    local chaos_on="${BENCH_CHAOS:-1}"
    local t_kill=$(( mixed_start + BENCH_CHAOS_KILL_AT_SECS )) t_back=$(( mixed_start + BENCH_CHAOS_BACK_AT_SECS )) t_obs=$(( mixed_start + BENCH_CHAOS_OBS_AT_SECS ))
    local recovery_schedule="" boundary_record=""
    if [ "${chaos_on}" = "1" ]; then
        case "${BENCH_CHAOS_TIMING}" in
            epoch)
                if [ "${BENCH_APPLY}" = "1" ]; then
                    bench_require_tools python3 cast || exit 1
                    bench_tunnel_up || bench_die "cannot measure the epoch boundary"
                    recovery_schedule="$(python3 "${DIR}/recovery-schedule.py" --rpc-url "${RPC_URL}" \
                        --earliest-kill "$((mixed_start + BENCH_CHAOS_MIN_LOAD_SECS))" \
                        --before-close "${BENCH_CHAOS_BEFORE_CLOSE_SECS}" --downtime "${BENCH_CHAOS_DOWNTIME_SECS}")" \
                        || bench_die "cannot measure the epoch boundary"
                    t_kill="$(printf '%s' "${recovery_schedule}" | jq -r .kill_unix)"
                    t_back="$(printf '%s' "${recovery_schedule}" | jq -r .restart_unix)"
                    t_obs=$((t_back + BENCH_CHAOS_OBS_AFTER_BACK_SECS))
                    [ "${t_back}" -lt "$((mixed_start + BENCH_DURATION_SECS + BENCH_COOLDOWN_SECS))" ] \
                        || bench_die "measured restart falls after the workload; extend BENCH_DURATION_SECS"
                    bench_manifest_jq --argjson s "${recovery_schedule}" '.chaos_schedule = $s'
                else
                    echo "    epoch timing: --yes reads the actual registry and boundary before scheduling"
                fi
                ;;
            mixed) ;;
            *) bench_die "BENCH_CHAOS_TIMING must be epoch or mixed" ;;
        esac
    fi
    if [ "${chaos_on}" = "1" ]; then
        if [ "${BENCH_CHAOS_TIMING}" = epoch ] && [ "${BENCH_APPLY}" != 1 ]; then
            echo "    chaos: epoch-relative kill/restart times require the measured RPC snapshot"
        else
            echo "    chaos: $(bench_iso_from_unix "${t_kill}") kill -9 ${INSTANCE_NAMES[$CHAOS_KILL_IDX]}; $(bench_iso_from_unix "${t_back}") start it; $(bench_iso_from_unix "${t_obs}") restart ${INSTANCE_NAMES[$OBSERVER_IDX]}"
        fi
    else
        echo "    chaos: disabled (BENCH_CHAOS=0)"
    fi
    local lag_on="${BENCH_LAG_INJECT:-0}" lag_inst="${INSTANCE_NAMES[$BENCH_LAG_IDX]}" lag_left
    local t_pause=$(( mixed_start + BENCH_LAG_AT_SECS )) t_unpause=$(( mixed_start + BENCH_LAG_AT_SECS + BENCH_LAG_PAUSE_SECS ))
    if [ "${lag_on}" = "1" ]; then
        lag_left=$(( BENCH_DURATION_SECS - BENCH_LAG_AT_SECS - BENCH_LAG_PAUSE_SECS ))
        echo "    lag: $(bench_iso_from_unix "${t_pause}") (mixed+${BENCH_LAG_AT_SECS}s) docker pause ${lag_inst}; $(bench_iso_from_unix "${t_unpause}") (mixed+$(( BENCH_LAG_AT_SECS + BENCH_LAG_PAUSE_SECS ))s) unpause it;" \
            "mixed-phase load continues $([ "${lag_left}" -ge 0 ] && echo "${lag_left}s" || echo "0s (the mixed phase ends $(( -lag_left ))s before)") after the unpause"
        [ "${lag_left}" -ge 900 ] || bench_warn "lag: only $(( lag_left > 0 ? lag_left : 0 ))s of mixed-phase load after the unpause (< 900 s) — too little to watch ${lag_inst} catch up under load; lower BENCH_LAG_AT_SECS/BENCH_LAG_PAUSE_SECS or raise BENCH_DURATION_SECS"
    else
        echo "    lag injection: off (BENCH_LAG_INJECT=0)"
    fi
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"
        [ -z "$(bench_instance_json "${name}" "${ZONES[$k]}")" ] || bench_die "${name} already exists — benchmark-blast.sh delete --yes first"
    done
    archive_prev_blast
    record_blast "${start_at}"

    # --- create the blasters in parallel ---
    gcloud auth print-access-token >/dev/null
    local pids=() names=() logs=()
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/logs"
    if [ "${BENCH_APPLY}" = "1" ]; then
        RUN_CREATED=1                      # from here on the EXIT trap owns cleanup
        trap on_run_exit EXIT
        # INT and TERM exit 130 as before; HUP (a closed terminal) 129 and PIPE (the output copy
        # is gone) 141, so the EXIT trap sees why. Each ignores PIPE before it exits: bash may
        # write a job notice on its way out, and a SIGPIPE from that ends bash 5 without the
        # EXIT trap.
        trap 'trap "" PIPE; exit 130' INT TERM
        trap 'trap "" PIPE; exit 129' HUP
        trap 'trap "" PIPE; exit 141' PIPE
    fi
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"; zone="${ZONES[$k]}"
        [ "${NODE_ROLES[$k]}" = "validator" ] || bench_die "index ${k} is not a validator"
        urls="$(node_url "$k")"
        start=$(( k * BENCH_SENDERS + BENCH_RUN_INDEX * 100000 ))
        echo ">>> ${name} (${zone}) -> ${urls} senders ${BENCH_SENDERS}@${start}"
        if [ "${BENCH_APPLY}" = "1" ]; then
            create_vm "${name}" "${zone}" blast "${urls}" "${BENCH_SENDERS}" "${start}" "${start_at}" \
                > "${BENCH_RESULTS_DIR}/logs/create-${name}.log" 2>&1 &
            pids+=("$!"); names+=("${name}"); logs+=("${BENCH_RESULTS_DIR}/logs/create-${name}.log")
        else
            create_vm "${name}" "${zone}" blast "${urls}" "${BENCH_SENDERS}" "${start}" "${start_at}"
        fi
    done
    [ "${BENCH_APPLY}" = "1" ] || { echo "DRY RUN — re-run with --yes."; return 0; }
    local failed=0 j
    for j in "${!pids[@]}"; do
        if wait "${pids[$j]}"; then echo "    ✓ created ${names[$j]}"; else echo "❌ create ${names[$j]} failed:" >&2; tail -5 "${logs[$j]}" >&2; failed=1; fi
    done
    [ "${failed}" -eq 0 ] || bench_die "blaster creation failed — clean up with: benchmark/benchmark-blast.sh delete --yes"
    for k in $(seq 0 $((VAL_COUNT - 1))); do assert_load_vm "$(blaster_name "$k")" "${ZONES[$k]}"; done

    # --- manifest: planned phases + blasters ---
    local p0="${start_at}" p1=$(( start_at + BENCH_PREAMBLE_SECS )) p2="${mixed_start}" p3=$(( mixed_start + BENCH_DURATION_SECS )) p4=$(( mixed_start + BENCH_DURATION_SECS + BENCH_COOLDOWN_SECS ))
    bench_manifest_ts blast_start_at "$(bench_iso_from_unix "${start_at}")"
    bench_manifest_jq --arg a "$(bench_iso_from_unix "${p0}")" --arg b "$(bench_iso_from_unix "${p1}")" \
        --arg c "$(bench_iso_from_unix "${p2}")" --arg d "$(bench_iso_from_unix "${p3}")" --arg e "$(bench_iso_from_unix "${p4}")" \
        '.phases = [{name:"preamble",start:$a,end:$b},{name:"warmup",start:$b,end:$c},{name:"mixed",start:$c,end:$d},{name:"cooldown",start:$d,end:$e}]
         | .notes += ["phases are PLANNED from BENCH_START_AT + configured durations; the per-blaster tn-blast/v2 run.phases are authoritative"]'
    local bl="[]" id
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"
        id="$(gcloud compute instances describe "${name}" --zone="${ZONES[$k]}" --project="${PROJECT_ID}" --format='value(id)' 2>/dev/null || true)"
        bl="$(printf '%s' "${bl}" | jq --arg n "${name}" --arg z "${ZONES[$k]}" --arg id "${id}" --arg t "${INSTANCE_NAMES[$k]}" \
            --arg u "$(sed 's/^[^=]*=//' "${BENCH_RESULTS_DIR}/meta/${name}/NODE_URLS")" \
            --arg s "$(( k * BENCH_SENDERS + BENCH_RUN_INDEX * 100000 ))" --arg c "${BENCH_SENDERS}" \
            '. + [{name:$n, zone:$z, instance_id:$id, target:$t, node_url:$u, sender_start:($s|tonumber), senders:($c|tonumber), result:("blasters/" + $n + ".json"), rc:null}]')"
    done
    bench_manifest_jq --argjson b "${bl}" '.blasters = $b'

    # --- watch loop: chaos + abort watchers + done markers ---
    local next_poll=$(( start_at + 60 )) all_done=0 sleep_for target
    local kill_blaster; kill_blaster="$(blaster_name "${CHAOS_KILL_IDX}")"
    LAST_ADVANCE_TS="${start_at}"
    while :; do
        now="$(bench_now_unix)"
        if [ "${chaos_on}" = "1" ] && [ -z "${ABORTED}" ] && [ "${RUN_DID_KILL}" -eq 0 ] && [ "${now}" -ge "${t_kill}" ]; then
            save_log_first "${CHAOS_KILL_IDX}" pre-kill
            # A restart is owed from here on, even if the kill reports a failure: an exit while its
            # ssh is in flight may follow a kill that landed. When it did not land, the owed restart
            # is harmless: `systemctl start` on an active unit does nothing, and is-active passes.
            RUN_DID_KILL=1
            chaos_do "${CHAOS_KILL_IDX}" "sudo docker kill -s KILL telcoin && sudo systemctl stop telcoin && { systemctl is-active telcoin || true; }" \
                "docker kill -s KILL telcoin" "restart across the epoch boundary; systemctl stop holds it down (unit has Restart=on-failure). ${kill_blaster} targets ONLY this node, so its sends fail for the outage by design; the generator resends on connection errors"
            if [ "${BENCH_CHAOS_TIMING}" = epoch ]; then
                t_back=$(( $(bench_now_unix) + BENCH_CHAOS_DOWNTIME_SECS ))
                t_obs=$(( t_back + BENCH_CHAOS_OBS_AFTER_BACK_SECS ))
                bench_manifest_jq --argjson due "${t_back}" '.chaos_restart_due_unix = $due'
            fi
            bench_manifest_note "blaster-05-outage: ${kill_blaster}'s only RPC target ${INSTANCE_NAMES[$CHAOS_KILL_IDX]} is down from $(bench_now_iso) for ~$(( t_back - t_kill ))s (chaos); its connection errors/resends in that window are the chaos, not a blaster fault" || true
        fi
        # The restart is owed even after an abort: never leave v05 down. Not confirmed, it is tried
        # again at the next poll (t_back moves there), and at each one after that until it is.
        if [ "${RUN_DID_KILL}" -eq 1 ] && [ "${RUN_DID_BACK}" -eq 0 ] && { [ "${now}" -ge "${t_back}" ] || [ -n "${ABORTED}" ]; }; then
            if [ -n "${recovery_schedule}" ] && [ -z "${boundary_record}" ]; then
                boundary_record="$(python3 "${DIR}/recovery-schedule.py" --rpc-url "${RPC_URL}" \
                    --epoch "$(( $(printf '%s' "${recovery_schedule}" | jq -r .closing_epoch) + 1 ))")" || true
                [ -z "${boundary_record}" ] || bench_manifest_jq --argjson b "${boundary_record}" '.chaos_boundary = $b'
            fi
            chaos_restart_v05 "docker start is impossible: the unit runs docker run --rm" \
                || t_back=$(( next_poll > now ? next_poll : now + BENCH_POLL_SECS ))
        fi
        if [ "${chaos_on}" = "1" ] && [ -z "${ABORTED}" ] && [ "${RUN_DID_OBS}" -eq 0 ] && [ "${now}" -ge "${t_obs}" ]; then
            save_log_first "${OBSERVER_IDX}" pre-restart
            chaos_do "${OBSERVER_IDX}" "sudo systemctl restart telcoin && systemctl is-active telcoin" "systemctl restart telcoin" "observer restart"
            RUN_DID_OBS=1
        fi
        if [ "${lag_on}" = "1" ] && [ -z "${ABORTED}" ] && [ "${RUN_DID_PAUSE}" -eq 0 ] && [ "${now}" -ge "${t_pause}" ]; then
            save_log_first "${BENCH_LAG_IDX}" pre-pause
            RUN_DID_PAUSE=1               # an unpause is owed from here on, even if the pause reports a failure
            t_unpause=$(( $(bench_now_unix) + BENCH_LAG_PAUSE_SECS ))
            chaos_do "${BENCH_LAG_IDX}" "${LAG_PAUSE_CMD}" "lag-pause" "paused ${BENCH_LAG_PAUSE_SECS}s so it falls behind under load, then it must catch up. $(blaster_name "${BENCH_LAG_IDX}") targets ONLY this node, so its sends stall for the pause by design"
        fi
        # The unpause is owed even after an abort (t_unpause is pulled forward): never leave it paused.
        if [ "${RUN_DID_PAUSE}" -eq 1 ] && [ "${RUN_DID_UNPAUSE}" -eq 0 ] && [ "${now}" -ge "${t_unpause}" ]; then
            lag_unpause "scheduled unpause" || t_unpause=$(( $(bench_now_unix) + 60 ))   # retry in a minute
        fi

        if [ "${now}" -ge "${next_poll}" ]; then
            bench_log "poll: blasters + node status + obs memory"
            if poll_blasters; then all_done=1; else all_done=0; fi
            # nodes: disk + FatalDBFailure from BENCH_STATUS (node-sampler.sh, serial console);
            # block= is informational only.
            local line inst pct fatal blk
            for k in "${!INSTANCE_NAMES[@]}"; do
                inst="${INSTANCE_NAMES[$k]}"
                line="$(bench_serial_last "${inst}" "${ZONES[$k]}" "BENCH_STATUS " || true)"
                [ -n "${line}" ] || { echo "    ${inst}: no BENCH_STATUS yet"; continue; }
                pct="$(status_field "${line}" root_used_pct)"; fatal="$(status_field "${line}" fatal_db)"
                blk="$(status_field "${line}" block)"
                echo "    ${inst}: root=${pct:-?}% fatal_db=${fatal:-?} block=${blk:-?}"
                if [ -n "${pct}" ] && [ "${pct}" -gt "${BENCH_ABORT_DISK_PCT}" ]; then record_abort "disk-full" "${inst}" "root disk ${pct}% > ${BENCH_ABORT_DISK_PCT}%"; fi
                if [ -n "${fatal}" ] && [ "${fatal}" -gt 0 ]; then record_abort "batch-cache-cliff" "${inst}" "FatalDBFailure x${fatal} in docker logs telcoin — batch-cache cliff, NOT a hardware limit"; fi
            done
            round_stall_check "${now}" "${all_done}"
            node_health_check "${now}" || true
            local mem; mem="$(bench_obs_mem_pct || true)"
            echo "    obs-devnet memory: ${mem:-n/a}%"
            if [ -n "${mem}" ] && awk -v m="${mem}" -v t="${BENCH_ABORT_OBS_MEM_PCT}" 'BEGIN{exit !(m>t)}'; then
                record_abort "obs-memory" "${OBS_INSTANCE_NAME}" "obs-devnet memory ${mem}% > ${BENCH_ABORT_OBS_MEM_PCT}%"
            fi
            next_poll=$(( now + BENCH_POLL_SECS ))
        fi

        if [ -n "${ABORTED}" ] && [ "${RUN_STOPPED}" -eq 0 ]; then
            bench_log "stopping blasters (docker stop txgen) after abort: ${ABORTED}"
            stop_blasters || true
            deadline=$(( now + 600 ))
            next_poll=$(( now + BENCH_POLL_SECS ))
            t_unpause=$(( t_unpause < now ? t_unpause : now ))    # an owed unpause runs on the next pass
        fi
        [ "${all_done}" -eq 1 ] && { bench_log "all blasters reported BENCH_BLAST_DONE"; break; }
        [ "${now}" -lt "${deadline}" ] || { bench_warn "deadline reached before every blaster finished"; break; }

        target="${next_poll}"
        if [ "${chaos_on}" = "1" ]; then
            [ "${RUN_DID_KILL}" -eq 0 ] && [ "${t_kill}" -lt "${target}" ] && target="${t_kill}"
            [ "${RUN_DID_BACK}" -eq 0 ] && [ "${RUN_DID_KILL}" -eq 1 ] && [ "${t_back}" -lt "${target}" ] && target="${t_back}"
            [ "${RUN_DID_OBS}" -eq 0 ] && [ "${t_obs}" -lt "${target}" ] && target="${t_obs}"
        fi
        [ "${lag_on}" = "1" ] && [ "${RUN_DID_PAUSE}" -eq 0 ] && [ "${t_pause}" -lt "${target}" ] && target="${t_pause}"
        [ "${RUN_DID_PAUSE}" -eq 1 ] && [ "${RUN_DID_UNPAUSE}" -eq 0 ] && [ "${t_unpause}" -lt "${target}" ] && target="${t_unpause}"
        sleep_for=$(( target - $(bench_now_unix) )); [ "${sleep_for}" -ge 5 ] || sleep_for=5
        sleep "${sleep_for}"
    done

    # The loop can end (all done, abort, deadline) before the scheduled unpause or restart, or while
    # the restart still fails: each is owed now. A normal end clears the EXIT trap, so the last
    # tries before the run exits stand in for its steps (a) and (b).
    [ "${RUN_DID_PAUSE}" -eq 0 ] || [ "${RUN_DID_UNPAUSE}" -eq 1 ] || lag_unpause "owed unpause at the end of the watch" || true
    [ "${RUN_DID_KILL}" -eq 0 ] || [ "${RUN_DID_BACK}" -eq 1 ] || chaos_restart_v05 "owed restart at the end of the watch" || true

    # --- results ---
    bench_manifest_ts blast_end
    local rc_k bad=0
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        rc_k="$(printf '%s\n' "${DONE_LINE[k]:-}" | marker_rc BENCH_BLAST_DONE)"
        [ "${rc_k:-x}" = "0" ] && [ "$(printf '%s\n' "${DONE_LINE[k]:-}" | marker_reason BENCH_BLAST_DONE)" = "ok" ] || bad=1
        [ -n "${rc_k}" ] || continue
        bench_manifest_jq --arg n "$(blaster_name "$k")" --arg rc "${rc_k}" \
            '.blasters |= map(if .name == $n then .rc = ($rc|tonumber) else . end)'
    done
    settle_blasters
    [ "${RUN_DID_PAUSE}" -eq 0 ] || [ "${RUN_DID_UNPAUSE}" -eq 1 ] || lag_unpause "last try before the run exits" || true
    [ "${RUN_DID_KILL}" -eq 0 ] || [ "${RUN_DID_BACK}" -eq 1 ] || chaos_restart_v05 "last try before the run exits" || true
    RUN_FINISHED=1
    trap - EXIT INT TERM HUP PIPE
    if [ -n "${ABORTED}" ] || [ "${bad}" -ne 0 ]; then
        echo "❌ run finished with abort='${ABORTED}' / a blaster not at rc=0 reason=ok — see ${BENCH_RESULTS_DIR}" >&2
        exit 1
    fi
    echo "    ✓ run complete: ${BENCH_RESULTS_DIR}/blasters/"
}

# ================================ collect ============================================
do_collect() {
    local i inst
    echo ">>> collect ${BENCH_RUN_ID} -> ${BENCH_RESULTS_DIR}"
    bench_manifest_ts collect_start
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/sampler"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo "    ${inst}: sampler CSV (IAP scp)"
        bench_run bench_iap_scp_down "${inst}" "${ZONES[$i]}" "/var/lib/bench-sampler/${inst}.csv" "${BENCH_RESULTS_DIR}/sampler/${inst}.csv" \
            || bench_warn "sampler CSV from ${inst} not copied"
        bench_run bench_iap_scp_down "${inst}" "${ZONES[$i]}" "/var/lib/bench-sampler/${inst}.epochs.txt" "${BENCH_RESULTS_DIR}/sampler/${inst}.epochs.txt" \
            || bench_warn "epoch inventory from ${inst} not copied"
    done
    copy_prefix "$(recorded_prefix blast blasters)" blasters || true
    copy_prefix "$(recorded_prefix fund funder)" funder || true
}

# ================================ delete / status ====================================
load_vms_json() {
    gcloud compute instances list --project="${PROJECT_ID}" --filter="labels.benchmark=1 AND name~'^bench-(blaster|funder)'" --format=json 2>/dev/null || echo '[]'
}

do_delete() {
    local rows z names
    rows="$(load_vms_json | jq -r '.[] | select(.labels.benchmark == "1") | (.zone|split("/")|last) + " " + .name')"
    [ -n "${rows}" ] || { echo ">>> no load VMs"; return 0; }
    for z in $(printf '%s\n' "${rows}" | awk '{print $1}' | sort -u); do
        names="$(printf '%s\n' "${rows}" | awk -v z="${z}" '$1 == z {print $2}' | tr '\n' ' ')"
        # shellcheck disable=SC2086  # names are ^bench- instance names (no spaces)
        delete_vms "${z}" ${names}
    done
}

do_status() {
    local rows z n
    rows="$(load_vms_json | jq -r '.[] | (.zone|split("/")|last) + " " + .name + " " + .status')"
    if [ -z "${rows}" ]; then echo ">>> no load VMs"; else
        while read -r z n st; do
            echo "    ${n} (${z}) ${st}: $(bench_serial_last "${n}" "${z}" "_DONE rc=")"
        done <<< "${rows}"
    fi
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        [ -n "$(bench_instance_json "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}")" ] || continue
        echo "    ${INSTANCE_NAMES[$i]}: $(bench_serial_last "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "BENCH_STATUS ")"
    done
}

start_blast_log
case "${ACTION}" in
    fund)    [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"; do_fund ;;
    run)     [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"; do_run ;;
    collect) do_collect ;;
    delete)  do_delete ;;
    status)  do_status ;;
esac
