# shellcheck shell=bash
# Contract-faithful stand-ins for what the teardown takes from benchmark/obs-lib.sh and the knobs
# block of benchmark/config.sh (both unit U-O1; tasks/checkpoint-bench4-design.md, "D-C contracts")
# and from bench-lib.sh's _bench_tunnel_start (unit U-O3), for a tree in which they have not landed.
# test_teardown_local_gate.py sources this file at the end of its temporary copy of bench-lib.sh. A
# knob is set only when unset and a function defined only when absent, so once the real ones are in
# place this file changes nothing. No stand-in starts a process: an apply-mode forward whose pidfile
# names no live process is only probed.

: "${BENCH_OBS_INSTANCE:=bench-obs}"
: "${BENCH_OBS_ZONE:=us-west2-a}"
: "${BENCH_OBS_PROM_LOCAL_PORT:=19090}"
: "${BENCH_OBS_GRAFANA_LOCAL_PORT:=13000}"
: "${BENCH_OBS_PULL_PROM:=1}"
: "${BENCH_PROM_AUTH:=0}"
: "${BENCH_PROM_URL:=http://127.0.0.1:${BENCH_OBS_PROM_LOCAL_PORT}/api/v1}"
export BENCH_OBS_INSTANCE BENCH_OBS_ZONE BENCH_OBS_PROM_LOCAL_PORT BENCH_OBS_GRAFANA_LOCAL_PORT \
    BENCH_OBS_PULL_PROM BENCH_PROM_AUTH BENCH_PROM_URL

# U-O1: rc 0 when describe answers for the bench-obs VM, 1 when it says not found, 2 when the describe
# itself failed (its stderr shown).
declare -F bench_obs_exists >/dev/null || bench_obs_exists() {
    local err rc=0
    err="$(gcloud compute instances describe "${BENCH_OBS_INSTANCE}" --zone="${BENCH_OBS_ZONE}" --project="${PROJECT_ID}" \
        --format='value(name)' 2>&1 >/dev/null)" || rc=$?
    [ "${rc}" -ne 0 ] || return 0
    case "${err}" in *"not found"*) return 1 ;; esac
    printf '%s\n' "${err}" | sed 's/^/      /' >&2
    return 2
}

# U-O1: no gcloud; BENCH_OBS_INTERNAL_IP from itself, else manifest.obs.internal_ip, else the placeholder.
declare -F bench_obs_urls >/dev/null || bench_obs_urls() {
    local ip="${BENCH_OBS_INTERNAL_IP:-}"
    [ -n "${ip}" ] || ip="$(jq -r '.obs.internal_ip // empty' "$(bench_manifest)" 2>/dev/null)" || ip=""
    BENCH_OBS_INTERNAL_IP="${ip:-bench-obs-internal-ip.invalid}"
    OBS_METRICS_PUSH_URL="http://${BENCH_OBS_INTERNAL_IP}:9090/api/v1/write"
    export BENCH_OBS_INTERNAL_IP OBS_METRICS_PUSH_URL
}

# U-O3: <pidfile> <inst> <zone> <local-port> <remote-host:port> <probe-cmd> <desc>; the plan line,
# the dry run, the "already up" check and the probe, without the supervisor.
declare -F _bench_tunnel_start >/dev/null || _bench_tunnel_start() {
    if [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; then echo "    tunnel already up (pid $(cat "$1")) -> $7"; return 0; fi
    printf '    + gcloud compute ssh %s --zone=%s --project=%s --tunnel-through-iap --ssh-flag=-N --ssh-flag=-L --ssh-flag=localhost:%s:%s ... &   (supervised; >> %s)\n' \
        "$2" "$3" "${PROJECT_ID}" "$4" "$5" "${BENCH_RESULTS_DIR}/tunnel.log"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    if eval "$6" >/dev/null 2>&1; then echo "    ✓ tunnel up (pid -) -> $7"; return 0; fi
    echo "❌ IAP tunnel to $2:${5##*:} did not come up; see ${BENCH_RESULTS_DIR}/tunnel.log" >&2
    return 1
}

# U-O1: the two forwards, Prometheus then Grafana.
# shellcheck disable=SC2016  # the probes are eval'd by _bench_tunnel_start
declare -F bench_obs_tunnel_up >/dev/null || bench_obs_tunnel_up() {
    _bench_tunnel_start "${BENCH_RESULTS_DIR}/tunnel-obs-prom.pid" "${BENCH_OBS_INSTANCE}" "${BENCH_OBS_ZONE}" \
        "${BENCH_OBS_PROM_LOCAL_PORT}" "127.0.0.1:9090" 'curl -sf "${BENCH_PROM_URL}/query?query=up"' "${BENCH_PROM_URL}" \
        || return 1
    _bench_tunnel_start "${BENCH_RESULTS_DIR}/tunnel-obs-grafana.pid" "${BENCH_OBS_INSTANCE}" "${BENCH_OBS_ZONE}" \
        "${BENCH_OBS_GRAFANA_LOCAL_PORT}" "127.0.0.1:3000" 'curl -sf "${BENCH_GRAFANA_URL}/api/health"' "${BENCH_GRAFANA_URL}"
}

# U-O1: <dest> — snapshot POST, then the gzipped tar of it into <dest>; warn-only, rc 0 always; a dry
# run prints the two steps and runs neither.
declare -F bench_obs_prom_snapshot_pull >/dev/null || bench_obs_prom_snapshot_pull() {
    local dest="$1" name out bytes
    if [ "${BENCH_OBS_PULL_PROM}" = "0" ]; then echo "    bench-obs: Prometheus snapshot skipped (BENCH_OBS_PULL_PROM=0)"; return 0; fi
    out="${dest}/bench-obs-prometheus-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
    echo "    + curl -sS -XPOST ${BENCH_PROM_URL}/admin/tsdb/snapshot"
    echo "    + bench_pull_stream ${BENCH_OBS_INSTANCE} ${BENCH_OBS_ZONE} gz ${out} cmd 'sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots <name> | gzip -1'"
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    name="$(curl -sS -XPOST "${BENCH_PROM_URL}/admin/tsdb/snapshot" | jq -r '.data.name // empty' 2>/dev/null)" || name=""
    if [ -z "${name}" ]; then bench_warn "bench-obs: no Prometheus snapshot (the snapshot request failed)"; return 0; fi
    mkdir -p "${dest}"
    if ! bench_pull_stream "${BENCH_OBS_INSTANCE}" "${BENCH_OBS_ZONE}" gz "${out}" cmd \
        "sudo tar -cf - -C /mnt/obs-data/prometheus/snapshots ${name} | gzip -1"; then
        bench_warn "bench-obs: Prometheus snapshot ${name} not pulled"; return 0
    fi
    bytes="$(wc -c < "${out}" | tr -d ' ')"
    bench_manifest_jq --arg n "${name}" --arg f "${out##*/}" --argjson b "${bytes}" --arg t "$(bench_now_iso)" \
        '.obs.prom_snapshot = {name: $n, file: $f, bytes: $b, at: $t}' || bench_warn "manifest.obs.prom_snapshot not written"
    echo "OBS_SNAPSHOT inst=${BENCH_OBS_INSTANCE} name=${name} bytes=${bytes} file=${out}"
    return 0
}
