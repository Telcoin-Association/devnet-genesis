#!/usr/bin/env bash
# Offline stand-in for gcloud (test_node_image.py). Logs every call to $STUB_LOG.
#   artifacts docker images describe  -> $STUB_DIGEST (fails when unset)
#   auth print-access-token           -> a dummy token
#   compute ssh <inst> ... --command=sudo bash -s   (deploy step 9) -> reads the script on
#       stdin (kept as $STUB_SPOOL/<inst>.sh when set) and answers like the node would:
#       POSTCFG_OK with sha $STUB_SHA, or $STUB_BAD_SHA for $STUB_BAD_INST
#   compute ssh <inst> ... (any other command, e.g. bench_save_node_log) -> success, no output
printf 'gcloud %s\n' "$*" >> "${STUB_LOG:?}"
case "$*" in
    "artifacts docker images describe "*) [ -n "${STUB_DIGEST:-}" ] || exit 1; echo "${STUB_DIGEST}" ;;
    "auth print-access-token"*) echo stub-token-not-a-secret ;;
    "compute ssh "*)
        inst="$3"; cmd=""
        for a in "$@"; do case "${a}" in --command=*) cmd="${a#--command=}" ;; esac; done
        if [ "${cmd}" = "sudo bash -s" ]; then
            if [ -n "${STUB_SPOOL:-}" ]; then cat > "${STUB_SPOOL}/${inst}.sh"; else cat > /dev/null; fi
            sha="${STUB_SHA:?}"
            [ "${inst}" != "${STUB_BAD_INST:-}" ] || sha="${STUB_BAD_SHA:?}"
            echo "Warning: Permanently added 'compute.0000' (ED25519) to the list of known hosts."
            echo "POSTCFG_OK ${inst} chain=0x7e1e block=0x5 ip=192.0.2.9 progress=blocks 3->5 sha=${sha} mhd=${STUB_MHD:-500} nhd=250 mbd=250 vt=? forks=subsecond-from-genesis"
        fi ;;
    *) echo "stub gcloud: unexpected: $*" >&2; exit 1 ;;
esac
