#!/usr/bin/env bash
# Fake gcloud for test_blast_argv's create-path cases (`run --yes` without a fleet). Every call is logged
# to $CALLS as its shell-quoted argv. State lives in $STUB: vm-<name> is an instance (its describe JSON),
# create-<name> lists the outcome of that VM's 1st, 2nd, ... create call (no line left: ok), ip-<node>
# answers a node's networkIP describe, list.json an instances list, delete-fail fails every delete,
# delete-secs moves the fake clock ($NOW_FILE) that far per delete, deleted lists the deletes with the clock at
# each, http-timeout the CLOUDSDK_CORE_HTTP_TIMEOUT each create and list ran with.
# Outcomes: ok | crash (bench 5's ReadTimeout, no instance) | crash-created (the crash, but the instance
# exists) | alarm-created (rc 142, as the alarm leaves it; the instance exists) | quota (no instance).
# <outcome>@<secs>: first wait (up to 20 s) until $STUB_WAIT_CREATES creates are known
# ($STUB_META/*/CREATE), then move the fake clock <secs> ahead. The creates run in parallel: each call's
# line goes out in one write, so lines never interleave.
line="gcloud$(printf ' %q' "$@")"
printf '%s\n' "${line}" >> "${CALLS:?}"
now() { cat "${NOW_FILE:?}"; }
name="${4:-}"; zone=""; mt=""
for a in "$@"; do
    case "$a" in --zone=*) zone="${a#--zone=}" ;; --machine-type=*) mt="${a#--machine-type=}" ;; esac
done
case "$1 $2 ${3:-}" in
    "auth print-access-token ") echo fake-token ;;
    "compute instances create")
        echo "${name} ${CLOUDSDK_CORE_HTTP_TIMEOUT:-unset}" >> "${STUB}/http-timeout"
        n="$(grep -c "^gcloud compute instances create ${name} " "${CALLS}")"
        out="$(sed -n "${n}p" "${STUB}/create-${name}" 2>/dev/null)"; out="${out:-ok}"
        case "${out}" in
            *@*)
                waited=0
                until [ "$(find "${STUB_META:?}" -name CREATE 2>/dev/null | wc -l)" -ge "${STUB_WAIT_CREATES:-0}" ] || [ "${waited}" -ge 200 ]; do
                    sleep 0.1; waited=$((waited + 1))
                done
                echo "$(( $(now) + ${out#*@} ))" > "${NOW_FILE}"
                out="${out%@*}" ;;
        esac
        case "${out}" in
            ok|crash-created|alarm-created)
                printf '{"name": "%s", "id": "4242", "status": "PROVISIONING", "machineType": "https://www.googleapis.com/compute/v1/projects/p/zones/%s/machineTypes/%s", "tags": {"items": ["bench-blaster"]}, "labels": {"benchmark": "1"}}\n' \
                    "${name}" "${zone}" "${mt}" > "${STUB}/vm-${name}" ;;
        esac
        case "${out}" in
            ok) echo "Created [https://www.googleapis.com/compute/v1/projects/p/zones/${zone}/instances/${name}]." ;;
            crash|crash-created) cat "${STUB_FIX:?}/create-crash.txt" >&2; exit 1 ;;
            alarm-created) exit 142 ;;
            quota) cat "${STUB_FIX}/create-quota.txt" >&2; exit 1 ;;
            *) echo "fake gcloud: unknown outcome '${out}'" >&2; exit 2 ;;
        esac ;;
    "compute instances describe")
        if [ -f "${STUB}/ip-${name}" ]; then
            case "$*" in *networkIP*) cat "${STUB}/ip-${name}"; exit 0 ;; esac
        fi
        if [ ! -f "${STUB}/vm-${name}" ]; then
            printf "ERROR: (gcloud.compute.instances.describe) Could not fetch resource:\n - The resource 'projects/p/zones/%s/instances/%s' was not found\n" "${zone}" "${name}" >&2
            exit 1
        fi
        case "$*" in *"value(id)"*) echo 4242 ;; *) cat "${STUB}/vm-${name}" ;; esac ;;
    "compute instances delete")
        [ ! -f "${STUB}/delete-fail" ] || exit 1
        [ ! -f "${STUB}/delete-secs" ] || echo "$(( $(now) + $(cat "${STUB}/delete-secs") ))" > "${NOW_FILE}"
        shift 3
        for a in "$@"; do
            case "$a" in --*) ;; *) rm -f "${STUB}/vm-${a}"; echo "${a} $(now)" >> "${STUB}/deleted" ;; esac
        done ;;
    "compute instances list")
        echo "list ${CLOUDSDK_CORE_HTTP_TIMEOUT:-unset}" >> "${STUB}/http-timeout"
        [ -f "${STUB}/list.json" ] || exit 1
        cat "${STUB}/list.json" ;;
    "compute disks add-labels") ;;
    "compute ssh "*) ;;
    *) exit 1 ;;
esac
