#!/usr/bin/env bash
# Runs a bench remote script on a sandbox v2 node (test_node_image.py), the way the node would:
#   v2-node-run.sh <node-root>                    script on stdin, run as `bash -s` (`sudo bash -s`)
#   v2-node-run.sh <node-root> <script-file> <$0>  run as `bash -c <script> <$0>`, this stdin kept
#                                                 (step 8's session: its stdin is the token line)
# The script's absolute node paths move under <node-root> (the test lays out the v2 tree there,
# from fixtures/v2-node), the node stubs in <node-root>/bin go first on PATH, and the environment
# is a clean one (nothing of the deploy's shell reaches the node): PATH, HOME, TMPDIR, LC_ALL, and
# the STUB_* / POSTCFG_WAIT_SECS knobs of the stubs. Every stub logs to <node-root>/calls.
set -euo pipefail
R="${1:?node root}"
relocate() {
    sed -e "s#/etc/telcoin/#${R}/etc/telcoin/#g" \
        -e "s#/etc/systemd/system/#${R}/etc/systemd/system/#g" \
        -e "s#/etc/logrotate.d/#${R}/etc/logrotate.d/#g" \
        -e "s#/usr/local/libexec/telcoin/#${R}/usr/local/libexec/telcoin/#g" \
        -e "s#/usr/local/bin/bench-node-sampler.sh#${R}/usr/local/bin/bench-node-sampler.sh#g" \
        -e "s#/opt/telcoin-node-scripts#${R}/opt/telcoin-node-scripts#g" \
        -e "s#/var/lib/telcoin-alloy/#${R}/var/lib/telcoin-alloy/#g" \
        -e "s#/tmp/bench-obs#${R}/tmp/bench-obs#g" \
        -e "s#/usr/local/bin/bench-persist-sampler.sh#${R}/usr/local/bin/bench-persist-sampler.sh#g" \
        -e "s#/usr/local/bin/bench-folio-census.py#${R}/usr/local/bin/bench-folio-census.py#g" \
        -e "s#/etc/sysctl.d/#${R}/etc/sysctl.d/#g" \
        -e "s#/proc/sys/net/ipv4/ip_local_reserved_ports#${R}/proc/sys/net/ipv4/ip_local_reserved_ports#g"
}
keep=()
while IFS='=' read -r k _; do
    case "${k}" in
        STUB_LOG|STUB_NODE|STUB_STATE) ;;
        STUB_*|POSTCFG_WAIT_SECS) keep+=("${k}=${!k}") ;;
    esac
done < <(env)
run=(env -i "PATH=${R}/bin:/usr/local/bin:/usr/bin:/bin" "HOME=${R}" "TMPDIR=${R}/tmp" "LC_ALL=C"
     "STUB_NODE=${R}" "STUB_STATE=${R}/state" "STUB_LOG=${R}/calls" ${keep[@]+"${keep[@]}"})
if [ $# -ge 2 ]; then
    script="$(relocate < "$2")"
    exec "${run[@]}" bash -c "${script}" "${3:-bash}"
fi
script="$(relocate)"
printf '%s\n' "${script}" | "${run[@]}" bash -s
