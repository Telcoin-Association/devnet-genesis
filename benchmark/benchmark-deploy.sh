#!/usr/bin/env bash
#
# benchmark-deploy.sh — stand up the throwaway benchmark fleet (10 validators + 1 observer,
# chain 32286, 20-min epochs) in tn-devnet, blast it from per-zone COS VMs, collect the
# evidence, and optionally tear it all down. The live devnet is never touched: no devnet
# instance, tag, rule, DNS name, LB or obs setting is created, modified or deleted.
#
# Dry run by default: without --yes it prints this run's full step plan (with the concrete
# commands) after local-only checks, and exits 0 without a single GCP call. With --yes it
# executes the steps; every gcloud mutation prints its argv first, and everything the script
# prints is also copied to results/<run>/logs/deploy-<UTC stamp>.log (a new file per invocation).
#
#    -  gate (--yes)     before ANY step: the node image probe when steps 0/5/6/7 are selected and the
#                        run has not pinned an image yet (bench-lib bench_node_image_probe: digest,
#                        telcoin -V sha, CLI flags, node-image-contract.txt strings, the EXPECT_* env);
#                        from then on every step and sub-script runs <repo>@sha256:<digest>
#                        (BENCH_DOCKER_IMAGE); manifest.json gets the probe, and consensus_parameters
#                        when step 7 (which stages PARAMETERS_FILE) is selected. Refuses sub-second
#                        delays (max_header_delay < 1000 ms) on a build not subsecond-from-genesis.
#                        Also the pinned :blast-v2-<sha> image, cloudbuild.yaml, config.bench.toml and
#                        deployments-bench.json that the selected steps need
#    0  preflight        auth + tools + python3 PyYAML + TN_NODE_SCRIPTS_REF a full 40-hex sha +
#                        no leftover bench-*/benchmark=1 resources + accounts file +
#                        empty benchmark/genesis + firewall/tag hygiene +
#                        each machine type in its nodes' zones (BENCH_NODE_MACHINE_TYPES; a fallback
#                        zone against its node's type), the first blaster type in every validator
#                        zone and BENCH_OBS_MACHINE_TYPE in BENCH_OBS_ZONE + a hyperdisk-* disk type
#                        offered in every fleet zone + quota headroom per region (vCPUs per family
#                        metric per node, addresses, disk, a -lssd node's local SSD; C4 vCPUs "not checked":
#                        regions describe lists no C4 metric; the bench-obs VM counted in its region); one die lists
#                        every failure; pre-snapshots. obs-devnet is not read: the bench has its own obs VM
#    1  image            :blast-v2-<sha> exists, else Cloud Build builds it (synchronous);
#                        `IMAGE blast --help` must carry every contract flag (when docker exists)
#    2  instances        common/create-instances.sh on the bench profile (-> logs/create-instances-<UTC>.log;
#                        several machine types: one call per type with BENCH_CREATE_MACHINE_TYPE, and the
#                        -lssd nodes by bench_create_node with --maintenance-policy=TERMINATE; BENCH_NODE_ZONES:
#                        zones.env + manifest.zone_overrides[] first);
#                        on a stockout that node moves to its next BENCH_ZONE_FALLBACKS zone (zones.env,
#                        manifest.zone_fallbacks[]) and the create runs again, at most 3 rounds; assert tag
#                        bench-node + label benchmark=1 on every node; label boot disks; manifest.instances[],
#                        zones_used; then bench_obs_create: the run's own bench-obs VM (metrics only,
#                        create-or-keep; one of another run is refused) -> manifest.obs
#    3  bootstrap        serial-console marker "devnet-startup.sh complete" on every node; with
#                        BENCH_NODE_DATADIR_LSSD=1 then, per local-SSD node (BENCH_NODE_JOBS at a time), one IAP
#                        session (bench_lssd_mount_script): its first local NVMe SSD becomes the data directory
#                        (ext4, the fstab options of /, fstab + RequiresMountsFor) -> logs/lssd-mount-<UTC>.log;
#                        LSSD_MOUNT -> manifest.instances[].data_disk; LSSD_MOUNT_SUMMARY; a failed node stops
#    4  firewall         benchmark-firewall.sh apply --yes
#    5  keygen           ../devnet-keygen.sh           (bench profile via CONFIG_FILE) -> logs/keygen-<UTC>.log;
#                        its KEYGEN_DONE lines -> manifest.keygen_timing + node_info_rpc
#    6  genesis          ../devnet-genesis-build.sh    (workspace benchmark/, chain 32286)
#    7  finalize         ONE coordinated start; no node runs before every node is configured:
#                        network-config    ../devnet-network-config.sh --yes (Closed admission on all
#                                          nodes, rendered under benchmark/genesis/network-config/)
#                        stage-only        ../devnet-finalize.sh --stage-only (stage + v2 finalize, then
#                                          stop: unit enabled, inactive) -> logs/finalize-stage-<utc>.log
#                        pre-start config  per node, ONE IAP session (a local-SSD node: bench_lssd_check_script
#                                          first, PRECFG_FAIL unless the data directory is the SSD; then
#                                          bench_fsync_probe_script, then
#                                          bench_prestart_script, on stdin): the datadir fsync probe
#                                          (FSYNC_PROBE -> node_startup.fsync_probe; never fatal), then
#                                          --http.addr/--ws.addr 0.0.0.0, --metrics 127.0.0.1:<port>, the
#                                          log filter, BENCH_NODE_DB_SYNC_MODE when set, per-node
#                                          parameters.yaml overrides; PRECFG_OK; after every node one
#                                          FSYNC_PROBE_SUMMARY line (⚠: a slow node or a failed probe; never fatal)
#                        start-all         ../devnet-finalize.sh --start-all (every unit at one due time)
#                                          -> logs/finalize-start-<utc>.log; COORDINATED_START ->
#                                          manifest.coordinated_start; stops when spread_secs > 10
#                        A re-run (--from 7) converges: network-config is idempotent, stage-only skips
#                        PRESTAGED/RUNNING nodes, pre-start skips nodes RUNNING since the coordinated start
#                        and accepts flags already set, start-all skips RUNNING nodes and the first start
#                        stays the record (later ones: manifest.coordinated_start_reruns). A unit RUNNING
#                        before any coordinated start stops the step (stop it by hand, then re-run).
#    8  observability    bench_obs_ensure: bench-obs up (created if absent, booted, Prometheus +
#                        Grafana brought up, forwards 127.0.0.1:19090 -> :9090 and 127.0.0.1:13000 ->
#                        :3000), then every validator CvvActive (bench_fleet_ready 0), then per node ONE
#                        IAP session, no node restart: a throwaway token (openssl rand -hex 16; bench-obs
#                        takes no ingest auth) on the session's stdin only -> setup-observability.sh
#                        --json --enable-metrics --token-stdin aimed at a black-hole URL (done ok:true,
#                        "Node already serves a metrics endpoint (--metrics).", container StartedAt
#                        unchanged, NRestarts=0), then (same session) bench-obs's /-/ready must answer
#                        from the node, stop Alloy, wipe its WAL, set TN_CHAIN=bench TN_NODE=<instance> +
#                        http://<bench-obs internal IP>:9090/api/v1/write, start Alloy — metrics only, no
#                        sample labelled network="devnet" ever leaves a bench node. obs-devnet is never
#                        touched (never create-obs-instance.sh, never devnet-observability.sh).
#    9  post-config      per node, ONE IAP session each, verify only (no restart, no start-script
#                        edit): the running container's args (--http.addr/--ws.addr 0.0.0.0, --metrics,
#                        log filters), <DATA_DIR from .node-meta>/parameters.yaml, the bench Alloy
#                        labels, eth_chainId on the internal IP + consensus progressing since the
#                        coordinated start (blocks rose, or subdag committed/quorum reached in its log
#                        — an idle chain stays at block 0), its boot lines (git sha, max/min header +
#                        max batch delay, fork schedule) against manifest.json -> manifest.node_startup;
#                        install node-sampler
#   10  health gate      wait_healthy x11, IAP tunnel -> cast chain-id == 32286, bench_obs_require
#                        (bench-obs exists, its forwards answer; disk use warn-only), bench-obs Prometheus
#                        min by (node)(tn_primary_round{network="bench"}) rising on all 11,
#                        Prometheus: count(count by (node)(tn_engine_canonical_height{network="bench"})) == 11
#                        and no bench node has any series labelled network="devnet";
#                        recovery-schedule.py: registry epoch duration == EPOCH_DURATION_SECS -> manifest.registry_probe;
#                        bench_admission_gate: Closed admission (primary + worker), fallback 0 on every node
#                        -> manifest.admission + fleet_modes
#   11  contracts        (--with-contracts) tn-contracts worktree bench/<run> -> devnet-contracts.sh
#   12  IAM + bucket     secretAccessor on the bench secrets for the compute SA; gs://<bucket>
#   13  fund             bench_obs_require, every validator CvvActive (bench_fleet_ready, waits up to one epoch boundary
#                        -> manifest.fleet_ready), then benchmark-blast.sh fund --yes
#   14  blast            benchmark-blast.sh run --yes
#   15  collect          benchmark-blast.sh collect --yes, bench_obs_require, then
#                        tn-transaction-generator/bench/collect-gcp-metrics.py (--prom-url BENCH_PROM_URL
#                        --prom-no-auth while BENCH_PROM_AUTH=0: bench-obs's Prometheus through its forward);
#                        after a chaos kill that landed (BENCH_COLLECT_WAIT_REJOIN=1) the Prometheus window
#                        ends once every validator is CvvActive again (--start/--end; manifest.prom_window)
#   16  teardown         (--with-teardown) benchmark-teardown.sh --yes
#
# Usage:
#   BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh                 # plan only
#   BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --yes --with-contracts
#   benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --from 9          # resume
#   benchmark/benchmark-deploy.sh --run r20260923-0100 --yes --only 15         # one step
#   BENCH_RUN_ID=r20260923-0100 benchmark/benchmark-deploy.sh --yes --with-contracts --to 12   # stop after step N
#   benchmark/benchmark-deploy.sh --run r20260923-0100 --note "v05 restarted by hand at 00:12Z"   # add a
#       deviation to manifest.notes ("<text> (operator note, <UTC>)") and exit; nothing else runs
#   benchmark/benchmark-deploy.sh --probe-node-image [REF]   # the gate's node image probe alone (local,
#       no run dir, no manifest; REF defaults to the configured image; with --yes a local image is
#       refused unless its repo digest is the registry's, exactly as at the gate). Expectations:
#       BENCH_DOCKER_IMAGE_EXPECT_DIGEST=sha256:<hex> BENCH_NODE_EXPECT_SHA=<7-40 hex>
#       BENCH_NODE_EXPECT_FORKS=subsecond-from-genesis|adiri-schedule|pre-subsecond
#   A resumed run (--run) keeps the node image its gate pinned (manifest node_image_pinned); a
#   BENCH_DOCKER_IMAGE naming any other image is refused.
#   Review aids (print a remote script and exit; no GCP call):
#   benchmark/benchmark-deploy.sh --print-prestart <instance>     # step 7's pre-start config script
#   benchmark/benchmark-deploy.sh --print-obs-script <instance>   # step 8's session (token: PLACEHOLDER-TOKEN;
#       bench-obs IP: BENCH_OBS_INTERNAL_IP, else the placeholder bench-obs-internal-ip.invalid)
#   benchmark/benchmark-deploy.sh --print-obs-bringup             # step 8's bench-obs bring-up (bench_obs_bringup_script)
#   benchmark/benchmark-deploy.sh --print-postconfig <instance>   # step 9's verify script
#   benchmark/benchmark-deploy.sh --print-lssd-mount <instance>   # step 3's local-SSD mount script
#       (BENCH_NODE_DATADIR_LSSD=1; a node whose data directory stays on the boot disk is refused)

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

LAST_STEP=16
CONFIRM=0; FROM=0; TO="${LAST_STEP}"; ONLY=""; WITH_CONTRACTS=0; WITH_TEARDOWN=0; PRINT_POSTCONFIG=""; PRINT_OBS=""; PRINT_PRESTART=""
PRINT_OBS_BRINGUP=""; PRINT_LSSD_MOUNT=""
PROBE_ONLY=0; PROBE_REF=""; NOTE=""; NOTE_GIVEN=0; RUN_GIVEN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --note) NOTE="${2?--note needs a text}"; NOTE_GIVEN=1; shift ;;   # with --run: append to manifest.notes, then exit
        --note=*) NOTE="${1#*=}"; NOTE_GIVEN=1 ;;
        --from) FROM="${2:?--from needs a step number}"; shift ;;
        --from=*) FROM="${1#*=}" ;;
        --to) TO="${2:?--to needs a step number}"; shift ;;
        --to=*) TO="${1#*=}" ;;
        --only) ONLY="${2:?--only needs a step number}"; shift ;;
        --only=*) ONLY="${1#*=}" ;;
        --with-contracts) WITH_CONTRACTS=1 ;;
        --with-teardown) WITH_TEARDOWN=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; RUN_GIVEN=1; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}"; RUN_GIVEN=1 ;;
        --print-postconfig) PRINT_POSTCONFIG="${2:?--print-postconfig needs an instance}"; shift ;;  # review aid: print step 9's remote script
        --print-prestart) PRINT_PRESTART="${2:?--print-prestart needs an instance}"; shift ;;        # review aid: step 7's pre-start config script
        --print-obs-script) PRINT_OBS="${2:?--print-obs-script needs an instance}"; shift ;;       # review aid: step 8's script, placeholder token
        --print-obs-bringup) PRINT_OBS_BRINGUP=1 ;;                                                 # review aid: step 8's bench-obs bring-up script
        --print-lssd-mount) PRINT_LSSD_MOUNT="${2:?--print-lssd-mount needs an instance}"; shift ;;  # review aid: step 3's local-SSD mount script
        --probe-node-image) PROBE_ONLY=1; case "${2:-}" in ''|-*) ;; *) PROBE_REF="$2"; shift ;; esac ;;
        --probe-node-image=*) PROBE_ONLY=1; PROBE_REF="${1#*=}" ;;
        -h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1' (supported: --yes, --from N, --to N, --only N, --with-contracts, --with-teardown, --run ID, --note TEXT (with --run), --probe-node-image [REF], --print-prestart INST, --print-lssd-mount INST, --print-obs-script INST, --print-obs-bringup, --print-postconfig INST)" >&2; exit 1 ;;
    esac
    shift
done
is_step() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 0 ] && [ "$1" -le "${LAST_STEP}" ]; }
is_step "${FROM}" || { echo "❌ --from must be 0..${LAST_STEP}" >&2; exit 1; }
is_step "${TO}" || { echo "❌ --to must be 0..${LAST_STEP}" >&2; exit 1; }
[ "${FROM}" -le "${TO}" ] || { echo "❌ --from ${FROM} is after --to ${TO}" >&2; exit 1; }
[ -z "${ONLY}" ] || is_step "${ONLY}" || { echo "❌ --only must be 0..${LAST_STEP}" >&2; exit 1; }
[ "${PROBE_ONLY}" -eq 0 ] || [ -n "${BENCH_RUN_ID:-}" ] || BENCH_RUN_ID="r00000000-0000"   # config.sh needs one
export BENCH_RUN_ID="${BENCH_RUN_ID:-}"
DEPLOY_SCOPE="$([ -n "${ONLY}" ] && echo "step ${ONLY}" || echo "steps ${FROM}..${TO}")"

# results/<run>/last-deploy.status from the first moment of an applied deploy (--yes; not a probe, a
# note or a review print): rc=- (running), last_step=starting, started=<now>, so a watcher never reads
# the previous invocation's outcome as this one's (watchers key on started >= their own launch). run_step
# rewrites it with each step's number; an exit before the deploy log starts (an argument, a pinned image,
# config.sh or bench-lib refusing) rewrites it with that exit's rc; deploy_log_stop writes the final one.
# A kill -9 leaves rc=- with the step it was in.
DEPLOY_STATUS_FILE=""; DEPLOY_STARTED=""; DEPLOY_LOG_FILE=""; DEPLOY_LAST_STEP=""
# deploy_status_write <rc> <last step> <ended> — the status file, replaced atomically (no-op without one).
deploy_status_write() {
    local f="${DEPLOY_STATUS_FILE}" tmp
    [ -n "${f}" ] || return 0
    tmp="$(mktemp "${f}.XXXXXX" 2>/dev/null)" || return 0
    if printf 'rc=%s\nlast_step=%s\nfirst_error=-\nstarted=%s\nended=%s\nscope=%s\nlog=%s\n' "$1" "$2" \
            "${DEPLOY_STARTED:--}" "$3" "${DEPLOY_SCOPE:--}" "${DEPLOY_LOG_FILE:--}" > "${tmp}" && mv -f "${tmp}" "${f}"; then :; else
        rm -f "${tmp}"
    fi
    return 0
}
if [ "${CONFIRM}" -eq 1 ] && [ "${PROBE_ONLY}" -eq 0 ] && [ "${NOTE_GIVEN}" -eq 0 ] \
    && [ -z "${PRINT_POSTCONFIG}${PRINT_PRESTART}${PRINT_OBS}${PRINT_OBS_BRINGUP}${PRINT_LSSD_MOUNT}" ]; then
    case "${BENCH_RUN_ID}" in
        ''|r*[!a-z0-9-]*|[!r]*) ;;   # config.sh refuses it (no status file for a run id that cannot exist)
        *)
            if mkdir -p "${DIR}/results/${BENCH_RUN_ID}" 2>/dev/null; then
                DEPLOY_STATUS_FILE="${DIR}/results/${BENCH_RUN_ID}/last-deploy.status"
                DEPLOY_STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
                deploy_status_write - starting -
                trap 'deploy_status_write "$?" starting "$(date -u +%Y-%m-%dT%H:%M:%SZ)"' EXIT
            fi ;;
    esac
fi
# A resumed run keeps the image step 1 verified (the generator checkout may have moved on).
if [ -z "${BENCH_TXGEN_SHA:-}" ] && [ -n "${BENCH_RUN_ID}" ] && [ -f "${DIR}/results/${BENCH_RUN_ID}/manifest.json" ]; then
    BENCH_TXGEN_SHA="$(jq -r '.txgen_git_sha // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    export BENCH_TXGEN_SHA
fi
# A resumed run keeps the node image its gate pinned (the tag may have moved since). An operator
# BENCH_DOCKER_IMAGE naming any other image is refused: a run never silently switches image.
NODE_PIN_FROM_MANIFEST=0
if [ "${PROBE_ONLY}" -eq 0 ] && [ -n "${BENCH_RUN_ID}" ] && [ -f "${DIR}/results/${BENCH_RUN_ID}/manifest.json" ]; then
    _pin="$(jq -r '.node_image_pinned // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    _ref="$(jq -r '.node_image_ref // empty' "${DIR}/results/${BENCH_RUN_ID}/manifest.json" 2>/dev/null || true)"
    if [ -n "${_pin}" ]; then
        if [ -n "${BENCH_DOCKER_IMAGE:-}" ] && [ "${BENCH_DOCKER_IMAGE}" != "${_pin}" ] && [ "${BENCH_DOCKER_IMAGE}" != "${_ref}" ]; then
            echo "❌ run ${BENCH_RUN_ID} is pinned to node image ${_pin} (probed from ${_ref:-?})," >&2
            echo "   but BENCH_DOCKER_IMAGE=${BENCH_DOCKER_IMAGE} names another image. A resumed run never" >&2
            echo "   switches image: unset BENCH_DOCKER_IMAGE (or set it to either ref above), or start a new run." >&2
            exit 1
        fi
        export BENCH_DOCKER_IMAGE="${_pin}"
        NODE_PIN_FROM_MANIFEST=1
    fi
    unset _pin _ref
fi
# shellcheck disable=SC2034  # read by bench-lib.sh (bench_run, manifest writers)
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"   # exports CONFIG_FILE=benchmark/config.sh for every sub-script

# --run <id> --note <text>: a deviation noted while the run is in flight (a hand fix, a re-run, a zone
# move) goes into manifest.notes as "<text> (operator note, <UTC>)"; nothing else runs, nothing is
# contacted.
if [ "${NOTE_GIVEN}" -eq 1 ]; then
    [ "${RUN_GIVEN}" -eq 1 ] || bench_die "--note needs --run <id>: the run whose manifest.notes it extends"
    [ -n "${NOTE}" ] || bench_die "--note needs a non-empty text"
    [ -f "$(bench_manifest)" ] || bench_die "run ${BENCH_RUN_ID} has no manifest ($(bench_manifest)) — nothing to note"
    bench_manifest_note "${NOTE} (operator note, $(bench_now_iso))" || bench_die "could not add the note to $(bench_manifest)"
    echo "✓ manifest.notes += $(jq -c '.notes[-1]' "$(bench_manifest)")"
    exit 0
fi

# --probe-node-image [REF]: the gate's node image probe alone — local, no run directory, no manifest.
if [ "${PROBE_ONLY}" -eq 1 ]; then
    bench_node_image_probe "${PROBE_REF:-${DOCKER_IMAGE}}"
    echo "pinned=${BENCH_NODE_IMAGE_PINNED} sha=${BENCH_NODE_GIT_SHA} forks=${BENCH_NODE_FORK_SCHEDULE}"
    exit 0
fi

BOOTSTRAP_TIMEOUT_SECS=600
BOOTSTRAP_POLL_SECS=15
# Step 7: the widest start spread (max began - min began over the nodes start-all started) the run
# accepts. A committee member that starts > gc_depth (50) rounds after quorum sits out the epoch
# (lessons 2026-11-02); at the bench cadence 10 s is well inside that.
START_SPREAD_MAX_SECS=10
CHAIN_ID_HEX="$(printf '0x%x' "${CHAIN_ID}")"
PROM_COUNT_QUERY="count(count by (node) (tn_engine_canonical_height{network=\"${BENCH_PROM_NETWORK_LABEL}\"}))"
PROM_LEAK_QUERY='count(count by (node) (tn_engine_canonical_height{network="devnet", node=~"bench.*"}))'
PROM_LEAK_ANY_QUERY='count(count by (node) ({network="devnet", node=~"bench.*"}))'
COLLECT_METRICS_PY="${BENCH_TXGEN_BENCH_DIR}/collect-gcp-metrics.py"
DEVNET_TXGEN_MASTER="0x46c26b4fafffaab86437b11f5cdbd1b9f7ddc844"

# run_expect <sha|forks|mhd|nhd|mbd|vt|thr> [<node-index>] — what this run's nodes must report at
# boot: the manifest (node_git_sha, node_fork_schedule, consensus_parameters.*_ms, as the gate
# recorded them) first, else this shell's node image probe / PARAMETERS_FILE. "" when neither has it.
# With a node index, that node's BENCH_NODE_PARAM_OVERRIDES value of the key wins (step 7's pre-start
# config writes it, from this shell's knob, which the gate records as consensus_parameters.overrides). vt (vote_timeout)
# is only ever an override: the fleet file need not set it and older builds do not log it.
run_expect() {
    local m v="" q="" g="" key="" ov=""
    m="$(bench_manifest)"
    case "$1" in
        sha)   q='.node_git_sha';                              g="${BENCH_NODE_GIT_SHA:-}" ;;
        forks) q='.node_fork_schedule';                        g="${BENCH_NODE_FORK_SCHEDULE:-}" ;;
        mhd)   q='.consensus_parameters.max_header_delay_ms';  g="$(bench_params_ms "${PARAMETERS_FILE}" max_header_delay)"; key=max_header_delay ;;
        nhd)   q='.consensus_parameters.min_header_delay_ms';  g="$(bench_params_ms "${PARAMETERS_FILE}" min_header_delay)"; key=min_header_delay ;;
        mbd)   q='.consensus_parameters.max_batch_delay_ms';   g="$(bench_params_ms "${PARAMETERS_FILE}" max_batch_delay)"; key=max_batch_delay ;;
        vt)    key=vote_timeout ;;
        thr)   g="$(bench_params_raw "${PARAMETERS_FILE}" header_num_of_batches_threshold)"; key=header_num_of_batches_threshold ;;
        *) return 1 ;;
    esac
    [ -z "${2:-}" ] || [ -z "${key}" ] || ov="$(bench_node_override "$2" "${key}")"
    if [ -n "${ov}" ]; then
        case "${key}" in header_num_of_batches_threshold) printf '%s' "${ov}" ;; *) bench_dur_ms "${ov}" | tr -d '\n' ;; esac
        return 0
    fi
    [ -z "${q}" ] || [ ! -f "${m}" ] || v="$(jq -r "${q} // empty" "${m}" 2>/dev/null || true)"
    printf '%s' "${v:-${g}}"
}

# disk_desc — "<size> GB <type>", plus the provisioned IOPS/throughput when set (hyperdisk only).
disk_desc() {
    local p="${NODE_DISK_IOPS:+${NODE_DISK_IOPS} IOPS}"
    [ -z "${NODE_DISK_THROUGHPUT}" ] || p="${p:+${p}, }${NODE_DISK_THROUGHPUT} MiB/s"
    printf '%s GB %s%s' "${NODE_DISK_SIZE}" "${NODE_DISK_TYPE}" "${p:+ (provisioned ${p})}"
}

# fleet_zones — the distinct zones of the whole fleet, space-separated, sorted.
fleet_zones() {
    local z; z="$(printf '%s\n' "${ZONES[@]}" | sort -u | tr '\n' ' ')"
    printf '%s' "${z% }"
}

# node_machine_type <index> — node <index>'s machine type (config.sh NODE_MACHINE_TYPES: its
# BENCH_NODE_MACHINE_TYPES item, else MACHINE_TYPE).
node_machine_type() { printf '%s' "${NODE_MACHINE_TYPES[$1]}"; }

# machine_groups — the fleet's distinct machine types in index order (each at its first node),
# space-separated. Every knob unset: MACHINE_TYPE alone.
machine_groups() {
    local i g
    g="$(for i in "${!INSTANCE_NAMES[@]}"; do node_machine_type "${i}"; echo; done | awk '!seen[$0]++' | tr '\n' ' ')"
    printf '%s' "${g% }"
}

# type_nodes <machine-type> — the indices of the nodes of that type, space-separated, in order.
type_nodes() {
    local i n=""
    for i in "${!INSTANCE_NAMES[@]}"; do [ "$(node_machine_type "${i}")" != "$1" ] || n="${n} ${i}"; done
    printf '%s' "${n# }"
}

# lssd_nodes — the indices of the nodes whose machine type ends in -lssd, space-separated, in order.
lssd_nodes() {
    local i n=""
    for i in "${!INSTANCE_NAMES[@]}"; do
        case "$(node_machine_type "${i}")" in *-lssd) n="${n} ${i}" ;; esac
    done
    printf '%s' "${n# }"
}

# lssd_datadir_nodes — the indices of the nodes whose data directory step 3 puts on their first local SSD
# (config.sh NODE_DATADIR_LSSD=1: BENCH_NODE_DATADIR_LSSD=1 and a -lssd type), space-separated, in order;
# "" with the knob off.
lssd_datadir_nodes() {
    local i n=""
    for i in "${!INSTANCE_NAMES[@]}"; do [ "${NODE_DATADIR_LSSD[$i]}" != 1 ] || n="${n} ${i}"; done
    printf '%s' "${n# }"
}

# node_datadir <index> — node <index>'s data directory (the repo config.sh's VALIDATOR_DATA_DIR or
# OBSERVER_DATA_DIR by its role): the mount point of its local SSD. Passed to the step-3 and step-7
# builders: /etc/telcoin/.node-meta does not exist before keygen.
node_datadir() {
    case "${NODE_ROLES[$1]}" in
        observer) printf '%s' "${OBSERVER_DATA_DIR}" ;;
        *) printf '%s' "${VALIDATOR_DATA_DIR}" ;;
    esac
}

# data_disk_plan — step 2's half of instances[].data_disk (BENCH_NODE_DATADIR_LSSD=1), one JSON object
# {<inst>: <data_disk>}: {"class": "local-ssd"} for a node with NODE_DATADIR_LSSD=1 (step 3 merges in the rest
# from its LSSD_MOUNT line), and for every other node the boot disk the create asks for (the config):
# {"class": "boot", "type": NODE_DISK_TYPE, "size_gb": NODE_DISK_SIZE, "provisioned_iops": NODE_DISK_IOPS or
# null, "provisioned_throughput": NODE_DISK_THROUGHPUT or null}. Not under instances[].disks: the collector
# copies that list into its disk inventory.
data_disk_plan() {
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do printf '%s %s\n' "${INSTANCE_NAMES[$i]}" "${NODE_DATADIR_LSSD[$i]}"; done \
        | jq -R -s -c --arg t "${NODE_DISK_TYPE}" --arg s "${NODE_DISK_SIZE}" --arg io "${NODE_DISK_IOPS:-}" \
            --arg th "${NODE_DISK_THROUGHPUT:-}" '
            def num: if . == "" then null else tonumber end;
            [split("\n")[] | select(. != "") | split(" ")
             | {key: .[0], value: (if .[1] == "1" then {class: "local-ssd"}
                 else {class: "boot", type: $t, size_gb: ($s | tonumber), provisioned_iops: ($io | num),
                       provisioned_throughput: ($th | num)} end)}]
            | from_entries'
}

# create_plain — 0 when step 2 creates the fleet with one plain common/create-instances.sh call: every
# node is MACHINE_TYPE and it is not a -lssd type (every knob unset).
create_plain() {
    [ "$(machine_groups)" = "${MACHINE_TYPE}" ] || return 1
    case "${MACHINE_TYPE}" in *-lssd) return 1 ;; esac
}

# type_zones <machine-type> — the distinct zones of the nodes of that type, space-separated, sorted
# (one machine type: fleet_zones).
type_zones() {
    local i z
    z="$(for i in $(type_nodes "$1"); do echo "${ZONES[$i]}"; done | sort -u | tr '\n' ' ')"
    printf '%s' "${z% }"
}

# fleet_desc — the fleet's shape for step 0 and the plan. One machine type: "<n> x <type>, <boot
# disk>" (as before the per-node types). Several: "<n> nodes: <k> x <type>[ (data dir ...)], ...,
# <boot disk> boot disk", in machine_groups order; a -lssd type says where its nodes' data
# directory is (NODE_DATADIR_LSSD).
fleet_desc() {
    local groups t n i lssd out=""
    groups="$(machine_groups)"
    case "${groups}" in
        *" "*) ;;
        *) printf '%s x %s, %s' "${#INSTANCE_NAMES[@]}" "${groups}" "$(disk_desc)"; return 0 ;;
    esac
    for t in ${groups}; do
        n=0; lssd=0
        for i in $(type_nodes "${t}"); do n=$((n + 1)); [ "${NODE_DATADIR_LSSD[$i]}" != 1 ] || lssd=1; done
        out="${out}${n} x ${t}"
        case "${t}:${lssd}" in
            *-lssd:1) out="${out} (data dir on local SSD)" ;;
            *-lssd:0) out="${out} (data dir on the boot disk; its local SSD unused)" ;;
        esac
        out="${out}, "
    done
    printf '%s nodes: %s%s boot disk' "${#INSTANCE_NAMES[@]}" "${out}" "$(disk_desc)"
}

# node_type_checks — machine_type_check once per machine type, over the zones of that type's nodes.
node_type_checks() {
    local t knob
    for t in $(machine_groups); do
        knob=BENCH_NODE_MACHINE_TYPES
        [ "${t}" != "${MACHINE_TYPE}" ] || knob=BENCH_MACHINE_TYPE
        machine_type_check "${t}" "${knob}" "$(type_zones "${t}")"
    done
}

# validator_zones — the distinct zones of the validators (each validator's blaster runs in its zone).
validator_zones() {
    local i z
    z="$(for i in "${!ZONES[@]}"; do [ "${NODE_ROLES[$i]}" != "validator" ] || echo "${ZONES[$i]}"; done | sort -u | tr '\n' ' ')"
    printf '%s' "${z% }"
}

# fleet_regions — the distinct regions of the fleet, space-separated, sorted.
fleet_regions() {
    local z r; r="$(for z in "${ZONES[@]}"; do tn_region_from_zone "${z}"; echo; done | sort -u | tr '\n' ' ')"
    printf '%s' "${r% }"
}

# quota_regions — the fleet's regions and BENCH_OBS_ZONE's (the bench-obs VM), space-separated, sorted.
quota_regions() {
    local r; r="$( { fleet_regions | tr ' ' '\n'; echo; tn_region_from_zone "${BENCH_OBS_ZONE}"; echo; } | grep . | sort -u | tr '\n' ' ')"
    printf '%s' "${r% }"
}

# disk_type_check — a hyperdisk-* boot disk type must be offered in every zone the fleet uses;
# dies naming the zones that lack it. The query goes through bench_run, so a dry run (the plan)
# prints it and nothing else. Other disk types: no-op.
disk_type_check() {
    case "${NODE_DISK_TYPE}" in hyperdisk-*) ;; *) return 0 ;; esac
    local zlist out have z lacking=""
    zlist="$(fleet_zones)"
    echo "    ${NODE_DISK_TYPE} must be offered in every fleet zone (${zlist})"
    out="$(bench_run perl -e 'alarm shift; exec @ARGV' 120 gcloud compute disk-types list --project="${PROJECT_ID}" \
        --filter="name=${NODE_DISK_TYPE} AND zone:(${zlist})" --format='value(zone.basename())' </dev/null)" \
        || bench_die "gcloud compute disk-types list failed (or gave no answer within 120 s)"
    printf '%s\n' "${out}" | grep '^ ' || true    # bench_run's argv line (and its dry-run note)
    [ "${BENCH_APPLY}" = "1" ] || return 0
    have=" $(printf '%s\n' "${out}" | { grep -v '^ ' || true; } | tr '\n' ' ')"
    for z in ${zlist}; do
        case "${have}" in *" ${z} "*) ;; *) lacking="${lacking} ${z}" ;; esac
    done
    [ -z "${lacking}" ] || bench_die "${NODE_DISK_TYPE} is not offered in:${lacking} — pick another BENCH_NODE_DISK_TYPE"
    echo "    ✓ ${NODE_DISK_TYPE} offered in all fleet zones"
}

# machine_type_check <machine-type> <knob> "<zone...>" — the type must exist in every listed zone: a
# zone without it fails the create part-way through the fleet (or the blast, an hour after the fleet
# came up). One describe per zone, each under an alarm; every zone that fails is listed in a single
# die. A dry run (the plan) prints the query and calls nothing.
machine_type_check() {
    local t="$1" knob="$2" zones="$3" z rc out bad="" n=0
    echo "    ${t} must exist in every zone it is created in (${zones})"
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe ${t} --zone=<each zone> --project=${PROJECT_ID} --format='value(name)'"
        echo "      (dry run — not executed)"
        return 0
    fi
    for z in ${zones}; do
        rc=0; n=$((n + 1))
        out="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe "${t}" --zone="${z}" \
            --project="${PROJECT_ID}" --format='value(name)' </dev/null 2>&1)" || rc=$?
        [ "${rc}" -ne 0 ] || continue
        case "${rc}:${out}" in
            142:*) out="no answer within 60 s" ;;
            *"was not found"*) out="not offered in this zone" ;;
            *) out="describe failed (rc ${rc}): $(printf '%s' "${out}" | tr -s '\n' ' ' | cut -c1-200)" ;;
        esac
        bad="${bad}
     ${z}: ${out}"
    done
    [ -z "${bad}" ] || bench_die "${t} cannot be created in every zone it needs — change ZONES (benchmark/config.sh) or ${knob}:${bad}"
    echo "    ✓ ${t} offered in all ${n} zones"
}

# boot_image_check — step 0's boot image gate, before anything is created: `gcloud compute images
# describe` of the pinned IMAGE (benchmark/config.sh BENCH_NODE_BOOT_IMAGE, projects/<p>/global/images/<name>,
# never a family). A missing image, a status other than READY or a deprecation state OBSOLETE or DELETED
# is refused; DEPRECATED is a warning (the image still boots the same bits). BOOT_IMAGE_JSON is then the
# manifest.node_boot_image record {ref, name, status, deprecation_state} (null when not deprecated),
# written by step 0 once the manifest exists. The dry run prints the call and makes none.
BOOT_IMAGE_JSON=""
boot_image_check() {
    local p n out rc=0 st dep nm
    p="${IMAGE#projects/}"; p="${p%%/*}"; n="${IMAGE##*/}"
    echo "    boot image ${IMAGE} must exist and be READY (OBSOLETE or DELETED refused, DEPRECATED warned)"
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "    + gcloud compute images describe ${n} --project=${p} --format=json"
        echo "      (dry run — not executed)"
        return 0
    fi
    out="$(gcloud compute images describe "${n}" --project="${p}" --format=json </dev/null 2>&1)" || rc=$?
    [ "${rc}" -eq 0 ] || bench_die "boot image ${IMAGE} cannot be described (rc ${rc}): $(printf '%s' "${out}" | tr -s '\n' ' ' | cut -c1-200) — nothing was created; pin an image that exists (BENCH_NODE_BOOT_IMAGE)"
    BOOT_IMAGE_JSON="$(printf '%s' "${out}" | jq -c --arg ref "${IMAGE}" 'select(type == "object")
        | {ref: $ref, name: (.name // null), status: (.status // null), deprecation_state: (.deprecated.state // null)}' 2>/dev/null)" || BOOT_IMAGE_JSON=""
    [ -n "${BOOT_IMAGE_JSON}" ] || bench_die "boot image ${IMAGE}: images describe gave no JSON object — nothing was created"
    nm="$(printf '%s' "${BOOT_IMAGE_JSON}" | jq -r '.name // ""')"
    st="$(printf '%s' "${BOOT_IMAGE_JSON}" | jq -r '.status // ""')"
    dep="$(printf '%s' "${BOOT_IMAGE_JSON}" | jq -r '.deprecation_state // ""')"
    [ "${nm}" = "${n}" ] || bench_die "boot image ${IMAGE}: images describe answered for '${nm}', not ${n} — nothing was created"
    case "${dep}" in
        OBSOLETE|DELETED) bench_die "boot image ${IMAGE} is ${dep} — a fleet cannot boot it; nothing was created (pin another: BENCH_NODE_BOOT_IMAGE)" ;;
        DEPRECATED) bench_warn "boot image ${IMAGE} is DEPRECATED: it still boots, but its replacement is out (manifest.node_boot_image.deprecation_state)" ;;
    esac
    [ "${st}" = READY ] || bench_die "boot image ${IMAGE} has status '${st:-none}', not READY — nothing was created"
    echo "    ✓ boot image ${n} (${p}): READY${dep:+, deprecation state ${dep}}"
}

# zone_fallback_zones [<machine-type>] — the distinct BENCH_ZONE_FALLBACKS zones (only the items of
# that type's nodes, when given), space-separated, sorted.
zone_fallback_zones() {
    local item z
    z="$(for item in ${BENCH_ZONE_FALLBACKS:-}; do
            [ -z "${1:-}" ] || [ "${NODE_MACHINE_TYPES[${item%%:*}]}" = "$1" ] || continue
            printf '%s\n' "${item#*:}" | tr ',' '\n'
        done | sort -u | tr '\n' ' ')"
    printf '%s' "${z% }"
}

# zone_fallback_check — every BENCH_ZONE_FALLBACKS zone should offer the machine type of the node it
# is for (one check per machine type, over its nodes' fallback zones): a fallback is tried only after a
# stockout, in the middle of step 2, so a zone that cannot host the type is reported now.
# One alarmed describe per zone; each failure is a warning (⚠), never a stop — the run needs its planned
# zones, not these. A dry run (the plan) prints the query and calls nothing.
zone_fallback_check() {
    local t zones z rc out bad n
    if [ -z "$(zone_fallback_zones)" ]; then
        echo "    no zone fallbacks (BENCH_ZONE_FALLBACKS is empty): a stockout in step 2 stops the run"
        return 0
    fi
    for t in $(printf '%s\n' "${NODE_MACHINE_TYPES[@]}" | awk '!seen[$0]++'); do
        zones="$(zone_fallback_zones "${t}")"
        [ -n "${zones}" ] || continue
        echo "    zone fallbacks ${BENCH_ZONE_FALLBACKS}: ${t} should exist in ${zones} (warning only)"
        if [ "${BENCH_APPLY}" != "1" ]; then
            echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe ${t} --zone=<each fallback zone> --project=${PROJECT_ID} --format='value(name)'"
            echo "      (dry run — not executed)"
            continue
        fi
        bad=0; n=0
        for z in ${zones}; do
            rc=0; n=$((n + 1))
            out="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe "${t}" --zone="${z}" \
                --project="${PROJECT_ID}" --format='value(name)' </dev/null 2>&1)" || rc=$?
            [ "${rc}" -ne 0 ] || continue
            case "${rc}:${out}" in
                142:*) out="no answer within 60 s" ;;
                *"was not found"*) out="not offered in this zone" ;;
                *) out="describe failed (rc ${rc}): $(printf '%s' "${out}" | tr -s '\n' ' ' | cut -c1-200)" ;;
            esac
            bad=$((bad + 1))
            bench_warn "zone fallback ${z}: ${t} ${out} — a stockout that falls back there would fail again; fix BENCH_ZONE_FALLBACKS"
        done
        [ "${bad}" -gt 0 ] || echo "    ✓ ${t} offered in all ${n} fallback zones"
    done
}

# machine_vcpus <machine-type> <zone> — its vCPU count: from the name when the name carries it
# (<family>-custom-<vcpus>-<mb>, <family>-<class>-<vcpus>, either with a trailing -lssd: the local-SSD
# shape of the same vCPU count), else (--yes only) from an alarmed describe in <zone>; "" when unknown.
machine_vcpus() {
    local n t="${1%-lssd}"
    case "${t}" in *-custom-*) n="${t#*-custom-}"; n="${n%%-*}" ;; *) n="${t##*-}" ;; esac
    case "${n}" in ''|*[!0-9]*) n="" ;; esac
    if [ -z "${n}" ] && [ "${BENCH_APPLY}" = "1" ]; then
        n="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe "$1" --zone="$2" \
            --project="${PROJECT_ID}" --format='value(guestCpus)' </dev/null 2>/dev/null || true)"
    fi
    printf '%s' "${n}"
}

# lssd_gb <machine-type> <zone> — the GB of local SSD a -lssd type brings with it: its
# bundledLocalSsds.partitionCount x 375, from an alarmed describe in <zone> (--yes only); "" when unknown.
lssd_gb() {
    local n=""
    if [ "${BENCH_APPLY}" = "1" ]; then
        n="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe "$1" --zone="$2" \
            --project="${PROJECT_ID}" --format='value(bundledLocalSsds.partitionCount)' </dev/null 2>/dev/null || true)"
    fi
    case "${n}" in ''|*[!0-9]*) n="" ;; esac
    printf '%s' "${n:+$(( n * 375 ))}"
}

# region_needs <region> — "<quota metric> <need>" lines: what the fleet's nodes in <region> and their
# blasters (one per validator, in its zone, on the first BENCH_BLASTER_MACHINE_TYPES type) take from
# the region's quotas. vCPUs count against each type's family metric (bench_cpu_quota_metric), one line
# per node (its own machine type) and one sum when nodes and blasters share a metric; every node and
# blaster holds one external address; the blasters'
# pd-balanced boot disks count against SSD_TOTAL_GB; the node disks against HDB_TOTAL_{GB,IOPS,
# THROUGHPUT} (hyperdisk-balanced; the IOPS/throughput only when provisioned), SSD_TOTAL_GB (pd-ssd,
# pd-balanced) or DISKS_TOTAL_GB (pd-standard); a -lssd node's bundled local SSDs against
# LOCAL_SSD_TOTAL_GB (lssd_gb). The bench-obs VM (BENCH_OBS_MACHINE_TYPE in
# BENCH_OBS_ZONE) counts in its own region: its vCPUs, one external address, its pd-balanced boot disk
# (obs_boot_gb: bench_obs_create's fixed 20 GB) and BENCH_OBS_DISK_GB pd-ssd data disk against
# SSD_TOTAL_GB. A need is "?" when a vCPU count (or a local SSD size) is unknown.
region_needs() {
    local region="$1" i t z="" nodes=0 vals=0 bt nc bc oc obs_boot_gb=20 cpu="" lssd="" g
    for i in "${!ZONES[@]}"; do
        [ "$(tn_region_from_zone "${ZONES[$i]}")" = "${region}" ] || continue
        z="${ZONES[$i]}"; nodes=$((nodes + 1))
        [ "${NODE_ROLES[$i]}" != "validator" ] || vals=$((vals + 1))
        t="${NODE_MACHINE_TYPES[$i]}"
        nc="$(machine_vcpus "${t}" "${z}")"
        cpu="${cpu}$(bench_cpu_quota_metric "${t}") ${nc:-?}
"
        case "${t}" in
            *-lssd) g="$(lssd_gb "${t}" "${z}")"; lssd="${lssd}LOCAL_SSD_TOTAL_GB ${g:-?}
" ;;
        esac
    done
    bt="${BENCH_BLASTER_MACHINE_TYPES%% *}"
    bc="$(machine_vcpus "${bt}" "${z}")"; bc="${bc:+$(( vals * bc ))}"
    {
        if [ "${nodes}" -gt 0 ]; then   # a region with bench-obs alone (quota_regions) has no node lines
            printf '%s' "${cpu}"
            [ "${vals}" -eq 0 ] || echo "$(bench_cpu_quota_metric "${bt}") ${bc:-?}"
            echo "IN_USE_ADDRESSES $(( nodes + vals ))"
            case "${NODE_DISK_TYPE}" in
                hyperdisk-balanced)
                    echo "HDB_TOTAL_GB $(( nodes * NODE_DISK_SIZE ))"
                    [ -z "${NODE_DISK_IOPS}" ] || echo "HDB_TOTAL_IOPS $(( nodes * NODE_DISK_IOPS ))"
                    [ -z "${NODE_DISK_THROUGHPUT}" ] || echo "HDB_TOTAL_THROUGHPUT $(( nodes * NODE_DISK_THROUGHPUT ))" ;;
                pd-ssd|pd-balanced) echo "SSD_TOTAL_GB $(( nodes * NODE_DISK_SIZE ))" ;;
                pd-standard) echo "DISKS_TOTAL_GB $(( nodes * NODE_DISK_SIZE ))" ;;
            esac
            printf '%s' "${lssd}"
            [ "${vals}" -eq 0 ] || echo "SSD_TOTAL_GB $(( vals * BENCH_BLASTER_BOOT_DISK_GB ))"
        fi
        if [ "$(tn_region_from_zone "${BENCH_OBS_ZONE}")" = "${region}" ]; then
            oc="$(machine_vcpus "${BENCH_OBS_MACHINE_TYPE}" "${BENCH_OBS_ZONE}")"
            echo "$(bench_cpu_quota_metric "${BENCH_OBS_MACHINE_TYPE}") ${oc:-?}"
            echo "IN_USE_ADDRESSES 1"
            echo "SSD_TOTAL_GB $(( obs_boot_gb + BENCH_OBS_DISK_GB ))"
        fi
    } | awk '{ if (!($1 in n)) { o[++k] = $1; n[$1] = 0 } if ($2 == "?") u[$1] = 1; else n[$1] += $2 }
             END { for (i = 1; i <= k; i++) print o[i], ((o[i] in u) ? "?" : n[o[i]]) }'
}

# hdb_headroom <metric> <region> <quota-info json> <disks json> — a HDB_TOTAL_* quota's headroom in
# <region>: the value in force (`gcloud beta quotas info describe` JSON: the region's own dimension,
# else the default that applies to it) less what the region's hyperdisk-balanced disks already hold.
# "unlimited" for -1; "" when the region has no value.
hdb_headroom() {
    local f limit used
    case "$1" in
        HDB_TOTAL_GB) f=sizeGb ;;
        HDB_TOTAL_IOPS) f=provisionedIops ;;
        *) f=provisionedThroughput ;;
    esac
    limit="$(printf '%s' "$3" | jq -r --arg r "$2" '
        ([.dimensionsInfos[]? | select(.dimensions.region? == $r)]
         + [.dimensionsInfos[]? | select((.dimensions.region? // null) == null and ((.applicableLocations // []) | index($r)))])
        | .[0].details.value // empty' 2>/dev/null || true)"
    case "${limit}" in
        -1) echo unlimited; return 0 ;;
        ''|*[!0-9]*) return 0 ;;
    esac
    used="$(printf '%s' "$4" | jq -r --arg r "$2" --arg f "${f}" '
        [.[]? | select((.type // "") | endswith("/hyperdisk-balanced"))
              | select(((.zone // .region // "") | split("/") | last | sub("-[a-z]$"; "")) == $r)
              | (.[$f] // "0" | tonumber)] | add // 0 | floor' 2>/dev/null || true)"
    echo $(( limit - ${used:-0} ))
}

# quota_check — per region, the fleet's need (region_needs) against the headroom (limit - usage).
# CPU family metrics, IN_USE_ADDRESSES and SSD_TOTAL_GB/DISKS_TOTAL_GB come from `gcloud compute
# regions describe`, which lists no hyperdisk quota: the HDB_TOTAL_* limits come from the Cloud
# Quotas API (HDB-TOTAL-{GB,IOPS,THROUGHPUT}-per-project-region) and their usage from the disks
# list. A headroom of 2^53 or more (LOCAL_SSD_TOTAL_GB's limit is 9.2e18, which jq prints as 9.2e+18, no
# integer for the shell) is "unlimited".
# Every shortfall is listed in one die; a quota that cannot be read is a warning. Every gcloud
# call is under an alarm. A dry run (the plan) prints the needs and the queries and calls nothing.
# The regions are the fleet's plus bench-obs's (quota_regions).
quota_check() {
    local regions r m need have why json qgb="" qiops="" qtput="" disks="[]" q qj ok short=""
    regions="$(quota_regions)"
    echo "    quota headroom (limit - usage) in each region must cover its nodes plus one blaster per validator (and ${BENCH_OBS_INSTANCE} in $(tn_region_from_zone "${BENCH_OBS_ZONE}")):"
    for r in ${regions}; do
        echo "      ${r}: $(region_needs "${r}" | awk '{ printf "%s%s %s", (NR > 1 ? ", " : ""), $1, $2 }')"
    done
    if [ "${BENCH_APPLY}" != "1" ]; then
        echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute regions describe <each region> --project=${PROJECT_ID} --format=json"
        case " ${NODE_MACHINE_TYPES[*]} " in
            *"-lssd "*) echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud compute machine-types describe <each -lssd node's type> --zone=<its zone> --project=${PROJECT_ID} --format='value(bundledLocalSsds.partitionCount)'   (x 375 GB: LOCAL_SSD_TOTAL_GB)" ;;
        esac
        if [ "${NODE_DISK_TYPE}" = "hyperdisk-balanced" ]; then
            echo "    + perl -e 'alarm shift; exec @ARGV' 60 gcloud beta quotas info describe HDB-TOTAL-<GB|IOPS|THROUGHPUT>-per-project-region --service=compute.googleapis.com --project=${PROJECT_ID} --format=json"
            echo "    + perl -e 'alarm shift; exec @ARGV' 120 gcloud compute disks list --project=${PROJECT_ID} --format=json"
        fi
        echo "      (dry run — not executed)"
        return 0
    fi
    if [ "${NODE_DISK_TYPE}" = "hyperdisk-balanced" ]; then
        for q in GB IOPS THROUGHPUT; do
            qj="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud beta quotas info describe "HDB-TOTAL-${q}-per-project-region" \
                --service=compute.googleapis.com --project="${PROJECT_ID}" --format=json </dev/null 2>/dev/null)" || qj=""
            case "${q}" in GB) qgb="${qj}" ;; IOPS) qiops="${qj}" ;; *) qtput="${qj}" ;; esac
        done
        disks="$(perl -e 'alarm shift; exec @ARGV' 120 gcloud compute disks list --project="${PROJECT_ID}" \
            --format=json </dev/null 2>/dev/null)" \
            || { bench_warn "gcloud compute disks list failed — existing hyperdisk usage counted as 0"; disks="[]"; }
    fi
    for r in ${regions}; do
        json="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute regions describe "${r}" --project="${PROJECT_ID}" \
            --format=json </dev/null 2>/dev/null)" \
            || bench_die "gcloud compute regions describe ${r} failed (or gave no answer within 60 s)"
        ok=""
        while read -r m need; do
            [ -n "${m}" ] || continue
            case "${m}" in
                HDB_TOTAL_GB) have="$(hdb_headroom "${m}" "${r}" "${qgb}" "${disks}")" ;;
                HDB_TOTAL_IOPS) have="$(hdb_headroom "${m}" "${r}" "${qiops}" "${disks}")" ;;
                HDB_TOTAL_THROUGHPUT) have="$(hdb_headroom "${m}" "${r}" "${qtput}" "${disks}")" ;;
                *) have="$(printf '%s' "${json}" | jq -r --arg q "${m}" \
                       '[.quotas[]? | select(.metric == $q) | (.limit - .usage) | floor
                         | if . >= 9007199254740992 then "unlimited" else . end][0] // empty' 2>/dev/null || true)" ;;
            esac
            why="$(bench_cpu_quota_unlisted "${m}")" || why=""
            if [ -n "${why}" ] && [ -z "${have}" ]; then
                bench_warn "${r}: ${m} not checked (need ${need}): ${why}"
            elif [ -z "${have}" ] || [ "${need}" = "?" ]; then
                bench_warn "${r}: ${m} not checked (need ${need}, headroom ${have:-not readable})"
            elif [ "${have}" = "unlimited" ] || [ "${have}" -ge "${need}" ]; then
                ok="${ok}, ${m} ${need}/${have}"
            else
                short="${short}
     $(printf '%-24s %-22s %10s %10s' "${r}" "${m}" "${need}" "${have}")"
            fi
        done <<EOF
$(region_needs "${r}")
EOF
        [ -z "${ok}" ] || echo "    ✓ ${r} need/headroom: ${ok#, }"
    done
    [ -z "${short}" ] || bench_die "quota shortfalls — nothing was created:
     $(printf '%-24s %-22s %10s %10s' region metric need headroom)${short}
   Raise the quota (console: IAM & Admin > Quotas; or gcloud beta quotas preferences create), or move the zone (ZONES in benchmark/config.sh)."
}

# step7_local_problems — what would stop step 7 on this host, one line each (nothing printed: none):
# python3 without PyYAML (devnet-network-config.sh renders and checks network-config with it, and
# devnet-finalize.sh's readiness gate parses it), and a TN_NODE_SCRIPTS_REF that is not a full
# lowercase 40-hex sha (as devnet-deploy.sh refuses it: the ref goes into every node's instance
# metadata and a root git command there, and the pre-start config compares the node's checkout with it).
# With BENCH_ARM_FILE: the arm must parse (bench_arm_state_load) and no BENCH_NODE_PARAM_OVERRIDES item
# may set a node switch beside it (bench_arm_override_conflicts).
step7_local_problems() {
    python3 -c 'import yaml' >/dev/null 2>&1 \
        || echo "python3 has no PyYAML (devnet-network-config.sh and devnet-finalize.sh parse YAML with it): sudo apt-get install python3-yaml, or python3 -m pip install --user pyyaml"
    case "${TN_NODE_SCRIPTS_REF:-}" in
        *[!0-9a-f]*|'') echo "TN_NODE_SCRIPTS_REF must be a full lowercase 40-hex commit sha (got '${TN_NODE_SCRIPTS_REF:-}')" ;;
        *) [ "${#TN_NODE_SCRIPTS_REF}" -eq 40 ] || echo "TN_NODE_SCRIPTS_REF must be exactly 40 hex characters (got ${#TN_NODE_SCRIPTS_REF})" ;;
    esac
    if [ -n "${BENCH_ARM_FILE:-}" ]; then
        local e
        if e="$(bench_arm_state_load 2>&1)"; then
            bench_arm_override_conflicts
        else
            printf '%s\n' "${e}" | sed 's/^❌ //' | head -n 1
        fi
    fi
}

# run_storage_engine — the node image's storage engine (tn-lmdb|mdbx): this invocation's gate probe, else the
# manifest's storage_engine (a resume); "" when neither knows it.
run_storage_engine() {
    if [ -n "${BENCH_NODE_STORAGE_ENGINE:-}" ]; then printf '%s' "${BENCH_NODE_STORAGE_ENGINE}"; return 0; fi
    jq -r '.storage_engine // empty' "$(bench_manifest)" 2>/dev/null || true
}

# mdbx_knob_problems — one line per MDBX-only knob this run sets while its node image runs tn-lmdb (nothing
# printed: none, or the engine is not tn-lmdb). Step 0 refuses it before anything exists, instead of a node
# failing later: evict-mdbx targets <datadir>/db/mdbx.dat, which a tn-lmdb datadir does not have.
# BENCH_NODE_DB_SYNC_MODE is not one: upstream main maps --db.sync-mode durable|safe-no-sync onto tn-lmdb,
# so the knob works on either engine and the manifest records db_sync_mode as before.
mdbx_knob_problems() {
    [ "$(run_storage_engine)" = tn-lmdb ] || return 0
    [ "${BENCH_NODE_EVICT_MDBX:-0}" = 0 ] \
        || echo "BENCH_NODE_EVICT_MDBX=${BENCH_NODE_EVICT_MDBX} evicts <datadir>/db/mdbx.dat and the node image runs tn-lmdb (storage_engine; its file is db/tn-lmdb.dat): unset it"
    return 0
}

# obs_or_die <resume hint> <fn> [args] — an obs-lib.sh function (bench-obs create / ensure / require) in a
# subshell, with errexit in force inside it (it is not the left side of `||`, where bash switches errexit
# off). When it fails (its own ❌ line is above) this shell dies with <resume hint>, so the EXIT trap
# prints BENCH_DEPLOY_RESULT on fd 5 as on any other stop. No fd is closed here: the forwards it starts
# are born with fd 5/6 closed (bench-lib _bench_tunnel_start's nohup). What the function exports stays
# in the subshell; the manifest carries what later steps need (bench_obs_urls reads manifest.obs.internal_ip).
obs_or_die() {
    local hint="$1" rc
    shift
    set +e
    ( set -e; "$@" )
    rc=$?
    set -e
    [ "${rc}" -eq 0 ] || bench_die "${hint}"
}

# ================================ steps ==============================================
step_0() {
    echo ">>> Step 0: preflight"
    echo "    fleet: $(fleet_desc), node image ${DOCKER_IMAGE} (git $(run_expect sha), forks $(run_expect forks); image probed at gate)"
    bench_require_tools gcloud cast jq python3 curl docker git openssl || bench_die "missing tools"
    [ "${WITH_CONTRACTS}" -eq 0 ] || bench_require_tools forge || bench_die "forge needed for --with-contracts"
    local p7; p7="$(step7_local_problems)"
    [ -z "${p7}" ] || bench_die "${p7}"
    echo "    ✓ python3 PyYAML, TN_NODE_SCRIPTS_REF ${TN_NODE_SCRIPTS_REF} (step 7)"
    local se mk; se="$(run_storage_engine)"; mk="$(mdbx_knob_problems)"
    [ -z "${mk}" ] || bench_die "${mk}"
    [ -z "${se}" ] || echo "    ✓ storage engine ${se} (node image '--version')$([ "${se}" != tn-lmdb ] || printf ', BENCH_NODE_EVICT_MDBX unset')"
    local acct; acct="$(gcloud config get-value account 2>/dev/null || true)"
    gcloud auth print-access-token >/dev/null || bench_die "gcloud auth failed — gcloud auth login"
    echo "    ✓ gcloud auth (${acct:-unknown account})"
    local left; left="$(bench_leftovers)"
    if [ -n "${left}" ]; then
        printf '%s\n' "${left}" | sed 's/^/    ✗ exists: /' >&2
        bench_die "benchmark resources from an earlier run still exist — tear them down first:
     benchmark/benchmark-teardown.sh            # dry run, then add --yes
   (or resume the run that owns them with --from N instead of starting at step 0)"
    fi
    echo "    ✓ no bench-* / benchmark=1 instance, disk, firewall rule or bucket exists"
    local accounts="${GENESIS_WORKSPACE}/testnet_accounts.yaml"
    grep -qi "${BENCH_TXGEN_MASTER_ADDRESS}" "${accounts}" || bench_die "${accounts} does not fund the bench txgen master ${BENCH_TXGEN_MASTER_ADDRESS}"
    ! grep -qi "${DEVNET_TXGEN_MASTER}" "${accounts}" || bench_die "${accounts} still funds the DEVNET txgen master"
    echo "    ✓ ${accounts} funds ${BENCH_TXGEN_MASTER_ADDRESS}"
    if [ -d "${BENCH_DIR}/genesis" ] && [ -n "$(ls -A "${BENCH_DIR}/genesis" 2>/dev/null)" ]; then
        bench_die "${BENCH_DIR}/genesis is not empty (a previous run's keys?) — benchmark-teardown.sh moves it into results/<run>/"
    fi
    echo "    ✓ benchmark/genesis empty"
    if [ ! -s "${TN_BLS_PASSPHRASE_FILE}" ]; then
        echo "    creating bench BLS passphrase ${TN_BLS_PASSPHRASE_FILE} (gitignored, mode 600, never printed)"
        ( umask 077; mkdir -p "$(dirname "${TN_BLS_PASSPHRASE_FILE}")"; openssl rand -hex 24 | tr -d '\n' > "${TN_BLS_PASSPHRASE_FILE}" )
    fi
    echo "    ✓ bench BLS passphrase present"
    local foreign
    foreign="$(gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json | jq -r \
        --argjson ours "$(printf '%s\n' "${BENCH_FIREWALL_RULES[@]}" | jq -R . | jq -s .)" \
        '.[] | select((.targetTags // []) | index("bench-node")) | select(.name as $n | $ours | index($n) | not) | .name')"
    [ -z "${foreign}" ] || bench_die "non-bench firewall rules target bench-node: ${foreign}"
    echo "    ✓ no non-bench firewall rule targets bench-node"
    # No obs-devnet read: the bench ships metrics only, to its own bench-obs VM (step 2 creates it, step 8
    # brings it up); a bench-obs left by an earlier run is a leftover above, like any bench-*.
    node_type_checks
    machine_type_check "${BENCH_BLASTER_MACHINE_TYPES%% *}" BENCH_BLASTER_MACHINE_TYPES "$(validator_zones)"
    machine_type_check "${BENCH_OBS_MACHINE_TYPE}" BENCH_OBS_MACHINE_TYPE "${BENCH_OBS_ZONE}"
    zone_fallback_check
    disk_type_check
    quota_check
    boot_image_check
    mkdir -p "${BENCH_RESULTS_DIR}"
    [ -f "${BENCH_RESULTS_DIR}/pre-instances.json" ] \
        || gcloud compute instances list --project="${PROJECT_ID}" --format=json > "${BENCH_RESULTS_DIR}/pre-instances.json"
    [ -f "${BENCH_RESULTS_DIR}/pre-firewall.json" ] \
        || gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json > "${BENCH_RESULTS_DIR}/pre-firewall.json"
    echo "    ✓ pre-snapshots in ${BENCH_RESULTS_DIR}/pre-{instances,firewall}.json"
    bench_manifest_init
    bench_manifest_jq --argjson b "${BOOT_IMAGE_JSON}" '.node_boot_image = $b' \
        || bench_die "could not record node_boot_image in $(bench_manifest)"
    echo "    ✓ manifest.node_boot_image: ${BOOT_IMAGE_JSON}"
}

step_1() {
    bench_require_txgen_image
    local digest tag="${BENCH_TXGEN_IMAGE##*:}" sha
    sha="${tag#blast-v2-}"
    echo ">>> Step 1: txgen image ${BENCH_TXGEN_IMAGE}"
    digest="$(bench_txgen_image_digest)"
    if [ -z "${digest}" ]; then
        # Build only what the tag claims: HEAD of a clean generator checkout.
        [ -z "${BENCH_TXGEN_IMAGE_ERROR}" ] || bench_die "cannot build: ${BENCH_TXGEN_IMAGE_ERROR}"
        [ "$(git -C "${BENCH_TXGEN_REPO}" rev-parse --short=7 HEAD)" = "${sha}" ] \
            || bench_die "tag ${tag} is not HEAD of ${BENCH_TXGEN_REPO} — check out ${sha} or unset BENCH_TXGEN_SHA/BENCH_TXGEN_IMAGE"
        [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] || bench_die "missing ${BENCH_TXGEN_CLOUDBUILD}"
        echo "    not in the registry — building it with Cloud Build (synchronous)"
        bench_run gcloud builds submit --project="${PROJECT_ID}" --config="${BENCH_TXGEN_CLOUDBUILD}" \
            --substitutions="_IMAGE=${BENCH_TXGEN_IMAGE%:*},_TAG=${tag},_GIT_SHA=${sha}" "${BENCH_TXGEN_REPO}"
        digest="$(bench_txgen_image_digest)"
        [ -n "${digest}" ] || bench_die "Cloud Build finished but ${BENCH_TXGEN_IMAGE} is still not in the registry"
    fi
    echo "    ✓ ${BENCH_TXGEN_IMAGE} = ${digest}"
    bench_txgen_cli_probe
    bench_manifest_jq --arg i "${BENCH_TXGEN_IMAGE}" --arg d "${digest}" --arg s "${sha}" \
        '.txgen_image = $i | .txgen_image_digest = $d | .txgen_git_sha = $s'
}

# create_failed_names <run log> — the instances common/create-instances.sh reported failed ("❌ Error:
# Failed to create instance <name> - See <file> for details"), one per line, first report order.
create_failed_names() {
    sed -n 's/^.*Failed to create instance \([^ ]*\) - See .* for details.*$/\1/p' "$1" | awk '!seen[$0]++'
}

# create_fail_log <run log> <instance> — the file that holds <instance>'s own create failure: the
# per-instance log named on its "Failed to create instance" line. create-instances.sh runs in REPO_ROOT
# (cd) and names it ./logs/..., so a relative path is REPO_ROOT's. rc 1 when there is no such line or
# the file cannot be read: a node is never judged on the round log, where another node's stockout text
# would pass for its own.
create_fail_log() {
    local f
    f="$(sed -n "s/^.*Failed to create instance $2 - See \(.*\) for details.*\$/\1/p" "$1" | tail -1)"
    case "${f}" in
        '') return 1 ;;
        /*) ;;
        *) f="${REPO_ROOT}/${f#./}" ;;
    esac
    [ -r "${f}" ] || return 1
    printf '%s' "${f}"
}

# zone_fallback_next <index> — the first BENCH_ZONE_FALLBACKS zone of node <index> it has not been in
# (its zone now, or a zone_fallbacks[] from/to of it in the manifest); "" when none is left.
zone_fallback_next() {
    local idx="$1" item z tried
    tried=" ${ZONES[$idx]} $(jq -r --arg i "${INSTANCE_NAMES[$idx]}" \
        '[(.zone_fallbacks // [])[] | objects | select(.inst == $i) | .from, .to] | join(" ")' "$(bench_manifest)" 2>/dev/null || true) "
    for item in ${BENCH_ZONE_FALLBACKS:-}; do
        [ "${item%%:*}" = "${idx}" ] || continue
        for z in $(printf '%s' "${item#*:}" | tr ',' ' '); do
            case "${tried}" in *" ${z} "*) ;; *) printf '%s' "${z}"; return 0 ;; esac
        done
    done
    return 0
}

# zone_fallback_record <index> <from> <to> — node <index> moves to zone <to> after a stockout in <from>
# (of the node's own machine type): ZONES here, manifest zone_fallbacks[] {inst, from, to, reason: "stockout",
# ts} and a note (the run's latency figures for that node are not the planned zone's).
zone_fallback_record() {
    local inst="${INSTANCE_NAMES[$1]}" ts t
    ts="$(bench_now_iso)"
    t="$(node_machine_type "$1")"
    ZONES[$1]="$3"
    bench_warn "${inst}: ${2} is out of ${t} (stockout) — it moves to ${3} (BENCH_ZONE_FALLBACKS)"
    bench_manifest_jq --arg i "${inst}" --arg f "$2" --arg t "$3" --arg ts "${ts}" \
        '.zone_fallbacks = ((.zone_fallbacks // []) + [{inst: $i, from: $f, to: $t, reason: "stockout", ts: $ts}])' \
        || bench_die "could not record zone_fallbacks in $(bench_manifest)"
    bench_manifest_note "zone fallback: ${inst} runs in ${3}, not ${2} (${t} stockout, ${ts}); its latency is that zone's, a comparability caveat" \
        || bench_die "could not add a note to $(bench_manifest)"
}

# zones_env_write — ${BENCH_RESULTS_DIR}/zones.env from ZONES (replaced atomically): the
# BENCH_ZONES_USED line benchmark/config.sh reads into ZONES for every later script of the run.
# Written after a stockout fallback, and before the first create whenever BENCH_NODE_ZONES is set: a later
# script run without that knob in its environment (the teardown) still finds a moved node in its zone.
zones_env_write() {
    local f="${BENCH_RESULTS_DIR}/zones.env" tmp why="stockout fallback"
    [ -z "${BENCH_NODE_ZONES:-}" ] || why="BENCH_NODE_ZONES, stockout fallback"
    tmp="$(mktemp "${f}.XXXXXX")" || bench_die "cannot write ${f}"
    if printf '# benchmark-deploy.sh step 2 (%s): the zone of each INSTANCE_NAMES entry, in order\nBENCH_ZONES_USED=%s\n' \
            "${why}" "${ZONES[*]}" > "${tmp}" && mv -f "${tmp}" "${f}"; then
        echo "    ✓ ${f}: BENCH_ZONES_USED=${ZONES[*]}"
    else
        rm -f "${tmp}"
        bench_die "cannot write ${f}"
    fi
}

# zones_used_record — manifest zones_used = {instance: the zone it was created in}.
zones_used_record() {
    local i z
    z="$(for i in "${!INSTANCE_NAMES[@]}"; do printf '%s\t%s\n' "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}"; done \
        | jq -R -s -c 'split("\n") | map(select(length > 0) | split("\t") | {key: .[0], value: .[1]}) | from_entries')" \
        || bench_die "could not list the fleet's zones"
    bench_manifest_jq --argjson z "${z}" '.zones_used = $z' || bench_die "could not record zones_used in $(bench_manifest)"
}

# zone_overrides_record — with BENCH_NODE_ZONES, once per run (while the manifest has no zone_overrides):
# manifest zone_overrides[] {inst, from, to, reason: "BENCH_NODE_ZONES", ts} and a note for every node the
# knob moves. <from> is the node's zone without the knob: config.sh loaded again in a fresh bash with
# BENCH_NODE_ZONES empty. That load reads zones.env too, so a zone zones.env already holds (it wins over the
# knob in config.sh) is no move. Runs before step 2 first writes zones.env.
zone_overrides_record() {
    local planned item i from ts recs="[]" notes="" note
    [ -n "${BENCH_NODE_ZONES:-}" ] || return 0
    [ "$(jq -r 'has("zone_overrides")' "$(bench_manifest)" 2>/dev/null || true)" != true ] || return 0
    planned="$(BENCH_NODE_ZONES="" BENCH_CREATE_MACHINE_TYPE="" bash -c '. "$1" >/dev/null && printf "%s\n" "${ZONES[@]}"' \
        benchmark-deploy.sh "${CONFIG_FILE}")" || bench_die "cannot load ${CONFIG_FILE} without BENCH_NODE_ZONES (the zones it moves nodes from)"
    ts="$(bench_now_iso)"
    for item in ${BENCH_NODE_ZONES}; do
        i="${item%%:*}"
        from="$(printf '%s\n' "${planned}" | sed -n "$((i + 1))p")"
        [ -n "${from}" ] && [ "${from}" != "${ZONES[$i]}" ] || continue
        recs="$(printf '%s' "${recs}" | jq -c --arg i "${INSTANCE_NAMES[$i]}" --arg f "${from}" --arg t "${ZONES[$i]}" --arg ts "${ts}" \
            '. + [{inst: $i, from: $f, to: $t, reason: "BENCH_NODE_ZONES", ts: $ts}]')" || bench_die "could not build zone_overrides"
        note="zone override: ${INSTANCE_NAMES[$i]} runs in ${ZONES[$i]}, not ${from} (BENCH_NODE_ZONES); its latency is that zone's, a comparability caveat"
        notes="${notes}${note}
"
        echo "    ${note}"
    done
    # zone_overrides first: it marks the record made, so a re-run never adds the notes twice.
    bench_manifest_jq --argjson a "${recs}" '.zone_overrides = $a' || bench_die "could not record zone_overrides in $(bench_manifest)"
    while IFS= read -r note; do
        [ -z "${note}" ] || bench_manifest_note "${note}" || bench_die "could not add a note to $(bench_manifest)"
    done <<EOF
${notes}
EOF
}

# bench_create_node <index> — create node <index>, a -lssd machine type (its local SSDs come with the type;
# no flag asks for them), with the argv common/create-instances.sh gives that node (create-instances.sh:166-185:
# name, zone, description, network interface, metadata, startup script, service account, scopes, tags, labels,
# boot disk, shielded VM, reservation affinity) except --machine-type=<its type> and
# --maintenance-policy=TERMINATE, the host-maintenance policy benchmark-probe.sh created its -lssd VM with
# (create-instances.sh hard-codes MIGRATE, untried on a local-SSD shape). bench_run prints the argv before it
# runs. test_node_deploy.py compares this argv with the real create-instances.sh's for the same node.
bench_create_node() {
    local i="$1" inst
    local -a labels
    inst="${INSTANCE_NAMES[$i]}"
    labels=()
    [ -z "${INSTANCE_LABELS:-}" ] || labels=(--labels="${INSTANCE_LABELS},tn-role=${NODE_ROLES[$i]}")
    [ "${BENCH_APPLY}" = "1" ] || return 0
    bench_run gcloud beta compute instances create "${inst}" \
        --project="${PROJECT_ID}" \
        --zone="${ZONES[$i]}" \
        --description="${NODE_ROLES[$i]} node $((i + 1))" \
        --machine-type="$(node_machine_type "${i}")" \
        --network-interface="network-tier=PREMIUM,subnet=default,nic-type=GVNIC,stack-type=IPV4_ONLY" \
        --metadata="EXECUTION_ADDRESS=${EXECUTION_ADDRESSES[$i]},NODE_NAME=${NODE_NAMES[$i]},DOCKER_IMAGE=${DOCKER_IMAGE},PROJECT_ID=${PROJECT_ID},PRIMARY_UDP_PORT=${DEFAULT_PRIMARY_UDP_PORT},WORKER_UDP_PORT=${DEFAULT_WORKER_UDP_PORT},HEALTHCHECK_TCP_PORT=${DEFAULT_HEALTHCHECK_TCP_PORT},BASE_DOMAIN=${BASE_DOMAIN}${TN_NODE_SCRIPTS_REF:+,tn-scripts-ref=${TN_NODE_SCRIPTS_REF}}" \
        --metadata-from-file="startup-script=${STARTUP_SCRIPT_PATH}" \
        --maintenance-policy=TERMINATE \
        --provisioning-model=STANDARD \
        --service-account="${SERVICE_ACCOUNT}" \
        --scopes=https://www.googleapis.com/auth/devstorage.read_only,https://www.googleapis.com/auth/logging.write,https://www.googleapis.com/auth/monitoring.write,https://www.googleapis.com/auth/service.management.readonly,https://www.googleapis.com/auth/servicecontrol,https://www.googleapis.com/auth/trace.append \
        --tags="${INSTANCE_TAGS:-validator,http-server,https-server,lb-health-check}" \
        ${labels[@]+"${labels[@]}"} \
        --create-disk="auto-delete=yes,boot=yes,device-name=${inst},image=${IMAGE},mode=rw,size=${NODE_DISK_SIZE:-100},type=${NODE_DISK_TYPE:-pd-ssd}${NODE_DISK_IOPS:+,provisioned-iops=${NODE_DISK_IOPS}}${NODE_DISK_THROUGHPUT:+,provisioned-throughput=${NODE_DISK_THROUGHPUT}}" \
        --no-shielded-secure-boot \
        --shielded-vtpm \
        --shielded-integrity-monitoring \
        --reservation-affinity=any
}

# bench_create_nodes <index...> — bench_create_node for each of these nodes side by side, each job's output
# in its own log (logs/create-<inst>-<UTC>.log), reported as create-instances.sh reports: a node that exists
# is skipped ("Instance <inst> already exists in <zone> — skipping."), a failed one is named on
# "❌ Error: Failed to create instance <inst> - See <log> for details" (step 2's create_failed_names and
# create_fail_log read that line) with the log's last lines. rc 1 when any failed.
bench_create_nodes() {
    local i inst log p rc=0
    local -a pids
    pids=()
    for i in "$@"; do
        inst="${INSTANCE_NAMES[$i]}"
        if gcloud compute instances describe "${inst}" --project="${PROJECT_ID}" --zone="${ZONES[$i]}" \
                --format='value(name)' </dev/null >/dev/null 2>&1; then
            echo "Instance ${inst} already exists in ${ZONES[$i]} — skipping."
            continue
        fi
        log="$(deploy_new_log "${BENCH_RESULTS_DIR}/logs" "create-${inst}")" || bench_die "cannot create a log in ${BENCH_RESULTS_DIR}/logs"
        bench_create_node "${i}" > "${log}" 2>&1 &
        pids[${#pids[@]}]="$!:${i}:${log}"
        echo "Started creation of ${inst} ($(node_machine_type "${i}") in ${ZONES[$i]}, PID: $!, Log: ${log})"
    done
    for p in ${pids[@]+"${pids[@]}"}; do
        i="${p#*:}"; log="${i#*:}"; i="${i%%:*}"; inst="${INSTANCE_NAMES[$i]}"
        if wait "${p%%:*}"; then
            echo "Successfully created instance ${inst}"
        else
            echo "❌ Error: Failed to create instance ${inst} - See ${log} for details"
            echo "   Last 10 lines of log:"
            tail -10 "${log}" | sed 's/^/   /'
            rc=1
        fi
    done
    return "${rc}"
}

# step_2 — common/create-instances.sh, its output copied to logs/create-instances-<UTC>.log per round.
# A fleet of one machine type that is not -lssd (every knob unset): one create-instances.sh call per round.
# Otherwise each round makes one create-instances.sh call per other machine type, with
# BENCH_CREATE_MACHINE_TYPE=<type> in that call's environment only (config.sh narrows the fleet to that
# type's nodes), and creates the -lssd nodes with bench_create_nodes; every call goes to the round's log.
# When a round fails, every instance it names must have failed on a stockout (bench_is_stockout; any other
# failure stops the step): each moves to its next BENCH_ZONE_FALLBACKS zone (zone_fallbacks[] + note),
# zones.env is written, and the create runs again — it skips the instances that exist — for at most
# ZONE_FALLBACK_MAX_ROUNDS rounds. manifest.zones_used records where every node was created. With
# BENCH_NODE_ZONES, zone_overrides_record and zones.env come first.
ZONE_FALLBACK_MAX_ROUNDS=3
step_2() {
    echo ">>> Step 2: create the bench instances (common/create-instances.sh, bench profile)"
    local i inst zone j bad=0 round=0 rc rlog clog name idx from to failed t lssd
    lssd="$(lssd_nodes)"
    if [ -n "${BENCH_NODE_ZONES:-}" ]; then
        zone_overrides_record
        zones_env_write
    fi
    while :; do
        round=$((round + 1))
        rlog="$(deploy_new_log "${BENCH_RESULTS_DIR}/logs" create-instances)" || bench_die "cannot create a log in ${BENCH_RESULTS_DIR}/logs"
        rc=0
        if create_plain; then
            echo "    + CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/common/create-instances.sh   (copy: ${rlog})"
            "${REPO_ROOT}/common/create-instances.sh" 2>&1 | tee -a "${rlog}" || rc=$?
        else
            for t in $(machine_groups); do
                case "${t}" in *-lssd) continue ;; esac
                echo "    + BENCH_CREATE_MACHINE_TYPE=${t} CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/common/create-instances.sh   (copy: ${rlog})"
                BENCH_CREATE_MACHINE_TYPE="${t}" "${REPO_ROOT}/common/create-instances.sh" 2>&1 | tee -a "${rlog}" || rc=$?
            done
            if [ -n "${lssd}" ]; then
                echo "    + bench_create_nodes ${lssd}   (-lssd: create-instances.sh's argv, --maintenance-policy=TERMINATE; copy: ${rlog})"
                # shellcheck disable=SC2086  # node indices
                bench_create_nodes ${lssd} 2>&1 | tee -a "${rlog}" || rc=$?
            fi
        fi
        [ "${rc}" -ne 0 ] || break
        failed="$(create_failed_names "${rlog}")"
        [ -n "${failed}" ] || bench_die "common/create-instances.sh exited ${rc} without naming a failed instance (${rlog})"
        for name in ${failed}; do
            clog="$(create_fail_log "${rlog}" "${name}")" \
                || bench_die "${name}: create failed and its own create log (named in ${rlog}) cannot be read — not judged a stockout"
            bench_is_stockout "$(cat "${clog}")" || bench_die "${name}: create failed for another reason than a stockout (${clog})"
        done
        [ "${round}" -lt "${ZONE_FALLBACK_MAX_ROUNDS}" ] \
            || bench_die "common/create-instances.sh still hits stockouts after ${round} rounds ($(printf '%s' "${failed}" | tr '\n' ' ')) — pick other zones (BENCH_ZONE_FALLBACKS) and re-run with --from 2"
        for name in ${failed}; do
            idx="$(bench_index_of "${name}")" || bench_die "create-instances.sh named '${name}', not a bench instance (${rlog})"
            from="${ZONES[$idx]}"
            to="$(zone_fallback_next "${idx}")"
            [ -n "${to}" ] || bench_die "${name}: ${from} is out of $(node_machine_type "${idx}") (stockout) and BENCH_ZONE_FALLBACKS has no zone left for index ${idx} — add one and re-run with --from 2"
            zone_fallback_record "${idx}" "${from}" "${to}"
        done
        zones_env_write
        echo "    round $((round + 1)) of at most ${ZONE_FALLBACK_MAX_ROUNDS}: create-instances.sh again (it skips the instances that exist)"
    done
    zones_used_record
    echo "    asserting tags == [bench-node] and labels.benchmark == 1 on every node"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        j="$(bench_instance_json "${inst}" "${zone}")"
        if [ -z "${j}" ] || ! printf '%s' "${j}" | jq -e '(.tags.items // []) == ["bench-node"] and .labels.benchmark == "1"' >/dev/null; then
            echo "    ✗ ${inst}: $(printf '%s' "${j}" | jq -c '{tags: .tags.items, labels}' 2>/dev/null || echo missing)" >&2; bad=1
        fi
    done
    if [ "${bad}" -ne 0 ]; then
        echo "❌ a bench instance is missing its bench-node tag / benchmark=1 label. Nothing else will run." >&2
        echo "   Inspect, then clean up with: benchmark/benchmark-teardown.sh --run ${BENCH_RUN_ID} (dry run first)" >&2
        exit 1
    fi
    echo "    ✓ all ${#INSTANCE_NAMES[@]} tagged bench-node + labelled benchmark=1"
    local insts="[]" disk djson shape dd
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        j="$(bench_instance_json "${inst}" "${zone}")"
        disk="$(printf '%s' "${j}" | jq -r '.disks[] | select(.boot) | .source | split("/") | last')"
        bench_run gcloud compute disks add-labels "${disk}" --zone="${zone}" --project="${PROJECT_ID}" \
            --labels="${BENCH_LABELS},tn-role=${NODE_ROLES[$i]}" --format=none
        djson="$(gcloud compute disks describe "${disk}" --zone="${zone}" --project="${PROJECT_ID}" --format=json)"
        shape="$(bench_machine_shape "$(printf '%s' "${j}" | jq -r '.machineType | split("/") | last')" "${zone}")"
        insts="$(printf '%s' "${insts}" | jq --argjson j "${j}" --argjson d "${djson}" --arg role "${NODE_ROLES[$i]}" \
            --arg zone "${zone}" --arg v "${shape% *}" --arg m "${shape#* }" '
            . + [{name: $j.name, role: $role, zone: $zone, instance_id: $j.id,
                  machine_type: ($j.machineType | split("/") | last), vcpus: ($v|tonumber), memory_mb: ($m|tonumber),
                  internal_ip: $j.networkInterfaces[0].networkIP,
                  external_ip: ($j.networkInterfaces[0].accessConfigs[0].natIP // null),
                  boot_disk: {name: $d.name, size_gb: ($d.sizeGb|tonumber), type: ($d.type | split("/") | last)},
                  source_image: ($d.sourceImage // null)}]')"
    done
    if [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ]; then
        dd="$(data_disk_plan)" && insts="$(printf '%s' "${insts}" | jq -c --argjson m "${dd}" 'map(.data_disk = $m[.name])')" \
            || bench_die "cannot build manifest.instances[].data_disk (BENCH_NODE_DATADIR_LSSD=1)"
        echo "    instances[].data_disk: \"local-ssd\" on $(lssd_datadir_nodes | wc -w | tr -d ' ') node(s) (step 3 mounts them and fills it in), \"boot\" on the others"
    fi
    bench_manifest_jq --argjson a "${insts}" '.instances = $a'
    echo "    ✓ manifest.instances[] recorded (${#INSTANCE_NAMES[@]})"
    # Every boot disk must come from the pinned image (IMAGE; a family would float): the disks describe
    # above reports it as a URL ending in projects/<p>/global/images/<name>.
    local offimg
    offimg="$(printf '%s' "${insts}" | jq -r --arg img "${IMAGE}" '.[] | (.source_image // "") as $s
        | select(($s == $img or ($s | endswith("/" + $img))) | not) | "\(.name) boots \(if $s == "" then "an unknown image" else $s end)"')" \
        || bench_die "could not read the instances' source images"
    [ -z "${offimg}" ] || bench_die "the fleet does not all boot the pinned image ${IMAGE} (BENCH_NODE_BOOT_IMAGE): $(printf '%s' "${offimg}" | paste -sd ';' - | sed 's/;/; /g') — the fleet is refused (manifest.instances[].source_image): tear it down (benchmark-teardown.sh) and deploy again"
    echo "    ✓ every boot disk is ${IMAGE}"
    # The run's own obs VM (metrics only; obs-lib.sh): created, or kept when this run already has it
    # (a re-run with --from 2); one that belongs to another run is refused. Step 8 brings it up.
    obs_or_die "bench-obs could not be created or kept (above) — re-run with --from 2 (nodes are kept, this run's VM is adopted)" \
        bench_obs_create
}

step_3() {
    echo ">>> Step 3: wait for first-boot bootstrap (serial marker 'devnet-startup.sh complete')"
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        bench_serial_wait "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "devnet-startup.sh complete" \
            "${BOOTSTRAP_TIMEOUT_SECS}" "${BOOTSTRAP_POLL_SECS}" \
            || bench_die "${INSTANCE_NAMES[$i]} did not finish bootstrap; serial: gcloud compute instances get-serial-port-output ${INSTANCE_NAMES[$i]} --zone=${ZONES[$i]}"
    done
    lssd_mount_all
}

# lssd_mount_node <index> — step 3's local-SSD session on one node: bench_lssd_mount_script on the stdin of one
# IAP session (tn_iap_ssh_stdin), its output (CRs dropped) into ${LSSD_MOUNT_DIR}/<index>.out. Never fails:
# lssd_mount_all reads that file, and a node without one, or without its LSSD_MOUNT line in it, is a failure
# lssd_mount_all names.
LSSD_MOUNT_DIR=""
lssd_mount_node() {
    local inst="${INSTANCE_NAMES[$1]}"
    [ "${BENCH_APPLY}" = "1" ] || return 0
    bench_lssd_mount_script "${inst}" "$(node_datadir "$1")" | tn_iap_ssh_stdin "${inst}" "${ZONES[$1]}" 2>&1 | tr -d '\r' > "${LSSD_MOUNT_DIR}/$1.out" || true
}

# lssd_mount_all — step 3's local-SSD sub-step, after the serial markers and before keygen (step 5) first
# writes into the data directory. With BENCH_NODE_DATADIR_LSSD unset or 0 it returns at once: step 3 is the
# serial markers alone. Otherwise lssd_mount_node on every node of lssd_datadir_nodes, BENCH_NODE_JOBS at a
# time (bench_node_jobs_run); then, in index order, each session's output goes to logs/lssd-mount-<UTC>.log
# under a "== <inst>" line, its LSSD_MOUNT line is printed, and bench_lssd_mount_record turns it into the
# object merged into that node's instances[].data_disk (over step 2's {"class": "local-ssd"}). A failed line
# (`failed lost: …` for a wiped SSD), no line or any other shape leaves that node's record as it is and puts
# it on the failed list; the other nodes' records are written all the same. After every node one line,
#   LSSD_MOUNT_SUMMARY nodes=<n> done=<n> kept=<n> resumed=<n> failed=[<inst> …]
# and the step stops naming every failed node: a data directory left on the boot disk would spoil the
# comparison. A re-run is safe: the script leaves a kept or resumed node's file system as it is and fails a
# lost one rather than format it again.
lssd_mount_all() {
    [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ] || return 0
    local nodes jobs log i inst out rec mk n=0 nd=0 nk=0 nr=0 failed=""
    nodes="$(lssd_datadir_nodes)"
    [ -n "${nodes}" ] || bench_die "step 3: BENCH_NODE_DATADIR_LSSD=1 but no node has its data directory on a local SSD"
    jobs="${BENCH_NODE_JOBS:-1}"
    case "${jobs}" in ''|*[!0-9]*|0) jobs=1 ;; esac
    log="$(deploy_new_log "${BENCH_RESULTS_DIR}/logs" lssd-mount)" || bench_die "cannot create a log in ${BENCH_RESULTS_DIR}/logs"
    LSSD_MOUNT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bench-lssd-mount.XXXXXX")" || bench_die "step 3: cannot create a temp directory"
    echo "    local SSD -> data directory on $(printf '%s' "${nodes}" | wc -w | tr -d ' ') node(s): one IAP session each (bench_lssd_mount_script; review: --print-lssd-mount <instance>)$([ "${jobs}" -le 1 ] || printf ', up to %s at a time' "${jobs}") -> ${log}"
    # shellcheck disable=SC2086  # node indices
    bench_node_jobs_run "${jobs}" "local SSD mount (step 3)" lssd_mount_node ${nodes}
    for i in ${nodes}; do
        inst="${INSTANCE_NAMES[$i]}"; n=$((n + 1)); out=""
        [ ! -f "${LSSD_MOUNT_DIR}/${i}.out" ] || out="$(cat "${LSSD_MOUNT_DIR}/${i}.out")"
        printf '== %s (%s) %s\n%s\n' "${inst}" "${ZONES[$i]}" "$(bench_now_iso)" "${out}" >> "${log}"
        printf '%s\n' "${out}" | grep -E "^LSSD_MOUNT ${inst} " | sed 's/^/      /' || true
        if rec="$(printf '%s\n' "${out}" | bench_lssd_mount_record "${inst}" 2>"${LSSD_MOUNT_DIR}/err")"; then
            bench_manifest_jq --arg n "${inst}" --argjson o "${rec}" '
                if any(.instances[]?; .name == $n) then .instances |= map(if .name == $n then .data_disk = ((.data_disk // {}) + $o) else . end)
                else error("no instances[] entry for " + $n + " (step 2 writes it)") end' \
                || bench_die "${inst}: could not record instances[].data_disk in $(bench_manifest)"
            mk="$(printf '%s' "${rec}" | jq -r '.mkfs')"
            case "${mk}" in done) nd=$((nd + 1)) ;; kept) nk=$((nk + 1)) ;; resumed) nr=$((nr + 1)) ;; esac
        else
            failed="${failed} ${inst}"
            echo "      ✗ ${inst}: $(sed 's/^❌ bench_lssd_mount_record: //' "${LSSD_MOUNT_DIR}/err" | head -1)" >&2
        fi
    done
    rm -f "${LSSD_MOUNT_DIR}"/*.out "${LSSD_MOUNT_DIR}/err"; rmdir "${LSSD_MOUNT_DIR}" 2>/dev/null || true; LSSD_MOUNT_DIR=""
    echo "LSSD_MOUNT_SUMMARY nodes=${n} done=${nd} kept=${nk} resumed=${nr} failed=[${failed# }]"
    [ -z "${failed}" ] || bench_die "step 3: the data directory is not on the local SSD of${failed} (each node's LSSD_MOUNT line above; sessions in ${log}) — keygen (step 5) must not write into it. Fix the node and re-run with --from 3 (a mounted node is kept), or tear down: a lost node's SSD was wiped and it is out for the run"
}

step_4()  { echo ">>> Step 4: bench firewall rules"; "${DIR}/benchmark-firewall.sh" apply --yes --run "${BENCH_RUN_ID}"; }
# keygen_record <log> — manifest keygen_timing {inst: {secs, reused}} and node_info_rpc {inst: {http, ws}}
# from the KEYGEN_DONE lines devnet-keygen.sh prints with KEYGEN_REPORT=1
#   KEYGEN_DONE <inst> rc=<n> secs=<n> reused=<0|1> rpc_http=<url|-> rpc_ws=<url|->
# (a node's last line wins; node_info_rpc only from rc=0 lines; "-" or a missing field: null), merged
# over what an earlier step 5 recorded. No line, no change; never fatal.
keygen_record() {
    local j n
    j="$(tr -d '\r' < "$1" | sed -nE 's/^[[:space:]]*(KEYGEN_DONE[[:space:]].*)$/\1/p' | jq -R -s -c '
        def kv: [.[] | capture("^(?<k>[a-z_]+)=(?<v>.*)$")?] | map({(.k): .v}) | add // {};
        def num: if . != null and test("^[0-9]+(\\.[0-9]+)?$") then tonumber else null end;
        def flag: if . == "1" or . == "true" or . == "yes" then true elif . == "0" or . == "false" or . == "no" then false else null end;
        def url: if . == null or . == "" or . == "-" then null else . end;
        split("\n") | map(select(length > 0) | split(" ") | map(select(length > 0)) | {inst: .[1], f: (.[2:] | kv)})
        | map(select(.inst != null))
        | {timing: (map({key: .inst, value: {secs: (.f.secs | num), reused: (.f.reused | flag)}}) | from_entries),
           rpc: (map(select(.f.rc == "0")) | map({key: .inst, value: {http: (.f.rpc_http | url), ws: (.f.rpc_ws | url)}}) | from_entries)}' 2>/dev/null)" || j=""
    n="$(printf '%s' "${j}" | jq -r '.timing | length' 2>/dev/null || true)"
    case "${n}" in ''|0) echo "    · no KEYGEN_DONE line in ${1} (KEYGEN_REPORT=${KEYGEN_REPORT:-unset}): keygen_timing not recorded"; return 0 ;; esac
    bench_manifest_jq --argjson j "${j}" '.keygen_timing = ((.keygen_timing // {}) + $j.timing)
        | .node_info_rpc = ((.node_info_rpc // {}) + $j.rpc)' \
        || { bench_warn "could not record keygen_timing / node_info_rpc in $(bench_manifest)"; return 0; }
    echo "    ✓ manifest.keygen_timing: ${n} node(s); node_info_rpc: $(printf '%s' "${j}" | jq -c '.rpc | length') node(s)"
}

# step_5 — devnet-keygen.sh (bench profile), its output copied to logs/keygen-<UTC>.log; then
# keygen_record from that copy, also when keygen failed (the nodes it finished are recorded).
step_5() {
    local log rc=0
    echo ">>> Step 5: keygen"
    log="$(deploy_new_log "${BENCH_RESULTS_DIR}/logs" keygen)" || bench_die "cannot create a log in ${BENCH_RESULTS_DIR}/logs"
    echo "    + CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/devnet-keygen.sh   (copy: ${log})"
    "${REPO_ROOT}/devnet-keygen.sh" 2>&1 | tee -a "${log}" || rc=$?
    keygen_record "${log}"
    [ "${rc}" -eq 0 ] || bench_die "devnet-keygen.sh exited ${rc} (${log})"
}
step_6()  { echo ">>> Step 6: genesis (chain ${CHAIN_ID}, workspace ${GENESIS_WORKSPACE})"; "${REPO_ROOT}/devnet-genesis-build.sh"; }

# coordinated_start_record <COORDINATED_START line> — manifest.coordinated_start (C4b) from the marker
# `devnet-finalize.sh --start-all` prints: "COORDINATED_START due=<unix> nodes=<n> started=<n>
# skipped_running=<n> spread_secs=<n> max_late_secs=<n>", integers only; dies on any other shape.
# The FIRST start is the run's record (step 9 measures progress from its due time; the analysis reads
# its spread). A later start-all (a --from 7 re-run) never replaces it: its line is appended to
# manifest.coordinated_start_reruns[] = {line, ts}, with a warning when it started nodes (they joined
# after the fleet, so they sit out the epoch they started in).
coordinated_start_record() {
    local line="$1" w k v prev due="" nodes="" started="" skipped="" spread="" late=""
    local -a words
    read -r -a words <<EOF
${line#COORDINATED_START }
EOF
    for w in "${words[@]}"; do
        case "${w}" in *=*) ;; *) bench_die "malformed COORDINATED_START line (${w}): ${line}" ;; esac
        k="${w%%=*}"; v="${w#*=}"
        case "${v}" in ''|*[!0-9]*) bench_die "malformed COORDINATED_START line (${k} is not an integer): ${line}" ;; esac
        case "${k}" in
            due) due="${v}" ;;
            nodes) nodes="${v}" ;;
            started) started="${v}" ;;
            skipped_running) skipped="${v}" ;;
            spread_secs) spread="${v}" ;;
            max_late_secs) late="${v}" ;;
            *) bench_die "malformed COORDINATED_START line (unknown field ${k}): ${line}" ;;
        esac
    done
    [ -n "${due}" ] && [ -n "${nodes}" ] && [ -n "${started}" ] && [ -n "${skipped}" ] && [ -n "${spread}" ] && [ -n "${late}" ] \
        || bench_die "malformed COORDINATED_START line (a field is missing): ${line}"
    prev="$(jq -c '.coordinated_start // empty' "$(bench_manifest)" 2>/dev/null || true)"
    if [ -n "${prev}" ]; then
        bench_manifest_jq --arg l "${line}" --arg ts "$(bench_now_iso)" \
            '.coordinated_start_reruns = ((.coordinated_start_reruns // []) + [{line: $l, ts: $ts}])' \
            || bench_die "could not record coordinated_start_reruns in $(bench_manifest)"
        if [ "${started}" -eq 0 ]; then
            echo "    · start-all started nothing (${skipped} already running): manifest.coordinated_start keeps the first start ${prev}"
        else
            bench_warn "start-all started ${started} node(s) on a re-run, after the fleet's coordinated start (${line}): they sit out the epoch they joined; manifest.coordinated_start keeps the first start, this one is in coordinated_start_reruns"
        fi
        return 0
    fi
    bench_manifest_jq --argjson due "${due}" --argjson nodes "${nodes}" --argjson started "${started}" \
        --argjson skipped "${skipped}" --argjson spread "${spread}" --argjson late "${late}" --arg ts "$(bench_now_iso)" '
        .coordinated_start = {due: $due, nodes: $nodes, started: $started, skipped_running: $skipped,
                              spread_secs: $spread, max_late_secs: $late, ts: $ts}' \
        || bench_die "could not record coordinated_start in $(bench_manifest)"
    echo "    ✓ manifest.coordinated_start: due ${due}, ${started}/${nodes} started (${skipped} already running), spread ${spread} s, latest ${late} s after due"
}

# node_startup_merge <inst> <json object> — manifest node_startup[<inst>] += <object> (its keys replace
# the record's, the others stay). Inline (a plain loop) it edits the manifest at once. Inside a node job of
# bench_node_jobs_run (NODE_JOBS_SPOOL set) it only appends the object to <spool>/<inst>.node_startup.jsonl;
# the parent applies those in fleet order once every job has ended, so jobs side by side never edit
# manifest.json themselves and no update can be lost. Non-zero when the write fails (the caller dies).
NODE_JOBS_SPOOL=""
node_startup_merge() {
    if [ -n "${NODE_JOBS_SPOOL:-}" ]; then
        printf '%s\n' "$2" >> "${NODE_JOBS_SPOOL}/$1.node_startup.jsonl"
        return
    fi
    bench_manifest_jq --arg i "$1" --argjson o "$2" '.node_startup[$i] = ((.node_startup[$i] // {}) + $o)'
}

# bench_node_jobs_run <jobs> <label> <fn> <idx…> — <fn> <idx> for every node index given, in that order.
# jobs 1 (or one node): inline, a plain loop: the output, and the stop at the first node whose <fn>
# dies, are a serial loop's. jobs > 1: batches of <jobs> nodes, each <fn> in its own subshell with its
# output (stdout + stderr) in <tmp>/<idx>.out and NODE_JOBS_SPOOL=<tmp>. Once all have ended, the
# node_startup records they spooled are applied to the manifest in the order given (node_startup_merge),
# the outputs are printed in that order, and the run dies naming every node whose <fn> failed (its own
# error is in its output) or whose record could not be applied. A <fn> run this way writes the manifest
# only through node_startup_merge.
bench_node_jobs_run() {
    local jobs="$1" label="$2" fn="$3" dir i p o inst failed="" unrecorded="" n=0
    local -a pids
    shift 3
    case "${jobs}" in ''|*[!0-9]*) jobs=1 ;; esac
    if [ "${jobs}" -le 1 ] || [ "$#" -le 1 ]; then
        for i in "$@"; do "${fn}" "${i}"; done
        return 0
    fi
    dir="$(mktemp -d "${TMPDIR:-/tmp}/bench-node-jobs.XXXXXX")" || bench_die "${label}: cannot create a temp directory"
    pids=()
    for i in "$@"; do
        ( NODE_JOBS_SPOOL="${dir}"; "${fn}" "${i}" ) > "${dir}/${i}.out" 2>&1 &
        pids[${#pids[@]}]="$!:${i}"
        n=$((n + 1))
        if [ "${n}" -ge "${jobs}" ]; then
            for p in "${pids[@]}"; do wait "${p%%:*}" || failed="${failed} ${p#*:}"; done
            pids=(); n=0
        fi
    done
    for p in ${pids[@]+"${pids[@]}"}; do wait "${p%%:*}" || failed="${failed} ${p#*:}"; done
    for i in "$@"; do
        inst="${INSTANCE_NAMES[$i]}"
        [ -f "${dir}/${inst}.node_startup.jsonl" ] || continue
        while IFS= read -r o; do
            [ -n "${o}" ] || continue
            node_startup_merge "${inst}" "${o}" || { unrecorded="${unrecorded} ${inst}"; break; }
        done < "${dir}/${inst}.node_startup.jsonl"
    done
    for i in "$@"; do cat "${dir}/${i}.out"; done
    rm -rf "${dir}"
    [ -z "${unrecorded}" ] || echo "❌ ${label}: could not record node_startup in $(bench_manifest) for:${unrecorded}" >&2
    [ -z "${failed}" ] || echo "❌ ${label}: failed on$(for i in ${failed}; do printf ' %s' "${INSTANCE_NAMES[$i]}"; done) (each node's own error is in its output above)" >&2
    [ -z "${failed}${unrecorded}" ] || exit 1
}

# prestart_node <index> — step 7's pre-start config on one node, one IAP session: skipped when
# stage-only reported the node RUNNING (STEP7_RUNNING). The session's stdin is the fsync probe
# (bench_fsync_probe_script) followed by the pre-start script; dies without its PRECFG_OK line, else
# records node_startup[<inst>].logrotate_size ("20G"|null) and .params_bak ("written"|"kept"|null)
# from that line's logrotate= / paramsbak= fields ("-" or absent: null), .db_sync_mode from its dbsync=
# field ("durable" when absent: BENCH_NODE_DB_SYNC_MODE unset passes no flag, and durable is the node's
# default; make_bundle.py refuses a run with any "safe-no-sync" node unless told otherwise), and
# .fsync_probe from its FSYNC_PROBE line (bench_fsync_probe_record: {p50_us, p95_us}, or
# {probe_failed: true, reason}). The host probe (bench_host_probe_script) runs between the two, before
# any host step: .host from its HOST_PROBE line (bench_host_probe_record), .host_steps from the HOST_STEP
# lines of the pre-start script's host steps (bench_host_step_record; [] when it ran none).
#
# A node whose data directory is on its local SSD (NODE_DATADIR_LSSD=1) starts the session with
# bench_lssd_check_script, before the fsync probe and the host probe: unless the data directory is the SSD's
# mount it prints `PRECFG_FAIL <inst> local SSD not mounted at <D>` and ends the session, so neither probe ever
# measures the boot disk on that node and no PRECFG_OK follows. Every other node's session is unchanged.
STEP7_RUNNING=""
prestart_node() {
    local inst="${INSTANCE_NAMES[$1]}" out line lr pb ds fp o hp hs chk="" rv
    case " ${STEP7_RUNNING}" in *" ${inst} "*) echo "      · ${inst}: running — skipped"; return 0 ;; esac
    if [ "${NODE_DATADIR_LSSD[$1]}" = 1 ]; then
        chk="$(bench_lssd_check_script "${inst}" "$(node_datadir "$1")")" \
            || bench_die "${inst}: cannot build its local-SSD check (bench_lssd_check_script) — no node has been started"
    fi
    out="$({ [ -z "${chk}" ] || printf '%s\n' "${chk}"; bench_fsync_probe_script "${inst}"; bench_host_probe_script "${inst}"; bench_prestart_script "${inst}"; } | tn_iap_ssh_stdin "${inst}" "${ZONES[$1]}" 2>&1 | tr -d '\r' || true)"
    printf '%s\n' "${out}" | grep -E '^FSYNC_PROBE |^HOST_PROBE |^HOST_STEP |PRECFG_(OK|FAIL)' | sed 's/^/      /' || true
    line="$(printf '%s\n' "${out}" | grep -F "PRECFG_OK ${inst} " | tail -1 || true)"
    [ -n "${line}" ] || bench_die "pre-start config failed on ${inst} — no node has been started; fix it and re-run with --from 7 (staged nodes are skipped, flags already set are accepted)"
    lr="$(postcfg_field "${line}" logrotate)"; pb="$(postcfg_field "${line}" paramsbak)"
    case "${pb}" in written|kept) ;; *) pb="" ;; esac
    ds="$(postcfg_field "${line}" dbsync)"; ds="${ds:-durable}"
    rv="$(postcfg_field "${line}" reserved)"
    fp="$(printf '%s\n' "${out}" | bench_fsync_probe_record "${inst}")" || fp=""
    [ -n "${fp}" ] || fp='{"probe_failed":true,"reason":"no record from bench_fsync_probe_record"}'
    hp="$(printf '%s\n' "${out}" | bench_host_probe_record "${inst}")" || hp=""
    [ -n "${hp}" ] || hp='{"probe_failed":true,"reason":"no record from bench_host_probe_record"}'
    hs="$(printf '%s\n' "${out}" | bench_host_step_record "${inst}")" || hs=""
    [ -n "${hs}" ] || hs='[]'
    o="$(jq -n -c --arg lr "${lr}" --arg pb "${pb}" --arg ds "${ds}" --argjson fp "${fp}" --argjson hp "${hp}" --argjson hs "${hs}" '
        def str: if . == "" or . == "-" then null else . end;
        {logrotate_size: ($lr|str), params_bak: ($pb|str), db_sync_mode: $ds, fsync_probe: $fp, host: $hp, host_steps: $hs}')" || bench_die "${inst}: cannot build its node_startup record"
    # BENCH_NODE_RESERVE_PORTS=1: the kernel's reserved list the pre-start config verified (PRECFG_OK reserved=).
    [ -z "${rv}" ] || o="$(printf '%s' "${o}" | jq -c --arg rv "${rv}" '. + {ip_local_reserved_ports: $rv}')" \
        || bench_die "${inst}: cannot build its node_startup record"
    node_startup_merge "${inst}" "${o}" || bench_die "${inst}: could not record node_startup in $(bench_manifest)"
}

# prestart_arm_json — the manifest's last param_arms[] entry with via "prestart" (the first-start arm
# step 7 applied), compact; "" when there is none.
prestart_arm_json() {
    jq -c '[(.param_arms // [])[]? | objects | select(.via == "prestart")] | last // empty' "$(bench_manifest)" 2>/dev/null || true
}

# step7_arm_check — with BENCH_ARM_FILE (bench_arm_state_load already ran), or with a first-start arm in
# the manifest: the arm a re-run would configure must be the one the fleet started in. Dies on an arm
# file whose sha256 is not the recorded one, on a recorded arm the run no longer names, and on an arm
# file named after the fleet started without one.
step7_arm_check() {
    local rec rsha
    rec="$(prestart_arm_json)"
    if [ -n "${rec}" ]; then
        rsha="$(printf '%s' "${rec}" | jq -r '.sha256 // ""')"
        [ -n "${BENCH_ARM_FILE:-}" ] || bench_die "the fleet started in the arm $(printf '%s' "${rec}" | jq -r '.name') ($(printf '%s' "${rec}" | jq -r '.file // "?"'), manifest.param_arms via prestart): set BENCH_ARM_FILE to that file to re-run step 7"
        [ "${rsha}" = "${BENCH_ARM_SHA256}" ] || bench_die "BENCH_ARM_FILE ${BENCH_ARM_FILE} (sha256 ${BENCH_ARM_SHA256}) is not the arm the fleet started in (sha256 ${rsha}, manifest.param_arms via prestart)"
    elif [ -n "${BENCH_ARM_FILE:-}" ] && [ -n "$(jq -c '.coordinated_start // empty' "$(bench_manifest)" 2>/dev/null || true)" ]; then
        bench_die "the fleet already started without a first-start arm (manifest.coordinated_start, no param_arms via prestart): BENCH_ARM_FILE cannot apply now — use tools/params-apply.sh, or unset it"
    fi
    return 0
}

# prestart_arm_record — manifest.param_arms += the first-start arm (BENCH_ARM_FILE), once, right after
# the first coordinated start: {name, begin, via: "prestart", file (repo-relative), sha256, switches (all
# of arms/switches.tsv, as strings), nodes ({inst: the switches step 7 wrote into its parameters.yaml}),
# host ([{step, value, nodes: {inst: node_startup[inst].host_steps' result}}], run order), ready}, with
# begin = ready = the coordinated start's due time and no end (the arm stays in force). A re-run keeps
# the first record (step7_arm_check has matched its sha256).
prestart_arm_record() {
    local m due begin root abs rel w insts steps
    m="$(bench_manifest)"
    if [ -n "$(prestart_arm_json)" ]; then
        echo "    · manifest.param_arms keeps the first start's arm ${BENCH_ARM_NAME} (via prestart)"
        return 0
    fi
    due="$(jq -r '.coordinated_start.due // empty' "${m}" 2>/dev/null || true)"
    case "${due}" in ''|*[!0-9]*) bench_die "cannot record the first-start arm ${BENCH_ARM_NAME}: manifest.coordinated_start.due is '${due}'" ;; esac
    begin="$(bench_iso_from_unix "${due}")" || bench_die "cannot turn the coordinated start ${due} into a UTC time"
    root="$(cd "${REPO_ROOT}" && pwd -P)"
    abs="$(cd "$(dirname "${BENCH_ARM_FILE}")" && pwd -P)/$(basename "${BENCH_ARM_FILE}")"
    case "${abs}" in "${root}"/*) rel="${abs#"${root}"/}" ;; *) rel="${abs}" ;; esac
    w="$(bench_arm_writes | jq -R -s -c 'split("\n") | map(select(length > 0) | capture("^(?<k>[^=]+)=(?<v>.*)$") | {(.k): .v}) | add // {}')" \
        || bench_die "cannot list the switches arm ${BENCH_ARM_NAME} writes"
    insts="$(printf '%s\n' "${INSTANCE_NAMES[@]}" | jq -R -s -c 'split("\n") | map(select(length > 0))')" || bench_die "cannot list the fleet"
    steps="$(printf '%s\n' "${BENCH_ARM_HOST}" | jq -R -s -c 'split("\n") | map(select(length > 0) | split(" ") | {step: .[0], value: (if .[1] == "-" then null else .[1] end)})')" \
        || bench_die "cannot list the host steps of arm ${BENCH_ARM_NAME}"
    bench_manifest_jq --arg n "${BENCH_ARM_NAME}" --arg b "${begin}" --arg f "${rel}" --arg s "${BENCH_ARM_SHA256}" \
        --argjson sw "$(bench_arm_switches_json)" --argjson w "${w}" --argjson insts "${insts}" --argjson steps "${steps}" '
        . as $m
        | .param_arms = ((.param_arms // []) + [{
            name: $n, begin: $b, via: "prestart", file: $f, sha256: $s, switches: $sw,
            nodes: (reduce $insts[] as $i ({}; .[$i] = $w)),
            host: [$steps[] as $st | {step: $st.step, value: $st.value,
                    nodes: (reduce $insts[] as $i ({}; .[$i] = ([($m.node_startup[$i].host_steps // [])[]? | objects
                        | select(.step == $st.step) | .result] | last // {failed: "no host step record from step 7"})))}],
            ready: $b}])' \
        || bench_die "could not record the first-start arm in $(bench_manifest)"
    echo "    ✓ manifest.param_arms: ${BENCH_ARM_NAME} via prestart (${rel}, sha256 ${BENCH_ARM_SHA256}), begin = ready = ${begin}; writes $(printf '%s' "${w}" | jq -r 'to_entries | map("\(.key)=\(.value)") | join(" ") | if . == "" then "none (every switch at its default)" else . end')"
}

# reserve_ports_node <index> — the host step reserve-ports (bench_host_step_script; RESERVE_PORTS, the
# list bench_reserved_ports prints) on one node over one IAP session, before its first start; dies unless its
# HOST_STEP line shows every port reserved after it, else records node_startup[<inst>].reserve_ports (the
# bench_host_step_record entry). Idempotent: a re-run finds the ports reserved and changes nothing.
RESERVE_PORTS=""
reserve_ports_node() {
    local inst="${INSTANCE_NAMES[$1]}" script out rec n
    script="$(bench_host_step_script "${inst}" reserve-ports "${RESERVE_PORTS}")" \
        || bench_die "${inst}: cannot build its reserve-ports host step — no node has been started"
    out="$(printf '%s\n' "${script}" | tn_iap_ssh_stdin "${inst}" "${ZONES[$1]}" 2>&1 | tr -d '\r' || true)"
    printf '%s\n' "${out}" | grep -E '^HOST_STEP ' | sed 's/^/      /' || true
    rec="$(printf '%s\n' "${out}" | bench_host_step_record "${inst}" | jq -c 'last // empty')" || rec=""
    n="$(printf '%s\n' "${RESERVE_PORTS}" | tr ',' '\n' | grep -c . || true)"
    [ -n "${rec}" ] && [ "$(printf '%s' "${rec}" | jq -r '.result.ports_reserved_after // empty')" = "${n}" ] \
        || bench_die "${inst}: reserve-ports ${RESERVE_PORTS} did not hold (HOST_STEP above: ${rec:-no line}) — no node has been started; re-run with --from 7"
    node_startup_merge "${inst}" "{\"reserve_ports\":${rec}}" || bench_die "${inst}: could not record node_startup in $(bench_manifest)"
}

# step7_reserve_ports <jobs> — BENCH_NODE_RESERVE_PORTS=1: the node's listener ports (bench_reserved_ports:
# the root config.sh's DEFAULT_PRIMARY_UDP_PORT, DEFAULT_WORKER_UDP_PORT, DEFAULT_HEALTHCHECK_TCP_PORT) out of
# the kernel's ephemeral range on every node, before stage-only's staging start binds them (bench 6's R3-D1:
# a node whose port an outgoing connection held failed to start with "Address already in use"). Then
# manifest.reserved_ports = those ports, as numbers. Any node that fails stops step 7 before any start.
step7_reserve_ports() {
    RESERVE_PORTS="$(bench_reserved_ports)" || bench_die "BENCH_NODE_RESERVE_PORTS=1 and the node's ports are not known (above) — no node has been started"
    echo "    reserve-ports: per node, one IAP session: ${RESERVE_PORTS} into net.ipv4.ip_local_reserved_ports, now and in /etc/sysctl.d, before the staging start$([ "$1" -le 1 ] || printf ', up to %s at a time' "$1")"
    bench_node_jobs_run "$1" "reserve-ports (no node has been started; re-run with --from 7)" reserve_ports_node "${!INSTANCE_NAMES[@]}"
    bench_manifest_jq --argjson p "[${RESERVE_PORTS}]" '.reserved_ports = $p' || bench_die "could not record reserved_ports in $(bench_manifest)"
    echo "    ✓ manifest.reserved_ports: [${RESERVE_PORTS}]"
}

# step_7 — the fleet's one coordinated start (D1: no validator runs while the committee is
# incomplete; no node restarts after the start). Every node is configured while its unit is
# stopped, then devnet-finalize.sh starts them all at one due time on the nodes' clocks:
#   network-config    devnet-network-config.sh --yes: Closed admission on every node (nothing restarts)
#   reserve-ports     BENCH_NODE_RESERVE_PORTS=1: step7_reserve_ports, the listener ports reserved per node
#   stage-only        devnet-finalize.sh --stage-only: stage + v2 finalize + stop; the unit stays enabled
#   pre-start config  bench_fsync_probe_script + bench_prestart_script per node over one IAP session
#                     (PRECFG_OK required; FSYNC_PROBE recorded, never required), then one
#                     FSYNC_PROBE_SUMMARY line over the fleet (bench_fsync_probe_summary; never fatal)
#   start-all         devnet-finalize.sh --start-all: COORDINATED_START -> manifest.coordinated_start
# The two finalize runs are also copied to results/<run>/logs/finalize-{stage,start}-<utc>.log.
# A re-run (--from 7) converges: network-config is idempotent, stage-only skips PRESTAGED and RUNNING
# nodes, pre-start is skipped for a node stage-only reported RUNNING after the coordinated start (it
# was configured before it; step 8 refuses a node without it) and accepts flags that already hold their
# value, and start-all skips RUNNING nodes. A unit RUNNING before any coordinated start ran alone: the
# step stops and asks for it to be stopped first.
step_7() {
    local logs="${BENCH_RESULTS_DIR}/logs" log rc running="" marker spread jobs w
    echo ">>> Step 7: finalize — network-config, stage-only, pre-start config, start-all (one coordinated start)"
    mkdir -p "${logs}"
    if [ -n "${BENCH_ARM_FILE:-}" ]; then
        # The first-start arm, read once here (the pre-start scripts below use it): its file must parse.
        bench_arm_state_load || bench_die "BENCH_ARM_FILE ${BENCH_ARM_FILE} is refused (above) — no node has been configured"
        w="$(bench_arm_writes | paste -sd ' ' -)"
        echo "    first-start arm ${BENCH_ARM_NAME} (${BENCH_ARM_FILE}, sha256 ${BENCH_ARM_SHA256}): writes ${w:-no switch}; host steps: $(printf '%s\n' "${BENCH_ARM_HOST}" | awk 'NF { printf "%s%s%s", (n++ ? ", " : ""), $1, ($2 == "-" ? "" : " " $2) } END { if (!n) printf "none" }')"
    fi
    step7_arm_check

    echo "    network-config: + CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/devnet-network-config.sh --yes   (renders ${GENESIS_WORKSPACE}/genesis/network-config/)"
    "${REPO_ROOT}/devnet-network-config.sh" --yes \
        || bench_die "devnet-network-config.sh --yes failed — no node has been started; fix it and re-run with --from 7"

    jobs="${BENCH_NODE_JOBS:-1}"
    case "${jobs}" in ''|*[!0-9]*|0) jobs=1 ;; esac
    [ "${BENCH_NODE_RESERVE_PORTS:-0}" != 1 ] || step7_reserve_ports "${jobs}"

    log="${logs}/finalize-stage-$(date -u +%Y%m%dT%H%M%SZ).log"
    echo "    stage-only: + CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/devnet-finalize.sh --stage-only   (copy: ${log})"
    if ! "${REPO_ROOT}/devnet-finalize.sh" --stage-only 2>&1 | tee -a "${log}"; then
        bench_die "devnet-finalize.sh --stage-only failed (${log}) — no node has been started by this step; re-run with --from 7 once fixed (staged nodes are skipped)"
    fi
    running="$(tr -d '\r' < "${log}" | sed -nE 's/^[[:space:]]*RUNNING[[:space:]]+([^[:space:]]+).*/\1/p' | sort -u | tr '\n' ' ')"
    if [ -n "${running}" ] && [ -z "$(jq -c '.coordinated_start // empty' "$(bench_manifest)" 2>/dev/null || true)" ]; then
        # No coordinated start yet: each of these ran alone (a stage-only that failed after v2 finalize
        # started it), so no quorum formed and stopping it is safe. Left running it would skip its
        # pre-start config and step 8 would refuse it after the start, when no restart is allowed.
        bench_die "stage-only found running unit(s) before any coordinated start: ${running}— each ran alone (no quorum). On each: sudo systemctl stop telcoin; sudo systemctl reset-failed telcoin — then re-run with --from 7"
    fi
    [ -z "${running}" ] || bench_warn "stage-only found these units already running after the coordinated start: ${running}— their pre-start config is not repeated (it ran before that start); step 8 refuses a node whose start script lacks it, and step 9 checks what each runs"

    echo "    pre-start config: per node, one IAP session (bench_prestart_script; review: --print-prestart <instance>)$([ "${jobs}" -le 1 ] || printf ', up to %s at a time' "${jobs}")"
    STEP7_RUNNING="${running}"
    bench_node_jobs_run "${jobs}" "pre-start config (no node has been started; re-run with --from 7)" prestart_node "${!INSTANCE_NAMES[@]}"
    # Every node's probe is in the manifest now (side-by-side jobs' records were merged): one line, never fatal.
    bench_fsync_probe_summary "$(bench_manifest)" "${INSTANCE_NAMES[@]}"
    bench_host_probe_summary "$(bench_manifest)" "${INSTANCE_NAMES[@]}"

    log="${logs}/finalize-start-$(date -u +%Y%m%dT%H%M%SZ).log"
    echo "    start-all: + CONFIG_FILE=${CONFIG_FILE} ${REPO_ROOT}/devnet-finalize.sh --start-all   (copy: ${log})"
    rc=0
    "${REPO_ROOT}/devnet-finalize.sh" --start-all 2>&1 | tee -a "${log}" || rc=$?
    marker="$(tr -d '\r' < "${log}" | grep -E '^COORDINATED_START ' | tail -1 || true)"
    [ -z "${marker}" ] || coordinated_start_record "${marker}"
    [ -z "${marker}" ] || [ -z "${BENCH_ARM_FILE:-}" ] || prestart_arm_record
    [ "${rc}" -eq 0 ] || bench_die "devnet-finalize.sh --start-all exited ${rc} (${log}). Never restart a started node inside the epoch: read its START_AT and phase B lines, then re-run with --from 7 (running nodes are skipped) or tear down"
    [ -n "${marker}" ] || bench_die "devnet-finalize.sh --start-all printed no COORDINATED_START line (${log})"
    spread="$(printf '%s\n' "${marker}" | sed -nE 's/.* spread_secs=([0-9]+)( .*)?$/\1/p')"
    if [ "${spread:-0}" -gt "${START_SPREAD_MAX_SECS}" ]; then
        bench_die "the coordinated start spread ${spread} s > ${START_SPREAD_MAX_SECS} s (${marker}). A validator that starts > gc_depth (50) rounds after quorum sits out the epoch ('too new for max round 50'). Do not restart it inside the epoch: read the START_AT lines in ${log}, then wait for the next epoch boundary (step 8's fleet-ready check names who is out) or tear down"
    fi
    echo "    ✓ fleet started together: ${marker#COORDINATED_START }"
}

# obs_script <instance> <region> — step 8's remote script for one node. It holds no secret: the
# token is the one line on the session's stdin (step_8 pipes it in; tn_iap_ssh_cmd_stdin runs the
# script with `sudo bash -c`, see obs_remote_cmd), read once into a plain shell variable (never
# exported, never on a command line, no set -x), and handed to setup-observability.sh on ITS stdin
# (--token-stdin) by the printf builtin, nowhere else. bench-obs's Prometheus takes no ingest auth:
# the token is a throwaway (openssl rand -hex 16) that setup-observability.sh requires, and it is
# still kept off every command line and log as a real one would be.
#
# The metrics go to bench-obs (the run's own VM; obs-devnet is never touched) at
# http://<BENCH_OBS_INTERNAL_IP>:9090/api/v1/write over the VPC (default-allow-internal); a print
# (--print-obs-script) without the IP shows the placeholder bench-obs-internal-ip.invalid.
# setup-observability.sh derives TN_CHAIN from the node's NETWORK=devnet (DEVNET_CHAIN_NAME is
# readonly in tn-node-deployment), so left alone the node would remote-write
# network="devnet" chain="devnet" samples. To make that impossible rather than brief,
# setup-observability.sh is pointed at a black hole (127.0.0.1:9, refused) for both its metrics URL and
# its log push URL (logs stay off, TN_OBS_ENABLE_LOGS=0; no obs-devnet endpoint ever lands in the
# node's Alloy env); then, in the
# same session, bench-obs's /-/ready must answer from this node (else OBSCFG_FAIL, Alloy untouched and
# still on the black hole), Alloy is stopped, its WAL (which holds the devnet-labelled samples) is
# wiped, the env gets TN_CHAIN/TN_NODE/the bench-obs URL, and Alloy starts again. The first sample
# bench-obs ever sees from a bench node is network=bench.
#
# No node restart (D1): step 7's pre-start config put `--metrics 127.0.0.1:<port>` on the node
# command, so --enable-metrics finds it and changes nothing (tn-node-deployment
# lib/observability.sh _obs_flags_apply prints "Node already serves a metrics endpoint
# (--metrics)." and obs_ensure_reth_flags restarts only when a flag changed). The script refuses
# before the call when the flag is missing or .node-meta enables log shipping (either would make
# setup-observability.sh edit the start script and restart the node), and after it requires the
# done event with "ok":true, that phrase (ANSI colour stripped), the container's StartedAt unchanged
# and NRestarts=0. Anything else is OBSCFG_FAIL <instance> contract drift; there is no restart fallback.
# The quorum guard the lib would consult before a restart reads DEVNET_RPC_URL: set to the black hole
# (BENCH_GUARD_PUBLIC_RPC) so a bench node never asks the live devnet. Last line:
#   OBSCFG_OK <instance> restarted=none <setup-observability.sh's done event>
obs_script() {
    local inst="$1" region="$2" hold="http://127.0.0.1:9/bench-hold" ip url
    ip="${BENCH_OBS_INTERNAL_IP:-bench-obs-internal-ip.invalid}"
    url="http://${ip}:9090/api/v1/write"
    cat <<EOS
set -euo pipefail
# ERRTAIL: the last lines of setup-observability.sh's stderr once it has run (each OBSCFG_ERR on a failure)
ERRTAIL=""
fail() { [ -z "\${ERRTAIL}" ] || printf '%s' "\${ERRTAIL}" | sed 's/^/OBSCFG_ERR ${inst} /'; echo "OBSCFG_FAIL ${inst} \$*"; exit 1; }
# the token: this session's one stdin line, into a plain variable; nothing else reads stdin
TOKEN=""
IFS= read -r TOKEN || [ -n "\${TOKEN}" ] || fail "no ingest token on stdin"
TOKEN="\${TOKEN%\$'\\r'}"
exec </dev/null
[ -n "\${TOKEN}" ] || fail "empty ingest token on stdin"
S=/usr/local/libexec/telcoin/tn-start-docker
M=/etc/telcoin/.node-meta
# before: the node runs since the coordinated start, and nothing here may restart it
systemctl is-active --quiet telcoin || fail "telcoin is not active (step 7 start-all starts it)"
T0="\$(docker inspect -f '{{.State.StartedAt}}' telcoin 2>/dev/null || true)"
[ -n "\${T0}" ] || fail "no running telcoin container"
N0="\$(systemctl show -p NRestarts --value telcoin 2>/dev/null || true)"
[ "\${N0}" = 0 ] || fail "telcoin NRestarts=\${N0:-?} before setup-observability.sh, expected 0"
grep -v '^[[:space:]]*#' "\${S}" | grep -E -- '(^|[[:space:]])--metrics[[:space:]]+127\.0\.0\.1:[0-9]+' >/dev/null \\
    || fail "contract drift: no --metrics 127.0.0.1:<port> on the node command in \${S} (step 7's pre-start config sets it); not calling setup-observability.sh, which would add it and restart the node"
! grep -qx 'ENABLE_OBSERVABILITY=true' "\${M}" \\
    || fail "contract drift: \${M} has ENABLE_OBSERVABILITY=true; log shipping would add JSON log flags and restart the node"
rc=0
printf '%s\\n' "\${TOKEN}" | DEVNET_RPC_URL='${BENCH_GUARD_PUBLIC_RPC}' OBS_PUSH_URL='${hold}' OBS_METRICS_PUSH_URL='${hold}' \\
    '${TN_NODE_SCRIPTS_DIR}/setup-observability.sh' --json --enable-metrics --region '${region}' --token-stdin \\
    --push-url '${hold}' --metrics-push-url '${hold}' > /tmp/bench-obscfg.json 2>/tmp/bench-obscfg.err || rc=\$?
# its last 5 stderr lines (ANSI stripped) for a failure report; setup-observability.sh never prints the
# token, and a line that held it anyway is withheld (a bash pattern match: the token is in no argv)
while IFS= read -r l; do
    case "\${l}" in *"\${TOKEN}"*) l="(line withheld: it holds the ingest token)" ;; esac
    ERRTAIL="\${ERRTAIL}\${l}
"
done < <(sed 's/\x1b\[[0-9;]*[A-Za-z]//g' /tmp/bench-obscfg.err 2>/dev/null | tail -5 || true)
TOKEN=""
unset TOKEN
# after: the done event says ok, the node command already had --metrics, and the node did not restart
DONE="\$(grep -F '"event":"done"' /tmp/bench-obscfg.json 2>/dev/null | tail -1 || true)"
case "\${DONE}" in
    *'"ok":true'*) ;;
    *) fail "setup-observability.sh rc \${rc}, done event: \${DONE:-none}" ;;
esac
[ "\${rc}" = 0 ] || fail "setup-observability.sh exited \${rc} after a done ok:true event (\${DONE})"
T1="\$(docker inspect -f '{{.State.StartedAt}}' telcoin 2>/dev/null || true)"
N1="\$(systemctl show -p NRestarts --value telcoin 2>/dev/null || true)"
[ "\${T1}" = "\${T0}" ] || fail "the node restarted: container StartedAt \${T0} -> \${T1:-none}"
[ "\${N1}" = 0 ] || fail "telcoin NRestarts=\${N1:-?} after setup-observability.sh, expected 0"
sed 's/\x1b\[[0-9;]*[A-Za-z]//g' /tmp/bench-obscfg.err /tmp/bench-obscfg.json | grep -F 'Node already serves a metrics endpoint (--metrics).' >/dev/null \\
    || fail "contract drift: setup-observability.sh did not report 'Node already serves a metrics endpoint (--metrics).' (no restart fallback; see /tmp/bench-obscfg.err on the node)"
# bench-obs must answer this node before Alloy is pointed at it (gone, wrong IP, no internal path):
# a failure here leaves Alloy as setup-observability.sh left it, on the black hole
curl -sf --max-time 5 "http://${ip}:9090/-/ready" >/dev/null || fail "bench-obs unreachable"
systemctl stop telcoin-alloy.service
rm -rf /var/lib/telcoin-alloy/* 2>/dev/null || true
E=/etc/telcoin/alloy/telcoin-alloy.env
[ -f "\$E" ] || fail "no \$E"
sed -i -e 's/^TN_CHAIN=.*/TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}/' -e 's/^TN_NODE=.*/TN_NODE=${inst}/' \\
    -e 's#^OBS_METRICS_PUSH_URL=.*#OBS_METRICS_PUSH_URL=${url}#' "\$E"
grep -qx 'TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}' "\$E" && grep -qx 'TN_NODE=${inst}' "\$E" \\
    && grep -qx 'OBS_METRICS_PUSH_URL=${url}' "\$E" || fail "alloy env not rewritten"
systemctl start telcoin-alloy.service
systemctl is-active --quiet telcoin-alloy.service || fail "telcoin-alloy not active"
echo "OBSCFG_OK ${inst} restarted=none \${DONE}"
EOS
}

# obs_remote_cmd <instance> <region> — the remote command of step 8's session: obs_script, base64
# (so no quote of it is parsed twice; lessons 2026-10-06), decoded on the node and run by
# `sudo bash -c`, which inherits the session's stdin: the token line (tn_iap_ssh_cmd_stdin, -T).
# Its $0 is bench-obscfg (the VM is bench-obs; the session is not).
obs_remote_cmd() {
    local b64
    b64="$(obs_script "$1" "$2" | base64 | tr -d '\n')"
    printf 'sudo bash -c "$(printf %%s %s | base64 -d)" bench-obscfg' "${b64}"
}

# obs_print <instance> — --print-obs-script: the session as step 8 runs it, the token replaced by
# PLACEHOLDER-TOKEN (comments, then the script; `| bash -n` parses it). The bench-obs IP is
# BENCH_OBS_INTERNAL_IP when set, else the placeholder bench-obs-internal-ip.invalid (no gcloud).
obs_print() {
    local i
    i="$(bench_index_of "$1")" || bench_die "$1 is not a bench instance"
    cat <<EOH
# step 8 session for $1 (--print-obs-script). Sent as:
#   printf '%s\n' PLACEHOLDER-TOKEN | tn_iap_ssh_cmd_stdin $1 ${ZONES[$i]} 'sudo bash -c "\$(printf %s <base64 of the script below> | base64 -d)" bench-obscfg'
# PLACEHOLDER-TOKEN stands for the token (step 8: openssl rand -hex 16; bench-obs takes no ingest auth):
# the session's only stdin line, read into TOKEN below and piped to setup-observability.sh --token-stdin;
# it is never on a command line or in an environment.
# bench-obs: ${BENCH_OBS_INTERNAL_IP:-bench-obs-internal-ip.invalid} (BENCH_OBS_INTERNAL_IP, else the placeholder)
EOH
    obs_script "$1" "$(tn_region_from_zone "${ZONES[$i]}")"
}

step_8() {
    echo ">>> Step 8: per-node observability, metrics only → bench-obs, labelled network=${BENCH_PROM_NETWORK_LABEL} before the first push; no node restarts"
    # obs-devnet is devnet's and is never touched: no create-obs-instance.sh, no devnet-observability.sh
    # (it cannot relabel inside the setup session either; see obs_script), no obs-devnet secret.
    local token i inst out line
    # bench-obs up: created if absent (an --only 8 after it was lost), booted, Prometheus + Grafana
    # brought up, the two forwards (manifest.obs). Then OBS_METRICS_PUSH_URL from manifest.obs.internal_ip.
    obs_or_die "bench-obs is not up (above) — re-run with --only 8, then your segment (--from 10 --to 12 or --from 13 --to 15)" \
        bench_obs_ensure
    bench_obs_urls
    echo "    metrics -> ${OBS_METRICS_PUSH_URL}"
    bench_fleet_ready 0 step8 \
        || bench_die "step 8: not every validator is CvvActive (above; manifest.fleet_ready). A validator that started too late after the coordinated start sits out until the next epoch boundary, and no restart helps inside the epoch: resume with --from 8 after the boundary, or tear down"
    # setup-observability.sh needs a token; bench-obs takes no ingest auth, so it is a throwaway, and
    # it still goes on the session's stdin only.
    token="$(openssl rand -hex 16)" || token=""
    [ -n "${token}" ] || bench_die "openssl rand gave no token for setup-observability.sh"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        echo "    ${inst}: setup-observability.sh --enable-metrics --token-stdin (token on stdin only) + bench-obs ready check + same-session relabel; no restart"
        out="$(printf '%s\n' "${token}" | tn_iap_ssh_cmd_stdin "${inst}" "${ZONES[$i]}" "$(obs_remote_cmd "${inst}" "$(tn_region_from_zone "${ZONES[$i]}")")" 2>&1 | tr -d '\r' || true)"
        printf '%s\n' "${out}" | grep -E 'OBSCFG_(OK|FAIL|ERR)' | cut -c1-300 | sed 's/^/      /' || true
        line="$(printf '%s\n' "${out}" | grep -F "OBSCFG_OK ${inst} restarted=none " | tail -1 || true)"
        [ -n "${line}" ] || bench_die "observability failed on ${inst} (OBSCFG_FAIL above; the whole script: --print-obs-script ${inst})"
    done
    unset token
}

# postconfig_readback — step 9's readback for the POSTCFG_OK line: pv <key> reads a top-level value
# of the node's parameters.yaml (P = <DATA_DIR from .node-meta>/parameters.yaml), ms turns it into ms
# (- when absent); arg <flag-regex> reads a flag's value off the running container's command line
# (docker inspect telcoin; "" when not set): rf / rff / rmf are its --log.stdout.filter,
# --log.file.filter and --log.file.max-files. The two filters must be the same.
postconfig_readback() {
    cat <<'EOS'
# 3b. what the node runs with: its parameters.yaml, and the container's command line
pv() { awk -v k="$1" 'index($0, k ":") == 1 { v = substr($0, length(k) + 2); sub(/^[ \t]+/, "", v); sub(/[ \t]*#.*$/, "", v); gsub(/["\047]/, "", v); print v; exit }' "$P"; }
ms() { case "$1" in '') echo - ;; *ms) echo "${1%ms}" ;; *s) awk -v s="${1%s}" 'BEGIN { printf "%d\n", s * 1000 }' ;; *) echo "?" ;; esac; }
CMDL="$(docker inspect -f '{{.Path}} {{join .Args " "}}' telcoin 2>/dev/null || true)"
[ -n "$CMDL" ] || fail "docker inspect telcoin gave no command line"
arg() { printf '%s\n' "$CMDL" | sed -nE "s/.* $1 ([^[:space:]]+).*/\1/p" | tail -1 || true; }
rf="$(arg '--log\.stdout\.filter')"; rff="$(arg '--log\.file\.filter')"; rmf="$(arg '--log\.file\.max-files')"
[ "$rff" = "$rf" ] || fail "running --log.file.filter '$rff' differs from --log.stdout.filter '$rf'"
pthr="$(pv header_num_of_batches_threshold)"
EOS
}

# postconfig_script <instance> — step 9's remote script for one node (piped to `sudo bash -s`).
# Verify only: step 7 configured the node while its unit was stopped (pre-start config) and started
# it with the fleet (start-all), so nothing here edits the start script, parameters.yaml or the unit,
# and nothing restarts the node; it fails when the unit has restarted (NRestarts) or the container
# changes while it runs. The RPC and the logs are polled with a deadline (POSTCFG_WAIT_SECS) and never
# trip set -e/pipefail; only the assertions fail the session.
# Its last line: POSTCFG_OK <inst> chain=<hex> block=<hex|?> ip=<ip> progress=<text with spaces>
#   sha=<git sha> mhd=<ms|?> nhd=<ms|?> mbd=<ms|?> vt=<ms|?> forks=<label|?>
#   max=<ms|-> min=<ms|-> batch=<ms|-> thr=<n|-> vote=<ms|-> filter=<filter|-> maxfiles=<n|-> back=-
# where sha / mhd / nhd / mbd / vt / forks come from the running container's boot lines (`docker logs
# --since` its StartedAt: the `telcoin-network <ver> (<sha>) starting` line, "Max|Min header delay set
# to N ms", "Max batch delay set to N ms", "... vote timeout set to N ms" when logged, the
# fork-schedule line labelled by report/provenance.py's rules); max / min / batch / thr / vote are read
# from <DATA_DIR from /etc/telcoin/.node-meta>/parameters.yaml (- = not in the file), filter / maxfiles
# from the running container's command line (- = not set), and back is "-" (no restart, so no
# downtime to report). step_9 compares them with the run's manifest and this node's overrides.
postconfig_script() {
    local inst="$1" b64 t0 lf="" sws="" pss="" arm nbs=""
    bench_index_of "${inst}" >/dev/null || bench_die "postconfig_script: ${inst} is not a bench instance"
    b64="$(base64 < "${DIR}/node-sampler.sh" | tr -d '\n')"
    # The first-start arm (manifest.param_arms via prestart): the `node switches` line of this start,
    # printed for step 9 to compare with the arm. From the container's log, else from the unit file's
    # block after its last 'starting' line (the rotation fallback of prov). Without such an arm: nothing.
    arm="$(prestart_arm_json | jq -r '.name // empty' 2>/dev/null || true)"
    if [ -n "${arm}" ]; then
        sws="
# 4b. the \`node switches\` line of this start (the fleet started in arm ${arm}; step 9 compares it)
swl=\"\$({ docker logs telcoin --since \"\$STARTED\" 2>&1 || true; } | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' | grep -F 'node switches' | tail -n 1 || true)\"
[ -n \"\$swl\" ] || swl=\"\$({ ufgen | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' | awk 'tolower(\$0) ~ /telcoin-network[ \\t]+[^ \\t]+[ \\t]+\\([^() \\t]+\\)[ \\t]+starting/ { n = 0 } { b[++n] = \$0 } END { for (i = 1; i <= n; i++) print b[i] }' | grep -F 'node switches' | tail -n 1; } || true)\"
echo \"POSTCFG_SWITCHES ${inst} \${swl:--}\""
    fi
    # Bench 7: the `node build:` line of this start (the coordinated start: the container's StartedAt), when
    # the probed image carries it (manifest node_probe.strings), printed for step 9 to record. From the
    # container's log, else from the unit file's block after its last 'starting' line, as above.
    if node_build_expected; then
        nbs="
# 4c. the \`node build:\` line of this start (step 9 records it: node_startup[].node_build, node_build)
nbl=\"\$({ docker logs telcoin --since \"\$STARTED\" 2>&1 || true; } | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' | grep -F 'node build: faucet=' | tail -n 1 || true)\"
[ -n \"\$nbl\" ] || nbl=\"\$({ ufgen | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' | awk 'tolower(\$0) ~ /telcoin-network[ \\t]+[^ \\t]+[ \\t]+\\([^() \\t]+\\)[ \\t]+starting/ { n = 0 } { b[++n] = \$0 } END { for (i = 1; i <= n; i++) print b[i] }' | grep -F 'node build: faucet=' | tail -n 1; } || true)\"
echo \"POSTCFG_BUILD ${inst} \${nbl:--}\""
    fi
    # BENCH_PERSIST_SAMPLER=1: the persist sampler and its folio census, a root unit beside the node sampler.
    if [ "${BENCH_PERSIST_SAMPLER:-0}" = 1 ]; then
        pss="
# 6b. persist sampler (BENCH_PERSIST_SAMPLER=1; systemd, root: the folio census reads /proc/kpageflags)
echo '$(base64 < "${DIR}/node-persist-sampler.sh" | tr -d '\n')' | base64 -d > /usr/local/bin/bench-persist-sampler.sh
chmod 0755 /usr/local/bin/bench-persist-sampler.sh
echo '$(base64 < "${DIR}/tools/folio-census.py" | tr -d '\n')' | base64 -d > /usr/local/bin/bench-folio-census.py
chmod 0755 /usr/local/bin/bench-folio-census.py
cat > /etc/systemd/system/bench-persist-sampler.service <<'UNIT'
[Unit]
Description=benchmark persist sampler (persist CSV every 30 s, folio census every 900 s -> /var/lib/bench-sampler)
After=docker.service telcoin.service
[Service]
Type=simple
ExecStart=/usr/local/bin/bench-persist-sampler.sh
Restart=always
RestartSec=10
Nice=10
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now bench-persist-sampler.service
systemctl is-active --quiet bench-persist-sampler.service || fail \"persist sampler not active\""
    fi
    # Progress counts from the coordinated start (step 7's due time), else from the container's start.
    t0="$(jq -r '.coordinated_start.due // empty' "$(bench_manifest)" 2>/dev/null || true)"
    case "${t0}" in *[!0-9]*) t0="" ;; esac
    [ -z "${BENCH_NODE_LOG_FILTER:-}" ] || lf="
[ \"\$rf\" = '${BENCH_NODE_LOG_FILTER}' ] && [ \"\$rmf\" = '${BENCH_NODE_LOG_MAX_FILES}' ] \\
    || fail \"running --log.stdout.filter/--log.file.filter '\$rf' --log.file.max-files '\$rmf', expected '${BENCH_NODE_LOG_FILTER}' / ${BENCH_NODE_LOG_MAX_FILES} (BENCH_NODE_LOG_FILTER; step 7 pre-start config)\""
    cat <<EOS
set -euo pipefail
fail() { echo "POSTCFG_FAIL \$*"; exit 1; }
# 1. the node runs since the coordinated start: unit active and never restarted, one container
M=/etc/telcoin/.node-meta
[ -f "\$M" ] || fail "no \$M (not a tn-node-deployment v2 node)"
meta() { [ "\$(grep -c -E "^\$1=" "\$M" || true)" = 1 ] || return 1; grep -E "^\$1=" "\$M" | sed -e 's/^[^=]*=//' -e 's/\r\$//'; }
systemctl is-active --quiet telcoin || fail "telcoin is not active (step 7 start-all starts it)"
NR="\$(systemctl show -p NRestarts --value telcoin 2>/dev/null || true)"
[ "\$NR" = 0 ] || fail "telcoin NRestarts=\${NR:-?}, expected 0 (no restart after the coordinated start)"
STARTED="\$(docker inspect -f '{{.State.StartedAt}}' telcoin 2>/dev/null || true)"
[ -n "\$STARTED" ] || fail "no running telcoin container"
# 2. its datadir from .node-meta DATA_DIR (never from the start script); parameters.yaml there
D="\$(meta DATA_DIR || true)"; D="\${D%/}"
[ -n "\$D" ] || fail "no single DATA_DIR line in \$M"
P="\$D/parameters.yaml"
[ -f "\$P" ] || fail "no \$P"
MP="\$(meta METRICS_PORT || true)"; MP="\${MP:-9101}"
case "\$MP" in *[!0-9]*) fail "METRICS_PORT '\$MP' in \$M is not a port number" ;; esac
MP=\$((10#\$MP))
# the unit's append file (StandardOutput=append:): every container run since finalize, uncapped
NL="\$(meta NODE_LOG_DIR || true)"; NL="\${NL:-/var/log/telcoin}"
UF="\$(sed -n 's/^StandardOutput=append://p' /etc/systemd/system/telcoin.service 2>/dev/null | tail -1 || true)"
UF="\${UF:-\$NL/telcoin.log}"
# 3. alloy labels were set in step 8's session; assert they are still bench labels
E=/etc/telcoin/alloy/telcoin-alloy.env
grep -qx 'TN_CHAIN=${BENCH_PROM_NETWORK_LABEL}' "\$E" && grep -qx 'TN_NODE=${inst}' "\$E" || fail "alloy env lacks bench labels (re-run step 8)"
$(postconfig_readback)
# 3c. what step 7's pre-start config put on the node command: RPC and WS on all interfaces
#     (blasters reach 8545 on the internal IP; no public rule admits it), metrics on loopback
[ "\$(arg '--http\.addr')" = 0.0.0.0 ] || fail "running --http.addr is '\$(arg '--http\.addr')', expected 0.0.0.0"
[ "\$(arg '--ws\.addr')" = 0.0.0.0 ] || fail "running --ws.addr is '\$(arg '--ws\.addr')', expected 0.0.0.0"
[ "\$(arg '--metrics')" = "127.0.0.1:\$MP" ] || fail "running --metrics is '\$(arg '--metrics')', expected 127.0.0.1:\$MP (.node-meta METRICS_PORT, default 9101)"${lf}
# 4. it serves chain ${CHAIN_ID} on the INTERNAL IP and consensus is progressing. An idle TN chain
#    stays at block 0 (the engine skips empty non-epoch-closing consensus outputs), so progress =
#    eth_blockNumber increased OR this node's own log shows consensus progress since the coordinated
#    start: validators log 'subdag committed' / 'quorum reached', an observer (follower) logs
#    'got new consensus' / 'catching up consensus blocks'.
T0='${t0}'
[ -n "\$T0" ] || T0="\$(date -d "\$STARTED" +%s 2>/dev/null || date +%s)"
IP=\$(curl -sf -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/ip || true)
[ -n "\$IP" ] || fail "no internal IP from the metadata server"
# A refused or slow RPC is retried: curl's failure is swallowed, empty = retry.
rpc() { { curl -s --max-time 3 -H 'content-type: application/json' --data "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"\$1\",\"params\":[]}" "http://\${IP}:8545" || true; } | sed -n 's/.*"result":"\([^"]*\)".*/\1/p' || true; }
# consensus lines in the node's docker log in the last 45 s, never before the coordinated start
commits() {
    local now since
    now=\$(date +%s); since=\$(( now - 45 )); [ "\$since" -ge "\$T0" ] || since="\$T0"
    { docker logs telcoin --since "\$since" 2>&1 || true; } | grep -c -E 'subdag committed|quorum reached|got new consensus|catching up consensus blocks|skipping execution for empty|executing consensus output' || true
}
# the running binary's boot lines (logged once, at start; read from the container's StartedAt): git
# sha, consensus delays, vote timeout (later builds only), fork schedule — labelled as
# report/provenance.py does: a "fork schedule (adiri)" line -> adiri-schedule; a "fork schedule:" line
# listing subsecond_timestamp before "active from genesis" -> subsecond-from-genesis; any other
# "fork schedule:" line -> pre-subsecond; none -> ?. Each pass fills only fields still empty,
# so a later read (say a transient empty docker logs) never blanks what an earlier one found.
# The container's json-file log is capped (50 MB x 3) and step 9 runs 30-55 min after the start, so
# the boot block may have rotated out of it. Then the source is the unit's append file (UF), which
# holds the stage-only run and then this one: its lines from the LAST 'starting' line on, so every
# field comes from this container's run. logrotate may have moved that block on too (copytruncate,
# delaycompress): the first of UF, UF.1, UF.2.gz that holds a 'starting' line is read (ufgen).
sha=""; mhd=""; nhd=""; mbd=""; vt=""; forks=""; FB=""
ufgen() {
    local g
    for g in "\$UF" "\$UF.1"; do
        if LC_ALL=C grep -aqiE 'telcoin-network[[:space:]]+[^[:space:]]+[[:space:]]+\([^()[:space:]]+\)[[:space:]]+starting' "\$g" 2>/dev/null; then
            cat "\$g"; return 0
        fi
    done
    zcat "\$UF.2.gz" 2>/dev/null || true
}
delay() { printf '%s\n' "\$1" | grep -ioE "\$2 set to [0-9]+ ?ms" | tail -1 | grep -oE '[0-9]+' | head -1 || true; }
prov() {
    local L fl
    if [ -z "\$FB" ]; then
        L="\$({ docker logs telcoin --since "\$STARTED" 2>&1 || true; } | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' || true)"
        [ -n "\$sha" ] || sha="\$(printf '%s\n' "\$L" | sed -nE 's/.*telcoin-network[[:space:]]+[^[:space:]]+[[:space:]]+\(([^()[:space:]]+)\)[[:space:]]+starting.*/\1/p' | tail -1 || true)"
        [ -n "\$sha" ] || FB=1   # rotated out: from now on every field comes from the unit file
    fi
    if [ -n "\$FB" ]; then
        L="\$({ ufgen | LC_ALL=C grep -aiE 'telcoin-network|delay set to|vote timeout set to|fork schedule' || true; } \\
            | sed 's/\x1b\[[0-9;]*[A-Za-z]//g' \\
            | awk 'tolower(\$0) ~ /telcoin-network[ \t]+[^ \t]+[ \t]+\([^() \t]+\)[ \t]+starting/ { n = 0 } { b[++n] = \$0 } END { for (i = 1; i <= n; i++) print b[i] }' || true)"
        [ -n "\$sha" ] || sha="\$(printf '%s\n' "\$L" | sed -nE 's/.*telcoin-network[[:space:]]+[^[:space:]]+[[:space:]]+\(([^()[:space:]]+)\)[[:space:]]+starting.*/\1/p' | tail -1 || true)"
    fi
    [ -n "\$mhd" ] || mhd="\$(delay "\$L" 'max header delay')"
    [ -n "\$nhd" ] || nhd="\$(delay "\$L" 'min header delay')"
    [ -n "\$mbd" ] || mbd="\$(delay "\$L" 'max batch delay')"
    [ -n "\$vt" ] || vt="\$(delay "\$L" 'vote timeout')"
    [ -z "\$forks" ] || return 0
    fl="\$(printf '%s\n' "\$L" | grep -iE 'fork schedule[[:space:]]*(\(adiri\)|:)' | tail -1 || true)"
    if [ -z "\$fl" ]; then forks=""
    elif printf '%s\n' "\$fl" | grep -qiE 'fork schedule[[:space:]]*\(adiri\)'; then forks=adiri-schedule
    elif printf '%s\n' "\$fl" | grep -qiE 'subsecond_timestamp[[:alnum:]_[:space:],]*active from genesis'; then forks=subsecond-from-genesis
    else forks=pre-subsecond; fi
}
booted() { [ -n "\$sha" ] && [ -n "\$mhd" ] && [ -n "\$nhd" ] && [ -n "\$mbd" ]; }
cid=""; b0=""; b=""; how=""; n=0
deadline=\$(( \$(date +%s) + \${POSTCFG_WAIT_SECS:-300} ))
while [ "\$(date +%s)" -lt "\$deadline" ]; do
    if [ -z "\$how" ]; then
        cid="\$(rpc eth_chainId)"
        if [ "\$cid" = "${CHAIN_ID_HEX}" ]; then
            b="\$(rpc eth_blockNumber)"
            if [ -n "\$b" ]; then
                if [ -z "\$b0" ]; then b0="\$b"; elif [ "\$((b))" -gt "\$((b0))" ]; then how="blocks \$((b0))->\$((b))"; fi
            fi
            if [ -z "\$how" ]; then
                n="\$(commits)"
                if [ "\${n:-0}" -ge 1 ]; then how="consensus log (\${n} subdag committed/quorum reached lines in the last 45 s)"; fi
            fi
        fi
    fi
    booted || prov
    if [ -n "\$how" ] && booted; then break; fi
    sleep 5
done
[ "\$cid" = "${CHAIN_ID_HEX}" ] || fail "eth_chainId on \${IP}:8545 = '\$cid', expected ${CHAIN_ID_HEX}"
[ -n "\$how" ] || fail "consensus not progressing: block \${b0:-none} -> \${b:-none} and no 'subdag committed|quorum reached' in docker logs since the coordinated start"
prov   # once more: lines logged after the last poll (the fork schedule, a vote timeout)
[ -n "\$sha" ] || fail "no 'telcoin-network <version> (<sha>) starting' line in docker logs since the container started (\$STARTED) nor in the unit file \$UF (nor its .1 / .2.gz generation)"${sws}${nbs}
# 5. still the same container and no restart while this ran
[ "\$(docker inspect -f '{{.State.StartedAt}}' telcoin 2>/dev/null || true)" = "\$STARTED" ] || fail "the telcoin container restarted while step 9 ran"
# 6. node sampler (systemd, root)
echo '${b64}' | base64 -d > /usr/local/bin/bench-node-sampler.sh
chmod 0755 /usr/local/bin/bench-node-sampler.sh
cat > /etc/systemd/system/bench-node-sampler.service <<'UNIT'
[Unit]
Description=benchmark node sampler (CSV every 30 s -> /var/lib/bench-sampler)
After=docker.service telcoin.service
[Service]
Type=simple
ExecStart=/usr/local/bin/bench-node-sampler.sh
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now bench-node-sampler.service
systemctl is-active --quiet bench-node-sampler.service || fail "sampler not active"${pss}
echo "POSTCFG_OK ${inst} chain=\$cid block=\${b:-?} ip=\${IP} progress=\${how} sha=\${sha} mhd=\${mhd:-?} nhd=\${nhd:-?} mbd=\${mbd:-?} vt=\${vt:-?} forks=\${forks:-?} max=\$(ms "\$(pv max_header_delay)") min=\$(ms "\$(pv min_header_delay)") batch=\$(ms "\$(pv max_batch_delay)") thr=\${pthr:--} vote=\$(ms "\$(pv vote_timeout)") filter=\${rf:--} maxfiles=\${rmf:--} back=-"
EOS
}

# node_build_expected — rc 0 when the run's probed image carries the `node build:` line (manifest
# node_probe.strings counts "node build: faucet=" above 0): step 9 then reads and records it. An image probed
# before bench 7's contract has no such count, and step 9 is what it was.
node_build_expected() {
    [ "$(jq -r '(.node_probe.strings["node build: faucet="] // 0) > 0' "$(bench_manifest)" 2>/dev/null || true)" = true ]
}

# node_build_json <line> — the `node build: faucet=<bool> adiri=<bool> chain_id=<n> genesis_hash=<0x..>` line as
# {faucet, adiri, chain_id, genesis_hash}, compact; "null" for "-", an empty line or one that does not parse.
node_build_json() {
    local l="$1" f a c g
    f="$(printf '%s\n' "${l}" | sed -nE 's/.*node build: faucet=(true|false)( .*)?$/\1/p' | tail -n 1)"
    a="$(printf '%s\n' "${l}" | sed -nE 's/.* adiri=(true|false)( .*)?$/\1/p' | tail -n 1)"
    c="$(printf '%s\n' "${l}" | sed -nE 's/.* chain_id=([0-9]{1,20})( .*)?$/\1/p' | tail -n 1)"
    g="$(printf '%s\n' "${l}" | sed -nE 's/.* genesis_hash=(0x[0-9a-fA-F]{64})([^0-9a-zA-Z].*)?$/\1/p' | tail -n 1)"
    if [ -z "${f}" ] || [ -z "${a}" ] || [ -z "${c}" ] || [ -z "${g}" ]; then echo null; return 0; fi
    jq -n -c --argjson f "${f}" --argjson a "${a}" --argjson c "${c}" --arg g "${g}" \
        '{faucet: $f, adiri: $a, chain_id: $c, genesis_hash: ($g | ascii_downcase)}'
}

# node_build_record — after every node's step 9: manifest.node_build = the one node_build all nodes recorded
# (node_startup[].node_build), null with a warning when none did; dies when two nodes differ (a different
# build or genesis in one fleet). A no-op unless node_build_expected.
node_build_record() {
    local m insts got n
    node_build_expected || return 0
    m="$(bench_manifest)"
    insts="$(printf '%s\n' "${INSTANCE_NAMES[@]}" | jq -R -s -c 'split("\n") | map(select(length > 0))')" || bench_die "cannot list the fleet"
    got="$(jq -c --argjson insts "${insts}" '[$insts[] as $i | .node_startup[$i].node_build // empty] | unique' "${m}")" \
        || bench_die "cannot read node_startup[].node_build from ${m}"
    n="$(printf '%s' "${got}" | jq 'length')"
    case "${n}" in
        0) bench_manifest_jq '.node_build = null' || bench_die "could not record node_build in ${m}"
           bench_warn "no node logged a parsable 'node build:' line since its start: manifest.node_build is null" ;;
        1) bench_manifest_jq --argjson b "$(printf '%s' "${got}" | jq -c '.[0]')" '.node_build = $b' \
               || bench_die "could not record node_build in ${m}"
           echo "    ✓ manifest.node_build: $(printf '%s' "${got}" | jq -c '.[0]')" ;;
        *) bench_die "the nodes logged ${n} different 'node build:' lines (node_startup[].node_build in ${m}): ${got}" ;;
    esac
}

# postcfg_field <POSTCFG_OK line> <key> — the value of its last " <key>=<value>" ("" if absent).
postcfg_field() { printf '%s\n' "$1" | sed -n "s/.* $2=\([^ ]*\).*/\1/p" | tail -1; }

# step9_node_check <node-index> <POSTCFG_OK line> <sha> <forks> — merge the node's boot lines and
# readback into manifest.node_startup[<inst>] (sha mhd nhd mbd vt forks from the boot lines; params
# {max_header_delay_ms, min_header_delay_ms, max_batch_delay_ms, header_num_of_batches_threshold,
# vote_timeout_ms} from its parameters.yaml; log_filter / log_max_files from its command line), then
# die on the first value that differs from what this node must run (the sha matches when the node's
# starts with the expected one: a full 40-hex expectation must match in full). Delays and the
# threshold are this node's (run_expect <field> <node-index>: an override, else the manifest's). vt is
# compared only with a vote_timeout override; the log fields only when BENCH_NODE_LOG_FILTER is set.
step9_node_check() {
    local idx="$1" line="$2" w_sha="$3" w_forks="$4" inst sha mhd nhd mbd vt forks pmax pmin pbatch pthr pvote lf lmf o
    local w_mhd w_nhd w_mbd w_vt w_thr src
    inst="${INSTANCE_NAMES[$idx]}"
    w_mhd="$(run_expect mhd "${idx}")"; w_nhd="$(run_expect nhd "${idx}")"; w_mbd="$(run_expect mbd "${idx}")"
    w_vt="$(run_expect vt "${idx}")"; w_thr="$(run_expect thr "${idx}")"
    sha="$(postcfg_field "${line}" sha | tr 'ABCDEF' 'abcdef')"
    mhd="$(postcfg_field "${line}" mhd)"; nhd="$(postcfg_field "${line}" nhd)"; mbd="$(postcfg_field "${line}" mbd)"
    vt="$(postcfg_field "${line}" vt)"; forks="$(postcfg_field "${line}" forks)"
    pmax="$(postcfg_field "${line}" max)"; pmin="$(postcfg_field "${line}" min)"; pbatch="$(postcfg_field "${line}" batch)"
    pthr="$(postcfg_field "${line}" thr)"; pvote="$(postcfg_field "${line}" vote)"
    lf="$(postcfg_field "${line}" filter)"; lmf="$(postcfg_field "${line}" maxfiles)"
    o="$(jq -n -c --arg sha "${sha}" --arg mhd "${mhd}" --arg nhd "${nhd}" \
        --arg mbd "${mbd}" --arg vt "${vt}" --arg forks "${forks}" --arg pmax "${pmax}" --arg pmin "${pmin}" \
        --arg pbatch "${pbatch}" --arg pthr "${pthr}" --arg pvote "${pvote}" --arg lf "${lf}" --arg lmf "${lmf}" '
        def num: if test("^[0-9]+$") then tonumber else null end;
        def str: if . == "" or . == "?" or . == "-" then null else . end;
        {sha: ($sha|str), mhd: ($mhd|num), nhd: ($nhd|num), mbd: ($mbd|num), vt: ($vt|num), forks: ($forks|str),
         params: {max_header_delay_ms: ($pmax|num), min_header_delay_ms: ($pmin|num),
                  max_batch_delay_ms: ($pbatch|num), header_num_of_batches_threshold: ($pthr|num),
                  vote_timeout_ms: ($pvote|num)},
         log_filter: ($lf|str), log_max_files: ($lmf|num)}')" || bench_die "${inst}: cannot build its node_startup record"
    node_startup_merge "${inst}" "${o}" || bench_die "${inst}: could not record node_startup in $(bench_manifest)"
    local stop="— stopping step 9 (it restarts nothing; the node keeps running)"
    src="manifest consensus_parameters"
    [ -z "$(bench_node_overrides "${idx}")" ] || src="${src} + BENCH_NODE_PARAM_OVERRIDES"
    case "${sha}" in
        "${w_sha}"?*|"${w_sha}") ;;
        *) bench_die "${inst}: boot sha = ${sha:-<none>}, expected ${w_sha} (manifest node_git_sha) ${stop}" ;;
    esac
    [ "${mhd}" = "${w_mhd}" ] || bench_die "${inst}: max_header_delay = ${mhd:-<none>} ms, expected ${w_mhd} ms (${src}) ${stop}"
    [ "${nhd}" = "${w_nhd}" ] || bench_die "${inst}: min_header_delay = ${nhd:-<none>} ms, expected ${w_nhd} ms (${src}) ${stop}"
    [ "${mbd}" = "${w_mbd}" ] || bench_die "${inst}: max_batch_delay = ${mbd:-<none>} ms, expected ${w_mbd} ms (${src}) ${stop}"
    [ "${forks}" = "${w_forks}" ] || bench_die "${inst}: fork schedule = ${forks:-<none>}, expected ${w_forks} (manifest node_fork_schedule) ${stop}"
    # The node's parameters.yaml must say what its boot lines say.
    [ "${pmax}" = "${w_mhd}" ] && [ "${pmin}" = "${w_nhd}" ] && [ "${pbatch}" = "${w_mbd}" ] \
        || bench_die "${inst}: parameters.yaml has max/min header delay ${pmax:-?}/${pmin:-?} ms and max batch delay ${pbatch:-?} ms, expected ${w_mhd}/${w_nhd}/${w_mbd} ms (${src}) ${stop}"
    [ -z "${w_thr}" ] || [ "${pthr}" = "${w_thr}" ] \
        || bench_die "${inst}: parameters.yaml has header_num_of_batches_threshold ${pthr:-?}, expected ${w_thr} (${src}) ${stop}"
    if [ -n "${w_vt}" ]; then
        [ "${pvote}" = "${w_vt}" ] || bench_die "${inst}: parameters.yaml has vote_timeout ${pvote:-?} ms, expected ${w_vt} ms (BENCH_NODE_PARAM_OVERRIDES) ${stop}"
        case "${vt}" in ''|'?') ;; *) [ "${vt}" = "${w_vt}" ] || bench_die "${inst}: vote_timeout = ${vt} ms at boot, expected ${w_vt} ms (BENCH_NODE_PARAM_OVERRIDES) ${stop}" ;; esac
    fi
    if [ -n "${BENCH_NODE_LOG_FILTER:-}" ]; then
        [ "${lf}" = "${BENCH_NODE_LOG_FILTER}" ] && [ "${lmf}" = "${BENCH_NODE_LOG_MAX_FILES}" ] \
            || bench_die "${inst}: the node runs --log.stdout.filter ${lf:-<none>} --log.file.max-files ${lmf:-<none>}, expected ${BENCH_NODE_LOG_FILTER} / ${BENCH_NODE_LOG_MAX_FILES} (BENCH_NODE_LOG_FILTER) ${stop}"
    fi
    echo "      ✓ ${inst}: boot git ${sha}, delays ${mhd}/${nhd}/${mbd} ms, vote timeout ${vt:-?}, forks ${forks}, yaml threshold ${pthr}, log filter ${lf} — as expected"
}

# step9_node <index> — step 9 on one node: its verify session (postconfig_script, one IAP session),
# then step9_node_check against STEP9_W_SHA / STEP9_W_FORKS; dies on the first problem.
STEP9_W_SHA=""; STEP9_W_FORKS=""; STEP9_ARM=""
step9_node() {
    local i="$1" inst="${INSTANCE_NAMES[$1]}" out line sl why bl nb
    echo "    ${inst}: running args (http/ws 0.0.0.0, --metrics, log filter), parameters.yaml$( [ -z "$(bench_node_overrides "${i}")" ] || printf ' (%s)' "$(bench_node_overrides "${i}" | paste -sd, -)" ), alloy labels, chain-id ${CHAIN_ID_HEX} on internal IP, progress since the coordinated start, boot lines + readback, sampler"
    out="$(postconfig_script "${inst}" | tn_iap_ssh_stdin "${inst}" "${ZONES[$i]}" 2>&1 | tr -d '\r' || true)"
    printf '%s\n' "${out}" | grep -E 'POSTCFG_(OK|FAIL)' | sed 's/^/      /' || true
    line="$(printf '%s\n' "${out}" | grep -F "POSTCFG_OK ${inst} " | tail -1 || true)"
    [ -n "${line}" ] || bench_die "post-config verification failed on ${inst} (POSTCFG_FAIL above; the whole script: --print-postconfig ${inst}) — stopping step 9; nothing was restarted"
    step9_node_check "${i}" "${line}" "${STEP9_W_SHA}" "${STEP9_W_FORKS}"
    if node_build_expected; then
        bl="$(printf '%s\n' "${out}" | sed -n "s/^POSTCFG_BUILD ${inst} //p" | tail -n 1)"
        nb="$(node_build_json "${bl}")" || nb=null
        node_startup_merge "${inst}" "{\"node_build\":${nb}}" || bench_die "${inst}: could not record node_startup in $(bench_manifest)"
        echo "      $([ "${nb}" = null ] && printf '·' || printf '✓') ${inst}: node build ${nb} ('node build:' line of this start)"
    fi
    [ -n "${STEP9_ARM}" ] || return 0
    # The fleet started in a first-start arm: this start's `node switches` line must show it, by value.
    sl="$(printf '%s\n' "${out}" | sed -n "s/^POSTCFG_SWITCHES ${inst} //p" | tail -n 1)"
    why="$(bench_switch_readback "$(printf '%s' "${STEP9_ARM}" | jq -c '.switches // {}')" "${sl}")" \
        || bench_die "${inst}: its node switches are not arm $(printf '%s' "${STEP9_ARM}" | jq -r '.name')'s (manifest.param_arms via prestart): ${why} — stopping step 9; the node keeps running in that state (no restart): tear down, or apply the arm with tools/params-apply.sh"
    echo "      ✓ ${inst}: node switches = arm $(printf '%s' "${STEP9_ARM}" | jq -r '.name') ($(bench_switch_line_values "${sl}" | paste -sd ' ' -))"
}

step_9() {
    local jobs="${BENCH_NODE_JOBS:-1}" w_sha w_mhd w_nhd w_mbd w_forks
    case "${jobs}" in ''|*[!0-9]*|0) jobs=1 ;; esac
    echo ">>> Step 9: post-config, verify only (no restart): one IAP session per node, $([ "${jobs}" -le 1 ] && echo serially || echo "up to ${jobs} at a time")"
    w_sha="$(run_expect sha | tr 'ABCDEF' 'abcdef')"; w_forks="$(run_expect forks)"
    w_mhd="$(run_expect mhd)"; w_nhd="$(run_expect nhd)"; w_mbd="$(run_expect mbd)"
    if [ -z "${w_sha}" ] || [ -z "${w_forks}" ] || [ -z "${w_mhd}" ] || [ -z "${w_nhd}" ] || [ -z "${w_mbd}" ]; then
        bench_die "step 9 cannot check the nodes' boot lines: expected sha='${w_sha}' forks='${w_forks}' delays='${w_mhd}/${w_nhd}/${w_mbd}' — $(bench_manifest) lacks node_git_sha / node_fork_schedule / consensus_parameters (the gate records them when a step of 0, 5, 6, 7 runs) and no node image probe ran in this invocation"
    fi
    echo "    every node must boot git ${w_sha}, header delay max ${w_mhd} / min ${w_nhd} ms, batch delay ${w_mbd} ms, forks ${w_forks}"
    [ -z "${BENCH_NODE_PARAM_OVERRIDES}" ] || echo "    except where BENCH_NODE_PARAM_OVERRIDES='${BENCH_NODE_PARAM_OVERRIDES}' sets that node's own values"
    echo "    node log filter: ${BENCH_NODE_LOG_FILTER:-untouched (BENCH_NODE_LOG_FILTER is empty)}${BENCH_NODE_LOG_FILTER:+, --log.file.max-files ${BENCH_NODE_LOG_MAX_FILES}}"
    STEP9_W_SHA="${w_sha}"; STEP9_W_FORKS="${w_forks}"
    STEP9_ARM="$(prestart_arm_json)"
    if [ -n "${STEP9_ARM}" ]; then
        echo "    every node's \`node switches\` line must show the first-start arm $(printf '%s' "${STEP9_ARM}" | jq -r '.name') (manifest.param_arms via prestart), by value"
    elif [ -n "${BENCH_ARM_FILE:-}" ]; then
        bench_die "BENCH_ARM_FILE is set but $(bench_manifest) has no first-start arm (param_arms via prestart): step 7 did not start the fleet in it — nothing to compare the nodes with"
    fi
    [ "${BENCH_PERSIST_SAMPLER:-0}" != 1 ] || echo "    and bench-persist-sampler.service installed and active on every node (BENCH_PERSIST_SAMPLER=1)"
    bench_node_jobs_run "${jobs}" "post-config verification (nothing was restarted)" step9_node "${!INSTANCE_NAMES[@]}"
    node_build_record
}

# bench_registry_probe — read the ConsensusRegistry over the tunnel with recovery-schedule.py (the
# current epoch, its opening block, its duration, plus the boundary drill it would schedule from
# now) and require the registry's epoch duration to be EPOCH_DURATION_SECS. The JSON is recorded
# as manifest.registry_probe. A failed read (non-zero exit: an RPC error, a timeout, a Python
# traceback, or output that is not a JSON object) is retried, 3 attempts 10 s apart; a duration
# that differs is final.
bench_registry_probe() {
    local out="" dur try=1
    while :; do
        echo "    + python3 ${DIR}/recovery-schedule.py --rpc-url ${RPC_URL} --earliest-kill <now>   (attempt ${try}/3)"
        if out="$(python3 "${DIR}/recovery-schedule.py" --rpc-url "${RPC_URL}" --earliest-kill "$(date +%s)")" \
            && printf '%s' "${out}" | jq -e 'type == "object"' >/dev/null 2>&1; then
            break
        fi
        [ "${try}" -lt 3 ] || bench_die "registry probe failed 3 times, 10 s apart (recovery-schedule.py --rpc-url ${RPC_URL})"
        echo "      registry read failed — retrying in 10 s"
        try=$((try + 1)); sleep 10
    done
    dur="$(printf '%s' "${out}" | jq -r '.duration_secs // empty' 2>/dev/null || true)"
    [ "${dur}" = "${EPOCH_DURATION_SECS}" ] \
        || bench_die "ConsensusRegistry epoch duration is ${dur:-<unreadable>} s, EPOCH_DURATION_SECS is ${EPOCH_DURATION_SECS} s (registry probe: ${out})"
    bench_manifest_jq --argjson r "${out}" '.registry_probe = $r' || bench_die "could not record registry_probe in $(bench_manifest)"
    echo "    ✓ registry: epoch $(printf '%s' "${out}" | jq -r '.epoch'), duration ${dur}s == EPOCH_DURATION_SECS (manifest.registry_probe)"
}

step_10() {
    echo ">>> Step 10: health gate"
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        HEALTH_POLL_SECS=15 HEALTH_TIMEOUT_SECS=180 wait_healthy "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "$(tn_service_for_role "${NODE_ROLES[$i]}")" \
            || bench_die "${INSTANCE_NAMES[$i]} not healthy"
    done
    bench_tunnel_up 5>&- 6>&- || bench_die "IAP tunnel failed"
    # bench-obs (the Prometheus every read below queries): it must exist and its forwards answer
    obs_or_die "step 10: bench-obs is not usable (above)" bench_obs_require
    local cid
    cid="$(cast chain-id --rpc-url "${RPC_URL}")"
    [ "${cid}" = "${CHAIN_ID}" ] || bench_die "tunnel RPC reports chain ${cid}, expected ${CHAIN_ID}"
    echo "    ✓ chain id ${cid} via ${RPC_URL} (block $(cast block-number --rpc-url "${RPC_URL}" 2>/dev/null || echo '?'); an idle TN chain stays at 0 until the funder runs)"
    bench_registry_probe
    # Progress = consensus rounds, not blocks: every node's min(tn_primary_round) must rise above
    # its first sample. Re-sampled every 30 s (up to 4x) to absorb scrape + remote-write lag.
    local r0 r1="" adv="[]" tries=0 missing=" (no Prometheus sample)" inst
    r0="$(bench_prom_rounds min)"
    [ -n "${r0}" ] || bench_die "Prometheus tn_primary_round query failed"
    while [ "${tries}" -lt 4 ]; do
        sleep 30; tries=$((tries + 1))
        r1="$(bench_prom_rounds min)"
        [ -n "${r1}" ] || continue
        adv="$(bench_rounds_advanced "${r0}" "${r1}")"
        missing=""
        for inst in "${INSTANCE_NAMES[@]}"; do
            printf '%s' "${adv}" | jq -e --arg n "${inst}" 'index($n) != null' >/dev/null || missing="${missing} ${inst}"
        done
        [ -n "${missing}" ] || break
        echo "      …consensus round not yet advanced on:${missing} ($((tries * 30))s)"
    done
    [ -z "${missing}" ] || bench_die "consensus round did not advance on:${missing} (first ${r0}, last ${r1:-none})"
    echo "    ✓ consensus progressing: tn_primary_round advanced on all ${#INSTANCE_NAMES[@]} nodes ($(printf '%s' "${r1}" | jq -r '[.[]] | "rounds " + (min|tostring) + ".." + (max|tostring)'))"
    local n="" waited=0
    while [ "${waited}" -le 300 ]; do
        n="$(bench_prom_scalar "${PROM_COUNT_QUERY}")"
        [ "${n}" = "${#INSTANCE_NAMES[@]}" ] && break
        echo "      …Prometheus sees ${n:-0}/${#INSTANCE_NAMES[@]} bench nodes (${waited}s)"
        sleep 30; waited=$((waited + 30))
    done
    [ "${n}" = "${#INSTANCE_NAMES[@]}" ] || bench_die "Prometheus sees ${n:-0} bench nodes, expected ${#INSTANCE_NAMES[@]} (${PROM_COUNT_QUERY})"
    echo "    ✓ Prometheus: ${n} bench nodes reporting"
    # No bench series may ever carry devnet's labels (step 8 relabels before the first push).
    local q raw leak
    for q in "${PROM_LEAK_QUERY}" "${PROM_LEAK_ANY_QUERY}"; do
        raw="$(bench_prom_query "${q}" || true)"
        printf '%s' "${raw}" | jq -e '.status == "success"' >/dev/null 2>&1 || bench_die "Prometheus query failed: ${q}"
        leak="$(printf '%s' "${raw}" | jq -r '.data.result[0].value[1] // "0"')"
        [ "${leak}" = "0" ] || bench_die "${leak} bench node(s) have series labelled network=\"devnet\" in bench-obs (${q})"
    done
    echo "    ✓ Prometheus: no network=\"devnet\" series from bench nodes"
    # Admission: every node runs Closed (primary + worker networks) with fallback 0, read from its
    # own /metrics over IAP (loopback only) -> manifest.admission[] + fleet_modes. It lists every
    # node that is not Closed.
    bench_admission_gate || bench_die "admission gate: not every node runs Closed admission (ADM_BAD lines above; manifest.admission)"
    bench_manifest_ts nodes_healthy
}

step_11() {
    echo ">>> Step 11: app contracts on chain ${CHAIN_ID}"
    local out="${BENCH_RESULTS_DIR}/deployments-bench.json"
    if [ "${WITH_CONTRACTS}" -ne 1 ]; then
        echo "    skipped (no --with-contracts). Steps 13/14 need ${out}."
        [ -f "${out}" ] || bench_warn "${out} does not exist yet"
        return 0
    fi
    local wt="${BENCH_CONTRACTS_WORKTREE}" br="${BENCH_CONTRACTS_BRANCH}"
    [ -d "${BENCH_CONTRACTS_SRC_DIR}" ] || bench_die "${BENCH_CONTRACTS_SRC_DIR} missing (devnet-contracts.sh's checkout)"
    if [ ! -d "${wt}" ]; then
        mkdir -p "$(dirname "${wt}")"
        bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" worktree add "${wt}" -b "${br}" "${BENCH_CONTRACTS_BASE_BRANCH}"
    fi
    [ "$(git -C "${wt}" rev-parse --abbrev-ref HEAD)" = "${br}" ] || bench_die "${wt} is not on ${br}"
    bench_run git -C "${wt}" submodule update --init --recursive
    # Chain 32286 routes tn-contracts to deployments-testnet.json (DeploymentsResolver.sol);
    # seed it with the devnet address book so the same CREATE2 addresses are expected.
    bench_run cp "${wt}/deployments/deployments-devnet.json" "${wt}/deployments/deployments-testnet.json"
    bench_tunnel_up 5>&- 6>&- || bench_die "IAP tunnel failed"
    echo "    + TN_CONTRACTS_DIR=${wt} TN_CONTRACTS_BRANCH=${br} DEPLOYMENTS_JSON=deployments/deployments-testnet.json DEVNET_RPC=${RPC_URL} EXPECTED_CHAIN_ID=${CHAIN_ID} devnet-contracts.sh --yes"
    TN_CONTRACTS_DIR="${wt}" TN_CONTRACTS_BRANCH="${br}" DEPLOYMENTS_JSON="deployments/deployments-testnet.json" \
        DEVNET_RPC="${RPC_URL}" EXPECTED_CHAIN_ID="${CHAIN_ID}" "${REPO_ROOT}/devnet-contracts.sh" --yes
    cp "${wt}/deployments/deployments-testnet.json" "${out}"
    echo "    ✓ ${out} (the worktree is never committed; teardown removes it + ${br})"
    bench_manifest_ts contracts_done
}

step_12() {
    echo ">>> Step 12: secret access for ${SERVICE_ACCOUNT} + results bucket gs://${BENCH_BUCKET}"
    local s
    for s in "${BENCH_TXGEN_MASTER_SECRET}" "${BENCH_TXGEN_SEED_SECRET}"; do
        case "${s}" in bench-txgen-*) ;; *) bench_die "unexpected secret ${s}" ;; esac
        bench_run gcloud secrets add-iam-policy-binding "${s}" --project="${PROJECT_ID}" \
            --member="serviceAccount:${SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor --format=none
    done
    if gcloud storage buckets describe "gs://${BENCH_BUCKET}" --format='value(name)' >/dev/null 2>&1; then
        echo "    bucket exists"
    else
        bench_run gcloud storage buckets create "gs://${BENCH_BUCKET}" --project="${PROJECT_ID}" \
            --location="${BENCH_BUCKET_LOCATION}" --uniform-bucket-level-access
    fi
    bench_run gcloud storage buckets update "gs://${BENCH_BUCKET}" --update-labels="${BENCH_LABELS}"
}

# step_13 — fund the senders, once every validator is CvvActive (bench_fleet_ready -> manifest.fleet_ready).
# A validator out of the committee's active set (a straggler from the coordinated start) gets up to
# BENCH_FLEET_READY_MAX_WAIT_SECS (one epoch boundary + settle) to rejoin; funding a fleet with a
# member missing would measure the wrong committee. The tunnel serves the boundary computation.
step_13() {
    echo ">>> Step 13: fund senders (every validator CvvActive first)"
    bench_tunnel_up 5>&- 6>&- || bench_die "IAP tunnel failed"
    obs_or_die "step 13: bench-obs is not usable (above)" bench_obs_require   # the blast's evidence goes to it
    bench_fleet_ready "${BENCH_FLEET_READY_MAX_WAIT_SECS}" step13 \
        || bench_die "step 13: not every validator is CvvActive after waiting up to ${BENCH_FLEET_READY_MAX_WAIT_SECS} s (above; manifest.fleet_ready) — nothing was funded"
    "${DIR}/benchmark-blast.sh" fund --yes --run "${BENCH_RUN_ID}" 5>&- 6>&-
}
step_14() { echo ">>> Step 14: blast";        "${DIR}/benchmark-blast.sh" run --yes --run "${BENCH_RUN_ID}" 5>&- 6>&-; }

# prom_window_wait — step 15's Prometheus window: manifest prom_window = {start, end, end_reason,
# waited_secs} and PROM_WINDOW_ARGS = the collector's --start/--end (or nothing). The collector's own
# window (collect-gcp-metrics.py window_from_manifest) runs from the earliest of
# timestamps.nodes_healthy / fund_start / blast_start_at and phases[].start to the latest of
# timestamps.blast_end / collect_start and phases[].end; in bench 3 that ended before the chaos target
# rejoined. With BENCH_COLLECT_WAIT_REJOIN=1 and a chaos kill that landed (a manifest.chaos[] entry
# with rc 0 whose action names kill), it waits — at most BENCH_FLEET_READY_MAX_WAIT_SECS in all — for
# every validator to be CvvActive (bench_tunnel_up for the boundary read, then bench_fleet_ready) AND
# for each killed node to still read CvvActive BENCH_NODE_BACK_SECS later: bench 3's target was
# promoted and demoted again 11 times, so one CvvActive reading is not a rejoin. A target that falls
# back starts the wait over. The window ends then: end_reason fleet_ready (both reads, confirm_secs
# between them), or max_wait when the cap came first (a warning, never a stop); the same start is
# passed as --start and the wait's end as --end (they win over the manifest window). Otherwise
# (end_reason knob_off or no_chaos, waited_secs 0) nothing is passed and the record holds the
# manifest window.
PROM_WINDOW_ARGS=()
prom_window_wait() {
    local m start end reason waited=0 t0 deadline left back confirm=null targets="" inst idx mode bad
    local sq='[(.timestamps // {}) | .nodes_healthy, .fund_start, .blast_start_at] + [(.phases // [])[] | objects | .start]'
    local eq='[(.timestamps // {}) | .blast_end, .collect_start] + [(.phases // [])[] | objects | .end]'
    local num='map(select(type == "string") | fromdateiso8601?)'
    m="$(bench_manifest)"
    PROM_WINDOW_ARGS=()
    start="$(jq -r "${sq} | ${num} | if length > 0 then (min | todate) else empty end" "${m}" 2>/dev/null || true)"
    end="$(jq -r "${eq} | ${num} | if length > 0 then (max | todate) else empty end" "${m}" 2>/dev/null || true)"
    if [ "${BENCH_COLLECT_WAIT_REJOIN:-0}" != "1" ]; then
        reason=knob_off
    elif ! jq -e '[(.chaos // [])[] | objects | select(.rc == 0 and ((.action // "") | test("(^|[^a-z])kill([^a-z]|$)")))] | length > 0' \
            "${m}" >/dev/null 2>&1; then
        reason=no_chaos
    else
        echo "    Prometheus window: a chaos kill landed — it ends once every validator is CvvActive again (BENCH_COLLECT_WAIT_REJOIN=1, at most ${BENCH_FLEET_READY_MAX_WAIT_SECS} s)"
        t0="$(bench_now_unix)"
        deadline=$((t0 + BENCH_FLEET_READY_MAX_WAIT_SECS))
        back="${BENCH_NODE_BACK_SECS:-180}"
        case "${back}" in ''|*[!0-9]*) back=180 ;; esac
        for inst in $(jq -r '[(.chaos // [])[] | objects | select(.rc == 0 and ((.action // "") | test("(^|[^a-z])kill([^a-z]|$)"))) | .node]
                | unique | .[]' "${m}" 2>/dev/null || true); do
            if idx="$(bench_index_of "${inst}")"; then targets="${targets} ${idx}"; fi
        done
        bench_tunnel_up 5>&- 6>&- \
            || bench_warn "step 15: the RPC tunnel is not up; the fleet-ready wait cannot read the next epoch boundary and may wait its whole cap"
        reason=max_wait
        while :; do
            left=$((deadline - $(bench_now_unix)))
            [ "${left}" -gt 0 ] || break
            bench_fleet_ready "${left}" step15 || break
            # the killed node(s) must still be CvvActive one BENCH_NODE_BACK_SECS later
            left=$((deadline - $(bench_now_unix)))
            [ "${left}" -ge "${back}" ] || { echo "    no time left to confirm the rejoin (${left} s < ${back} s)"; break; }
            echo "    every validator CvvActive; confirming${targets:+ the chaos target(s)} in ${back} s"
            sleep "${back}"
            bad=""
            for idx in ${targets}; do
                mode="$(_bench_ro_retry bench_node_mode "${idx}")" || mode=""
                [ "${mode}" = "CvvActive" ] || bad="${bad} ${INSTANCE_NAMES[$idx]}=${mode:-unreadable}"
            done
            if [ -z "${bad}" ]; then reason=fleet_ready; confirm="${back}"; break; fi
            bench_warn "step 15: CvvActive did not hold ${back} s later:${bad} — waiting on (a transient promotion is not a rejoin)"
        done
        [ "${reason}" = fleet_ready ] \
            || bench_warn "step 15: no confirmed rejoin within ${BENCH_FLEET_READY_MAX_WAIT_SECS} s (manifest.fleet_ready, prom_window); collecting up to now anyway"
        waited=$(( $(bench_now_unix) - t0 ))
        end="$(bench_now_iso)"
        if [ -n "${start}" ]; then
            PROM_WINDOW_ARGS=(--start "${start}" --end "${end}")
        else
            bench_warn "step 15: the manifest has no window start (timestamps, phases); the collector derives its own window"
        fi
    fi
    bench_manifest_jq --arg s "${start}" --arg e "${end}" --arg r "${reason}" --argjson w "${waited}" --argjson c "${confirm}" '
        def str: if . == "" then null else . end;
        .prom_window = {start: ($s|str), end: ($e|str), end_reason: $r, waited_secs: $w, confirm_secs: $c}' \
        || bench_warn "step 15: could not record prom_window in $(bench_manifest)"
    echo "    Prometheus window: ${start:-?} -> ${end:-?} (${reason}, waited ${waited} s)"
}

# step_15 — the blast's collect, the Prometheus window, then the collector against bench-obs's
# Prometheus (bench_obs_exists first: a lost VM is named as lost data, never a --from 8; then
# bench_obs_require: its forward answers): with BENCH_PROM_AUTH=0 the
# collector gets --prom-url ${BENCH_PROM_URL} --prom-no-auth (no Grafana proxy, no password).
step_15() {
    local wargs="" pargs=()
    echo ">>> Step 15: collect"
    "${DIR}/benchmark-blast.sh" collect --yes --run "${BENCH_RUN_ID}" 5>&- 6>&-
    prom_window_wait
    # bench-obs holds the run's only copy of its Prometheus series: gone now is gone for good, and a
    # --from 8 would recreate an empty VM and then re-fund and re-blast.
    bench_obs_exists || bench_die "bench-obs is gone: the run's Prometheus series went with it; do NOT --from 8 (it would re-fund and re-blast) — collect without Prometheus (--no-prom) or accept the gap"
    obs_or_die "step 15: bench-obs is not usable (above) — re-run with --only 15 once its forward answers" bench_obs_require
    [ "${#PROM_WINDOW_ARGS[@]}" -eq 0 ] || wargs=" ${PROM_WINDOW_ARGS[*]}"
    [ "${BENCH_PROM_AUTH:-0}" != 0 ] || pargs=(--prom-url "${BENCH_PROM_URL}" --prom-no-auth)
    [ "${#pargs[@]}" -eq 0 ] || wargs="${wargs} ${pargs[*]}"
    if [ -f "${COLLECT_METRICS_PY}" ]; then
        echo "    + python3 ${COLLECT_METRICS_PY} --manifest ${BENCH_RESULTS_DIR}/manifest.json --out ${BENCH_RESULTS_DIR}/metrics.json${wargs}"
        python3 "${COLLECT_METRICS_PY}" --manifest "$(bench_manifest)" --out "${BENCH_RESULTS_DIR}/metrics.json" \
            ${PROM_WINDOW_ARGS[@]+"${PROM_WINDOW_ARGS[@]}"} ${pargs[@]+"${pargs[@]}"}
    else
        bench_warn "${COLLECT_METRICS_PY} not found — metrics.json not produced (re-run --only 15 once it exists)"
        bench_manifest_note "collect: ${COLLECT_METRICS_PY} missing at $(bench_now_iso)"
    fi
    # metrics.json is new since the collect: analysis/ and the index again (non-fatal; the
    # teardown's local gate is what guards results/<run>/, the only copy of the run).
    bench_local_analysis
    bench_local_index || bench_warn "INDEX.md / CHECKSUMS.sha256 not written — the teardown writes them"
}

step_16() {
    echo ">>> Step 16: teardown"
    if [ "${WITH_TEARDOWN}" -ne 1 ]; then
        echo "    skipped (no --with-teardown). Later: benchmark/benchmark-teardown.sh --run ${BENCH_RUN_ID} --yes"
        return 0
    fi
    bench_tunnel_down
    "${DIR}/benchmark-teardown.sh" --yes --run "${BENCH_RUN_ID}" 5>&- 6>&-
}

# ================================ dry-run plan ==========================================
# plan_probe_line — what the gate's node image probe will check (nothing is executed here).
plan_probe_line() {
    local e="" v
    for v in BENCH_DOCKER_IMAGE_EXPECT_DIGEST BENCH_NODE_EXPECT_SHA BENCH_NODE_EXPECT_FORKS; do
        [ -z "${!v:-}" ] || e="${e} ${v}=${!v}"
    done
    [ -n "${e}" ] || e=" none set"
    if [ "${NODE_PIN_FROM_MANIFEST}" -eq 1 ]; then
        printf '%s: pinned by this run'"'"'s gate (manifest node_image_pinned, git %s, forks %s) — not probed again' \
            "${DOCKER_IMAGE}" "$(run_expect sha)" "$(run_expect forks)"
    else
        printf '%s: digest, telcoin -V sha, flag + string contract (node-image-contract.txt), EXPECT_* env (%s); at the gate when steps 0/5/6/7 run' \
            "${DOCKER_IMAGE}" "${e# }"
    fi
}

# plan_node_params — the plan's "logs" line; with BENCH_NODE_PARAM_OVERRIDES set, one line per node:
# the parameters step 7 starts it with (the fleet file's, overrides applied); then every node whose
# parameters the node would refuse at startup.
plan_node_params() {
    local i ov vt
    if [ -n "${BENCH_NODE_LOG_FILTER}" ]; then
        echo "  logs     --log.stdout.filter/--log.file.filter ${BENCH_NODE_LOG_FILTER} --log.file.max-files ${BENCH_NODE_LOG_MAX_FILES} (BENCH_NODE_LOG_FILTER, step 7 pre-start config)"
    else
        echo "  logs     node command line untouched (BENCH_NODE_LOG_FILTER is empty)"
    fi
    if [ -n "${BENCH_NODE_PARAM_OVERRIDES}" ]; then
        for i in "${!INSTANCE_NAMES[@]}"; do
            ov="$(bench_node_overrides "${i}" | paste -sd, -)"
            vt="$(bench_node_param_ms "${i}" vote_timeout)"
            printf '    %-20s max_header_delay %s ms, min_header_delay %s ms, max_batch_delay %s ms, threshold %s, vote_timeout %s%s\n' \
                "${INSTANCE_NAMES[$i]}" "$(bench_node_param_ms "${i}" max_header_delay)" "$(bench_node_param_ms "${i}" min_header_delay)" \
                "$(bench_node_param_ms "${i}" max_batch_delay)" "$(bench_node_param_int "${i}" header_num_of_batches_threshold)" \
                "${vt:+${vt} ms}${vt:-5000 ms (node default)}" "${ov:+  [override ${ov}]}"
        done
    fi
    bench_node_params_problems | sed 's/^/    ✗ the node would refuse to start: /'
}

# plan_prestart_lines — per node, what step 7's pre-start config sets on it that is not fleet-wide:
# its BENCH_NODE_PARAM_OVERRIDES (into parameters.yaml); one line per node with any, else one line.
plan_prestart_lines() {
    local i l n=0
    for i in "${!INSTANCE_NAMES[@]}"; do
        l="$(bench_node_overrides "${i}" | paste -sd, -)"
        [ -n "${l}" ] || continue
        printf '                                       %-20s parameters.yaml %s\n' "${INSTANCE_NAMES[$i]}:" "${l}"
        n=$((n + 1))
    done
    [ "${n}" -gt 0 ] || echo "                                       no per-node parameters (BENCH_NODE_PARAM_OVERRIDES is empty)"
    [ -n "${BENCH_ARM_FILE:-}" ] || return 0
    if bench_arm_state_load 2>/dev/null; then
        l="$(bench_arm_writes | paste -sd, -)"
        printf '                                       %-20s parameters.yaml %s (first-start arm %s, %s; every switch away from its default)\n' \
            "every node:" "${l:-unchanged}" "${BENCH_ARM_NAME}" "${BENCH_ARM_FILE}"
        echo "                                       -> manifest.param_arms {name: ${BENCH_ARM_NAME}, via: prestart, begin = ready = the coordinated start}; step 9 reads every node's switch line back"
    else
        echo "                                       first-start arm ${BENCH_ARM_FILE}: refused (see the step 7 check above)"
    fi
}

# plan_reserve_ports_line — step 7's reserve-ports line of the plan (BENCH_NODE_RESERVE_PORTS=1), with its
# leading newline; nothing at 0, so that plan is bench 6's.
plan_reserve_ports_line() {
    local ports
    [ "${BENCH_NODE_RESERVE_PORTS:-0}" = 1 ] || return 0
    ports="$(bench_reserved_ports 2>/dev/null)" || ports="? (root config.sh DEFAULT_*_PORT unset)"
    printf '\n                     reserve-ports     per node, one IAP session (bench_host_step_script <instance> reserve-ports %s): the ports into net.ipv4.ip_local_reserved_ports, now and in /etc/sysctl.d, before the staging start binds them' "${ports}"
    printf '\n                                       (HOST_STEP -> node_startup.reserve_ports, manifest.reserved_ports; a failed one stops step 7; the pre-start config reads them back: PRECFG_OK reserved=)'
}

# plan_host_step_line — the pre-start host steps (BENCH_NODE_READ_AHEAD_KB, BENCH_NODE_EVICT_MDBX, or the
# first-start arm's) on a line of their own, led by a newline; nothing when there are none.
plan_host_step_line() {
    local ra="${BENCH_NODE_READ_AHEAD_KB:-}" ev="${BENCH_NODE_EVICT_MDBX:-0}" src="BENCH_NODE_READ_AHEAD_KB / BENCH_NODE_EVICT_MDBX" steps=""
    if [ -n "${BENCH_ARM_FILE:-}" ] && bench_arm_state_load 2>/dev/null; then
        ra="$(bench_arm_host_value read-ahead-kb)"; ev=0
        [ -z "$(bench_arm_host_value evict-mdbx)" ] || ev=1
        src="arm ${BENCH_ARM_NAME}"
    fi
    [ -z "${ra}" ] || steps="read-ahead-kb ${ra}"
    [ "${ev}" != 1 ] || steps="${steps:+${steps}, }evict-mdbx (fincore must then read 0)"
    [ -n "${steps}" ] || return 0
    printf '\n                                       host steps last, before the start (%s): %s; HOST_STEP -> node_startup.host_steps, a failed one is PRECFG_FAIL' "${src}" "${steps}"
}

# plan_lssd_mount_lines — step 3's local-SSD sub-step (BENCH_NODE_DATADIR_LSSD=1), each line led by a newline;
# nothing at all with the knob off (step 3's plan is then the serial marker alone). Text only: the script is
# bench_lssd_mount_script's (--print-lssd-mount <instance>).
plan_lssd_mount_lines() {
    [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ] || return 0
    local i names="" dirs l="                       "
    for i in $(lssd_datadir_nodes); do names="${names} ${INSTANCE_NAMES[$i]}"; done
    dirs="$(for i in $(lssd_datadir_nodes); do node_datadir "${i}"; echo; done | sort -u | paste -sd ' ' -)"
    printf '\n                     local SSD -> data directory (BENCH_NODE_DATADIR_LSSD=1), per node (BENCH_NODE_JOBS=%s at a time), one IAP session, script on stdin (bench_lssd_mount_script; --print-lssd-mount <instance>):' "${BENCH_NODE_JOBS:-1}"
    printf '\n%s%s' "${l}" "${names# }"
    printf '\n%sdevice /dev/disk/by-id/google-local-nvme-ssd-0 (only); first time (no marker /var/lib/bench-lssd/uuid): mkfs.ext4 -q -F -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard' "${l}"
    printf '\n%smount at %s with the fstab options of /; fstab UUID=<uuid> <dir> ext4 <options of />,nofail,x-systemd.device-timeout=30s 0 2;' "${l}" "${dirs}"
    printf '\n%stelcoin.service.d/bench-lssd.conf RequiresMountsFor=<dir>; the owner is left to keygen (step 5, the first writer)' "${l}"
    printf '\n%sLSSD_MOUNT <instance> ... mkfs=done|kept|resumed -> manifest.instances[].data_disk (step 2 wrote {"class": "local-ssd"} there and {"class": "boot", ...} for the other nodes)' "${l}"
    printf '\n%s-> %s/logs/lssd-mount-<utc>.log; a failed or missing line stops the step and names the node (failed lost: a wiped SSD, never formatted again)' "${l}" "${BENCH_RESULTS_DIR}"
    printf '\n%safter every node: LSSD_MOUNT_SUMMARY nodes= done= kept= resumed= failed=[]' "${l}"
}

# plan_lssd_check_line — step 7's local-SSD check (BENCH_NODE_DATADIR_LSSD=1) on a line of its own, led by a
# newline; nothing with the knob off.
plan_lssd_check_line() {
    [ "${BENCH_NODE_DATADIR_LSSD:-0}" = 1 ] || return 0
    printf '\n                                       on the %s local-SSD node(s), before anything else: bench_lssd_check_script (the data directory must be the SSD mount, else PRECFG_FAIL <instance> local SSD not mounted at <dir>)' \
        "$(lssd_datadir_nodes | wc -w | tr -d ' ')"
}

# plan_step9_lines — step 9's checks that only some runs have (the first-start arm's switch line, the
# persist sampler), each on a line of its own led by a newline; nothing when neither applies.
plan_step9_lines() {
    if [ -n "${BENCH_ARM_FILE:-}" ]; then
        printf '\n                     every node'"'"'s `node switches` line == the first-start arm (manifest.param_arms via prestart; by value, an optional switch may be absent at its default), else stop'
    fi
    if [ "${BENCH_PERSIST_SAMPLER:-0}" = 1 ]; then
        printf '\n                     bench-persist-sampler.service (node-persist-sampler.sh + tools/folio-census.py -> /usr/local/bin, root; BENCH_PERSIST_SAMPLER=1), must be active'
    fi
    return 0
}

# plan_light_lines <13|14> — with BENCH_LIGHT_LOAD=1, the light-load arm's line under step 13 (fund) or
# 14 (blast), led by a newline so it sits on a line of its own; nothing at all when the knob is off (the
# plan is then bench 4's, byte for byte). The sequence itself is benchmark-blast.sh's (light_plan).
plan_light_lines() {
    [ "${BENCH_LIGHT_LOAD:-0}" = "1" ] || return 0
    local after="" pairs="" sn k=0 ws=()
    [ "${BENCH_LIGHT_LOAD_AFTER:-0}" != "1" ] || after=", then one more light blast like the first"
    read -r -a ws <<< "${BENCH_LIGHT_WINDOWS:-}"
    for sn in ${BENCH_LIGHT_SENDERS:-}; do
        pairs="${pairs}${pairs:+, }${sn} x ${ws[$k]:-${BENCH_WINDOW}}"; k=$((k + 1))
    done
    if [ "$1" = 13 ]; then
        printf '\n                     light-load arm (BENCH_LIGHT_LOAD=1): one fund per blast from BENCH_RUN_INDEX=%s up, senders per blaster x window %s, the configured profile (%s x %s) funded last%s' \
            "${BENCH_RUN_INDEX}" "${pairs}" "${BENCH_SENDERS}" "${BENCH_WINDOW}" "${after}"
    else
        printf '\n                     light-load arm (BENCH_LIGHT_LOAD=1): first one light blast per senders x window (%s; %ss warmup, %ss mixed, %ss cooldown, chaos off), then the configured profile above%s;\n                     LIGHT_LOAD_START/DONE around each light blast, manifest blasts[], one LOG_RATE line per blast; about 15-20 min per light blast' \
            "${pairs}" "${BENCH_LIGHT_WARMUP_SECS}" "${BENCH_LIGHT_DURATION_SECS}" "${BENCH_LIGHT_COOLDOWN_SECS}" "${after}"
    fi
}

# plan_tunnel_line — the RPC tunnel bench_tunnel_up opens, as this shell's BENCH_TUNNEL_MODE has it:
# ssh (default) = one IAP ssh session carrying a port forward under a restarting supervisor;
# websocket = gcloud compute start-iap-tunnel (a websocket per connection).
plan_tunnel_line() {
    case "${BENCH_TUNNEL_MODE:-ssh}" in
        ssh) printf 'gcloud compute ssh %s --zone=%s --tunnel-through-iap -- -N -L localhost:%s:127.0.0.1:8545 (BENCH_TUNNEL_MODE=ssh: one IAP ssh port-forward, restarted by its supervisor, which gives up after %s consecutive failures; tunnel.log)' \
            "${INSTANCE_NAMES[0]}" "${ZONES[0]}" "${BENCH_TUNNEL_PORT}" "${BENCH_TUNNEL_MAX_FAILS:-5}" ;;
        *) printf 'gcloud compute start-iap-tunnel %s 8545 --local-host-port=localhost:%s --zone=%s (BENCH_TUNNEL_MODE=%s: a websocket per connection; tunnel.log)' \
            "${INSTANCE_NAMES[0]}" "${BENCH_TUNNEL_PORT}" "${ZONES[0]}" "${BENCH_TUNNEL_MODE}" ;;
    esac
}

# plan_harness — this checkout's HEAD, ",dirty" when tracked files differ from it (local git only).
plan_harness() {
    local sha st
    sha="$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
    st="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=no 2>/dev/null || true)"
    printf '%s%s' "${sha}" "${st:+,dirty}"
}

# plan_create_lines — step 2's create lines in the plan (the first carries the step's label): one plain
# create-instances.sh call (create_plain), or one per machine type that is not -lssd and a
# bench_create_node line per -lssd node; with BENCH_NODE_ZONES, what step 2 writes before them.
plan_create_lines() {
    local lead="   2  instances      " t i names
    if [ -n "${BENCH_NODE_ZONES:-}" ]; then
        echo "${lead}BENCH_NODE_ZONES (${BENCH_NODE_ZONES}): first ${BENCH_RESULTS_DIR}/zones.env, manifest.zone_overrides[] + a note per moved node"
        lead="                     "
    fi
    if create_plain; then
        echo "${lead}CONFIG_FILE=benchmark/config.sh ${REPO_ROOT}/common/create-instances.sh -> ${BENCH_RESULTS_DIR}/logs/create-instances-<utc>.log"
        return 0
    fi
    for t in $(machine_groups); do
        case "${t}" in *-lssd) continue ;; esac
        names=""
        for i in $(type_nodes "${t}"); do names="${names} ${INSTANCE_NAMES[$i]}"; done
        echo "${lead}BENCH_CREATE_MACHINE_TYPE=${t} CONFIG_FILE=benchmark/config.sh ${REPO_ROOT}/common/create-instances.sh (${names# }) -> ${BENCH_RESULTS_DIR}/logs/create-instances-<utc>.log"
        lead="                     "
    done
    for i in $(lssd_nodes); do
        echo "${lead}bench_create_node ${i}: ${INSTANCE_NAMES[$i]}, $(node_machine_type "${i}") in ${ZONES[$i]}: create-instances.sh's argv with --maintenance-policy=TERMINATE (local SSDs come with the type) -> ${BENCH_RESULTS_DIR}/logs/create-${INSTANCE_NAMES[$i]}-<utc>.log"
        lead="                     "
    done
}

print_plan() {
    local i
    bench_obs_urls   # no gcloud: BENCH_OBS_INTERNAL_IP (or manifest.obs.internal_ip, else the placeholder)
    cat <<EOP
PLAN for run ${BENCH_RUN_ID} (nothing below has been executed):

  fleet    $(fleet_desc), tag ${INSTANCE_TAGS}, labels ${INSTANCE_LABELS}
  chain    ${CHAIN_ID} (${CHAIN_ID_HEX}), epoch ${EPOCH_DURATION_SECS}s, image ${DOCKER_IMAGE}${BENCH_DOCKER_IMAGE:+ (BENCH_DOCKER_IMAGE)}
  probe    $(plan_probe_line)
  params   ${PARAMETERS_FILE}: max_header_delay $(bench_params_ms "${PARAMETERS_FILE}" max_header_delay) ms, min_header_delay $(bench_params_ms "${PARAMETERS_FILE}" min_header_delay) ms, max_batch_delay $(bench_params_ms "${PARAMETERS_FILE}" max_batch_delay) ms
  per-node ${BENCH_NODE_PARAM_OVERRIDES:-none} (BENCH_NODE_PARAM_OVERRIDES; step 7's pre-start config writes them into that node's parameters.yaml)
$(plan_node_params)
  harness  $(plan_harness)
  genesis  workspace ${GENESIS_WORKSPACE}, accounts ${GENESIS_WORKSPACE}/testnet_accounts.yaml
  metrics  -> ${OBS_METRICS_PUSH_URL} as network="${BENCH_PROM_NETWORK_LABEL}" (bench-obs: ${BENCH_OBS_INSTANCE}, ${BENCH_OBS_MACHINE_TYPE} in ${BENCH_OBS_ZONE}, metrics only; obs-devnet is never touched)
           forwards 127.0.0.1:${BENCH_OBS_PROM_LOCAL_PORT} -> ${BENCH_OBS_INSTANCE}:9090 (Prometheus, ${BENCH_PROM_URL}), 127.0.0.1:${BENCH_OBS_GRAFANA_LOCAL_PORT} -> ${BENCH_OBS_INSTANCE}:3000 (Grafana, ${BENCH_GRAFANA_URL})
  load     ${BENCH_TXGEN_IMAGE}, COS blasters x ${BENCH_SENDERS} senders on ${BENCH_BLASTER_MACHINE_TYPES// / -> } (next type on a zone stockout), bucket gs://${BENCH_BUCKET}
  results  ${BENCH_RESULTS_DIR}
EOP
    for i in "${!INSTANCE_NAMES[@]}"; do
        printf '    %-20s %-10s %-26s %s %s\n' "${INSTANCE_NAMES[$i]}" "${NODE_ROLES[$i]}" "${ZONES[$i]}" "${NODE_NAMES[$i]}" "${EXECUTION_ADDRESSES[$i]}"
    done
    echo "    ${#INSTANCE_NAMES[@]} instances in $(fleet_zones | wc -w | tr -d ' ') zones, $(fleet_regions | wc -w | tr -d ' ') regions"
    cat <<EOP

   -  gate           (--yes, before any step) node image probe + pin (when steps 0/5/6/7 run; see "probe" above),
                     manifest.json (+ node_* probe fields, consensus_parameters), pinned txgen image,
                     ${BENCH_TXGEN_CLOUDBUILD}, ${BENCH_TXGEN_CONFIG}, deployments-bench.json
   0  preflight      tools, auth, NO leftover bench-*/benchmark=1 instance|disk|rule|bucket, accounts, empty genesis/,
                     bench-node tag hygiene (an existing ${BENCH_OBS_INSTANCE} is a leftover too; obs-devnet is not read),
                     machine types (${BENCH_OBS_MACHINE_TYPE} for ${BENCH_OBS_INSTANCE} in ${BENCH_OBS_ZONE}), disk type and quota headroom
                     (below, ${BENCH_OBS_INSTANCE} counted in its region; every failure listed in one die),
                     pre-snapshots -> ${BENCH_RESULTS_DIR}/pre-{instances,firewall}.json, manifest.json
EOP
    {
        node_type_checks
        machine_type_check "${BENCH_BLASTER_MACHINE_TYPES%% *}" BENCH_BLASTER_MACHINE_TYPES "$(validator_zones)"
        machine_type_check "${BENCH_OBS_MACHINE_TYPE}" BENCH_OBS_MACHINE_TYPE "${BENCH_OBS_ZONE}"
        zone_fallback_check
        disk_type_check
        quota_check
        boot_image_check
    } | sed 's/^    /                     /'
    cat <<EOP
   1  image          ${BENCH_TXGEN_IMAGE:-<unresolved: ${BENCH_TXGEN_IMAGE_ERROR}>}
                     if absent: gcloud builds submit --config=${BENCH_TXGEN_CLOUDBUILD} --substitutions=_IMAGE=${BENCH_TXGEN_IMAGE_REPO},_TAG=${BENCH_TXGEN_TAG:-blast-v2-<sha>},_GIT_SHA=${BENCH_TXGEN_SHA:-<sha>} ${BENCH_TXGEN_REPO}
                     then docker run --rm --platform linux/amd64 <image> blast --help must list: ${BENCH_TXGEN_CONTRACT_FLAGS}
$(plan_create_lines)
                     stockout: that node moves to its next zone of BENCH_ZONE_FALLBACKS (${BENCH_ZONE_FALLBACKS:-none}), zones.env,
                     create again (existing nodes skipped; at most ${ZONE_FALLBACK_MAX_ROUNDS} rounds); any other failure stops; manifest.zones_used
                     assert tags==[bench-node] + labels.benchmark=1; gcloud compute disks add-labels <boot> --labels=${BENCH_LABELS},tn-role=<role>
                     bench_obs_create: ${BENCH_OBS_INSTANCE} (create-or-keep; one of another run is refused) -> manifest.obs
$(bench_obs_plan_lines 2 | sed 's/^[[:space:]]*/                       /')
   3  bootstrap      serial marker 'devnet-startup.sh complete' (${BOOTSTRAP_TIMEOUT_SECS}s/node)$(plan_lssd_mount_lines)
   4  firewall       benchmark/benchmark-firewall.sh apply --yes   (${BENCH_FIREWALL_RULES[*]} -> tag bench-node)
   5  keygen         ${REPO_ROOT}/devnet-keygen.sh           -> ${GENESIS_WORKSPACE}/genesis/{validators,observers}/
                     (-> ${BENCH_RESULTS_DIR}/logs/keygen-<utc>.log; KEYGEN_DONE lines -> manifest.keygen_timing, node_info_rpc)
   6  genesis        ${REPO_ROOT}/devnet-genesis-build.sh    -> ${GENESIS_FILE}
   7  finalize       one coordinated start: every node is configured while stopped, then all start together
                     network-config    CONFIG_FILE=benchmark/config.sh ${REPO_ROOT}/devnet-network-config.sh --yes
                                       (Closed admission on all ${#INSTANCE_NAMES[@]}; rendered under ${GENESIS_WORKSPACE}/genesis/network-config/)$(plan_reserve_ports_line)
                     stage-only        ${REPO_ROOT}/devnet-finalize.sh --stage-only (stage + v2 finalize + stop; unit enabled, inactive)
                                       -> ${BENCH_RESULTS_DIR}/logs/finalize-stage-<utc>.log
                     pre-start config  per node (BENCH_NODE_JOBS=${BENCH_NODE_JOBS:-1} at a time), one IAP session, script on stdin (bench_prestart_script; --print-prestart <instance>):$(plan_lssd_check_line)
                                       first the datadir fsync probe (200 x write 4 KB + fsync; FSYNC_PROBE <instance> p50_us= p95_us= -> node_startup.fsync_probe, never fatal), then
                                       the host probe (kernel, boot image serial, datadir mount, block queue, THP, vm.dirty_*, memory limit, mdbx.dat; HOST_PROBE <instance> -> node_startup.host, never fatal), then
                                       --http.addr/--ws.addr 0.0.0.0, --metrics 127.0.0.1:<METRICS_PORT>, ${BENCH_NODE_LOG_FILTER:+log filter + max-files, }${BENCH_NODE_DB_SYNC_MODE:+--db.sync-mode ${BENCH_NODE_DB_SYNC_MODE}, }parameters.yaml overrides; PRECFG_OK <instance>$(plan_host_step_line)
                                       after every node: FSYNC_PROBE_SUMMARY median_us= slow=[p50 > 20 % over the median] probe_failed=[] (⚠ when either lists a node; never fatal)
                                       and HOST_PROBE_SUMMARY kernel= image= ra_kb= uniform=yes|no differ=[] probe_failed=[] (⚠ when not uniform or a probe failed; never fatal)
$(plan_prestart_lines)
                     start-all         ${REPO_ROOT}/devnet-finalize.sh --start-all (every unit at one due time, node clocks)
                                       -> ${BENCH_RESULTS_DIR}/logs/finalize-start-<utc>.log; COORDINATED_START -> manifest.coordinated_start;
                                       stop when spread_secs > ${START_SPREAD_MAX_SECS}
                     re-run (--from 7) converges: PRESTAGED/RUNNING nodes are skipped, flags already set are accepted,
                     the first start stays manifest.coordinated_start (later ones: coordinated_start_reruns);
                     a unit RUNNING before any coordinated start stops the step (stop it by hand first)
   8  observability  bench_obs_ensure: ${BENCH_OBS_INSTANCE} created if absent, booted, Prometheus + Grafana up (--print-obs-bringup),
                     forwards 127.0.0.1:${BENCH_OBS_PROM_LOCAL_PORT} -> :9090 and 127.0.0.1:${BENCH_OBS_GRAFANA_LOCAL_PORT} -> :3000 -> manifest.obs; metrics only -> bench-obs, obs-devnet never touched
$(bench_obs_plan_lines 8 | sed 's/^[[:space:]]*/                       /')
                     bench_fleet_ready 0: every validator CvvActive (manifest.fleet_ready), else stop; then per node, one IAP session, no restart:
                     throwaway token (openssl rand -hex 16) on stdin only -> setup-observability.sh --json --enable-metrics --token-stdin -> black hole 127.0.0.1:9 (push + metrics URLs);
                     needs done ok:true + 'Node already serves a metrics endpoint (--metrics).' + container StartedAt unchanged + NRestarts=0;
                     curl http://<bench-obs internal IP>:9090/-/ready from the node (else OBSCFG_FAIL "bench-obs unreachable", Alloy untouched);
                     stop alloy, wipe /var/lib/telcoin-alloy, TN_CHAIN=${BENCH_PROM_NETWORK_LABEL} TN_NODE=<instance> OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}, start alloy;
                     OBSCFG_OK <instance> restarted=none (the whole session: --print-obs-script <instance>)
   9  post-config    per node (BENCH_NODE_JOBS=${BENCH_NODE_JOBS:-1} at a time), one IAP session, verify only (no restart, no start-script edit): docker inspect telcoin args
                     --http.addr/--ws.addr 0.0.0.0, --metrics 127.0.0.1:<port>${BENCH_NODE_LOG_FILTER:+, log filters == BENCH_NODE_LOG_FILTER}; <DATA_DIR from .node-meta>/parameters.yaml;
                     bench alloy labels; NRestarts=0; eth_chainId == ${CHAIN_ID_HEX} on the internal IP + consensus progressing since the coordinated
                     start (blocks rose OR docker logs 'subdag committed|quorum reached'); boot lines (git sha, delays, fork schedule)
                     == manifest node_git_sha / consensus_parameters / node_fork_schedule, else stop; bench-node-sampler.service; POSTCFG_OK ... back=-$(plan_step9_lines)
                     (the whole script: --print-postconfig <instance>; step 7's pre-start script: --print-prestart <instance>)
  10  health gate    wait_healthy x${#INSTANCE_NAMES[@]}; RPC tunnel to ${RPC_URL}:
                     $(plan_tunnel_line)
                     bench_obs_require: ${BENCH_OBS_INSTANCE} exists (else stop: re-run with --only 8), forwards up, ${BENCH_PROM_URL}/query answers, disk >= ${BENCH_OBS_DISK_MAX_PCT}% a warning;
                     cast chain-id == ${CHAIN_ID}; bench-obs Prometheus ${PROM_COUNT_QUERY} == ${#INSTANCE_NAMES[@]};
                     min by (node)(tn_primary_round{network="${BENCH_PROM_NETWORK_LABEL}"}) rises on every node (samples 30 s apart);
                     ${PROM_LEAK_QUERY} == 0 (and the same over every metric);
                     python3 recovery-schedule.py --rpc-url ${RPC_URL}: registry epoch duration == ${EPOCH_DURATION_SECS} -> manifest.registry_probe;
                     bench_admission_gate: every node admission Closed (primary + worker), fallback 0 -> manifest.admission, fleet_modes
  11  contracts      $([ "${WITH_CONTRACTS}" -eq 1 ] && echo "git worktree add ${BENCH_CONTRACTS_WORKTREE} -b ${BENCH_CONTRACTS_BRANCH} ${BENCH_CONTRACTS_BASE_BRANCH}" || echo "SKIPPED (pass --with-contracts)")
                     $([ "${WITH_CONTRACTS}" -eq 1 ] && echo "devnet-contracts.sh --yes (DEPLOYMENTS_JSON=deployments/deployments-testnet.json EXPECTED_CHAIN_ID=${CHAIN_ID}) -> ${BENCH_RESULTS_DIR}/deployments-bench.json")
  12  IAM + bucket   gcloud secrets add-iam-policy-binding ${BENCH_TXGEN_MASTER_SECRET}|${BENCH_TXGEN_SEED_SECRET} --member=serviceAccount:${SERVICE_ACCOUNT} --role=roles/secretmanager.secretAccessor
                     gcloud storage buckets create gs://${BENCH_BUCKET} --location=${BENCH_BUCKET_LOCATION}; update --update-labels=${BENCH_LABELS}
  13  fund           bench_obs_require; bench_fleet_ready ${BENCH_FLEET_READY_MAX_WAIT_SECS}: every validator CvvActive, waiting up to one epoch boundary (manifest.fleet_ready)
                     benchmark/benchmark-blast.sh fund --yes   (bench-funder, --prepare $(( 10 * BENCH_SENDERS )) senders from $(( BENCH_RUN_INDEX * 100000 )))$(plan_light_lines 13)
  14  blast          benchmark/benchmark-blast.sh run --yes    (bench-blaster-01..10, start now+${BENCH_START_DELAY_SECS}s, ${BENCH_DURATION_SECS}s mixed, $([ "${BENCH_CHAOS}" = "1" ] && echo "chaos on v05 + observer" || echo "chaos off (BENCH_CHAOS=0)"))$(plan_light_lines 14)
  15  collect        benchmark/benchmark-blast.sh collect --yes; ${BENCH_OBS_INSTANCE} gone = its series lost (stop, never --from 8); bench_obs_require; python3 ${COLLECT_METRICS_PY} --manifest ${BENCH_RESULTS_DIR}/manifest.json --out ${BENCH_RESULTS_DIR}/metrics.json$([ "${BENCH_PROM_AUTH:-0}" != 0 ] || printf ' --prom-url %s --prom-no-auth' "${BENCH_PROM_URL}")
                     $([ "${BENCH_COLLECT_WAIT_REJOIN:-0}" = "1" ] && echo "after a landed chaos kill: bench_fleet_ready + the killed node still CvvActive ${BENCH_NODE_BACK_SECS:-180} s later, within ${BENCH_FLEET_READY_MAX_WAIT_SECS} s (warn only), then --start <manifest window start> --end <then> (manifest.prom_window)" || echo "Prometheus window = the manifest's (BENCH_COLLECT_WAIT_REJOIN is not 1; manifest.prom_window end_reason knob_off)")
                     tools/cert-rate.py + tools/block-rate.py -> results/${BENCH_RUN_ID}/analysis/; INDEX.md + CHECKSUMS.sha256 (non-fatal; results/ is the only copy)
  16  teardown       $([ "${WITH_TEARDOWN}" -eq 1 ] && echo "benchmark/benchmark-teardown.sh --yes --run ${BENCH_RUN_ID}" || echo "SKIPPED (pass --with-teardown; or run benchmark-teardown.sh later)")

Scope: $([ -n "${ONLY}" ] && echo "ONLY step ${ONLY}" || echo "steps ${FROM}..${TO}")
EOP
    echo "Local checks (no GCP calls):"
    local ok=1
    bench_require_tools gcloud cast jq python3 curl docker git || ok=0
    if grep -qi "${BENCH_TXGEN_MASTER_ADDRESS}" "${GENESIS_WORKSPACE}/testnet_accounts.yaml" 2>/dev/null; then
        echo "    ✓ accounts file funds the bench txgen master"; else echo "    ✗ accounts file lacks ${BENCH_TXGEN_MASTER_ADDRESS}"; ok=0; fi
    if [ -d "${BENCH_DIR}/genesis" ] && [ -n "$(ls -A "${BENCH_DIR}/genesis" 2>/dev/null)" ]; then
        echo "    ✗ ${BENCH_DIR}/genesis is not empty"; ok=0; else echo "    ✓ benchmark/genesis empty"; fi
    local p7; p7="$(step7_local_problems)"
    if [ -z "${p7}" ]; then echo "    ✓ python3 PyYAML, TN_NODE_SCRIPTS_REF ${TN_NODE_SCRIPTS_REF} (step 7)"
    else printf '%s\n' "${p7}" | sed 's/^/    ✗ /'; ok=0; fi
    if ( bench_require_txgen_image ) 2>/dev/null; then echo "    ✓ image pinned: ${BENCH_TXGEN_IMAGE}"
    else echo "    ✗ image: ${BENCH_TXGEN_IMAGE_ERROR:-tag of '${BENCH_TXGEN_IMAGE}' is not blast-v2-<sha>}"; ok=0; fi
    [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] && echo "    ✓ ${BENCH_TXGEN_CLOUDBUILD}" || { echo "    ✗ ${BENCH_TXGEN_CLOUDBUILD} missing (step 1)"; ok=0; }
    [ -f "${BENCH_TXGEN_CONFIG}" ] && echo "    ✓ ${BENCH_TXGEN_CONFIG}" || echo "    · ${BENCH_TXGEN_CONFIG} not present yet (needed by steps 13-14)"
    [ -f "${COLLECT_METRICS_PY}" ] && echo "    ✓ ${COLLECT_METRICS_PY}" || echo "    · ${COLLECT_METRICS_PY} not present yet (needed by step 15)"
    [ "${ok}" -eq 1 ] || echo "    (fix the ✗ items before --yes)"
    echo ""
    echo "DRY RUN — re-run with --yes to execute."
}

# ================================ output copy (--yes) ===================================
# deploy_new_log <dir> <prefix> — create and print a new, empty <dir>/<prefix>-<UTC stamp>.log
# (noclobber; -1, -2, ... when that name exists), so no invocation ever appends to another's copy.
deploy_new_log() {
    local stamp f n=0
    mkdir -p "$1" || return 1
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    f="$1/$2-${stamp}.log"
    until ( set -C; : > "${f}" ) 2>/dev/null; do
        [ -e "${f}" ] || { echo "❌ cannot create ${f}" >&2; return 1; }
        n=$((n + 1)); f="$1/$2-${stamp}-${n}.log"
    done
    printf '%s' "${f}"
}

# deploy_log_start — from here on, everything the script prints (stdout and stderr merged, so
# the order holds) also goes to ${BENCH_RESULTS_DIR}/logs/deploy-<UTC stamp>.log, each line there
# prefixed with the UTC time it was read (HH:MM:SSZ), while the terminal gets it unchanged. Each
# invocation creates its own file (noclobber), so a --from resume never truncates an earlier log.
# The copier (perl, line by line, both outputs unbuffered) reads a FIFO as a background job, not
# a process substitution: bash 3.2 cannot wait for the latter. It ignores HUP INT TERM PIPE and
# ends at EOF, once this script and every child writing to the FIFO have exited: after a closed
# terminal or a TERM to the process group it keeps copying what the step-14 blast prints during
# its exit cleanup, and a write to a gone terminal fails inside the copier instead of ending it
# (the blast's own copy ignores a dead FIFO the same way).
# fd 5 / fd 6 keep the invocation's own stdout / stderr: deploy_log_stop prints the result line
# there once the copy has drained. A process that outlives this script (the RPC tunnel's
# supervisor, started by bench_tunnel_up here or in benchmark-blast.sh) must not hold them, or a
# pipeline reading this script's output would never see its end: those calls run with 5>&- 6>&-.
deploy_log_start() {
    local tmp
    DEPLOY_LOG_FILE="$(deploy_new_log "${BENCH_RESULTS_DIR}/logs" deploy)" || bench_die "cannot create a deploy log in ${BENCH_RESULTS_DIR}/logs"
    DEPLOY_STARTED="${DEPLOY_STARTED:-$(bench_now_iso)}"
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/bench-deploy.XXXXXX")"
    mkfifo "${tmp}/out"
    # shellcheck disable=SC2016  # perl code, not shell: $f, $l and $| are perl's
    ( trap '' HUP INT TERM PIPE; exec perl -MPOSIX=strftime -e '
        open(my $f, ">>", $ARGV[0]) or die "cannot append to $ARGV[0]: $!\n";
        select((select($f), $| = 1)[0]); $| = 1;
        while (my $l = <STDIN>) { print STDOUT $l; print $f strftime("%H:%M:%SZ ", gmtime), $l; }' "${DEPLOY_LOG_FILE}" ) < "${tmp}/out" &
    DEPLOY_TEE_PID=$!
    trap deploy_log_stop EXIT
    exec 5>&1 6>&2
    exec > "${tmp}/out" 2>&1
    rm -f "${tmp}/out"; rmdir "${tmp}"
    echo "output copied to ${DEPLOY_LOG_FILE}"
}

# deploy_result_record <rc> <first error|""> <ended> — the outcome of this applied invocation:
# ${BENCH_RESULTS_DIR}/last-deploy.status (key=value lines rc, last_step, first_error, started,
# ended, scope, log; replaced atomically) and manifest deploy_result = {rc, last_step, first_error,
# started, ended, scope, log} (log relative to the run directory; null for an unknown field), also
# appended to deploy_runs[]. A run whose manifest does not exist yet (the gate stopped a new run)
# gets the status file only. Never fails.
deploy_result_record() {
    local rc="$1" err="$2" ended="$3" st tmp rel
    st="${DEPLOY_STATUS_FILE:-${BENCH_RESULTS_DIR}/last-deploy.status}"
    rel="${DEPLOY_LOG_FILE#"${BENCH_RESULTS_DIR}/"}"
    tmp="$(mktemp "${st}.XXXXXX" 2>/dev/null)" || tmp=""
    if [ -n "${tmp}" ] && printf 'rc=%s\nlast_step=%s\nfirst_error=%s\nstarted=%s\nended=%s\nscope=%s\nlog=%s\n' \
            "${rc}" "${DEPLOY_LAST_STEP:--}" "${err:--}" "${DEPLOY_STARTED:--}" "${ended}" "${DEPLOY_SCOPE:--}" \
            "${DEPLOY_LOG_FILE:--}" > "${tmp}" && mv -f "${tmp}" "${st}"; then :; else
        [ -z "${tmp}" ] || rm -f "${tmp}"
        echo "⚠ could not write ${st}" >&6
    fi
    [ -f "$(bench_manifest)" ] || return 0
    bench_manifest_jq --argjson rc "${rc}" --arg ls "${DEPLOY_LAST_STEP:-}" --arg e "${err}" --arg s "${DEPLOY_STARTED:-}" \
        --arg t "${ended}" --arg sc "${DEPLOY_SCOPE:-}" --arg l "${rel}" '
        def str: if . == "" then null else . end;
        {rc: $rc, last_step: ($ls | if test("^[0-9]+$") then tonumber else str end), first_error: ($e|str),
         started: ($s|str), ended: $t, scope: ($sc|str), log: ($l|str)} as $r
        | .deploy_result = $r | .deploy_runs = ((.deploy_runs // []) + [$r])' >/dev/null 2>&6 \
        || echo "⚠ could not record deploy_result in $(bench_manifest)" >&6
}

# deploy_log_stop — EXIT trap: close our end of the FIFO so the copier reads EOF, wait up to 10 s for it
# to drain and end (a leftover child still holding stdout must not block the exit: after the cap the
# copier is killed, so no copied line can follow the result line), record the outcome
# (deploy_result_record; first_error = the first ❌ line of this invocation's log, at most 300
# characters, its time prefix dropped), print
#   BENCH_DEPLOY_RESULT rc=<n> last_step=<step|gate|-> first_error=<text|-> log=<deploy log>
# to the invocation's own stdout (fd 5) as its last line, and keep the status. An EXIT handler
# never aborts half-way: set -e is off in here.
deploy_log_stop() {
    local rc=$? n=0 f="${DEPLOY_LOG_FILE:-}" first_error ended
    set +e
    ended="$(bench_now_iso)"
    exec >&- 2>&-
    while kill -0 "${DEPLOY_TEE_PID}" 2>/dev/null && [ "${n}" -lt 100 ]; do sleep 0.1; n=$((n + 1)); done
    # A child still holding the FIFO keeps the copier alive past the cap: stop it (it ignores TERM), so
    # nothing it copies can land after the result line; what that child prints later is not copied.
    if kill -0 "${DEPLOY_TEE_PID}" 2>/dev/null; then
        kill -KILL "${DEPLOY_TEE_PID}" 2>/dev/null
        echo "⚠ the deploy log copier was still busy 10 s after the end (a leftover child holds its input) — stopped; ${f} may lack that child's last lines" >&6
    fi
    wait "${DEPLOY_TEE_PID}" 2>/dev/null
    first_error="$(grep -m1 -F '❌' "${f}" 2>/dev/null | cut -c1-300)"
    first_error="${first_error#[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z }"
    deploy_result_record "${rc}" "${first_error}" "${ended}"
    printf 'BENCH_DEPLOY_RESULT rc=%s last_step=%s first_error=%s log=%s\n' "${rc}" "${DEPLOY_LAST_STEP:--}" \
        "${first_error:--}" "${f:--}" >&5
    exit "${rc}"
}

# ================================ runner ================================================
if [ -n "${PRINT_POSTCONFIG}" ]; then
    bench_index_of "${PRINT_POSTCONFIG}" >/dev/null || bench_die "${PRINT_POSTCONFIG} is not a bench instance"
    postconfig_script "${PRINT_POSTCONFIG}"
    exit 0
fi
if [ -n "${PRINT_PRESTART}" ]; then
    bench_index_of "${PRINT_PRESTART}" >/dev/null || bench_die "${PRINT_PRESTART} is not a bench instance"
    bench_prestart_script "${PRINT_PRESTART}"
    exit 0
fi
if [ -n "${PRINT_LSSD_MOUNT}" ]; then
    _i="$(bench_index_of "${PRINT_LSSD_MOUNT}")" || bench_die "${PRINT_LSSD_MOUNT} is not a bench instance"
    [ "${NODE_DATADIR_LSSD[$_i]}" = 1 ] || bench_die "${PRINT_LSSD_MOUNT} keeps its data directory on the boot disk (machine type $(node_machine_type "${_i}"), BENCH_NODE_DATADIR_LSSD=${BENCH_NODE_DATADIR_LSSD:-0}): step 3 mounts no local SSD on it"
    bench_lssd_mount_script "${PRINT_LSSD_MOUNT}" "$(node_datadir "${_i}")"
    exit 0
fi
if [ -n "${PRINT_OBS}" ]; then
    obs_print "${PRINT_OBS}"
    exit 0
fi
if [ -n "${PRINT_OBS_BRINGUP}" ]; then
    bench_obs_bringup_script   # obs-lib.sh: step 8's root session on bench-obs (stdin -> sudo bash -s)
    exit 0
fi
if [ "${BENCH_APPLY}" = "1" ]; then deploy_log_start; fi
echo "=========================================="
echo "benchmark deploy — run ${BENCH_RUN_ID}, project ${PROJECT_ID}, chain ${CHAIN_ID}"
echo "=========================================="
if [ "${CONFIRM}" -ne 1 ]; then
    print_plan
    exit 0
fi

# --- fail-fast gate for --yes runs (M1): everything a LATER step needs is checked now, so a
# run cannot die at step 13 an hour after the fleet came up.
in_range() { if [ -n "${ONLY}" ]; then [ "${ONLY}" -eq "$1" ]; else [ "${FROM}" -le "$1" ] && [ "$1" -le "${TO}" ]; fi; }
gate() {
    echo ">>> gate: prerequisites of the selected steps"
    local deps="${BENCH_DEPLOYMENTS_JSON:-${BENCH_RESULTS_DIR}/deployments-bench.json}" bad=0
    if in_range 1 || in_range 13 || in_range 14; then
        ( bench_require_txgen_image ) || bad=1
        [ -n "${BENCH_TXGEN_IMAGE}" ] && echo "    image ${BENCH_TXGEN_IMAGE}"
    fi
    if in_range 1; then
        [ -f "${BENCH_TXGEN_CLOUDBUILD}" ] && echo "    ✓ ${BENCH_TXGEN_CLOUDBUILD}" || { echo "    ✗ missing ${BENCH_TXGEN_CLOUDBUILD}" >&2; bad=1; }
    fi
    if in_range 13 || in_range 14; then
        [ -f "${BENCH_TXGEN_CONFIG}" ] && echo "    ✓ ${BENCH_TXGEN_CONFIG}" || { echo "    ✗ missing ${BENCH_TXGEN_CONFIG}" >&2; bad=1; }
        if [ "${WITH_CONTRACTS}" -eq 1 ] && in_range 11; then
            echo "    · ${deps} will be produced by step 11"
        elif [ -f "${deps}" ]; then
            echo "    ✓ ${deps}"
        else
            echo "    ✗ missing ${deps} and step 11 will not produce it (pass --with-contracts with a range that includes 11)" >&2; bad=1
        fi
    fi
    if in_range 7; then
        local p7
        p7="$(step7_local_problems)"
        if [ -n "${p7}" ]; then
            printf '%s\n' "${p7}" | sed 's/^/    ✗ /' >&2
            bad=1
        else
            echo "    ✓ python3 PyYAML, TN_NODE_SCRIPTS_REF ${TN_NODE_SCRIPTS_REF} (step 7)"
        fi
    fi
    if in_range 7 || in_range 9; then
        local probs
        probs="$(bench_node_params_problems)"
        if [ -n "${probs}" ]; then
            printf '%s\n' "${probs}" | sed 's/^/    ✗ /' >&2
            bad=1
        else
            echo "    ✓ every node's effective parameters pass the node's startup checks${BENCH_NODE_PARAM_OVERRIDES:+ (overrides: ${BENCH_NODE_PARAM_OVERRIDES})}"
        fi
    fi
    if in_range 2 || in_range 8; then
        # bench-obs (step 2 creates it, step 8 brings it up), locally: the knobs, the VM's startup script,
        # and the whole bring-up session built from the bundle + dashboards (no gcloud)
        local oerr
        if oerr="$( ( _bench_obs_knobs_ok ) 2>&1 )"; then
            echo "    ✓ bench-obs knobs (${BENCH_OBS_INSTANCE}, ${BENCH_OBS_MACHINE_TYPE} in ${BENCH_OBS_ZONE})"
        else
            printf '%s\n' "${oerr}" | sed 's/^❌ */    ✗ bench-obs: /' >&2; bad=1
        fi
        if [ -r "${BENCH_OBS_STARTUP_SCRIPT}" ]; then
            echo "    ✓ bench-obs startup script ${BENCH_OBS_STARTUP_SCRIPT}"
        else
            echo "    ✗ bench-obs startup script ${BENCH_OBS_STARTUP_SCRIPT} is missing or unreadable (is the common submodule checked out?)" >&2; bad=1
        fi
        if oerr="$( ( bench_obs_bringup_script >/dev/null ) 2>&1 )"; then
            echo "    ✓ bench-obs bring-up session (bundle ${BENCH_OBS_BUNDLE_DIR}, dashboards ${BENCH_OBS_DASHBOARDS_DIR})"
        else
            printf '%s\n' "${oerr:-bench_obs_bringup_script failed}" | sed 's/^❌ */    ✗ bench-obs: /' >&2; bad=1
        fi
    fi
    [ "${bad}" -eq 0 ] || bench_die "prerequisites missing — nothing was started"
    gate_node_image
}

# gate_node_image — pin the node image before anything can deploy it. A run whose manifest pins
# one already (a resume) keeps it. Otherwise, when a selected step creates or starts nodes from
# it (0, 5 keygen, 6 genesis, 7 finalize), bench_node_image_probe examines DOCKER_IMAGE (dies on
# any mismatch) and BENCH_DOCKER_IMAGE / DOCKER_IMAGE become its <repo>@sha256:<digest>, which
# every later step and every sub-script (they re-source config.sh) then runs.
# A probe that refuses, or a build that cannot honour the delays, stops the run before any
# manifest is written, so the run id is not pinned to an image it can never use.
GATE_PROBED=0
gate_node_image() {
    local m forks
    if [ "${NODE_PIN_FROM_MANIFEST}" -eq 1 ]; then
        echo "    node image ${DOCKER_IMAGE} (pinned by this run's gate probe: manifest node_image_pinned)"
    elif in_range 0 || in_range 5 || in_range 6 || in_range 7; then
        bench_node_image_probe "${DOCKER_IMAGE}"
        export BENCH_DOCKER_IMAGE="${BENCH_NODE_IMAGE_PINNED}" DOCKER_IMAGE="${BENCH_NODE_IMAGE_PINNED}"
        GATE_PROBED=1
        echo "    ✓ node image pinned: ${DOCKER_IMAGE} (git ${BENCH_NODE_GIT_SHA}, forks ${BENCH_NODE_FORK_SCHEDULE})"
        fork_delay_check "${BENCH_NODE_FORK_SCHEDULE}"
        return 0
    else
        echo "    node image ${DOCKER_IMAGE} (no selected step deploys it — not probed)"
    fi
    # A resume: the same check on what this run recorded (its build and its delays).
    m="$(bench_manifest)"
    [ -f "${m}" ] || return 0
    forks="$(jq -r '.node_fork_schedule // empty' "${m}" 2>/dev/null || true)"
    [ -n "${forks}" ] && jq -e '.consensus_parameters | type == "object"' "${m}" >/dev/null 2>&1 || return 0
    fork_delay_check "${forks}"
}

# run_params_mhd — the smallest max_header_delay (ms) this invocation leaves any node with, and where
# it comes from, as "<ms> <source>". The fleet value: PARAMETERS_FILE when step 7 (which stages it)
# is selected or the manifest has none recorded, else manifest.consensus_parameters. A per-node
# override below it wins: one in BENCH_NODE_PARAM_OVERRIDES, or one the manifest records as applied
# (consensus_parameters.overrides), so a single node cannot slip past fork_delay_check. "<ms>" is ""
# when unknown.
run_params_mhd() {
    local m v="" src="" i o inst
    m="$(bench_manifest)"
    if ! in_range 7 && [ -f "${m}" ]; then
        v="$(jq -r '.consensus_parameters.max_header_delay_ms // empty' "${m}" 2>/dev/null || true)"
        [ -z "${v}" ] || src="manifest consensus_parameters"
    fi
    if [ -z "${src}" ]; then v="$(bench_params_ms "${PARAMETERS_FILE}" max_header_delay)"; src="${PARAMETERS_FILE}"; fi
    for i in "${!INSTANCE_NAMES[@]}"; do
        o="$(bench_dur_ms "$(bench_node_override "${i}" max_header_delay)")"
        if [ -n "${o}" ] && { [ -z "${v}" ] || [ "${o}" -lt "${v}" ]; }; then
            v="${o}"; src="BENCH_NODE_PARAM_OVERRIDES (${INSTANCE_NAMES[$i]})"
        fi
    done
    if [ -f "${m}" ]; then
        while read -r inst o; do
            o="$(bench_dur_ms "${o}")"
            if [ -n "${o}" ] && { [ -z "${v}" ] || [ "${o}" -lt "${v}" ]; }; then
                v="${o}"; src="manifest consensus_parameters.overrides (${inst})"
            fi
        done <<EOF
$(jq -r '.consensus_parameters.overrides // {} | to_entries[] | select(.value.max_header_delay != null) | "\(.key) \(.value.max_header_delay)"' "${m}" 2>/dev/null || true)
EOF
    fi
    printf '%s %s' "${v}" "${src}"
}

# fork_delay_check <fork schedule> — die when the nodes would run sub-second header delays on a
# build that is not subsecond-from-genesis: such a build stamps whole-second timestamps, cannot
# honour them, and the fleet would be spent measuring nothing.
fork_delay_check() {
    local forks="$1" r mhd src way
    r="$(run_params_mhd)"; mhd="${r%% *}"; src="${r#* }"
    case "${mhd}" in ''|*[!0-9]*) return 0 ;; esac
    [ "${mhd}" -lt 1000 ] && [ "${forks}" != "subsecond-from-genesis" ] || return 0
    way="a sub-second image (one the probe reports as subsecond-from-genesis) via BENCH_DOCKER_IMAGE"
    [ "${NODE_PIN_FROM_MANIFEST}" -eq 0 ] || way="${way} — on a new run: this run is pinned to ${DOCKER_IMAGE}"
    bench_die "node image ${DOCKER_IMAGE} has fork schedule ${forks}, but max_header_delay is ${mhd} ms (${src}).
   A build without sub-second timestamps from genesis stamps whole seconds and cannot honour
   sub-second delays; running it would waste the fleet. Either:
     - ${way}, or
     - BENCH_PARAMETERS_FILE=<a parameters file with delays >= 1 s> (e.g. common/parameters.yaml: 3s/1s/1s), with step 7 selected so it is staged"
}

# gate_manifest — record what the gate established: the node image probe (when it ran in this
# invocation) and the consensus parameters. PARAMETERS_FILE reaches the nodes at step 7
# (devnet-finalize.sh stages it), so consensus_parameters is (re)recorded only when step 7 is
# selected; otherwise the recorded values stay (a warning when the file has changed since), and
# step 9 checks the nodes against them.
gate_manifest() {
    local m have now
    m="$(bench_manifest)"
    if [ "${GATE_PROBED}" -eq 1 ]; then
        bench_node_probe_manifest || bench_die "could not record the node image probe in ${m}"
        have="$(jq -r '.docker_image // empty' "${m}")"
        if [ "${have}" != "${DOCKER_IMAGE}" ]; then   # an older run's manifest, resumed
            bench_manifest_note "docker_image ${have:-unset} -> ${DOCKER_IMAGE} (gate probe, $(bench_now_iso))"
            bench_manifest_jq --arg i "${DOCKER_IMAGE}" '.docker_image = $i'
        fi
        echo "    ✓ manifest: node_image_pinned, node_git_sha, node_fork_schedule, node_probe"
    fi
    have="$(jq -r '.consensus_parameters.sha256 // empty' "${m}")"
    if in_range 7; then
        bench_consensus_params_manifest || bench_die "could not record ${PARAMETERS_FILE} in ${m}"
        echo "    ✓ manifest: consensus_parameters $(jq -c '.consensus_parameters | {file, max_header_delay_ms, min_header_delay_ms, max_batch_delay_ms}' "${m}")"
    elif [ -n "${have}" ]; then
        now="$(bench_file_sha256 "${PARAMETERS_FILE}" || true)"
        [ "${have}" = "${now}" ] || bench_warn "${PARAMETERS_FILE} changed since step 7 staged it (sha256 ${have} recorded, ${now:-unreadable} now) — keeping the recorded consensus_parameters"
    else
        echo "    · consensus_parameters not recorded yet (recorded when a range including step 7 runs)"
    fi
    # The per-node part is applied by step 7's pre-start config, so it is recorded with step 7 (above);
    # step 9 only verifies the nodes against this shell's knobs.
    if in_range 7; then
        echo "    ✓ manifest: consensus_parameters.overrides $(jq -c '.consensus_parameters.overrides' "${m}"), node_startup[*].log_filter ${BENCH_NODE_LOG_FILTER:-null}"
    elif [ -f "${m}" ] && [ "$(jq -c '.consensus_parameters.overrides // {}' "${m}" 2>/dev/null || true)" != "$(bench_node_overrides_json)" ]; then
        bench_warn "BENCH_NODE_PARAM_OVERRIDES differs from what step 7 applied ($(jq -c '.consensus_parameters.overrides // {}' "${m}")); it takes effect only when step 7 configures a fresh fleet, and step 9 will check the nodes against the new value"
    fi
}

DEPLOY_LAST_STEP="gate"
deploy_status_write - gate -
gate
# Creates manifest.json, or keeps the existing one (a resume). A failure is fatal, not hidden.
bench_manifest_init || bench_die "cannot initialise $(bench_manifest)"
jq -e '.schema == "tn-bench-manifest/v1"' "$(bench_manifest)" >/dev/null 2>&1 \
    || bench_die "$(bench_manifest) is not a readable tn-bench-manifest/v1 file — inspect it before re-running"
gate_manifest
# run_step <n> — step <n>, then timestamps.step_<n>_done. DEPLOY_LAST_STEP names the step running
# (deploy_log_stop reports it).
run_step() {
    local n="$1"
    DEPLOY_LAST_STEP="${n}"
    deploy_status_write - "${n}" -
    echo ""
    echo "##########################################"
    "step_${n}"
    bench_manifest_ts "step_${n}_done"
    echo "## step ${n} done"
}
if [ -n "${ONLY}" ]; then
    run_step "${ONLY}"
else
    n="${FROM}"
    while [ "${n}" -le "${TO}" ]; do run_step "${n}"; n=$((n + 1)); done
fi
echo ""
echo "=========================================="
echo "benchmark deploy: $([ -n "${ONLY}" ] && echo "step ${ONLY}" || echo "steps ${FROM}..${TO}") complete — ${BENCH_RESULTS_DIR}"
echo "=========================================="
