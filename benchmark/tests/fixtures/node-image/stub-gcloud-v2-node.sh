#!/usr/bin/env bash
# gcloud for the deploy steps that run a script on every node (test_node_image.py Step7Tests,
# Step9Tests) and for step 2 (ZoneFallbackTests). Logs every call to $STUB_LOG.
#   compute ssh <inst> ... --command=sudo bash -s   (tn_iap_ssh_stdin) -> the script on stdin is
#       kept as $STUB_SPOOL/<inst>.sh and run on the sandbox node $STUB_NODES/<inst> by
#       v2-node-run.sh (installed next to this file); its output is the session's. A node with
#       no sandbox answers like an unreachable host (rc 255). STUB_SSH_HANG=<secs>: every session first
#       sleeps that long.
#   auth print-access-token                    -> a dummy token
#   compute instances describe <inst> --zone=Z  -> the instance's JSON when the stub create-instances.sh
#       created it in zone Z ($STUB_SPOOL/instances/<inst> holds its zone), else "not found" (rc 1)
#   compute disks add-labels / disks describe / machine-types describe -> success, a 100 GB
#       hyperdisk-balanced boot disk, "8<TAB>16384" (c3-highcpu-8)
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
        [ -z "${STUB_SSH_HANG:-}" ] || sleep "${STUB_SSH_HANG}"   # a session that does not come back (tests kill the deploy)
        echo "Warning: Permanently added 'compute.0000' (ED25519) to the list of known hosts."
        exec bash "$(dirname "$0")/v2-node-run.sh" "${node}" < "${STUB_SPOOL}/${inst}.sh" ;;
    "auth print-access-token"*) echo stub-token-not-a-secret ;;
    "compute instances describe "*)
        inst="$4"; zone=""
        for a in "$@"; do case "${a}" in --zone=*) zone="${a#--zone=}" ;; esac; done
        f="${STUB_SPOOL:?}/instances/${inst}"
        if [ ! -f "${f}" ] || [ "$(cat "${f}")" != "${zone}" ]; then
            printf "ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n - The resource 'projects/tn-fake/zones/%s/instances/%s' was not found\n" "${zone}" "${inst}" >&2
            exit 1
        fi
        n="${inst##*-}"; n=$((10#${n}))
        printf '{"name":"%s","id":"%d","zone":"https://x/zones/%s","tags":{"items":["bench-node"]},"labels":{"benchmark":"1"},"machineType":"https://x/zones/%s/machineTypes/c3-highcpu-8","networkInterfaces":[{"networkIP":"198.51.100.%d","accessConfigs":[{"natIP":"203.0.113.%d"}]}],"disks":[{"boot":true,"source":"https://x/zones/%s/disks/%s"}]}\n' \
            "${inst}" "$((4200 + n))" "${zone}" "${zone}" "${n}" "${n}" "${zone}" "${inst}" ;;
    "compute disks add-labels "*) ;;
    "compute disks describe "*) printf '{"name":"%s","sizeGb":"100","type":"https://x/diskTypes/hyperdisk-balanced"}\n' "$4" ;;
    "compute machine-types describe "*) printf '8\t16384\n' ;;
    *) echo "stub gcloud: unexpected: $*" >&2; exit 1 ;;
esac
