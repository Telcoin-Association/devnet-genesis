#!/usr/bin/env bash
#
# benchmark/obs-lib.sh — bench-obs, the run's own metrics VM: one Prometheus (remote-write
# receiver) and one Grafana, nothing else. Sourced by bench-lib.sh right after pull-lib.sh; it
# only defines functions (sourcing it twice is harmless) and runs against the bench profile
# (benchmark/config.sh: BENCH_OBS_*, BENCH_PROM_*, BENCH_GRAFANA_URL).
#
# Lifecycle: deploy step 2 creates the VM (bench_obs_create), step 8 brings the stack up and opens
# the two local forwards (bench_obs_ensure), later steps and the blaster check it is still there
# (bench_obs_require), and the teardown pulls a Prometheus TSDB snapshot
# (bench_obs_prom_snapshot_pull) before it deletes the VM. The nodes' Alloy pushes to the VM's VPC
# internal IP on port 9090 (OBS_METRICS_PUSH_URL, set by bench_obs_urls); the operator reaches
# Prometheus and Grafana only through IAP ssh forwards on localhost. No DNS, TLS, Loki, Caddy,
# Secret Manager, static IP or firewall rule.
#
# Lines other tools parse (one per event, on stdout):
#   OBS_CREATE inst=<i> zone=<z> ip=<ip> id=<id> existing=<0|1|dry>
#   OBS_BOOT inst=<i> secs=<n>
#   OBS_STACK_OK bench-obs prom=ready grafana=ok secs=<n>      last line of the bring-up session
#   OBS_STACK_FAIL bench-obs reason=<why>                       (or this, and the session exits 1)
#   OBS_READY inst=<i> ip=<ip> secs=<n>
#   OBS_SNAPSHOT inst=<i> name=<snapshot> bytes=<n> file=<path>
# Remote session header (the first line of the script on stdin): "# bench-obs: bringup".
#
# Every GCP mutation goes through bench_run (printed first, executed only with BENCH_APPLY=1);
# reads call gcloud directly. With BENCH_APPLY other than 1 the one call out left is
# bench_obs_exists, a read-only instances describe (the teardown's dry run uses it too); every other
# function calls no gcloud, ssh or curl and prints what it would do.

# Host name used for the VM's internal IP wherever it is not known yet (dry runs, print modes, no
# manifest). Nothing resolves under .invalid (RFC 6761).
BENCH_OBS_PLACEHOLDER_IP="bench-obs-internal-ip.invalid"
# The service-account scopes the bench nodes get (common/create-instances.sh), so the Ops Agent the
# startup script installs can write the VM's metrics and logs.
BENCH_OBS_SCOPES="https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write,https://www.googleapis.com/auth/service.management.readonly,https://www.googleapis.com/auth/servicecontrol,https://www.googleapis.com/auth/trace.append"
# Resume hints in the dies. Step 8 (bench_obs_ensure) recreates or repairs the VM and re-points every
# node's Alloy; a bare --from 8 would also re-fund and re-blast, so a later step resumes with --only 8
# and then its own segment again.
BENCH_OBS_HINT_STEP8="re-run with --only 8 (then continue with --from 9)"
BENCH_OBS_HINT_RESUME="resume with --only 8 (then re-run your segment: --from 10 --to 12 or --from 13 --to 15)"
# Set by bench_obs_create: 0 created now, 1 this run's VM was already there, dry (dry run).
_BENCH_OBS_EXISTING="${_BENCH_OBS_EXISTING:-}"

# _bench_obs_knobs_ok — the BENCH_OBS_* knobs this file builds commands from; bench_die on a bad one.
_bench_obs_knobs_ok() {
    local k v
    for k in BENCH_OBS_DISK_GB BENCH_OBS_PROM_LOCAL_PORT BENCH_OBS_GRAFANA_LOCAL_PORT \
             BENCH_OBS_BOOT_TIMEOUT_SECS BENCH_OBS_DISK_MAX_PCT; do
        v="${!k:-}"
        case "${v}" in ''|*[!0-9]*|0*) bench_die "${k}='${v}' must be a positive integer" ;; esac
    done
    # ^bench- keeps the VM inside the teardown's candidate names (and BENCH_PROTECTED_RE's reach).
    case "${BENCH_OBS_INSTANCE:-}" in
        bench-*[!a-z0-9-]*|bench-) bench_die "BENCH_OBS_INSTANCE='${BENCH_OBS_INSTANCE}' may hold only [a-z0-9-]" ;;
        bench-*) ;;
        *) bench_die "BENCH_OBS_INSTANCE='${BENCH_OBS_INSTANCE:-}' must start with bench-" ;;
    esac
    for k in BENCH_OBS_ZONE BENCH_OBS_MACHINE_TYPE; do
        v="${!k:-}"
        case "${v}" in ''|*[!a-z0-9-]*) bench_die "${k}='${v}' may hold only [a-z0-9-]" ;; esac
    done
    case "${BENCH_PROM_RETENTION:-}" in
        [0-9]*[smhdwy]) case "${BENCH_PROM_RETENTION%?}" in *[!0-9]*) bench_die "BENCH_PROM_RETENTION='${BENCH_PROM_RETENTION}' must be <n><s|m|h|d|w|y>, e.g. 7d" ;; esac ;;
        *) bench_die "BENCH_PROM_RETENTION='${BENCH_PROM_RETENTION:-}' must be <n><s|m|h|d|w|y>, e.g. 7d" ;;
    esac
}

# bench_obs_urls — no gcloud. BENCH_OBS_INTERNAL_IP keeps its value when set (an override), else
# takes manifest.obs.internal_ip (when the manifest exists), else the .invalid placeholder; the
# placeholder itself counts as unset, so a later call picks up the manifest. Exports it and
# OBS_METRICS_PUSH_URL=http://<ip>:9090/api/v1/write. OBS_PUSH_URL (logs) is not touched.
bench_obs_urls() {
    local ip="${BENCH_OBS_INTERNAL_IP:-}" f
    if [ -z "${ip}" ] || [ "${ip}" = "${BENCH_OBS_PLACEHOLDER_IP}" ]; then
        ip=""
        f="$(bench_manifest)"
        if [ -f "${f}" ]; then ip="$(jq -r '.obs.internal_ip // empty' "${f}" 2>/dev/null)" || ip=""; fi
    fi
    [ -n "${ip}" ] || ip="${BENCH_OBS_PLACEHOLDER_IP}"
    case "${ip}" in *[!A-Za-z0-9.:-]*) bench_die "bench-obs internal IP '${ip}' is not an address or host name" ;; esac
    BENCH_OBS_INTERNAL_IP="${ip}"
    OBS_METRICS_PUSH_URL="http://${ip}:9090/api/v1/write"
    export BENCH_OBS_INTERNAL_IP OBS_METRICS_PUSH_URL
}

# _bench_obs_exists_retry — bench_obs_exists, a describe that fails otherwise than "not found" tried
# three times 5 s apart, then bench_die. rc 0 found, 1 not found.
_bench_obs_exists_retry() {
    local erc tries=0
    while :; do
        erc=0
        bench_obs_exists || erc=$?
        [ "${erc}" -eq 2 ] || return "${erc}"
        tries=$((tries + 1))
        [ "${tries}" -lt 3 ] || bench_die "${BENCH_OBS_INSTANCE} describe failed 3× (transient API/auth error? re-run the step)"
        bench_warn "${BENCH_OBS_INSTANCE}: instances describe failed (not a 'not found') — again in 5 s (${tries}/3)"
        sleep 5
    done
}

# bench_obs_exists — rc 0 when GCP knows the VM (instances describe answers its name); 1 only when
# describe says it is not found; 2 for any other failure (an API or auth error: the VM may well be
# there), with gcloud's stderr passed on.
bench_obs_exists() {
    local n="" errf rc=0
    errf="$(mktemp)" || return 2
    n="$(gcloud compute instances describe "${BENCH_OBS_INSTANCE}" --zone="${BENCH_OBS_ZONE}" \
        --project="${PROJECT_ID}" --format='value(name)' 2>"${errf}")" || rc=$?
    if [ "${rc}" -eq 0 ] && [ -n "${n}" ]; then rm -f "${errf}"; return 0; fi
    if grep -qi 'not found' "${errf}"; then rm -f "${errf}"; return 1; fi
    sed 's/^/      /' "${errf}" >&2
    rm -f "${errf}"
    return 2
}

# bench_obs_create — create the VM, or keep it when it is this run's. Idempotent. An existing VM of
# that name must carry exactly the bench-obs tag, benchmark=1 and this run's bench-run label; any
# other is refused (never adopted). A new one: debian-12 on a 20 GB pd-balanced boot disk, a pd-ssd
# data disk with device name obs-data (the startup script formats and mounts it at /mnt/obs-data),
# tag bench-obs, the run's labels plus tn-role=obs on the VM and both disks, an ephemeral external
# IP, the nodes' service account and scopes. Writes manifest.obs, exports BENCH_OBS_INTERNAL_IP
# (and OBS_METRICS_PUSH_URL), prints OBS_CREATE. Dry run: the gcloud lines, nothing created.
bench_obs_create() {
    local inst="${BENCH_OBS_INSTANCE}" zone="${BENCH_OBS_ZONE}" j="" existing=0 boot ip id mt dgb ct st found=0
    _bench_obs_knobs_ok
    _BENCH_OBS_EXISTING=""
    if [ "${BENCH_APPLY}" != "1" ]; then
        [ -r "${BENCH_OBS_STARTUP_SCRIPT}" ] || bench_warn "bench-obs startup script ${BENCH_OBS_STARTUP_SCRIPT} is missing or unreadable — a --yes run stops here"
        _bench_obs_create_vm "${inst}" "${zone}"
        _bench_obs_label_disks "${inst}" "${zone}" "${inst}"
        _BENCH_OBS_EXISTING=dry
        echo "OBS_CREATE inst=${inst} zone=${zone} ip=${BENCH_OBS_PLACEHOLDER_IP} id=- existing=dry"
        return 0
    fi
    # Existence through bench_obs_exists: a transient describe error must not look like "absent"
    # (a create would then fail on "already exists").
    _bench_obs_exists_retry || found=$?
    if [ "${found}" -eq 0 ]; then
        j="$(bench_instance_json "${inst}" "${zone}")"
        [ -n "${j}" ] || bench_die "${inst}: describe --format=json answered nothing (transient API/auth error? re-run the step)"
        if ! printf '%s' "${j}" | jq -e --arg run "${BENCH_RUN_ID}" '(.tags.items // []) == ["bench-obs"] and .labels.benchmark == "1" and .labels["bench-run"] == $run' >/dev/null; then
            echo "    ✗ ${inst}: $(printf '%s' "${j}" | jq -c '{tags: .tags.items, labels}' 2>/dev/null || echo unreadable)" >&2
            bench_die "${inst} exists in ${zone} but is not this run's bench-obs (tag bench-obs, labels benchmark=1 and bench-run=${BENCH_RUN_ID}) — it is never adopted; tear its run down first, or pick another BENCH_OBS_INSTANCE"
        fi
        st="$(printf '%s' "${j}" | jq -r '.status // empty')" || st=""
        [ "${st}" = "RUNNING" ] \
            || bench_die "${inst} is this run's bench-obs but ${st:-in an unknown state}, not RUNNING — start it (gcloud compute instances start ${inst} --zone ${zone} --project ${PROJECT_ID}), then re-run the step"
        existing=1
        echo "    ${inst} exists (tag bench-obs, bench-run=${BENCH_RUN_ID}) — kept"
    else
        [ -r "${BENCH_OBS_STARTUP_SCRIPT}" ] \
            || bench_die "bench-obs startup script ${BENCH_OBS_STARTUP_SCRIPT} is missing or unreadable (is the common submodule checked out?)"
        _bench_obs_create_vm "${inst}" "${zone}" \
            || bench_die "gcloud compute instances create ${inst} failed — re-run with --from 2 (nodes are kept, this run's VM is adopted)"
        j="$(bench_instance_json "${inst}" "${zone}")"
        [ -n "${j}" ] || bench_die "${inst}: created, but instances describe answers nothing"
        boot="$(printf '%s' "${j}" | jq -r '[.disks[]? | select(.boot) | .source | split("/") | last][0] // empty')" || boot=""
        _bench_obs_label_disks "${inst}" "${zone}" "${boot:-${inst}}"
    fi
    ip="$(printf '%s' "${j}" | jq -r '.networkInterfaces[0].networkIP // empty')" || ip=""
    id="$(printf '%s' "${j}" | jq -r '.id // empty')" || id=""
    mt="$(printf '%s' "${j}" | jq -r '(.machineType // "") | split("/") | last')" || mt=""
    dgb="$(printf '%s' "${j}" | jq -r '[.disks[]? | select(.deviceName == "obs-data") | .diskSizeGb][0] // empty')" || dgb=""
    ct="$(printf '%s' "${j}" | jq -r '.creationTimestamp // empty')" || ct=""
    [ -n "${ip}" ] || bench_die "${inst}: instances describe shows no internal IP"
    case "${dgb}" in ''|*[!0-9]*) dgb="${BENCH_OBS_DISK_GB}" ;; esac
    bench_manifest_jq --arg i "${inst}" --arg z "${zone}" --arg mt "${mt:-${BENCH_OBS_MACHINE_TYPE}}" \
        --argjson gb "${dgb}" --arg ip "${ip}" --arg id "${id}" --arg ex "${existing}" \
        --arg now "$(bench_now_iso)" --arg ct "${ct}" '
        (if $ex == "1" then (.obs // {}) else {} end) as $old
        | .obs = ($old + {instance: $i, zone: $z, machine_type: $mt, disk_gb: $gb, internal_ip: $ip, instance_id: $id})
        | .obs.created_at = (if $ex == "1" then ($old.created_at // (if $ct == "" then null else $ct end)) else $now end)' \
        || bench_warn "manifest.obs not recorded"
    BENCH_OBS_INTERNAL_IP="${ip}"
    bench_obs_urls
    _BENCH_OBS_EXISTING="${existing}"
    echo "OBS_CREATE inst=${inst} zone=${zone} ip=${ip} id=${id:--} existing=${existing}"
}

# _bench_obs_create_vm <inst> <zone> — the one create call (bench_run: printed, run with --yes).
_bench_obs_create_vm() {
    bench_run gcloud compute instances create "$1" --project="${PROJECT_ID}" --zone="$2" \
        --machine-type="${BENCH_OBS_MACHINE_TYPE}" \
        --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=20GB --boot-disk-type=pd-balanced \
        --create-disk="name=$1-data,device-name=obs-data,size=${BENCH_OBS_DISK_GB}GB,type=pd-ssd,auto-delete=yes" \
        --tags=bench-obs --labels="${BENCH_LABELS},tn-role=obs" \
        --metadata-from-file="startup-script=${BENCH_OBS_STARTUP_SCRIPT}" \
        --service-account="${SERVICE_ACCOUNT}" --scopes="${BENCH_OBS_SCOPES}" --format=none
}

# _bench_obs_label_disks <inst> <zone> <boot disk> — the run's labels plus tn-role=obs on the boot
# disk and on the data disk (<inst>-data; --create-disk carries no labels). Warn-only: a disk
# without labels is still found by name (^bench-) by bench_leftovers and the teardown.
_bench_obs_label_disks() {
    local d
    for d in "$3" "$1-data"; do
        bench_run gcloud compute disks add-labels "${d}" --zone="$2" --project="${PROJECT_ID}" \
            --labels="${BENCH_LABELS},tn-role=obs" --format=none \
            || bench_warn "${d}: labels not added (gcloud compute disks add-labels failed)"
    done
}

# _bench_obs_boot_done <inst> <zone> — rc 0 when the serial console holds the startup script's
# last line, `[obs-startup] <date> done`. Counted, not `grep -q`: an early exit would SIGPIPE the
# serial text under pipefail.
_bench_obs_boot_done() {
    local out n
    out="$(bench_serial "$1" "$2")"
    n="$(printf '%s\n' "${out}" | grep -F '[obs-startup]' | grep -cw 'done')" || n=0
    [ "${n:-0}" -gt 0 ]
}

# bench_obs_wait_boot — poll the VM's serial console every 10 s, at most BENCH_OBS_BOOT_TIMEOUT_SECS,
# for the startup script's `[obs-startup] … done` (Docker, the Ops Agent and /mnt/obs-data are
# ready). Prints OBS_BOOT; bench_die on timeout.
bench_obs_wait_boot() {
    local inst="${BENCH_OBS_INSTANCE}" zone="${BENCH_OBS_ZONE}" limit waited=0 t0
    _bench_obs_knobs_ok
    limit="${BENCH_OBS_BOOT_TIMEOUT_SECS}"
    echo "    waiting for '[obs-startup] … done' on ${inst}'s serial console (every 10 s, at most ${limit} s)"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    t0="$(bench_now_unix)"
    while :; do
        if _bench_obs_boot_done "${inst}" "${zone}"; then
            echo "OBS_BOOT inst=${inst} secs=$(( $(bench_now_unix) - t0 ))"
            return 0
        fi
        [ "${waited}" -lt "${limit}" ] || break
        sleep 10
        waited=$((waited + 10))
    done
    bench_die "${inst}: no '[obs-startup] … done' on the serial console within ${limit} s — see: gcloud compute instances get-serial-port-output ${inst} --zone=${zone}; ${BENCH_OBS_HINT_STEP8}"
}

# bench_obs_bringup_script — print the root session script for the VM (stdin of `sudo bash -s`).
# It carries the bundle (BENCH_OBS_BUNDLE_DIR) with the metrics dashboards of BENCH_OBS_DASHBOARDS_DIR
# (*metrics*.json only: the others, node-logs.json, read the Loki datasource bench-obs does not
# have) staged under grafana/dashboards/, as one base64 tar.gz; on the VM it untars that into /opt/obs, writes
# /opt/obs/.env once (mode 600: the internal IP from the metadata server, BENCH_PROM_RETENTION and
# a random Grafana admin password), runs docker compose up and waits at most 120 s for Prometheus
# and Grafana to answer on loopback. Its last line is OBS_STACK_OK, or OBS_STACK_FAIL and exit 1.
# Non-zero, with nothing on stdout, when the bundle cannot be packed or there is no metrics dashboard.
bench_obs_bringup_script() {
    local stage b64="" rc=0 d n=0
    _bench_obs_knobs_ok
    [ -r "${BENCH_OBS_BUNDLE_DIR}/docker-compose.yml" ] \
        || { echo "❌ bench_obs_bringup_script: ${BENCH_OBS_BUNDLE_DIR}/docker-compose.yml is missing" >&2; return 1; }
    [ -d "${BENCH_OBS_DASHBOARDS_DIR}" ] \
        || { echo "❌ bench_obs_bringup_script: dashboards dir ${BENCH_OBS_DASHBOARDS_DIR} is missing (is the common submodule checked out?)" >&2; return 1; }
    for d in "${BENCH_OBS_DASHBOARDS_DIR}"/*metrics*.json; do [ -f "${d}" ] && n=$((n + 1)); done
    [ "${n}" -gt 0 ] \
        || { echo "❌ bench_obs_bringup_script: no metrics dashboard (*metrics*.json) in ${BENCH_OBS_DASHBOARDS_DIR}" >&2; return 1; }
    stage="$(mktemp -d "${TMPDIR:-/tmp}/bench-obs-bundle.XXXXXX")" \
        || { echo "❌ bench_obs_bringup_script: no staging dir" >&2; return 1; }
    # The archive's root entry is /opt/obs on the VM: 755, not mktemp's 700.
    { chmod 755 "${stage}" \
        && cp -R "${BENCH_OBS_BUNDLE_DIR}/." "${stage}/" \
        && mkdir -p "${stage}/grafana/dashboards" \
        && cp "${BENCH_OBS_DASHBOARDS_DIR}"/*metrics*.json "${stage}/grafana/dashboards/"; } || rc=1
    if [ "${rc}" -eq 0 ]; then
        # COPYFILE_DISABLE: macOS tar would add AppleDouble ._ files.
        b64="$(cd "${stage}" && COPYFILE_DISABLE=1 tar -cf - . | gzip -9 | base64)" || rc=1
    fi
    rm -rf "${stage}"
    if [ "${rc}" -ne 0 ] || [ -z "${b64}" ]; then
        echo "❌ bench_obs_bringup_script: could not pack ${BENCH_OBS_BUNDLE_DIR} + ${BENCH_OBS_DASHBOARDS_DIR}" >&2
        return 1
    fi
    cat <<'EOS'
# bench-obs: bringup
# Runs as root on bench-obs (stdin of `sudo bash -s`, written by benchmark/obs-lib.sh). Stages the
# metrics-only bundle in /opt/obs, writes /opt/obs/.env once, starts Prometheus + Grafana and waits
# for both to answer. stdout carries only this script's own lines; the last one is the verdict.
set -euo pipefail
t0="$(date +%s)"
fail() { echo "OBS_STACK_FAIL bench-obs reason=$1"; exit 1; }
command -v docker >/dev/null 2>&1 || fail docker-missing
docker compose version >/dev/null 2>&1 || fail compose-missing
mountpoint -q /mnt/obs-data || fail obs-data-not-mounted
mkdir -p /opt/obs /mnt/obs-data/prometheus /mnt/obs-data/grafana
chown 65534:65534 /mnt/obs-data/prometheus
chown 472:472 /mnt/obs-data/grafana
bundle="$(mktemp /tmp/bench-obs-bundle.XXXXXX)"
base64 -d > "${bundle}" <<'BENCH_OBS_BUNDLE_B64' || { rm -f "${bundle}"; fail bundle-decode; }
EOS
    printf '%s\n' "${b64}"
    cat <<'EOS'
BENCH_OBS_BUNDLE_B64
tar -xzf "${bundle}" -C /opt/obs --no-same-owner || { rm -f "${bundle}"; fail bundle-untar; }
rm -f "${bundle}"
chmod -R a+rX /opt/obs/grafana
chmod a+r /opt/obs/docker-compose.yml /opt/obs/prometheus.yml
if [ ! -s /opt/obs/.env ]; then
    ip="$(curl -sf --max-time 10 -H 'Metadata-Flavor: Google' \
        'http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip')" || ip=""
    [ -n "${ip}" ] || fail metadata-ip
    pw="$(openssl rand -hex 16 2>/dev/null)" || pw=""
    [ -n "${pw}" ] || pw="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
EOS
    printf '    retention=%s\n' "${BENCH_PROM_RETENTION}"
    cat <<'EOS'
    ( umask 077; printf 'OBS_BIND_IP=%s\nPROM_RETENTION=%s\nGF_ADMIN_PASSWORD=%s\n' "${ip}" "${retention}" "${pw}" > /opt/obs/.env.new )
    mv /opt/obs/.env.new /opt/obs/.env
fi
chmod 600 /opt/obs/.env
docker compose -f /opt/obs/docker-compose.yml --env-file /opt/obs/.env up -d --remove-orphans >&2 || fail compose-up
prom=""; graf=""; p0="$(date +%s)"
while :; do
    if [ -z "${prom}" ] && curl -sf --max-time 5 http://127.0.0.1:9090/-/ready >/dev/null 2>&1; then prom=ready; fi
    if [ -z "${graf}" ] && curl -sf --max-time 5 http://127.0.0.1:3000/api/health >/dev/null 2>&1; then graf=ok; fi
    if [ -n "${prom}" ] && [ -n "${graf}" ]; then break; fi
    if [ "$(( $(date +%s) - p0 ))" -ge 120 ]; then
        docker compose -f /opt/obs/docker-compose.yml --env-file /opt/obs/.env ps >&2 || true
        [ -n "${prom}" ] || fail prometheus-not-ready
        fail grafana-not-healthy
    fi
    sleep 3
done
echo "OBS_STACK_OK bench-obs prom=ready grafana=ok secs=$(( $(date +%s) - t0 ))"
EOS
}

# bench_obs_bringup — the bring-up session: bench_obs_bringup_script on the stdin of the VM's
# `sudo bash -s` (tn_iap_ssh_stdin). Its last line must be OBS_STACK_OK, else bench_die.
bench_obs_bringup() {
    local inst="${BENCH_OBS_INSTANCE}" zone="${BENCH_OBS_ZONE}" script out="" rc=0 last
    echo "    + bench_obs_bringup_script | tn_iap_ssh_stdin ${inst} ${zone}   (${BENCH_OBS_BUNDLE_DIR} + ${BENCH_OBS_DASHBOARDS_DIR}/*metrics*.json -> /opt/obs; docker compose up)"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    script="$(bench_obs_bringup_script)" || bench_die "${inst}: the bring-up script could not be built"
    out="$(printf '%s\n' "${script}" | tn_iap_ssh_stdin "${inst}" "${zone}")" || rc=$?
    [ -z "${out}" ] || printf '%s\n' "${out}" | sed 's/^/      /'
    last="$(printf '%s\n' "${out}" | tr -d '\r' | sed '/^[[:space:]]*$/d' | tail -n 1)"
    case "${last}" in
        "OBS_STACK_OK bench-obs "*) [ "${rc}" -eq 0 ] || bench_die "${inst}: the bring-up session ended rc ${rc} after OBS_STACK_OK — ${BENCH_OBS_HINT_STEP8}" ;;
        *) bench_die "${inst}: the stack did not come up (session rc ${rc}; last line: ${last:-<none>}) — ${BENCH_OBS_HINT_STEP8}" ;;
    esac
}

# bench_obs_tunnel_up — the two supervised local forwards to the VM (bench-lib's _bench_tunnel_start):
# localhost:BENCH_OBS_PROM_LOCAL_PORT -> 127.0.0.1:9090 (pid file tunnel-obs-prom.pid, probed with a
# Prometheus query) and localhost:BENCH_OBS_GRAFANA_LOCAL_PORT -> 127.0.0.1:3000
# (tunnel-obs-grafana.pid, probed with Grafana's health endpoint). rc 0 both up; 1 the Prometheus
# forward did not come up (whatever Grafana's did); 2 only the Grafana forward did not.
bench_obs_tunnel_up() {
    local prom=0 graf=0
    _bench_obs_knobs_ok
    # shellcheck disable=SC2016  # the probes are eval'd by _bench_tunnel_start
    _bench_tunnel_start "${BENCH_RESULTS_DIR}/tunnel-obs-prom.pid" "${BENCH_OBS_INSTANCE}" "${BENCH_OBS_ZONE}" \
        "${BENCH_OBS_PROM_LOCAL_PORT}" "127.0.0.1:9090" \
        'curl -sf --max-time 5 "${BENCH_PROM_URL}/query?query=up"' "${BENCH_PROM_URL}" || prom=1
    # shellcheck disable=SC2016  # the probes are eval'd by _bench_tunnel_start
    _bench_tunnel_start "${BENCH_RESULTS_DIR}/tunnel-obs-grafana.pid" "${BENCH_OBS_INSTANCE}" "${BENCH_OBS_ZONE}" \
        "${BENCH_OBS_GRAFANA_LOCAL_PORT}" "127.0.0.1:3000" \
        'curl -sf --max-time 5 "${BENCH_GRAFANA_URL}/api/health"' "${BENCH_GRAFANA_URL}" || graf=1
    if [ "${prom}" -ne 0 ]; then return 1; fi
    if [ "${graf}" -ne 0 ]; then return 2; fi
    return 0
}

# _bench_obs_forwards <resume hint> — bench_obs_tunnel_up for ensure and require: bench_die (with the
# hint) when the Prometheus forward is down; only a warning when Grafana's is (nothing in the run
# reads Grafana with BENCH_PROM_AUTH=0, and with 1 BENCH_GRAFANA_URL is obs-devnet's, not this one).
_bench_obs_forwards() {
    local rc=0 hint="${1:-${BENCH_OBS_HINT_STEP8}}"
    bench_obs_tunnel_up || rc=$?
    case "${rc}" in
        0) ;;
        2) bench_warn "${BENCH_OBS_INSTANCE}: the Grafana forward (localhost:${BENCH_OBS_GRAFANA_LOCAL_PORT}) did not come up — nothing in the run reads it; continuing (see ${BENCH_RESULTS_DIR}/tunnel.log)" ;;
        *) bench_die "${BENCH_OBS_INSTANCE}: the Prometheus forward (localhost:${BENCH_OBS_PROM_LOCAL_PORT}) did not come up (see ${BENCH_RESULTS_DIR}/tunnel.log) — ${hint}" ;;
    esac
}

# _bench_obs_prom_answers <resume hint> — Prometheus answers a query through its local forward, else
# bench_die with the hint.
_bench_obs_prom_answers() {
    curl -sf --max-time 20 "${BENCH_PROM_URL}/query?query=up" >/dev/null \
        || bench_die "${BENCH_OBS_INSTANCE}: Prometheus does not answer at ${BENCH_PROM_URL}/query?query=up — ${1:-${BENCH_OBS_HINT_STEP8}}"
}

# bench_obs_ensure — deploy step 8: create or keep the VM, wait for its startup script (skipped when
# the VM was already there and its serial console shows it done), bring the stack up, open the two
# forwards (a Grafana forward that does not come up is only a warning), check Prometheus answers
# through its forward (forwards found already up are only pid checks), record
# manifest.obs.{ready_at,prom_local_port,grafana_local_port,ship_logs}, print OBS_READY.
# Idempotent: every part keeps what is already in place.
bench_obs_ensure() {
    local t0 inst="${BENCH_OBS_INSTANCE}" zone="${BENCH_OBS_ZONE}"
    t0="$(bench_now_unix)"
    bench_obs_create
    if [ "${_BENCH_OBS_EXISTING}" = "1" ] && _bench_obs_boot_done "${inst}" "${zone}"; then
        echo "    ${inst}: the startup script already finished (serial console) — no boot wait"
    else
        bench_obs_wait_boot
    fi
    bench_obs_bringup
    if [ "${BENCH_APPLY}" != "1" ]; then
        bench_obs_tunnel_up || true
        echo "      (dry run — ${inst} not ensured)"
        return 0
    fi
    _bench_obs_forwards
    _bench_obs_prom_answers
    bench_manifest_jq --arg at "$(bench_now_iso)" --argjson pp "${BENCH_OBS_PROM_LOCAL_PORT}" \
        --argjson gp "${BENCH_OBS_GRAFANA_LOCAL_PORT}" \
        '.obs.ready_at = $at | .obs.prom_local_port = $pp | .obs.grafana_local_port = $gp | .obs.ship_logs = false' \
        || bench_warn "manifest.obs.ready_at not recorded"
    echo "OBS_READY inst=${inst} ip=${BENCH_OBS_INTERNAL_IP} secs=$(( $(bench_now_unix) - t0 ))"
}

# bench_obs_require — the VM is still there and Prometheus answers on its local forward (steps 10,
# 13, 15 and the blaster). bench_die when describe says the VM is not found (resume with --only 8),
# when describe fails otherwise three times 5 s apart, or when Prometheus does not answer; a Grafana
# forward that does not come up is only a warning; one `df` over IAP warns at
# BENCH_OBS_DISK_MAX_PCT % or more and never stops the run.
bench_obs_require() {
    local inst="${BENCH_OBS_INSTANCE}" zone="${BENCH_OBS_ZONE}" out pct
    _bench_obs_knobs_ok
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "    bench-obs: ${inst} must exist; its forwards; Prometheus must answer ${BENCH_PROM_URL}/query?query=up; data disk warn at ${BENCH_OBS_DISK_MAX_PCT}%"
        bench_obs_urls
        bench_obs_tunnel_up || true
        return 0
    fi
    _bench_obs_exists_retry \
        || bench_die "${inst} is gone — ${BENCH_OBS_HINT_RESUME}; step 8 recreates it and re-points every node's Alloy"
    bench_obs_urls
    _bench_obs_forwards "${BENCH_OBS_HINT_RESUME}"
    _bench_obs_prom_answers "${BENCH_OBS_HINT_RESUME}"
    out="$(tn_iap_ssh "${inst}" "${zone}" "df --output=pcent /mnt/obs-data")" || out=""
    pct="$(printf '%s\n' "${out}" | tr -d ' %\r' | grep -E '^[0-9]+$' | tail -n 1)" || pct=""
    if [ -z "${pct}" ]; then
        bench_warn "${inst}: could not read the data disk use (df /mnt/obs-data over IAP) — continuing"
    elif [ "${pct}" -ge "${BENCH_OBS_DISK_MAX_PCT}" ]; then
        bench_warn "${inst}: data disk /mnt/obs-data is ${pct}% (>= BENCH_OBS_DISK_MAX_PCT ${BENCH_OBS_DISK_MAX_PCT}%) — warn only; the run continues"
    else
        echo "    ✓ ${inst}: Prometheus answers; data disk ${pct}%"
    fi
}

# bench_obs_prom_snapshot_pull <dest> — the teardown's copy of the run's metrics: ask Prometheus for
# a TSDB snapshot (admin API, through the local forward), then stream it off the VM with
# bench_pull_stream into <dest>/bench-obs-prometheus-<UTC>.tar.gz, record
# manifest.obs.prom_snapshot{name,file,bytes,at} and print OBS_SNAPSHOT. Warn-only: rc 0 always.
# BENCH_OBS_PULL_PROM=0 skips it (one line).
bench_obs_prom_snapshot_pull() {
    local dest="${1:-}" inst="${BENCH_OBS_INSTANCE}" zone="${BENCH_OBS_ZONE}" out resp name rc=0 bytes rel
    if [ "${BENCH_OBS_PULL_PROM:-1}" = "0" ]; then
        echo "    bench-obs: Prometheus snapshot skipped (BENCH_OBS_PULL_PROM=0)"
        return 0
    fi
    if [ -z "${dest}" ]; then bench_warn "bench_obs_prom_snapshot_pull <dest>: no destination — no snapshot"; return 0; fi
    out="${dest}/bench-obs-prometheus-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
    echo "    + curl -sS -XPOST ${BENCH_PROM_URL}/admin/tsdb/snapshot"
    echo "    + bench_pull_stream ${inst} ${zone} gz ${out} cmd 'sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots <name> | gzip -1'"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    resp="$(curl -sS --max-time 120 -XPOST "${BENCH_PROM_URL}/admin/tsdb/snapshot")" || {
        bench_warn "${inst}: the Prometheus snapshot request failed — no snapshot pulled; the teardown continues"
        return 0
    }
    name="$(printf '%s' "${resp}" | jq -r 'select(.status == "success") | .data.name // empty' 2>/dev/null)" || name=""
    case "${name}" in
        ''|*[!A-Za-z0-9_-]*)
            bench_warn "${inst}: no usable snapshot name in Prometheus's answer (${resp:0:200}) — no snapshot pulled; the teardown continues"
            return 0 ;;
    esac
    mkdir -p "${dest}" || { bench_warn "${inst}: cannot create ${dest} — no snapshot pulled"; return 0; }
    bench_pull_stream "${inst}" "${zone}" gz "${out}" cmd \
        "sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots ${name} | gzip -1" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        bench_warn "${inst}: snapshot ${name} not pulled (bench_pull_stream rc ${rc}) — the teardown continues"
        return 0
    fi
    # The remote pipeline's status is gzip's, so a tar cut short inside a whole gzip stream lands.
    if ! gzip -cd -- "${out}" 2>/dev/null | tar -tf - >/dev/null 2>&1; then
        bench_warn "${inst}: ${out##*/} does not list as a whole tar archive — kept, but it may be incomplete"
    fi
    bytes="$(wc -c < "${out}" | tr -d ' ')"
    rel="${out#"${BENCH_RESULTS_DIR}"/}"
    bench_manifest_jq --arg n "${name}" --arg f "${rel}" --argjson b "${bytes}" --arg at "$(bench_now_iso)" \
        '.obs.prom_snapshot = {name: $n, file: $f, bytes: $b, at: $at}' \
        || bench_warn "manifest.obs.prom_snapshot not recorded"
    echo "OBS_SNAPSHOT inst=${inst} name=${name} bytes=${bytes} file=${rel}"
    return 0
}

# bench_obs_plan_lines <step> — the plan / dry-run text for deploy step 2 (create) or 8 (ensure).
bench_obs_plan_lines() {
    local images
    case "${1:-}" in
        2)
            echo "    bench-obs: ${BENCH_OBS_INSTANCE} in ${BENCH_OBS_ZONE}, ${BENCH_OBS_MACHINE_TYPE}, debian-12, 20 GB pd-balanced boot disk"
            echo "      + ${BENCH_OBS_DISK_GB} GB pd-ssd data disk (device obs-data, /mnt/obs-data); tag bench-obs, labels ${BENCH_LABELS},tn-role=obs;"
            echo "      ephemeral external IP, no DNS/TLS/static IP/firewall rule; startup script ${BENCH_OBS_STARTUP_SCRIPT}"
            echo "      an existing ${BENCH_OBS_INSTANCE} is kept only when it is this run's (tag bench-obs, bench-run=${BENCH_RUN_ID}); any other is refused"
            ;;
        8)
            images="$(sed -n 's/^[[:space:]]*image:[[:space:]]*//p' "${BENCH_OBS_BUNDLE_DIR}/docker-compose.yml" 2>/dev/null | tr '\n' ' ')" || images=""
            echo "    bench-obs: create or keep ${BENCH_OBS_INSTANCE}; wait for '[obs-startup] … done' on its serial console (at most ${BENCH_OBS_BOOT_TIMEOUT_SECS} s)"
            echo "      bring-up over IAP (sudo bash -s): ${BENCH_OBS_BUNDLE_DIR} + ${BENCH_OBS_DASHBOARDS_DIR}/*metrics*.json -> /opt/obs,"
            echo "      docker compose up ${images:-prometheus + grafana}(retention ${BENCH_PROM_RETENTION}); metrics only, no Loki"
            echo "      forwards localhost:${BENCH_OBS_PROM_LOCAL_PORT} -> ${BENCH_OBS_INSTANCE}:9090 (${BENCH_PROM_URL}), localhost:${BENCH_OBS_GRAFANA_LOCAL_PORT} -> ${BENCH_OBS_INSTANCE}:3000 (${BENCH_GRAFANA_URL})"
            echo "      the nodes push to http://<internal ip of ${BENCH_OBS_INSTANCE}>:9090/api/v1/write"
            ;;
        *)
            echo "❌ bench_obs_plan_lines <2|8>: no plan text for step '${1:-}'" >&2
            return 2 ;;
    esac
}
