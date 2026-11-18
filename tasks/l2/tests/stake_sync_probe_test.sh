#!/usr/bin/env bash
#
# stake_sync_probe_test.sh: contained test of the step 4 sync gate (sync_probe) of
# devnet-stake-node5.sh.
#
# The script is run with TN_STAKE_NODE5_TEST_HOOKS set to a hook written here. The hook replaces
# ref_head, node5_head and node5_mode with stubs that return scripted values (an empty value makes
# the stub fail) and record the order they were called in, calls sync_probe once per case, prints
# PASS/FAIL per case and exits before any step runs.
#
# No network, no secrets: CONFIG_FILE is a stub config written here (two fake nodes), and PATH
# starts with stub gcloud / ssh / scp / curl / cast / docker / gsutil that record the attempt and
# fail. The test fails if any of them was called, or if a step header was printed.
#
# Usage, from the repo root:
#   bash tasks/l2/tests/stake_sync_probe_test.sh [SCRIPT]
# SCRIPT defaults to ./devnet-stake-node5.sh. It is copied into a temp dir next to a copy of
# ./devnet-lib.sh, so an older copy (git show HEAD:devnet-stake-node5.sh > F) can be tested too.
# Exit 0 only if every case passes.
#
# Cases (SYNC_MAX_LAG=5; the reference is read first by a correct sync_probe):
#   (a) ref 2476, node 5 2487, Observer -> in sync, lag 0 (node 5 read later, past the reference)
#   (b) ref 1000, node 5 995,  Observer -> in sync, lag 5
#   (c) ref 1000, node 5 994,  Observer -> not in sync, lag 6
#   (d) ref 1000, node 5 1000, CvvActive -> not in sync (mode)
#   (e) node 5 unreachable (head and mode fail), ref 1000 -> not in sync, "(unreachable?)"
#   (f) ref_head is called before node5_head
#   (g) reference unreachable, node 5 1000, Observer -> not in sync, "(unreachable?)"

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../../.." && pwd)"
TARGET="${1:-${REPO_DIR}/devnet-stake-node5.sh}"
[ -f "${TARGET}" ] || { echo "no such script: ${TARGET}" >&2; exit 2; }

T="$(mktemp -d "${TMPDIR:-/tmp}/stake-sync-probe-test.XXXXXX")"
trap 'rm -rf "${T}"' EXIT
mkdir -p "${T}/stage" "${T}/bin"
cp "${TARGET}" "${T}/stage/devnet-stake-node5.sh"
cp "${REPO_DIR}/devnet-lib.sh" "${T}/stage/devnet-lib.sh"

# Anything that could reach the network or Secret Manager: record and fail.
for b in gcloud ssh scp curl cast docker gsutil; do
    printf '#!/bin/sh\necho "%s $*" >> "%s/network-attempts"\nexit 97\n' "${b}" "${T}" > "${T}/bin/${b}"
    chmod +x "${T}/bin/${b}"
done

cat > "${T}/config.sh" <<'EOF'
# stub config for stake_sync_probe_test.sh: two fake nodes, no real hosts or secrets
PROJECT_ID="none"
CHAIN_ID=0
RPC_URL="http://127.0.0.1:9"
NODE_NAMES=(node1 node5)
NODE_ROLES=(validator observer)
INSTANCE_NAMES=(test-validator-1 test-observer-5)
ZONES=(test-zone test-zone)
EXECUTION_ADDRESSES=(0x0000000000000000000000000000000000000001 0x0000000000000000000000000000000000000005)
SAFE_EXTRA_OWNER="0x0000000000000000000000000000000000000002"
DOCKER_IMAGE="none"
EPOCH_DURATION_SECS=60
NODE_RPC_PORT=8545
EOF

cat > "${T}/hook.sh" <<'EOF'
# Sourced by devnet-stake-node5.sh after every function is defined (set -euo pipefail applies).
ORDER_FILE="${STAKE_TEST_DIR}/order"
STUB_REF=""; STUB_N5=""; STUB_MODE=""
ref_head()   { echo ref_head >> "${ORDER_FILE}";   [ -n "${STUB_REF}" ] && printf '%s\n' "${STUB_REF}"; }
node5_head() { echo node5_head >> "${ORDER_FILE}"; [ -n "${STUB_N5}" ] && printf '%s\n' "${STUB_N5}"; }
node5_mode() { echo node5_mode >> "${ORDER_FILE}"; [ -n "${STUB_MODE}" ] && printf '%s\n' "${STUB_MODE}"; }

fails=0
lag_re='\((behind by|lag) ([0-9]+)\)'
# probe_case <label> <ref head> <node 5 head> <mode> <in|out> <lag N|unreachable>
probe_case() {
    local label="$1" want_rc="$5" want="$6" out rc ok=1 got
    STUB_REF="$2"; STUB_N5="$3"; STUB_MODE="$4"
    : > "${ORDER_FILE}"
    if out="$(sync_probe)"; then rc=0; else rc=$?; fi
    if [ "${want_rc}" = in ]; then [ "${rc}" -eq 0 ] || ok=0; else [ "${rc}" -ne 0 ] || ok=0; fi
    case "${want}" in
        unreachable) case "${out}" in *'(unreachable?)'*) ;; *) ok=0 ;; esac ;;
        *) got=""; if [[ ${out} =~ ${lag_re} ]]; then got="${BASH_REMATCH[2]}"; fi
           [ "${got}" = "${want#lag }" ] || ok=0 ;;
    esac
    if [ "${ok}" -eq 1 ]; then echo "PASS ${label}"; else echo "FAIL ${label}: rc ${rc}"; fails=$((fails + 1)); fi
    echo "     ${out#"${out%%[! ]*}"}"
}

probe_case "(a) ref 2476 then node 5 2487, Observer -> in sync, lag 0" 2476 2487 Observer in "lag 0"
probe_case "(b) ref 1000, node 5 995 -> in sync, lag 5"                 1000 995  Observer in "lag 5"
probe_case "(c) ref 1000, node 5 994 -> not in sync, lag 6"             1000 994  Observer out "lag 6"
probe_case "(d) ref 1000, node 5 1000, CvvActive -> not in sync"        1000 1000 CvvActive out "lag 0"
probe_case "(e) node 5 unreachable -> not in sync, (unreachable?)"      1000 ""   ""        out unreachable
probe_case "(g) reference unreachable -> not in sync, (unreachable?)"   ""   1000 Observer  out unreachable

STUB_REF=1000; STUB_N5=1000; STUB_MODE=Observer
: > "${ORDER_FILE}"
sync_probe >/dev/null || true
order="$(tr '\n' ' ' < "${ORDER_FILE}")"
case "${order}" in
    "ref_head node5_head "*) echo "PASS (f) ref_head before node5_head: ${order}" ;;
    *) echo "FAIL (f) ref_head before node5_head: ${order}"; fails=$((fails + 1)) ;;
esac

echo "HOOK-DONE fails=${fails}"
if [ "${fails}" -eq 0 ]; then exit 0; else exit 1; fi
EOF

set +e
out="$(
    unset TN_USE_VPN SYNC_MAX_LAG REF_RPC NODE5_RPC
    cd "${REPO_DIR}" &&
    STAKE_TEST_DIR="${T}" CONFIG_FILE="${T}/config.sh" TN_STAKE_NODE5_TEST_HOOKS="${T}/hook.sh" \
        TN_SSH_TRANSPORT=iap SYNC_MAX_LAG=5 PATH="${T}/bin:${PATH}" \
        bash "${T}/stage/devnet-stake-node5.sh" 2>&1
)"
rc=$?
set -e
printf '%s\n' "${out}"

status=0
case "${out}" in *"HOOK-DONE fails="*) ;; *) echo "FAIL: the hook never finished (the script exited before or inside it)"; status=1 ;; esac
case "${out}" in *">>> step"*) echo "FAIL: a step ran (the hook must exit first)"; status=1 ;; esac
if [ -s "${T}/network-attempts" ]; then
    echo "FAIL: network/secret tools were called:"; sed 's/^/     /' "${T}/network-attempts"; status=1
fi
[ "${rc}" -eq 0 ] || status=1
if [ "${status}" -eq 0 ]; then echo "ALL PASS (${TARGET})"; else echo "FAILED (${TARGET}; script rc ${rc})"; fi
exit "${status}"
