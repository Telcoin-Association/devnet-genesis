#!/usr/bin/env bash
#
# benchmark-blast.sh — drive load against the bench fleet from per-zone COS VMs.
#
#   fund     one bench-funder VM in ZONES[0] runs `blast --prepare` for the whole sender
#            range [RUN_INDEX*100000, +10*BENCH_SENDERS) against bench-validator-01, waits for
#            BENCH_FUND_DONE on its serial console, copies gs://<bucket>/<run>/funder/ into
#            results/<run>/funder/, then deletes the VM (unless --keep).
#   run      bench-blaster-01..10, one per validator in the validator's zone, all starting at
#            BENCH_START_AT=now+BENCH_START_DELAY_SECS. Runs the chaos schedule (kill -9
#            bench-validator-05 at mixed+15 min, restart it at mixed+20 min, restart the
#            observer at mixed+25 min) and the abort watchers, waits for every
#            BENCH_BLAST_DONE, copies gs://<bucket>/<run>/blasters/ into results/<run>/blasters/,
#            deletes the blasters (unless --keep).
#   collect  sampler CSVs from every bench node (IAP scp) into results/<run>/sampler/ and the
#            bucket's run prefix into results/<run>/.
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
        -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
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
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"

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
    if [ "${BENCH_APPLY}" = "1" ]; then
        gcloud artifacts docker images describe "${BENCH_TXGEN_IMAGE}" --format='value(image_summary.digest)' >/dev/null 2>&1 \
            || bench_die "image ${BENCH_TXGEN_IMAGE} not found (benchmark-deploy.sh step 1)"
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
    meta="${meta}##BENCH_BUCKET=${BENCH_BUCKET}##RUN_ID=${BENCH_RUN_ID}##LABEL=${name}"
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

marker_rc() { sed -n "s/.*$1 rc=\([0-9][0-9]*\).*/\1/p" | tail -1; }

copy_prefix() { # <gcs-subdir> -> results/<run>/<subdir>/
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/$1"
    bench_run gcloud storage cp -r "gs://${BENCH_BUCKET}/${BENCH_RUN_ID}/$1/*" "${BENCH_RESULTS_DIR}/$1/" || bench_warn "copy of gs://${BENCH_BUCKET}/${BENCH_RUN_ID}/$1 failed"
}

# ================================ fund ===============================================
do_fund() {
    preflight
    local zone="${ZONES[0]}" urls senders start rc line
    urls="$(node_url 0)"
    senders=$(( VAL_COUNT * BENCH_SENDERS ))
    start=$(( BENCH_RUN_INDEX * 100000 ))
    echo ">>> fund: ${FUNDER} (${zone}) --prepare senders=${senders} sender-start=${start} against ${urls}"
    if [ -n "$(bench_instance_json "${FUNDER}" "${zone}")" ]; then
        bench_die "${FUNDER} already exists — inspect/delete it first (benchmark-blast.sh delete --yes)"
    fi
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
    copy_prefix funder
    bench_manifest_ts fund_end
    bench_manifest_note "fund: ${line}"
    [ "${KEEP}" -eq 1 ] || delete_vms "${zone}" "${FUNDER}"
    [ "${rc:-1}" = "0" ] || bench_die "funding failed (${line})"
    echo "    ✓ funded"
}

# ================================ run ================================================
ABORTED=""
record_abort() { # <reason> <node> <detail>
    [ -n "${ABORTED}" ] && return 0
    ABORTED="$1"
    echo "❌❌ ABORT: $1 node=$2 — $3" >&2
    bench_manifest_jq --arg ts "$(bench_now_iso)" --arg r "$1" --arg n "$2" --arg d "$3" \
        '.abort = {ts: $ts, reason: $r, node: $n, detail: $d}'
}

record_chaos() { # <node> <action> <note> <rc>
    bench_manifest_jq --arg ts "$(bench_now_iso)" --arg n "$1" --arg a "$2" --arg note "$3" --arg rc "$4" \
        '.chaos += [{ts: $ts, node: $n, action: $a, note: $note, rc: ($rc|tonumber)}]'
}

# chaos_do <idx> <remote-cmd> <action-label> <note>
chaos_do() {
    local inst="${INSTANCE_NAMES[$1]}" zone="${ZONES[$1]}" rc=0
    bench_log "CHAOS ${inst}: $3"
    tn_iap_ssh "${inst}" "${zone}" "$2" || rc=$?
    record_chaos "${inst}" "$3" "$4" "${rc}"
}

stop_blasters() {
    local k
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        tn_iap_ssh "$(blaster_name "$k")" "${ZONES[$k]}" "sudo docker stop -t 30 txgen >/dev/null 2>&1; true" || true
    done
}

# status_field <line> <key> — value of key=... in a BENCH_STATUS line.
status_field() { printf '%s' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p" | tail -1; }

do_run() {
    preflight
    local k name zone urls start now start_at mixed_start deadline
    [ -n "${OBSERVER_IDX}" ] || bench_die "no observer in NODE_ROLES"
    now="$(bench_now_unix)"
    start_at=$(( now + BENCH_START_DELAY_SECS ))
    mixed_start=$(( start_at + BENCH_PREAMBLE_SECS + BENCH_WARMUP_SECS ))
    deadline=$(( mixed_start + BENCH_DURATION_SECS + BENCH_COOLDOWN_SECS + 600 ))
    echo ">>> run ${BENCH_RUN_ID} index ${BENCH_RUN_INDEX}: ${VAL_COUNT} blasters x ${BENCH_SENDERS} senders, start_at $(bench_iso_from_unix "${start_at}")"
    echo "    phases (planned): preamble ${BENCH_PREAMBLE_SECS}s, warmup ${BENCH_WARMUP_SECS}s, mixed ${BENCH_DURATION_SECS}s, cooldown ${BENCH_COOLDOWN_SECS}s; wait deadline $(bench_iso_from_unix "${deadline}")"
    local chaos_on="${BENCH_CHAOS:-1}"
    local t_kill=$(( mixed_start + 900 )) t_back=$(( mixed_start + 1200 )) t_obs=$(( mixed_start + 1500 ))
    if [ "${chaos_on}" = "1" ]; then
        echo "    chaos: $(bench_iso_from_unix "${t_kill}") kill -9 ${INSTANCE_NAMES[$CHAOS_KILL_IDX]}; $(bench_iso_from_unix "${t_back}") start it; $(bench_iso_from_unix "${t_obs}") restart ${INSTANCE_NAMES[$OBSERVER_IDX]}"
    else
        echo "    chaos: disabled (BENCH_CHAOS=0)"
    fi
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        name="$(blaster_name "$k")"
        [ -z "$(bench_instance_json "${name}" "${ZONES[$k]}")" ] || bench_die "${name} already exists — benchmark-blast.sh delete --yes first"
    done

    # --- create the blasters in parallel ---
    gcloud auth print-access-token >/dev/null
    local pids=() names=() logs=()
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/logs"
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
            --arg u "$(cat "${BENCH_RESULTS_DIR}/meta/${name}/NODE_URLS" | sed 's/^[^=]*=//')" \
            --arg s "$(( k * BENCH_SENDERS + BENCH_RUN_INDEX * 100000 ))" --arg c "${BENCH_SENDERS}" \
            '. + [{name:$n, zone:$z, instance_id:$id, target:$t, node_url:$u, sender_start:($s|tonumber), senders:($c|tonumber), result:("blasters/" + $n + ".json"), rc:null}]')"
    done
    bench_manifest_jq --argjson b "${bl}" '.blasters = $b'

    # --- watch loop: chaos + abort watchers + done markers ---
    local next_poll=$(( start_at + 60 )) did_kill=0 did_back=0 did_obs=0 all_done=0
    local last_max_block="" last_block_change_ts="" sleep_for target
    local done_rc=(); for k in $(seq 0 $((VAL_COUNT - 1))); do done_rc[k]=""; done
    while :; do
        now="$(bench_now_unix)"
        if [ "${chaos_on}" = "1" ] && [ -z "${ABORTED}" ]; then
            if [ "${did_kill}" -eq 0 ] && [ "${now}" -ge "${t_kill}" ]; then
                chaos_do "${CHAOS_KILL_IDX}" "sudo docker kill -s KILL telcoin; sudo systemctl stop telcoin; systemctl is-active telcoin || true" \
                    "docker kill -s KILL telcoin" "5 min outage then restart (replay worst case); systemctl stop holds it down (unit has Restart=on-failure)"
                did_kill=1
            fi
        fi
        # The restart is owed even after an abort: never leave v05 down.
        if [ "${did_kill}" -eq 1 ] && [ "${did_back}" -eq 0 ] && { [ "${now}" -ge "${t_back}" ] || [ -n "${ABORTED}" ]; }; then
            chaos_do "${CHAOS_KILL_IDX}" "sudo systemctl start telcoin && systemctl is-active telcoin" \
                "systemctl start telcoin" "docker start is impossible: the unit runs docker run --rm"
            did_back=1
        fi
        if [ "${chaos_on}" = "1" ] && [ -z "${ABORTED}" ] && [ "${did_obs}" -eq 0 ] && [ "${now}" -ge "${t_obs}" ]; then
            chaos_do "${OBSERVER_IDX}" "sudo systemctl restart telcoin && systemctl is-active telcoin" "systemctl restart telcoin" "observer restart"
            did_obs=1
        fi

        if [ "${now}" -ge "${next_poll}" ]; then
            bench_log "poll: blasters + node status + obs memory"
            # blasters
            all_done=1
            for k in $(seq 0 $((VAL_COUNT - 1))); do
                [ -n "${done_rc[k]}" ] && continue
                name="$(blaster_name "$k")"
                done_rc[k]="$(bench_serial_last "${name}" "${ZONES[$k]}" "BENCH_BLAST_DONE rc=" | marker_rc BENCH_BLAST_DONE)"
                [ -n "${done_rc[k]}" ] && echo "    ${name} done rc=${done_rc[k]}" || all_done=0
            done
            # nodes (BENCH_STATUS from node-sampler.sh on the serial console)
            local maxb="" line inst pct fatal blk
            for k in "${!INSTANCE_NAMES[@]}"; do
                inst="${INSTANCE_NAMES[$k]}"
                line="$(bench_serial_last "${inst}" "${ZONES[$k]}" "BENCH_STATUS ")"
                [ -n "${line}" ] || { echo "    ${inst}: no BENCH_STATUS yet"; continue; }
                pct="$(status_field "${line}" root_used_pct)"; fatal="$(status_field "${line}" fatal_db)"; blk="$(status_field "${line}" block)"
                echo "    ${inst}: root=${pct:-?}% fatal_db=${fatal:-?} block=${blk:-?}"
                if [ -n "${pct}" ] && [ "${pct}" -gt "${BENCH_ABORT_DISK_PCT}" ]; then record_abort "disk-full" "${inst}" "root disk ${pct}% > ${BENCH_ABORT_DISK_PCT}%"; fi
                if [ -n "${fatal}" ] && [ "${fatal}" -gt 0 ]; then record_abort "batch-cache-cliff" "${inst}" "FatalDBFailure x${fatal} in docker logs telcoin — batch-cache cliff, NOT a hardware limit"; fi
                if [ -n "${blk}" ] && { [ -z "${maxb}" ] || [ "${blk}" -gt "${maxb}" ]; }; then maxb="${blk}"; fi
            done
            if [ -n "${maxb}" ]; then
                if [ -z "${last_max_block}" ] || [ "${maxb}" -gt "${last_max_block}" ]; then
                    last_max_block="${maxb}"; last_block_change_ts="${now}"
                elif [ $(( now - last_block_change_ts )) -gt "${BENCH_ABORT_STALL_SECS}" ] && [ "${all_done}" -eq 0 ]; then
                    record_abort "quorum-lost" "fleet" "max block ${maxb} unchanged for $(( now - last_block_change_ts ))s"
                fi
            fi
            local mem; mem="$(bench_obs_mem_pct)"
            echo "    obs-devnet memory: ${mem:-n/a}%"
            if [ -n "${mem}" ] && awk -v m="${mem}" -v t="${BENCH_ABORT_OBS_MEM_PCT}" 'BEGIN{exit !(m>t)}'; then
                record_abort "obs-memory" "${OBS_INSTANCE_NAME}" "obs-devnet memory ${mem}% > ${BENCH_ABORT_OBS_MEM_PCT}%"
            fi
            next_poll=$(( now + BENCH_POLL_SECS ))
        fi

        if [ -n "${ABORTED}" ] && [ -z "${STOPPED:-}" ]; then
            STOPPED=1
            bench_log "stopping blasters (docker stop txgen) after abort: ${ABORTED}"
            stop_blasters
            deadline=$(( now + 600 ))
            next_poll=$(( now + BENCH_POLL_SECS ))
        fi
        [ "${all_done}" -eq 1 ] && { bench_log "all blasters reported BENCH_BLAST_DONE"; break; }
        [ "${now}" -lt "${deadline}" ] || { bench_warn "deadline reached before every blaster finished"; break; }

        target="${next_poll}"
        if [ "${chaos_on}" = "1" ]; then
            [ "${did_kill}" -eq 0 ] && [ "${t_kill}" -lt "${target}" ] && target="${t_kill}"
            [ "${did_back}" -eq 0 ] && [ "${did_kill}" -eq 1 ] && [ "${t_back}" -lt "${target}" ] && target="${t_back}"
            [ "${did_obs}" -eq 0 ] && [ "${t_obs}" -lt "${target}" ] && target="${t_obs}"
        fi
        sleep_for=$(( target - $(bench_now_unix) )); [ "${sleep_for}" -ge 5 ] || sleep_for=5
        sleep "${sleep_for}"
    done

    # --- results ---
    bench_manifest_ts blast_end
    for k in $(seq 0 $((VAL_COUNT - 1))); do
        [ -n "${done_rc[k]}" ] || continue
        bench_manifest_jq --arg n "$(blaster_name "$k")" --arg rc "${done_rc[k]}" \
            '.blasters |= map(if .name == $n then .rc = ($rc|tonumber) else . end)'
    done
    copy_prefix blasters
    if [ "${KEEP}" -eq 0 ]; then
        for k in $(seq 0 $((VAL_COUNT - 1))); do delete_vms "${ZONES[$k]}" "$(blaster_name "$k")" || true; done
    fi
    local bad=0
    for k in $(seq 0 $((VAL_COUNT - 1))); do [ "${done_rc[k]:-x}" = "0" ] || bad=1; done
    if [ -n "${ABORTED}" ] || [ "${bad}" -ne 0 ]; then
        echo "❌ run finished with abort='${ABORTED}' / non-zero blaster rc — see ${BENCH_RESULTS_DIR}" >&2
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
    done
    copy_prefix blasters
    copy_prefix funder
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

case "${ACTION}" in
    fund)    [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"; do_fund ;;
    run)     [ -n "${BENCH_RUN_ID}" ] || bench_die "no run id"; do_run ;;
    collect) do_collect ;;
    delete)  do_delete ;;
    status)  do_status ;;
esac
