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
#            the chaos schedule. Each chaos action is staged: one IAP session opened
#            BENCH_CHAOS_STAGE_SECS early starts saving the container log in the background, waits
#            on the node's clock and runs the action on time whether or not the save has finished
#            (then waits up to BENCH_CHAOS_SAVE_WAIT_SECS for it); a poll due within
#            BENCH_CHAOS_GUARD_SECS of it waits for it.
#            BENCH_LAG_INJECT=1 `docker pause`s bench-validator-03 (BENCH_LAG_IDX) at
#            mixed+BENCH_LAG_AT_SECS for BENCH_LAG_PAUSE_SECS, then unpauses it and reports its
#            node mode every poll while it catches up; the unpause is owed on any exit.
#            Before a container is killed, restarted or paused, its log is saved on the node.
#   collect  sampler CSVs from every bench node (IAP scp) into results/<run>/sampler/, and the
#            bucket prefixes of the blast and the funder output in results/<run>/ (manifest
#            .blast/.fund.bucket_prefix; without one, the old gs://<bucket>/<run>/blasters|funder/).
#            Then analysis/ (tools/block-rate.py; tools/cert-rate.py once node logs are pulled)
#            and results/<run>/INDEX.md + CHECKSUMS.sha256, both non-fatal.
#   delete   delete every bench-blaster-* / bench-funder VM of the benchmark (label-guarded).
#   status   list the load VMs and the latest serial markers (read-only).
#   chaos-stage-test --instance <node>
#            one staged chaos session against that live node with the harmless action `true`
#            (its container log is saved alongside): prints the node's BEGIN/END and the lateness.
#            Run it once against a live fleet before a blast relies on the staged path.
#
# Abort watchers (each sets manifest.abort and stops the blasters): any bench node's root
# disk > BENCH_ABORT_DISK_PCT, bench-obs memory > BENCH_ABORT_OBS_MEM_PCT, a FatalDBFailure
# in any node's telcoin log (recorded as "batch-cache-cliff" — the batch-cache defect, NOT a
# hardware limit), or no chain progress for > BENCH_ABORT_STALL_SECS (quorum lost). They read
# the nodes' BENCH_STATUS serial lines (node-sampler.sh), Cloud Monitoring and bench-obs's
# Prometheus (through the local forward `run --yes` opens first, bench_obs_require) — no IAP
# polling — every BENCH_POLL_SECS (>= 240 s, tasks/lessons.md IAP-throttling lesson).
#
# Usage: benchmark/benchmark-blast.sh {fund|run|collect|delete|status|chaos-stage-test} [--yes] [--keep]
#        [--run ID] [--instance NODE]
# Without --yes nothing is created, deleted or copied: the gcloud argv is printed instead.
# With --yes, a copy of everything printed goes to results/<run>/logs/blast-<action>-<UTC>.log.
#
# A second blast on the same fleet: `run` first moves the previous blast's outputs (blasters/,
# meta/bench-blaster-*, its create/run/collect logs, metrics.json) into
# results/<run>/blast-<its BENCH_RUN_INDEX>-<UTC>/ next to a copy of manifest.json, then resets
# the per-blast manifest keys. It refuses a BENCH_RUN_INDEX an earlier blast used (same
# senders): fund and run the second blast under a new one. The exception is a retry of an
# attempt that exited before its blasters' start time: allowed until 60 s before that time.
# `fund` under a new index first MOVES funder/ of the previous one into
# results/<run>/funder-<its index>-<UTC>/. Each index has its own bucket prefix
# (gs://<bucket>/<run>/index-<N>/), so no blast or fund reads another one's objects.
#
# Light-load arm (BENCH_LIGHT_LOAD=1; light_fund / light_run below): `fund` and `run` become a
# sequence of single-blast invocations of this script on one fleet, each under its own
# BENCH_RUN_INDEX (counting up from BENCH_RUN_INDEX, default 0) and therefore funded, archived and
# bucket-prefixed as above: one light blast per entry of BENCH_LIGHT_SENDERS (that many senders per
# blaster at the paired BENCH_LIGHT_WINDOWS entry, else BENCH_WINDOW; BENCH_LIGHT_WARMUP/DURATION/
# COOLDOWN_SECS; chaos and lag injection off), then the configured profile (BENCH_SENDERS at
# BENCH_WINDOW), then with BENCH_LIGHT_LOAD_AFTER=1 one more light blast like the first entry.
# `run` prints LIGHT_LOAD_START i=<index> senders=<n> window=<w> / LIGHT_LOAD_DONE i=<index> rc=<rc>
# around each light blast, appends manifest blasts[] {index, senders, window, chaos, started, ended,
# rc} per blast, stops at the first rc != 0 with the commands that finish the sequence by hand, and
# measures one node's unit-log growth in every blast (LOG_RATE, log_rate_check); a dry run prints
# its plan instead of the LIGHT_LOAD_* markers. The configured
# profile's outputs end in the usual places (blasters/, then the step-15 collect and metrics.json);
# every light blast is archived in results/<run>/blast-<index>-<UTC>/. The sequence's own output is
# logs/blast-light-<action>-<UTC>.log. BENCH_WINDOW (default 16) is the generator's --window: the
# load VMs get a WINDOW metadata key only when it differs from 16. BENCH_LANDINGS_SAMPLE > 0 adds a
# LANDINGS_SAMPLE key: the generator writes /out/landings-<label>.ndjson.gz, one row per N landings,
# which comes back into results/<run>/blasters/ with the rest of its /out (with it the generator's
# unlanded-<label>.ndjson.gz, the transactions still unlanded after the run).
#
# Bench 6. A light blast of the sequence (its child gets BENCH_BLAST_KIND=light) starts
# BENCH_LIGHT_START_DELAY_SECS after the announce, as given; any other blast keeps start_delay_secs's
# floor. BENCH_TAIL_SCAN_SECS > 0 adds a TAIL_SCAN_SECS key (the generator's --tail-scan-secs), recorded as
# .blast.tail_scan_secs; every wait for the done markers grows by done_wait_extra_secs. From the planned
# mixed end, completion is read from the bucket every BUCKET_CHECK_SECS (bucket_done_check); the
# blasters' deletes run in the background (await_deletes) and their disk relabels in parallel
# (assert_load_vms). Each blast records the nodes' pools at its start (.blast.pool_at_start), and once
# every blaster's result is in, .phases holds the blasters' real phases and .phases_planned the plan
# (record_real_phases). blasts[] entries carry kind, arm, phases (+ phases_planned) and pool_at_start.
# A `fund` or `run` started by hand (neither the deploy nor the sequence: blast_caller) appends
# manifest blast_runs[] {action: "fund"|"run", index: its BENCH_RUN_INDEX (the base of a light-load
# sequence), started, ended, rc, log: its output copy, relative to results/<run>/}; a hand `run` that
# ends rc 0 sets timestamps.step_14_done.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

ACTION=""; CONFIRM=0; KEEP=0; STAGE_INSTANCE=""
while [ $# -gt 0 ]; do
    case "$1" in
        fund|run|collect|delete|status|chaos-stage-test) ACTION="$1" ;;
        --yes) CONFIRM=1 ;;
        --keep) KEEP=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}" ;;
        --instance) STAGE_INSTANCE="${2:?--instance needs a node name}"; shift ;;
        --instance=*) STAGE_INSTANCE="${1#*=}" ;;
        -h|--help) sed -n '2,53p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1'" >&2; exit 1 ;;
    esac
    shift
done
[ -n "${ACTION}" ] || { echo "❌ missing action: fund | run | collect | delete | status | chaos-stage-test" >&2; exit 1; }
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
# Commit-stall note (commit_flat_check): rounds allowed over a stall's last BENCH_STALL_NOTE_SECS.
BENCH_STALL_NOTE_MAX_ROUNDS="${BENCH_STALL_NOTE_MAX_ROUNDS:-4}"
case "${BENCH_STALL_NOTE_MAX_ROUNDS}" in ''|*[!0-9]*) bench_die "BENCH_STALL_NOTE_MAX_ROUNDS='${BENCH_STALL_NOTE_MAX_ROUNDS}' must be a whole number" ;; esac
# A poll the guard lets through must end before the next action's session opens.
[ "${BENCH_CHAOS_STAGE_SECS}" -lt "${BENCH_CHAOS_GUARD_SECS}" ] \
    || bench_die "BENCH_CHAOS_STAGE_SECS=${BENCH_CHAOS_STAGE_SECS} must be below BENCH_CHAOS_GUARD_SECS=${BENCH_CHAOS_GUARD_SECS}"
# The kill's session may run BENCH_CHAOS_SAVE_WAIT_SECS past the kill (the log save); it must end
# before the restart's session opens BENCH_CHAOS_STAGE_SECS ahead of the restart.
case "${BENCH_CHAOS_SAVE_WAIT_SECS}" in ''|*[!0-9]*) bench_die "BENCH_CHAOS_SAVE_WAIT_SECS='${BENCH_CHAOS_SAVE_WAIT_SECS}' must be a whole number" ;; esac
case "${BENCH_CHAOS_REFRESH_SCHEDULE:-1}" in 0|1) ;; *) bench_die "BENCH_CHAOS_REFRESH_SCHEDULE='${BENCH_CHAOS_REFRESH_SCHEDULE}' must be 0 or 1" ;; esac
# The schedule refresh runs inside a poll the guard admitted: its RPC read plus that poll must end
# before the kill's session opens, so the read is bounded by BENCH_CHAOS_STAGE_SECS at most.
case "${BENCH_CHAOS_REFRESH_TIMEOUT_SECS:-20}" in ''|*[!0-9]*|0*) bench_die "BENCH_CHAOS_REFRESH_TIMEOUT_SECS='${BENCH_CHAOS_REFRESH_TIMEOUT_SECS}' must be a positive whole number" ;; esac
[ "${BENCH_CHAOS_REFRESH_TIMEOUT_SECS:-20}" -le "${BENCH_CHAOS_STAGE_SECS}" ] \
    || bench_die "BENCH_CHAOS_REFRESH_TIMEOUT_SECS=${BENCH_CHAOS_REFRESH_TIMEOUT_SECS} must not exceed BENCH_CHAOS_STAGE_SECS=${BENCH_CHAOS_STAGE_SECS}"
CHAOS_OUTAGE_SECS="${BENCH_CHAOS_DOWNTIME_SECS}"
[ "${BENCH_CHAOS_TIMING}" != mixed ] || CHAOS_OUTAGE_SECS=$(( BENCH_CHAOS_BACK_AT_SECS - BENCH_CHAOS_KILL_AT_SECS ))
[ $(( BENCH_CHAOS_STAGE_SECS + BENCH_CHAOS_SAVE_WAIT_SECS )) -lt "${CHAOS_OUTAGE_SECS}" ] \
    || bench_die "BENCH_CHAOS_STAGE_SECS + BENCH_CHAOS_SAVE_WAIT_SECS (${BENCH_CHAOS_STAGE_SECS}+${BENCH_CHAOS_SAVE_WAIT_SECS}) must be below the ${CHAOS_OUTAGE_SECS}s outage"
# The sequence's word to its child (light_env): a light blast, or the configured profile (unset).
case "${BENCH_BLAST_KIND:-load}" in light|load) ;; *) bench_die "BENCH_BLAST_KIND='${BENCH_BLAST_KIND}' must be light or load" ;; esac

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
        txgen_cli_probe
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

# txgen_cli_probe — bench-lib's bench_txgen_cli_probe, with --tail-scan-secs among the flags it requires
# when BENCH_TAIL_SCAN_SECS > 0 (its contract list, widened for this call only): an image from before the
# tail scan would otherwise fail on every blaster, after start_at.
txgen_cli_probe() {
    local BENCH_TXGEN_CONTRACT_FLAGS="${BENCH_TXGEN_CONTRACT_FLAGS}"
    [ "${BENCH_TAIL_SCAN_SECS:-0}" = 0 ] || BENCH_TXGEN_CONTRACT_FLAGS="${BENCH_TXGEN_CONTRACT_FLAGS} --tail-scan-secs"
    bench_txgen_cli_probe
}

# Internal IP per node index, filled once before the blasters' creates (resolve_node_urls).
NODE_IP=()

# node_url <idx> — "<instance>=http://<internal-ip>:8545" (placeholder when absent, dry run): the IP
# resolve_node_urls found, else a describe of the node (fund).
node_url() {
    local ip="${NODE_IP[$1]:-}"
    [ -n "${ip}" ] || ip="$(tn_node_int_ip "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}" 2>/dev/null || true)"
    if [ -z "${ip}" ]; then
        [ "${BENCH_APPLY}" = "1" ] && bench_die "${INSTANCE_NAMES[$1]} has no internal IP — is the fleet up?"
        ip="<internal-ip-of-${INSTANCE_NAMES[$1]}>"
    fi
    printf '%s=http://%s:8545' "${INSTANCE_NAMES[$1]}" "${ip}"
}

# resolve_node_urls — NODE_IP[k] of every validator k, once, before the blasters are created: the
# internal IPs deploy step 2 recorded in manifest.instances[], else ONE `gcloud compute instances list`
# for the nodes the manifest lacks (its stderr kept). Bench 5 described each node inside the create
# loop with stderr discarded, and one slow describe started three blasters after start_at (D48).
# A node left without an IP stops the run (--yes) before anything is recorded or created; a dry run
# gets the placeholder.
resolve_node_urls() {
    local k ip missing="" names="" listed=""
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        ip="$(jq -r --arg n "${INSTANCE_NAMES[$k]}" --arg z "${ZONES[$k]}" \
            'first((.instances // [])[] | select(.name == $n and .zone == $z) | .internal_ip // empty)' \
            "$(bench_manifest)" 2>/dev/null)" || ip=""
        NODE_IP[k]="${ip}"
        [ -n "${ip}" ] || { missing="${missing} ${k}"; names="${names:+${names} }${INSTANCE_NAMES[$k]}"; }
    done
    [ -n "${missing}" ] || return 0
    listed="$(perl -e 'alarm shift; exec @ARGV' "${CREATE_ALARM_SECS}" env CLOUDSDK_CORE_HTTP_TIMEOUT="${CREATE_HTTP_TIMEOUT_SECS}" \
        gcloud compute instances list --project="${PROJECT_ID}" --filter="name=(${names})" --format=json </dev/null)" || listed=""
    for k in ${missing}; do
        ip="$(printf '%s' "${listed}" | jq -r --arg n "${INSTANCE_NAMES[$k]}" --arg z "${ZONES[$k]}" \
            'first(.[]? | select(.name == $n and ((.zone // "") | split("/") | last) == $z) | .networkInterfaces[0].networkIP // empty)' \
            2>/dev/null)" || ip=""
        if [ -z "${ip}" ]; then
            [ "${BENCH_APPLY}" = "1" ] && bench_die "${INSTANCE_NAMES[$k]} has no internal IP — is the fleet up?"
            ip="<internal-ip-of-${INSTANCE_NAMES[$k]}>"
        fi
        NODE_IP[k]="${ip}"
    done
}

# Bounds of a load VM's create (D36). Each create call: gcloud's HTTP read timeout
# CREATE_HTTP_TIMEOUT_SECS (CLOUDSDK_CORE_HTTP_TIMEOUT; gcloud's own default is 300 s, which bench 5
# hit) under a CREATE_ALARM_SECS alarm. After a call that failed with anything but a stockout, the
# instance is described (CREATE_DESCRIBE_ALARM_SECS) before anything else is decided. A blaster's
# create must be known by start_at - CREATE_LATE_LEAD_SECS (the late-start guard, create_blasters);
# start_at is at least CREATE_WORST_SECS ahead, so a create that needs its one retry still fits.
CREATE_ALARM_SECS=90; CREATE_HTTP_TIMEOUT_SECS=60; CREATE_DESCRIBE_ALARM_SECS=60; CREATE_LATE_LEAD_SECS=30
CREATE_WORST_SECS=$(( 2 * CREATE_ALARM_SECS + 60 ))

# is_stockout <gcloud output> — 0 when a create failed because the zone has run out of the machine
# type (code ZONE_RESOURCE_POOL_EXHAUSTED[_WITH_DETAILS], reason: stockout). gcloud wraps its YAML
# error ("does not have\n  enough resources"), so whitespace is folded before matching.
is_stockout() {
    case "$(printf '%s' "$1" | tr -s ' \t\n' '   ')" in
        *ZONE_RESOURCE_POOL_EXHAUSTED*|*stockout*|*"does not have enough resources"*) return 0 ;;
    esac
    return 1
}

# create_vm <name> <zone> <mode> <node-urls> <senders> <sender-start> <start-at> [<deadline>] — one COS
# load VM on the first BENCH_BLASTER_MACHINE_TYPES type the zone has in stock: a create that fails on
# a stockout is retried at once with the next type, and the substitution is logged. Any other failed
# call is followed by a describe: a call that crashed or timed out has often created the instance
# anyway (bench 5, D36). An instance that exists counts as created, on the type the describe reports.
# Otherwise a transport fault (gcloud crashed, ReadTimeout, ConnectionError, or rc 142 from the alarm)
# gets one more call, once per VM, and anything else fails. Bounds: CREATE_ALARM_SECS per create call
# (gcloud's HTTP timeout CREATE_HTTP_TIMEOUT_SECS inside it), CREATE_DESCRIBE_ALARM_SECS per describe;
# with <deadline> (unix) no call starts after it and none outlasts it (status late). The type used is
# written to meta/<name>/MACHINE_TYPE (manifest blasters[].machine_type) and the outcome to
# meta/<name>/CREATE: "<ok|failed|late> <end-unix> <seconds from the first call> <create calls> <rc>".
# Returns 0 once created, else the last call's status (142: the alarm).
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
    [ "${mode}" != blast ] || [ "${BENCH_WINDOW:-16}" = 16 ] || meta="${meta}##WINDOW=${BENCH_WINDOW}"
    [ "${mode}" != blast ] || [ "${BENCH_LANDINGS_SAMPLE:-0}" = 0 ] || meta="${meta}##LANDINGS_SAMPLE=${BENCH_LANDINGS_SAMPLE}"
    [ "${mode}" != blast ] || [ "${BENCH_TAIL_SCAN_SECS:-0}" = 0 ] || meta="${meta}##TAIL_SCAN_SECS=${BENCH_TAIL_SCAN_SECS}"
    local pre=(compute instances create "${name}" --project="${PROJECT_ID}" --zone="${zone}")
    local post=(--image-family=cos-stable --image-project=cos-cloud
        --boot-disk-size="${BENCH_BLASTER_BOOT_DISK_GB}GB" --boot-disk-type=pd-balanced
        --service-account="${SERVICE_ACCOUNT}" --scopes=cloud-platform
        --tags=bench-blaster
        --labels="${BENCH_LABELS},tn-role=blaster"
        --metadata-from-file="${files}"
        --metadata="${meta}")
    local t out rc=0 tried="" first="${BENCH_BLASTER_MACHINE_TYPES%% *}" deadline="${8:-}"
    local status="" began end attempts=0 retried=0 transient bound left found drc dout
    if [ "${BENCH_APPLY}" != "1" ]; then
        bench_run perl -e 'alarm shift; exec @ARGV' "${CREATE_ALARM_SECS}" env CLOUDSDK_CORE_HTTP_TIMEOUT="${CREATE_HTTP_TIMEOUT_SECS}" \
            gcloud "${pre[@]}" --machine-type="${first}" "${post[@]}"
        [ "${BENCH_BLASTER_MACHINE_TYPES}" = "${first}" ] \
            || echo "      on a zone stockout: the same create with --machine-type=${BENCH_BLASTER_MACHINE_TYPES#* } (in turn)"
        return 0
    fi
    began="$(bench_now_unix)"
    for t in ${BENCH_BLASTER_MACHINE_TYPES}; do
        while :; do
            bound="${CREATE_ALARM_SECS}"
            if [ -n "${deadline}" ]; then
                left=$(( deadline - $(bench_now_unix) ))
                if [ "${left}" -le 0 ]; then status=late; rc=142; break 2; fi
                [ "${left}" -ge "${bound}" ] || bound="${left}"
            fi
            attempts=$((attempts + 1)); rc=0
            [ "${BENCH_APPLY}" = "1" ] || return 0
            out="$(bench_run perl -e 'alarm shift; exec @ARGV' "${bound}" env CLOUDSDK_CORE_HTTP_TIMEOUT="${CREATE_HTTP_TIMEOUT_SECS}" \
                gcloud "${pre[@]}" --machine-type="${t}" "${post[@]}" </dev/null 2>&1)" || rc=$?
            printf '%s\n' "${out}"
            if [ "${rc}" -eq 0 ]; then
                printf '%s\n' "${t}" > "${mdir}/MACHINE_TYPE"; status=ok
                [ -z "${tried}" ] || bench_warn "${name}: created on ${t} in ${zone} after a stockout of${tried}"
                break 2
            fi
            if is_stockout "${out}"; then status=stockout; break; fi
            # Any other failure: the API has often created the instance although the call crashed or
            # timed out. The describe's stderr stays in this create's output.
            bound="${CREATE_DESCRIBE_ALARM_SECS}"; found=""
            if [ -n "${deadline}" ]; then
                left=$(( deadline - $(bench_now_unix) ))
                [ "${left}" -ge "${bound}" ] || bound="${left}"
            fi
            if [ "${bound}" -gt 0 ]; then
                drc=0
                dout="$(perl -e 'alarm shift; exec @ARGV' "${bound}" gcloud compute instances describe "${name}" --zone="${zone}" \
                    --project="${PROJECT_ID}" --format=json </dev/null)" || drc=$?
                [ "${drc}" -ne 0 ] || found="$(printf '%s' "${dout}" | jq -r --arg n "${name}" --arg t "${t}" \
                    'select(type == "object" and .name == $n) | (.machineType // $t) | split("/") | last' 2>/dev/null)" || found=""
            fi
            if [ -n "${found}" ]; then
                printf '%s\n' "${found}" > "${mdir}/MACHINE_TYPE"; status=ok
                bench_warn "${name}: create call ${attempts} ended rc ${rc}, but the instance exists (${found}): counted as created"
                rc=0; break 2
            fi
            transient=0
            case "${rc}:${out}" in 142:*|*"gcloud crashed"*|*ReadTimeout*|*ConnectionError*) transient=1 ;; esac
            if [ "${transient}" -eq 1 ] && [ "${retried}" -eq 0 ]; then
                retried=1
                bench_warn "${name}: create call ${attempts} failed (rc ${rc}) and the instance does not exist: one more try"
                continue
            fi
            status=failed; break 2
        done
        tried="${tried} ${t}"
        bench_warn "${name}: ${t} is out of stock in ${zone} (stockout); trying the next blaster type"
    done
    if [ "${status}" = stockout ]; then
        status=failed
        bench_warn "${name}: every blaster type is out of stock in ${zone} (${BENCH_BLASTER_MACHINE_TYPES})"
    fi
    end="$(bench_now_unix)"
    printf '%s %s %s %s %s\n' "${status}" "${end}" "$(( end - began ))" "${attempts}" "${rc}" > "${mdir}/CREATE"
    return "${rc}"
}

# blasters_json [<k>] — manifest .blasters: one entry per blaster; machine_type is the type its create used
# (meta/<name>/MACHINE_TYPE from create_vm; null when that file is missing); created_at, create_secs and
# attempts once its create succeeded (meta/<name>/CREATE). With <k>: blaster k alone, its instance_id
# not looked up yet (""), the entry create_blasters records as soon as that create is known.
blasters_json() {
    local bl="[]" k name id mt st end secs calls
    for k in $(if [ $# -gt 0 ]; then echo "$1"; else seq 0 $((VAL_COUNT - 1)); fi); do
        name="$(blaster_name "$k")"
        id=""
        [ $# -gt 0 ] || id="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute instances describe "${name}" --zone="${ZONES[$k]}" \
            --project="${PROJECT_ID}" --format='value(id)' </dev/null 2>/dev/null || true)"
        mt="$(cat "${BENCH_RESULTS_DIR}/meta/${name}/MACHINE_TYPE" 2>/dev/null || true)"
        st=""; end=""; secs=""; calls=""
        [ ! -f "${BENCH_RESULTS_DIR}/meta/${name}/CREATE" ] || read -r st end secs calls _ < "${BENCH_RESULTS_DIR}/meta/${name}/CREATE" || true
        [ "${st}" = ok ] || end=""
        bl="$(printf '%s' "${bl}" | jq --arg n "${name}" --arg z "${ZONES[$k]}" --arg id "${id}" --arg t "${INSTANCE_NAMES[$k]}" \
            --arg u "$(sed 's/^[^=]*=//' "${BENCH_RESULTS_DIR}/meta/${name}/NODE_URLS")" --arg mt "${mt}" \
            --arg s "$(( k * BENCH_SENDERS + BENCH_RUN_INDEX * 100000 ))" --arg c "${BENCH_SENDERS}" \
            --arg ca "${end:+$(bench_iso_from_unix "${end}")}" --arg cs "${secs}" --arg ac "${calls}" \
            '. + [{name:$n, zone:$z, machine_type:(if $mt == "" then null else $mt end), instance_id:$id, target:$t, node_url:$u,
                   sender_start:($s|tonumber), senders:($c|tonumber), result:("blasters/" + $n + ".json"), rc:null}
                  + (if $ca == "" then {} else {created_at:$ca, create_secs:($cs|tonumber), attempts:($ac|tonumber)} end)]')"
    done
    printf '%s' "${bl}"
}

# blaster_created <k> — 0 when blaster k's create succeeded (meta/<name>/MACHINE_TYPE, written only
# then). The exit cleanup stops and waits for these alone: a blaster that was never created has no
# container to stop and sends no done marker (bench 5 waited 5m36s for one, D36).
blaster_created() { [ -f "${BENCH_RESULTS_DIR}/meta/$(blaster_name "$1")/MACHINE_TYPE" ]; }

# assert_load_vm <name> <zone> — created VM carries tag bench-blaster + label benchmark=1.
assert_load_vm() {
    [ "${BENCH_APPLY}" = "1" ] || return 0
    local j; j="$(bench_instance_json "$1" "$2")"
    [ -n "${j}" ] || bench_die "$1 not found after create"
    printf '%s' "${j}" | jq -e '(.tags.items // []) == ["bench-blaster"] and .labels.benchmark == "1"' >/dev/null \
        || bench_die "$1 lacks tag bench-blaster / label benchmark=1 — delete it: benchmark/benchmark-blast.sh delete --yes"
    [ "${BENCH_APPLY}" = "1" ] || return 0
    bench_run gcloud compute disks add-labels "$1" --zone="$2" --project="${PROJECT_ID}" --labels="${BENCH_LABELS},tn-role=blaster" --format=none
}

# assert_load_vms — assert_load_vm for every blaster at once (bench 5 ran them one after another, about
# 1.3 min per blast, D40); each one's output is printed in blaster order once all have ended. At most
# RELABEL_WAIT_SECS: one still running then is stopped and counts as failed. Stops the run (bench_die,
# the EXIT trap cleans up) when one failed, as the serial loop did under set -e.
RELABEL_WAIT_SECS=180
assert_load_vms() {
    local k f pids=() outs=() failed="" waited=0 running
    [ "${BENCH_APPLY}" = "1" ] || return 0
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        f="$(mktemp "${TMPDIR:-/tmp}/blast-relabel.XXXXXX")" || bench_die "no temporary file for the relabel of $(blaster_name "$k")"
        outs[k]="${f}"
        ( assert_load_vm "$(blaster_name "$k")" "${ZONES[$k]}" ) > "${f}" 2>&1 < /dev/null &
        pids[k]=$!
    done
    while :; do
        running=0
        for k in "${!pids[@]}"; do ! kill -0 "${pids[k]}" 2>/dev/null || running=1; done
        [ "${running}" -eq 1 ] && [ "${waited}" -lt "${RELABEL_WAIT_SECS}" ] || break
        sleep 1; waited=$((waited + 1))
    done
    for k in "${!pids[@]}"; do
        if kill -0 "${pids[k]}" 2>/dev/null; then
            kill "${pids[k]}" 2>/dev/null || true
            wait "${pids[k]}" 2>/dev/null || true
            failed="${failed} $(blaster_name "$k") (still running after ${RELABEL_WAIT_SECS} s)"
        elif ! wait "${pids[k]}"; then
            failed="${failed} $(blaster_name "$k")"
        fi
        cat "${outs[k]}"; rm -f "${outs[k]}"
    done
    [ -z "${failed}" ] || bench_die "blaster check or disk relabel failed:${failed} — the exit cleanup deletes the blasters; if it cannot: benchmark/benchmark-blast.sh delete --yes"
}

delete_vms() { # <zone> <name...>
    local zone="$1"; shift
    [ $# -gt 0 ] || return 0
    local n; for n in "$@"; do bench_assert_bench_name "instance" "${n}"; done
    if [ "${BENCH_APPLY}" != "1" ]; then bench_run gcloud compute instances delete "$@" --zone="${zone}" --project="${PROJECT_ID}" --quiet; return 0; fi
    [ "${BENCH_APPLY}" = "1" ] || return 0
    bench_run gcloud compute instances delete "$@" --zone="${zone}" --project="${PROJECT_ID}" --quiet
}

# Blaster deletes after a run (D40): each issued in the background (delete_vm_bg), then await_deletes
# describes every VM still there each DELETE_POLL_SECS until all are gone or DELETE_WAIT_SECS have passed
# (the teardown's routine). Bench 5 deleted them one after another, about 20 s each.
DELETE_POLL_SECS=10; DELETE_WAIT_SECS=300
DELETE_JOBS=()    # "<pid> <zone> <name>" per background delete

# delete_vm_bg <zone> <name> — delete_vms in the background; await_deletes waits for it. A dry run
# prints the argv, as delete_vms does.
delete_vm_bg() {
    if [ "${BENCH_APPLY}" != "1" ]; then delete_vms "$1" "$2"; return 0; fi
    [ "${BENCH_APPLY}" = "1" ] || return 0
    delete_vms "$1" "$2" < /dev/null &
    DELETE_JOBS+=("$! $1 $2")
}

# delete_state <zone> <name> — "gone" once a describe says the instance was not found, else its status
# ("?" when the describe failed for another reason). The teardown's delete_state, by name.
delete_state() {
    local out rc=0
    out="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute instances describe "$2" --zone="$1" --project="${PROJECT_ID}" \
        --format='value(status)' </dev/null 2>&1)" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        case "${out}" in *"not found"*) echo gone ;; *) echo "?" ;; esac
        return 0
    fi
    printf '%s\n' "${out:-?}" | tail -1
}

# await_deletes — the describe loop for DELETE_JOBS: one describe per VM still there every
# DELETE_POLL_SECS, until none is left or DELETE_WAIT_SECS have passed (also as many passes as fit in
# it, whatever the clock says). Then the finished delete calls are reaped; one still running is
# named, never waited for. 1 when a VM is still there at the cap (each named, with the cleanup command).
await_deletes() {
    local t0 c pid z n st pass=0 passes failed=0 pending=() still=()
    [ "${#DELETE_JOBS[@]}" -gt 0 ] || return 0
    passes=$(( DELETE_WAIT_SECS / (DELETE_POLL_SECS > 0 ? DELETE_POLL_SECS : 1) + 1 ))
    echo "    waiting for ${#DELETE_JOBS[@]} blaster delete(s): a describe each every ${DELETE_POLL_SECS} s, at most ${DELETE_WAIT_SECS} s"
    pending=("${DELETE_JOBS[@]}")
    t0="$(bench_now_unix)"
    while :; do
        still=(); pass=$((pass + 1))
        for c in "${pending[@]}"; do
            read -r pid z n <<< "${c}"
            st="$(delete_state "${z}" "${n}")"
            if [ "${st}" = gone ]; then echo "    ✓ ${n} deleted"; else still+=("${c} ${st}"); fi
        done
        [ "${#still[@]}" -gt 0 ] || break
        if [ $(( $(bench_now_unix) - t0 )) -ge "${DELETE_WAIT_SECS}" ] || [ "${pass}" -ge "${passes}" ]; then
            for c in "${still[@]}"; do
                read -r pid z n st <<< "${c}"
                echo "❌ ${n} (${z}) still there after ${DELETE_WAIT_SECS} s (status ${st}) — benchmark/benchmark-blast.sh delete --yes removes it" >&2
            done
            failed=1; break
        fi
        pending=()
        for c in "${still[@]}"; do pending+=("${c% *}"); done
        sleep "${DELETE_POLL_SECS}"
    done
    for c in "${DELETE_JOBS[@]}"; do
        read -r pid z n <<< "${c}"
        if kill -0 "${pid}" 2>/dev/null; then echo "    ✗ delete of ${n} still running (pid ${pid}) — not waited for"; continue; fi
        wait "${pid}" || true    # a VM still there is reported above; a call that failed but deleted it is not a fault
    done
    DELETE_JOBS=()
    return "${failed}"
}

# Done markers from blaster-startup.sh: "<MARK> rc=N reason=R [...]". Only rc=0 reason=ok
# means the results are in the bucket; anything else leaves the VM holding the only copy.
# Serial-console lines end in CRLF: strip \r first or "reason=ok" compares as "ok\r".
marker_rc() { tr -d '\r' | sed -n "s/.*$1 rc=\([0-9][0-9]*\).*/\1/p" | tail -1; }
marker_reason() { tr -d '\r' | sed -n "s/.*$1 rc=[0-9][0-9]* reason=\([^ ]*\).*/\1/p" | tail -1; }

# settle_load_vm <name> <zone> <results-subdir> <done-line> <MARK> [<delete-fn>] — delete the VM only
# when its results are safe: rc=0 reason=ok (uploaded), or an IAP scp of /var/lib/bench/out
# succeeded. Otherwise KEEP it and say so (it may hold the only copy). --keep never deletes. The
# delete is <delete-fn> <zone> <name>: delete_vms (default), or delete_vm_bg for the blasters.
settle_load_vm() {
    local name="$1" zone="$2" sub="$3" line="$4" mark="$5" del="${6:-delete_vms}" rc reason dest
    if [ "${BENCH_APPLY}" = "1" ] && [ -z "$(bench_instance_json "${name}" "${zone}")" ]; then return 0; fi
    rc="$(printf '%s\n' "${line}" | marker_rc "${mark}")"
    reason="$(printf '%s\n' "${line}" | marker_reason "${mark}")"
    if [ "${rc}" = "0" ] && [ "${reason}" = "ok" ]; then
        [ "${KEEP}" -eq 1 ] || "${del}" "${zone}" "${name}" || true
        return 0
    fi
    bench_warn "${name}: '${line:-no ${mark} marker}' — fetching /var/lib/bench/out over IAP before any delete"
    # The fetch goes into a directory that holds no file yet, so the check below counts only
    # what this fetch brought: funder/ keeps its scp-bench-funder/ when the same index is funded
    # again (a new index moves funder/ aside first).
    dest="${BENCH_RESULTS_DIR}/${sub}/scp-${name}"
    [ -z "$(find "${dest}" -type f 2>/dev/null | head -1)" ] || dest="${dest}-$(date -u +%Y%m%dT%H%M%SZ)"
    if [ "${BENCH_APPLY}" = "1" ]; then mkdir -p "${dest}"; fi
    if bench_run gcloud compute scp --recurse "${name}:/var/lib/bench/out" "${dest}/" --zone="${zone}" \
            --project="${PROJECT_ID}" --tunnel-through-iap --scp-flag="-o ConnectTimeout=20" \
       && { [ "${BENCH_APPLY}" != "1" ] || [ -n "$(find "${dest}" -type f 2>/dev/null | head -1)" ]; }; then
        bench_manifest_note "${name}: '${line:-no marker}' — results fetched over IAP into ${dest#"${BENCH_RESULTS_DIR}"/}/" || true
        [ "${KEEP}" -eq 1 ] || "${del}" "${zone}" "${name}" || true
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

# start_blast_log [<name>] — with --yes, copy everything this invocation prints to
# logs/blast-<name, default the action>-<UTC>.log (a new file) while it still reaches the terminal. stdout and
# stderr keep separate tees. Both ignore HUP, INT (tee -i as well), TERM and PIPE, so they end
# only when the script closes their input: a Ctrl-C, a TERM to the process group, a closed
# terminal or a dead parent copy (deploy step 14) leaves the file copy running for the EXIT
# trap. A write to a gone terminal or parent then fails inside tee, which carries on with the
# file. A plan-only run creates nothing.
start_blast_log() {
    [ "${BENCH_APPLY}" = "1" ] || return 0
    local n=0
    mkdir -p "${BENCH_RESULTS_DIR}/logs"
    until BLAST_LOG="${BENCH_RESULTS_DIR}/logs/blast-${1:-${ACTION}}-$(date -u +%Y%m%dT%H%M%SZ).log"; ( set -C; : > "${BLAST_LOG}" ) 2>/dev/null; do
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
prev_blast_items() { blast_items_in "${BENCH_RESULTS_DIR}"; }

# blast_items_in <dir> — the per-blast outputs in <dir> (the results dir, or a blast-<i>-<UTC>/ the
# light-load arm moves back), relative to it; never this invocation's own output copy.
blast_items_in() {
    local r="$1" f
    for f in "${r}/blasters" "${r}"/meta/bench-blaster-* "${r}"/logs/create-bench-blaster-*.log \
             "${r}"/logs/blast-run-*.log "${r}"/logs/blast-collect-*.log "${r}/metrics.json"; do
        [ -e "${f}" ] && [ "${f}" != "${BLAST_LOG}" ] && printf '%s\n' "${f#"${r}"/}"
    done
    return 0
}

# prev_attempt_unsent — 0 when the blast in the live manifest used this BENCH_RUN_INDEX but none of
# its senders can have sent: its run exited (the EXIT trap recorded .abort "interrupted", or a create
# stopped it: "create_failed", "late_create") and .blast.start_at, the BENCH_START_AT its blasters
# sleep until, is still more than 60 s away (clock skew). do_run has already checked that no
# bench-blaster VM exists, so none can start later. Once that time has passed, a blaster left running
# (--keep, a failed delete) may have sent before someone deleted it; only a create stop that recorded
# .abort.unsent (every blaster deleted before start_at) rules that out.
prev_attempt_unsent() {
    jq -e --arg i "${BENCH_RUN_INDEX}" --arg t "$(bench_iso_from_unix "$(( $(bench_now_unix) + 60 ))")" \
        '.blast.run_index == ($i|tonumber)
         and (.abort.reason == "interrupted" or .abort.reason == "create_failed" or .abort.reason == "late_create")
         and ((.blast.start_at // "") > $t or (.abort.reason != "interrupted" and .abort.unsent == true))' \
        "$(bench_manifest)" >/dev/null 2>&1
}

# archive_prev_blast — see above. Stops before anything moves when an earlier blast (the previous
# or an archived one) used this BENCH_RUN_INDEX: its sender range would be reused. The one
# exception is a previous attempt that never sent (prev_attempt_unsent): it is archived like any
# blast and this run retries its index. Dry run: prints the plan, touches nothing.
archive_prev_blast() {
    local used next
    case "${BENCH_RUN_INDEX}" in ''|*[!0-9]*|0?*) bench_die "BENCH_RUN_INDEX='${BENCH_RUN_INDEX}' must be a non-negative integer" ;; esac
    used="$(blast_indices_used)"
    if [ "$(grep -cx "${BENCH_RUN_INDEX}" <<< "${used}")" -eq 1 ] && prev_attempt_unsent; then
        echo "    the previous attempt under BENCH_RUN_INDEX=${BENCH_RUN_INDEX} exited before its blasters' start and none exists: retrying under the same index"
    elif grep -qx "${BENCH_RUN_INDEX}" <<< "${used}"; then
        next="$(grep -x '[0-9][0-9]*' <<< "${used}" | sort -n | tail -1)"
        bench_die "an earlier blast on this fleet used BENCH_RUN_INDEX=${BENCH_RUN_INDEX}, so this one would reuse its senders. Fund and run under a new index: BENCH_RUN_INDEX=$(( next + 1 )) benchmark/benchmark-blast.sh fund --yes, then run --yes. Nothing was moved."
    fi
    archive_blast_outputs
}

# archive_blast_outputs — archive_prev_blast's moves, without its index check: the blast in the
# results dir (if any) into blast-<its index>-<UTC>/, its per-blast manifest keys reset.
archive_blast_outputs() {
    local r="${BENCH_RESULTS_DIR}" prev dest it n=0 items=()
    if ! prev_blast_recorded; then echo "    no previous blast in ${r} — nothing to archive"; return 0; fi
    prev="$(prev_blast_index)"
    [ "${prev}" != "unknown" ] || bench_warn "the previous blast recorded no BENCH_RUN_INDEX: make sure index ${BENCH_RUN_INDEX} was funded and never blasted"
    while IFS= read -r it; do items+=("${it}"); done < <(prev_blast_items)
    echo ">>> archive the previous blast (BENCH_RUN_INDEX ${prev}) into ${r}/blast-${prev}-<UTC>/ with a copy of manifest.json"
    # "${items[@]}" of an empty array is an unbound variable under bash 3.2 with set -u: a blast
    # the manifest records may have left no file (it failed before creating its blasters).
    if [ "${#items[@]}" -eq 0 ]; then echo "    (no per-blast file to move)"
    else for it in "${items[@]}"; do echo "    mv ${it}"; done; fi
    echo "    manifest: .blasters=[] .chaos=[] .abort=null .phases=[], drop .blast, .phases_planned and timestamps blast_start_at/blast_end/collect_start/step_14_done/step_15_done"
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
    bench_manifest_jq '.blasters = [] | .chaos = [] | .abort = null | .phases = [] | del(.blast) | del(.phases_planned)
        | .timestamps |= del(.blast_start_at, .blast_end, .collect_start, .step_14_done, .step_15_done)' \
        || bench_die "outputs moved into ${dest}/ but manifest.json was not reset — the blast has not started"
    bench_manifest_note "blast index ${prev} archived into $(basename "${dest}")/ at $(bench_now_iso); earlier notes belong to it or to the fleet" || true
    echo "    ✓ previous blast archived: ${dest}/"
}

# record_blast <start_at-unix> — manifest.blast: the settings that tell one blast from another, with
# tail_scan_secs, the blasters' --tail-scan-secs (0: off).
record_blast() {
    echo "    blast: BENCH_RUN_INDEX=${BENCH_RUN_INDEX} chaos=${BENCH_CHAOS} lag_inject=${BENCH_LAG_INJECT} (node idx ${BENCH_LAG_IDX}, mixed+${BENCH_LAG_AT_SECS}s for ${BENCH_LAG_PAUSE_SECS}s)$([ "${BENCH_TAIL_SCAN_SECS:-0}" = 0 ] || echo " tail_scan=${BENCH_TAIL_SCAN_SECS}s")"
    echo "    bucket prefix: $(bucket_prefix blasters)/"
    [ "${BENCH_APPLY}" = "1" ] || return 0
    bench_manifest_jq --arg i "${BENCH_RUN_INDEX}" --arg c "${BENCH_CHAOS}" --arg li "${BENCH_LAG_INJECT}" --arg lx "${BENCH_LAG_IDX}" \
        --arg la "${BENCH_LAG_AT_SECS}" --arg lp "${BENCH_LAG_PAUSE_SECS}" --arg s "$(bench_iso_from_unix "$1")" --arg bp "$(bucket_prefix blasters)" \
        --arg ts "${BENCH_TAIL_SCAN_SECS:-0}" \
        '.blast = {run_index: ($i|tonumber), chaos: ($c|tonumber), lag_inject: ($li|tonumber), lag_idx: ($lx|tonumber),
                   lag_at_secs: ($la|tonumber), lag_pause_secs: ($lp|tonumber), start_at: $s, bucket_prefix: $bp,
                   tail_scan_secs: ($ts|tonumber)}'
}

# ================================ fund ===============================================
# prev_funder_index — BENCH_RUN_INDEX of the output in results/<run>/funder/: .fund.run_index,
# recorded once `fund` has copied its objects there; "unknown" for output from before that key.
prev_funder_index() {
    jq -r '.fund.run_index // "unknown" | tostring' "$(bench_manifest)" 2>/dev/null || echo unknown
}

# set_aside_prev_funder — before `fund` writes anything, MOVE the funder output of another index
# (funder/, meta/bench-funder/) into results/<run>/funder-<its index>-<UTC>/, a directory mkdir just
# created, beside a COPY of manifest.json with its fund timestamps. Bench 5 copied funder/ and left it,
# so each funder-<i>-<UTC>/ also held the txgen logs of every index before it (D47). No later step reads
# an older index's funder/: .fund names the moved index until the new fund's copy succeeds, and collect
# copies that prefix back if it never does. Dry run: prints the plan.
set_aside_prev_funder() {
    local r="${BENCH_RESULTS_DIR}" prev dest it n=0 items=()
    [ -n "$(find "${r}/funder" -type f 2>/dev/null | head -1)" ] || return 0
    prev="$(prev_funder_index)"
    if [ "${prev}" = "${BENCH_RUN_INDEX}" ]; then
        echo "    funder/ holds the output of BENCH_RUN_INDEX ${prev}: funding it again overwrites it"; return 0
    fi
    for it in funder meta/bench-funder manifest.json; do [ -e "${r}/${it}" ] && items+=("${it}"); done
    echo ">>> move the funder output of BENCH_RUN_INDEX ${prev} ($(find "${r}/funder" -type f | wc -l | tr -d ' ') files in funder/) into ${r}/funder-${prev}-<UTC>/"
    for it in "${items[@]}"; do if [ "${it}" = manifest.json ]; then echo "    cp ${it}"; else echo "    mv ${it}"; fi; done
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — nothing moved)"; return 0; fi
    until dest="${r}/funder-${prev}-$(date -u +%Y%m%dT%H%M%SZ)"; [ ! -e "${dest}" ] && mkdir "${dest}"; do
        [ -e "${dest}" ] || bench_die "cannot create ${dest} — nothing was moved; the fund has not started"
        n=$((n + 1)); [ "${n}" -lt 5 ] || bench_die "no free funder-${prev}-<UTC> name in ${r} — nothing was moved; the fund has not started"
        echo "    $(basename "${dest}") exists — trying a new timestamp"
        sleep 1
    done
    for it in "${items[@]}"; do
        if [ "${it}" = manifest.json ]; then
            cp -p "${r}/${it}" "${dest}/${it}" || bench_die "could not copy manifest.json into ${dest}/ — the fund has not started"
        elif ! mkdir -p "${dest}/$(dirname "${it}")" || ! mv "${r}/${it}" "${dest}/${it}"; then
            bench_die "could not move ${it} into ${dest}/ — the fund has not started; what moved is in ${dest}/, the rest is still in place"
        fi
    done
    bench_manifest_note "funder output of index ${prev} moved into $(basename "${dest}")/ at $(bench_now_iso); funder/ now receives index ${BENCH_RUN_INDEX}" || true
    echo "    ✓ funder output moved: ${dest}/"
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
CHAOS_RC=0        # rc of the last chaos action (its BENCH_CHAOS_END rc, else the ssh rc)
CHAOS_BEGIN=""    # node-side begin (unix.ms) of the last chaos action; the local time when it reported none
KILL_ENTRY=""; KILL_BEGIN=""; BACK_BEGIN=""   # the kill's index in .chaos[]; kill and restart begin times
BOUNDARY_DONE=0   # 1 once the boundary verdict (chaos_boundary_check) is recorded
SCHEDULE_REFRESHED=0   # 1 once chaos_schedule_refresh has re-planned the kill in the opened closing epoch
DONE_LINE=()      # per blaster index: its last "BENCH_BLAST_DONE rc=..." serial line
PREV_ROUNDS=""    # {"<node>": max tn_primary_round} from the previous poll (Prometheus)
STALL_POLLS=0; LAST_ADVANCE_TS=0
NODE_STALL_COUNTS="{}"
STATUS_SEEN=()    # per node index: ts of the newest BENCH_STATUS sample already read
POLL_SAMPLES=""   # "<ts> <block>" of every node's BENCH_STATUS samples since the last poll
FLAT_BLOCK=""; FLAT_SINCE=0; FLAT_UNTIL=0; FLAT_STATE=""; FLAT_ROUND=""; FLAT_ROUNDS_UP=""   # commit_flat_check
STALL_WIN_START=0; STALL_MIXED_END=0   # planned mixed start and end
# Why the EXIT trap runs, when a blaster create stopped the run (create_blasters): create_failed or
# late_create, the blaster, and the first ERROR: line or the lateness. Unset, it records interrupted/operator.
ABORT_REASON=""; ABORT_NODE=""; ABORT_DETAIL=""
CREATE_PIDS=()    # per blaster index: the pid of its background create (create_blasters)

record_abort() { # <reason> <node> <detail> [<unsent: true|false>]
    [ -n "${ABORTED}" ] && return 0
    ABORTED="$1"
    echo "❌❌ ABORT: $1 node=$2 — $3${4:+ (unsent=$4)}" >&2
    bench_manifest_jq --arg ts "$(bench_now_iso)" --arg r "$1" --arg n "$2" --arg d "$3" --arg u "${4:-}" \
        '.abort = {ts: $ts, reason: $r, node: $n, detail: $d} + (if $u == "" then {} else {unsent: ($u == "true")} end)' || true
}

# chaos_mark <BEGIN|END> <remote-output> — the node-side unix time (ms) on the action's
# BENCH_CHAOS_<mark> line; nothing when there is none.
chaos_mark() {
    printf '%s\n' "$2" | tr -d '\r' | awk -v m="BENCH_CHAOS_$1" '$1 == m && $NF ~ /^[0-9]+(\.[0-9]+)?$/ { t = $NF }
        END { if (t != "") { n = split(t, p, "."); printf "%s.%s\n", p[1], substr((n > 1 ? p[2] : "") "000", 1, 3) } }'
}

# record_chaos <node> <action> <note> <ssh-rc> [<remote-output> [<planned-unix> [<staged> [<extra-json>]]]]
# — one .chaos[] entry. The action's BENCH_CHAOS_BEGIN/END lines in <remote-output> carry the
# node's clock: ts is the begin (the local time when the node reported none), plus begin_unix,
# end_unix and late_secs = begin - planned. rc is END's rc, else the ssh rc: a session that drops
# after END does not undo an action that landed. Sets CHAOS_RC and CHAOS_BEGIN.
record_chaos() {
    local out="${5:-}" extra="${8:-}" begin end rc
    begin="$(chaos_mark BEGIN "${out}")"; end="$(chaos_mark END "${out}")"
    rc="$(printf '%s\n' "${out}" | tr -d '\r' | sed -n 's/^BENCH_CHAOS_END node=[^ ]* rc=\([0-9][0-9]*\) .*/\1/p' | tail -1)"
    CHAOS_RC="${rc:-$4}"
    CHAOS_BEGIN="${begin:-$(bench_now_unix)}"
    [ -n "${extra}" ] || extra='{}'
    bench_manifest_jq --arg ts "$(bench_iso_from_unix "${CHAOS_BEGIN%.*}")" --arg n "$1" --arg a "$2" --arg note "$3" \
        --arg rc "${CHAOS_RC}" --arg p "${6:-}" --arg b "${begin}" --arg e "${end}" --arg s "${7:-false}" --argjson x "${extra}" '
        def num: if . == "" then null else tonumber end;
        .chaos += [{ts: $ts, node: $n, action: $a, note: $note, rc: ($rc|tonumber),
                    planned_unix: ($p|num), begin_unix: ($b|num), end_unix: ($e|num),
                    late_secs: (if $b == "" or $p == "" then null else (($b|tonumber) - ($p|tonumber)) * 1000 | round / 1000 end),
                    staged: ($s == "true")} + $x]' || true
}

# chaos_do <idx> <remote-cmd> <action-label> <note> [<planned-unix> [<extra-json>]] — the direct
# path: one --command at once, recorded by record_chaos (staged=false); CHAOS_RC as there.
# One session, never retried by the transport (TN_IAP_RETRIES=0, here and in chaos_stage_send): a
# session that drops after the action ran would run it again seconds later, or late, and each
# caller already owns its retry (the staged path falls back to this one; an owed restart or
# unpause is tried again at a later poll).
chaos_do() {
    local inst="${INSTANCE_NAMES[$1]}" zone="${ZONES[$1]}" rc=0 out
    bench_log "CHAOS ${inst}: $3"
    local remote_cmd="printf 'BENCH_CHAOS_BEGIN node=${inst} '; date -u +%s.%N; { $2; }; action_rc=\$?; printf 'BENCH_CHAOS_END node=${inst} rc=%s ' \"\$action_rc\"; date -u +%s.%N; exit \"\$action_rc\""
    out="$(TN_IAP_RETRIES=0 tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}" | tee -a "${BENCH_RESULTS_DIR}/chaos-remote.log")" || rc=$?
    [ -z "${out}" ] || printf '%s\n' "${out}" | sed 's/^/      /'
    record_chaos "${inst}" "$3" "$4" "${rc}" "${out}" "${5:-}" false "${6:-}"
}

# chaos_direct_cmd <kill|start|restart> — the direct path's command for a staged action.
chaos_direct_cmd() {
    case "$1" in
        kill) printf '%s' "sudo docker kill -s KILL telcoin && sudo systemctl stop telcoin && { systemctl is-active telcoin || true; }" ;;
        start) printf '%s' "sudo systemctl start telcoin && systemctl is-active telcoin" ;;
        restart) printf '%s' "sudo systemctl restart telcoin && systemctl is-active telcoin" ;;
        *) printf 'true' ;;
    esac
}

# CHAOS_STAGE_SCRIPT — a staged chaos action, sent on stdin to `sudo bash -s` after the CHAOS_*
# assignment lines chaos_stage_send writes; nothing is quoted into a --command string
# (tasks/lessons.md). The body is one function called on the last line, so a script cut short in
# transit is a syntax error and runs nothing. It starts the container-log save as a background job
# (as bench_save_node_log does, same file name, so the pulls collect it) and prints
# BENCH_CHAOS_SAVE_STARTED, waits on the node's clock for CHAOS_DUE, then prints BENCH_CHAOS_BEGIN,
# runs the action and prints BENCH_CHAOS_END in the direct path's format. The save never holds the
# action back (r20261007-0316: a 70 s save before the wait put the kill 41.8 s late); late is the
# 0.2 s poll of the wait. After END the session waits up to CHAOS_SAVE_WAIT seconds for the save
# and prints one of: BENCH_CHAOS_SAVED <file> at_action=finished|running (the save had finished
# when the action began, or finished after it), BENCH_CHAOS_SAVE_FAILED <name> at_action=... <error>,
# BENCH_CHAOS_SAVE_RUNNING <file> at_action=running (still writing: it completes on the node by
# itself and the file appears under its name only when complete). A save that outlives a kill is
# not cut short: `docker logs` reads the log to the size it had when the save began, and Docker
# removes the --rm container without waiting for it (Docker 29.8 json-file: a 542 MB read started
# 0.5 s before a SIGKILL completed in full, rc 0, and the name was free 0.2 s after the kill).
# The BEGIN line is written before the action and checked: once the operator's session is gone
# that write fails, so a run interrupted during the wait cannot kill the node after its EXIT trap
# restarted it. A due time more than CHAOS_MAX_WAIT ahead on the node's clock (skew) is refused
# before the save starts. Case patterns carry their opening parenthesis: macOS /bin/bash 3.2
# misparses a bare `pattern)` inside this $(...) (tasks/lessons.md).
CHAOS_STAGE_SCRIPT=$(cat <<'EOS'
chaos_stage() {
    set -u -o pipefail
    local name="" sd="" at="" ahead rc
    now_ms() { local t; t=$(date -u +%s.%N); case $t in (*.[0-9][0-9][0-9]*) printf '%s' "${t%"${t#*.???}"}" ;; (*) printf '%s.000' "${t%%.*}" ;; esac; }
    save_log() { # <dir> <name>
        local d=$1 f=$1/$2 p
        docker container inspect telcoin >/dev/null || return 1
        mkdir -p "$d" || return 1
        if [ -e "$f" ]; then echo "$f exists already" >&2; return 1; fi
        p=$(mktemp "$d/.$2.XXXXXX") || return 1
        docker logs telcoin 2>&1 | gzip -1 > "$p" || return 1
        [ "$(gzip -cd "$p" | head -c 1 | wc -c)" -eq 1 ] || { echo "the telcoin container log is empty" >&2; return 1; }
        mv -n "$p" "$f" && [ ! -e "$p" ] && [ -s "$f" ]
    }
    save_report() { # <secs> — wait up to <secs> for the background save, then print its outcome
        local until=$(( $(date +%s) + $1 ))
        while [ ! -s "$sd/rc" ] && [ "$(date +%s)" -lt "$until" ]; do sleep 0.5; done
        if [ ! -s "$sd/rc" ]; then
            echo "BENCH_CHAOS_SAVE_RUNNING $CHAOS_LOG_DIR/$name at_action=$at"
        elif [ "$(cat "$sd/rc")" = 0 ]; then
            echo "BENCH_CHAOS_SAVED $CHAOS_LOG_DIR/$name at_action=$at"; rm -rf "$sd"
        else
            echo "BENCH_CHAOS_SAVE_FAILED $name at_action=$at $(tr '\n' ' ' < "$sd/err" | cut -c1-300)"; rm -rf "$sd"
        fi
    }
    case $CHAOS_ACTION in (kill|start|restart|true) ;; (*) echo "BENCH_CHAOS_STAGE_FAIL action $CHAOS_ACTION"; return 2 ;; esac
    ahead=$(( CHAOS_DUE - $(date +%s) ))
    if [ "$ahead" -gt "$CHAOS_MAX_WAIT" ]; then
        echo "BENCH_CHAOS_STAGE_FAIL due in ${ahead}s on this clock, more than ${CHAOS_MAX_WAIT}s"; return 2
    fi
    # The save's fds are not the session's: a save still running at the end does not hold it open.
    if [ -n "$CHAOS_SAVE" ] && sd=$(mktemp -d); then
        name="telcoin-$CHAOS_SAVE-$(date -u +%Y%m%dT%H%M%SZ).log.gz"
        { save_log "$CHAOS_LOG_DIR" "$name" 2>"$sd/err"; echo "$?" > "$sd/rc"; } </dev/null >/dev/null 2>&1 &
        echo "BENCH_CHAOS_SAVE_STARTED $CHAOS_LOG_DIR/$name"
    else
        sd=""
    fi
    while [ "$(date +%s)" -lt "$CHAOS_DUE" ]; do sleep 0.2; done
    if [ -n "$sd" ]; then if [ -s "$sd/rc" ]; then at=finished; else at=running; fi; fi
    printf 'BENCH_CHAOS_BEGIN node=%s %s\n' "$CHAOS_NODE" "$(now_ms)" || return 2
    case $CHAOS_ACTION in
        (kill) docker kill -s KILL telcoin && systemctl stop telcoin && { systemctl is-active telcoin || true; } ;;
        (start) systemctl start telcoin && systemctl is-active telcoin ;;
        (restart) systemctl restart telcoin && systemctl is-active telcoin ;;
        (true) true ;;
    esac
    rc=$?
    printf 'BENCH_CHAOS_END node=%s rc=%s %s\n' "$CHAOS_NODE" "$rc" "$(now_ms)"
    [ -z "$sd" ] || save_report "$CHAOS_SAVE_WAIT"
    return "$rc"
}
chaos_stage
EOS
)

# chaos_stage_send <idx> <kill|start|restart|true> <due-unix> <log-label|""> — CHAOS_STAGE_SCRIPT on
# the node; its output on stdout, the ssh rc. Each value is checked here, so every CHAOS_* line
# the node reads is a plain assignment. The session is never retried by the transport
# (TN_IAP_RETRIES=0): a re-sent script after a drop past BEGIN would fire the action twice, and
# one re-sent before it would start late; chaos_staged's fallback to the direct path is the retry.
chaos_stage_send() {
    local inst="${INSTANCE_NAMES[$1]:-}" zone="${ZONES[$1]:-}"
    case "${inst}" in ''|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*) echo "❌ chaos_stage_send: no node at index '$1'" >&2; return 2 ;; esac
    case "$2" in kill|start|restart|true) ;; *) echo "❌ chaos_stage_send: action '$2'" >&2; return 2 ;; esac
    case "$3" in ''|*[!0-9]*) echo "❌ chaos_stage_send: due time '$3'" >&2; return 2 ;; esac
    case "$4" in *[!abcdefghijklmnopqrstuvwxyz0123456789-]*) echo "❌ chaos_stage_send: log label '$4'" >&2; return 2 ;; esac
    case "${BENCH_NODE_LOG_DIR}" in ''|*[!A-Za-z0-9/._-]*) echo "❌ chaos_stage_send: log dir '${BENCH_NODE_LOG_DIR}'" >&2; return 2 ;; esac
    printf 'CHAOS_NODE=%s\nCHAOS_ACTION=%s\nCHAOS_DUE=%s\nCHAOS_SAVE=%s\nCHAOS_LOG_DIR=%s\nCHAOS_MAX_WAIT=%s\nCHAOS_SAVE_WAIT=%s\n%s\n' \
        "${inst}" "$2" "$3" "$4" "${BENCH_NODE_LOG_DIR}" "$(( BENCH_CHAOS_STAGE_SECS + 60 ))" "$(( BENCH_CHAOS_SAVE_WAIT_SECS ))" \
        "${CHAOS_STAGE_SCRIPT}" | TN_IAP_RETRIES=0 tn_iap_ssh_stdin "${inst}" "${zone}"
}

# chaos_save_report <idx> <log-label|""> <remote-output> — the staged log save's outcome, reported
# as save_log_first reports its own. A save the session left running (SAVE_RUNNING, or STARTED
# with no outcome when the session ended early) completes on the node by itself.
chaos_save_report() {
    [ -n "$2" ] || return 0
    local out saved at
    out="$(printf '%s\n' "$3" | tr -d '\r')"
    saved="$(printf '%s\n' "${out}" | sed -n 's/^BENCH_CHAOS_SAVED \([^ ]*\).*/\1/p' | tail -1)"
    at="$(printf '%s\n' "${out}" | sed -n 's/^BENCH_CHAOS_SAVED [^ ]* at_action=\([a-z]*\).*/\1/p' | tail -1)"
    if [ -n "${saved}" ]; then
        echo "      ✓ ${INSTANCE_NAMES[$1]}: container log saved on the node as ${saved} (${at:-?} when the ${2#pre-} began)"; return 0
    fi
    saved="$(printf '%s\n' "${out}" | sed -n -e 's/^BENCH_CHAOS_SAVE_RUNNING \([^ ]*\).*/\1/p' -e 's/^BENCH_CHAOS_SAVE_STARTED \([^ ]*\).*/\1/p' | tail -1)"
    if [ -n "${saved}" ] && ! printf '%s\n' "${out}" | grep -q '^BENCH_CHAOS_SAVE_FAILED '; then
        bench_warn "${INSTANCE_NAMES[$1]}: container log still being saved on the node when the session ended (${saved}); it completes there and the teardown pulls it"
        bench_manifest_note "log-save-unconfirmed: ${INSTANCE_NAMES[$1]} $2 at $(bench_now_iso); ${saved} was still being written when the session ended" || true
        return 0
    fi
    bench_warn "${INSTANCE_NAMES[$1]}: container log not saved ($2) — the ${2#pre-} goes ahead on schedule without it (the unit-stdout file has its output)"
    bench_manifest_note "log-save-failed: ${INSTANCE_NAMES[$1]} $2 at $(bench_now_iso); the ${2#pre-} went ahead without a saved log" || true
}

# chaos_staged <idx> <kill|start|restart> <due-unix> <log-label|""> <action-label> <note> [<extra-json>]
# — the action at <due> on the node's clock, from a session the loop opens BENCH_CHAOS_STAGE_SECS
# early (r20261006-0053: a poll, the log save and the IAP setup ran before the kill, 17 s late).
# A session that fails before BENCH_CHAOS_BEGIN falls back to the direct path at <due>
# (staged=false), without a log save of its own: a save before the action would delay it
# (r20261007-0316), and the unit's append file (<node>-unit-stdout.log.gz) has the container's
# output. One that fails after BEGIN is recorded as it ran. CHAOS_RC, CHAOS_BEGIN as record_chaos.
chaos_staged() {
    local idx="$1" act="$2" due="$3" save="$4" inst="${INSTANCE_NAMES[$1]}" rc=0 out
    bench_log "CHAOS ${inst}: $5 staged for $(bench_iso_from_unix "${due}") on the node's clock"
    out="$(chaos_stage_send "${idx}" "${act}" "${due}" "${save}" | tee -a "${BENCH_RESULTS_DIR}/chaos-remote.log")" || rc=$?
    [ -z "${out}" ] || printf '%s\n' "${out}" | sed 's/^/      /'
    if [ -n "$(chaos_mark BEGIN "${out}")" ]; then
        chaos_save_report "${idx}" "${save}" "${out}" || true
        record_chaos "${inst}" "$5" "$6" "${rc}" "${out}" "${due}" true "${7:-}"
        return 0
    fi
    bench_warn "${inst}: the staged $5 failed before it began (rc=${rc}) — the direct path runs it at $(bench_iso_from_unix "${due}")"
    chaos_save_report "${idx}" "${save}" "${out}" || true
    sleep_until "${due}" 0
    chaos_do "${idx}" "$(chaos_direct_cmd "${act}")" "$5" "$6" "${due}" "${7:-}"
}

# chaos_restart_v05 <note> [<due-unix>] — the restart owed after the kill: staged for <due> when
# one is given (the scheduled restart), else at once over the direct path (after an abort, at the
# end of the watch, from the EXIT trap). Until systemd confirms the unit active it stays owed
# (the watch loop tries again at each later poll), and the command to run by hand is printed.
chaos_restart_v05() {
    local inst="${INSTANCE_NAMES[$CHAOS_KILL_IDX]}" zone="${ZONES[$CHAOS_KILL_IDX]}"
    if [ -n "${2:-}" ]; then
        chaos_staged "${CHAOS_KILL_IDX}" start "$2" "" "systemctl start telcoin" "$1"
    else
        chaos_do "${CHAOS_KILL_IDX}" "$(chaos_direct_cmd start)" "systemctl start telcoin" "$1"
    fi
    if [ "${CHAOS_RC}" -eq 0 ]; then RUN_DID_BACK=1; BACK_BEGIN="${CHAOS_BEGIN}"; return 0; fi
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

# stop_blasters [tries] — docker stop txgen on every created blaster (blaster_created), each up to
# <tries> times (default 1). 1 (and the names, each with the command to run by hand) when a stop was
# not confirmed; every blaster is tried either way.
stop_blasters() {
    local k name failed=""
    RUN_STOPPED=1
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"
        blaster_created "$k" || continue
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

# next_action_due — "<due-unix> <action>" of the earliest chaos action still owed, or nothing. It
# reads do_run's chaos_on and t_kill/t_back/t_obs.
next_action_due() {
    [ "${chaos_on}" = "1" ] || return 0
    {
        [ -n "${ABORTED}" ] || [ "${RUN_DID_KILL}" -eq 1 ] || echo "${t_kill} kill"
        [ "${RUN_DID_KILL}" -eq 0 ] || [ "${RUN_DID_BACK}" -eq 1 ] || echo "${t_back} restart"
        [ -n "${ABORTED}" ] || [ "${RUN_DID_OBS}" -eq 1 ] || echo "${t_obs} observer-restart"
    } | sort -n | head -1
}

# poll_deferred <now> — 0, with next_poll moved to that action's due time, when a chaos action is
# due within BENCH_CHAOS_GUARD_SECS: a poll (serial reads and queries, ~40 s) must not run into the
# action's staged session (r20261006-0053: one that overran made the kill late). The poll then runs
# right after the action. Lag pause/unpause do not defer it: an unpause retried every minute would
# starve the abort watchers.
poll_deferred() {
    local due="" name=""
    read -r due name <<< "$(next_action_due)" || true
    [ -n "${due}" ] && [ "${due}" -gt "$1" ] && [ $(( due - $1 )) -le "${BENCH_CHAOS_GUARD_SECS}" ] || return 1
    echo "    poll deferred: ${name} due in $(( due - $1 ))s"
    next_poll="${due}"
}

# sleep_until <unix> [<floor-secs>] — sleep until <unix>, at least <floor> s (default 1). An overdue
# target is retried after 1 s; the old 5 s floor made a late kill later still.
sleep_until() {
    local s=$(( $1 - $(bench_now_unix) )) floor="${2:-1}"
    [ "${s}" -ge "${floor}" ] || s="${floor}"
    [ "${s}" -le 0 ] || sleep "${s}"
}

# status_samples <seen-ts> — "<ts> <block>" of each BENCH_STATUS line on stdin newer than <seen-ts>.
status_samples() {
    tr -d '\r' | awk -v seen="$1" '{ ts = ""; b = ""
        for (i = 1; i <= NF; i++) { if ($i ~ /^ts=/) ts = substr($i, 4); else if ($i ~ /^block=/) b = substr($i, 7) }
        if (ts ~ /^[0-9]+$/ && ts + 0 > seen + 0) print ts, b }'
}

# status_collect <idx> <BENCH_STATUS lines> — the node's samples since the last poll onto POLL_SAMPLES.
status_collect() {
    local new; new="$(printf '%s\n' "$2" | status_samples "${STATUS_SEEN[$1]:-0}")"
    [ -n "${new}" ] || return 0
    POLL_SAMPLES="${POLL_SAMPLES}${new}"$'\n'
    STATUS_SEEN[$1]="$(printf '%s\n' "${new}" | sort -n | tail -1 | cut -d' ' -f1)"
}

# fleet_round_at <unix> — the fleet's highest consensus round at that time (epoch*1e8+round, as
# bench_prom_rounds encodes it), from Prometheus with `offset`; nothing when unknown. The watcher's
# own reads are a poll (240 s) apart, too coarse to judge a stall. round_text <value> spells it out.
fleet_round_at() {
    local off=$(( $(bench_now_unix) - $1 )) l="${BENCH_PROM_NETWORK_LABEL}" o=""
    [ "${off}" -le 0 ] || o=" offset ${off}s"
    bench_prom_query "max(max by (node) (tn_epoch_current{network=\"${l}\"}${o}) * 100000000 + max by (node) (tn_primary_round{network=\"${l}\"}${o}))" 2>/dev/null \
        | jq -r 'select(.status == "success") | .data.result[0].value[1] // empty | tonumber | floor' 2>/dev/null || true
}
round_text() {
    case "$1" in ''|*[!0-9]*) printf '?' ;; *) printf '%s (epoch %s)' "$(( $1 % 100000000 ))" "$(( $1 / 100000000 ))" ;; esac
}

# commit_flat_check <samples> — a note, never an abort. <samples> are "<ts> <block>" lines, oldest
# first, from every node's BENCH_STATUS lines since the last poll. A commit stall is the fleet's
# highest block AND its highest consensus round standing still: blocks flat for at least
# BENCH_STALL_NOTE_SECS, and rounds up by at most BENCH_STALL_NOTE_MAX_ROUNDS over the last
# BENCH_STALL_NOTE_SECS of that (r20261006-0053: 301 s at block 15513, rounds +0 after the first
# 28 s). Blocks flat while rounds advance is an idle chain: empty consensus outputs are not
# executed, so blocks stop once the generators do (r20261006-0458 noted 213 s of that by mistake).
# A stall prints one line, and goes into .commit_stalls[] with a note when the block moves again;
# idle prints one line and is judged again at each poll. A stretch must start in the mixed phase
# (in cooldown the generator only drains); a later advance closes it, after cooldown too.
commit_flat_check() {
    local ts blk
    while read -r ts blk; do
        case "${ts}:${blk}" in *[!0-9:]*|:*|*:) continue ;; esac
        [ "${ts}" -ge "${STALL_WIN_START}" ] || continue
        if [ -n "${FLAT_BLOCK}" ] && [ "${blk}" -le "${FLAT_BLOCK}" ]; then FLAT_UNTIL="${ts}"; continue; fi
        [ -z "${FLAT_BLOCK}" ] || commit_flat_close "${ts}"
        FLAT_BLOCK="${blk}"; FLAT_SINCE="${ts}"; FLAT_UNTIL="${ts}"; FLAT_STATE=""
    done <<< "$1"
    commit_flat_judge
}

# commit_flat_judge — the current stretch, once blocks have been flat for BENCH_STALL_NOTE_SECS:
# stall when the rounds were flat over its last BENCH_STALL_NOTE_SECS, else idle. Unknown rounds
# leave it for the next poll. A stall stays one until the block moves.
commit_flat_judge() {
    local span=$(( FLAT_UNTIL - FLAT_SINCE )) r0 r1 d since
    { [ -n "${FLAT_BLOCK}" ] && [ "${FLAT_STATE}" != stall ] && [ "${FLAT_SINCE}" -lt "${STALL_MIXED_END}" ] \
        && [ "${span}" -ge "${BENCH_STALL_NOTE_SECS}" ]; } || return 0
    since="$(bench_iso_from_unix "${FLAT_SINCE}")"
    r0="$(fleet_round_at $(( FLAT_UNTIL - BENCH_STALL_NOTE_SECS )))"; r1="$(fleet_round_at "${FLAT_UNTIL}")"
    if [ -z "${r0}" ] || [ -z "${r1}" ] || [ "${r1}" -lt "${r0}" ]; then
        echo "    blocks flat at ${FLAT_BLOCK} since ${since} (${span}s); consensus rounds unknown — judged again at the next poll"
        return 0
    fi
    d=$(( r1 - r0 ))
    if [ "${d}" -le "${BENCH_STALL_NOTE_MAX_ROUNDS}" ]; then
        FLAT_STATE=stall; FLAT_ROUND="$(fleet_round_at "${FLAT_SINCE}")"; FLAT_ROUNDS_UP="${d}"
        echo "    ⚠ commits flat at block ${FLAT_BLOCK} since ${since} (${span}s; rounds +${d} in its last ${BENCH_STALL_NOTE_SECS}s, at $(round_text "${r1}")) — note only"
    elif [ "${FLAT_STATE}" != idle ]; then
        FLAT_STATE=idle
        echo "    idle: blocks flat at ${FLAT_BLOCK} since ${since} (${span}s), consensus rounds advancing (+${d} in ${BENCH_STALL_NOTE_SECS}s) — not a stall"
    fi
}

# commit_flat_close <end-unix> — the block moved again at <end> (a sample of this poll): the stretch
# is judged one last time, and a stall goes into .commit_stalls[].
commit_flat_close() {
    commit_flat_judge
    [ "${FLAT_STATE}" != stall ] || commit_stall_record "$1" false
    FLAT_STATE=""
}

# commit_stall_record <end-unix> <open: true|false> — the stall into .commit_stalls[] and a note.
# Its bounds are sample times; round_start/round_end are the rounds at those times.
commit_stall_record() {
    local r1 s e; r1="$(fleet_round_at "$1")"
    s="$(bench_iso_from_unix "${FLAT_SINCE}")"; e="$(bench_iso_from_unix "$1")"
    bench_manifest_jq --arg s "${s}" --arg e "${e}" --argjson secs "$(( $1 - FLAT_SINCE ))" --argjson b "${FLAT_BLOCK}" \
        --arg r0 "${FLAT_ROUND}" --arg r1 "${r1}" --argjson o "$2" '
        def num: if . == "" then null else tonumber end;
        .commit_stalls += [{start: $s, end: $e, secs: $secs, block: $b, round_start: ($r0|num), round_end: ($r1|num),
                            source: "watch"} + (if $o then {open: true} else {} end)]' || true
    bench_manifest_note "commit-stall (note only, no abort): the fleet's highest block stayed at ${FLAT_BLOCK} from ${s} to ${e}$([ "$2" = false ] || echo ' (still flat at the end of the watch)') ($(( $1 - FLAT_SINCE ))s between BENCH_STATUS samples); consensus rounds +${FLAT_ROUNDS_UP} in its last ${BENCH_STALL_NOTE_SECS}s, $(round_text "${FLAT_ROUND}") -> $(round_text "${r1}")" || true
}

# commit_flat_flush — at the end of the watch: a stall still flat goes in as open, ending at its
# last flat sample.
commit_flat_flush() {
    commit_flat_judge
    [ "${FLAT_STATE}" != stall ] || commit_stall_record "${FLAT_UNTIL}" true
    FLAT_BLOCK=""; FLAT_STATE=""
}

# chaos_schedule_refresh — epoch timing: the kill re-planned in the closing epoch once that epoch
# has opened, from its own start (recovery-schedule.py --epoch <closing> --before-close --downtime).
# The first plan projects the closing epoch at whole durations from the epoch it measured, but a
# loaded boundary waits for execution (bench 3: 12-26 s without a block), so each epoch in between
# can open late and the planned kill would land that much more than BENCH_CHAOS_BEFORE_CLOSE_SECS
# before the real close. No epoch opens before its projected start, so nothing is asked before
# then. Called at each poll while no kill has happened, and only while the kill is more than
# BENCH_CHAOS_GUARD_SECS + BENCH_CHAOS_STAGE_SECS away (the rest of the poll still ends before the
# kill's session opens): it moves t_kill, t_back and t_obs and the kill's `planned`, records
# .chaos_schedule_refresh (.chaos_schedule stays the first plan) and is done. An epoch not opened
# yet is asked again at the next poll. The read is bounded so it cannot eat into the kill's margin:
# it runs only through a tunnel already up (starting one waits longer than the margin allows) and
# under an alarm of BENCH_CHAOS_REFRESH_TIMEOUT_SECS (20); either miss leaves the plan as it was
# and is tried again at the next poll. BENCH_CHAOS_REFRESH_SCHEDULE=0 keeps the first plan.
# Reads do_run's recovery_schedule; sets its t_kill, t_back, t_obs and kill_extra.
chaos_schedule_refresh() {
    { [ "${BENCH_CHAOS_REFRESH_SCHEDULE:-1}" = 1 ] && [ -n "${recovery_schedule}" ] && [ "${SCHEDULE_REFRESHED}" -eq 0 ] \
        && [ -z "${ABORTED}" ] && [ "${RUN_DID_KILL}" -eq 0 ]; } || return 0
    local now epoch opens rec planned kill back start pidf rc=0 bound="${BENCH_CHAOS_REFRESH_TIMEOUT_SECS:-20}"
    now="$(bench_now_unix)"
    [ $(( t_kill - now )) -gt $(( BENCH_CHAOS_GUARD_SECS + BENCH_CHAOS_STAGE_SECS )) ] || return 0
    read -r epoch opens <<< "$(printf '%s' "${recovery_schedule}" | jq -r '"\(.closing_epoch) \(.boundary_unix - .duration_secs)"')" || true
    case "${epoch}:${opens}" in *[!0-9:]*|:*|*:) return 0 ;; esac
    [ "${now}" -ge "${opens}" ] || return 0
    pidf="$(bench_tunnel_pidfile)"
    if ! { [ -f "${pidf}" ] && kill -0 "$(cat "${pidf}" 2>/dev/null)" 2>/dev/null; }; then
        echo "    chaos schedule: the RPC tunnel is not up — not refreshed at this poll"
        return 0
    fi
    rec="$(perl -e 'alarm shift; exec @ARGV' "${bound}" python3 "${DIR}/recovery-schedule.py" --rpc-url "${RPC_URL}" \
        --epoch "${epoch}" --before-close "${BENCH_CHAOS_BEFORE_CLOSE_SECS}" --downtime "${BENCH_CHAOS_DOWNTIME_SECS}")" || rc=$?
    if [ "${rc}" -eq 142 ]; then
        echo "    chaos schedule: no answer from the registry within ${bound}s — not refreshed at this poll"
        return 0
    elif [ "${rc}" -ne 0 ]; then
        echo "    chaos schedule: closing epoch ${epoch} not opened (or not readable) yet — asked again at the next poll"
        return 0
    fi
    read -r kill back start <<< "$(printf '%s' "${rec}" | jq -r '"\(.kill_unix) \(.restart_unix) \(.epoch_start_unix)"')" || true
    case "${kill}:${back}:${start}" in *[!0-9:]*|:*|*:|*::*) echo "    chaos schedule: unreadable re-plan '${rec}' — the first plan stands"; return 0 ;; esac
    planned="${t_kill}"
    t_kill="${kill}"; t_back="${back}"; t_obs=$(( back + BENCH_CHAOS_OBS_AFTER_BACK_SECS ))
    kill_extra="$(printf '%s' "${rec}" | jq -c '{planned: {closing_epoch, boundary_unix, restart_unix}}')" || kill_extra=""
    SCHEDULE_REFRESHED=1
    bench_manifest_jq --argjson p "${planned}" --argjson k "${kill}" --argjson e "${epoch}" --argjson s "${start}" \
        --arg ts "$(bench_now_iso)" '.chaos_schedule_refresh = {planned_kill_unix: $p, kill_unix: $k,
            drift_secs: ($k - $p), closing_epoch: $e, epoch_start_unix: $s, ts: $ts}' || true
    echo "    chaos schedule: epoch ${epoch} opened $(bench_iso_from_unix "${start}"); kill moved $(( kill - planned ))s to $(bench_iso_from_unix "${t_kill}"), restart $(bench_iso_from_unix "${t_back}"), observer restart $(bench_iso_from_unix "${t_obs}")"
}

# chaos_boundary_check [final] — epoch timing, once the restart is confirmed: the block that opened
# epoch closing+1 (recovery-schedule.py --epoch), asked again at every poll until that epoch has
# opened. The outage crossed the boundary when kill begin < boundary < restart begin (node-side
# begin times). The verdict goes into .chaos[<kill>] (crossed_boundary, boundary_unix),
# .chaos_boundary and a note. "final" (the end of the watch) records an epoch still not opened.
# Reads do_run's recovery_schedule.
chaos_boundary_check() {
    { [ -n "${recovery_schedule}" ] && [ "${BOUNDARY_DONE}" -eq 0 ] && [ "${RUN_DID_BACK}" -eq 1 ]; } || return 0
    local epoch rec start crossed verdict times
    epoch=$(( $(printf '%s' "${recovery_schedule}" | jq -r .closing_epoch) + 1 ))
    times="the kill began $(bench_iso_from_unix "${KILL_BEGIN%.*}") and the restart $(bench_iso_from_unix "${BACK_BEGIN%.*}") (node clock)"
    bench_tunnel_up >/dev/null 2>&1 || true
    if ! rec="$(python3 "${DIR}/recovery-schedule.py" --rpc-url "${RPC_URL}" --epoch "${epoch}")"; then
        if [ "${1:-}" != final ]; then echo "    chaos boundary: epoch ${epoch} not opened (or not readable) yet — asked again at the next poll"; return 0; fi
        BOUNDARY_DONE=1
        bench_manifest_jq --argjson i "${KILL_ENTRY:-null}" 'if $i == null then . else .chaos[$i].crossed_boundary = null end' || true
        bench_manifest_note "chaos-boundary: epoch ${epoch} not opened by the end of the watch ($(bench_now_iso)); ${times}" || true
        echo "    chaos boundary: epoch ${epoch} not opened by the end of the watch"
        return 0
    fi
    start="$(printf '%s' "${rec}" | jq -r .epoch_start_unix)"
    crossed="$(awk -v k="${KILL_BEGIN}" -v s="${start}" -v r="${BACK_BEGIN}" 'BEGIN { print ((k < s && s < r) ? "true" : "false") }')"
    verdict="crossed"; [ "${crossed}" = true ] || verdict="did not cross"
    BOUNDARY_DONE=1
    bench_manifest_jq --argjson b "${rec}" --argjson i "${KILL_ENTRY:-null}" --argjson c "${crossed}" '.chaos_boundary = $b
        | if $i == null then . else .chaos[$i] += {crossed_boundary: $c, boundary_unix: $b.epoch_start_unix} end' || true
    bench_manifest_note "chaos-boundary: epoch ${epoch} opened at $(bench_iso_from_unix "${start}") (its closing block); ${times}: the outage ${verdict} the boundary" || true
    echo "    chaos boundary: the outage ${verdict} the boundary (epoch ${epoch} opened $(bench_iso_from_unix "${start}"))"
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

# poll_blasters — refresh DONE_LINE[]; returns 0 iff every created blaster (blaster_created) has reported.
poll_blasters() {
    local k name all=0
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        blaster_created "$k" || continue
        if [ -z "${DONE_LINE[k]:-}" ]; then
            name="$(blaster_name "$k")"
            DONE_LINE[k]="$(bench_serial_last "${name}" "${ZONES[$k]}" "BENCH_BLAST_DONE rc=" || true)"
            [ -n "${DONE_LINE[k]}" ] && echo "    ${name}: $(printf '%s' "${DONE_LINE[k]}" | sed 's/.*BENCH_BLAST_DONE/BENCH_BLAST_DONE/')"
        fi
        [ -n "${DONE_LINE[k]}" ] || all=1
    done
    return "${all}"
}

# Completion through the bucket (D40): from the planned mixed end, every BUCKET_CHECK_SECS one listing of
# this index's result files, where bench 5 waited up to BENCH_POLL_SECS (240 s) for the next serial poll.
BUCKET_CHECK_SECS=20; BUCKET_LS_ALARM_SECS=60

# bucket_done_check — one `gcloud storage ls <prefix>/*.json` (no IAP, no serial read); then, for each
# created blaster without a marker yet whose <name>.json is listed, its serial marker (blaster-startup.sh
# uploads the result file last and prints the marker right after). 0 when every created blaster has
# reported (poll_blasters' test). A listing that fails or matches nothing lists nothing.
bucket_done_check() {
    local prefix listing k name all=0
    prefix="$(bucket_prefix blasters)"
    listing="$(perl -e 'alarm shift; exec @ARGV' "${BUCKET_LS_ALARM_SECS}" gcloud storage ls "${prefix}/*.json" \
        --project="${PROJECT_ID}" </dev/null 2>/dev/null)" || listing=""
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        blaster_created "$k" || continue
        name="$(blaster_name "$k")"
        if [ -z "${DONE_LINE[k]:-}" ] && grep -qxF -- "${prefix}/${name}.json" <<< "${listing}"; then
            DONE_LINE[k]="$(bench_serial_last "${name}" "${ZONES[$k]}" "BENCH_BLAST_DONE rc=" || true)"
            [ -z "${DONE_LINE[k]}" ] || echo "    ${name}: $(printf '%s' "${DONE_LINE[k]}" | sed 's/.*BENCH_BLAST_DONE/BENCH_BLAST_DONE/') (result in the bucket)"
        fi
        [ -n "${DONE_LINE[k]:-}" ] || all=1
    done
    return "${all}"
}

# UNLANDED_LOOKUP_SECS — the generator's unlanded export: up to this long of lookups after the run,
# before it writes its results, whenever the landings export is on (contract H9b).
UNLANDED_LOOKUP_SECS=30

# done_wait_extra_secs — what every wait for the blasters' done markers adds for the generator's work
# after its cooldown: the tail scan (BENCH_TAIL_SCAN_SECS) and, with the landings export on
# (BENCH_LANDINGS_SAMPLE > 0), UNLANDED_LOOKUP_SECS. 0 with both off: bench 5's deadlines.
done_wait_extra_secs() {
    local x="${BENCH_TAIL_SCAN_SECS:-0}"
    [ "${BENCH_LANDINGS_SAMPLE:-0}" = 0 ] || x=$(( x + UNLANDED_LOOKUP_SECS ))
    printf '%s' "${x}"
}

# bucket_check_deferred <now> — 0, with next_check moved to that action's due time, when a chaos action
# is due within BENCH_CHAOS_GUARD_SECS (poll_deferred's test): the listing and its serial reads must not
# run into the action's staged session. The check then runs right after the action.
bucket_check_deferred() {
    local due=""
    read -r due _ <<< "$(next_action_due)" || true
    [ -n "${due}" ] && [ "${due}" -gt "$1" ] && [ $(( due - $1 )) -le "${BENCH_CHAOS_GUARD_SECS}" ] || return 1
    next_check="${due}"
}

# settle_blasters — copy this index's bucket prefix, then delete each blaster whose results are safe:
# the deletes in the background, then the describe loop until they are gone (await_deletes). A VM
# still there is named with the command that removes it, and does not fail the run (as before).
settle_blasters() {
    local k
    copy_prefix "$(bucket_prefix blasters)" blasters || true
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        settle_load_vm "$(blaster_name "$k")" "${ZONES[$k]}" blasters "${DONE_LINE[k]:-}" BENCH_BLAST_DONE delete_vm_bg
    done
    await_deletes || true
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
# they would start blasting unwatched at that time. Each blaster is described and, when it exists,
# deleted, all at once: the deletes race start_at. 1 when a delete failed; UNSTARTED_DELETED=1 when
# none did (on_run_exit's abort.unsent).
UNSTARTED_DELETED=0
delete_unstarted_blasters() {
    local k failed=0 pids=()
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        [ "${BENCH_APPLY}" = "1" ] || return 0
        ( [ -z "$(bench_instance_json "$(blaster_name "$k")" "${ZONES[$k]}")" ] || delete_vms "${ZONES[$k]}" "$(blaster_name "$k")" ) &
        pids+=("$!")
    done
    for k in "${!pids[@]}"; do wait "${pids[$k]}" || failed=1; done
    [ "${failed}" -ne 0 ] || UNSTARTED_DELETED=1
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
# never skips the next one. The record names the cause: a create that stopped the run
# (ABORT_REASON create_failed or late_create, set by create_blasters) with abort.unsent, true when
# every blaster was deleted before start_at so none can have sent; else interrupted/operator (D37).
on_run_exit() {
    local rc=$? started=1 wait_note="" why="interrupted" unsent="" wait_secs
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
    wait_secs=$(( BENCH_TRAP_WAIT_SECS + $(done_wait_extra_secs) ))
    if [ "${RUN_FINISHED}" -eq 0 ]; then
        [ "${RUN_CREATED}" -eq 0 ] || [ "${KEEP}" -eq 1 ] || [ "${started}" -eq 0 ] \
            || wait_note=" up to ${wait_secs}s of waiting for the blasters' results plus"
        [ -z "${ABORT_REASON}" ] || why="stopped (${ABORT_REASON} ${ABORT_NODE})"
        echo "❌ run ${why} (exit ${rc}) — restoring the fleet and securing results. This takes${wait_note} a few minutes of ssh and gcloud calls; INT, TERM and HUP are ignored until it ends (kill -9 $$ stops it and leaves the fleet as it is)" >&2
    fi
    # (a) the lag target: paused, it falls further behind every second
    if [ "${RUN_DID_PAUSE}" -eq 1 ] && [ "${RUN_DID_UNPAUSE}" -eq 0 ]; then
        exit_step "(a) unpause ${INSTANCE_NAMES[$BENCH_LAG_IDX]}" try_up_to 3 lag_unpause "owed unpause, performed by the EXIT trap"
    fi
    [ "${RUN_FINISHED}" -eq 1 ] && { blast_run_end "${rc}"; exit "${rc}"; }
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
    case "${ABORT_REASON}" in
        create_failed|late_create)
            unsent=false
            [ "${UNSTARTED_DELETED}" -ne 1 ] || [ "$(bench_now_unix)" -ge "${RUN_START_AT}" ] || unsent=true ;;
    esac
    record_abort "${ABORT_REASON:-interrupted}" "${ABORT_NODE:-operator}" \
        "${ABORT_DETAIL:-benchmark-blast.sh run exited rc=${rc} before completing}" "${unsent}"
    if [ "${RUN_CREATED}" -eq 1 ] && [ "${KEEP}" -eq 0 ] && [ "${started}" -eq 1 ]; then
        exit_step "(d) wait up to ${wait_secs}s for every blaster's done marker" wait_blasters_done "${wait_secs}"
        exit_step "(d) copy the results, delete each blaster whose results are safe" settle_blasters
    fi
    echo "    exit cleanup finished — exit ${rc}" >&2
    blast_run_end "${rc}"
    exit "${rc}"
}

# --- LOG_RATE: one node's unit-log growth (light-load arm, every blast) ----------------------
# log_rate_cmd — the remote command of one sample: "LOG_BYTES <bytes> <node unix time>", the size of
# the unit's stdout log (BENCH_NODE_UNIT_LOGS, the file the teardown pulls) plus its rotated
# siblings <file>.N[.gz], read under sudo as the pull reads them. Non-zero when that path is unusable.
log_rate_cmd() {
    local p f=""
    for p in ${BENCH_NODE_UNIT_LOGS}; do case "${p}" in stdout:/*) f="${p#stdout:}" ;; esac; done
    case "${f}" in ''|*[!A-Za-z0-9._/-]*) return 1 ;; esac
    printf '%s' "sudo sh -c 't=0; for g in ${f} ${f}.[0-9]*; do if [ -f \"\$g\" ]; then t=\$((t + \$(wc -c < \"\$g\"))); fi; done; echo \"LOG_BYTES \$t \$(date +%s)\"'"
}

# log_rate_sample <node-idx> — "<bytes> <node unix time>" from one ssh session (tn_iap_ssh, so
# devnet-lib's transport retry applies); non-zero and nothing printed when the session or its answer fails.
log_rate_sample() {
    local cmd out
    cmd="$(log_rate_cmd)" || return 1
    out="$(tn_iap_ssh "${INSTANCE_NAMES[$1]}" "${ZONES[$1]}" "${cmd}" </dev/null)" || return 1
    out="$(printf '%s\n' "${out}" | tr -d '\r' | sed -n 's/^LOG_BYTES \([0-9][0-9]*\) \([0-9][0-9]*\)$/\1 \2/p' | tail -1)"
    [ -n "${out}" ] || return 1
    printf '%s\n' "${out}"
}

# log_rate_mb_per_min <sample> <later sample> — MB (10^6 bytes) per minute between them, one decimal.
# Non-zero when a sample is missing, the node clock did not advance or the total shrank (the log
# rotated in between: copytruncate empties the file and delaycompress changes the siblings' sizes).
log_rate_mb_per_min() {
    [ -n "$1" ] && [ -n "$2" ] || return 1
    awk -v a="$1" -v b="$2" 'BEGIN { split(a, x, " "); split(b, y, " "); d = y[2] - x[2]; g = y[1] - x[1]
        if (d <= 0 || g < 0) exit 1; printf "%.1f\n", g / d * 60 / 1000000 }'
}

# log_rate_check <node-idx> <not-before-unix> — once the blasters send (not before <not-before>: their
# start plus the generator's preamble), the growth of that node's unit log over 60 s: two samples, one
# session each. Prints "LOG_RATE <inst> blast=<BENCH_RUN_INDEX> mb_per_min=<n.n>", with ⚠ when above
# BENCH_LOG_RATE_WARN_MB_MIN (a log filter that floods the teardown pull: tasks/lessons.md, sizing
# by bytes per minute), and appends {blast, inst, mb_per_min, warn} to the manifest's .log_rate list
# (one entry per measured blast, in run order; the archive of a blast keeps the list, so the live
# manifest holds every blast's). Never fatal: an unmeasured rate prints mb_per_min=? and records
# null. Runs before the watch loop's first poll.
log_rate_check() {
    local inst="${INSTANCE_NAMES[$1]}" b="${BENCH_RUN_INDEX:-0}" s0 s1 rate warn=false
    sleep_until "$2" 0
    bench_log "LOG_RATE: ${inst}'s unit log over 60 s"
    s0="$(log_rate_sample "$1")" || s0=""
    sleep 60
    s1="$(log_rate_sample "$1")" || s1=""
    rate="$(log_rate_mb_per_min "${s0}" "${s1}")" || rate=""
    if [ -z "${rate}" ]; then
        echo "LOG_RATE ${inst} blast=${b} mb_per_min=?"
        bench_warn "LOG_RATE ${inst}: not measured (a sample failed, or the log rotated between the samples); the run continues"
    elif awk -v m="${rate}" -v t="${BENCH_LOG_RATE_WARN_MB_MIN}" 'BEGIN { exit !(m > t) }'; then
        warn=true
        echo "LOG_RATE ${inst} blast=${b} mb_per_min=${rate} ⚠ above BENCH_LOG_RATE_WARN_MB_MIN=${BENCH_LOG_RATE_WARN_MB_MIN}: check the node log filter before the teardown pull (the run continues)"
    else
        echo "LOG_RATE ${inst} blast=${b} mb_per_min=${rate}"
    fi
    bench_manifest_jq --arg b "${b}" --arg i "${inst}" --arg m "${rate}" --argjson w "${warn}" \
        '.log_rate = ((.log_rate // []) | if type == "array" then . else [.] end)
            + [{blast: ($b | tonumber? // $b), inst: $i, mb_per_min: (if $m == "" then null else ($m | tonumber) end), warn: $w}]' \
        || bench_warn "LOG_RATE not recorded in $(bench_manifest)"
    return 0
}

# --- blaster creates: bounded, retried once, and never late (D36, D37, D39, D48) -------------------
# start_delay_secs — seconds from now to start_at: BENCH_START_DELAY_SECS, at least CREATE_WORST_SECS
# (two create calls and the describe between them), so a create that needs its one retry still fits.
# A light blast of the sequence (BENCH_BLAST_KIND=light) takes BENCH_LIGHT_START_DELAY_SECS as given,
# without that floor (D40: bench 5 idled about 2.5 min of every light blast's 300-s lead). The late-start
# guard, not the lead, keeps a short lead safe: every create call is cut at start_at -
# CREATE_LATE_LEAD_SECS, and a create not done by then stops the blast unsent (late_create), so the
# index is retried and no blaster ever starts late. At 150 s that limit falls 120 s after start_at is
# fixed. The work before the creates (the bench-obs check, ten existence describes, the token; bench 5's
# creates were all done about 60 s after the announce) plus one create call run to its
# CREATE_ALARM_SECS alarm (90 s) fits when that work stays under 30 s. A create that needs its retry,
# or slower work before the creates, costs one unsent attempt, never a late blaster.
start_delay_secs() {
    if [ "${BENCH_BLAST_KIND:-load}" = light ]; then printf '%s' "${BENCH_LIGHT_START_DELAY_SECS}"
    elif [ "${BENCH_START_DELAY_SECS}" -ge "${CREATE_WORST_SECS}" ]; then printf '%s' "${BENCH_START_DELAY_SECS}"
    else printf '%s' "${CREATE_WORST_SECS}"; fi
}

# create_errors <create-log> — what a failed create printed about why: each gcloud `ERROR:` line
# with its indented continuation, else the log's last 5 lines. Bench 5 printed the last 5 only, which
# after a crash are gcloud's "report this issue" boilerplate (D39).
create_errors() {
    local e
    e="$(awk '/^ERROR:/ { on = 1; print; next } on && /^[ \t]/ && !/^    \+ / { print; next } { on = 0 }' "$1" 2>/dev/null)" || e=""
    if [ -n "${e}" ]; then printf '%s\n' "${e}"; else tail -5 "$1" 2>/dev/null; fi
}

# create_error_detail <create-log> — the log's first `ERROR:` line, its indented continuation joined
# on (manifest .abort.detail); nothing when there is none.
create_error_detail() {
    awk '/^ERROR:/ { if (s != "") exit; s = $0; next }
         s != "" && /^[ \t]/ && !/^    \+ / { sub(/^[ \t]+/, ""); s = s " " $0; next }
         s != "" { exit }
         END { if (s != "") print s }' "$1" 2>/dev/null || true
}

# create_blasters <start_at> — the blasters, created in parallel (each create's output in
# logs/create-<name>.log; a dry run prints each create). Every create is bounded by the late-start
# limit, start_at - CREATE_LATE_LEAD_SECS (create_vm's <deadline>), and each one known to have
# succeeded goes into manifest blasters[] at once, with created_at, create_secs and attempts. Then
# the late-start guard: a create that failed twice or for good (create_failed) or that was not done
# by the limit (late_create) stops the run before any blaster can send. ABORT_* carry the cause into
# the EXIT trap, which deletes every blaster before start_at and records .abort with unsent
# (on_run_exit). A blaster that started late would blast into a run already under way, unrecorded
# (bench 5, D48).
create_blasters() {
    local start_at="$1" limit k name zone urls start log st end secs calls crc used note
    local failed="" failed_detail="" late="" late_detail="" err
    limit=$(( start_at - CREATE_LATE_LEAD_SECS ))
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"; zone="${ZONES[$k]}"
        [ "${NODE_ROLES[$k]}" = "validator" ] || bench_die "index ${k} is not a validator"
        urls="$(node_url "$k")"
        start=$(( k * BENCH_SENDERS + BENCH_RUN_INDEX * 100000 ))
        echo ">>> ${name} (${zone}) -> ${urls} senders ${BENCH_SENDERS}@${start}"
        if [ "${BENCH_APPLY}" != "1" ]; then create_vm "${name}" "${zone}" blast "${urls}" "${BENCH_SENDERS}" "${start}" "${start_at}"; continue; fi
        create_vm "${name}" "${zone}" blast "${urls}" "${BENCH_SENDERS}" "${start}" "${start_at}" "${limit}" \
            > "${BENCH_RESULTS_DIR}/logs/create-${name}.log" 2>&1 &
        CREATE_PIDS[k]=$!
    done
    [ "${BENCH_APPLY}" = "1" ] || return 0
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"; log="${BENCH_RESULTS_DIR}/logs/create-${name}.log"
        wait "${CREATE_PIDS[k]}" || true
        st=""; end=""; secs=""; calls=""; crc=""
        [ ! -f "${BENCH_RESULTS_DIR}/meta/${name}/CREATE" ] || read -r st end secs calls crc < "${BENCH_RESULTS_DIR}/meta/${name}/CREATE" || true
        if [ "${st}" = ok ]; then
            bench_manifest_jq --argjson b "$(blasters_json "$k")" '.blasters = ((.blasters // []) | map(select(.name != $b[0].name))) + $b' \
                || bench_warn "${name}: created, but not recorded in manifest blasters[] yet"
        fi
        if [ "${st}" = ok ] && [ "${end}" -le "${limit}" ]; then
            used="$(cat "${BENCH_RESULTS_DIR}/meta/${name}/MACHINE_TYPE" 2>/dev/null || true)"; note=""
            [ -z "${used}" ] || [ "${used}" = "${BENCH_BLASTER_MACHINE_TYPES%% *}" ] || note=", fallback after a stockout"
            [ "${calls:-1}" -le 1 ] || note="${note}, ${calls} create calls"
            echo "    ✓ created ${name} (${used:-type not recorded}${note})"
        elif [ "${st}" = ok ] || [ "${st}" = late ]; then
            err="$(create_error_detail "${log}")"
            echo "❌ create ${name} not done by the late-start limit $(bench_iso_from_unix "${limit}") (start_at - ${CREATE_LATE_LEAD_SECS} s)${end:+: it ended $(bench_iso_from_unix "${end}")}, ${calls:-0} create calls" >&2
            [ -n "${late}" ] || { late="${name}"
                late_detail="create not done by $(bench_iso_from_unix "${limit}") = start_at - ${CREATE_LATE_LEAD_SECS} s (${st}, ${calls:-0} create calls, ${secs:-?} s)${err:+; ${err}}"; }
        else
            echo "❌ create ${name} failed:" >&2
            create_errors "${log}" >&2
            [ -n "${failed}" ] || { failed="${name}"; failed_detail="$(create_error_detail "${log}")"
                [ -n "${failed_detail}" ] || failed_detail="create rc=${crc:-?} with no ERROR: line (logs/create-${name}.log)"; }
        fi
    done
    if [ -n "${failed}" ]; then
        ABORT_REASON=create_failed; ABORT_NODE="${failed}"; ABORT_DETAIL="${failed_detail}"
        bench_die "blaster creation failed (${failed}) — the exit cleanup deletes the blasters; if it cannot: benchmark/benchmark-blast.sh delete --yes"
    fi
    if [ -n "${late}" ]; then
        ABORT_REASON=late_create; ABORT_NODE="${late}"; ABORT_DETAIL="${late_detail}"
        bench_die "blaster ${late} was not created by start_at - ${CREATE_LATE_LEAD_SECS} s; no blaster may start late, so the exit cleanup deletes them all before start_at"
    fi
}

# record_late_secs <start_at> — manifest blasters[].late_secs: each blaster's own preamble start
# (run.phases in blasters/<name>.json) minus start_at, one decimal, with a ⚠ above 5 s. A blaster
# whose result file holds no preamble start gets none.
record_late_secs() {
    local k name p late
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"
        p="$(jq -r 'first((.run.phases // [])[] | select(.name == "preamble") | .start_unix | numbers) // empty' \
            "${BENCH_RESULTS_DIR}/blasters/${name}.json" 2>/dev/null)" || p=""
        [ -n "${p}" ] || continue
        late="$(awk -v p="${p}" -v s="$1" 'BEGIN { printf "%.1f", p - s }')"
        bench_manifest_jq --arg n "${name}" --argjson l "${late}" '.blasters |= map(if .name == $n then .late_secs = $l else . end)' \
            || bench_warn "${name}: late_secs ${late} not recorded"
        if awk -v l="${late}" 'BEGIN { exit !(l > 5) }'; then
            bench_warn "${name} began its preamble ${late}s after start_at $(bench_iso_from_unix "$1") (blasters[].late_secs)"
        fi
    done
}

# record_real_phases — D42: once every created blaster's result file (blasters/<name>.json) holds its
# run.phases, manifest .phases becomes the real schedule: per phase, the earliest start (rounded down)
# and the latest end (rounded up) over the blasters, in the blasters' phase order. The plan is kept as
# .phases_planned (a second rewrite keeps the first plan). Bench 5's planned phases put the idle chain
# after the load inside the planned cooldown, where the stall scan read it as a commit stall. Without
# every result the plan stays, and the line says why. The tail scan is not a phase: run.phases ends at
# the cooldown.
record_real_phases() {
    local k name f files=() missing="" real
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        blaster_created "$k" || continue
        name="$(blaster_name "$k")"; f="${BENCH_RESULTS_DIR}/blasters/${name}.json"
        if jq -e '[(.run.phases // [])[] | select((.start_unix | type) == "number" and (.end_unix | type) == "number")] | length > 0' \
                "${f}" >/dev/null 2>&1; then files+=("${f}")
        else missing="${missing} ${name}"; fi
    done
    if [ -n "${missing}" ] || [ "${#files[@]}" -eq 0 ]; then
        echo "    phases: kept as planned (no run.phases from:${missing:- any blaster})"; return 0
    fi
    real="$(jq -s -c '[.[] | (.run.phases // [])[] | select((.start_unix | type) == "number" and (.end_unix | type) == "number")] as $all
        | reduce ($all[] | .name) as $n ([]; if index([$n]) then . else . + [$n] end)
        | map(. as $n | [$all[] | select(.name == $n)]
              | {name: $n, start: (map(.start_unix) | min | floor | todate), end: (map(.end_unix) | max | ceil | todate)})' \
        "${files[@]}" 2>/dev/null)" || real=""
    [ -n "${real}" ] && [ "${real}" != "[]" ] || { echo "    phases: kept as planned (the blasters' run.phases could not be read)"; return 0; }
    bench_manifest_jq --argjson r "${real}" --arg n "phases rewritten at $(bench_now_iso) from the blasters' run.phases (earliest start, latest end per phase); the plan is phases_planned" \
        '(if has("phases_planned") then . else .phases_planned = (.phases // []) end) | .phases = $r | .notes += [$n]' \
        || { bench_warn "real phases not recorded in $(bench_manifest); .phases stays the plan"; return 0; }
    echo "    phases (real, the blasters' run.phases; the plan is kept as phases_planned): $(printf '%s' "${real}" \
        | jq -r 'map("\(.name) \(.start) - \(.end)") | join(", ")')"
}

# pool_at_start <start_at> — each node's transaction pool when the blast starts: reth's pending and queued
# sub-pool sizes (reth_transaction_pool_{pending,queued}_pool_transactions) from bench-obs's Prometheus,
# one bounded query for the fleet (bench_prom_query: 20 s), evaluated at start_at - 1 (with an offset
# when it runs later). A node's txpool_status RPC cannot stand in: TN serves no txpool_* method.
# Recorded as .blast.pool_at_start = {inst: {pending, queued}} (null for a node without a sample, every
# node null when the query failed); light_record copies it into blasts[]. Prints
#   POOL_AT_START blast=<index> at=<time> read=<n>/<nodes> queued_max=<q> (<inst>) pending_max=<p> (<inst>)
# and a ⚠ line naming every node above POOL_QUEUED_WARN queued: bench 5's load began with stale queued
# transactions from earlier blasts on three nodes, and those three evicted accepted ones. Record only:
# it waits for start_at (nothing in do_run is due before then) and never stops the run.
POOL_QUEUED_WARN=1000
pool_at_start() {
    local at=$(( $1 - 1 )) off o="" l="${BENCH_PROM_NETWORK_LABEL}" raw rec names b="${BENCH_RUN_INDEX:-0}" summary hot
    sleep_until "$1" 0
    off=$(( $(bench_now_unix) - at )); [ "${off}" -le 0 ] || o=" offset ${off}s"
    names="$(printf '%s\n' "${INSTANCE_NAMES[@]}" | jq -R -s -c 'split("\n") | map(select(. != ""))')"
    raw="$(bench_prom_query "{__name__=~\"reth_transaction_pool_(pending|queued)_pool_transactions\",network=\"${l}\"}${o}" 2>/dev/null)" || raw=""
    rec="$(printf '%s' "${raw}" | jq -c --argjson names "${names}" 'select(.status == "success")
        | [.data.result[] | {node: .metric.node, k: (.metric.__name__ | capture("_(?<k>pending|queued)_pool_").k),
                             v: (.value[1] | tonumber | floor)}] as $r
        | [$names[] as $n | {key: $n, value: ([$r[] | select(.node == $n)]
              | if length == 0 then null
                else {pending: ([.[] | select(.k == "pending") | .v] | max), queued: ([.[] | select(.k == "queued") | .v] | max)} end)}]
        | from_entries' 2>/dev/null)" || rec=""
    [ -n "${rec}" ] || rec="$(printf '%s' "${names}" | jq -c 'map({key: ., value: null}) | from_entries')"
    summary="$(printf '%s' "${rec}" | jq -r 'def top(k): ([to_entries[] | select(.value[k] != null)] | max_by(.value[k]) // null
            | if . == null then "?" else "\(.value[k]) (\(.key))" end);
        "read=\([.[] | select(. != null)] | length)/\(length) queued_max=\(top("queued")) pending_max=\(top("pending"))"')"
    echo "POOL_AT_START blast=${b} at=$(bench_iso_from_unix "${at}") ${summary}"
    hot="$(printf '%s' "${rec}" | jq -r --argjson w "${POOL_QUEUED_WARN}" \
        '[to_entries[] | select((.value.queued // 0) > $w) | "\(.key) (\(.value.queued))"] | join(", ")')"
    [ -z "${hot}" ] || bench_warn "POOL_AT_START blast=${b}: more than ${POOL_QUEUED_WARN} queued on ${hot}; stale transactions from earlier blasts take queued-pool room this blast needs (blast.pool_at_start)"
    bench_manifest_jq --argjson p "${rec}" '.blast.pool_at_start = $p' || bench_warn "pool_at_start not recorded in $(bench_manifest)"
    return 0
}

do_run() {
    preflight
    local k name now start_at mixed_start deadline extra
    [ -n "${OBSERVER_IDX}" ] || bench_die "no observer in NODE_ROLES"
    now="$(bench_now_unix)"
    if [ "${BENCH_BLAST_KIND:-load}" = light ]; then
        [ "${BENCH_LIGHT_START_DELAY_SECS}" -ge "${CREATE_WORST_SECS}" ] \
            || echo "    start_at lead: ${BENCH_LIGHT_START_DELAY_SECS}s (BENCH_LIGHT_START_DELAY_SECS, a light blast), not raised to ${CREATE_WORST_SECS}s: a create that needs its retry stops the blast unsent at start_at - ${CREATE_LATE_LEAD_SECS} s"
    else
        [ "${BENCH_START_DELAY_SECS}" -ge "${CREATE_WORST_SECS}" ] \
            || echo "    start_at lead: ${CREATE_WORST_SECS}s, not BENCH_START_DELAY_SECS=${BENCH_START_DELAY_SECS}: two create calls and the describe between them must fit before it"
    fi
    start_at=$(( now + $(start_delay_secs) ))
    RUN_START_AT="${start_at}"
    mixed_start=$(( start_at + BENCH_PREAMBLE_SECS + BENCH_WARMUP_SECS ))
    # Every wait for the done markers also covers the generator's tail scan and unlanded lookups.
    extra="$(done_wait_extra_secs)"
    deadline=$(( mixed_start + BENCH_DURATION_SECS + BENCH_COOLDOWN_SECS + 600 + extra ))
    echo ">>> run ${BENCH_RUN_ID} index ${BENCH_RUN_INDEX}: ${VAL_COUNT} blasters x ${BENCH_SENDERS} senders, start_at $(bench_iso_from_unix "${start_at}")"
    echo "    phases (planned): preamble ${BENCH_PREAMBLE_SECS}s, warmup ${BENCH_WARMUP_SECS}s, mixed ${BENCH_DURATION_SECS}s, cooldown ${BENCH_COOLDOWN_SECS}s$([ "${BENCH_TAIL_SCAN_SECS:-0}" = 0 ] || echo ", tail scan ${BENCH_TAIL_SCAN_SECS}s (not a phase)"); wait deadline $(bench_iso_from_unix "${deadline}")$([ "${extra}" = 0 ] || echo " (cooldown end + 600 s + ${extra} s for the tail scan and the unlanded lookups)")"
    local chaos_on="${BENCH_CHAOS:-1}"
    local t_kill=$(( mixed_start + BENCH_CHAOS_KILL_AT_SECS )) t_back=$(( mixed_start + BENCH_CHAOS_BACK_AT_SECS )) t_obs=$(( mixed_start + BENCH_CHAOS_OBS_AT_SECS ))
    local recovery_schedule=""
    # Every Prometheus read of the run (quorum-lost watcher, node health, commit-flat judge) goes
    # to bench-obs through its local forward, whatever the chaos timing: check the VM and open the
    # forward first. Fatal like the epoch read's tunnel below; no blaster exists yet.
    if [ "${BENCH_APPLY}" = "1" ]; then
        bench_obs_require || bench_die "bench-obs Prometheus is not reachable"
    fi
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
    resolve_node_urls
    archive_prev_blast
    record_blast "${start_at}"

    # --- create the blasters in parallel ---
    gcloud auth print-access-token >/dev/null
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
    create_blasters "${start_at}"
    [ "${BENCH_APPLY}" = "1" ] || { echo "DRY RUN — re-run with --yes."; return 0; }
    assert_load_vms

    # --- manifest: planned phases + blasters ---
    local p0="${start_at}" p1=$(( start_at + BENCH_PREAMBLE_SECS )) p2="${mixed_start}" p3=$(( mixed_start + BENCH_DURATION_SECS )) p4=$(( mixed_start + BENCH_DURATION_SECS + BENCH_COOLDOWN_SECS ))
    bench_manifest_ts blast_start_at "$(bench_iso_from_unix "${start_at}")"
    bench_manifest_jq --arg a "$(bench_iso_from_unix "${p0}")" --arg b "$(bench_iso_from_unix "${p1}")" \
        --arg c "$(bench_iso_from_unix "${p2}")" --arg d "$(bench_iso_from_unix "${p3}")" --arg e "$(bench_iso_from_unix "${p4}")" \
        '.phases = [{name:"preamble",start:$a,end:$b},{name:"warmup",start:$b,end:$c},{name:"mixed",start:$c,end:$d},{name:"cooldown",start:$d,end:$e}]
         | .notes += ["phases are PLANNED from BENCH_START_AT + configured durations; the per-blaster tn-blast/v2 run.phases are authoritative"]'
    bench_manifest_jq --argjson b "$(blasters_json)" '.blasters = $b'
    # The nodes' pools as the blast starts (Prometheus; record only).
    pool_at_start "${start_at}"
    # LOG_RATE: set by the light-load arm for each of its blasts (log_rate_check).
    [ "${BENCH_LOG_RATE_CHECK:-0}" != 1 ] || log_rate_check 0 "$(( start_at + BENCH_PREAMBLE_SECS ))"

    # --- watch loop: chaos + abort watchers + done markers ---
    # From the planned mixed end (the real one comes earlier when the preamble is shorter than planned)
    # completion is also read from the bucket every BUCKET_CHECK_SECS (bucket_done_check).
    local next_poll=$(( start_at + 60 )) all_done=0 target due back_due n next_check="${p3}"
    local kill_blaster; kill_blaster="$(blaster_name "${CHAOS_KILL_IDX}")"
    # Chaos actions open their session this early (chaos_staged); epoch timing plans the kill.
    local stage="${BENCH_CHAOS_STAGE_SECS}" kill_extra=""
    [ -z "${recovery_schedule}" ] \
        || kill_extra="$(printf '%s' "${recovery_schedule}" | jq -c '{planned: {closing_epoch, boundary_unix, restart_unix}}')"
    LAST_ADVANCE_TS="${start_at}"
    STALL_WIN_START="${mixed_start}"; STALL_MIXED_END="${p3}"
    while :; do
        now="$(bench_now_unix)"
        if [ "${chaos_on}" = "1" ] && [ -z "${ABORTED}" ] && [ "${RUN_DID_KILL}" -eq 0 ] && [ "${now}" -ge "$(( t_kill - stage ))" ]; then
            # A restart is owed from here on, even if the kill reports a failure: an exit while its
            # ssh is in flight may follow a kill that landed. When it did not land, the owed restart
            # is harmless: `systemctl start` on an active unit does nothing, and is-active passes.
            RUN_DID_KILL=1
            KILL_ENTRY="$(jq '.chaos | length' "$(bench_manifest)" 2>/dev/null || true)"
            chaos_staged "${CHAOS_KILL_IDX}" kill "${t_kill}" pre-kill "docker kill -s KILL telcoin" \
                "systemctl stop holds it down (unit has Restart=on-failure). ${kill_blaster} targets ONLY this node, so its sends fail for the outage by design; the generator resends on connection errors" \
                "${kill_extra}"
            KILL_BEGIN="${CHAOS_BEGIN}"
            # Epoch timing: the outage is BENCH_CHAOS_DOWNTIME_SECS from the kill's node-side begin.
            if [ "${BENCH_CHAOS_TIMING}" = epoch ]; then
                t_back=$(( ${KILL_BEGIN%.*} + BENCH_CHAOS_DOWNTIME_SECS ))
                t_obs=$(( t_back + BENCH_CHAOS_OBS_AFTER_BACK_SECS ))
                bench_manifest_jq --argjson due "${t_back}" '.chaos_restart_due_unix = $due'
            fi
            bench_manifest_note "blaster-05-outage: ${kill_blaster}'s only RPC target ${INSTANCE_NAMES[$CHAOS_KILL_IDX]} is down from $(bench_iso_from_unix "${KILL_BEGIN%.*}") (the kill's node-side begin) until its restart, due $(bench_iso_from_unix "${t_back}") (~$(( t_back - ${KILL_BEGIN%.*} ))s; chaos); its connection errors/resends in that window are the chaos, not a blaster fault" || true
        fi
        # The restart is owed even after an abort: never leave v05 down (then it runs at once, not
        # staged). Not confirmed, it is tried again at the next poll (t_back moves there), and at
        # each one after that until it is.
        if [ "${RUN_DID_KILL}" -eq 1 ] && [ "${RUN_DID_BACK}" -eq 0 ] && { [ "${now}" -ge "$(( t_back - stage ))" ] || [ -n "${ABORTED}" ]; }; then
            back_due="${t_back}"; [ -z "${ABORTED}" ] || back_due=""
            chaos_restart_v05 "docker start is impossible: the unit runs docker run --rm" "${back_due}" \
                || { n="$(bench_now_unix)"; t_back=$(( next_poll > n ? next_poll : n + BENCH_POLL_SECS )); }
            # Epoch timing: the observer restart follows this restart's node-side begin.
            if [ "${RUN_DID_BACK}" -eq 1 ] && [ "${BENCH_CHAOS_TIMING}" = epoch ]; then
                t_obs=$(( ${BACK_BEGIN%.*} + BENCH_CHAOS_OBS_AFTER_BACK_SECS ))
            fi
        fi
        if [ "${chaos_on}" = "1" ] && [ -z "${ABORTED}" ] && [ "${RUN_DID_OBS}" -eq 0 ] && [ "${now}" -ge "$(( t_obs - stage ))" ]; then
            chaos_staged "${OBSERVER_IDX}" restart "${t_obs}" pre-restart "systemctl restart telcoin" "observer restart"
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

        if [ "${now}" -ge "${next_poll}" ] && ! poll_deferred "${now}"; then
            bench_log "poll: blasters + node status + obs memory"
            chaos_schedule_refresh
            if poll_blasters; then all_done=1; else all_done=0; fi
            # nodes: disk + FatalDBFailure from the newest BENCH_STATUS (node-sampler.sh, serial
            # console); block= of every sample since the last poll feeds the commit-flat note only.
            local lines line inst pct fatal blk
            POLL_SAMPLES=""
            for k in "${!INSTANCE_NAMES[@]}"; do
                inst="${INSTANCE_NAMES[$k]}"
                lines="$(bench_serial "${inst}" "${ZONES[$k]}" | grep -F -- "BENCH_STATUS " || true)"
                line="$(printf '%s\n' "${lines}" | tail -1)"
                status_collect "${k}" "${lines}"
                [ -n "${line}" ] || { echo "    ${inst}: no BENCH_STATUS yet"; continue; }
                pct="$(status_field "${line}" root_used_pct)"; fatal="$(status_field "${line}" fatal_db)"
                blk="$(status_field "${line}" block)"
                echo "    ${inst}: root=${pct:-?}% fatal_db=${fatal:-?} block=${blk:-?}"
                if [ -n "${pct}" ] && [ "${pct}" -gt "${BENCH_ABORT_DISK_PCT}" ]; then record_abort "disk-full" "${inst}" "root disk ${pct}% > ${BENCH_ABORT_DISK_PCT}%"; fi
                if [ -n "${fatal}" ] && [ "${fatal}" -gt 0 ]; then record_abort "batch-cache-cliff" "${inst}" "FatalDBFailure x${fatal} in docker logs telcoin — batch-cache cliff, NOT a hardware limit"; fi
            done
            round_stall_check "${now}" "${all_done}"
            commit_flat_check "$(printf '%s' "${POLL_SAMPLES}" | sort -n)"
            node_health_check "${now}" || true
            local mem; mem="$(bench_obs_mem_pct || true)"
            echo "    ${BENCH_OBS_INSTANCE} memory: ${mem:-n/a}%"
            if [ -n "${mem}" ] && awk -v m="${mem}" -v t="${BENCH_ABORT_OBS_MEM_PCT}" 'BEGIN{exit !(m>t)}'; then
                record_abort "obs-memory" "${BENCH_OBS_INSTANCE}" "${BENCH_OBS_INSTANCE} memory ${mem}% > ${BENCH_ABORT_OBS_MEM_PCT}%"
            fi
            chaos_boundary_check
            next_poll=$(( now + BENCH_POLL_SECS ))
        fi
        # The bucket check: one listing, no IAP; it gives way to a chaos action due within the guard.
        if [ "${all_done}" -eq 0 ] && [ "${now}" -ge "${next_check}" ] && ! bucket_check_deferred "${now}"; then
            if bucket_done_check; then all_done=1; fi
            next_check=$(( now + BUCKET_CHECK_SECS ))
        fi

        if [ -n "${ABORTED}" ] && [ "${RUN_STOPPED}" -eq 0 ]; then
            bench_log "stopping blasters (docker stop txgen) after abort: ${ABORTED}"
            stop_blasters 1 || true
            deadline=$(( now + 600 + extra ))
            next_poll=$(( now + BENCH_POLL_SECS ))
            next_check=$(( now + BUCKET_CHECK_SECS ))             # stopped blasters upload what they have
            t_unpause=$(( t_unpause < now ? t_unpause : now ))    # an owed unpause runs on the next pass
            t_back=$(( t_back < now ? t_back : now ))             # and so does an owed restart
        fi
        [ "${all_done}" -eq 1 ] && { bench_log "all blasters reported BENCH_BLAST_DONE"; break; }
        [ "${now}" -lt "${deadline}" ] || { bench_warn "deadline reached before every blaster finished"; break; }

        target="${next_poll}"
        [ "${next_check}" -ge "${target}" ] || target="${next_check}"
        read -r due _ <<< "$(next_action_due)" || true
        [ -z "${due}" ] || [ $(( due - stage )) -ge "${target}" ] || target=$(( due - stage ))
        [ "${lag_on}" = "1" ] && [ -z "${ABORTED}" ] && [ "${RUN_DID_PAUSE}" -eq 0 ] && [ "${t_pause}" -lt "${target}" ] && target="${t_pause}"
        [ "${RUN_DID_PAUSE}" -eq 1 ] && [ "${RUN_DID_UNPAUSE}" -eq 0 ] && [ "${t_unpause}" -lt "${target}" ] && target="${t_unpause}"
        sleep_until "${target}"
    done

    # The loop can end (all done, abort, deadline) before the scheduled unpause or restart, or while
    # the restart still fails: each is owed now. A normal end clears the EXIT trap, so the last
    # tries before the run exits stand in for its steps (a) and (b).
    [ "${RUN_DID_PAUSE}" -eq 0 ] || [ "${RUN_DID_UNPAUSE}" -eq 1 ] || lag_unpause "owed unpause at the end of the watch" || true
    [ "${RUN_DID_KILL}" -eq 0 ] || [ "${RUN_DID_BACK}" -eq 1 ] || chaos_restart_v05 "owed restart at the end of the watch" || true
    chaos_boundary_check final
    commit_flat_flush

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
    record_late_secs "${start_at}"     # reads the result files settle_blasters copied in
    record_real_phases                 # so do they
    [ "${RUN_DID_PAUSE}" -eq 0 ] || [ "${RUN_DID_UNPAUSE}" -eq 1 ] || lag_unpause "last try before the run exits" || true
    [ "${RUN_DID_KILL}" -eq 0 ] || [ "${RUN_DID_BACK}" -eq 1 ] || chaos_restart_v05 "last try before the run exits" || true
    RUN_FINISHED=1
    trap - EXIT INT TERM HUP PIPE
    [ -z "${BLAST_RUN_STARTED}" ] || trap blast_run_exit EXIT     # a hand run's blast_runs[] entry
    if [ -n "${ABORTED}" ] || [ "${bad}" -ne 0 ]; then
        echo "❌ run finished with abort='${ABORTED}' / a blaster not at rc=0 reason=ok — see ${BENCH_RESULTS_DIR}" >&2
        exit 1
    fi
    echo "    ✓ run complete: ${BENCH_RESULTS_DIR}/blasters/"
}

# ================================ collect ============================================
# collect_missing <instance> <what> — a sampler file not copied: a warning and a manifest note, so
# the report never reads a missing file as a quiet node.
collect_missing() {
    bench_warn "$2 from $1 not copied"
    bench_manifest_note "collect: $2 from $1 not copied at $(bench_now_iso)" || true
}

# stall_scan — .commit_stalls_sampled from the sampler CSVs (stall-scan.py: the fleet's highest
# block per 30 s, flat for >= BENCH_STALL_NOTE_SECS inside the mixed phase and cooldown of
# manifest .phases: the blasters' real phases once record_real_phases rewrote them, else the plan).
# A note beside the watch's .commit_stalls, never fatal.
stall_scan() {
    local out
    echo "    commit stalls from sampler/*.csv: stall-scan.py --min-secs ${BENCH_STALL_NOTE_SECS}"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    if out="$(python3 "${DIR}/stall-scan.py" --results "${BENCH_RESULTS_DIR}" --min-secs "${BENCH_STALL_NOTE_SECS}")" \
        && bench_manifest_jq --argjson s "${out}" '.commit_stalls_sampled = $s'; then
        echo "      $(printf '%s' "${out}" | jq -r length) flat stretch(es) in .commit_stalls_sampled"
    else
        bench_warn "stall-scan failed — .commit_stalls_sampled not updated"
    fi
    return 0
}

do_collect() {
    local i inst
    echo ">>> collect ${BENCH_RUN_ID} -> ${BENCH_RESULTS_DIR}"
    bench_manifest_ts collect_start
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/sampler"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo "    ${inst}: sampler CSV (IAP scp)"
        bench_run bench_iap_scp_down "${inst}" "${ZONES[$i]}" "/var/lib/bench-sampler/${inst}.csv" "${BENCH_RESULTS_DIR}/sampler/${inst}.csv" \
            || collect_missing "${inst}" "sampler CSV"
        bench_run bench_iap_scp_down "${inst}" "${ZONES[$i]}" "/var/lib/bench-sampler/${inst}.epochs.txt" "${BENCH_RESULTS_DIR}/sampler/${inst}.epochs.txt" \
            || collect_missing "${inst}" "epoch inventory"
    done
    stall_scan
    copy_prefix "$(recorded_prefix blast blasters)" blasters || true
    copy_prefix "$(recorded_prefix fund funder)" funder || true
    # results/<run>/ is the only copy of the run: index it now, so an interrupted run has one too.
    bench_local_analysis
    # The certification outcome (manifest.certification, .cert_failures + log snapshots) needs the
    # node logs, so it is usually recorded by the teardown; never fatal here.
    bench_certification_record "${BENCH_RESULTS_DIR}/logs" "$(bench_manifest)" || bench_warn "certification not recorded"
    bench_cert_failures_snapshot "${BENCH_RESULTS_DIR}/logs" "$(bench_manifest)" || bench_warn "certification snapshots not taken"
    bench_local_index || bench_warn "INDEX.md / CHECKSUMS.sha256 not written — the teardown writes them"
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

# ================================ chaos-stage-test ===================================
# do_chaos_stage_test — one staged session (chaos_stage_send) against --instance with the action
# `true`, due BENCH_CHAOS_STAGE_SECS after it opens, as a blast stages its chaos; the node's
# container log is saved alongside as telcoin-stage-test-<UTC>.log.gz (the teardown pulls it with
# the other saved logs). Prints BEGIN/END, the lateness and the save's state; non-zero when the
# session, a marker or the action fails. A remote path tested only through stubs has never been parsed by a remote shell
# (tasks/lessons.md): run this once against a live node before a blast depends on it.
do_chaos_stage_test() {
    local idx due rc=0 out begin end late
    [ -n "${STAGE_INSTANCE}" ] || bench_die "chaos-stage-test needs --instance <node> (one of: ${INSTANCE_NAMES[*]})"
    idx="$(bench_index_of "${STAGE_INSTANCE}")" || bench_die "${STAGE_INSTANCE} is not a node of this fleet (${INSTANCE_NAMES[*]})"
    echo ">>> chaos-stage-test ${STAGE_INSTANCE} (${ZONES[$idx]}): save its container log in the background, wait for the due time on its clock, run 'true'"
    printf 'CHAOS_NODE=x\nCHAOS_ACTION=true\nCHAOS_DUE=0\nCHAOS_SAVE=\nCHAOS_LOG_DIR=/x\nCHAOS_MAX_WAIT=0\nCHAOS_SAVE_WAIT=0\n%s\n' "${CHAOS_STAGE_SCRIPT}" \
        | bash -n || bench_die "the staged chaos script does not parse (bash -n)"
    echo "    ✓ the staged script parses (bash -n)"
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "    + chaos_stage_send ${idx} true <now+${BENCH_CHAOS_STAGE_SECS}s> stage-test: CHAOS_* lines + CHAOS_STAGE_SCRIPT | TN_IAP_RETRIES=0 tn_iap_ssh_stdin ${STAGE_INSTANCE} ${ZONES[$idx]}"
        echo "      (dry run — not executed; --yes runs it)"
        return 0
    fi
    due=$(( $(bench_now_unix) + BENCH_CHAOS_STAGE_SECS ))
    out="$(chaos_stage_send "${idx}" true "${due}" stage-test)" || rc=$?
    [ -z "${out}" ] || printf '%s\n' "${out}" | sed 's/^/      /'
    begin="$(chaos_mark BEGIN "${out}")"; end="$(chaos_mark END "${out}")"
    { [ -n "${begin}" ] && [ -n "${end}" ]; } \
        || bench_die "${STAGE_INSTANCE}: no BENCH_CHAOS_BEGIN/END (ssh rc=${rc}) — the staged path does not work there; a blast would fall back to the direct path"
    [ "${rc}" -eq 0 ] || bench_die "${STAGE_INSTANCE}: the staged session ended rc=${rc}"
    case "${out}" in
        *BENCH_CHAOS_SAVED\ *) ;;
        *BENCH_CHAOS_SAVE_RUNNING\ *) bench_warn "${STAGE_INSTANCE}: container log still being saved ${BENCH_CHAOS_SAVE_WAIT_SECS}s after the action (it completes on the node)" ;;
        *) bench_warn "${STAGE_INSTANCE}: container log not saved (no telcoin container?)" ;;
    esac
    late="$(awk -v b="${begin}" -v d="${due}" 'BEGIN { printf "%.3f", b - d }')"
    echo "    due $(bench_iso_from_unix "${due}") (${due}); BEGIN ${begin}, END ${end} (node clock): late ${late}s"
    if awk -v l="${late}" 'BEGIN { exit !(l >= 0 && l < 1) }'; then echo "    ✓ the action began within 1 s of its due time"
    else bench_warn "the action began ${late}s from its due time (expected 0 <= late < 1)"; fi
}

# ================================ light-load arm =====================================
# BENCH_LIGHT_LOAD=1 (header): `fund` and `run` drive one single-blast invocation of this script per
# blast of the sequence. Each child is the plain bench-4 path (BENCH_LIGHT_LOAD=0) under its own
# BENCH_RUN_INDEX, so the index check, the archive, the funder copy and the bucket prefixes are the
# second-blast support's; the sequence adds the plan, the markers, manifest blasts[] and the stop.
LIGHT_IDX=(); LIGHT_SND=(); LIGHT_WIN=(); LIGHT_KIND=()

# light_plan — LIGHT_IDX / LIGHT_SND / LIGHT_WIN / LIGHT_KIND (light|load): the sequence's blasts in run
# order, indices counting up from BENCH_RUN_INDEX. A light entry's window is its BENCH_LIGHT_WINDOWS
# entry (config.sh checks there is one per BENCH_LIGHT_SENDERS entry), else BENCH_WINDOW.
light_plan() {
    local i="${BENCH_RUN_INDEX}" n w k=0 ws=() first="" firstw=""
    case "${i}" in ''|*[!0-9]*|0?*) bench_die "BENCH_RUN_INDEX='${i}' must be a non-negative integer" ;; esac
    LIGHT_IDX=(); LIGHT_SND=(); LIGHT_WIN=(); LIGHT_KIND=()
    for w in ${BENCH_LIGHT_WINDOWS:-}; do ws+=("${w}"); done
    for n in ${BENCH_LIGHT_SENDERS}; do
        w="${ws[$k]:-${BENCH_WINDOW}}"; k=$((k + 1))
        [ -n "${first}" ] || { first="${n}"; firstw="${w}"; }
        LIGHT_IDX+=("${i}"); LIGHT_SND+=("${n}"); LIGHT_WIN+=("${w}"); LIGHT_KIND+=(light); i=$((i + 1))
    done
    LIGHT_IDX+=("${i}"); LIGHT_SND+=("${BENCH_SENDERS}"); LIGHT_WIN+=("${BENCH_WINDOW}"); LIGHT_KIND+=(load); i=$((i + 1))
    if [ "${BENCH_LIGHT_LOAD_AFTER}" = 1 ]; then
        LIGHT_IDX+=("${i}"); LIGHT_SND+=("${first}"); LIGHT_WIN+=("${firstw}"); LIGHT_KIND+=(light)
    fi
}

# light_env <p> — the environment of plan entry <p>'s single-blast invocation, as NAME=<value> words
# (integers, and the word light): a light blast has its senders and window, the BENCH_LIGHT_*_SECS
# phases, no chaos and no lag injection, and BENCH_BLAST_KIND=light (its start delay, start_delay_secs);
# the configured profile keeps every setting but the index.
light_env() {
    printf 'BENCH_LIGHT_LOAD=0 BENCH_RUN_INDEX=%s' "${LIGHT_IDX[$1]}"
    [ "${LIGHT_KIND[$1]}" = light ] || return 0
    printf ' BENCH_SENDERS=%s BENCH_WINDOW=%s BENCH_WARMUP_SECS=%s BENCH_DURATION_SECS=%s BENCH_COOLDOWN_SECS=%s BENCH_CHAOS=0 BENCH_LAG_INJECT=0 BENCH_BLAST_KIND=light' \
        "${LIGHT_SND[$1]}" "${LIGHT_WIN[$1]}" "${BENCH_LIGHT_WARMUP_SECS}" "${BENCH_LIGHT_DURATION_SECS}" "${BENCH_LIGHT_COOLDOWN_SECS}"
}

# light_child <action> <p> [NAME=value...] — this script's <action> for plan entry <p> (light_env, then
# BENCH_BLAST_SEQUENCE=1 so the child records no blast_runs[] entry, then the extra words), --yes when
# this invocation has it. Its status.
light_child() {
    local action="$1" p="$2" yes=()
    shift 2
    [ "${CONFIRM}" -ne 1 ] || yes=(--yes)
    # shellcheck disable=SC2046  # light_env prints NAME=<value> words without spaces, split on purpose
    env $(light_env "${p}") BENCH_BLAST_SEQUENCE=1 "$@" bash "${DIR}/benchmark-blast.sh" "${action}" ${yes[@]+"${yes[@]}"} --run "${BENCH_RUN_ID}"
}

# light_show_plan <action> — the sequence, one line per blast.
light_show_plan() {
    local p
    echo ">>> light-load arm (BENCH_LIGHT_LOAD=1): $1 ${#LIGHT_IDX[@]} blasts on ${BENCH_RUN_ID}"
    for p in "${!LIGHT_IDX[@]}"; do
        if [ "${LIGHT_KIND[$p]}" = light ]; then
            echo "    index ${LIGHT_IDX[$p]}: light, ${LIGHT_SND[$p]} senders per blaster at window ${LIGHT_WIN[$p]}, warmup ${BENCH_LIGHT_WARMUP_SECS}s mixed ${BENCH_LIGHT_DURATION_SECS}s cooldown ${BENCH_LIGHT_COOLDOWN_SECS}s, chaos off, lag injection off"
        else
            echo "    index ${LIGHT_IDX[$p]}: the configured profile, ${LIGHT_SND[$p]} senders per blaster at window ${LIGHT_WIN[$p]}, warmup ${BENCH_WARMUP_SECS}s mixed ${BENCH_DURATION_SECS}s cooldown ${BENCH_COOLDOWN_SECS}s, chaos=${BENCH_CHAOS} lag_inject=${BENCH_LAG_INJECT}"
        fi
    done
}

# light_check_indices — refuse a plan index an earlier blast on this fleet used (its senders may have
# sent): nothing is funded or run; the next free base is named.
light_check_indices() {
    local used i next
    used="$(blast_indices_used)"
    for i in "${LIGHT_IDX[@]}"; do
        grep -qx "${i}" <<< "${used}" || continue
        next="$(printf '%s\n' "${used}" "${LIGHT_IDX[@]}" | grep -x '[0-9][0-9]*' | sort -n | tail -1)"
        bench_die "light-load arm: an earlier blast on this fleet used BENCH_RUN_INDEX=${i} (the sequence is ${LIGHT_IDX[*]}); fund and run it under a new base: BENCH_RUN_INDEX=$(( next + 1 )). Nothing was funded or run."
    done
}

# arm_in_force <time> — the name of the param_arms[] entry in force at <time>: the latest whose begin
# is at or before it (MANIFEST-FIELDS blasts[].arm). A new arm closes the open one, so that is the open
# arm when there is one; nothing when the manifest has no arm.
arm_in_force() {
    jq -r --arg t "$1" '[(.param_arms // [])[] | select(type == "object" and (.begin | type) == "string" and .begin <= $t)]
        | last | .name // empty' "$(bench_manifest)" 2>/dev/null || true
}

# light_record <p> <started> <ended> <rc> [<arm>] — with --yes, manifest blasts[] += plan entry <p>'s
# blast: {index, senders, window, chaos, started, ended, rc, kind (light|load), arm (null: none)}, and
# from the child's own record when the live manifest holds it (.blast.run_index is this index):
# phases (+ phases_planned once they are real, record_real_phases) and pool_at_start.
light_record() {
    [ "${BENCH_APPLY}" = "1" ] || return 0
    local chaos=0
    [ "${LIGHT_KIND[$1]}" = light ] || chaos="${BENCH_CHAOS}"
    bench_manifest_jq --argjson i "${LIGHT_IDX[$1]}" --argjson s "${LIGHT_SND[$1]}" --argjson w "${LIGHT_WIN[$1]}" \
        --argjson c "${chaos}" --arg a "$2" --arg e "$3" --argjson rc "$4" --arg k "${LIGHT_KIND[$1]}" --arg arm "${5:-}" \
        '(if (.blast.run_index // null) == $i then
              (if (.phases // []) != [] then {phases: .phases} else {} end)
              + (if has("phases_planned") then {phases_planned: .phases_planned} else {} end)
              + (if (.blast | has("pool_at_start")) then {pool_at_start: .blast.pool_at_start} else {} end)
          else {} end) as $own
         | .blasts = (.blasts // []) + [{index: $i, senders: $s, window: $w, chaos: $c, started: $a, ended: $e, rc: $rc,
                                         kind: $k, arm: (if $arm == "" then null else $arm end)} + $own]' \
        || bench_warn "blasts[] not updated in $(bench_manifest) (index ${LIGHT_IDX[$1]} rc=$4)"
}

# light_stop <action> <rc> <p> [<p>...] — plan entry <p> ended rc != 0: print the whole command
# sequence that finishes the arm by hand (the entries given, in order, then the collect step the deploy
# would have run next: step 15), exit <rc>. A blast that ran may have sent from its senders, so a
# failed `run` entry is funded and run again under a fresh index, one past every index used or
# planned; the entries after it keep their funded, unused indices. Each `run` line carries
# BENCH_LOG_RATE_CHECK=1, as the sequence gives every child (bench 5's hand-run load had no LOG_RATE,
# D38). A failed fund has spent nothing: the remaining funds keep their indices, then the sequence's
# `run` follows.
light_stop() {
    local action="$1" rc="$2" p="$3" q f fresh cmd="benchmark/benchmark-blast.sh"
    local collect="benchmark/benchmark-deploy.sh --yes --from 15 --to 15 --run ${BENCH_RUN_ID}"
    shift 2
    echo "❌ light-load arm: ${action} of index ${LIGHT_IDX[$p]} (${LIGHT_KIND[$p]}, ${LIGHT_SND[$p]} senders per blaster at window ${LIGHT_WIN[$p]}) ended rc=${rc}; the sequence stopped there" >&2
    echo "   Resume by hand, one command at a time, each once the one before it succeeded (the last is the collect, deploy step 15):" >&2
    if [ "${action}" = fund ]; then
        for q in "$@"; do echo "     $(light_env "${q}") ${cmd} fund --yes --run ${BENCH_RUN_ID}" >&2; done
        echo "     BENCH_LIGHT_LOAD=1 BENCH_RUN_INDEX=${LIGHT_IDX[0]} ${cmd} run --yes --run ${BENCH_RUN_ID}" >&2
        echo "     ${collect}" >&2
        exit "${rc}"
    fi
    fresh="$( { blast_indices_used; printf '%s\n' "${LIGHT_IDX[@]}"; } | grep -x '[0-9][0-9]*' | sort -n | tail -1)"
    LIGHT_IDX[p]=$(( fresh + 1 ))
    echo "     $(light_env "${p}") ${cmd} fund --yes --run ${BENCH_RUN_ID}" >&2
    for q in "$@"; do echo "     $(light_env "${q}") BENCH_LOG_RATE_CHECK=1 ${cmd} run --yes --run ${BENCH_RUN_ID}" >&2; done
    echo "     ${collect}" >&2
    echo "   blasts[] records this sequence's blasts only; a blast run by hand is recorded in its own manifest .blast and in blast_runs[]." >&2
    [ "${LIGHT_KIND[$q]}" = load ] \
        || echo "   A light blast run by hand after the load stays current: the configured profile's outputs are then in its blast-<index>-<UTC>/, and step 15 collects the light blast." >&2
    for f in "$@"; do
        [ "${LIGHT_KIND[$f]}" = light ] || continue
        echo "   A light blast run by hand is not in blasts[], so the floor KPIs miss it: pass its blast-<index>-<UTC>/ as --floor-blast-dir to report/make_bundle.py and report/kpis.py." >&2
        break
    done
    exit "${rc}"
}

# light_swap_back — after the light blast that follows the load: archive it like any blast, then move
# the configured profile's outputs back from the blast-<its index>-<UTC>/ that blast's run archived them
# into, and make that directory's manifest copy the live manifest again with the live notes, blasts[]
# and log_rate. The emptied directory goes. Dry run: the plan only.
light_swap_back() {
    local r="${BENCH_RESULTS_DIR}" load="" p d src="" it items=() m tmp
    for p in "${!LIGHT_KIND[@]}"; do [ "${LIGHT_KIND[$p]}" != load ] || load="${LIGHT_IDX[$p]}"; done
    for d in "${r}/blast-${load}-"*; do [ -d "${d}" ] || continue; src="${d}"; done   # the newest: UTC stamps sort
    echo ">>> light-load arm: archive the light blast after the load, move the configured profile (index ${load}) back into place"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — nothing moved)"; return 0; fi
    { [ -n "${src}" ] && [ -f "${src}/manifest.json" ]; } \
        || bench_die "light-load arm: no blast-${load}-<UTC>/ with a manifest.json in ${r}; nothing was moved: the light blast after the load is current, the configured profile's outputs are where its run put them"
    archive_blast_outputs
    while IFS= read -r it; do items+=("${it}"); done < <(blast_items_in "${src}")
    [ "${#items[@]}" -eq 0 ] || for it in "${items[@]}"; do
        if [ -e "${r}/${it}" ] || ! mkdir -p "${r}/$(dirname "${it}")" || ! mv "${src}/${it}" "${r}/${it}"; then
            bench_die "light-load arm: could not move ${it} back from ${src}/ — what moved is in ${r}, the rest (and the manifest copy) is still in ${src}/"
        fi
    done
    m="$(bench_manifest)"
    tmp="$(mktemp "${m}.XXXXXX")" \
        || bench_die "light-load arm: index ${load}'s outputs are back in ${r} but no temporary file could be made next to ${m}; its manifest copy ${src}/manifest.json is not live yet: put it in place of ${m} by hand"
    if jq --slurpfile live "${m}" '$live[0] as $l | . + {notes: ($l.notes // []), blasts: ($l.blasts // [])}
            | if ($l | has("log_rate")) then .log_rate = $l.log_rate else . end' "${src}/manifest.json" > "${tmp}"; then
        mv "${tmp}" "${m}"
    else
        rm -f "${tmp}"
        bench_die "light-load arm: index ${load}'s outputs are back in ${r} but its manifest copy ${src}/manifest.json could not be made live"
    fi
    rm -f "${src}/manifest.json"
    find "${src}" -depth -type d -empty -exec rmdir {} + 2>/dev/null || true
    [ ! -e "${src}" ] || bench_warn "light-load arm: ${src} still holds files after the move back; left in place"
    bench_manifest_note "light-load arm: index ${load} (the configured profile) moved back from $(basename "${src}")/ at $(bench_now_iso)" || true
    echo "    ✓ ${r}/blasters/ holds index ${load} again"
}

# light_fund — `fund`: one single-blast fund per blast of the sequence, the configured profile's last,
# so funder/ and manifest .fund end with its output as after a plain fund (the light indices' are
# moved aside into funder-<index>-<UTC>/ by the next fund).
light_fund() {
    local p order=() rc k
    light_plan
    light_check_indices
    for p in "${!LIGHT_IDX[@]}"; do [ "${LIGHT_KIND[$p]}" = load ] || order+=("${p}"); done
    for p in "${!LIGHT_IDX[@]}"; do [ "${LIGHT_KIND[$p]}" != load ] || order+=("${p}"); done
    light_show_plan fund
    for k in "${!order[@]}"; do
        p="${order[$k]}"; rc=0
        echo ">>> light-load arm: fund index ${LIGHT_IDX[$p]} (${LIGHT_KIND[$p]}, ${LIGHT_SND[$p]} senders per blaster)"
        light_child fund "${p}" || rc=$?
        [ "${rc}" -eq 0 ] || light_stop fund "${rc}" "${order[@]:$k}"
    done
    [ "${BENCH_APPLY}" = "1" ] || { echo "DRY RUN (light-load arm) — re-run with --yes."; return 0; }
    echo "    ✓ light-load arm: indices ${LIGHT_IDX[*]} funded"
}

# light_run — `run`: each blast in order, LIGHT_LOAD_START/DONE around the light ones (a dry run
# prints a plan line instead: a log watcher must not read a plan as a run), blasts[] after every
# one, the stop at the first rc != 0; every blast also measures LOG_RATE, the configured profile's
# under load too (each child gets BENCH_LOG_RATE_CHECK set to 1, whatever the caller's environment holds).
light_run() {
    local p rc started ended arm
    light_plan
    light_check_indices
    light_show_plan run
    for p in "${!LIGHT_IDX[@]}"; do
        if [ "${LIGHT_KIND[$p]}" != light ]; then echo ">>> light-load arm: the configured profile, index ${LIGHT_IDX[$p]}"
        elif [ "${BENCH_APPLY}" = "1" ]; then echo "LIGHT_LOAD_START i=${LIGHT_IDX[$p]} senders=${LIGHT_SND[$p]} window=${LIGHT_WIN[$p]}"
        else echo ">>> light-load arm (plan): light blast, index ${LIGHT_IDX[$p]}, ${LIGHT_SND[$p]} senders per blaster at window ${LIGHT_WIN[$p]}"; fi
        started="$(bench_now_iso)"; rc=0
        arm="$(arm_in_force "${started}")"
        light_child run "${p}" BENCH_LOG_RATE_CHECK=1 || rc=$?
        ended="$(bench_now_iso)"
        light_record "${p}" "${started}" "${ended}" "${rc}" "${arm}"
        [ "${LIGHT_KIND[$p]}" != light ] || [ "${BENCH_APPLY}" != "1" ] || echo "LIGHT_LOAD_DONE i=${LIGHT_IDX[$p]} rc=${rc}"
        [ "${rc}" -eq 0 ] || light_stop run "${rc}" $(seq "${p}" $(( ${#LIGHT_IDX[@]} - 1 )))
    done
    [ "${LIGHT_KIND[$p]}" = load ] || light_swap_back
    [ "${BENCH_APPLY}" = "1" ] || { echo "DRY RUN (light-load arm) — re-run with --yes."; return 0; }
    echo "    ✓ light-load arm complete: indices ${LIGHT_IDX[*]}; the configured profile's outputs are in ${BENCH_RESULTS_DIR}/blasters/"
}

# ================================ hand runs (D46) ====================================
# blast_caller — who started this invocation: "sequence" (a child of the light-load arm: light_child
# sets BENCH_BLAST_SEQUENCE=1), "deploy" (benchmark-deploy.sh steps 13 and 14: this process's parent runs
# that script) or "hand".
blast_caller() {
    [ "${BENCH_BLAST_SEQUENCE:-0}" != 1 ] || { echo sequence; return 0; }
    case "$(ps -o args= -p "${PPID}" 2>/dev/null)" in *benchmark-deploy.sh*) echo deploy ;; *) echo hand ;; esac
}

BLAST_RUN_STARTED=""; BLAST_RUN_RECORDED=0

# blast_run_begin — with --yes, a `fund` or `run` started by hand records its blast_runs[] entry on
# its way out (blast_run_exit as the EXIT trap; do_run's own trap calls blast_run_end). The deploy
# records its steps in deploy_runs[] and the sequence its blasts in blasts[]; bench 5's hand-run fund
# and run after an abort were in neither (D46).
blast_run_begin() {
    [ "${BENCH_APPLY}" = "1" ] || return 0
    case "${ACTION}" in fund|run) ;; *) return 0 ;; esac
    [ "$(blast_caller)" = hand ] || return 0
    BLAST_RUN_STARTED="$(bench_now_iso)"
    trap blast_run_exit EXIT
}

# blast_run_end <rc> — once per hand run: manifest blast_runs[] += {action, index, started, ended, rc,
# log} (log: this invocation's output copy, relative to results/<run>/; null without one), and
# timestamps.step_14_done when a `run` ended rc 0, as deploy step 14 sets it. Never fails.
blast_run_end() {
    [ -n "${BLAST_RUN_STARTED}" ] && [ "${BLAST_RUN_RECORDED}" -eq 0 ] || return 0
    BLAST_RUN_RECORDED=1
    bench_manifest_jq --arg a "${ACTION}" --arg i "${BENCH_RUN_INDEX:-}" --arg s "${BLAST_RUN_STARTED}" --arg e "$(bench_now_iso)" \
        --argjson rc "$1" --arg l "${BLAST_LOG#"${BENCH_RESULTS_DIR}"/}" \
        '.blast_runs = ((.blast_runs // []) + [{action: $a, index: ($i | tonumber? // $i), started: $s, ended: $e, rc: $rc,
                                               log: (if $l == "" then null else $l end)}])' \
        || bench_warn "blast_runs[] not updated in $(bench_manifest) (${ACTION} rc=$1)"
    if [ "${ACTION}" = run ] && [ "$1" -eq 0 ]; then bench_manifest_ts step_14_done || true; fi
    return 0
}

# blast_run_exit — the EXIT trap of a hand run outside do_run's own: its entry, then the same exit status.
blast_run_exit() {
    local rc=$?
    set +eu
    blast_run_end "${rc}"
    exit "${rc}"
}

blast_run_begin
case "${BENCH_LIGHT_LOAD:-0}:${ACTION}" in
    1:fund|1:run)
        [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"
        [ "${KEEP}" -eq 0 ] || bench_die "--keep cannot be used with BENCH_LIGHT_LOAD=1: the next blast of the sequence needs the load VMs' names"
        start_blast_log "light-${ACTION}"
        if [ "${ACTION}" = fund ]; then light_fund; else light_run; fi
        exit 0 ;;
esac

start_blast_log
case "${ACTION}" in
    fund)    [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"; do_fund ;;
    run)     [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"; do_run ;;
    collect) do_collect ;;
    delete)  do_delete ;;
    status)  do_status ;;
    chaos-stage-test) [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"; do_chaos_stage_test ;;
esac
