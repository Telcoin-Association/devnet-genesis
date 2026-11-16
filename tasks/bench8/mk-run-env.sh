#!/usr/bin/env bash
# mk-run-env.sh — bench 8, orchestrator only: the filled launch env of one run, outside benchmark/ (launch.sh
# refuses a placeholder and a dirty harness tree).
#   tasks/bench8/mk-run-env.sh <control|floor16|nohold|reduced> <run-id>
# Copies benchmark/launch/bench8-<form>.env to tasks/bench8/<run-id>/bench8-<form>.env with <run-id>, the image's
# digest and the node commit from tasks/bench8/image-build.meta.json; refuses an existing file, a run id that is
# not rYYYYMMDD-HHMM, and a copy that still holds a "<...>" placeholder. Prints the file's path and its
# non-comment lines.
set -euo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
form="${1:?control|floor16|nohold|reduced}"; run="${2:?run id}"
case "${form}" in control|floor16|nohold|reduced) ;; *) echo "form must be control, floor16, nohold or reduced" >&2; exit 64 ;; esac
case "${run}" in r[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9]) ;; *) echo "run id must be rYYYYMMDD-HHMM" >&2; exit 64 ;; esac
src="${ROOT}/benchmark/launch/bench8-${form}.env"; meta="${ROOT}/tasks/bench8/image-build.meta.json"
[ -f "${src}" ] && [ -f "${meta}" ] || { echo "missing ${src} or ${meta}" >&2; exit 2; }
digest="$(jq -r .digest "${meta}")"; sha="$(jq -r .node_git_sha "${meta}")"
case "${digest}" in sha256:????????????????????????????????????????????????????????????????) ;; *) echo "bad digest in ${meta}" >&2; exit 2 ;; esac
[ "${#sha}" -eq 40 ] || { echo "bad node sha in ${meta}" >&2; exit 2; }
out="${ROOT}/tasks/bench8/${run}/bench8-${form}.env"
[ ! -e "${out}" ] || { echo "${out} exists" >&2; exit 2; }
mkdir -p "$(dirname "${out}")"
sed -e "s|<run-id>|${run}|g" -e "s|sha256:<image-digest>|${digest}|g" -e "s|<image-digest>|${digest#sha256:}|g" -e "s|<node-sha>|${sha}|g" "${src}" > "${out}"
if grep -n '<[a-z-]*>' "${out}" | grep -v '^[0-9]*:#' ; then echo "a placeholder is left in ${out}" >&2; rm -f "${out}"; exit 2; fi
echo "${out}"
grep -v '^#' "${out}" | grep -v '^$'
