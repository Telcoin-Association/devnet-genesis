#!/bin/bash
#
# blaster-startup.sh — GCE startup-script for the benchmark's COS load VMs
# (bench-funder, bench-blaster-NN). Created by benchmark-blast.sh with
#   --image-family=cos-stable --image-project=cos-cloud --scopes=cloud-platform
#   --metadata-from-file=startup-script=blaster-startup.sh,txgen-config=<toml>,txgen-deployments=<json>
#   --metadata=BENCH_MODE=fund|blast,TXGEN_IMAGE=...,NODE_URLS=...,SENDERS=...,SENDER_START=...,
#              BLAST_ARGS=...,BENCH_START_AT=<unix>,BENCH_BUCKET=...,RUN_ID=...,RUN_INDEX=...,LABEL=...,
#              MASTER_SECRET=...,SEED_SECRET=...[,WINDOW=<n>][,LANDINGS_SAMPLE=<n>]
# (WINDOW, the generator's closed-loop window per sender, is set only when BENCH_WINDOW is not
# the default 16; LANDINGS_SAMPLE, one sampled landing row per <n> landed transactions in
# /out/landings-<label>.ndjson.gz, only when BENCH_LANDINGS_SAMPLE is not 0. A default blast's
# metadata is unchanged.)
#
# Flow: done-guard -> SA token from the metadata server -> Secret Manager REST :access for
# the txgen master key + children seed (into a root-only docker --env-file; they never
# touch metadata or the operator's disk) -> registry auth + pre-pull -> /etc/txgen/{config.toml,
# deployments.json} from metadata -> sleep until BENCH_START_AT -> run the generator ->
# upload results + docker log to gs://$BENCH_BUCKET/$RUN_ID/index-$RUN_INDEX/{blasters|funder}/
# (no RUN_INDEX key: gs://$BENCH_BUCKET/$RUN_ID/{blasters|funder}/) -> print
# BENCH_<MODE>_DONE rc=N on the serial console (what benchmark-blast.sh waits for).
#
# cos-stable ships docker, curl, base64 and docker-credential-gcr but no gcloud and no jq,
# so every Google API call here is curl REST with the metadata token, parsed with sed.
#
# DRY_RUN=1 renders instead of acting: metadata is read from files in $BENCH_MD_DIR (one
# file per key), no network call is made, and the docker command is printed, not run.

set -uo pipefail

DRY_RUN="${DRY_RUN:-0}"
STATE="${BENCH_STATE_DIR:-/var/lib/bench}"
MD="http://metadata.google.internal/computeMetadata/v1"
CONSOLE="/dev/ttyS0"

log() {
    local line="[bench-startup] $*"
    printf '%s\n' "${line}"
    if [ "${DRY_RUN}" != "1" ] && [ -w "${CONSOLE}" ]; then printf '%s\n' "${line}" > "${CONSOLE}" 2>/dev/null || true; fi
}
md() { curl -sf -H 'Metadata-Flavor: Google' "${MD}/$1"; }
attr() {
    if [ "${DRY_RUN}" = "1" ]; then cat "${BENCH_MD_DIR:?DRY_RUN needs BENCH_MD_DIR}/$1" 2>/dev/null || true
    else md "instance/attributes/$1" 2>/dev/null || true; fi
}
# Run (or, in DRY_RUN, print) a command.
act() {
    if [ "${DRY_RUN}" = "1" ]; then printf 'DRY_RUN:'; printf ' %q' "$@"; printf '\n'; return 0; fi
    "$@"
}

MODE="$(attr BENCH_MODE)"
TXGEN_IMAGE="$(attr TXGEN_IMAGE)"
NODE_URLS="$(attr NODE_URLS)"
SENDERS="$(attr SENDERS)"
SENDER_START="$(attr SENDER_START)"
BLAST_ARGS="$(attr BLAST_ARGS)"
BENCH_START_AT="$(attr BENCH_START_AT)"
BENCH_BUCKET="$(attr BENCH_BUCKET)"
RUN_ID="$(attr RUN_ID)"
RUN_INDEX="$(attr RUN_INDEX)"
LABEL="$(attr LABEL)"
MASTER_SECRET="$(attr MASTER_SECRET)"
SEED_SECRET="$(attr SEED_SECRET)"
WARMUP_SECS="$(attr WARMUP_SECS)";     WARMUP_SECS="${WARMUP_SECS:-120}"
DURATION_SECS="$(attr DURATION_SECS)"; DURATION_SECS="${DURATION_SECS:-2400}"
COOLDOWN_SECS="$(attr COOLDOWN_SECS)"; COOLDOWN_SECS="${COOLDOWN_SECS:-180}"
FUND_TEL="$(attr FUND_TEL)";           FUND_TEL="${FUND_TEL:-2}"
WINDOW="$(attr WINDOW)";               WINDOW="${WINDOW:-16}"
LANDINGS_SAMPLE="$(attr LANDINGS_SAMPLE)"; LANDINGS_SAMPLE="${LANDINGS_SAMPLE:-0}"

case "${MODE}" in
    fund)  MARK="BENCH_FUND_DONE";  PREFIX="funder" ;;
    blast) MARK="BENCH_BLAST_DONE"; PREFIX="blasters" ;;
    *) log "BENCH_UNKNOWN_DONE rc=2 reason=bad-BENCH_MODE:'${MODE}'"; exit 2 ;;
esac
LABEL="${LABEL:-$(hostname -s 2>/dev/null || hostname)}"
OUT_DIR="${STATE}/out"
ENV_FILE="${STATE}/txgen.env"
DONE_FILE="${STATE}/done-${MODE}"

# --- done-guard: a reboot re-runs startup-scripts; never blast twice -----------------
if [ -f "${DONE_FILE}" ] && [ "${DRY_RUN}" != "1" ]; then
    log "already ran: $(cat "${DONE_FILE}") (delete ${DONE_FILE} to force)"
    log "${MARK} $(cat "${DONE_FILE}") (from done-guard)"
    exit 0
fi

finished=0
finish() {
    local rc="$1" reason="${2:-}"
    [ "${finished}" -eq 1 ] && return 0
    finished=1
    rm -f "${ENV_FILE}" 2>/dev/null || true
    if [ "${DRY_RUN}" != "1" ]; then printf 'rc=%s%s\n' "${rc}" "${reason:+ reason=${reason}}" > "${DONE_FILE}"; fi
    log "${MARK} rc=${rc}${reason:+ reason=${reason}}"
}
trap 'finish $? trap-exit' EXIT
fail() { finish "$1" "$2"; exit "$1"; }

missing=""
for k in TXGEN_IMAGE NODE_URLS SENDERS SENDER_START BENCH_BUCKET RUN_ID MASTER_SECRET SEED_SECRET; do
    eval "v=\${${k}}"
    [ -n "${v}" ] || missing="${missing} ${k}"
done
[ -z "${missing}" ] || fail 2 "missing-metadata:${missing# }"
case "${RUN_INDEX}" in *[!0-9]*|0?*) fail 2 "bad-RUN_INDEX:'${RUN_INDEX}'" ;; esac
case "${WINDOW}" in *[!0-9]*|0*) fail 2 "bad-WINDOW:'${WINDOW}'" ;; esac
case "${LANDINGS_SAMPLE}" in *[!0-9]*|0?*) fail 2 "bad-LANDINGS_SAMPLE:'${LANDINGS_SAMPLE}'" ;; esac
# Bucket objects of this VM: one prefix per BENCH_RUN_INDEX, so a second blast (or funding) on
# the fleet never shares an object name with the first. A VM created by a benchmark-blast.sh
# that set no RUN_INDEX keeps the old flat prefix, where that script looks for its objects.
OBJ_PREFIX="${RUN_ID}/${RUN_INDEX:+index-${RUN_INDEX}/}${PREFIX}"
log "mode=${MODE} label=${LABEL} run=${RUN_ID} image=${TXGEN_IMAGE} senders=${SENDERS}@${SENDER_START} nodes=${NODE_URLS} objects=gs://${BENCH_BUCKET}/${OBJ_PREFIX}/"

TXGEN_ETC="/etc/txgen"; [ "${DRY_RUN}" = "1" ] && TXGEN_ETC="${STATE}/etc-txgen"
mkdir -p "${STATE}" "${OUT_DIR}" "${TXGEN_ETC}"
chmod 777 "${OUT_DIR}"          # the image is distroless nonroot: /out must be writable by 65532

# --- credentials: metadata SA token -> Secret Manager -------------------------------
sa_token() { md "instance/service-accounts/default/token" | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p'; }
PROJECT="$( [ "${DRY_RUN}" = "1" ] && echo dry-project || md project/project-id )"

# fetch_secret <name> — latest version payload, decoded. Never logged.
fetch_secret() {
    local tok="$1" name="$2"
    curl -sf -H "Authorization: Bearer ${tok}" \
        "https://secretmanager.googleapis.com/v1/projects/${PROJECT}/secrets/${name}/versions/latest:access" \
        | tr -d '\n' | sed -n 's/.*"data" *: *"\([^"]*\)".*/\1/p' | base64 -d 2>/dev/null
}

if [ "${DRY_RUN}" = "1" ]; then
    log "DRY_RUN: would fetch secrets ${MASTER_SECRET} + ${SEED_SECRET} via Secret Manager REST"
    printf 'TXGEN_MASTER_KEY=%s\nTXGEN_CHILDREN_SEED=%s\n' "0xDRYRUN" "dry run words" > "${ENV_FILE}"
else
    TOKEN="$(sa_token)"; [ -n "${TOKEN}" ] || fail 3 "no-sa-token"
    master="$(fetch_secret "${TOKEN}" "${MASTER_SECRET}" | tr -d '[:space:]')"
    seed="$(fetch_secret "${TOKEN}" "${SEED_SECRET}" | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//')"
    [ -n "${master}" ] || fail 3 "secret-${MASTER_SECRET}-unreadable"
    [ -n "${seed}" ] || fail 3 "secret-${SEED_SECRET}-unreadable"
    ( umask 077; printf 'TXGEN_MASTER_KEY=%s\nTXGEN_CHILDREN_SEED=%s\n' "${master}" "${seed}" > "${ENV_FILE}" )
    unset master seed
    chmod 600 "${ENV_FILE}"
    log "secrets fetched into root-only env file (values not logged)"
fi

# --- registry auth + pre-pull ---------------------------------------------------------
REGISTRY="${TXGEN_IMAGE%%/*}"
export HOME="${STATE}/home"; mkdir -p "${HOME}"      # COS: /root is not writable for docker config
if [ "${DRY_RUN}" = "1" ]; then
    act docker-credential-gcr configure-docker --registries="${REGISTRY}"
    act docker pull "${TXGEN_IMAGE}"
else
    if ! docker-credential-gcr configure-docker --registries="${REGISTRY}" >/dev/null 2>&1; then
        log "docker-credential-gcr failed; falling back to token login"
        printf '%s' "${TOKEN}" | docker login -u oauth2accesstoken --password-stdin "https://${REGISTRY}" >/dev/null 2>&1 \
            || fail 4 "registry-auth"
    fi
    pulled=0
    for attempt in 1 2 3 4 5; do
        if docker pull -q "${TXGEN_IMAGE}" >/dev/null 2>&1; then pulled=1; break; fi
        log "pull attempt ${attempt} failed; retrying"; sleep $((attempt * 10))
    done
    [ "${pulled}" -eq 1 ] || fail 4 "pull-failed"
    log "image pulled: ${TXGEN_IMAGE}"
fi

# --- generator config + address book from metadata ----------------------------------
attr txgen-config > "${TXGEN_ETC}/config.toml"
attr txgen-deployments > "${TXGEN_ETC}/deployments.json"
[ -s "${TXGEN_ETC}/config.toml" ] || fail 5 "empty-txgen-config"
[ -s "${TXGEN_ETC}/deployments.json" ] || fail 5 "empty-txgen-deployments"
chmod 644 "${TXGEN_ETC}/config.toml" "${TXGEN_ETC}/deployments.json"

# --- generator argv (CLI contract: tn-transaction-generator blast) -------------------
args=(--config /etc/txgen/config.toml blast)
if [ "${MODE}" = "fund" ]; then
    args+=(--prepare --nodes "${NODE_URLS}" --senders "${SENDERS}" --sender-start "${SENDER_START}"
           --fund-tel "${FUND_TEL}" --deployments-path /etc/txgen/deployments.json --out /out/prepare.json)
else
    args+=(--nodes "${NODE_URLS}" --senders "${SENDERS}" --sender-start "${SENDER_START}" --window "${WINDOW}"
           --warmup-secs "${WARMUP_SECS}" --duration-secs "${DURATION_SECS}" --cooldown-secs "${COOLDOWN_SECS}"
           --receipts all --deployments-path /etc/txgen/deployments.json --label "${LABEL}"
           --run-id "${RUN_ID}" --out "/out/${LABEL}.json" --stdout-json chunked)
    # Uploaded with the rest of /out (flat under the blasters prefix), so the copy into
    # results/<run>/blasters/ brings it back.
    [ "${LANDINGS_SAMPLE}" = 0 ] || args+=(--landings-out "/out/landings-${LABEL}.ndjson.gz" --landings-sample "${LANDINGS_SAMPLE}")
fi
if [ -n "${BLAST_ARGS}" ]; then
    # Operator-supplied extra flags, appended verbatim (word-split on whitespace).
    read -r -a extra <<< "${BLAST_ARGS}"
    args+=("${extra[@]}")
fi

# --- wait for the synchronized start --------------------------------------------------
if [ -n "${BENCH_START_AT}" ]; then
    now="$(date +%s)"
    if [ "${BENCH_START_AT}" -gt "${now}" ]; then
        log "sleeping $((BENCH_START_AT - now))s until BENCH_START_AT=${BENCH_START_AT}"
        [ "${DRY_RUN}" = "1" ] || sleep $((BENCH_START_AT - now))
    else
        log "BENCH_START_AT=${BENCH_START_AT} already passed ($((now - BENCH_START_AT))s late) — starting now"
    fi
fi

# --- run --------------------------------------------------------------------------------
DOCKER_LOG="${OUT_DIR}/${LABEL}.docker.log"
log "BENCH_$(printf '%s' "${MODE}" | tr '[:lower:]' '[:upper:]')_START ts=$(date +%s)"
if [ "${DRY_RUN}" = "1" ]; then
    act docker run --rm --name txgen --network host --env-file "${ENV_FILE}" -e TXGEN_LOG_DIR=/out/logs \
        -v "${TXGEN_ETC}:/etc/txgen:ro" -v "${OUT_DIR}:/out" "${TXGEN_IMAGE}" "${args[@]}"
    rc=0
else
    docker rm -f txgen >/dev/null 2>&1 || true
    docker run --rm --name txgen --network host --env-file "${ENV_FILE}" -e TXGEN_LOG_DIR=/out/logs \
        -v "${TXGEN_ETC}:/etc/txgen:ro" -v "${OUT_DIR}:/out" "${TXGEN_IMAGE}" "${args[@]}" \
        > "${DOCKER_LOG}" 2>&1
    rc=$?
fi
rm -f "${ENV_FILE}"
log "generator exited rc=${rc}"

# --- upload results + docker log (GCS JSON API; no gcloud on COS) ---------------------
upload_rc=0
upload() { # <local-file> <object-name>
    local f="$1" obj="$2" enc ctype="application/octet-stream"
    case "${f}" in *.json) ctype="application/json" ;; *.log|*.txt) ctype="text/plain" ;; esac
    enc="$(printf '%s' "${obj}" | sed 's#/#%2F#g')"
    if [ "${DRY_RUN}" = "1" ]; then   # BENCH_DRY_UPLOAD_FAIL=1 exercises the rc=75 path in a render
        log "DRY_RUN: would upload ${f} -> gs://${BENCH_BUCKET}/${obj}"; [ "${BENCH_DRY_UPLOAD_FAIL:-0}" != "1" ]; return; fi
    # -T streams the file (a large docker log is never read into memory); -X POST is what the
    # JSON API's media upload expects.
    curl -sf -X POST -H "Authorization: Bearer ${UP_TOKEN}" -H "Content-Type: ${ctype}" \
        -T "${f}" \
        "https://storage.googleapis.com/upload/storage/v1/b/${BENCH_BUCKET}/o?uploadType=media&name=${enc}" >/dev/null
}
UP_TOKEN="$( [ "${DRY_RUN}" = "1" ] && echo dry || sa_token )"   # re-fetch: the blast outlives a token
while IFS= read -r f; do
    rel="${f#"${OUT_DIR}"/}"
    # Flat layout under OBJ_PREFIX (copied into results/<run>/blasters/, so manifest
    # .blasters[].result = "blasters/<label>.json"); the generator's own log files get the
    # label as a prefix so blasters never collide.
    case "${rel}" in logs/*) rel="${LABEL}.${rel#logs/}" ;; */*) rel="${LABEL}.${rel//\//.}" ;; esac
    if upload "${f}" "${OBJ_PREFIX}/${rel}"; then log "uploaded ${rel}"; else log "upload FAILED ${rel}"; upload_rc=1; fi
done < <(find "${OUT_DIR}" -type f 2>/dev/null)

# Marker contract (benchmark-blast.sh): rc=0 reason=ok is the ONLY state in which the VM may
# be deleted unattended. A failed upload is rc=75 even when the generator succeeded, because
# this VM then holds the only copy of the results.
trap - EXIT
if [ "${upload_rc}" -ne 0 ]; then
    finish 75 "upload-failed gen_rc=${rc}"
elif [ "${rc}" -ne 0 ]; then
    finish "${rc}" "generator-exit"
else
    finish 0 "ok"
fi
exit 0
