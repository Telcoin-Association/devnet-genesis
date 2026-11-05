#!/usr/bin/env bash
# Offline stand-in for gcloud (test_node_image.py). Logs every call to $STUB_LOG.
#   artifacts docker images describe  -> $STUB_DIGEST (fails when unset)
#   auth print-access-token           -> a dummy token
#   the bench-obs VM (obs-lib.sh: deploy steps 2, 8, 10, 13, 15), its state in $STUB_OBSVM_DIR
#   (default $TMPDIR/stub-bench-obs); stub-gcloud-v2-node.sh hands every bench-obs call here:
#     compute instances create bench-obs ...   -> created (argv kept in create.argv);
#         STUB_OBSVM_CREATE_FAIL=1: a quota error, rc 1
#     compute instances describe bench-obs ... -> "not found" (rc 1) until created (or STUB_OBSVM_EXISTS=1);
#         --format=json: the VM (internal IP $STUB_OBSVM_IP, default 192.0.2.50; tag bench-obs; labels
#         benchmark=1, bench-run=$STUB_OBSVM_RUN (default $BENCH_RUN_ID), tn-role=obs; id 4300);
#         --format=value(name|id|status|networkInterfaces[0].networkIP): that field
#     compute disks add-labels bench-obs[-data] ...      -> ok
#     compute instances get-serial-port-output bench-obs -> the startup-obs.sh done marker from the
#         $STUB_OBSVM_BOOT_CALLS-th call on (default 1), boot noise before
#     compute ssh bench-obs ... --command=sudo bash -s   -> its stdin kept as bringup.sh; a first line
#         '# bench-obs: bringup' answers OBS_STACK_OK (STUB_OBSVM_STACK=fail: OBS_STACK_FAIL, rc 1)
#     compute ssh bench-obs ... --command=<df ...>      -> a df answer ($STUB_OBSVM_DF_PCT, default 12)
#     compute ssh bench-obs ... -N -L ...               -> a forward: sleeps $STUB_TUNNEL_SECS (default 60)
# Anything else fails loudly (the deploy steps that ssh to nodes use stub-gcloud-v2-node.sh).
printf 'gcloud %s\n' "$*" >> "${STUB_LOG:?}"

bench_obs() {
    local d="${STUB_OBSVM_DIR:-${TMPDIR:?}/stub-bench-obs}" fmt="" cmd="" a n ip="${STUB_OBSVM_IP:-192.0.2.50}"
    mkdir -p "${d}"
    [ "${STUB_OBSVM_EXISTS:-0}" != 1 ] || [ -f "${d}/created" ] || : > "${d}/created"
    for a in "$@"; do
        case "${a}" in --format=*) fmt="${a#--format=}" ;; --command=*) cmd="${a#--command=}" ;; esac
    done
    case "$*" in
        "compute instances create "*)
            [ "${STUB_OBSVM_CREATE_FAIL:-0}" != 1 ] || { echo "ERROR: (gcloud.compute.instances.create) Quota 'CPUS' exceeded.  Limit: 0.0 in region us-west2." >&2; return 1; }
            printf '%s\n' "$@" > "${d}/create.argv"; : > "${d}/created"
            echo "Created [https://www.googleapis.com/compute/v1/projects/tn-fake/zones/us-west2-a/instances/$4]." ;;
        "compute instances describe "*)
            if [ ! -f "${d}/created" ]; then
                printf "ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n - The resource 'projects/tn-fake/zones/us-west2-a/instances/%s' was not found\n" "$4" >&2
                return 1
            fi
            case "${fmt}" in
                'value(name)') echo "$4" ;;
                'value(id)') echo 4300 ;;
                'value(status)') echo RUNNING ;;
                'value(networkInterfaces[0].networkIP)') echo "${ip}" ;;
                *) printf '{"name":"%s","id":"4300","status":"RUNNING","zone":"https://x/zones/us-west2-a","tags":{"items":["bench-obs"]},"labels":{"benchmark":"1","bench-run":"%s","tn-role":"obs"},"machineType":"https://x/zones/us-west2-a/machineTypes/e2-standard-4","networkInterfaces":[{"networkIP":"%s","accessConfigs":[{"natIP":"203.0.113.50"}]}],"disks":[{"boot":true,"source":"https://x/zones/us-west2-a/disks/%s"},{"boot":false,"deviceName":"obs-data","source":"https://x/zones/us-west2-a/disks/%s-data"}]}\n' \
                       "$4" "${STUB_OBSVM_RUN:-${BENCH_RUN_ID:-}}" "${ip}" "$4" "$4" ;;
            esac ;;
        "compute disks add-labels "*) ;;
        "compute instances get-serial-port-output "*)
            n=$(( $(cat "${d}/serial.n" 2>/dev/null || echo 0) + 1 )); echo "${n}" > "${d}/serial.n"
            echo "Nov  5 06:00:00 bench-obs google_metadata_script_runner[612]: startup-script: [obs-startup] mounting /mnt/obs-data"
            [ "${n}" -lt "${STUB_OBSVM_BOOT_CALLS:-1}" ] || echo "Nov  5 06:01:00 bench-obs google_metadata_script_runner[612]: startup-script: [obs-startup] done" ;;
        "compute ssh "*)
            case "$*" in
                *--ssh-flag=-N*|*" -N "*) exec sleep "${STUB_TUNNEL_SECS:-60}" ;;
            esac
            case "${cmd}" in
                "sudo bash -s")
                    cat > "${d}/bringup.sh"
                    [ "$(head -1 "${d}/bringup.sh")" = "# bench-obs: bringup" ] \
                        || { echo "stub gcloud: bench-obs session without the bringup header" >&2; return 1; }
                    if [ "${STUB_OBSVM_STACK:-ok}" = fail ]; then echo "OBS_STACK_FAIL bench-obs reason=prometheus-not-ready"; return 1; fi
                    echo "OBS_STACK_OK bench-obs prom=ready grafana=ok secs=4" ;;
                *df*) printf 'Use%%\n %s%%\n' "${STUB_OBSVM_DF_PCT:-12}" ;;
                *) echo "stub gcloud: unexpected bench-obs ssh command: ${cmd}" >&2; return 1 ;;
            esac ;;
        *) echo "stub gcloud: unexpected bench-obs call: $*" >&2; return 1 ;;
    esac
}

case " $3 $4 " in
    *" bench-obs "*|*" bench-obs-data "*) bench_obs "$@"; exit $? ;;
esac
case "$*" in
    "artifacts docker images describe "*) [ -n "${STUB_DIGEST:-}" ] || exit 1; echo "${STUB_DIGEST}" ;;
    "auth print-access-token"*) echo stub-token-not-a-secret ;;
    *) echo "stub gcloud: unexpected: $*" >&2; exit 1 ;;
esac
