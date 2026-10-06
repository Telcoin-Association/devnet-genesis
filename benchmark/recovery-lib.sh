#!/usr/bin/env bash
# Pure progress comparison. Nodes missing from either poll are unknown.
# Intended downtime and pauses reset the corresponding node's count.
bench_node_stall_counts() { # <previous> <current> <counts> <validators-json> <exempt-json>
    jq -cn --argjson prev "$1" --argjson cur "$2" --argjson counts "$3" \
        --argjson validators "$4" --argjson exempt "$5" '
        $validators | map(. as $node |
          {key: $node, value:
            (if ($exempt | index($node)) != null or
                $prev[$node] == null or $cur[$node] == null or
                $cur[$node] != $prev[$node]
             then 0 else (($counts[$node] // 0) + 1) end)})
        | from_entries'
}

# Pull auxiliary recovery evidence without changing what counts as a saved node log.
# A readable archive is required before teardown; missing sampler files on an older
# deployment are allowed and the service journal still lands.
bench_pull_recovery_evidence() { # <instance> <zone> <id> <destination>
    local inst="$1" zone="$2" id="$3" dest="$4" temporary saved remote_script
    # The script travels on stdin (tn_iap_ssh_stdin -> sudo bash -s). A --command string with
    # quotes nested inside quotes was parsed twice on the way to the node and broke the trap
    # line on the live fleet (2026-10-06); stdin needs no quoting at all.
    remote_script=$(cat <<'EOS'
set -e -o pipefail
recovery_tmp=$(mktemp -d)
trap 'rm -rf "$recovery_tmp"' EXIT
journalctl -u telcoin --no-pager -o short-iso-precise > "$recovery_tmp/telcoin.journal"
recovery_host=$(hostname -s)
for kind in csv epochs.txt; do
    path="/var/lib/bench-sampler/$recovery_host.$kind"
    [ ! -s "$path" ] || cp "$path" "$recovery_tmp/sampler.$kind"
done
tar -czf - -C "$recovery_tmp" .
EOS
)
    if [ "${BENCH_APPLY}" != 1 ]; then
        printf '    + recovery evidence: %s (instance %s) -> %s\n' "${inst}" "${id}" "${dest}"
        return 0
    fi
    for saved in "${dest}/${inst}-recovery-${id}."*.tgz; do
        if [ -f "${saved}" ] && tar -tzf "${saved}" >/dev/null 2>&1; then
            echo "    recovery evidence already saved: ${saved}"
            return 0
        fi
    done
    temporary="$(mktemp "${dest}/${inst}-recovery-${id}.XXXXXX")" || return 1
    if ! printf '%s\n' "${remote_script}" | tn_iap_ssh_stdin "${inst}" "${zone}" > "${temporary}" \
        || ! tar -tzf "${temporary}" >/dev/null; then
        rm -f "${temporary}"
        echo "recovery evidence not saved: ${inst}" >&2
        return 1
    fi
    mv "${temporary}" "${temporary}.tgz" || return 1
    echo "    recovery evidence: ${temporary}.tgz"
}
