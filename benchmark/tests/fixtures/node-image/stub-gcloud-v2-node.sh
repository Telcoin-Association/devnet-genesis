#!/usr/bin/env bash
# gcloud for the deploy steps that run a script on every node (test_node_image.py Step7Tests,
# Step9Tests). Logs every call to $STUB_LOG.
#   compute ssh <inst> ... --command=sudo bash -s   (tn_iap_ssh_stdin) -> the script on stdin is
#       kept as $STUB_SPOOL/<inst>.sh and run on the sandbox node $STUB_NODES/<inst> by
#       v2-node-run.sh (installed next to this file); its output is the session's. A node with
#       no sandbox answers like an unreachable host (rc 255).
#   anything else -> fails loudly.
printf 'gcloud %s\n' "$*" >> "${STUB_LOG:?}"
case "$*" in
    "compute ssh "*)
        inst="$3"; cmd=""
        for a in "$@"; do case "${a}" in --command=*) cmd="${a#--command=}" ;; esac; done
        [ "${cmd}" = "sudo bash -s" ] || { echo "stub gcloud: unexpected ssh command: ${cmd}" >&2; exit 1; }
        node="${STUB_NODES:?}/${inst}"
        [ -d "${node}" ] || { cat > /dev/null; echo "ssh: connect to host ${inst} port 22: Connection timed out" >&2; exit 255; }
        cat > "${STUB_SPOOL:?}/${inst}.sh"
        echo "Warning: Permanently added 'compute.0000' (ED25519) to the list of known hosts."
        exec bash "$(dirname "$0")/v2-node-run.sh" "${node}" < "${STUB_SPOOL}/${inst}.sh" ;;
    *) echo "stub gcloud: unexpected: $*" >&2; exit 1 ;;
esac
