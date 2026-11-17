#!/usr/bin/env bash
#
# devnet-keygen.sh — OPERATOR driver: run tn-node-deployment v2 keygen on every node
# (or a targeted subset) over IAP SSH, then pull each node's node-info.yaml back
# into the local genesis/ tree so devnet-genesis-build.sh can assemble the
# committee.
#
# Per node it runs (as root, on the node), the same for every role (v2 has one entry
# point, setup-node.sh; the role is decided on-chain):
#   sudo bash '${TN_NODE_SCRIPTS_DIR}/setup-node.sh' --json --phase=keygen ... --passphrase-stdin
# v2 keygen creates the service account itself (SERVICE_USER: a system uid with no home
# and no login shell), lays out the data dir and generates the keys. Its --json contract
# puts one JSON event per line on STDOUT and every human-readable line on stderr: stdout
# is captured and judged by its {"event":"done",...} line, stderr goes to the per-run log
# logs/<ts>-keygen/<instance>.log. Then <DATA_DIR>/node-info.yaml (the done line's
# node_info_path) is copied down to genesis/<tn_role_dir>/<nodeN>.yaml: validators/ for a
# validator, observers/ for node 5 (observer) and the public RPC node (rpc). That split
# follows NODE_ROLES, not the done line (v2 reports node_type "observer" for every node):
# `telcoin genesis` builds the committee from every file in genesis/validators/.
# Only node hosts are visited (tn_node_indices: roles validator, observer, rpc). A `gateway`
# entry runs no node and holds no keys: it is never selected, and naming it as a target
# is refused like an unknown target (rc 2, or 1 with --pull-only, before anything runs).
#
# Keygen leaves <DATA_DIR>/network-config alone. v2 writes its `hostname:` line only in
# the finalize phase (step_write_config -> write_advertised_name), and does not record
# --advertised-name in .node-meta, so the flag below is accepted and unused at keygen;
# the hostname line appears only if finalize passes it too. devnet-network-config.sh
# installs the file between keygen and finalize, and finalize's edit merges into it.
#
# SECURITY: the BLS keystore passphrase is resolved ONCE up front via
# tn_require_bls_passphrase (TN_BLS_PASSPHRASE > TN_BLS_PASSPHRASE_FILE >
# .secrets/bls-passphrase) and reaches the node on STDIN only: printf (a bash builtin,
# so it is never a process argv) pipes "<passphrase>\n" into tn_iap_ssh_cmd_stdin, and
# setup-node.sh --passphrase-stdin reads that one line. It is never in the remote
# command (remote argv: visible in ps, sudo's log and the ssh audit trail), never in the
# environment handed to gcloud/ssh (unexported below; setup-node.sh also refuses
# TN_BLS_PASSPHRASE and --passphrase-stdin together), never echoed and never in the run
# log. `set -x` is never enabled. With KEYGEN_JOBS > 1 each node runs in a background
# subshell, which inherits the variable unexported and pipes it the same way.
#
# Usage:
#   ./devnet-keygen.sh                  # all nodes
#   ./devnet-keygen.sh node1 node3      # subset by NODE_NAME
#   ./devnet-keygen.sh validator-1-devnet  # subset by INSTANCE_NAME
#   ./devnet-keygen.sh 0 4              # subset by index
#   ./devnet-keygen.sh --pull-only node3   # no keygen: only download node3's node-info.yaml
#                                          # (no targets = every node; no passphrase needed)
#
# Knobs (environment; every one unset = the behaviour before bench 4, output for output):
#   KEYGEN_JOBS=N            nodes keyed at once (default 1, in this shell). N > 1: background
#                            subshells, each node's output printed whole, in index order.
#   KEYGEN_REUSE_EXISTING=1  a node that refuses keygen because it is keyed already ("node-keys
#                            already exist", "already installed") or whose keygen sent no done
#                            line (dropped ssh) is re-probed: if its .node-meta records this
#                            node's VALIDATOR_ADDRESS and its node-info.yaml is non-empty, that
#                            node-info.yaml is downloaded ("already keyed ... reusing"); else
#                            the node fails. Default 0: such a node fails.
#   KEYGEN_RPC_ADVERTISE     domain (default): node-info.yaml advertises https/wss://<node>.<BASE_DOMAIN>/.
#                            With TN_GATEWAY_ENABLE=1, in domain mode: a node with a worker
#                            gateway (tn_gateway_mode same-host|standalone) advertises only
#                            https://<tn_public_domain>/ (--rpc-http, no --rpc-ws); an rpc node
#                            advertises nothing at keygen (the public-RPC edge sets its URL later).
#                            internal-ip: http://<intIP>:KEYGEN_RPC_HTTP_PORT/ (8545) and
#                            ws://<intIP>:KEYGEN_RPC_WS_PORT/ (8546), reth's own listeners.
#   KEYGEN_REPORT=1          one line per node: KEYGEN_DONE <inst> rc=<0|1> secs=<n> reused=<0|1>
#                            rpc_http=<url|-> rpc_ws=<url|-> (what the collected node-info.yaml
#                            advertises). Default 0: no such line.

set -euo pipefail

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# ----------------------------------------------------------------------------
# Resolve the set of node indices to act on. With no args → every node host
# (tn_node_indices; never a gateway entry). With args, each may be an index, an
# INSTANCE_NAME, or a NODE_NAME. An unknown target, or an entry that runs no node (a
# gateway), is an error: a message on stderr, rc 1, nothing printed.
# ----------------------------------------------------------------------------
tn_select_indices() {
    local out=() arg i matched
    if [ "$#" -eq 0 ]; then
        tn_node_indices; return 0
    fi
    for arg in "$@"; do
        matched=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                matched="${i}"; break
            fi
        done
        if [ -z "${matched}" ]; then
            echo "❌ unknown target: ${arg} (expected an index, INSTANCE_NAME, or NODE_NAME)" >&2
            return 1
        fi
        if ! tn_is_node_index "${matched}"; then
            echo "❌ ${arg} (${INSTANCE_NAMES[$matched]}) is a '${NODE_ROLES[$matched]:-}' entry: it runs no node and holds no keys, so it is not a keygen target" >&2
            return 1
        fi
        out+=("${matched}")
    done
    printf '%s\n' "${out[@]}"
}

# gcloud compute scp in the DOWN direction (remote -> local). tn_iap_scp only
# does local -> remote, so the down-copy is spelled out here. Over IAP it rides
# devnet-lib's transport retry (_tn_iap_retry: rc 255 or a gcloud crash is tried
# again, TN_IAP_RETRIES times), like every other IAP call the drivers make.
tn_iap_scp_down() {
    local inst="$1" zone="$2" remote_src="$3" local_dest="$4"
    if [ "${TN_SSH_TRANSPORT}" = "overlay" ]; then
        # remote -> local: tn_scp rewrites the "NAME:path" src to tnadmin@<overlay-ip>:path.
        tn_scp "${inst}" "${inst}:${remote_src}" "${local_dest}"
    else
        _tn_iap_retry "tn_iap_scp_down ${inst}" 0 compute scp "${inst}:${remote_src}" "${local_dest}" \
            --zone="${zone}" --project="${PROJECT_ID}" \
            --tunnel-through-iap --scp-flag="-o ConnectTimeout=20"
    fi
}

# keygen_check_knobs — refuse a malformed KEYGEN_* knob before anything runs (stderr, rc 1).
keygen_is_port() { case "$1" in ""|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
keygen_check_knobs() {
    local bad=0
    case "${KEYGEN_JOBS:-1}" in
        *[!0-9]*) bad=1 ;;
        *) if [ "${KEYGEN_JOBS:-1}" -lt 1 ]; then bad=1; fi ;;
    esac
    if [ "${bad}" = 1 ]; then echo "❌ KEYGEN_JOBS='${KEYGEN_JOBS}' is not a whole number >= 1" >&2; fi
    case "${KEYGEN_REUSE_EXISTING:-0}" in 0|1) ;; *) bad=1
        echo "❌ KEYGEN_REUSE_EXISTING='${KEYGEN_REUSE_EXISTING}' is not 0 or 1" >&2 ;; esac
    case "${KEYGEN_REPORT:-0}" in 0|1) ;; *) bad=1
        echo "❌ KEYGEN_REPORT='${KEYGEN_REPORT}' is not 0 or 1" >&2 ;; esac
    case "${KEYGEN_RPC_ADVERTISE:-domain}" in domain|internal-ip) ;; *) bad=1
        echo "❌ KEYGEN_RPC_ADVERTISE='${KEYGEN_RPC_ADVERTISE}' is not domain or internal-ip" >&2 ;; esac
    if ! keygen_is_port "${KEYGEN_RPC_HTTP_PORT:-8545}"; then bad=1
        echo "❌ KEYGEN_RPC_HTTP_PORT='${KEYGEN_RPC_HTTP_PORT}' is not a port number (1-65535)" >&2; fi
    if ! keygen_is_port "${KEYGEN_RPC_WS_PORT:-8546}"; then bad=1
        echo "❌ KEYGEN_RPC_WS_PORT='${KEYGEN_RPC_WS_PORT}' is not a port number (1-65535)" >&2; fi
    [ "${bad}" = 0 ]
}

# keygen_already_keyed <inst> <zone> <addr> <ddir> — rc 0 iff the node is keyed for <addr>:
# its .node-meta records VALIDATOR_ADDRESS=<addr> (v2 records the --address value as given)
# AND <ddir>/node-info.yaml is a non-empty file. Two read-only sessions; a node that cannot
# be read (a transport fault, no .node-meta) counts as not keyed: nothing is reused on a
# guess. Prints what it found.
keygen_already_keyed() {
    local inst="$1" zone="$2" addr="$3" ddir="$4" have_addr have_info=0 out info_word=missing
    have_addr="$(tn_node_meta_get "${inst}" "${zone}" VALIDATOR_ADDRESS)" || have_addr=""
    out="$(tn_iap_ssh "${inst}" "${zone}" \
        "sudo test -s '${ddir}/node-info.yaml' && echo __tn_info=1 || echo __tn_info=0")" || out=""
    case "${out}" in *__tn_info=1*) have_info=1; info_word=present ;; esac
    echo "      ${inst}: VALIDATOR_ADDRESS=${have_addr:-<none>} node-info.yaml=${info_word}"
    [ "${have_addr}" = "${addr}" ] && [ "${have_info}" = 1 ] || return 1
}

# keygen_info_rpc <node-info.yaml> <http|ws> — the worker RPC URL the file advertises (its
# first `<key>: "<url>"` line), or "-".
keygen_info_rpc() {
    local v nl=$'\n'
    v="$(sed -n "s/^[[:space:]]*$2:[[:space:]]*\"\{0,1\}\([^\"[:space:]]*\)\"\{0,1\}[[:space:]]*\$/\1/p" "$1" 2>/dev/null)" || v=""
    v="${v%%${nl}*}"
    printf '%s' "${v:--}"
}

# keygen_fetch_info <node> <inst> <zone> <role_dir> <info_src> — copy the node's node-info.yaml
# down to genesis/<role_dir>/<node>.yaml (role_dir = tn_role_dir: validators or observers):
# collected+= (and kn_dest) on success, failed+= otherwise.
keygen_fetch_info() {
    local node="$1" inst="$2" zone="$3" rdir="$4" info_src="$5" tmp_remote local_dest

    # Pull node-info.yaml. It is not readable by the SSH user under the data dir, so
    # copy it to /tmp and chown to the SSH user before scp-ing it down.
    tmp_remote="/tmp/${node}.yaml"
    echo ">>> [${node}] staging node-info.yaml for download"
    if ! tn_iap_ssh "${inst}" "${zone}" \
        "sudo cp '${info_src}' '${tmp_remote}' && sudo chown \$(whoami) '${tmp_remote}'"; then
        echo "❌ [${node}] failed to stage node-info.yaml"
        failed+=("${node}")
        return 0
    fi

    local_dest="${GENESIS_LOCAL}/${rdir}/${node}.yaml"

    echo ">>> [${node}] downloading ${tmp_remote} -> ${local_dest}"
    if tn_iap_scp_down "${inst}" "${zone}" "${tmp_remote}" "${local_dest}"; then
        echo ">>> [${node}] collected node-info -> ${local_dest}"
        collected+=("${local_dest}")
        kn_dest="${local_dest}"
    else
        echo "❌ [${node}] failed to download node-info.yaml"
        failed+=("${node}")
    fi
}

# keygen_node_steps <index> — keygen on one node (or, with KEYGEN_REUSE_EXISTING=1, proof
# that it is keyed already), then keygen_fetch_info. A failure is recorded in failed[] and
# returns 0: it fails this node, not the run.
keygen_node_steps() {
    local i="$1" inst zone node role rdir setup ddir addr extIP intIP rpc_http rpc_ws remote_cmd nlog
    local keygen_rc keygen_out done_line reuse_why info_src info_path pub gw
    local -a keygen_args
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    node="${NODE_NAMES[$i]}"
    role="$(tn_node_role "$i")"
    setup="$(tn_setup_script_for_role "${role}")"
    ddir="$(tn_data_dir_for_role "${role}")"
    addr="${EXECUTION_ADDRESSES[$i]}"

    echo ""
    echo ">>> [${node}] keygen on ${inst} (${zone}) role=${role}"
    if ! rdir="$(tn_role_dir "$i")"; then
        failed+=("${node}")
        return 0
    fi

    echo ">>> [${node}] resolving external + internal IP"
    # `|| x=""`: under `set -e` a failed lookup (an API fault, a gcloud crash) would end the
    # whole run; empty fails this node below instead.
    extIP="$(tn_node_ext_ip "${inst}" "${zone}")" || extIP=""
    intIP="$(tn_node_int_ip "${inst}" "${zone}")" || intIP=""
    if [ -z "${extIP}" ] || [ -z "${intIP}" ]; then
        echo "❌ [${node}] could not resolve IPs (ext='${extIP}' int='${intIP}') — skipping"
        failed+=("${node}")
        return 0
    fi
    echo ">>> [${node}] extIP=${extIP} intIP=${intIP} addr=${addr}"

    # The JSON-RPC endpoints node-info.yaml advertises. telcoin-network attaches RpcInfo to
    # the WORKER entry only (primary stays null) and publishes it through the kademlia node
    # record, so wallets/dapps (and peers forwarding transactions) can discover where to
    # submit them. devnet-genesis-build.sh then carries it from node-info into
    # genesis/committee.yaml, which is what makes it SURVIVE a full redeploy -- the genesis/
    # files are regenerated every run, so hand-editing them would not. Trailing slash
    # matches how Url serializes (https://host -> https://host/).
    # domain (default): the PUBLIC endpoints, through Caddy on :443, not reth's loopback
    # 8545/8546. internal-ip: reth's own listeners on the node's internal IP, for a fleet
    # with no public names (the bench: a node forwarding to benchNN.bench.invalid failed).
    # Launch 2 (TN_GATEWAY_ENABLE=1, domain mode): a node fronted by a worker gateway
    # advertises its public domain over https only (the gateway carries no WebSocket); the rpc
    # node advertises nothing here, its URL is set by the public-RPC edge after it starts.
    # With gateways off the rpc node advertises https:// and wss:// on its own public name.
    # setup-node.sh passes --rpc-ws to the keytool only together with --rpc-http and builds
    # no RPC argument at all when neither is given.
    gw="$(tn_gateway_mode "$i")"
    if [ "${KEYGEN_RPC_ADVERTISE:-domain}" = internal-ip ]; then
        rpc_http="http://${intIP}:${KEYGEN_RPC_HTTP_PORT:-8545}/"
        rpc_ws="ws://${intIP}:${KEYGEN_RPC_WS_PORT:-8546}/"
    elif [ "${TN_GATEWAY_ENABLE:-0}" = 1 ] && [ "${role}" = rpc ]; then
        rpc_http=""
        rpc_ws=""
    elif [ "${TN_GATEWAY_ENABLE:-0}" = 1 ] && { [ "${gw}" = same-host ] || [ "${gw}" = standalone ]; }; then
        if ! pub="$(tn_public_domain "$i")"; then
            failed+=("${node}")
            return 0
        fi
        rpc_http="https://${pub}/"
        rpc_ws=""
    elif [ "${role}" = rpc ]; then
        # No gateway model in force (TN_GATEWAY_ENABLE not 1): the rpc node serves RPC under its
        # own public name (tn_public_domain: RPC_HOSTNAME), http and ws, like any node without a
        # gateway, and the URL finalize records (--public-rpc-url / --public-ws-url).
        if ! pub="$(tn_public_domain "$i")"; then
            failed+=("${node}")
            return 0
        fi
        rpc_http="https://${pub}/"
        rpc_ws="wss://${pub}/"
    else
        rpc_http="https://${node}.${BASE_DOMAIN}/"
        rpc_ws="wss://${node}.${BASE_DOMAIN}/"
    fi

    # The keygen args, the same for every role. Multiaddrs use the fixed devnet
    # consensus ports (49590 primary / 49594 worker). --data-dir and --service-user
    # restate v2's defaults (/var/lib/telcoin, telcoin) so config.sh stays the one place
    # that names them; keygen records both in .node-meta for finalize.
    keygen_args=(
        --json
        --phase=keygen
        --network devnet
        --install-method docker
        --docker-image "${DOCKER_IMAGE}"
        # The passphrase arrives on stdin (see SECURITY above); this flag carries no secret.
        --passphrase-stdin
        --address "${addr}"
        --external-primary "/ip4/${extIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --external-worker "/ip4/${extIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --listener-primary "/ip4/${intIP}/udp/${DEFAULT_PRIMARY_UDP_PORT}/quic-v1"
        --listener-worker "/ip4/${intIP}/udp/${DEFAULT_WORKER_UDP_PORT}/quic-v1"
        --public-ip "${extIP}"
        --data-dir "${ddir}"
        --service-user "${SERVICE_USER}"
        # Accepted but unused at keygen in v2 (see the header): finalize writes the name.
        --advertised-name "${node}"
    )
    # The advertised RPC, each flag only when set (both are set on every path but launch 2's,
    # in this order, so that argv is unchanged).
    if [ -n "${rpc_http}" ]; then keygen_args+=(--rpc-http "${rpc_http}"); fi
    if [ -n "${rpc_ws}" ]; then keygen_args+=(--rpc-ws "${rpc_ws}"); fi

    # The remote command holds no secret, so it is echoed as is. Every value above comes
    # from config.sh or GCP and has no shell metacharacters: the plain join is the
    # remote argv word for word.
    remote_cmd="sudo bash '${setup}' ${keygen_args[*]}"
    nlog="${RUN_LOG_DIR}/${inst}.log"
    echo ">>> [${node}] running: ${remote_cmd}"
    echo ">>> [${node}] passphrase on stdin; setup-node.sh stderr -> ${nlog}"

    # STDOUT only is captured (the JSON events); stderr is appended to the run log. The
    # exit status is kept, not acted on at once, so the done line can say what failed.
    keygen_rc=0
    keygen_out="$(printf '%s\n' "${TN_BLS_PASSPHRASE}" \
        | tn_iap_ssh_cmd_stdin "${inst}" "${zone}" "${remote_cmd}" 2>>"${nlog}")" || keygen_rc=$?
    [ -n "${keygen_out}" ] && printf '%s\n' "${keygen_out}" >>"${nlog}"
    done_line="$(tn_json_done_line "${keygen_out}")"
    # node-info.yaml is at <DATA_DIR>/node-info.yaml.
    info_src="${ddir}/node-info.yaml"

    # KEYGEN_REUSE_EXISTING=1: keygen did not run here because the node is keyed already
    # (v2 refuses over its own keys and over an installed node), or its done line never came
    # back (the ssh dropped, perhaps after the keys were written). Such a node is used only
    # once it proves it is keyed for this address.
    reuse_why=""
    if [ "${KEYGEN_REUSE_EXISTING:-0}" = 1 ]; then
        if [ -z "${done_line}" ]; then
            reuse_why="no done event, rc=${keygen_rc}"
        elif ! tn_json_true "${done_line}" ok; then
            case "$(tn_json_str "${done_line}" msg)" in
                *"already installed"*|*"node-keys already exist"*) reuse_why="$(tn_json_str "${done_line}" msg)" ;;
            esac
        fi
    fi

    if [ -n "${reuse_why}" ]; then
        echo ">>> [${node}] keygen did not run (${reuse_why}); checking whether ${inst} is keyed for ${addr}"
        if ! keygen_already_keyed "${inst}" "${zone}" "${addr}" "${ddir}"; then
            echo "❌ [${node}] not reusing ${inst}: it is not keyed for ${addr} with a node-info.yaml — see ${nlog}:"
            tail -n 5 "${nlog}" | sed 's/^/      /'
            failed+=("${node}")
            return 0
        fi
        echo ">>> [${node}] already keyed for ${addr} on ${inst}: reusing its node-info.yaml"
        kn_reused=1
    else
        if [ -z "${done_line}" ]; then
            echo "❌ [${node}] keygen sent no done event (rc=${keygen_rc}; ssh failed or dropped?) — see ${nlog}:"
            tail -n 5 "${nlog}" | sed 's/^/      /'
            failed+=("${node}")
            return 0
        fi
        if [ "${keygen_rc}" -ne 0 ] || ! tn_json_true "${done_line}" ok; then
            echo "❌ [${node}] keygen failed (rc=${keygen_rc}): $(tn_json_str "${done_line}" msg) — see ${nlog}"
            failed+=("${node}")
            return 0
        fi
        echo ">>> [${node}] keygen ok: $(tn_json_str "${done_line}" msg)"

        # The done line names the file keygen wrote; any other path means the node's data
        # dir is not config.sh's, so stop here rather than download a file from somewhere else.
        info_path="$(tn_json_str "${done_line}" node_info_path)"
        if [ -n "${info_path}" ] && [ "${info_path}" != "${info_src}" ]; then
            echo "❌ [${node}] keygen wrote ${info_path}, not ${info_src} — not downloading"
            failed+=("${node}")
            return 0
        fi
    fi

    keygen_fetch_info "${node}" "${inst}" "${zone}" "${rdir}" "${info_src}"
}

# keygen_report <index> <t0> <failed-before> — KEYGEN_REPORT=1: the node's KEYGEN_DONE line
# (rc 0 = collected, 1 = failed; secs since <t0>; the URLs its collected node-info advertises).
keygen_report() {
    local rc=0 http=- ws=-
    [ "${KEYGEN_REPORT:-0}" = 1 ] || return 0
    if [ "${#failed[@]}" -gt "$3" ]; then rc=1; fi
    if [ "${rc}" = 0 ] && [ -n "${kn_dest}" ]; then
        http="$(keygen_info_rpc "${kn_dest}" http)"
        ws="$(keygen_info_rpc "${kn_dest}" ws)"
    fi
    echo "KEYGEN_DONE ${INSTANCE_NAMES[$1]} rc=${rc} secs=$(( $(date +%s) - $2 )) reused=${kn_reused} rpc_http=${http} rpc_ws=${ws}"
}

# keygen_node <index> — one node of a keygen run (the loop body); always rc 0.
keygen_node() {
    local t0 nfail="${#failed[@]}"
    t0="$(date +%s)"
    kn_reused=0 kn_dest=""
    keygen_node_steps "$1"
    keygen_report "$1" "${t0}" "${nfail}"
}

# keygen_pull_node <index> — one node of a --pull-only run: download only; always rc 0.
keygen_pull_node() {
    local i="$1" t0 nfail="${#failed[@]}" role rdir
    t0="$(date +%s)"
    kn_reused=1 kn_dest=""
    role="$(tn_node_role "$i")"
    echo ""
    echo ">>> [${NODE_NAMES[$i]}] pull-only: node-info.yaml from ${INSTANCE_NAMES[$i]} (${ZONES[$i]}) role=${role}"
    if rdir="$(tn_role_dir "$i")"; then
        keygen_fetch_info "${NODE_NAMES[$i]}" "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "${rdir}" \
            "$(tn_data_dir_for_role "${role}")/node-info.yaml"
    else
        failed+=("${NODE_NAMES[$i]}")
    fi
    keygen_report "$i" "${t0}" "${nfail}"
}

# keygen_job <fn> <index> — one background node for keygen_run: its own empty collected[]
# and failed[], its output in ${RUN_LOG_DIR}/<inst>.out/.err, its result in <inst>.res
# ("collected <file>" / "failed <node>" lines), written last: a job that died under
# `set -e` leaves no .res.
keygen_job() {
    local base="${RUN_LOG_DIR}/${INSTANCE_NAMES[$2]}" f
    rm -f "${base}.res"
    collected=() failed=()
    "$1" "$2" >"${base}.out" 2>"${base}.err"
    {
        for f in ${collected[@]+"${collected[@]}"}; do printf 'collected %s\n' "${f}"; done
        for f in ${failed[@]+"${failed[@]}"}; do printf 'failed %s\n' "${f}"; done
    } >"${base}.res.tmp"
    mv "${base}.res.tmp" "${base}.res"
}

# keygen_reap <index> <pid> — print a finished background node's output (stdout, then its
# stderr on stderr) and take its result into collected[] / failed[].
keygen_reap() {
    local base="${RUN_LOG_DIR}/${INSTANCE_NAMES[$1]}" rc=0 line
    wait "$2" || rc=$?
    cat "${base}.out"
    cat "${base}.err" >&2
    if [ ! -f "${base}.res" ]; then
        echo "❌ [${NODE_NAMES[$1]}] keygen job ended (rc=${rc}) without a result — see ${base}.err"
        failed+=("${NODE_NAMES[$1]}")
        return 0
    fi
    while IFS= read -r line; do
        case "${line}" in
            "collected "*) collected+=("${line#collected }") ;;
            "failed "*) failed+=("${line#failed }") ;;
        esac
    done <"${base}.res"
    rm -f "${base}.res"
}

# keygen_kill_tree <pid> — SIGTERM <pid> and every LOCAL process below it (the node's
# subshells, gcloud, ssh), each recorded in KEYGEN_KILLED. A process is stopped (SIGSTOP)
# before its children are listed, so it cannot start another one in between, then sent
# TERM and continued. As devnet-finalize.sh's _kill_tree, it cannot stop a remote keygen
# that already connected (no pty, so no SIGHUP): that one runs to its end on the node, and
# a re-run meets it as "node-keys already exist" (KEYGEN_REUSE_EXISTING=1 reuses it).
KEYGEN_KILLED=()
keygen_kill_tree() {
    local kids c
    kill -STOP "$1" 2>/dev/null || return 0
    kids="$(ps -A -o pid= -o ppid= 2>/dev/null | awk -v p="$1" '$2 == p { print $1 }')"
    kill -TERM "$1" 2>/dev/null || true
    kill -CONT "$1" 2>/dev/null || true
    KEYGEN_KILLED+=("$1")
    for c in ${kids}; do keygen_kill_tree "${c}"; done
}

# keygen_stop_jobs <signal> — the INT/TERM/HUP trap of keygen_run: kill the tree of every
# node job not yet reaped, wait for the jobs, give their descendants (reparented, so not
# ours to wait for) up to 5 s to exit, then SIGKILL any left. Nothing of a stopped node is
# printed or collected.
keygen_stop_jobs() {
    local p n=0 alive
    echo "⚠️  keygen: SIG$1 — stopping the node jobs still running; a remote keygen that already started may finish on its node" >&2
    KEYGEN_KILLED=()
    for p in ${KEYGEN_JOB_PIDS[@]+"${KEYGEN_JOB_PIDS[@]}"}; do keygen_kill_tree "${p}"; done
    for p in ${KEYGEN_JOB_PIDS[@]+"${KEYGEN_JOB_PIDS[@]}"}; do wait "${p}" 2>/dev/null || true; done
    while :; do
        alive=0
        for p in ${KEYGEN_KILLED[@]+"${KEYGEN_KILLED[@]}"}; do
            if kill -0 "${p}" 2>/dev/null; then alive=1; fi
        done
        if [ "${alive}" = 0 ] || [ "${n}" -ge 50 ]; then break; fi
        sleep 0.1
        n=$((n + 1))
    done
    for p in ${KEYGEN_KILLED[@]+"${KEYGEN_KILLED[@]}"}; do
        if kill -0 "${p}" 2>/dev/null; then kill -KILL "${p}" 2>/dev/null || true; fi
    done
}

# keygen_run <fn> <index>... — <fn> <index> for every node. KEYGEN_JOBS=1 (the default): in
# this shell, one after the other, the loop this replaced. KEYGEN_JOBS=N>1: up to N nodes at
# once (keygen_job); a node's output is printed whole, in index order, once it and every node
# before it are done. Polled once a second: bash 3.2 has no `wait -n`, and waiting on the
# oldest job instead would idle the other slots behind one slow node. While jobs run, INT,
# TERM or HUP stops them (a background job ignores the terminal's INT, so it and its gcloud
# would otherwise outlive the script and still write genesis/*/<node>.yaml), then exits
# 130/143/129. KEYGEN_JOB_PIDS holds the jobs not yet reaped (indexed like idx).
KEYGEN_JOB_PIDS=()
keygen_run() {
    local fn="$1" k n next=0 head=0 running idx fin
    shift
    if [ "${KEYGEN_JOBS:-1}" -le 1 ]; then
        for k in "$@"; do "${fn}" "${k}"; done
        return 0
    fi
    idx=("$@"); fin=(); KEYGEN_JOB_PIDS=()
    n="${#idx[@]}"
    trap 'keygen_stop_jobs INT; exit 130' INT
    trap 'keygen_stop_jobs TERM; exit 143' TERM
    trap 'keygen_stop_jobs HUP; exit 129' HUP
    while [ "${head}" -lt "${n}" ]; do
        running=0
        k="${head}"
        while [ "${k}" -lt "${next}" ]; do
            if [ -z "${fin[k]:-}" ]; then
                if kill -0 "${KEYGEN_JOB_PIDS[k]}" 2>/dev/null; then running=$((running + 1)); else fin[k]=1; fi
            fi
            k=$((k + 1))
        done
        while [ "${next}" -lt "${n}" ] && [ "${running}" -lt "${KEYGEN_JOBS}" ]; do
            keygen_job "${fn}" "${idx[next]}" &
            KEYGEN_JOB_PIDS[next]=$!
            next=$((next + 1))
            running=$((running + 1))
        done
        while [ "${head}" -lt "${next}" ] && [ -n "${fin[head]:-}" ]; do
            keygen_reap "${idx[head]}" "${KEYGEN_JOB_PIDS[head]}"
            unset "KEYGEN_JOB_PIDS[${head}]"
            head=$((head + 1))
        done
        if [ "${head}" -lt "${n}" ]; then sleep 1; fi
    done
    trap - INT TERM HUP
}

PULL_ONLY=0
if [ "${1:-}" = "--pull-only" ]; then
    PULL_ONLY=1
    shift
fi
keygen_check_knobs || exit 1

# The targets are resolved first, before the passphrase is read or any node is touched: an
# unknown target, or an entry that runs no node, ends the run here with rc 2 (as
# devnet-finalize.sh does). --pull-only keeps the rc 1 it always gave for a bad target
# (benchmark/tests/test_keygen.py holds it to that). The verdict is taken from $(...): read
# through a process substitution it was lost, and one bad target emptied the selection and
# let a keygen run exit 0 having keyed nothing.
# macOS /bin/bash is 3.2 and lacks `mapfile`; this read-loop is the portable equivalent.
INDICES=()
if ! _sel="$(tn_select_indices "$@")"; then
    if [ "${PULL_ONLY}" = 1 ]; then exit 1; fi
    exit 2
fi
while IFS= read -r _idx; do
    if [ -n "${_idx}" ]; then INDICES+=("${_idx}"); fi
done <<< "${_sel}"

if [ "${PULL_ONLY}" = 1 ]; then
    # Nothing is generated, so the passphrase is not needed: drop any inherited copy.
    unset TN_BLS_PASSPHRASE
else
    echo ">>> resolving BLS passphrase (never logged)"
    if ! tn_require_bls_passphrase; then
        exit 1
    fi
    # A shell variable from here on, not an environment variable: tn_require_bls_passphrase
    # exports it, and every gcloud/ssh child would inherit it. It travels on stdin only.
    export -n TN_BLS_PASSPHRASE
fi

if [ "${PULL_ONLY}" = 1 ]; then
    if [ "${#INDICES[@]}" -eq 0 ]; then
        echo "❌ --pull-only: no node selected" >&2
        exit 1
    fi
    echo ">>> pull-only (no keygen): node-info.yaml from ${#INDICES[@]} node(s) — ${INDICES[*]}"
else
    echo ">>> keygen targets: ${#INDICES[@]} node(s) — ${INDICES[*]}"
fi

# Local collection dirs for the pulled node-info files. GENESIS_WORKSPACE (config.sh)
# is REPO_ROOT for devnet; a profile such as benchmark/ points it at its own tree.
GENESIS_LOCAL="${GENESIS_WORKSPACE:-${REPO_ROOT}}/genesis"
mkdir -p "${GENESIS_LOCAL}/validators" "${GENESIS_LOCAL}/observers"

# Per-run log: each node's setup-node.sh stderr (its human-readable progress) and the
# JSON events it sent. The passphrase never reaches it (it only rides the ssh stdin).
RUN_LOG_DIR="${REPO_ROOT}/logs/$(date +%Y%m%d_%H%M%S)-keygen"
mkdir -p "${RUN_LOG_DIR}"
echo ">>> per-node logs: ${RUN_LOG_DIR}"

collected=()
failed=()
kn_reused=0     # per node: 1 when its node-info was reused, not generated by this run
kn_dest=""      # per node: the node-info file collected for it

if [ "${PULL_ONLY}" = 1 ]; then
    keygen_run keygen_pull_node "${INDICES[@]}"
else
    keygen_run keygen_node "${INDICES[@]}"
fi

echo ""
echo "========================================="
echo "keygen summary"
echo "========================================="
echo "collected node-info files (${#collected[@]}):"
for f in "${collected[@]}"; do echo "  - ${f}"; done
if [ "${#failed[@]}" -gt 0 ]; then
    echo "failed nodes (${#failed[@]}):"
    for n in "${failed[@]}"; do echo "  - ${n}"; done
    echo "per-node logs: ${RUN_LOG_DIR}"
    exit 1
fi
echo "per-node logs: ${RUN_LOG_DIR}"
if [ "${PULL_ONLY}" = 1 ]; then
    echo "all targeted nodes collected (pull-only: nothing generated). Next: ./devnet-genesis-build.sh"
else
    echo "all targeted nodes keyed and collected. Next: ./devnet-genesis-build.sh"
fi
