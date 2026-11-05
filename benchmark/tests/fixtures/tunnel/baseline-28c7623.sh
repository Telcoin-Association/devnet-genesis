# Baseline for test_tunnel.py's parity tests: bench-lib.sh's ssh-mode tunnel supervisor and its RPC
# tunnel and Prometheus query functions exactly as they were at commit 28c7623, before the bench-obs
# forwards shared the supervisor. Cut out by the test's own extraction (supervisor_assignment and
# shell_function over `git show 28c7623:benchmark/bench-lib.sh`, in this order); test_tunnel.py checks
# this text against that commit whenever the checkout has it. Never edit by hand.
IFS= read -r -d '' BENCH_TUNNEL_SUPERVISOR <<'EOS' || true
fails=0
while :; do
    [ "${fails}" -lt "${BENCH_TUNNEL_MAX_FAILS:-5}" ] || { echo "tunnel: giving up after ${fails} consecutive failures at $(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit 1; }
    t0="$(date +%s)"
    gcloud compute ssh "$1" --zone="$2" --project="$3" --tunnel-through-iap \
        --ssh-flag="-N" --ssh-flag="-L" --ssh-flag="localhost:$4:127.0.0.1:8545" \
        --ssh-flag="-o ServerAliveInterval=15" --ssh-flag="-o ServerAliveCountMax=3" \
        --ssh-flag="-o ExitOnForwardFailure=yes" --ssh-flag="-o StrictHostKeyChecking=accept-new" \
        </dev/null &
    child=$!
    echo "tunnel: start $(date -u +%Y-%m-%dT%H:%M:%SZ) mode=ssh target=$1:8545 local=$4 pid=${child}"
    rc=0; wait "${child}" || rc=$?
    up=$(( $(date +%s) - t0 ))
    if [ "${up}" -ge "${BENCH_TUNNEL_MIN_UP_SECS:-20}" ]; then fails=0; else fails=$((fails + 1)); fi
    echo "tunnel: exit $(date -u +%Y-%m-%dT%H:%M:%SZ) rc=${rc} up=${up}s fails=${fails}/${BENCH_TUNNEL_MAX_FAILS:-5}"
    if perl -e 'alarm shift; exec @ARGV' 60 gcloud compute instances describe "$1" --zone="$2" --project="$3" \
        --format='value(status)' </dev/null 2>&1 >/dev/null | grep -qi 'not found'; then
        echo "tunnel: $1 is gone (instances describe: not found) at $(date -u +%Y-%m-%dT%H:%M:%SZ); not restarting"
        exit 0
    fi
    [ "${fails}" -ge "${BENCH_TUNNEL_MAX_FAILS:-5}" ] || { echo "tunnel: restarting in 3 s"; sleep 3; }
done
EOS
bench_tunnel_pidfile() { printf '%s' "${BENCH_RESULTS_DIR}/tunnel.pid"; }
bench_tunnel_up() {
    local pidf pid waited=0 mode="${BENCH_TUNNEL_MODE:-ssh}" maxf="${BENCH_TUNNEL_MAX_FAILS:-5}" minup="${BENCH_TUNNEL_MIN_UP_SECS:-20}"
    pidf="$(bench_tunnel_pidfile)"
    if [ -f "${pidf}" ] && kill -0 "$(cat "${pidf}")" 2>/dev/null; then
        echo "    tunnel already up (pid $(cat "${pidf}")) -> ${RPC_URL}"; return 0
    fi
    case "${maxf}" in ''|*[!0-9]*|0*) bench_warn "BENCH_TUNNEL_MAX_FAILS='${maxf}' is not a positive integer — using 5"; maxf=5 ;; esac
    case "${minup}" in ''|*[!0-9]*) bench_warn "BENCH_TUNNEL_MIN_UP_SECS='${minup}' is not a whole number of seconds — using 20"; minup=20 ;; esac
    if [ "${mode}" = "ssh" ]; then
        printf '    + gcloud compute ssh %s --zone=%s --project=%s --tunnel-through-iap --ssh-flag=-N --ssh-flag=-L --ssh-flag=localhost:%s:127.0.0.1:8545 ... &   (supervised: restarted on a drop, gives up after %s consecutive failures shorter than %s s or when the instance is gone; >> %s)\n' \
            "${INSTANCE_NAMES[0]}" "${ZONES[0]}" "${PROJECT_ID}" "${BENCH_TUNNEL_PORT}" "${maxf}" "${minup}" "${BENCH_RESULTS_DIR}/tunnel.log"
    else
        printf '    + gcloud compute start-iap-tunnel %s 8545 --local-host-port=localhost:%s --zone=%s --project=%s &   (BENCH_TUNNEL_MODE=%s; >> %s)\n' \
            "${INSTANCE_NAMES[0]}" "${BENCH_TUNNEL_PORT}" "${ZONES[0]}" "${PROJECT_ID}" "${mode}" "${BENCH_RESULTS_DIR}/tunnel.log"
    fi
    if [ "${BENCH_APPLY}" != "1" ]; then echo "      (dry run — not executed)"; return 0; fi
    mkdir -p "${BENCH_RESULTS_DIR}"
    if [ "${mode}" = "ssh" ]; then
        BENCH_TUNNEL_MAX_FAILS="${maxf}" BENCH_TUNNEL_MIN_UP_SECS="${minup}" \
            nohup setsid bash -c "${BENCH_TUNNEL_SUPERVISOR}" tn-bench-tunnel-supervisor \
            "${INSTANCE_NAMES[0]}" "${ZONES[0]}" "${PROJECT_ID}" "${BENCH_TUNNEL_PORT}" \
            >> "${BENCH_RESULTS_DIR}/tunnel.log" 2>&1 &
        pid=$!
    else
        nohup gcloud compute start-iap-tunnel "${INSTANCE_NAMES[0]}" 8545 \
            --local-host-port="localhost:${BENCH_TUNNEL_PORT}" --zone="${ZONES[0]}" --project="${PROJECT_ID}" \
            >> "${BENCH_RESULTS_DIR}/tunnel.log" 2>&1 &
        pid=$!
        echo "tunnel: start $(bench_now_iso) mode=websocket target=${INSTANCE_NAMES[0]}:8545 local=${BENCH_TUNNEL_PORT} pid=${pid}" \
            >> "${BENCH_RESULTS_DIR}/tunnel.log"
    fi
    echo "${pid}" > "${pidf}"
    while [ "${waited}" -lt 45 ]; do
        if cast chain-id --rpc-url "${RPC_URL}" >/dev/null 2>&1; then
            echo "    ✓ tunnel up (pid ${pid}) -> ${RPC_URL}"; return 0
        fi
        kill -0 "${pid}" 2>/dev/null || break
        sleep 3; waited=$((waited + 3))
    done
    echo "❌ IAP tunnel to ${INSTANCE_NAMES[0]}:8545 did not come up; see ${BENCH_RESULTS_DIR}/tunnel.log" >&2
    return 1
}
bench_tunnel_down() {
    local pidf p; pidf="$(bench_tunnel_pidfile)"
    if [ -f "${pidf}" ]; then
        p="$(cat "${pidf}")"
        # the ssh-mode supervisor is a session leader: kill its whole group (supervisor + gcloud + ssh)
        { kill -- -"${p}" 2>/dev/null || kill "${p}" 2>/dev/null; } && echo "    stopped tunnel pid ${p}"
        rm -f "${pidf}"
    fi
}
bench_prom_query() {
    local pw esc
    pw="$(tn_secret "${OBS_GRAFANA_SECRET_NAME}")" || return 1
    esc="$(printf '%s' "${pw}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    printf 'user = "admin:%s"\n' "${esc}" | curl -sS --max-time 20 -K - --get \
        --data-urlencode "query=$1" \
        "${BENCH_GRAFANA_URL}/api/datasources/proxy/uid/${BENCH_PROM_DATASOURCE_UID}/api/v1/query"
}
