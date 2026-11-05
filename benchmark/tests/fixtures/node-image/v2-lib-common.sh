# Stand-in for tn-node-deployment lib/common.sh on a sandbox v2 node (test_node_image.py): what
# a bench remote script reaches through `tnlib` (bench_remote_lib_preamble), nothing more.
# Sourcing it logs the DEVNET_RPC_URL the sourcing shell exported (the real lib reads it once,
# readonly, as the quorum guard's public RPC). The launch-flag pair edits the node command of a
# tn-start-docker the way the real lib does (the words after `telcoin node` on its one live
# `docker run` line; the first occurrence of a flag wins, a repeat is dropped, a new flag is
# appended), with the real rc table:
#   tn_launch_flag_set FILE FLAG VALUE  0 set · 1 FLAG already reads VALUE · 3 bad FLAG / VALUE
#                                       (empty, leading - or #, not one word) · 4 FILE missing
#   tn_launch_flag_get FILE FLAG        0 printed · 1 absent · 2 no node line · 3 bad FLAG · 4 FILE missing
#   tn_write_root_file DEST MODE [GROUP] stdin -> DEST with MODE (rc 1: DEST not absolute, a directory or
#                                       a symlink, MODE not 3-4 octal digits; 2: the write failed)
# STUB_LIB_FORCE="<op>:<flag>=<rc> ..." makes that call return <rc> untouched (a refused write).
# Each call logs `lib <op> <flag> [<value>] rc=<rc>` to $STUB_LOG.
set -euo pipefail
# The lib's log layout (lib/common.sh: readonly DEFAULT_LOG_DIR, TN_LOG_GROUP), the log dir moved under
# the sandbox node (STUB_NODE, set by v2-node-run.sh).
# shellcheck disable=SC2034  # read by the sourcing shell (tnlib eval), as the real lib's are
readonly DEFAULT_LOG_DIR="${STUB_NODE:-}/var/log/telcoin" TN_LOG_GROUP="telcoin-log"
printf 'lib source DEVNET_RPC_URL=%s\n' "$(printenv DEVNET_RPC_URL || echo '<unset>')" >> "${STUB_LOG:?}"

_stub_forced() {
    local w
    for w in ${STUB_LIB_FORCE:-}; do
        case "${w}" in "$1:$2="*) printf '%s' "${w#*=}"; return 0 ;; esac
    done
    return 1
}

# _stub_node_line FILE — "<line number>:<line>" of the live (non-comment) `telcoin node` line.
_stub_node_line() { grep -n -E '^[^#]*[[:space:]]telcoin node([[:space:]]|$)' "$1" | tail -1; }

_stub_get() {
    local file="$1" flag="$2" l i
    local -a w
    [ -n "${file}" ] && [ -f "${file}" ] && [ -r "${file}" ] || return 4
    case "${flag}" in --[A-Za-z0-9]*) ;; *) return 3 ;; esac
    l="$(_stub_node_line "${file}")" || return 2
    read -r -a w <<< "${l#*telcoin node}"
    for i in "${!w[@]}"; do
        if [ "${w[$i]}" = "${flag}" ]; then printf '%s\n' "${w[$((i + 1))]:-}"; return 0; fi
    done
    return 1
}

_stub_set() {
    local file="$1" flag="$2" value="${3:-}" l n out="" skip=0 seen=0 cur rc=0 x
    local -a w
    [ -n "${file}" ] && [ -f "${file}" ] && [ -r "${file}" ] || return 4
    case "${flag}" in --[A-Za-z0-9]*) ;; *) return 3 ;; esac
    case "${value}" in ''|-*|'#'*|*[[:space:]]*) return 3 ;; esac
    cur="$(_stub_get "${file}" "${flag}")" || rc=$?
    if [ "${rc}" = 0 ] && [ "${cur}" = "${value}" ]; then return 1; fi
    l="$(_stub_node_line "${file}")" || return 3
    n="${l%%:*}"; l="${l#*:}"
    read -r -a w <<< "${l#*telcoin node}"
    for x in ${w[@]+"${w[@]}"}; do
        if [ "${skip}" = 1 ]; then skip=0; continue; fi
        if [ "${x}" = "${flag}" ]; then
            skip=1
            [ "${seen}" = 0 ] || continue
            seen=1; out="${out} ${flag} ${value}"; continue
        fi
        out="${out} ${x}"
    done
    [ "${seen}" = 1 ] || out="${out} ${flag} ${value}"
    STUB_LINE="${l%%telcoin node*}telcoin node${out}" awk -v n="${n}" \
        'NR == n + 0 { print ENVIRON["STUB_LINE"]; next } { print }' "${file}" > "${file}.stub-new"
    cat "${file}.stub-new" > "${file}"
    rm -f "${file}.stub-new"
}

tn_launch_flag_get() {
    local rc=0 forced
    if forced="$(_stub_forced get "${2:-}")"; then rc="${forced}"
    else _stub_get "${1:-}" "${2:-}" || rc=$?; fi
    printf 'lib get %s rc=%s\n' "${2:-}" "${rc}" >> "${STUB_LOG}"
    return "${rc}"
}

tn_launch_flag_set() {
    local rc=0 forced
    if forced="$(_stub_forced set "${2:-}")"; then rc="${forced}"
    else _stub_set "$@" || rc=$?; fi
    printf 'lib set %s %s rc=%s\n' "${2:-}" "${3:-}" "${rc}" >> "${STUB_LOG}"
    return "${rc}"
}

tn_write_root_file() {
    local dest="${1:-}" mode="${2:-}" rc=0
    case "${dest}" in /*/) rc=1 ;; /*) ;; *) rc=1 ;; esac
    case "${mode}" in [0-7][0-7][0-7]|[0-7][0-7][0-7][0-7]) ;; *) rc=1 ;; esac
    if [ "${rc}" = 0 ] && { [ -L "${dest}" ] || [ -d "${dest}" ]; }; then rc=1; fi
    if [ "${rc}" = 0 ]; then
        { cat > "${dest}.stub-new" && chmod "${mode}" "${dest}.stub-new" && mv -f "${dest}.stub-new" "${dest}"; } || rc=2
    else
        cat > /dev/null
    fi
    printf 'lib write %s %s rc=%s\n' "${dest}" "${mode}" "${rc}" >> "${STUB_LOG}"
    return "${rc}"
}
