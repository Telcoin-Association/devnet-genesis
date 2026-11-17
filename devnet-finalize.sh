#!/usr/bin/env bash
#
# devnet-finalize.sh — OPERATOR driver: stage the assembled genesis on every node (or a
# targeted subset), run the tn-node-deployment v2 FINALIZE phase (setup-node.sh
# --phase=finalize writes /etc/telcoin/node.env, the start script and the systemd unit,
# then starts and enables the node), and prove each node came up the way v2 says it does.
#
# Phase A, per node (a failure skips the rest of that node, never the other nodes):
#   0. local checks: DOCKER_IMAGE is <repository>@sha256:<64 hex> (v2 on devnet runs an
#      image by digest only) and the node's EXECUTION_ADDRESSES entry is 0x + 40 hex.
#      Once per run, before the first node: the release-signature gate (see below).
#   1. readiness gate (one ssh): setup-node.sh is in TN_NODE_SCRIPTS_DIR, keygen ran
#      (.node-meta records PASSPHRASE_METHOD), no telcoin unit is installed yet (v2
#      refuses to finalize over one), and the node's admission input is in place:
#      TN_ADMISSION_VIA=devnet (the bench): <DATA_DIR>/network-config from
#      devnet-network-config.sh configures Closed admission (the file's bytes come back and
#      are checked here; see _nc_verdict). The node reads that file once, at its first
#      start; when it is missing the node writes the default (admission Open).
#      TN_ADMISSION_VIA=native (the devnet): the maps devnet-network-config.sh --yes
#      installed, ADMISSION_HOST_DIR/bootstrap-peers.yaml and, for a validator or observer,
#      ADMISSION_HOST_DIR/trusted-nodes.yaml, have the sha256 of the local
#      ADMISSION_MAPS_DIR/<NODE_NAME>.bootstrap-peers.yaml / .trusted-nodes.yaml (an rpc node
#      has no trusted map). The same ssh records where the logs
#      end (size + checksum of each log file A4 reads, and the journal cursor), so A4 reads
#      only what this finalize produced.
#   2. stage committee.yaml + genesis.yaml + parameters.yaml (PARAMETERS_FILE): scp to
#      /tmp, then `sudo install -o root -g root -m 0644` into the genesis dir (root 0755).
#      Nothing is chowned to the service user: setup-node.sh copies the three files into
#      the data dir AS the service user, which only needs to read them.
#   3. setup-node.sh --json --phase=finalize ... It counts only with ssh rc 0 AND a done
#      event carrying "ok":true (stdout is JSON events only; the human log is stderr).
#      --public-rpc-url https://<tn_public_domain>, and --public-ws-url wss://<the same>
#      only for a node without a worker gateway (tn_gateway_mode none: every node on the
#      bench, the rpc node on the devnet; the gateway carries no WebSocket).
#      TN_ADMISSION_VIA=native adds --admission <tn_admission_mode> --bootstrap-peers
#      <host bootstrap map> and, for a validator or observer, --trusted-nodes <host trusted
#      map>: setup-node.sh installs copies under /etc/telcoin, records them in .node-meta
#      and renders <DATA_DIR>/network-config from them before the first start.
#   4. wait_healthy (devnet-lib.sh): unit active AND the healthcheck port answers (GET / on
#      127.0.0.1:43174, the node's liveness route: 200 once the listener is bound). It
#      needs no peer, committee or block, so a lone genesis validator, node 5 before the
#      rpc node runs, and the rpc node before any validator runs all pass it.
# Phase B, per node that passed phase A. Each assertion prints one ✓/✗ line with what it
# observed; any ✗ fails the node and the run.
#   A1 telcoin stays active for FINALIZE_STABLE_SECS (60), polled every
#      FINALIZE_STABLE_POLL_SECS (10), with NRestarts = 0, and is-enabled = enabled.
#      Active but not enabled is a latent outage: the node never comes back from a reboot
#      (devnet genesis reset 2026-09-17).
#   A2 .node-meta NETWORK=devnet, and DOCKER_IMAGE_DIGEST equal to the digest part of
#      DOCKER_IMAGE (v2 records ${DOCKER_IMAGE##*@}: sha256:<hex>, prefix included).
#   A3 <DATA_DIR>/network-config still configures Closed admission (the gate's check, on
#      the file as it is now). Finalize adds (or rewrites) only its `hostname: "<name>"`
#      line, from --advertised-name; that line is shown, not required.
#      TN_ADMISSION_VIA=native: the file setup-node.sh rendered holds one admission block
#      with the node's mode (Closed; Open for rpc) and one committee_peers, and
#      devnet-network-config.py validate --native --node <node> passes on it.
#   A4 the logs this finalize produced hold none of `bad yaml data`, `committee_peers:`,
#      `trusted_nodes[`, `bootstrap_peers[` (config errors: the node exits at start and
#      systemd restarts it) and no `panicked`, and are not empty. TN_ADMISSION_VIA=native
#      also counts `committee_peers: missing validator` on its own line of the summary
#      (the node's refusal of a bootstrap-peers map without every committee member). Files: the unit's
#      StandardOutput/StandardError append: files (/var/log/telcoin/telcoin.log +
#      telcoin-error.log) and NODE_LOG_DIR/telcoin.log when .node-meta records one, each
#      read past the size the gate recorded; the whole file when it was absent or empty
#      then, when its first <size> bytes no longer match the gate's checksum (v2 finalize
#      truncates both append: files before the start, setup-node.sh:1231-1232), or when
#      the gate has no record of it. Journal: the unit's entries after the gate's cursor
#      (this boot when the gate got none); a journalctl error fails A4.
#   A5 ExecStart is /usr/local/libexec/telcoin/tn-start-docker; the container `telcoin` is
#      running DOCKER_IMAGE with a read-only rootfs; the docker client the unit runs
#      (MainPID) was started with --pull=never and --read-only (docker inspect does not
#      record the pull policy, so the launch line is the evidence); and no
#      TN_BLS_PASSPHRASE in /proc/<pid>/environ of the container's process (docker
#      inspect .State.Pid) or of any `telcoin node` process on the host.
#   A6 (TN_ADMISSION_VIA=native only) .node-meta ADMISSION_MODE = tn_admission_mode,
#      BOOTSTRAP_PEERS_FILE=/etc/telcoin/bootstrap-peers.yaml, and TRUSTED_NODES_FILE=
#      /etc/telcoin/trusted-nodes.yaml for a validator or observer, empty or absent for an
#      rpc node (setup-node.sh prepare_node_extra_flags records the installed copies).
#
# Read-only probes (the readiness gate, A1, A3, A4, A5, every .node-meta read) and the
# --stage-only stop, which is safe to run twice, retry ONCE, FINALIZE_RO_RETRY_SECS (5)
# later, when ssh returns 255: one IAP drop is never evidence about the node (lessons
# 2026-11-02). A second 255 fails as before; FINALIZE_RO_RETRY_SECS=0 turns the retry off.
#
# Modes: at most one flag, anywhere among the targets. Without one the run is the above.
# Genesis validators must start within ~50 rounds of each other or a late one sits out the
# whole epoch (lessons 2026-11-02), so the fleet can be finalized with every unit left
# stopped, then started at one moment:
#   --stage-only   phase A as above, then per node: require ActiveState=active and
#                  NRestarts=0, stop the unit (systemctl stop, then systemctl reset-failed:
#                  the docker-wrapped unit can end `failed` once the docker client exits 143
#                  on SIGTERM; the unit stays enabled) and require ActiveState=inactive,
#                  UnitFileState=enabled and no running container. Prints
#                  `STAGED <inst> state=inactive enabled=enabled`. The readiness probe decides
#                  first: a unit installed, inactive and enabled prints `PRESTAGED <inst>`
#                  and the node is skipped; an active one prints `RUNNING <inst>` and a
#                  warning (a quorum may have formed) and is skipped, never stopped. Any other
#                  installed unit fails the gate as above. No phase B. Each node runs alone,
#                  from its finalize to its stop, so no quorum forms (FINALIZE_JOBS=N: at most
#                  N at once, see below); a node that fails after finalize started it is left
#                  as it is (exit 1).
#   --start-all    every target must have the unit installed and enabled: inactive ones are
#                  started, an active one prints `RUNNING <inst>` and is skipped; any other
#                  state, or no answer, stops the run (exit 1) before any start. due = now +
#                  FINALIZE_START_LEAD_SECS (60). One background ssh per node, launched
#                  FINALIZE_START_LAUNCH_GAP_SECS (1) apart, sleeps on the NODE clock until
#                  due, runs `systemctl start` and prints
#                  `START_AT <inst> due=<unix> began=<unix> late_secs=<began-due>`. The probe
#                  is idempotent: the attempt that starts records began in
#                  /run/tn-start-at.<due>, and a later attempt prints that record and starts
#                  nothing; an attempt that reaches the node after due +
#                  FINALIZE_START_SPREAD_WARN_SECS starts nothing (start_rc=late, the node
#                  fails). An ssh rc 255 with no answer is retried, up to 3 attempts, only
#                  while now < due - 10. The wait ends at due + FINALIZE_START_TIMEOUT_SECS
#                  (120); a probe still running then is killed and its node fails. Then
#                  wait_healthy per started node, then one
#                  stdout line, integers only:
#                  `COORDINATED_START due=<unix> nodes=<targets> started=<n> skipped_running=<n> spread_secs=<max-min began> max_late_secs=<max began-due>`
#                  (both 0 when nothing started), a warning on stderr when spread_secs >
#                  FINALIZE_START_SPREAD_WARN_SECS (10), then phase B on every node that is up
#                  (A4 reads what came after the start check).
#   --defer-start  --stage-only, then --start-all on the same targets in the same run, only
#                  when every target is STAGED or PRESTAGED (else nothing starts, exit 1).
#   --verify       phase B only, on nodes with an installed unit (A4 has no gate record: it
#                  reads the whole log files and this boot's journal).
#
# Release-signature gate (config.sh RELEASE_TAG; empty skips it and changes nothing else).
# Runs after the local artifact + digest checks and before the PyYAML check and any
# gcloud/ssh: ./devnet-release-sign.sh verify checks releases/<tag>/SHA256SUMS.asc with
# gpgv against the RELEASE_KEYS_DIR allow-list, and SHA256SUMS against IMAGE_DIGEST and
# the chain configs. Verified (rc 0): one ✓ line, the run goes on. Signature absent (rc 3):
# the sign script's RELEASE_SIG_PENDING line reaches stdout, a hint goes to stderr, and
# finalize exits 3 with no node touched. Bad or unlisted signature, hash or digest
# mismatch, missing file, usage or tooling error (any other rc): ❌, exit 1.
# Bypass, devnet only: TN_SKIP_RELEASE_SIG=1 lets a PENDING signature (rc 3) through
# behind a ⚠️ banner on stdout and stderr. A FAILED verification is never bypassable.
#
# SECURITY: finalize takes NO secret. v2 keygen stored the BLS passphrase on the node (a
# systemd credential, or a root-only file below systemd 250) and the unit loads it from
# there, so this script never resolves, sends or logs a passphrase.
#
# Usage:
#   ./devnet-finalize.sh                    # every node host (tn_node_indices)
#   ./devnet-finalize.sh node1 node3        # subset by NODE_NAME
#   ./devnet-finalize.sh rpc-6-devnet       # subset by INSTANCE_NAME
#   ./devnet-finalize.sh 0 5                # subset by index (0-based)
#   ./devnet-finalize.sh --stage-only       # finalize every node, leave each stopped + enabled
#   ./devnet-finalize.sh --start-all        # then: one coordinated start, then A1-A5
#   ./devnet-finalize.sh --defer-start      # both, in one run
#   ./devnet-finalize.sh --verify node4     # A1-A5 only (e.g. after a transient ssh drop)
# Targets are node hosts only (roles validator, observer, rpc): no target means every one of
# them, and a gateway entry named as a target is refused (exit 2), like an unknown target.
# An unknown target stops the run before any node is touched; so do an unknown --option and
# a second mode flag (usage on stderr). A1-A5 below means A1-A6 with TN_ADMISSION_VIA=native.
# Knobs (env, whole seconds): FINALIZE_STABLE_SECS (60), FINALIZE_STABLE_POLL_SECS (10),
# FINALIZE_RO_RETRY_SECS (5), FINALIZE_START_LEAD_SECS (60), FINALIZE_START_LAUNCH_GAP_SECS
# (1), FINALIZE_START_TIMEOUT_SECS (120), FINALIZE_START_SPREAD_WARN_SECS (10).
# FINALIZE_JOBS (1, a whole number of nodes): how many nodes phase A, and then phase B,
# work on at once. 1 is the serial run, byte for byte. With N > 1 each node's phase A (then
# each node's phase B) runs in a background job, at most N at a time, started in target
# order; a node's stdout and stderr are held until it is done and printed in target order,
# so stdout reads as the serial run's (a note per phase on stderr says so). A job that stops
# without an outcome fails its node, never the run. The coordinated start and --verify's
# unit check stay serial. In --stage-only / --defer-start up to N finalized units run at
# once before their stops: N must be below a quorum (2n/3 + 1) of the n validators in
# NODE_ROLES, else the run is refused (exit 2).
# NETCFG_TRUST_OBSERVERS_EVERYWHERE (0 or 1): set it to what devnet-network-config.sh used. 1 =
# every validator trusts every observer and each observer every validator, so the gate and A3
# validate each network-config with devnet-network-config.py's --trust-observers-everywhere
# context; 0 = the hub-only context above.
# Exit: 0 every targeted node finalized and passed A1-A5; 1 a node failed, or a local
# check did (a failed release-signature verification included); 2 bad target (unknown, or
# a gateway entry), or a TN_ADMISSION_VIA other than devnet or native; 3 release
# signature pending (RELEASE_SIG_PENDING), no node touched.
# With a mode: 0 means --stage-only every target STAGED, PRESTAGED or RUNNING (RUNNING is
# reported, not failed); --start-all / --defer-start every target started or already
# running, and passed A1-A5; --verify every target passed A1-A5. 1 any other outcome
# (--defer-start: also a RUNNING node, which stops the start). 2 also a bad option, two mode
# flags, a knob that is not whole seconds, a NETCFG_TRUST_OBSERVERS_EVERYWHERE other than 0
# or 1, or a FINALIZE_JOBS that is not a whole number of 1 or more, or reaches a quorum in
# --stage-only / --defer-start.

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

FINALIZE_STABLE_SECS="${FINALIZE_STABLE_SECS:-60}"
FINALIZE_STABLE_POLL_SECS="${FINALIZE_STABLE_POLL_SECS:-10}"
TN_START_DOCKER="/usr/local/libexec/telcoin/tn-start-docker"   # v2 tn_start_script_path docker
case "${FINALIZE_STABLE_SECS}${FINALIZE_STABLE_POLL_SECS}" in
    *[!0123456789]*) echo "❌ FINALIZE_STABLE_SECS / FINALIZE_STABLE_POLL_SECS must be whole seconds" >&2; exit 2 ;;
esac
if [ "${FINALIZE_STABLE_POLL_SECS}" -lt 1 ]; then FINALIZE_STABLE_POLL_SECS=1; fi
# The read-only retry and the mode knobs (see the header), whole seconds like the two above.
FINALIZE_RO_RETRY_SECS="${FINALIZE_RO_RETRY_SECS:-5}"
FINALIZE_START_LEAD_SECS="${FINALIZE_START_LEAD_SECS:-60}"
FINALIZE_START_LAUNCH_GAP_SECS="${FINALIZE_START_LAUNCH_GAP_SECS:-1}"
FINALIZE_START_TIMEOUT_SECS="${FINALIZE_START_TIMEOUT_SECS:-120}"
FINALIZE_START_SPREAD_WARN_SECS="${FINALIZE_START_SPREAD_WARN_SECS:-10}"
case "${FINALIZE_RO_RETRY_SECS}${FINALIZE_START_LEAD_SECS}${FINALIZE_START_LAUNCH_GAP_SECS}${FINALIZE_START_TIMEOUT_SECS}${FINALIZE_START_SPREAD_WARN_SECS}" in
    *[!0123456789]*) echo "❌ FINALIZE_RO_RETRY_SECS / FINALIZE_START_{LEAD,LAUNCH_GAP,TIMEOUT,SPREAD_WARN}_SECS must be whole seconds" >&2; exit 2 ;;
esac
# Base 10 (08 is not octal) before they reach $(( )).
FINALIZE_RO_RETRY_SECS=$((10#${FINALIZE_RO_RETRY_SECS}))
FINALIZE_START_LEAD_SECS=$((10#${FINALIZE_START_LEAD_SECS}))
FINALIZE_START_LAUNCH_GAP_SECS=$((10#${FINALIZE_START_LAUNCH_GAP_SECS}))
FINALIZE_START_TIMEOUT_SECS=$((10#${FINALIZE_START_TIMEOUT_SECS}))
FINALIZE_START_SPREAD_WARN_SECS=$((10#${FINALIZE_START_SPREAD_WARN_SECS}))
# FINALIZE_JOBS (1): nodes in phase A / phase B at once (see the header); 1 = the serial run.
FINALIZE_JOBS="${FINALIZE_JOBS:-1}"
case "${FINALIZE_JOBS}" in
    *[!0123456789]*) FINALIZE_JOBS=0 ;;
    *) FINALIZE_JOBS=$((10#${FINALIZE_JOBS})) ;;
esac
if [ "${FINALIZE_JOBS}" -lt 1 ]; then
    echo "❌ FINALIZE_JOBS must be a whole number of nodes, 1 or more" >&2; exit 2
fi
# NETCFG_TRUST_OBSERVERS_EVERYWHERE (0): the trust context the network-configs were rendered
# with (devnet-network-config.sh's knob of the same name); the gate and A3 validate with it.
NETCFG_TRUST_OBSERVERS_EVERYWHERE="${NETCFG_TRUST_OBSERVERS_EVERYWHERE:-0}"
case "${NETCFG_TRUST_OBSERVERS_EVERYWHERE}" in
    0|1) ;;
    *) echo "❌ NETCFG_TRUST_OBSERVERS_EVERYWHERE must be 0 or 1 (got '${NETCFG_TRUST_OBSERVERS_EVERYWHERE}')" >&2; exit 2 ;;
esac
# TN_ADMISSION_VIA (config.sh; unset = devnet): devnet = the node reads the network-config
# devnet-network-config.sh rendered and installed (the bench); native = setup-node.sh renders
# it from the admission maps this run passes (--admission, --bootstrap-peers, --trusted-nodes).
ADMISSION_VIA="${TN_ADMISSION_VIA:-devnet}"
case "${ADMISSION_VIA}" in
    devnet|native) ;;
    *) echo "❌ TN_ADMISSION_VIA must be devnet or native (got '${ADMISSION_VIA}')" >&2; exit 2 ;;
esac
_native() { [ "${ADMISSION_VIA}" = "native" ]; }
if _native && { [ -z "${ADMISSION_HOST_DIR:-}" ] || [ -z "${ADMISSION_MAPS_DIR:-}" ]; }; then
    echo "❌ TN_ADMISSION_VIA=native needs ADMISSION_HOST_DIR and ADMISSION_MAPS_DIR (config.sh)" >&2; exit 2
fi

# Same selector as devnet-network-config.sh: no args → every node host (tn_node_indices:
# roles validator, observer, rpc; never a gateway entry); args may be an index (0-based),
# an INSTANCE_NAME, or a NODE_NAME. A node named twice is visited once. An unknown target,
# or one that runs no node (a gateway entry), is an error (rc 1), never a silent empty run.
tn_select_indices() {
    local out=() arg i matched
    if [ "$#" -eq 0 ]; then
        tn_node_indices; return 0
    fi
    for arg in "$@"; do
        matched=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                if ! tn_is_node_index "${i}"; then
                    echo "❌ ${arg} is a '${NODE_ROLES[$i]:-}' entry, not a node host: finalize visits only validator, observer and rpc hosts" >&2
                    return 1
                fi
                case " ${out[*]+"${out[*]}"} " in *" ${i} "*) ;; *) out+=("$i") ;; esac
                matched=1; break
            fi
        done
        if [ -z "${matched}" ]; then
            echo "❌ unknown target: ${arg} (expected an index, INSTANCE_NAME, or NODE_NAME)" >&2
            return 1
        fi
    done
    printf '%s\n' "${out[@]}"
}

_usage() {
    cat >&2 <<'EOF'
usage: ./devnet-finalize.sh [--stage-only | --start-all | --defer-start | --verify] [target ...]
  (no mode)      stage, finalize and start each node in turn, then assert A1-A5
  --stage-only   finalize each node, then leave it stopped and enabled (STAGED / PRESTAGED / RUNNING)
  --start-all    start every staged node at one moment (START_AT, COORDINATED_START), then A1-A5
  --defer-start  --stage-only, then --start-all on the same targets, in one run
  --verify       A1-A5 only, on nodes with an installed unit
  target         an index (0-based), an INSTANCE_NAME or a NODE_NAME of a node host
                 (validator, observer, rpc); none = every node host; a gateway entry is refused
At most one mode flag, anywhere among the targets. With TN_ADMISSION_VIA=native, A1-A5 is A1-A6.
Knobs: see the header of this script.
EOF
}

# The mode flag comes out of the arguments here; the rest are targets. An unknown --option
# or a second mode flag stops the run (usage, exit 2) before any gcloud or ssh call.
FINALIZE_MODE=""
_targets=()
for _a in "$@"; do
    case "${_a}" in
        --stage-only|--start-all|--defer-start|--verify)
            if [ -n "${FINALIZE_MODE}" ]; then
                echo "❌ one mode flag at most: --${FINALIZE_MODE} and ${_a}" >&2
                _usage; exit 2
            fi
            FINALIZE_MODE="${_a#--}" ;;
        --*) echo "❌ unknown option: ${_a}" >&2; _usage; exit 2 ;;
        *) _targets+=("${_a}") ;;
    esac
done
set -- ${_targets[@]+"${_targets[@]}"}
unset _a _targets

# Resolve the targets first: an unknown one stops the run (exit 2) before anything else.
if ! SELECTION="$(tn_select_indices "$@")"; then exit 2; fi
# macOS /bin/bash is 3.2 and lacks `mapfile`; this read-loop is the portable equivalent.
INDICES=()
while IFS= read -r _idx; do
    if [ -n "${_idx}" ]; then INDICES+=("${_idx}"); fi
done <<< "${SELECTION}"
if [ "${#INDICES[@]}" -eq 0 ]; then
    echo "❌ no target nodes (INSTANCE_NAMES is empty?)" >&2
    exit 2
fi
# --stage-only / --defer-start with FINALIZE_JOBS=N > 1: up to N finalized units run at once
# before their stops. N must stay below a quorum (2n/3 + 1, as the node computes it) of the
# fleet's n validators, or the staged start could have a quorum running before its due.
case "${FINALIZE_JOBS}:${FINALIZE_MODE}" in
    1:*) ;;
    *:stage-only|*:defer-start)
        _nval=0
        for _r in ${NODE_ROLES[@]+"${NODE_ROLES[@]}"}; do
            if [ "${_r}" = "validator" ]; then _nval=$((_nval + 1)); fi
        done
        _q=$((2 * _nval / 3 + 1))
        if [ "${FINALIZE_JOBS}" -ge "${_q}" ]; then
            echo "❌ FINALIZE_JOBS=${FINALIZE_JOBS} with --${FINALIZE_MODE}: that many units could run at once between finalize and stop, a quorum (${_q}) of this fleet's ${_nval} validators; use FINALIZE_JOBS=$(( _q > 2 ? _q - 1 : 1 )) or less" >&2
            exit 2
        fi
        unset _r _nval _q ;;
esac

# Local genesis artifacts produced by devnet-genesis-build.sh (in GENESIS_WORKSPACE,
# which config.sh sets to REPO_ROOT for devnet).
GENESIS_LOCAL_DIR="${GENESIS_WORKSPACE:-${REPO_ROOT}}/genesis"
COMMITTEE_LOCAL="${GENESIS_LOCAL_DIR}/committee.yaml"
GENESIS_LOCAL="${GENESIS_LOCAL_DIR}/genesis.yaml"

echo ">>> verifying local genesis artifacts"
for f in "${COMMITTEE_LOCAL}" "${GENESIS_LOCAL}" "${PARAMETERS_FILE}"; do
    if [ ! -f "${f}" ]; then
        echo "❌ missing ${f}. Run ./devnet-genesis-build.sh first." >&2
        exit 1
    fi
done

# v2 on devnet takes the image by digest only (setup-node.sh refuses a tag on the node);
# say so here, before any node is touched. The digest part is what A2 compares.
IMAGE_DIGEST="${DOCKER_IMAGE##*@}"
_hex="${IMAGE_DIGEST#sha256:}"
case "${DOCKER_IMAGE}" in *@sha256:*) ;; *) _hex="" ;; esac
case "${_hex}" in *[!0123456789abcdef]*) _hex="" ;; esac
if [ "${#_hex}" -ne 64 ]; then
    echo "❌ DOCKER_IMAGE='${DOCKER_IMAGE}' is not <repository>@sha256:<64 lower-case hex> (config.sh: fill in the pushed digest)" >&2
    exit 1
fi
unset _hex

# Release-signature gate (config.sh RELEASE_TAG; empty skips it). Runs before any gcloud
# or ssh call, so a pending or failed signature leaves every node untouched. The sign
# script's output is not captured: its RELEASE_SIG_PENDING line reaches stdout as is.
if [ -n "${RELEASE_TAG:-}" ]; then
    echo ">>> verifying release signature (${RELEASE_TAG})"
    _sig_rc=0
    "${DEVNET_LIB_DIR}/devnet-release-sign.sh" verify || _sig_rc=$?
    case "${_sig_rc}" in
        0)
            echo "    ✓ release ${RELEASE_TAG}: SHA256SUMS.asc verified against the release keys" ;;
        3)
            if [ "${TN_SKIP_RELEASE_SIG:-}" = "1" ]; then
                _sig_banner() {
                    echo "⚠️  =========================================================================="
                    echo "⚠️  RELEASE SIGNATURE BYPASSED (TN_SKIP_RELEASE_SIG=1) — nodes start on an UNSIGNED release; devnet only"
                    echo "⚠️  release ${RELEASE_TAG}: releases/${RELEASE_TAG}/SHA256SUMS.asc is absent and was NOT verified."
                    echo "⚠️  Unset TN_SKIP_RELEASE_SIG once the release is signed."
                    echo "⚠️  =========================================================================="
                }
                _sig_banner
                _sig_banner >&2
                unset -f _sig_banner
            else
                echo "    sign releases/${RELEASE_TAG}/SHA256SUMS on the signing machine, place SHA256SUMS.asc beside it," >&2
                echo "    then re-run ./devnet-finalize.sh or ./devnet-deploy.sh --yes --from 8" >&2
                exit 3
            fi ;;
        *)
            echo "❌ release ${RELEASE_TAG}: signature verification FAILED (devnet-release-sign.sh verify rc ${_sig_rc}); no node was touched." >&2
            if [ "${TN_SKIP_RELEASE_SIG:-}" = "1" ]; then
                echo "   TN_SKIP_RELEASE_SIG=1 bypasses only a pending signature, never a failed verification." >&2
            fi
            exit 1 ;;
    esac
    unset _sig_rc
fi

# The gate and A3 run devnet-network-config.py's validator on each node's network-config,
# with the context devnet-network-config.sh --verify gives it (the fleet in config.sh
# order, hub = the first validator, --trust-observers-everywhere when
# NETCFG_TRUST_OBSERVERS_EVERYWHERE=1), so python3 + PyYAML are needed here too.
NC_PY="${DEVNET_LIB_DIR}/devnet-network-config.py"
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import yaml' >/dev/null 2>&1; then
    echo "❌ python3 with PyYAML is needed to validate each node's network-config (sudo apt-get install python3-yaml)" >&2
    exit 1
fi
# --nodes: <NODE_NAME>=<role> for every node host (tn_node_indices), in array order; a
# gateway entry never appears (on the bench every entry is a validator or an observer).
NODES_SPEC=""
HUB=""
for _n in $(tn_node_indices); do
    NODES_SPEC="${NODES_SPEC:+${NODES_SPEC},}${NODE_NAMES[$_n]}=${NODE_ROLES[$_n]}"
    if [ -z "${HUB}" ] && [ "${NODE_ROLES[$_n]}" = "validator" ]; then HUB="${NODE_NAMES[$_n]}"; fi
done
unset _n
NC_CTX=(--committee "${COMMITTEE_LOCAL}" --genesis-dir "${GENESIS_LOCAL_DIR}" --nodes "${NODES_SPEC}" --hub "${HUB}")
# The trust-observers knob shapes the devnet-rendered file only; native trust comes from roles.
if [ "${NETCFG_TRUST_OBSERVERS_EVERYWHERE}" = 1 ] && ! _native; then NC_CTX+=(--trust-observers-everywhere); fi

# Native admission (TN_ADMISSION_VIA=native): the local maps devnet-network-config.sh rendered,
# and setup-node.sh's config dir, where it installs its copies of them (CONFIG_DIR default).
ADMISSION_LOCAL_DIR="${GENESIS_WORKSPACE:-${REPO_ROOT}}/${ADMISSION_MAPS_DIR:-}"
TN_CONFIG_DIR="/etc/telcoin"
# _has_trusted_map <i> — rc 0 when node i gets a trusted-nodes map (validator, observer).
_has_trusted_map() {
    case "${NODE_ROLES[$1]:-}" in validator|observer) return 0 ;; esac
    return 1
}
# _sha256 <file> — the file's sha256, lower-case hex (python3 is required above anyway).
_sha256() {
    python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
}
# _mode_word <i> — the node's admission mode as network-config spells it (Closed, Open).
_mode_word() {
    case "$(tn_admission_mode "$1")" in open) echo Open ;; grace) echo Grace ;; *) echo Closed ;; esac
}

# v2's LOG_DIR default (lib/common.sh:55): the unit appends to <dir>/<service>.log and
# <dir>/<service>-error.log (setup-node.sh:1083-1084). The gate records where those end.
TN_LOG_DIR="/var/log/telcoin"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/tn-finalize.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

# --- remote probes ------------------------------------------------------------------
# Each probe is a small root script run as `sudo bash -c '<script>' _ <args...>` over
# tn_iap_ssh. The script text comes from a quoted heredoc (nothing expands locally) and
# holds no single quote; its inputs travel as positional arguments. Its first line names
# it (`# tn-probe: <name>`), it prints KEY=value lines, and its last line is the
# __tn_probe_done sentinel, so a probe that did not run to the end is never read as a
# pass. Exit status is always the final echo's: the answer is in the lines, not the rc.

_rs_done() { echo "echo __tn_probe_done"; }

# The network-config at $nc, byte for byte as base64 on one line (shared by the gate and
# A3; _nc_verdict judges it locally). base64 keeps a BOM or a CR that _tn_probe's CR strip
# would otherwise hide.
_rs_nc_lines() {
    cat <<'EOF'
if [ -f "$nc" ]; then echo nc_present=1; echo "nc_b64=$(base64 < "$nc" | tr -d "\n")"; else echo nc_present=0; fi
EOF
}

# ready: $1 setup script, $2 service, $3 data dir to use when .node-meta has none, $4 v2
# log dir. Also prints, for A4, a logmark=<size>:<cksum crc>:<path> line per log file
# (0:-:<path> when absent) and jcursor=, the journal's last cursor.
_rs_ready() {
    cat <<'EOF'
# tn-probe: ready
setup="$1"; svc="$2"; meta=/etc/telcoin/.node-meta
if [ -f "$setup" ]; then echo setup=1; else echo setup=0; fi
if [ -f "$meta" ] && grep -q "^PASSPHRASE_METHOD=." "$meta"; then echo keygen=1; else echo keygen=0; fi
unit="/etc/systemd/system/$svc.service"
if [ -e "$unit" ] || [ -L "$unit" ]; then echo installed=1; else echo installed=0; fi
data=$(sed -n "s/^DATA_DIR=//p" "$meta" 2>/dev/null | tr -d "\r" | tail -n 1)
nodelog=$(sed -n "s/^NODE_LOG_DIR=//p" "$meta" 2>/dev/null | tr -d "\r" | tail -n 1)
for f in "$4/$svc.log" "$4/$svc-error.log" ${nodelog:+"$nodelog/telcoin.log"}; do
    if [ -f "$f" ]; then ck=$(cksum < "$f"); echo "logmark=${ck#* }:${ck%% *}:$f"; else echo "logmark=0:-:$f"; fi
done
echo "jcursor=$(journalctl -n 1 --no-pager --show-cursor -o cat 2>/dev/null | sed -n "s/^-- cursor: //p" | tail -n 1)"
nc="${data:-$3}/network-config"
echo "nc=$nc"
EOF
    # A mode's skip rules (PRESTAGED / RUNNING) read the unit's state from this probe.
    if [ -n "${FINALIZE_MODE}" ]; then _rs_unit_lines; fi
    if _native; then _rs_map_lines; else _rs_nc_lines; fi
    _rs_done
}

# Native admission ($5 = ADMISSION_HOST_DIR): the sha256 of each installed map, or missing.
_rs_map_lines() {
    cat <<'EOF'
if [ -f "$5/bootstrap-peers.yaml" ]; then echo "bp_sha=$(sha256sum < "$5/bootstrap-peers.yaml" | cut -c 1-64)"; else echo bp_sha=missing; fi
if [ -f "$5/trusted-nodes.yaml" ]; then echo "tn_sha=$(sha256sum < "$5/trusted-nodes.yaml" | cut -c 1-64)"; else echo tn_sha=missing; fi
EOF
}

# network-config: $1 the file.
_rs_nc() {
    cat <<'EOF'
# tn-probe: network-config
nc="$1"
EOF
    _rs_nc_lines
    _rs_done
}

# service: $1 service.
_rs_service() {
    cat <<'EOF'
# tn-probe: service
svc="$1"
echo "active=$(systemctl is-active "$svc" 2>/dev/null)"
echo "enabled=$(systemctl is-enabled "$svc" 2>/dev/null)"
echo "nrestarts=$(systemctl show -p NRestarts --value "$svc" 2>/dev/null)"
EOF
    _rs_done
}

# logs: $1 service, $2 NODE_LOG_DIR ("" when .node-meta has none), $3 the gate's logmark
# values (space-separated), $4 the gate's journal cursor. Reads only what came after the
# gate: a file past its recorded size while its first <size> bytes still match the
# recorded checksum, else the whole file (it was absent, empty, truncated or rewritten
# since, or the gate did not see it); the journal after the cursor. files= shows, per
# file, the bytes skipped and why.
_rs_logs() {
    cat <<'EOF'
# tn-probe: logs
svc="$1"; nodelog="$2"; marks="$3"; cur="$4"; seen=""; files=""
s=$(mktemp); j=$(mktemp)
for f in $(systemctl cat "$svc" 2>/dev/null | sed -n "s/^Standard[A-Za-z]*=append://p") ${nodelog:+$nodelog/telcoin.log}; do
    case " $seen " in *" $f "*) continue ;; esac
    seen="$seen $f"
    if [ ! -f "$f" ]; then continue; fi
    off=0; why=no-gate-record
    for m in $marks; do
        size=${m%%:*}; rest=${m#*:}; crc=${rest%%:*}
        if [ "${rest#*:}" != "$f" ]; then continue; fi
        if [ "$size" = 0 ]; then why=new-since-gate
        elif [ "$(head -c "$size" "$f" | cksum)" = "$crc $size" ]; then off=$size; why=after-gate
        else why=rewritten-since-gate; fi
    done
    tail -c +$((off + 1)) "$f" >> "$s"
    files="$files $f(skip=$off,$why)"
done
if [ -n "$cur" ]; then
    journalctl -u "$svc" --after-cursor="$cur" --no-pager -o cat > "$j" 2>/dev/null; jrc=$?; jfrom=after-gate-cursor
else
    journalctl -u "$svc" -b --no-pager -o cat > "$j" 2>/dev/null; jrc=$?; jfrom=this-boot
fi
echo "files=$files"
echo "journal=$(wc -l < "$j" | tr -d " ")"
echo "journal_from=$jfrom"
echo "journal_rc=$jrc"
echo "lines=$(cat "$s" "$j" | wc -l | tr -d " ")"
EOF
    # Native admission: the node's own refusal of an incomplete committee map gets its own count.
    if _native; then
        echo 'for p in "bad yaml data" "committee_peers:" "committee_peers: missing validator" "trusted_nodes[" "bootstrap_peers[" "panicked"; do'
    else
        echo 'for p in "bad yaml data" "committee_peers:" "trusted_nodes[" "bootstrap_peers[" "panicked"; do'
    fi
    cat <<'EOF'
    n=$(cat "$s" "$j" | grep -cF -- "$p")
    first=$(cat "$s" "$j" | grep -F -m 1 -- "$p" | tr -d "\r" | cut -c 1-160)
    echo "hit=$n|$p|$first"
done
rm -f "$s" "$j"
EOF
    _rs_done
}

# runtime: $1 service (= the container name v2 gives docker run --name).
# pgrep's pattern is written "telcoin[ ]node" so it cannot match this probe's own
# command line, which carries the pattern text.
_rs_runtime() {
    cat <<'EOF'
# tn-probe: runtime
svc="$1"
echo "execstart=$(systemctl cat "$svc" 2>/dev/null | sed -n "s/^ExecStart=//p" | tail -n 1)"
pid=$(systemctl show -p MainPID --value "$svc" 2>/dev/null)
echo "mainpid=$pid"
launch=""
if [ -n "$pid" ] && [ "$pid" != 0 ] && [ -r "/proc/$pid/cmdline" ]; then launch=$(tr "\0" " " < "/proc/$pid/cmdline"); fi
echo "launch_cmd=$(printf "%s" "$launch" | cut -c 1-40)"
case " $launch " in *" --pull=never "*) echo launch_pull=1 ;; *) echo launch_pull=0 ;; esac
case " $launch " in *" --read-only "*) echo launch_ro=1 ;; *) echo launch_ro=0 ;; esac
echo "container=$(docker inspect -f "{{.State.Running}} {{.HostConfig.ReadonlyRootfs}} {{.State.Pid}} {{.Config.Image}}" "$svc" 2>/dev/null)"
cpid=$(docker inspect -f "{{.State.Pid}}" "$svc" 2>/dev/null)
checked=""; hits=0
for p in $cpid $(pgrep -f "telcoin[ ]node" 2>/dev/null); do
    case " $checked " in *" $p "*) continue ;; esac
    if [ "$p" != 0 ] && [ -r "/proc/$p/environ" ]; then
        n=$(tr "\0" "\n" < "/proc/$p/environ" | grep -c TN_BLS_PASSPHRASE)
        hits=$((hits + n)); checked="$checked $p"
    fi
done
echo "env_pids=$checked"
echo "env_hits=$hits"
EOF
    _rs_done
}

# The unit's state in ONE systemctl call, as KEY=value lines (ActiveState=, SubState=,
# UnitFileState=, NRestarts=, Result=); needs $svc. A unit systemd does not know shows
# ActiveState=inactive with an empty UnitFileState.
_rs_unit_lines() {
    cat <<'EOF'
systemctl show -p ActiveState,SubState,UnitFileState,NRestarts,Result "$svc" 2>/dev/null
EOF
}

# unit: $1 service.
_rs_unit() {
    cat <<'EOF'
# tn-probe: unit
svc="$1"
EOF
    _rs_unit_lines
    _rs_done
}

# stop (--stage-only): $1 service. `systemctl stop` runs the unit's ExecStop (docker stop);
# the docker client then exits 143 and the unit can sit in `failed`, so reset-failed follows.
# The unit stays enabled. Reports both rcs, the state after, and whether a container named
# $1 still runs (container=true|false, empty when there is none).
_rs_stop() {
    cat <<'EOF'
# tn-probe: stop
svc="$1"
systemctl stop "$svc"; echo "stop_rc=$?"
systemctl reset-failed "$svc" >/dev/null 2>&1; echo "reset_rc=$?"
EOF
    _rs_unit_lines
    cat <<'EOF'
echo "container=$(docker inspect -f "{{.State.Running}}" "$svc" 2>/dev/null)"
EOF
    _rs_done
}

# start-check (--start-all): $1 service, $2 v2 log dir. The unit's state, plus the gate's
# logmark= / jcursor= lines, so A4 reads only what the coordinated start produced.
_rs_startcheck() {
    cat <<'EOF'
# tn-probe: start-check
svc="$1"; meta=/etc/telcoin/.node-meta
EOF
    _rs_unit_lines
    cat <<'EOF'
nodelog=$(sed -n "s/^NODE_LOG_DIR=//p" "$meta" 2>/dev/null | tr -d "\r" | tail -n 1)
for f in "$2/$svc.log" "$2/$svc-error.log" ${nodelog:+"$nodelog/telcoin.log"}; do
    if [ -f "$f" ]; then ck=$(cksum < "$f"); echo "logmark=${ck#* }:${ck%% *}:$f"; else echo "logmark=0:-:$f"; fi
done
echo "jcursor=$(journalctl -n 1 --no-pager --show-cursor -o cat 2>/dev/null | sed -n "s/^-- cursor: //p" | tail -n 1)"
EOF
    _rs_done
}

# start-at (--start-all): $1 service, $2 due (unix seconds), $3 instance, $4 late window
# (FINALIZE_START_SPREAD_WARN_SECS). Idempotent, so the driver can retry it: the attempt
# that starts the unit first records began (and the instance) in /run/tn-start-at.<due>,
# created atomically (ln of a complete temp file), then appends start_rc. An attempt that
# finds that file starts nothing: it waits up to 10 s for the recorded start_rc and prints
# the RECORDED began (start_attempt=repeat). With no file and the node clock past due +
# window, it starts nothing and prints start_rc=late (a late member sits out the epoch).
# Otherwise it waits on the NODE clock until due (whole seconds, then 50 ms steps). Prints
# start_rc= and the START_AT line; the node never starts before due.
_rs_start_at() {
    cat <<'EOF'
# tn-probe: start-at
svc="$1"; due="$2"; inst="$3"; window="$4"; mark="/run/tn-start-at.$due"; now=$(date +%s)
if [ ! -e "$mark" ] && [ "$now" -gt $((due + window)) ]; then
    echo "start_rc=late"
    echo "START_AT $inst due=$due began=$now late_secs=$((now - due))"
else
    won=""
    if [ ! -e "$mark" ]; then
        if [ $((due - now)) -gt 1 ]; then sleep $((due - now - 1)); fi
        while [ "$(date +%s)" -lt "$due" ]; do sleep 0.05; done
        tmp=$(mktemp /run/tn-start-at-tmp.XXXXXX)
        printf "inst=%s\nbegan=%s\n" "$inst" "$(date +%s)" > "$tmp"
        if ln "$tmp" "$mark" 2>/dev/null; then won=1; fi
        rm -f "$tmp"
    fi
    if [ -n "$won" ]; then
        systemctl start "$svc"; echo "start_rc=$?" >> "$mark"
        echo "start_attempt=first"
    else
        n=0
        while ! grep -q "^start_rc=" "$mark" 2>/dev/null && [ "$n" -lt 100 ]; do sleep 0.1; n=$((n + 1)); done
        echo "start_attempt=repeat"
    fi
    began=$(sed -n "s/^began=//p" "$mark" | tail -n 1)
    rc=$(sed -n "s/^start_rc=//p" "$mark" | tail -n 1)
    echo "start_rc=${rc:-unknown}"
    echo "START_AT $inst due=$due began=$began late_secs=$((began - due))"
fi
EOF
    _rs_done
}

# _tn_probe <instance> <zone> <script> [args...] — run one probe; print its output (CR
# stripped). rc 1, with the reason on stdout, when ssh failed or the sentinel is missing.
_tn_probe() {
    local inst="$1" zone="$2" script="$3" cmd a out rc=0
    shift 3
    case "${script}" in *"'"*) echo "internal: probe script holds a single quote"; return 1 ;; esac
    cmd="sudo bash -c '${script}' _"
    for a in "$@"; do
        case "${a}" in *"'"*) echo "internal: probe argument holds a single quote: ${a}"; return 1 ;; esac
        cmd="${cmd} '${a}'"
    done
    out="$(tn_iap_ssh "${inst}" "${zone}" "${cmd}" </dev/null 2>/dev/null)" || rc=$?
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    case "${out}" in
        *__tn_probe_done*) printf '%s\n' "${out}" ;;
        *) echo "no answer from ${inst} (ssh rc ${rc})"; return 1 ;;
    esac
}

# _ro <fn> [args...] — the read-only retry. Runs <fn> (_tn_probe with a probe that changes
# nothing, or one that is safe to run twice; tn_node_meta_get) in a subshell whose
# tn_iap_ssh, when ssh returns 255, waits FINALIZE_RO_RETRY_SECS and runs the same ssh ONCE
# more. Only the last attempt's stdout reaches <fn>; a second 255 fails as without _ro.
# The retry note goes to the caller's stderr. Never wrap a probe that must not run twice.
# _tn_iap_ssh_once is devnet-lib.sh's tn_iap_ssh, copied under that name.
eval "_tn_iap_ssh_once() $(declare -f tn_iap_ssh | sed 1d)"
_ro() {
    (
        exec 4>&2
        # shellcheck disable=SC2329  # invoked indirectly: _tn_probe / tn_node_meta_get call it
        tn_iap_ssh() {
            local out rc=0
            out="$(_tn_iap_ssh_once "$@")" || rc=$?
            if [ "${rc}" -eq 255 ] && [ "${FINALIZE_RO_RETRY_SECS}" -gt 0 ]; then
                echo "    … ssh rc 255 from ${1}; one retry in ${FINALIZE_RO_RETRY_SECS}s" >&4
                sleep "${FINALIZE_RO_RETRY_SECS}"
                rc=0
                out="$(_tn_iap_ssh_once "$@")" || rc=$?
            fi
            printf '%s\n' "${out}"
            return "${rc}"
        }
        "$@"
    )
}

# _kv <probe-output> <key> — the value of the last "key=" line ("" when absent).
_kv() { printf '%s\n' "$1" | sed -n "s/^$2=//p" | tail -n 1; }

# _num <value> — the value when it is a non-negative integer, else 0 (a missing or
# garbled count must read as "none found", never pass a numeric test by erroring).
_num() {
    case "${1:-}" in ""|*[!0123456789]*) printf '0' ;; *) printf '%s' "$1" ;; esac
}

# _nc_verdict <node> <nc_present> <nc_b64> [<Mode> native] — does this network-config (the
# node's exact bytes) configure Closed admission (or <Mode>: Closed, Open) for <node>? Prints
# one observation; rc 0 yes, 1 no. With `native` (TN_ADMISSION_VIA=native, A3), (b) is
# devnet-network-config.py validate --native, which compares the file setup-node.sh rendered
# with the admission maps by content.
#   (a) what the NODE's parser (serde_yaml 0.8) sees: no UTF-8 BOM (serde_yaml makes it
#       part of the first key), exactly one column-0 `admission:` whose block (up to the
#       next column-0 key) holds `mode: Closed`, and one column-0 `committee_peers:`.
#       The node ignores an unknown top-level key, so a misspelt `admission` runs Open.
#   (b) devnet-network-config.py validate --node <node>, as devnet-network-config.sh
#       --verify runs it: exact keys, shapes and content (a `hostname:` line is allowed).
#   (a) alone misses wrong content; (b) parses with PyYAML, which drops a BOM and expands
#   `<<` merge keys where serde_yaml does neither, so (a) reads the raw lines instead and
#   holds even where (b)'s own guards for those cases would not.
_nc_verdict() {
    local node="$1" present="$2" b64="$3" want="${4:-Closed}" native="${5:-}" f bad="" shape err host
    f="${WORK}/${node}/network-config"
    if [ "${present}" != "1" ]; then echo "missing"; return 1; fi
    mkdir -p "${WORK}/${node}"
    if ! printf '%s' "${b64}" | base64 --decode > "${f}" 2>/dev/null || [ ! -s "${f}" ]; then
        echo "empty or unreadable"; return 1
    fi
    if [ "$(head -c 3 "${f}" | od -An -tx1 | tr -d ' \n')" = "efbbbf" ]; then
        bad="${bad} starts with a UTF-8 BOM;"
    fi
    shape="$(awk -v want="${want}" '
        /^admission:[ \t]*$/ { adm++; inblock = 1; next }
        /^[^ \t#]/ { inblock = 0 }
        inblock && $0 ~ ("^[ \t]+mode:[ \t]*" want "[ \t]*$") { closed++ }
        /^committee_peers:[ \t]*$/ { peers++ }
        END { printf "admission:x%d mode-%s-in-it:x%d committee_peers:x%d", adm, want, closed, peers }' "${f}")"
    case "${shape}" in
        "admission:x1 mode-${want}-in-it:x1 committee_peers:x1") ;;
        *) bad="${bad} ${shape} (want x1 each);" ;;
    esac
    if ! err="$(python3 "${NC_PY}" validate ${native:+"--native"} "${NC_CTX[@]}" --node "${node}" "${f}" 2>&1 >/dev/null)"; then
        err="${err//"${f}"/network-config}"
        bad="${bad} validator: $(printf '%s\n' "${err}" | grep -c '^FAIL') error(s), first: $(printf '%s\n' "${err}" | grep -m 1 '^FAIL' | cut -c 6-220);"
    fi
    host="$(grep -m 1 '^hostname:' "${f}" || true)"
    if [ -n "${bad}" ]; then echo "NOT ${want}:${bad} ${host:-no hostname line}"; return 1; fi
    echo "${want} admission, committee_peers, validator${native:+ --native} ok for ${node}; ${host:-no hostname line}"
}

# _report <node> <rc> <label> <observed> — one assertion line.
_report() {
    local mark="✓"
    if [ "$2" -ne 0 ]; then mark="✗"; fi
    printf '    %s [%s] %s: %s\n' "${mark}" "$1" "$3" "$4"
}

# --- phase B assertions (each prints one line; rc 0 pass, 1 fail) ---------------------

# A1 <inst> <zone> <node> <svc>
assert_service() {
    local inst="$1" zone="$2" node="$3" svc="$4" script out st="" en="" nr="" waited=0 polls=0 bad=""
    script="$(_rs_service)"
    while :; do
        if ! out="$(_ro _tn_probe "${inst}" "${zone}" "${script}" "${svc}")"; then
            bad="${out} at ${waited}s"; break
        fi
        st="$(_kv "${out}" active)"; en="$(_kv "${out}" enabled)"; nr="$(_kv "${out}" nrestarts)"
        polls=$((polls + 1))
        if [ "${st}" != "active" ]; then bad="is-active=${st:-?} at ${waited}s"; break; fi
        if [ "${nr}" != "0" ]; then bad="NRestarts=${nr:-?} at ${waited}s"; break; fi
        if [ "${waited}" -ge "${FINALIZE_STABLE_SECS}" ]; then break; fi
        sleep "${FINALIZE_STABLE_POLL_SECS}"
        waited=$((waited + FINALIZE_STABLE_POLL_SECS))
    done
    if [ -z "${bad}" ] && [ "${en}" != "enabled" ]; then bad="is-enabled=${en:-?}"; fi
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A1 service" "${bad} (polls ${polls}; is-active=${st:-?} is-enabled=${en:-?} NRestarts=${nr:-?})"
        return 1
    fi
    _report "${node}" 0 "A1 service" "is-active=active for ${waited}s (${polls} polls), is-enabled=${en}, NRestarts=${nr}"
}

# A2 <inst> <zone> <node>. Also sets META_DATA_DIR / META_NODE_LOG_DIR for A3 / A4.
META_DATA_DIR=""
META_NODE_LOG_DIR=""
assert_meta() {
    local inst="$1" zone="$2" node="$3" net dig rc_net=0 rc_dig=0 rc_nl=0 bad=""
    net="$(_ro tn_node_meta_get "${inst}" "${zone}" NETWORK)" || rc_net=$?
    dig="$(_ro tn_node_meta_get "${inst}" "${zone}" DOCKER_IMAGE_DIGEST)" || rc_dig=$?
    META_DATA_DIR="$(_ro tn_node_meta_get "${inst}" "${zone}" DATA_DIR)" || META_DATA_DIR=""
    META_NODE_LOG_DIR="$(_ro tn_node_meta_get "${inst}" "${zone}" NODE_LOG_DIR 2>/dev/null)" || rc_nl=$?
    if [ "${rc_nl}" -ne 0 ]; then META_NODE_LOG_DIR=""; fi
    if [ "${rc_net}" -ne 0 ]; then net="<unread rc ${rc_net}>"; fi
    if [ "${rc_dig}" -ne 0 ]; then dig="<unread rc ${rc_dig}>"; fi
    if [ "${net}" != "devnet" ]; then bad=1; fi
    if [ "${dig}" != "${IMAGE_DIGEST}" ]; then bad=1; fi
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A2 node-meta" "NETWORK=${net} (want devnet), DOCKER_IMAGE_DIGEST=${dig} (want ${IMAGE_DIGEST})"
        return 1
    fi
    _report "${node}" 0 "A2 node-meta" "NETWORK=${net}, DOCKER_IMAGE_DIGEST=${dig}"
}

# A3 <inst> <zone> <node> <data-dir> [<Mode>] — with <Mode> (TN_ADMISSION_VIA=native), the
# file must hold that admission mode and pass validate --native.
assert_network_config() {
    local inst="$1" zone="$2" node="$3" nc="$4/network-config" out obs
    if ! out="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_nc)" "${nc}")"; then
        _report "${node}" 1 "A3 network-config" "${out}"; return 1
    fi
    if obs="$(_nc_verdict "${node}" "$(_kv "${out}" nc_present)" "$(_kv "${out}" nc_b64)" ${5:+"$5" native})"; then
        _report "${node}" 0 "A3 network-config" "${nc}: ${obs}"
        return 0
    fi
    _report "${node}" 1 "A3 network-config" "${nc}: ${obs}"
    return 1
}

# A6 <inst> <zone> <node> <index> (TN_ADMISSION_VIA=native only): what setup-node.sh's
# prepare_node_extra_flags recorded for the admission flags this run passed. A key that is
# absent reads as empty (setup-node.sh writes TRUSTED_NODES_FILE= when no map was passed).
assert_admission_meta() {
    local inst="$1" zone="$2" node="$3" i="$4" k v rc want obs="" bad=""
    for k in ADMISSION_MODE BOOTSTRAP_PEERS_FILE TRUSTED_NODES_FILE; do
        case "${k}" in
            ADMISSION_MODE) want="$(tn_admission_mode "${i}")" || want="?" ;;
            BOOTSTRAP_PEERS_FILE) want="${TN_CONFIG_DIR}/bootstrap-peers.yaml" ;;
            *) want=""; if _has_trusted_map "${i}"; then want="${TN_CONFIG_DIR}/trusted-nodes.yaml"; fi ;;
        esac
        rc=0
        v="$(_ro tn_node_meta_get "${inst}" "${zone}" "${k}")" || rc=$?
        if [ "${rc}" -eq 1 ]; then v=""; elif [ "${rc}" -ne 0 ]; then v="<unread rc ${rc}>"; fi
        obs="${obs:+${obs}, }${k}=${v}"
        if [ "${v}" != "${want}" ]; then bad="${bad} ${k} want '${want}';"; fi
    done
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A6 admission meta" "${obs};${bad}"
        return 1
    fi
    _report "${node}" 0 "A6 admission meta" "${obs}"
}

# A4 <inst> <zone> <node> <svc> <node-log-dir> <gate logmarks> <gate journal cursor>
assert_logs() {
    local inst="$1" zone="$2" node="$3" svc="$4" nodelog="$5" marks="$6" cursor="$7" out line rest n pat first
    local summary="" firsts="" bad="" lines files journal jrc
    if ! out="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_logs)" "${svc}" "${nodelog}" "${marks}" "${cursor}")"; then
        _report "${node}" 1 "A4 logs" "${out}"; return 1
    fi
    files="$(_kv "${out}" files)"; lines="$(_num "$(_kv "${out}" lines)")"; jrc="$(_kv "${out}" journal_rc)"
    journal="$(_kv "${out}" journal) lines $(_kv "${out}" journal_from)"
    if [ "${jrc}" != "0" ]; then journal="${journal}, journalctl rc ${jrc:-?}"; bad=1; fi
    while IFS= read -r line; do
        case "${line}" in hit=*) ;; *) continue ;; esac
        rest="${line#hit=}"; n="${rest%%|*}"; rest="${rest#*|}"; pat="${rest%%|*}"; first="${rest#*|}"
        n="$(_num "${n}")"
        summary="${summary} '${pat}'=${n}"
        if [ "${n}" -ne 0 ]; then
            bad=1
            firsts="${firsts}"$'\n'"        first '${pat}': ${first}"
        fi
    done <<< "${out}"
    if [ -z "${summary}" ]; then bad=1; summary=" no pattern counts returned"; fi
    if [ "${lines}" -eq 0 ]; then bad=1; summary="${summary} (no log lines since the gate to scan)"; fi
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A4 logs" "${lines} lines scanned (files:${files:- none}; journal: ${journal}):${summary}${firsts}"
        return 1
    fi
    _report "${node}" 0 "A4 logs" "${lines} lines scanned (files:${files:- none}; journal: ${journal}):${summary}"
}

# A5 <inst> <zone> <node> <svc>
assert_runtime() {
    local inst="$1" zone="$2" node="$3" svc="$4" out exe pull ro cont running rofs cimg pids hits obs bad=""
    if ! out="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_runtime)" "${svc}")"; then
        _report "${node}" 1 "A5 runtime" "${out}"; return 1
    fi
    exe="$(_kv "${out}" execstart)"; pull="$(_kv "${out}" launch_pull)"; ro="$(_kv "${out}" launch_ro)"
    cont="$(_kv "${out}" container)"; pids="$(_kv "${out}" env_pids)"; hits="$(_kv "${out}" env_hits)"
    running="${cont%% *}"; rofs="${cont#* }"; rofs="${rofs%% *}"; cimg="${cont##* }"
    if [ "${exe}" != "${TN_START_DOCKER}" ]; then bad="${bad} ExecStart;"; fi
    if [ "${running}" != "true" ]; then bad="${bad} container-not-running;"; fi
    if [ "${rofs}" != "true" ]; then bad="${bad} rootfs-not-read-only;"; fi
    if [ "${cimg}" != "${DOCKER_IMAGE}" ]; then bad="${bad} image;"; fi
    if [ "${pull}" != "1" ]; then bad="${bad} no--pull=never;"; fi
    if [ "${ro}" != "1" ]; then bad="${bad} no--read-only;"; fi
    if [ -z "${pids// /}" ]; then bad="${bad} no-node-pid-checked;"; fi
    if [ "${hits}" != "0" ]; then bad="${bad} TN_BLS_PASSPHRASE-in-environ;"; fi
    obs="ExecStart=${exe:-?}; container running=${running:-?} ReadonlyRootfs=${rofs:-?} image=${cimg:-?}; MainPID $(_kv "${out}" mainpid) '$(_kv "${out}" launch_cmd)...' --pull=never=${pull:-?} --read-only=${ro:-?}; TN_BLS_PASSPHRASE in environ of pids [${pids# }]: ${hits:-?}"
    if [ -n "${bad}" ]; then
        _report "${node}" 1 "A5 runtime" "MISS:${bad} ${obs}"; return 1
    fi
    _report "${node}" 0 "A5 runtime" "${obs}"
}

# --- modes: the stop (--stage-only) and the coordinated start (--start-all) -------------

# _defer_stop <inst> <zone> <service> — the --stage-only stop (_rs_stop; safe to run twice,
# so it goes through _ro). Requires ActiveState=inactive, UnitFileState=enabled and no
# running container afterwards. Prints "state=inactive enabled=enabled" (rc 0), or what it
# saw (rc 1).
_defer_stop() {
    local inst="$1" zone="$2" svc="$3" out st en cont
    if ! out="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_stop)" "${svc}")"; then
        echo "${out}"; return 1
    fi
    st="$(_kv "${out}" ActiveState)"; en="$(_kv "${out}" UnitFileState)"; cont="$(_kv "${out}" container)"
    if [ "${st}" != "inactive" ] || [ "${en}" != "enabled" ] || [ "${cont}" = "true" ]; then
        echo "after stop: ActiveState=${st:-?} SubState=$(_kv "${out}" SubState) Result=$(_kv "${out}" Result) UnitFileState=${en:-?} container-running=${cont:-none} (stop rc $(_kv "${out}" stop_rc), reset-failed rc $(_kv "${out}" reset_rc))"
        return 1
    fi
    echo "state=${st} enabled=${en}"
}

# _kill_tree <pid> — SIGTERM <pid> and every LOCAL process below it (the start-at probe's
# subshells, gcloud and ssh), so a probe still running at the deadline cannot report later.
# It does not stop a remote script that already connected (no pty, so no SIGHUP; it dies
# on its first write, after its systemctl start). What keeps a late connect from starting
# its node is the remote's own check: no start past due + FINALIZE_START_SPREAD_WARN_SECS.
_kill_tree() {
    local kids c
    kids="$(ps -A -o pid= -o ppid= 2>/dev/null | awk -v p="$1" '$2 == p { print $1 }')"
    kill "$1" 2>/dev/null || true
    for c in ${kids}; do _kill_tree "${c}"; done
}

# _start_all <index>... — the coordinated start (--start-all, and --defer-start once every
# target is staged). First a start check per node (read-only): any node that is not
# installed + enabled + (inactive | active) refuses the whole start (rc 1, nothing
# started). Then one background start-at probe per inactive node, the bounded wait, the
# START_AT lines, wait_healthy, the COORDINATED_START marker and the spread warning.
# Appends to finalized (nodes up: started and healthy, or RUNNING) and failed; records
# LOG_MARKS / JOURNAL_CURSORS from the start check, for A4.
_start_all() {
    local i inst zone node service out st en refused="" script due deadline k n f rc_s line began late
    local todo pids healthy nrun=0 started=0 bmin="" bmax="" maxlate="" spread=0 up=" "
    todo=(); pids=(); healthy=()
    echo ""
    echo ">>> coordinated start: checking ${#} node(s) (unit installed and enabled; inactive to start)"
    for i in "$@"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"; node="${NODE_NAMES[$i]}"
        service="$(tn_service_for_role "$(tn_node_role "$i")")"
        if ! out="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_startcheck)" "${service}" "${TN_LOG_DIR}")"; then
            echo "❌ [${node}] start check: ${out}"
            failed+=("${node}: start check (no answer)"); refused="${refused} ${node}"; continue
        fi
        st="$(_kv "${out}" ActiveState)"; en="$(_kv "${out}" UnitFileState)"
        LOG_MARKS[i]="$(printf '%s\n' "${out}" | sed -n 's/^logmark=//p' | tr '\n' ' ')"
        JOURNAL_CURSORS[i]="$(_kv "${out}" jcursor)"
        if [ "${en}" = "enabled" ] && [ "${st}" = "inactive" ]; then
            echo ">>> [${node}] ${service} on ${inst}: installed, enabled, inactive: will start"
            todo+=("${i}")
        elif [ "${en}" = "enabled" ] && [ "${st}" = "active" ]; then
            echo "RUNNING ${inst}"
            echo "⚠️  [${node}] ${service} on ${inst} is already running: not started again (skipped_running)" >&2
            nrun=$((nrun + 1)); up="${up}${i} "
        else
            echo "❌ [${node}] ${service} on ${inst}: ActiveState=${st:-?} SubState=$(_kv "${out}" SubState) Result=$(_kv "${out}" Result) UnitFileState=${en:-none} (want an installed, enabled unit, inactive or active)"
            failed+=("${node}: start check (${st:-?}/${en:-none})"); refused="${refused} ${node}"
        fi
    done
    if [ -n "${refused}" ]; then
        echo "❌ coordinated start refused, nothing was started:${refused}"
        return 1
    fi

    due=$(( $(date +%s) + FINALIZE_START_LEAD_SECS ))
    if [ "${#todo[@]}" -gt 0 ]; then
        echo ">>> coordinated start of ${#todo[@]} node(s): due=${due} (now + ${FINALIZE_START_LEAD_SECS}s, on each node's clock), one ssh per node ${FINALIZE_START_LAUNCH_GAP_SECS}s apart"
        if [ $(( (${#todo[@]} - 1) * FINALIZE_START_LAUNCH_GAP_SECS )) -ge "${FINALIZE_START_LEAD_SECS}" ]; then
            echo "⚠️  the last start-at ssh launches at or after due (FINALIZE_START_LEAD_SECS=${FINALIZE_START_LEAD_SECS}, ${#todo[@]} nodes x FINALIZE_START_LAUNCH_GAP_SECS=${FINALIZE_START_LAUNCH_GAP_SECS}): expect late starts" >&2
        fi
        script="$(_rs_start_at)"
        k=0
        for i in "${todo[@]}"; do
            if [ "${k}" -gt 0 ] && [ "${FINALIZE_START_LAUNCH_GAP_SECS}" -gt 0 ]; then sleep "${FINALIZE_START_LAUNCH_GAP_SECS}"; fi
            k=$((k + 1))
            inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
            service="$(tn_service_for_role "$(tn_node_role "$i")")"
            f="${WORK}/start-${i}"
            # The start-at probe is idempotent (/run/tn-start-at.<due>), so an ssh that
            # returned 255 with no answer is retried: at most 3 attempts in all, 1 s apart,
            # and only while the local clock is before due - 10. Nothing else is retried.
            (
                att=0
                while :; do
                    att=$((att + 1)); rc_s=0
                    out="$(_tn_probe "${inst}" "${zone}" "${script}" "${service}" "${due}" "${inst}" "${FINALIZE_START_SPREAD_WARN_SECS}")" || rc_s=$?
                    case "${rc_s}:${out}" in 1:*"(ssh rc 255)") ;; *) break ;; esac
                    if [ "${att}" -ge 3 ] || [ "$(date +%s)" -ge $((due - 10)) ]; then break; fi
                    echo "ssh rc 255 on start-at attempt ${att} at $(date +%s) (due ${due}); retrying" >> "${f}.log"
                    sleep 1
                done
                echo "start-at attempts: ${att}" >> "${f}.log"
                printf '%s\n' "${out}" > "${f}.out"
                echo "${rc_s}" > "${f}.rc"
            ) &
            pids+=("$!")
        done
        # Bounded wait: at due + FINALIZE_START_TIMEOUT_SECS a probe still running is killed.
        deadline=$((due + FINALIZE_START_TIMEOUT_SECS))
        while :; do
            n=0
            for k in "${pids[@]}"; do if kill -0 "${k}" 2>/dev/null; then n=$((n + 1)); fi; done
            if [ "${n}" -eq 0 ] || [ "$(date +%s)" -ge "${deadline}" ]; then break; fi
            sleep 1
        done
        for k in "${pids[@]}"; do
            if kill -0 "${k}" 2>/dev/null; then _kill_tree "${k}"; fi
            wait "${k}" 2>/dev/null || true
        done

        for i in "${todo[@]}"; do
            inst="${INSTANCE_NAMES[$i]}"; node="${NODE_NAMES[$i]}"
            f="${WORK}/start-${i}"
            if [ ! -f "${f}.rc" ]; then
                echo "❌ [${node}] start-at on ${inst}: no answer by due + ${FINALIZE_START_TIMEOUT_SECS}s (probe killed)"
                failed+=("${node}: start (no answer by the deadline)"); continue
            fi
            sed -n "s/^ssh rc 255/    … [${node}] ssh rc 255/p" "${f}.log" 2>/dev/null || true
            out="$(cat "${f}.out" 2>/dev/null || true)"
            line="$(printf '%s\n' "${out}" | sed -n '/^START_AT /p' | tail -n 1)"
            began="${line##* began=}"; began="${began%% *}"
            if [ "$(_kv "${out}" start_rc)" = "late" ]; then
                echo "❌ [${node}] start-at on ${inst}: reached the node after due + ${FINALIZE_START_SPREAD_WARN_SECS}s; NOT started (a late member sits out the epoch) (${line#START_AT })"
                failed+=("${node}: start (late, not started)"); continue
            fi
            if [ "$(cat "${f}.rc")" != "0" ] || [ "$(_kv "${out}" start_rc)" != "0" ] || [ -z "${line}" ] \
                || [ "$(_num "${began}")" != "${began}" ]; then
                echo "❌ [${node}] start-at on ${inst}: $(printf '%s\n' "${out}" | sed -n -e '/^start_rc=/p' -e '/^no answer /p' | tr '\n' ' ')${line:+(${line#START_AT })} ($(sed -n 's/^start-at attempts: /attempts /p' "${f}.log" 2>/dev/null))"
                failed+=("${node}: start"); continue
            fi
            if [ "$(_kv "${out}" start_attempt)" = "repeat" ]; then
                echo "    … [${node}] an earlier attempt had started the unit; began is the one it recorded"
            fi
            echo "${line}"
            started=$((started + 1))
            late=$((began - due))
            if [ -z "${bmin}" ] || [ "${began}" -lt "${bmin}" ]; then bmin="${began}"; fi
            if [ -z "${bmax}" ] || [ "${began}" -gt "${bmax}" ]; then bmax="${began}"; fi
            if [ -z "${maxlate}" ] || [ "${late}" -gt "${maxlate}" ]; then maxlate="${late}"; fi
            healthy+=("${i}")
        done
        for i in ${healthy[@]+"${healthy[@]}"}; do
            inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"; node="${NODE_NAMES[$i]}"
            service="$(tn_service_for_role "$(tn_node_role "$i")")"
            if wait_healthy "${inst}" "${zone}" "${service}"; then
                up="${up}${i} "
            else
                echo "❌ [${node}] not healthy after the coordinated start"
                failed+=("${node}: health"); continue
            fi
        done
    fi
    if [ "${started}" -gt 0 ]; then spread=$((bmax - bmin)); fi
    echo "COORDINATED_START due=${due} nodes=${#} started=${started} skipped_running=${nrun} spread_secs=${spread} max_late_secs=${maxlate:-0}"
    if [ "${spread}" -gt "${FINALIZE_START_SPREAD_WARN_SECS}" ]; then
        echo "⚠️  coordinated start spread ${spread}s > FINALIZE_START_SPREAD_WARN_SECS=${FINALIZE_START_SPREAD_WARN_SECS}s: a committee member that starts more than gc_depth (50) rounds after the others reach quorum sits out the whole epoch. Look for \"too new for max round 50\" in the late node's log and tn_nodeMode CvvInactive; a restart cannot help inside the epoch (lessons 2026-11-02)." >&2
    fi
    # Phase B runs on every node that is up, in target order.
    for i in "$@"; do
        case "${up}" in *" ${i} "*) finalized+=("${i}") ;; esac
    done
}

# --- FINALIZE_JOBS: phase A / phase B on several nodes at once ---------------------------

# _run_nodes <a|b> <fn> <index>... — <fn> <index> for every index, in target order.
# FINALIZE_JOBS=1 (the default): inline, one node after the other: the serial loop.
# Otherwise each node runs in a background job (_node_job), at most FINALIZE_JOBS at once,
# started in target order (with that many running, the oldest is awaited first), and each
# finished node is merged (_merge_node) in target order, so stdout reads as the serial
# run's. INT, TERM or HUP stops the jobs too (a background job ignores the terminal's INT).
_JOB_PIDS=()
_run_nodes() {
    local ph="$1" fn="$2" i k=0 next=0 idx name="phase B"
    shift 2
    if [ "${FINALIZE_JOBS}" -eq 1 ]; then
        for i in "$@"; do "${fn}" "${i}"; done
        return 0
    fi
    if [ "${ph}" = a ]; then name="phase A"; fi
    idx=(); _JOB_PIDS=()
    if [ "$#" -gt 0 ]; then
        echo ">>> ${name}: $# node(s), at most ${FINALIZE_JOBS} at a time (FINALIZE_JOBS); each node's lines follow, in target order, once it is done" >&2
    fi
    trap '_stop_jobs; exit 130' INT
    trap '_stop_jobs; exit 143' TERM
    trap '_stop_jobs; exit 129' HUP
    for i in "$@"; do
        if [ $((k - next)) -ge "${FINALIZE_JOBS}" ]; then
            wait "${_JOB_PIDS[next]}" || true
            _merge_node "${ph}" "${idx[next]}" "${name}"; next=$((next + 1))
        fi
        _node_job "${ph}" "${fn}" "${i}" > "${WORK}/${ph}.${i}.out" 2> "${WORK}/${ph}.${i}.err" &
        _JOB_PIDS[k]=$!; idx[k]="${i}"; k=$((k + 1))
    done
    while [ "${next}" -lt "${k}" ]; do
        wait "${_JOB_PIDS[next]}" || true
        _merge_node "${ph}" "${idx[next]}" "${name}"; next=$((next + 1))
    done
    trap - INT TERM HUP
    _JOB_PIDS=()
}

_stop_jobs() { local p; for p in ${_JOB_PIDS[@]+"${_JOB_PIDS[@]}"}; do _kill_tree "${p}"; done; }

# _node_job <a|b> <fn> <index> — one node's <fn> inside its background job. The lists
# start empty there, so what <fn> appends is this node's alone: it goes to
# ${WORK}/<a|b>.<index>.kv (result=finalized|staged|prestaged|running|verified|failed,
# failed_text, verified_text, logmark, jcursor), written last and renamed into place.
_node_job() {
    local ph="$1" fn="$2" i="$3" kv="${WORK}/$1.$3.kv" result=""
    failed=(); finalized=(); verified=(); STAGED_IDX=(); PRESTAGED_IDX=(); RUNNING_IDX=()
    "${fn}" "${i}"
    if [ "${#failed[@]}" -gt 0 ]; then result=failed
    elif [ "${#STAGED_IDX[@]}" -gt 0 ]; then result=staged
    elif [ "${#PRESTAGED_IDX[@]}" -gt 0 ]; then result=prestaged
    elif [ "${#RUNNING_IDX[@]}" -gt 0 ]; then result=running
    elif [ "${#finalized[@]}" -gt 0 ]; then result=finalized
    elif [ "${#verified[@]}" -gt 0 ]; then result=verified
    fi
    {
        echo "result=${result}"
        echo "failed_text=${failed[0]:-}"
        echo "verified_text=${verified[0]:-}"
        echo "logmark=${LOG_MARKS[i]:-}"
        echo "jcursor=${JOURNAL_CURSORS[i]:-}"
    } > "${kv}.tmp"
    mv "${kv}.tmp" "${kv}"
}

# _merge_node <a|b> <index> <name> — one finished job: its stdout, then its stderr, then
# its outcome added to the lists as the serial loop would have. A job that left no outcome
# (it stopped under set -e) fails its node, never the run.
_merge_node() {
    local ph="$1" i="$2" name="$3" kv="${WORK}/$1.$2.kv" out=""
    cat "${WORK}/${ph}.${i}.out"
    cat "${WORK}/${ph}.${i}.err" >&2
    if [ -f "${kv}" ]; then out="$(cat "${kv}")"; fi
    case "$(_kv "${out}" result)" in
        failed) failed+=("$(_kv "${out}" failed_text)") ;;
        staged) STAGED_IDX+=("${i}") ;;
        prestaged) PRESTAGED_IDX+=("${i}") ;;
        running) RUNNING_IDX+=("${i}") ;;
        finalized) finalized+=("${i}") ;;
        verified) verified+=("$(_kv "${out}" verified_text)") ;;
        *)
            echo "❌ [${NODE_NAMES[$i]}] ${name}: the node's job ended without an outcome (see its lines above)"
            failed+=("${NODE_NAMES[$i]}: ${name} job ended early") ;;
    esac
    if [ "${ph}" = a ]; then
        LOG_MARKS[i]="$(_kv "${out}" logmark)"
        JOURNAL_CURSORS[i]="$(_kv "${out}" jcursor)"
    fi
}

echo ">>> finalize targets: ${#INDICES[@]} node(s) — ${INDICES[*]}"
if [ -n "${FINALIZE_MODE}" ]; then echo ">>> mode --${FINALIZE_MODE}"; fi
echo ">>> image ${DOCKER_IMAGE}"

finalized=()   # "index" of nodes that passed phase A
LOG_MARKS=()        # by index: the gate's logmark values, for A4
JOURNAL_CURSORS=()  # by index: the gate's journal cursor, for A4
verified=()
failed=()
STAGED_IDX=()      # --stage-only / --defer-start: by index, finalized then stopped
PRESTAGED_IDX=()   #   unit already installed, inactive and enabled: skipped
RUNNING_IDX=()     #   unit already active: skipped, never stopped

# --verify: no phase A; phase B runs on every target with an installed unit.
if [ "${FINALIZE_MODE}" = "verify" ]; then
    for i in "${INDICES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"; node="${NODE_NAMES[$i]}"
        service="$(tn_service_for_role "$(tn_node_role "$i")")"
        if ! unit_out="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_unit)" "${service}")"; then
            echo "❌ [${node}] unit check: ${unit_out}"
            failed+=("${node}: unit check (no answer)"); continue
        fi
        if [ -z "$(_kv "${unit_out}" UnitFileState)" ]; then
            echo "❌ [${node}] no ${service} unit installed on ${inst}: nothing to verify"
            failed+=("${node}: no ${service} unit"); continue
        fi
        finalized+=("${i}")
    done
fi

# Phase A visits every target, except in --start-all and --verify (none).
PHASE_A=()
case "${FINALIZE_MODE}" in start-all|verify) ;; *) PHASE_A=("${INDICES[@]}") ;; esac

# --- phase A: gate, stage, finalize, health ------------------------------------------
# _maps_verdict <index> <gate output> — TN_ADMISSION_VIA=native: are the admission maps
# installed on the host (bp_sha / tn_sha from _rs_map_lines) the local ones, by sha256? The
# trusted map counts only for a node that gets one (validator, observer). Prints one
# observation; rc 0 yes, 1 no.
_maps_verdict() {
    local i="$1" gate="$2" node="${NODE_NAMES[$1]}" k key loc host got want bad="" ok=""
    for k in bootstrap-peers trusted-nodes; do
        key=bp_sha
        if [ "${k}" = trusted-nodes ]; then
            _has_trusted_map "${i}" || continue
            key=tn_sha
        fi
        loc="${ADMISSION_LOCAL_DIR}/${node}.${k}.yaml"
        host="${ADMISSION_HOST_DIR}/${k}.yaml"
        got="$(_kv "${gate}" "${key}")"
        if [ ! -f "${loc}" ]; then bad="${bad} local ${loc} missing;"; continue; fi
        want="$(_sha256 "${loc}")" || want=""
        if [ -z "${want}" ]; then bad="${bad} could not hash ${loc};"
        elif [ -z "${got}" ] || [ "${got}" = "missing" ]; then bad="${bad} ${host} missing on the host;"
        elif [ "${got}" != "${want}" ]; then bad="${bad} ${host} sha256 ${got:0:12}… differs from ${loc} (${want:0:12}…);"
        else ok="${ok} ${k} ${want:0:12}…"; fi
    done
    if [ -n "${bad}" ]; then echo "admission maps not as rendered:${bad}"; return 1; fi
    echo "installed = local by sha256:${ok}"
}

# _phase_a_node <index> — phase A on one node (the serial loop's body). Its outcome is one
# entry in failed, PRESTAGED_IDX, RUNNING_IDX, STAGED_IDX or finalized, and the node's
# LOG_MARKS / JOURNAL_CURSORS once its gate passed. _run_nodes runs it for every target.
_phase_a_node() {
    local i="$1"
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    addr="${EXECUTION_ADDRESSES[$i]}"
    role="$(tn_node_role "$i")"
    gdir="$(tn_genesis_dir_for_role "${role}")"
    ddir="$(tn_data_dir_for_role "${role}")"
    setup="$(tn_setup_script_for_role "${role}")"
    service="$(tn_service_for_role "${role}")"

    echo ""
    echo ">>> [${node}] finalize on ${inst} (${zone}) role=${role} service=${service}"

    # --- Step 0: local checks ------------------------------------------------------
    case "${addr}" in
        0x*) _ahex="${addr#0x}" ;;
        *) _ahex="" ;;
    esac
    case "${_ahex}" in *[!0123456789abcdefABCDEF]*) _ahex="" ;; esac
    if [ "${#_ahex}" -ne 40 ]; then
        echo "❌ [${node}] EXECUTION_ADDRESSES[${i}]='${addr}' is not 0x + 40 hex (config.sh)"
        failed+=("${node}: bad execution address"); return 0
    fi
    if ! pubdom="$(tn_public_domain "${i}")" || [ -z "${pubdom}" ]; then
        echo "❌ [${node}] no public domain for index ${i} (config.sh)"
        failed+=("${node}: public domain"); return 0
    fi

    # --- Step 1: readiness gate ----------------------------------------------------
    ready_args=("${setup}" "${service}" "${ddir}" "${TN_LOG_DIR}")
    if _native; then ready_args+=("${ADMISSION_HOST_DIR}"); fi
    if ! gate="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_ready)" "${ready_args[@]}")"; then
        echo "❌ [${node}] readiness gate: ${gate}"
        failed+=("${node}: readiness gate (no answer)"); return 0
    fi
    # --stage-only / --defer-start skip rules, decided by this probe before anything else.
    case "${FINALIZE_MODE}" in
        stage-only|defer-start)
            if [ "$(_kv "${gate}" installed)" = "1" ]; then
                unit_st="$(_kv "${gate}" ActiveState)"; unit_en="$(_kv "${gate}" UnitFileState)"
                if [ "${unit_st}" = "inactive" ] && [ "${unit_en}" = "enabled" ]; then
                    echo "PRESTAGED ${inst}"
                    PRESTAGED_IDX+=("${i}"); return 0
                fi
                if [ "${unit_st}" = "active" ]; then
                    echo "RUNNING ${inst}"
                    echo "⚠️  [${node}] ${service} is already running on ${inst} (UnitFileState=${unit_en:-?}): not staged and NOT stopped; if other committee members run too, a quorum may have formed" >&2
                    RUNNING_IDX+=("${i}"); return 0
                fi
                echo ">>> [${node}] ${service} unit installed with ActiveState=${unit_st:-?} UnitFileState=${unit_en:-?}: neither PRESTAGED nor RUNNING"
            fi ;;
    esac
    gate_bad=""
    if [ "$(_kv "${gate}" setup)" != "1" ]; then gate_bad="${gate_bad} ${setup} missing (fetch the node scripts);"; fi
    if [ "$(_kv "${gate}" keygen)" != "1" ]; then gate_bad="${gate_bad} no keygen record in /etc/telcoin/.node-meta (run ./devnet-keygen.sh);"; fi
    if [ "$(_kv "${gate}" installed)" != "0" ]; then gate_bad="${gate_bad} a ${service} unit is already installed (v2 refuses finalize over it: edit-config.sh, or remove-node.sh first);"; fi
    if _native; then
        if ! nc_obs="$(_maps_verdict "${i}" "${gate}")"; then
            gate_bad="${gate_bad} ${nc_obs} (run ./devnet-network-config.sh --yes ${node});"
        fi
        ready_what="admission maps"
    else
        if ! nc_obs="$(_nc_verdict "${node}" "$(_kv "${gate}" nc_present)" "$(_kv "${gate}" nc_b64)")"; then
            gate_bad="${gate_bad} $(_kv "${gate}" nc) ${nc_obs} (run ./devnet-network-config.sh --yes ${node});"
        fi
        ready_what="$(_kv "${gate}" nc)"
    fi
    if [ -n "${gate_bad}" ]; then
        echo "❌ [${node}] not ready to finalize:${gate_bad}"
        failed+=("${node}: readiness gate"); return 0
    fi
    echo ">>> [${node}] ready: setup-node.sh present, keygen recorded, no unit yet, ${ready_what}: ${nc_obs}"
    # Where the logs end before this finalize: A4 reads only what comes after.
    LOG_MARKS[i]="$(printf '%s\n' "${gate}" | sed -n 's/^logmark=//p' | tr '\n' ' ')"
    JOURNAL_CURSORS[i]="$(_kv "${gate}" jcursor)"

    # --- Step 2: stage genesis files (root-owned 0644) ------------------------------
    echo ">>> [${node}] staging committee/genesis/parameters to ${gdir}"
    stage_ok=1
    tn_iap_scp "${COMMITTEE_LOCAL}" "${inst}" "${zone}" "/tmp/committee.yaml" || stage_ok=0
    tn_iap_scp "${GENESIS_LOCAL}"   "${inst}" "${zone}" "/tmp/genesis.yaml"   || stage_ok=0
    tn_iap_scp "${PARAMETERS_FILE}" "${inst}" "${zone}" "/tmp/parameters.yaml" || stage_ok=0
    if [ "${stage_ok}" -ne 1 ]; then
        echo "❌ [${node}] failed to scp one or more genesis files"
        failed+=("${node}: scp"); return 0
    fi
    stage_cmd="sudo install -d -o root -g root -m 0755 '${gdir%/*}' '${gdir}'"
    for f in committee.yaml genesis.yaml parameters.yaml; do
        stage_cmd="${stage_cmd} && sudo install -o root -g root -m 0644 /tmp/${f} '${gdir}/${f}'"
    done
    stage_cmd="${stage_cmd}; rc=\$?; rm -f /tmp/committee.yaml /tmp/genesis.yaml /tmp/parameters.yaml; exit \$rc"
    echo ">>> [${node}] running: ${stage_cmd}"
    if ! tn_iap_ssh "${inst}" "${zone}" "${stage_cmd}"; then
        echo "❌ [${node}] failed to install genesis files into ${gdir}"
        failed+=("${node}: stage"); return 0
    fi
    echo ">>> [${node}] genesis staged in ${gdir} (root:root 0644)"

    # The node binds its P2P listeners to the INTERNAL IP (mirrors devnet-keygen.sh's
    # --listener-*). v2 writes them to /etc/telcoin/node.env, and finalize refuses to run
    # without both (an empty one would start a node with no listener).
    intIP="$(tn_node_int_ip "${inst}" "${zone}")" || intIP=""
    if [ -z "${intIP}" ]; then
        echo "❌ [${node}] could not resolve internal IP for listener multiaddrs"
        failed+=("${node}: internal IP"); return 0
    fi
    # Finalize rewrites PUBLIC_IP / EXTERNAL_PRIMARY_ADDR / EXTERNAL_WORKER_ADDR in
    # .node-meta from its OWN flags (keygen does not keep them), so pass the same values
    # keygen passed or the fields stay empty for the UI and update tooling.
    extIP="$(tn_node_ext_ip "${inst}" "${zone}")" || extIP=""
    if [ -z "${extIP}" ]; then
        echo "❌ [${node}] could not resolve external IP for the advertised multiaddrs"
        failed+=("${node}: external IP"); return 0
    fi

    # --- Step 3: finalize (node.env + start script + unit; start + enable) ----------
    finalize_args=(
        --json
        --phase=finalize
        --network devnet
        --install-method docker
        # Must equal what keygen recorded in .node-meta (finalize stops on a mismatch).
        --docker-image "${DOCKER_IMAGE}"
        # setup-node.sh looks here FIRST for genesis/committee/parameters.yaml.
        --genesis-dir "${gdir}"
        --data-dir "${ddir}"
        --service-user "${SERVICE_USER}"
        # Finalize rewrites VALIDATOR_ADDRESS in .node-meta from this flag (empty without
        # it), and its post-start check_validator_onchain_status probes the
        # ConsensusRegistry with it.
        --address "${addr}"
        # Finalize alone writes the network-config `hostname: "<name>"` line
        # (step_write_config -> write_advertised_name); keygen does not keep the name, so
        # pass the value keygen passes, the bare NODE_NAME.
        --advertised-name "${node}"
        # The node's own public, operator-facing endpoints, served by its Caddy edge
        # (https -> reth RPC :8545, wss -> reth WS :8546). Recorded in .node-meta
        # (PUBLIC_RPC_URL / PUBLIC_WS_URL) for the UI and tooling; never sent to the
        # network. No --rpc-domain: the devnet's Caddy is configured by its own drivers.
        # The domain is tn_public_domain (<NODE_NAME>.<BASE_DOMAIN>; RPC_HOSTNAME for rpc).
        --public-rpc-url "https://${pubdom}"
    )
    # A node behind a worker gateway gets no ws URL (the gateway carries no WebSocket, and
    # setup-node.sh records PUBLIC_WS_URL empty); with TN_GATEWAY_ENABLE not 1 every node
    # is mode none, so the bench passes it for every node, as before.
    if [ "$(tn_gateway_mode "${i}")" = "none" ]; then
        finalize_args+=(--public-ws-url "wss://${pubdom}")
    fi
    finalize_args+=(
        --listener-primary "/ip4/${intIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --listener-worker "/ip4/${intIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --external-primary "/ip4/${extIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --external-worker "/ip4/${extIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --public-ip "${extIP}"
        # Bakes `--healthcheck 43174` (TN_KUMA_PORT) into the start script's node line, so
        # the node opens the listener Uptime Kuma and the GCP LB probe. Needs nothing
        # else on devnet (is_testnet_like); the host-firewall rule is devnet-firewall.sh's.
        --enable-healthcheck-monitor
    )
    # Native admission: setup-node.sh checks each map (regular, mode o+g readable, at most
    # 64 KiB; the bootstrap map also by the release's own parser), installs root 0644 copies
    # under /etc/telcoin, records them in .node-meta (A6) and renders network-config (A3).
    if _native; then
        finalize_args+=(--admission "$(tn_admission_mode "${i}")"
            --bootstrap-peers "${ADMISSION_HOST_DIR}/bootstrap-peers.yaml")
        if _has_trusted_map "${i}"; then
            finalize_args+=(--trusted-nodes "${ADMISSION_HOST_DIR}/trusted-nodes.yaml")
        fi
    fi
    finalize_cmd="sudo bash '${setup}'"
    for a in "${finalize_args[@]}"; do finalize_cmd="${finalize_cmd} '${a}'"; done
    echo ">>> [${node}] running: ${finalize_cmd}"

    fin_rc=0
    fin_out="$(tn_iap_ssh "${inst}" "${zone}" "${finalize_cmd}" </dev/null)" || fin_rc=$?
    if [ -n "${fin_out}" ]; then printf '%s\n' "${fin_out}" | sed 's/^/    json: /'; fi
    fin_done="$(tn_json_done_line "${fin_out}")"
    if [ "${fin_rc}" -ne 0 ] || ! tn_json_true "${fin_done}" ok; then
        echo "❌ [${node}] finalize failed (ssh rc ${fin_rc}; done: ${fin_done:-none})"
        failed+=("${node}: finalize"); return 0
    fi
    echo ">>> [${node}] finalize ok"

    # --- Step 4: health gate ----------------------------------------------------------
    if ! wait_healthy "${inst}" "${zone}" "${service}"; then
        echo "❌ [${node}] not healthy after finalize"
        failed+=("${node}: health"); return 0
    fi
    # --stage-only / --defer-start: the node ran alone long enough to prove it starts; leave
    # it stopped and enabled for the coordinated start.
    case "${FINALIZE_MODE}" in
        stage-only|defer-start)
            if ! unit_out="$(_ro _tn_probe "${inst}" "${zone}" "$(_rs_unit)" "${service}")"; then
                echo "❌ [${node}] unit state before the stop: ${unit_out}"
                failed+=("${node}: unit state (no answer)"); return 0
            fi
            if [ "$(_kv "${unit_out}" ActiveState)" != "active" ] || [ "$(_kv "${unit_out}" NRestarts)" != "0" ]; then
                echo "❌ [${node}] after finalize: ActiveState=$(_kv "${unit_out}" ActiveState) NRestarts=$(_kv "${unit_out}" NRestarts) (want active, 0); not stopped"
                failed+=("${node}: not stable after finalize"); return 0
            fi
            if ! stop_obs="$(_defer_stop "${inst}" "${zone}" "${service}")"; then
                echo "❌ [${node}] stop: ${stop_obs}"
                failed+=("${node}: stop"); return 0
            fi
            echo "STAGED ${inst} ${stop_obs}"
            STAGED_IDX+=("${i}"); return 0 ;;
    esac
    finalized+=("${i}")
}
_run_nodes a _phase_a_node ${PHASE_A[@]+"${PHASE_A[@]}"}

# --- coordinated start (--start-all; --defer-start once every target is staged) ---------
STAGE_SUMMARY=""
case "${FINALIZE_MODE}" in
    stage-only) STAGE_SUMMARY=1 ;;
    start-all) _start_all "${INDICES[@]}" || true ;;
    defer-start)
        if [ $(( ${#STAGED_IDX[@]} + ${#PRESTAGED_IDX[@]} )) -eq "${#INDICES[@]}" ]; then
            _start_all "${INDICES[@]}" || true
        else
            echo ""
            echo "❌ --defer-start: not every target is STAGED or PRESTAGED; nothing was started"
            failed+=("coordinated start not attempted (${#RUNNING_IDX[@]} RUNNING, $(( ${#INDICES[@]} - ${#STAGED_IDX[@]} - ${#PRESTAGED_IDX[@]} - ${#RUNNING_IDX[@]} )) failed)")
            STAGE_SUMMARY=1
        fi ;;
esac

# --- phase B: post-finalize assertions -----------------------------------------------
if [ "${#finalized[@]}" -gt 0 ]; then
    echo ""
    echo ">>> post-finalize assertions (${#finalized[@]} node(s); stability window ${FINALIZE_STABLE_SECS}s every ${FINALIZE_STABLE_POLL_SECS}s)"
fi
# _phase_b_node <index> — A1-A5 on one node (the serial loop's body): one entry in
# verified or failed. _run_nodes runs it for every node that passed phase A.
_phase_b_node() {
    local i="$1"
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    service="$(tn_service_for_role "$(tn_node_role "$i")")"
    echo ">>> [${node}] asserting ${inst}"
    misses=0
    assert_service "${inst}" "${zone}" "${node}" "${service}" || misses=$((misses + 1))
    assert_meta "${inst}" "${zone}" "${node}" || misses=$((misses + 1))
    data_dir="${META_DATA_DIR:-$(tn_data_dir_for_role "$(tn_node_role "$i")")}"
    nc_mode=""
    if _native; then nc_mode="$(_mode_word "${i}")"; fi
    assert_network_config "${inst}" "${zone}" "${node}" "${data_dir}" ${nc_mode:+"${nc_mode}"} || misses=$((misses + 1))
    assert_logs "${inst}" "${zone}" "${node}" "${service}" "${META_NODE_LOG_DIR}" \
        "${LOG_MARKS[$i]:-}" "${JOURNAL_CURSORS[$i]:-}" || misses=$((misses + 1))
    assert_runtime "${inst}" "${zone}" "${node}" "${service}" || misses=$((misses + 1))
    if _native; then
        assert_admission_meta "${inst}" "${zone}" "${node}" "${i}" || misses=$((misses + 1))
    fi
    if [ "${misses}" -eq 0 ]; then
        verified+=("${node} (${service})")
    else
        failed+=("${node}: ${misses} assertion(s) failed")
    fi
}
_run_nodes b _phase_b_node ${finalized[@]+"${finalized[@]}"}

# _list_idx <index>... — one "  - NODE_NAME (INSTANCE_NAME)" line per index.
_list_idx() { local i; for i in "$@"; do echo "  - ${NODE_NAMES[$i]} (${INSTANCE_NAMES[$i]})"; done; }
if [ -n "${STAGE_SUMMARY}" ]; then
    echo ""
    echo "========================================="
    echo "finalize --${FINALIZE_MODE} summary"
    echo "========================================="
    echo "staged: finalized, then stopped, enabled (${#STAGED_IDX[@]}):"
    _list_idx ${STAGED_IDX[@]+"${STAGED_IDX[@]}"}
    echo "prestaged, skipped (${#PRESTAGED_IDX[@]}):"
    _list_idx ${PRESTAGED_IDX[@]+"${PRESTAGED_IDX[@]}"}
    echo "running, skipped, NOT stopped (${#RUNNING_IDX[@]}):"
    _list_idx ${RUNNING_IDX[@]+"${RUNNING_IDX[@]}"}
    if [ "${#failed[@]}" -gt 0 ]; then
        echo "failed (${#failed[@]}):"
        for n in "${failed[@]}"; do echo "  - ${n}"; done
        exit 1
    fi
    if [ "${#RUNNING_IDX[@]}" -gt 0 ]; then
        echo "⚠️  ${#RUNNING_IDX[@]} node(s) were already running and were left as they are; every other target is staged (stopped, enabled)."
    else
        echo "every targeted node is staged (stopped, enabled) or was already; start them with --start-all."
    fi
    exit 0
fi

echo ""
echo "========================================="
echo "finalize summary"
if [ -n "${FINALIZE_MODE}" ]; then echo "mode: --${FINALIZE_MODE}"; fi
echo "========================================="
echo "finalized + verified (${#verified[@]}):"
for n in ${verified[@]+"${verified[@]}"}; do echo "  - ${n}"; done
if [ "${#failed[@]}" -gt 0 ]; then
    echo "failed (${#failed[@]}):"
    for n in "${failed[@]}"; do echo "  - ${n}"; done
    exit 1
fi
echo "all targeted nodes finalized, started, enabled and verified."
