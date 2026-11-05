#!/usr/bin/env bash
#
# benchmark-teardown.sh — remove everything the benchmark created, and prove it.
#
# Candidates (each re-proven before anything is deleted):
#   instances   bench INSTANCE_NAMES ∪ every instance labelled benchmark=1 (bench-obs among them)
#   firewall    BENCH_FIREWALL_RULES (only if they target exactly bench-node + say benchmark=1)
#   buckets     every bucket labelled benchmark=1 or named tn-devnet-bench-* (copied into
#               results/<run>/bucket/ first; a non-empty bucket whose copy failed is LEFT)
#   disks       labelled benchmark=1 or named ^bench-, unattached after the instances are gone, and
#               labelled bench-run=<run>; another run's disk or one with no bench-run label is kept
#   IAM         the compute SA's secretAccessor binding on the two bench-txgen-* secrets
#   secrets     bench-txgen-* — KEPT unless --purge
#   contracts   the tn-contracts worktree benchmark/work/tn-contracts + bench/r* branches with
#               no commits of their own
#   tunnels     local `gcloud compute start-iap-tunnel ... 18545` processes, and the two bench-obs
#               forwards (BENCH_OBS_PROM_LOCAL_PORT, BENCH_OBS_GRAFANA_LOCAL_PORT)
#   local       benchmark/genesis/ is moved into results/<run>/genesis/
#
# First a CREDENTIAL CHECK: `gcloud auth print-access-token` must answer within 60 s, or the
# teardown stops before any pull or delete and says to run `gcloud auth login` (a long pull that
# outlives the session cannot finish, and a half-pulled fleet is the worst place to find out).
# BENCH-OBS (BENCH_OBS_INSTANCE in BENCH_OBS_ZONE) holds the run's metrics. When it exists, its two local
# forwards come up first (bench_obs_tunnel_up; in a dry run, their plan lines), so the Prometheus reads
# below go through them; a run without it warns and goes on with no snapshot. An instance listed under
# that name that describe cannot find stops the teardown with nothing pulled or deleted.
# Before the first delete: a Prometheus health table per node (mode, failed batch reports,
# consensus round; informs, never blocks), then the LOG GATE — every fleet node's logs are
# pulled to results/<run>/logs/ from three sources (current container, logs saved on the
# node, the unit's stdout/stderr files). A node is saved when no transfer failed and at least
# one non-empty log of it landed; the pull then leaves a marker naming the instance's id. A node
# not saved stops the teardown with nothing deleted; BENCH_TEARDOWN_SKIP_LOGS=1 names those
# nodes and deletes anyway. A node is not pulled again only when a marker names the id of the
# instance that holds its name NOW and every log that marker lists is still here at its listed
# size; a marker or a log an earlier fleet left under the same name never counts. An instance
# already gone never blocks. A pull that hits an expired gcloud session stops the rest of the pull
# (BENCH_PULL_STOP_FILE, touched by the pull helpers); the teardown then stops with nothing deleted
# and says to run `gcloud auth login`. A marker also has to be fresh (pulled at most 15 min ago: after that
# the node has logged more than it covers, and the node is pulled again).
# BENCH_TEARDOWN_TRUST_MARKERS=1 lifts that age rule only, for a re-run after an interrupted
# teardown: an older marker that is otherwise intact counts, its verdict line ends
# "(BENCH_TEARDOWN_TRUST_MARKERS=1)", the node is not pulled again, and a manifest note lists
# each node accepted that way with its marker's pull time.
# The pull copies each node's whole log as it is now, and a fleet left up after the run keeps
# logging, so it can far exceed the run's own log size: check df before a teardown. Before the pull
# starts, the filesystem under results/<run>/logs/ must have BENCH_TEARDOWN_MIN_FREE_GB (default 20;
# 0 = no check) GB free; otherwise it stops with nothing pulled or deleted.
# Then the service journal + sampler evidence per node, then the CERTIFICATION record: cert-rate.py
# runs over the pulled logs (manifest.certification); a validator under BENCH_CERT_FAIL_PCT in any
# window gets a cert-fail log snapshot saved on the node and pulled, listed in
# manifest.cert_failures[].logs[]. Then bench-obs's Prometheus TSDB snapshot is pulled into
# logs/bench-obs-prometheus-<UTC>.tar.gz (bench_obs_prom_snapshot_pull; warn-only, BENCH_OBS_PULL_PROM=0
# skips it), so the gates below see it and index it; neither requires it.
# Then the COVERAGE GATE: every fleet node's pulled logs must span the run, its earliest line at or before manifest coordinated_start.due and its latest at or
# after timestamps.blast_end (one LOGCOV line per node from bench_log_coverage_check, recorded as
# manifest.log_coverage[]). A node whose logs start late or end early stops the teardown with nothing
# deleted, and so does a live node with no recorded span when the run's start and end are known;
# otherwise ok=- (a run without a coordinated start or blast end, a node already gone, or
# BENCH_TEARDOWN_SKIP_LOGS=1) is a note, not a failure. BENCH_TEARDOWN_SKIP_COVERAGE=1 deletes anyway
# and notes it in the manifest.
# Then the LOCAL GATE: results/<run>/ is the
# only copy of the run (no bucket keeps another), so before the first delete it must hold, for every
# node in INSTANCE_NAMES, a non-empty logs/<node>-telcoin.log.gz, logs/<node>-unit-stdout.log.gz and
# logs/<node>-recovery-*.tgz, a manifest.json that parses, and every log manifest.cert_failures[]
# names. It then writes INDEX.md and CHECKSUMS.sha256 there and records manifest.archive (kind
# local, path, verified_at, files, bytes). A missing file stops the teardown with nothing deleted,
# naming every one; BENCH_TEARDOWN_SKIP_LOCAL_GATE=1 deletes anyway and notes it in the manifest
# (archive.skipped_gate). The harness never deletes a node log.
# Deletes: each instance (bench-obs too, after the local gate and every Prometheus read; its boot and data
# disks auto-delete with it, else the orphan-disk step deletes them by their bench-run label) is deleted
# in the background right after its id is re-checked, then one loop
# describes every instance still deleting every 10 s until each is gone or
# BENCH_TEARDOWN_DELETE_WAIT_SECS (default 600) have passed; one still there is reported, listed in
# manifest teardown_pending[] and counted by the left-nothing checks. manifest timestamps.teardown_start
# is the first teardown's (written once, just before the first delete); a later teardown of the same
# run appends {start, done} to teardown_reruns[]; timestamps.teardown_done is written once, by the
# first teardown whose deletes all finished.
# After the deletes, report/provenance.py checks the node build the saved logs show against the
# manifest's node_git_sha and records it as manifest node_startup_check (informs, never blocks);
# then tools/cert-rate.py and tools/block-rate.py write analysis/ (BENCH_TEARDOWN_SKIP_ANALYSIS=1
# skips them), and INDEX.md + CHECKSUMS.sha256 are written again over the final tree (never blocks).
# The last line of a teardown that reaches its end is
#   TEARDOWN_DONE run=<id> deleted=<instances confirmed gone> left=<items the left-nothing checks
#   still see> at=<UTC ISO>
# with " dry_run=1" appended in a dry run.
#
# Instance rule: labels.benchmark == "1" AND (name ∈ bench INSTANCE_NAMES OR name ~
# ^bench-(blaster|funder) OR name == BENCH_OBS_INSTANCE, in BENCH_OBS_ZONE) AND name ∉ the devnet
# denylist (INSTANCE_NAMES of a clean ../config.sh + obs-devnet txgen-devnet devnet-indexer; obs-devnet
# is devnet's, never the bench's). ANY violation aborts the whole teardown before a single delete.
#
# Run rule: results/<run>/ must exist (the teardown never creates it) and every candidate
# instance must carry labels.bench-run == <run>; otherwise it stops before anything is pulled,
# deleted or created. Without --run, <run> is the bench-run label the bench instances share;
# no bench instance, or labels that are missing or disagree, stops it and asks for --run.
#
# Usage: benchmark/benchmark-teardown.sh [--yes] [--run ID] [--purge]
#        benchmark/benchmark-teardown.sh --run ID --reindex
# Without --yes it lists the candidates + denylist, prints the delete argv and changes nothing.
# --reindex is local only, for files written into results/<run>/ after the teardown (analysis/
# summaries, per-arm tables): it rewrites INDEX.md and CHECKSUMS.sha256 over the tree as it is now
# (and, when the manifest has a local archive record, its files/bytes totals and
# archive.reindexed_at), prints the file count and bytes, and exits. No gcloud call, no gate, no
# delete; it needs --run and takes no other option.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

CONFIRM=0; PURGE=0; REINDEX=0; RUN_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --purge) PURGE=1 ;;
        --reindex) REINDEX=1 ;;
        --run) BENCH_RUN_ID="${2:?--run needs an id}"; RUN_ARG="${BENCH_RUN_ID}"; shift ;;
        --run=*) BENCH_RUN_ID="${1#*=}"; RUN_ARG="${BENCH_RUN_ID}" ;;
        -h|--help) sed -n '2,/^$/p' "$0"; exit 0 ;;
        *) echo "❌ unknown argument '$1' (supported: --yes, --run ID, --purge, --reindex)" >&2; exit 1 ;;
    esac
    shift
done
SKIP_LOGS="${BENCH_TEARDOWN_SKIP_LOGS:-0}"
case "${SKIP_LOGS}" in 0|1) ;; *) echo "❌ BENCH_TEARDOWN_SKIP_LOGS must be 0 or 1 (got '${SKIP_LOGS}')" >&2; exit 1 ;; esac
SKIP_GATE="${BENCH_TEARDOWN_SKIP_LOCAL_GATE:-0}"
case "${SKIP_GATE}" in 0|1) ;; *) echo "❌ BENCH_TEARDOWN_SKIP_LOCAL_GATE must be 0 or 1 (got '${SKIP_GATE}')" >&2; exit 1 ;; esac
# Read by bench-lib.sh's _bench_marker_verdict; only "1" changes anything there.
TRUST_MARKERS="${BENCH_TEARDOWN_TRUST_MARKERS:-0}"
case "${TRUST_MARKERS}" in 0|1) ;; *) echo "❌ BENCH_TEARDOWN_TRUST_MARKERS must be 0 or 1 (got '${TRUST_MARKERS}')" >&2; exit 1 ;; esac
# A whole number of GB, no leading zero (bash reads 08 as octal), at most 6 digits; 0 = no check.
MIN_FREE_GB="${BENCH_TEARDOWN_MIN_FREE_GB:-20}"
case "${MIN_FREE_GB}" in
    0|[1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) echo "❌ BENCH_TEARDOWN_MIN_FREE_GB must be a whole number of GB, 0 to 999999 (got '${MIN_FREE_GB}')" >&2; exit 1 ;;
esac
# Read by bench-lib.sh's bench_local_analysis; only "1" changes anything there.
SKIP_ANALYSIS="${BENCH_TEARDOWN_SKIP_ANALYSIS:-0}"
case "${SKIP_ANALYSIS}" in 0|1) ;; *) echo "❌ BENCH_TEARDOWN_SKIP_ANALYSIS must be 0 or 1 (got '${SKIP_ANALYSIS}')" >&2; exit 1 ;; esac
SKIP_COVERAGE="${BENCH_TEARDOWN_SKIP_COVERAGE:-0}"
case "${SKIP_COVERAGE}" in 0|1) ;; *) echo "❌ BENCH_TEARDOWN_SKIP_COVERAGE must be 0 or 1 (got '${SKIP_COVERAGE}')" >&2; exit 1 ;; esac
# Whole seconds, no leading zero, at most 6 digits; 0 = one describe pass, no wait.
DELETE_WAIT_SECS="${BENCH_TEARDOWN_DELETE_WAIT_SECS:-600}"
case "${DELETE_WAIT_SECS}" in
    0|[1-9]|[1-9][0-9]|[1-9][0-9][0-9]|[1-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9]|[1-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) echo "❌ BENCH_TEARDOWN_DELETE_WAIT_SECS must be a whole number of seconds, 0 to 999999 (got '${DELETE_WAIT_SECS}')" >&2; exit 1 ;;
esac
DELETE_POLL_SECS=10
results_ids() { (cd "${DIR}/results" 2>/dev/null && ls -1d r* 2>/dev/null | paste -sd ' ' -) || true; }

# --reindex: INDEX.md + CHECKSUMS.sha256 over results/<run>/ as it is now, then exit. Local only:
# bench-lib.sh is sourced for bench_local_index (sourcing calls no gcloud); nothing below runs.
if [ "${REINDEX}" -eq 1 ]; then
    if [ -z "${RUN_ARG}" ]; then
        echo "❌ --reindex needs --run <id> — nothing was done (results/ holds: $(results_ids))" >&2
        exit 1
    fi
    if [ "${CONFIRM}" -eq 1 ] || [ "${PURGE}" -eq 1 ]; then
        echo "❌ --reindex runs on its own (no --yes or --purge) — nothing was done" >&2
        exit 1
    fi
    export BENCH_RUN_ID
    BENCH_APPLY=1
    # shellcheck source=bench-lib.sh
    source "${DIR}/bench-lib.sh"
    if [ ! -d "${BENCH_RESULTS_DIR}" ]; then
        echo "❌ ${BENCH_RESULTS_DIR} does not exist — nothing was done (results/ holds: $(results_ids))" >&2
        exit 1
    fi
    echo ">>> reindex: ${BENCH_RESULTS_DIR} (local only: no gcloud call, no gate, nothing deleted)"
    if jq -e '.archive.kind == "local"' "$(bench_manifest)" >/dev/null 2>&1; then
        bench_local_index --arg t "$(bench_now_iso)" '.archive.reindexed_at = $t'
    else
        bench_local_index
    fi
    exit 0
fi
# fleet_runs — "<name> <bench-run label, or (none)>" per bench instance that exists (labelled
# benchmark=1 or named in INSTANCE_NAMES, as the candidate list below). Call it with a
# placeholder BENCH_RUN_ID: its subshell sources the profile only to list them; nothing is written.
fleet_runs() (
    # shellcheck source=bench-lib.sh disable=SC1091  # the same file as the source below
    source "${DIR}/bench-lib.sh" >&2 || exit 1
    gcloud compute instances list --project="${PROJECT_ID}" --format=json \
        | jq -r --argjson names "$(printf '%s\n' "${INSTANCE_NAMES[@]}" | jq -R . | jq -s .)" \
            '.[] | select((.labels.benchmark // "") == "1" or ((.name) as $n | $names | index($n)))
             | .name + " " + ((.labels["bench-run"] // "") | if . == "" then "(none)" else . end)'
)
if [ -z "${BENCH_RUN_ID:-}" ]; then
    # No --run: the run is the one the live fleet is labelled with, never the last name under
    # results/ (rteardown sorts after every r2026… id; an earlier run's markers would pass).
    _rows="$(BENCH_RUN_ID=rprobe BENCH_APPLY=0 fleet_runs)" || { echo "❌ no --run given and the instances could not be listed — name the run: --run <id>" >&2; exit 1; }
    _runs="$(printf '%s\n' "${_rows}" | awk 'NF == 2 {print $2}' | LC_ALL=C sort -u)"
    if [ -z "${_rows}" ]; then
        echo "❌ no --run given and no bench instance exists to take the run from — nothing was done." >&2
        echo "   Name the run: benchmark/benchmark-teardown.sh --run <id>   (results/ holds: $(results_ids))" >&2
        exit 1
    fi
    if [ "$(printf '%s\n' "${_runs}" | grep -c .)" -ne 1 ] || [ "${_runs}" = "(none)" ]; then
        echo "❌ no --run given and the bench instances do not share one bench-run label — nothing was done:" >&2
        printf '%s\n' "${_rows}" | awk '{ print "   - " $1 ": " ($2 == "(none)" ? "no bench-run label" : "bench-run=" $2) }' >&2
        echo "   Name the run: benchmark/benchmark-teardown.sh --run <id>   (results/ holds: $(results_ids))" >&2
        exit 1
    fi
    BENCH_RUN_ID="${_runs}"
    echo "no --run given: run ${BENCH_RUN_ID}, the bench-run label of all $(printf '%s\n' "${_rows}" | grep -c .) bench instance(s)"
fi
export BENCH_RUN_ID
BENCH_APPLY="${CONFIRM}"
# shellcheck source=bench-lib.sh
source "${DIR}/bench-lib.sh"

echo "=========================================="
echo "benchmark teardown — project ${PROJECT_ID}, run ${BENCH_RUN_ID}$([ "${PURGE}" -eq 1 ] && echo ' (--purge)')"
[ "${CONFIRM}" -eq 1 ] && echo "Mode: APPLY (--yes)" || echo "Mode: DRY RUN — nothing will be changed"
echo "=========================================="

# The run's results directory holds its logs, markers and manifest. It is never created here: a
# mistyped or foreign run id must not get a fresh one, filled with this fleet's logs and markers.
if [ ! -d "${BENCH_RESULTS_DIR}" ]; then
    echo "❌ ${BENCH_RESULTS_DIR} does not exist — NOTHING was pulled, deleted or created." >&2
    echo "   Check the run id (results/ holds: $(results_ids)). The teardown saves the node logs into" >&2
    echo "   the run's results directory and never creates it; if ${BENCH_RUN_ID} really is the run, create it first." >&2
    exit 1
fi

# --- gcloud credentials, before any pull or delete -----------------------------------------
# The pull takes long enough for a gcloud session to expire under it (bench 3: "Reauthentication
# failed" mid-pull, a re-run that died at its first call). A token that cannot be printed within
# 60 s now means every later call fails the same way: stop before the first pull.
login_hint() {
    echo "   Run: gcloud auth login   then re-run: benchmark/benchmark-teardown.sh$([ "${CONFIRM}" -eq 1 ] && echo ' --yes') --run ${BENCH_RUN_ID}" >&2
    echo "   Logs already in ${BENCH_RESULTS_DIR}/logs are kept; a node whose marker vouches for them is not pulled again." >&2
}
echo ">>> gcloud credentials: gcloud auth print-access-token (60 s)"
if ! perl -e 'alarm shift; exec @ARGV' 60 gcloud auth print-access-token </dev/null >/dev/null; then
    echo "" >&2
    echo "❌ gcloud has no usable credentials (gcloud auth print-access-token failed or took over 60 s) — NOTHING was pulled or deleted." >&2
    login_hint
    exit 1
fi
echo "    ✓ gcloud prints an access token"
# The pull helpers touch BENCH_PULL_STOP_FILE when gcloud needs re-authentication mid-pull, and
# attempt no further node; the teardown reads it after the pull and after the certification snapshots.
TD_TMP="$(mktemp -d "${TMPDIR:-/tmp}/tn-bench-teardown.XXXXXX")"
trap 'rm -rf "${TD_TMP}"' EXIT
export BENCH_PULL_STOP_FILE="${TD_TMP}/pull-stop"
# stop_if_reauth <what ran> — exit 1, nothing deleted, when the pull helpers asked to stop.
stop_if_reauth() {
    [ -e "${BENCH_PULL_STOP_FILE}" ] || return 0
    echo "" >&2
    echo "❌ gcloud needs re-authentication (the session expired during $1) — NOTHING was deleted." >&2
    login_hint
    exit 1
}

VIOLATIONS=()
violate() { VIOLATIONS+=("$*"); echo "    ✗ VIOLATION: $*" >&2; }

# --- denylist -------------------------------------------------------------------------
DENY=()
while IFS= read -r n; do [ -n "${n}" ] && DENY+=("${n}"); done < <(bench_devnet_denylist)
[ "${#DENY[@]}" -ge 3 ] || bench_die "devnet denylist came back short (${DENY[*]:-}) — refusing to tear down blind"
echo ">>> devnet denylist (never deleted): ${DENY[*]}"

# --- instances --------------------------------------------------------------------------
ALL_INST="$(gcloud compute instances list --project="${PROJECT_ID}" --format=json)"
CAND_INST=()   # "zone name"
while IFS= read -r row; do
    [ -n "${row}" ] || continue
    name="${row#* }"; zone="${row%% *}"
    labelled="$(printf '%s' "${ALL_INST}" | jq -r --arg n "${name}" '.[] | select(.name == $n) | .labels.benchmark // ""')"
    ok_name=0
    bench_in_list "${name}" "${INSTANCE_NAMES[@]}" && ok_name=1
    case "${name}" in bench-blaster-*|bench-funder*|"${BENCH_OBS_INSTANCE}") ok_name=1 ;; esac
    if [ "${labelled}" != "1" ]; then violate "instance ${name} lacks labels.benchmark=1"; continue; fi
    if [ "${ok_name}" -ne 1 ]; then violate "instance ${name} is labelled benchmark=1 but is not a bench node/blaster/funder/obs name"; continue; fi
    # Every bench-obs call (forwards, snapshot) names BENCH_OBS_ZONE: one elsewhere is not the run's.
    if [ "${name}" = "${BENCH_OBS_INSTANCE}" ] && [ "${zone}" != "${BENCH_OBS_ZONE}" ]; then
        violate "instance ${name} is in ${zone}, not BENCH_OBS_ZONE=${BENCH_OBS_ZONE}"; continue
    fi
    if bench_in_list "${name}" "${DENY[@]}"; then violate "instance ${name} is on the devnet denylist"; continue; fi
    if bench_is_protected "${name}"; then violate "instance ${name} matches ${BENCH_PROTECTED_RE}"; continue; fi
    CAND_INST+=("${zone} ${name}")
done < <(printf '%s' "${ALL_INST}" | jq -r --argjson names "$(printf '%s\n' "${INSTANCE_NAMES[@]}" | jq -R . | jq -s .)" \
    '.[] | select((.labels.benchmark // "") == "1" or ((.name) as $n | $names | index($n))) | (.zone|split("/")|last) + " " + .name')
echo ">>> instance candidates (${#CAND_INST[@]}):"
for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do echo "    - ${c#* } (${c%% *})"; done
overlap=""
for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do bench_in_list "${c#* }" "${DENY[@]}" && overlap="${overlap} ${c#* }"; done
[ -z "${overlap}" ] && echo "    ✓ no devnet instance is a candidate" || violate "devnet instance(s) among candidates:${overlap}"

# --- run rule: every candidate carries bench-run=<this run> --------------------------------------
# Instance names repeat in every fleet; the label is what ties a VM to this run's results dir and
# markers. A mismatch or a missing label stops here, before anything is pulled or deleted.
RUN_BAD=(); RUN_SEEN=""
for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do
    lbl="$(printf '%s' "${ALL_INST}" | jq -r --arg n "${c#* }" --arg z "${c%% *}" \
        '[.[] | select(.name == $n and (.zone|split("/")|last) == $z) | .labels["bench-run"] // ""] | first // ""')"
    [ "${lbl}" != "${BENCH_RUN_ID}" ] || continue
    if [ -z "${lbl}" ]; then RUN_BAD+=("${c#* }: no bench-run label"); continue; fi
    RUN_BAD+=("${c#* }: bench-run=${lbl}"); RUN_SEEN="${RUN_SEEN}${lbl}"$'\n'
done
if [ "${#RUN_BAD[@]}" -gt 0 ]; then
    echo "" >&2
    echo "❌ ${#RUN_BAD[@]} instance(s) are not labelled bench-run=${BENCH_RUN_ID} (this teardown's run) — NOTHING was pulled or deleted:" >&2
    for v in "${RUN_BAD[@]}"; do echo "   - ${v}" >&2; done
    for v in $(printf '%s' "${RUN_SEEN}" | LC_ALL=C sort -u); do
        echo "   Those labelled ${v} are run ${v}'s fleet: benchmark/benchmark-teardown.sh --run ${v} (add --yes to apply)." >&2
    done
    if printf '%s\n' "${RUN_BAD[@]}" | grep -q ': no bench-run label$'; then
        echo "   An instance with no bench-run label belongs to no run: find out what it is and save its logs by hand" >&2
        echo "   before deleting it, or label it (gcloud compute instances add-labels <name> --labels=bench-run=<run>)." >&2
    fi
    exit 1
fi
echo "    ✓ every candidate instance is labelled bench-run=${BENCH_RUN_ID}"

# --- firewall rules ------------------------------------------------------------------------
CAND_FW=()
for r in "${BENCH_FIREWALL_RULES[@]}"; do
    j="$(gcloud compute firewall-rules describe "${r}" --project="${PROJECT_ID}" --format=json 2>/dev/null || true)"
    [ -n "${j}" ] || continue
    bench_is_protected "${r}" && { violate "rule ${r} matches ${BENCH_PROTECTED_RE}"; continue; }
    if ! printf '%s' "${j}" | jq -e '(.targetTags // []) == ["bench-node"] and ((.description // "") | contains("benchmark=1"))' >/dev/null; then
        violate "rule ${r} does not target exactly bench-node with benchmark=1 in its description"; continue
    fi
    CAND_FW+=("${r}")
done
echo ">>> firewall candidates (${#CAND_FW[@]}): ${CAND_FW[*]:-none}"
foreign="$(gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json | jq -r \
    --argjson ours "$(printf '%s\n' "${BENCH_FIREWALL_RULES[@]}" | jq -R . | jq -s .)" \
    '.[] | select((.targetTags // []) | index("bench-node")) | select(.name as $n | $ours | index($n) | not) | .name')"
[ -z "${foreign}" ] || bench_warn "non-bench rules target bench-node (left alone): ${foreign}"

# --- buckets ---------------------------------------------------------------------------------
CAND_BKT=()
while IFS= read -r b; do
    [ -n "${b}" ] || continue
    case "${b}" in tn-devnet-bench-*) CAND_BKT+=("${b}") ;; *) violate "bucket ${b} is labelled benchmark=1 but not named tn-devnet-bench-*" ;; esac
done < <(bench_bucket_names)   # label benchmark=1 OR name tn-devnet-bench-* (step 12 labels in a 2nd call)
echo ">>> bucket candidates (${#CAND_BKT[@]}): ${CAND_BKT[*]:-none}"

# --- disks (listed now for the plan; re-listed after the instances are gone) ----------------
list_disks() {
    gcloud compute disks list --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -r '.[] | select(((.labels.benchmark // "") == "1") or (.name | test("^bench-")))
            | (.zone|split("/")|last) + " " + .name + " " + ((.labels["bench-run"] // "") | if . == "" then "-" else . end)
              + " " + (((.users // []) | map(split("/")|last)) | join(","))'
}
# disk_fate <bench-run label or -> — what the orphan-disk step does with an unattached disk. Only
# this run's disks go: a disk kept on purpose (instances delete --keep-disks) may hold another
# run's only copy of a node's logs.
disk_fate() {
    if [ "$1" = "${BENCH_RUN_ID}" ]; then echo "deleted once unattached"
    elif [ "$1" = "-" ]; then echo "kept: no bench-run label"
    else echo "kept: belongs to another run (bench-run=$1)"; fi
}
CAND_DISK=()
while IFS= read -r row; do
    [ -n "${row}" ] || continue
    read -r dz dn dl du <<< "${row}"
    case "${dn}" in bench-*) ;; *) violate "disk ${dn} labelled benchmark=1 but not named bench-*"; continue ;; esac
    bench_in_list "${dn}" "${DENY[@]}" && { violate "disk ${dn} is on the denylist"; continue; }
    if [ -n "${du:-}" ]; then
        for u in ${du//,/ }; do
            found=0; for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do [ "${c#* }" = "${u}" ] && found=1; done
            [ "${found}" -eq 1 ] || violate "disk ${dn} is attached to non-candidate instance ${u}"
        done
    fi
    CAND_DISK+=("${dz} ${dn} ${dl}")
done < <(list_disks)
echo ">>> disk candidates (${#CAND_DISK[@]}; boot disks auto-delete with their instance):"
for c in "${CAND_DISK[@]+"${CAND_DISK[@]}"}"; do read -r dz dn dl <<< "${c}"; echo "    - ${dn} (${dz}): $(disk_fate "${dl}")"; done

# --- local / git / IAM ------------------------------------------------------------------------
# Both tunnel transports (bench_tunnel_up): the ssh-forward supervisor (its $0, which restarts the
# session when it drops, so it must die first), its gcloud/ssh child (the expanded -L spec), and the
# old websocket tunnel. Then the gcloud/ssh children of the two bench-obs forwards (bench_obs_tunnel_up,
# under the same supervisor), by their local ports.
TUNNEL_PAT="tn-bench-tunnel-supervisor|localhost:${BENCH_TUNNEL_PORT}:127\.0\.0\.1:8545|start-iap-tunnel.*${BENCH_TUNNEL_PORT}"
TUNNEL_PAT="${TUNNEL_PAT}|localhost:${BENCH_OBS_PROM_LOCAL_PORT}:|localhost:${BENCH_OBS_GRAFANA_LOCAL_PORT}:"
TUNNEL_PIDS="$(pgrep -f "${TUNNEL_PAT}" 2>/dev/null | tr '\n' ' ' || true)"
echo ">>> IAP tunnel pids: ${TUNNEL_PIDS:-none}"
WT_PRESENT=0; [ -e "${BENCH_CONTRACTS_WORKTREE}" ] && WT_PRESENT=1
BENCH_BRANCHES=()
if [ -d "${BENCH_CONTRACTS_SRC_DIR}" ]; then
    while IFS= read -r br; do
        [ -n "${br}" ] || continue
        if git -C "${BENCH_CONTRACTS_SRC_DIR}" merge-base --is-ancestor "${br}" "${BENCH_CONTRACTS_BASE_BRANCH}" 2>/dev/null; then
            BENCH_BRANCHES+=("${br}")
        else
            bench_warn "branch ${br} has commits not on ${BENCH_CONTRACTS_BASE_BRANCH} — left alone"
        fi
    done < <(git -C "${BENCH_CONTRACTS_SRC_DIR}" for-each-ref --format='%(refname:short)' 'refs/heads/bench/r*' 2>/dev/null)
fi
echo ">>> contracts worktree: $([ "${WT_PRESENT}" -eq 1 ] && echo "${BENCH_CONTRACTS_WORKTREE}" || echo absent); branches: ${BENCH_BRANCHES[*]:-none}"
SECRETS=("${BENCH_TXGEN_MASTER_SECRET}" "${BENCH_TXGEN_SEED_SECRET}")
echo ">>> secrets: ${SECRETS[*]} — $([ "${PURGE}" -eq 1 ] && echo 'DELETE (--purge)' || echo 'kept; accessor binding for the compute SA removed')"
echo ">>> local: $([ -d "${BENCH_DIR}/genesis" ] && echo "move ${BENCH_DIR}/genesis -> ${BENCH_RESULTS_DIR}/genesis" || echo 'no benchmark/genesis to move')"

if [ "${#VIOLATIONS[@]}" -gt 0 ]; then
    echo "" >&2
    echo "❌ ${#VIOLATIONS[@]} guard violation(s) — NOTHING was deleted:" >&2
    for v in "${VIOLATIONS[@]}"; do echo "   - ${v}" >&2; done
    exit 1
fi

# ================================ bench-obs (read before any delete) ======================
# bench-obs holds the run's metrics. The health table and the Prometheus snapshot below read it
# through the two local forwards brought up here (a dry run prints their plan lines); it is deleted
# with the fleet, after the local gate. OBS_CAND is its candidate row ("<zone> <name>") when listed;
# OBS_UP=1 once bench_obs_exists answers for it too (it then gets a GATE_IDS row after the load-VM gate).
# bench_obs_exists: rc 0 found, 1 not found, 2 the describe itself failed (its stderr is shown).
OBS_CAND=""; OBS_UP=0; obs_rc=0
for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do [ "${c#* }" != "${BENCH_OBS_INSTANCE}" ] || OBS_CAND="${c}"; done
echo ""
echo ">>> bench-obs: ${BENCH_OBS_INSTANCE} (${BENCH_OBS_ZONE}), the run's Prometheus, read before any delete"
bench_obs_exists || obs_rc=$?
if [ "${obs_rc}" -eq 0 ]; then
    if [ -n "${OBS_CAND}" ]; then
        OBS_UP=1
        { bench_obs_urls && bench_obs_tunnel_up; } \
            || bench_warn "bench-obs forwards not up — the health table and the Prometheus snapshot may find nothing; teardown continues"
    else
        bench_warn "${BENCH_OBS_INSTANCE} exists but is not labelled benchmark=1 — not this run's: no Prometheus snapshot, not deleted"
    fi
elif [ -n "${OBS_CAND}" ]; then
    # Listed above, yet describe does not answer for it: no snapshot, and no row its delete could be
    # re-checked against. Stop before the first pull rather than in the middle of the deletes.
    if [ "${BENCH_APPLY}" = "1" ]; then
        echo "" >&2
        echo "❌ ${BENCH_OBS_INSTANCE} is listed in ${BENCH_OBS_ZONE} but gcloud compute instances describe does not answer for it — NOTHING was pulled or deleted." >&2
        echo "   Re-run the teardown (a transient gcloud failure clears), or look at the instance by hand." >&2
        exit 1
    fi
    echo "    ✗ listed, but describe does not answer for it: with --yes the teardown stops here, before any pull or delete"
elif [ "${obs_rc}" -eq 1 ]; then
    bench_warn "bench-obs absent — no Prometheus snapshot"
else
    bench_warn "bench-obs describe failed (transient?) — no snapshot; if ${BENCH_OBS_INSTANCE} exists, re-run the teardown"
fi

# ================================ node health + logs (before any delete) ==================
# A node's container log dies with its VM, so the health table and the log gate come first.
# prom_get <json|""> <node> <absent> — the node's value; "?" when the query failed ("").
prom_get() { if [ -z "$1" ]; then printf '?'; else printf '%s' "$1" | jq -r --arg n "$2" --arg d "$3" '.[$n] // $d'; fi; }
# health_table — one row per fleet node; ⚠ = validator not cvv_active or > 20 failed reports.
health_table() {
    local l="${BENCH_PROM_NETWORK_LABEL}" q_mode q_fail modes fails rounds i inst mode nf rnd flag nflag=0
    q_mode="tn_node_mode{network=\"${l}\"} == 1"
    q_fail="sum by (node) (increase(tn_batch_builder_seal_failures_total{network=\"${l}\",reason=\"failed_to_report\"}[30m]))"
    echo ""
    echo ">>> node health (Prometheus network=\"${l}\"; informs, never blocks)"
    if [ "${BENCH_APPLY}" != "1" ]; then
        printf '    query: %s\n' "${q_mode}" "${q_fail}" \
            "bench_prom_rounds max = max by (node) (tn_epoch_current{network=\"${l}\"}) * 100000000 + max by (node) (tn_primary_round{network=\"${l}\"})"
        echo "      (dry run — not queried)"
        return 0
    fi
    modes="$(bench_prom_query "${q_mode}" 2>/dev/null \
        | jq -c 'select(.status == "success") | [.data.result[] | {key: .metric.node, value: (.metric.mode // "?")}] | from_entries' 2>/dev/null || true)"
    fails="$(bench_prom_query "${q_fail}" 2>/dev/null \
        | jq -c 'select(.status == "success") | [.data.result[] | {key: .metric.node, value: (.value[1] | tonumber | round)}] | from_entries' 2>/dev/null || true)"
    rounds="$(bench_prom_rounds max)"
    [ -z "${rounds}" ] || rounds="$(printf '%s' "${rounds}" | jq -c 'map_values((. / 100000000 | floor) as $e | "\($e)/\(. - $e * 100000000)")')"
    if [ -z "${modes}${fails}${rounds}" ]; then
        echo "    ⚠ Prometheus not reachable via $([ "${BENCH_PROM_AUTH:-0}" = 0 ] && echo "${BENCH_PROM_URL}" || echo "${BENCH_GRAFANA_URL}") — no health table; teardown continues"
        return 0
    fi
    printf '    %-20s %-9s %-14s %10s  %-12s\n' node role mode failed_rpt epoch/round
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        mode="$(prom_get "${modes}" "${inst}" none)"; nf="$(prom_get "${fails}" "${inst}" 0)"; rnd="$(prom_get "${rounds}" "${inst}" none)"
        flag=""
        if [ "${NODE_ROLES[$i]}" = "validator" ] && [ "${mode}" != "?" ] && [ "${mode}" != "cvv_active" ]; then flag="⚠ not cvv_active"; fi
        case "${nf}" in ''|*[!0-9]*) ;; *) if [ "${nf}" -gt 20 ]; then flag="${flag:+${flag}; }⚠ ${nf} failed reports"; fi ;; esac
        [ -z "${flag}" ] || nflag=$((nflag + 1))
        printf '    %-20s %-9s %-14s %10s  %-12s %s\n' "${inst}" "${NODE_ROLES[$i]}" "${mode}" "${nf}" "${rnd}" "${flag}"
    done
    if [ "${nflag}" -gt 0 ]; then echo "    ⚠ ${nflag} node(s) flagged — read their logs (pulled next) before the next deploy"; fi
    return 0
}
health_table || bench_warn "health table failed — teardown continues"

# Load-VM gate. A blaster or the funder holds its results until it has uploaded them to the run's
# bucket, which is copied into results/<run>/bucket/ before it is removed (below). So a load VM may
# go only when every file it owes is in the bucket or already in results/<run>/. What it owes comes
# from the manifest: a blaster's .blasters[] entry (same instance id) names its .result under
# .blast.bucket_prefix; the funder's .fund (same BENCH_RUN_INDEX as the VM's metadata) names its
# prefix and it owes prepare.json. Each also owes <name>.docker.log (blaster-startup.sh uploads
# both). One read-only listing of the prefix per VM, in a dry run too.
# load_vm_verdict <zone> <name> — one line, "saved — ..." or "NOT shown saved — <why>"; rc 0 = saved.
load_vm_verdict() {
    local z="$1" n="$2" mf id rec sub pfx idx f listing lrc=0 miss="" here="" inb=""
    mf="$(bench_manifest)"
    [ -f "${mf}" ] || { echo "NOT shown saved — no manifest at ${mf}"; return 1; }
    id="$(inst_id "${z}" "${n}")"
    case "${id}" in ''|*[!0-9]*) echo "NOT shown saved — its instance id is unknown"; return 1 ;; esac
    case "${n}" in
        bench-blaster-*)
            sub=blasters
            rec="$(jq -r --arg n "${n}" '[(.blasters // [])[] | select(.name == $n)]
                | if length == 1 then "\(.[0].instance_id // "" | tostring) \(.[0].result // "")" else "" end' "${mf}" 2>/dev/null)" || rec=""
            [ -n "${rec}" ] || { echo "NOT shown saved — the manifest has no single .blasters entry for it"; return 1; }
            if [ "${rec%% *}" != "${id}" ]; then
                echo "NOT shown saved — the manifest's entry is for instance ${rec%% *}; ${n} now is instance ${id}"; return 1
            fi
            f="${rec#* }"
            case "${f}" in blasters/*.json) f="${f#blasters/}" ;; *) echo "NOT shown saved — unexpected .result '${f}'"; return 1 ;; esac
            pfx="$(jq -r '.blast.bucket_prefix // empty' "${mf}" 2>/dev/null)" || pfx=""
            ;;
        bench-funder*)
            sub=funder; f=prepare.json
            idx="$(printf '%s' "${ALL_INST}" | jq -r --arg n "${n}" --arg z "${z}" \
                '[.[] | select(.name == $n and (.zone|split("/")|last) == $z) | .metadata.items[]? | select(.key == "RUN_INDEX") | .value] | first // ""')"
            rec="$(jq -r '"\(.fund.run_index // "" | tostring) \(.fund.bucket_prefix // "")"' "${mf}" 2>/dev/null)" || rec=""
            if [ -z "${idx}" ] || [ "${rec%% *}" != "${idx}" ]; then
                echo "NOT shown saved — the VM ran BENCH_RUN_INDEX ${idx:-?}, the manifest's .fund is for '${rec%% *}'"; return 1
            fi
            pfx="${rec#* }"
            ;;
        *) echo "NOT shown saved — not a load VM"; return 1 ;;
    esac
    case "${pfx}" in gs://?*) ;; *) echo "NOT shown saved — the manifest records no bucket prefix for its results"; return 1 ;; esac
    listing="$(gcloud storage ls "${pfx}/" --project="${PROJECT_ID}" 2>/dev/null)" || lrc=$?
    for f in "${f}" "${n}.docker.log"; do
        if [ -s "${BENCH_RESULTS_DIR}/${sub}/${f}" ]; then here="${here} ${f}"
        elif [ "${lrc}" -eq 0 ] && _bench_in_lines "${pfx}/${f}" "${listing}"; then inb="${inb} ${f}"
        else miss="${miss} ${f}"; fi
    done
    if [ -n "${miss}" ]; then
        echo "NOT shown saved — in neither ${pfx}/ $([ "${lrc}" -eq 0 ] || echo "(listing failed or empty) ")nor results/${BENCH_RUN_ID}/${sub}/:${miss}"
        return 1
    fi
    echo "saved —${here:+ in results/${BENCH_RUN_ID}/${sub}/:${here};}${inb:+ in ${pfx}/:${inb}}"
}
# inst_id <zone> <name> — the numeric id ALL_INST holds for that instance ("" unless exactly one).
inst_id() {
    printf '%s' "${ALL_INST}" | jq -r --arg n "$2" --arg z "$1" \
        '[.[] | select(.name == $n and (.zone|split("/")|last) == $z) | (.id // "" | tostring)] | if length == 1 then .[0] else "" end'
}
LOAD_BAD=(); LOAD_N=0
GATE_IDS=""   # "<zone> <name> <id>" per instance the gates let through; re-checked just before its delete
for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do
    case "${c#* }" in bench-blaster-*|bench-funder*) ;; *) continue ;; esac
    LOAD_N=$((LOAD_N + 1))
    [ "${LOAD_N}" -gt 1 ] || { echo ""; echo ">>> load VMs: results in the bucket or in results/${BENCH_RUN_ID}/ before any delete"; }
    st="$(printf '%s' "${ALL_INST}" | jq -r --arg n "${c#* }" --arg z "${c%% *}" \
        '[.[] | select(.name == $n and (.zone|split("/")|last) == $z) | .status] | first // "?"')"
    if v="$(load_vm_verdict "${c%% *}" "${c#* }")"; then echo "    ✓ ${c#* } (${st}): ${v}"
    else echo "    ✗ ${c#* } (${st}): ${v}"; LOAD_BAD+=("${c#* }"); fi
    GATE_IDS="${GATE_IDS}${c} $(inst_id "${c%% *}" "${c#* }")"$'\n'
done
if [ "${#LOAD_BAD[@]}" -gt 0 ]; then
    if [ "${SKIP_LOGS}" = "1" ]; then
        bench_warn "BENCH_TEARDOWN_SKIP_LOGS=1 — deleting load VM(s) whose results are not shown saved; abandoned: ${LOAD_BAD[*]}"
        [ "${BENCH_APPLY}" != "1" ] || bench_manifest_note "teardown: load VMs deleted without their results shown saved (BENCH_TEARDOWN_SKIP_LOGS=1): ${LOAD_BAD[*]}"
    elif [ "${BENCH_APPLY}" = "1" ]; then
        echo "" >&2
        echo "❌ results of ${#LOAD_BAD[@]} load VM(s) not shown saved — NOTHING was pulled or deleted: ${LOAD_BAD[*]}" >&2
        echo "   Collect them: benchmark/benchmark-blast.sh collect --run ${BENCH_RUN_ID} --yes, then re-run the teardown." >&2
        echo "   A blaster still running uploads when it finishes; one whose upload failed holds the only copy in" >&2
        echo "   /var/lib/bench/out. Or delete without them: BENCH_TEARDOWN_SKIP_LOGS=1 benchmark/benchmark-teardown.sh --yes --run ${BENCH_RUN_ID}" >&2
        exit 1
    else
        echo "    ✗ with --yes the teardown stops here, before any pull or delete: ${LOAD_BAD[*]} (collect first: benchmark/benchmark-blast.sh collect --run ${BENCH_RUN_ID} --yes)"
    fi
fi
# bench-obs owes no file: its metrics leave in the Prometheus snapshot pulled before the gates (warn-only).
# Its row lets the delete loop re-check its id like every other instance's; without one it is not deleted.
[ "${OBS_UP}" -ne 1 ] || GATE_IDS="${GATE_IDS}${OBS_CAND} $(inst_id "${OBS_CAND%% *}" "${OBS_CAND#* }")"$'\n'

# Log gate. The helper walks INSTANCE_NAMES and re-pulls an existing log under a new name, so
# it gets a narrowed fleet in a subshell: live instances not saved yet. "Saved" means a marker
# naming the id of the instance that holds the name now (from ALL_INST), whose logs are all still
# here (bench_node_markers_report). A marker of an earlier fleet's instance, or of the older
# format, never counts: that node is pulled again and its new logs land beside the old ones.
# A marker older than BENCH_MARKER_MAX_AGE_SECS counts only with BENCH_TEARDOWN_TRUST_MARKERS=1;
# TRUSTED collects "<inst>@<pull time>" for each marker accepted that way, for the manifest note.
LOG_DIR="${BENCH_RESULTS_DIR}/logs"
PULL_NAMES=(); PULL_ZONES=(); PULL_IDS=(); MISSING=(); TRUSTED=""
echo ""
echo ">>> node logs -> ${LOG_DIR} (nothing is deleted until these are saved)$([ "${SKIP_LOGS}" = "1" ] && echo ' — BENCH_TEARDOWN_SKIP_LOGS=1')$([ "${TRUST_MARKERS}" = "1" ] && echo ' — BENCH_TEARDOWN_TRUST_MARKERS=1')"
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    if [ "$(printf '%s' "${ALL_INST}" | jq --arg n "${inst}" '[.[] | select(.name == $n)] | length')" = "0" ]; then
        echo "    - ${inst}: instance gone — no log to pull"
        continue
    fi
    id="$(inst_id "${ZONES[$i]}" "${inst}")"
    GATE_IDS="${GATE_IDS}${ZONES[$i]} ${inst} ${id}"$'\n'
    if report="$(bench_node_markers_report "${LOG_DIR}" "${inst}" "${id}")"; then
        echo "    ✓ ${inst}: already saved — not pulled again ($(bench_node_saved_sources "${LOG_DIR}" "${inst}" "${id}"))"
        for t in $(printf '%s\n' "${report}" | sed -n 's/.*: accepted .*, pulled \([^;]*\);.*(BENCH_TEARDOWN_TRUST_MARKERS=1)$/\1/p'); do
            TRUSTED="${TRUSTED} ${inst}@${t}"
        done
    else
        echo "    + ${inst}: to pull (instance ${id:-with no id in ${ZONES[$i]}})"
        PULL_NAMES+=("${inst}"); PULL_ZONES+=("${ZONES[$i]}"); PULL_IDS+=("${id}")
    fi
    printf '%s\n' "${report}"
done
# Free-space floor, before the pull starts. The pull copies each node's whole log as it is NOW: a
# fleet left up after the run keeps logging, so the pull can far exceed the run's own log size.
# Below BENCH_TEARDOWN_MIN_FREE_GB under <dest> (or unreadable) it does not start: nothing pulled,
# nothing deleted. 0 skips the check.
if [ "${#PULL_NAMES[@]}" -gt 0 ] && [ "${MIN_FREE_GB}" -gt 0 ]; then
    df_dir="${LOG_DIR}"; [ -d "${df_dir}" ] || df_dir="${BENCH_RESULTS_DIR}"
    free_kb="$(df -Pk "${df_dir}" 2>/dev/null | awk 'NR == 2 { print $4 }')" || free_kb=""
    case "${free_kb}" in ''|*[!0-9]*) free_kb="" ;; esac
    if [ -n "${free_kb}" ]; then
        free_what="$(awk -v k="${free_kb}" 'BEGIN { printf "%.1f GB free", k / 1048576 }')"
    else
        free_what="free space unknown (df -Pk printed no number)"
    fi
    if [ -n "${free_kb}" ] && [ "${free_kb}" -ge $((MIN_FREE_GB * 1048576)) ]; then
        echo "    ✓ ${free_what} under ${df_dir} (BENCH_TEARDOWN_MIN_FREE_GB=${MIN_FREE_GB}) for ${#PULL_NAMES[@]} node(s)"
    elif [ "${BENCH_APPLY}" = "1" ]; then
        echo "" >&2
        echo "❌ ${free_what} under ${df_dir}, below BENCH_TEARDOWN_MIN_FREE_GB=${MIN_FREE_GB} — the pull of ${#PULL_NAMES[@]} node(s) did not start; NOTHING was deleted." >&2
        echo "   Each node's whole log is pulled as it is now. A fleet left up after the run keeps logging, so the" >&2
        echo "   pull can far exceed the run's own log size. Check df -h ${df_dir}, make room, and re-run." >&2
        echo "   Logs a marker already vouches for are not pulled again; a marker older than" >&2
        echo "   $((BENCH_MARKER_MAX_AGE_SECS / 60)) min counts only with BENCH_TEARDOWN_TRUST_MARKERS=1 (see the marker lines above)." >&2
        echo "   Or set the floor: BENCH_TEARDOWN_MIN_FREE_GB=<GB> (0 = no check)." >&2
        exit 1
    else
        echo "    ✗ ${free_what} under ${df_dir}, below BENCH_TEARDOWN_MIN_FREE_GB=${MIN_FREE_GB}: with --yes the teardown stops here, before the pull"
    fi
fi
pull_rc=0
if [ "${#PULL_NAMES[@]}" -gt 0 ]; then
    ( INSTANCE_NAMES=("${PULL_NAMES[@]}"); ZONES=("${PULL_ZONES[@]}"); bench_pull_node_logs "${LOG_DIR}" ) || pull_rc=$?
    stop_if_reauth "the log pull"
    if [ "${BENCH_APPLY}" = "1" ]; then
        # Trust the files, not only the exit status: fail closed on anything the helper missed,
        # and on a marker naming any instance but the one listed above.
        for i in "${!PULL_NAMES[@]}"; do
            bench_node_marker_ok "${LOG_DIR}" "${PULL_NAMES[$i]}" "${PULL_IDS[$i]}" || MISSING+=("${PULL_NAMES[$i]}")
        done
    fi
fi
if [ "${pull_rc}" -ne 0 ] || [ "${#MISSING[@]}" -gt 0 ]; then
    [ "${#MISSING[@]}" -gt 0 ] || MISSING=("(none identified — bench_pull_node_logs exited ${pull_rc})")
    if [ "${SKIP_LOGS}" = "1" ]; then
        bench_warn "BENCH_TEARDOWN_SKIP_LOGS=1 — deleting WITHOUT the node log of: ${MISSING[*]}"
        bench_manifest_note "teardown: instances deleted without their node log (BENCH_TEARDOWN_SKIP_LOGS=1): ${MISSING[*]}"
    else
        echo "" >&2
        echo "❌ node logs not saved — NOTHING was deleted. Missing:" >&2
        for inst in "${MISSING[@]}"; do
            st="$(printf '%s' "${ALL_INST}" | jq -r --arg n "${inst}" '.[] | select(.name == $n) | .status' 2>/dev/null || true)"
            echo "   - ${inst}${st:+ (${st})}" >&2
        done
        echo "   Either fix the pull (IAP ssh; a node needs one log from its container, saved logs or unit" >&2
        echo "   files, and no failed transfer; logs an earlier instance of the same name left do not count)" >&2
        echo "   and re-run; logs already in ${LOG_DIR} are kept." >&2
        echo "   Or delete without them: BENCH_TEARDOWN_SKIP_LOGS=1 benchmark/benchmark-teardown.sh --yes --run ${BENCH_RUN_ID}" >&2
        exit 1
    fi
fi
# The logs of a node saved by an older marker end at that marker's pull time: say so, once the gate
# has passed (a gate that stops here records nothing; its re-run does).
if [ -n "${TRUSTED}" ] && [ "${BENCH_APPLY}" = "1" ]; then
    bench_manifest_note "teardown: saved logs accepted from markers older than the freshness window (BENCH_TEARDOWN_TRUST_MARKERS=1):${TRUSTED}"
fi

# Preserve sampler history and the service journal before any deletion, even when a
# previous attempt already saved the node's container log.
source "${DIR}/recovery-lib.sh"
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    id="$(printf '%s' "${GATE_IDS}" | awk -v z="${ZONES[$i]}" -v n="${inst}" '$1 == z && $2 == n { print $3; exit }')"
    [ -n "${id}" ] || continue
    if ! bench_pull_recovery_evidence "${inst}" "${ZONES[$i]}" "${id}" "${LOG_DIR}"; then
        if [ "${SKIP_LOGS}" = 1 ]; then
            bench_manifest_note "teardown: recovery evidence unavailable for ${inst} (BENCH_TEARDOWN_SKIP_LOGS=1)"
        else
            echo "recovery evidence missing for ${inst}; nothing was deleted" >&2
            exit 1
        fi
    fi
done

# ================================ certification outcome (before the local gate) ===========
# tools/cert-rate.py over the logs just pulled: manifest.certification and .cert_failures. Each
# failing validator still up gets a cert-fail container-log snapshot, pulled into logs/ and listed
# in .cert_failures[].logs[], which the local gate below requires. Informational: it only warns.
echo ""
echo ">>> certification outcome: ${LOG_DIR} (before the local gate, which requires every log manifest.cert_failures lists)"
bench_certification_record "${LOG_DIR}" "$(bench_manifest)" || bench_warn "certification not recorded — the gate checks what manifest.cert_failures lists"
bench_cert_failures_snapshot "${LOG_DIR}" "$(bench_manifest)" || bench_warn "certification snapshots not taken — the gate checks what manifest.cert_failures lists"
stop_if_reauth "the certification snapshots"

# ================================ bench-obs Prometheus snapshot (before the gates) ========
# The run's metrics go with bench-obs: a TSDB snapshot lands in logs/ now, so the coverage and local
# gates below see it and INDEX.md / CHECKSUMS.sha256 list it. Neither gate requires it: the pull
# warns and returns 0 whatever happens (BENCH_OBS_PULL_PROM=0 skips it); a dry run prints its argv.
echo ""
echo ">>> bench-obs Prometheus snapshot -> ${LOG_DIR} (informs, never blocks)"
if [ "${OBS_UP}" -ne 1 ]; then
    echo "    - no bench-obs of this run: no snapshot"
else
    bench_obs_prom_snapshot_pull "${LOG_DIR}" || bench_warn "bench-obs Prometheus snapshot not pulled — teardown continues"
    stop_if_reauth "the Prometheus snapshot"
fi

# ================================ log coverage (before the local gate) ====================
# D19: presence is not coverage. logrotate moved bench 3's first hours into telcoin.log.1 and the
# teardown pulled only the live file, so the nodes were deleted with their logs starting 70-90 min
# after the coordinated start. Each fleet node's pulled logs must reach back to
# coordinated_start.due and forward to timestamps.blast_end (unix seconds, "-" when the manifest has
# none); bench_log_coverage_check reads the span the pull recorded and prints one LOGCOV line.
# ok=0, or no LOGCOV line at all, stops the teardown. ok=- is a note for a run without both ends,
# for a node already gone, and under BENCH_TEARDOWN_SKIP_LOGS=1. Otherwise ok=- can only mean
# there is no logs/<inst>.logspan (the span script prints a line per stream even for a missing
# file), and a live node whose span was never recorded stops the teardown like ok=0.
echo ""
echo ">>> log coverage: ${LOG_DIR} (each node's logs from the coordinated start to the blast end)$([ "${SKIP_COVERAGE}" = "1" ] && echo ' — BENCH_TEARDOWN_SKIP_COVERAGE=1')"
cov_due="$(jq -r '.coordinated_start.due // empty | tostring' "$(bench_manifest)" 2>/dev/null)" || cov_due=""
case "${cov_due}" in ''|*[!0-9]*) cov_due="-" ;; esac
cov_end="$(jq -r '.timestamps.blast_end // empty | fromdateiso8601 | tostring' "$(bench_manifest)" 2>/dev/null)" || cov_end=""
case "${cov_end}" in ''|*[!0-9]*) cov_end="-" ;; esac
[ "${cov_due}" != "-" ] || echo "    · the manifest has no coordinated_start.due: no node can be held to the run's start (ok=-)"
[ "${cov_end}" != "-" ] || echo "    · the manifest has no timestamps.blast_end: no node can be held to the run's end (ok=-)"
cov_bad=0; cov_unknown=0; COV_BAD=""; COV_LINES=""
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    # live: the log gate saw the instance (GATE_IDS has a row for it, with or without an id)
    cov_live="$(printf '%s' "${GATE_IDS}" | awk -v z="${ZONES[$i]}" -v n="${inst}" '$1 == z && $2 == n { print "live"; exit }')"
    cov_rc=0
    cov_out="$(bench_log_coverage_check "${LOG_DIR}" "${inst}" "${cov_due}" "${cov_end}" 2>&1)" || cov_rc=$?
    [ -z "${cov_out}" ] || printf '%s\n' "${cov_out}"
    cov_line="$(printf '%s\n' "${cov_out}" | sed -n "s/^[[:space:]]*\(LOGCOV ${inst} .*\)\$/\1/p" | tail -n 1)"
    case " ${cov_line} " in
        *" ok=1 "*) ;;
        *" ok=- "*)
            if [ "${cov_due}" != "-" ] && [ "${cov_end}" != "-" ] && [ -n "${cov_live}" ] && [ "${SKIP_LOGS}" != "1" ]; then
                echo "    ✗ ${inst}: no recorded span (logs/${inst}.logspan) for a live node of a run whose start and end are known — counted as not covered"
                cov_line="${cov_line% ok=-} ok=0"
                cov_bad=$((cov_bad + 1)); COV_BAD="${COV_BAD} ${inst}"
            else
                cov_unknown=$((cov_unknown + 1))
            fi
            ;;
        *" ok=0 "*) cov_bad=$((cov_bad + 1)); COV_BAD="${COV_BAD} ${inst}" ;;
        *)
            echo "    ✗ ${inst}: no LOGCOV line from bench_log_coverage_check (rc ${cov_rc}) — counted as not covered"
            cov_line="LOGCOV ${inst} due=${cov_due} end=${cov_end} ok=0"
            cov_bad=$((cov_bad + 1)); COV_BAD="${COV_BAD} ${inst}"
            ;;
    esac
    COV_LINES="${COV_LINES}${cov_line}"$'\n'
done
if [ "${BENCH_APPLY}" = "1" ]; then
    cov_json="$(printf '%s' "${COV_LINES}" | jq -R -s -c --arg t "$(bench_now_iso)" '
        def v: if . == null or . == "" or . == "-" then null elif test("^[0-9]+$") then tonumber else . end;
        [split("\n")[] | select(startswith("LOGCOV ")) | split(" ") as $w
         | ([$w[2:][] | capture("^(?<k>[a-z_]+)=(?<v>.*)$")] | map({(.k): .v}) | add // {}) as $f
         | {inst: $w[1], generations: ($f.gens | v), first_ts: ($f.first | v), last_ts: ($f.last | v),
            due: ($f.due | v), blast_end: ($f.end | v),
            ok: (if $f.ok == "1" then true elif $f.ok == "0" then false else null end), checked_at: $t}]')" \
        && bench_manifest_jq --argjson c "${cov_json}" '.log_coverage = $c' \
        || bench_warn "manifest.log_coverage not written — the LOGCOV lines above are the record"
fi
if [ "${cov_bad}" -gt 0 ] && [ "${SKIP_COVERAGE}" != "1" ]; then
    if [ "${BENCH_APPLY}" = "1" ]; then
        echo "" >&2
        echo "❌ the logs of ${cov_bad} node(s) do not cover the run (LOGCOV ok=0 above) — NOTHING was deleted:${COV_BAD}" >&2
        echo "   Their earliest line is after the coordinated start, their latest before the blast end, or their span is" >&2
        echo "   missing or unreadable. Pull the missing generations (telcoin.log.1, telcoin.log.N.gz) from the live nodes, or" >&2
        echo "   rescue them by hand, and re-run; what is already in ${LOG_DIR} is kept." >&2
        echo "   Or delete without them: BENCH_TEARDOWN_SKIP_COVERAGE=1 benchmark/benchmark-teardown.sh --yes --run ${BENCH_RUN_ID}" >&2
        exit 1
    fi
    echo "    ✗ with --yes the teardown stops here, before any delete:${COV_BAD} (BENCH_TEARDOWN_SKIP_COVERAGE=1 deletes without their coverage)"
elif [ "${cov_bad}" -gt 0 ]; then
    bench_warn "BENCH_TEARDOWN_SKIP_COVERAGE=1 — deleting although the logs of${COV_BAD} do not cover the run"
    [ "${BENCH_APPLY}" != "1" ] || bench_manifest_note "teardown: deleted although the logs of${COV_BAD} do not cover the run (BENCH_TEARDOWN_SKIP_COVERAGE=1) at $(bench_now_iso)" || true
else
    echo "    ✓ ${#INSTANCE_NAMES[@]} node(s): $((${#INSTANCE_NAMES[@]} - cov_unknown)) cover the run$([ "${cov_unknown}" -eq 0 ] || echo ", ${cov_unknown} unknown (ok=-, a note: no run window, a node already gone, or BENCH_TEARDOWN_SKIP_LOGS=1)")"
fi

# ================================ local gate (before any delete) ==========================
# results/<run>/ is the only copy of the run once the fleet is gone (see the header).
echo ""
echo ">>> local gate: ${BENCH_RESULTS_DIR} (the only copy; nothing is deleted until it holds every node's logs)$([ "${SKIP_GATE}" = "1" ] && echo ' — BENCH_TEARDOWN_SKIP_LOCAL_GATE=1')"
[ "${BENCH_APPLY}" = "1" ] || echo "    (dry run — the pulls above did not run; this is what results/${BENCH_RUN_ID}/ holds now)"
RESULTS_ABS="$(cd "${BENCH_RESULTS_DIR}" && pwd -P)"
if bench_local_gate_check "${INSTANCE_NAMES[@]}"; then
    bench_local_index --arg p "${RESULTS_ABS}" --arg t "$(bench_now_iso)" '.archive = {kind: "local", path: $p, verified_at: $t}' || {
        echo "❌ ${BENCH_RESULTS_DIR}: INDEX.md, CHECKSUMS.sha256 or manifest.archive not written — NOTHING was deleted." >&2
        exit 1
    }
elif [ "${SKIP_GATE}" = "1" ]; then
    bench_warn "BENCH_TEARDOWN_SKIP_LOCAL_GATE=1 — deleting although ${BENCH_RESULTS_DIR} lacks the file(s) marked ✗ above; they are lost with the fleet"
    if [ "${BENCH_APPLY}" = "1" ]; then
        bench_local_index --arg p "${RESULTS_ABS}" '.archive = {kind: "local", path: $p, skipped_gate: true}' \
            || bench_warn "INDEX.md, CHECKSUMS.sha256 or manifest.archive not written"
        bench_manifest_note "teardown: deleted without the local gate (BENCH_TEARDOWN_SKIP_LOCAL_GATE=1) at $(bench_now_iso)" || true
    fi
elif [ "${BENCH_APPLY}" = "1" ]; then
    echo "" >&2
    echo "❌ ${BENCH_RESULTS_DIR} lacks the file(s) marked ✗ above — NOTHING was deleted." >&2
    echo "   It is the only copy of the run. Fix the pull (the teardown pulls what is missing from the" >&2
    echo "   live nodes) and re-run; what is already in ${LOG_DIR} is kept." >&2
    echo "   Or delete without them: BENCH_TEARDOWN_SKIP_LOCAL_GATE=1 benchmark/benchmark-teardown.sh --yes --run ${BENCH_RUN_ID}" >&2
    exit 1
else
    echo "    ✗ with --yes the teardown stops here, before any delete, unless the pulls above land them (BENCH_TEARDOWN_SKIP_LOCAL_GATE=1 deletes without them)"
fi

# ================================ delete ==================================================
echo ""
echo ">>> plan / execution"
# The bench-obs forwards came up after the listing above: look again (Prometheus is not read after this).
[ "${BENCH_APPLY}" != "1" ] || TUNNEL_PIDS="$(pgrep -f "${TUNNEL_PAT}" 2>/dev/null | tr '\n' ' ' || true)"
if [ -n "${TUNNEL_PIDS}" ]; then
    # the pidfiles' process groups first (supervisor + child together; bench_tunnel_down stops every
    # tunnel*.pid, the bench-obs forwards' too), then whatever is left
    [ "${BENCH_APPLY}" = "1" ] && bench_tunnel_down
    # shellcheck disable=SC2086  # pid list
    bench_run kill ${TUNNEL_PIDS} || true
fi
# Every tunnel process found was stopped above: a pidfile still here names a dead one.
[ "${BENCH_APPLY}" = "1" ] && rm -f "$(bench_tunnel_pidfile)" "${BENCH_RESULTS_DIR}"/tunnel*.pid
# D21: timestamps.teardown_start is the first teardown's; a re-run of a run whose teardown already
# reached this point appends {start, done} to teardown_reruns[] instead of moving it.
TD_START="$(bench_now_iso)"
if [ "${BENCH_APPLY}" = "1" ]; then
    bench_manifest_jq --arg t "${TD_START}" '
        if (.timestamps.teardown_start // null) == null then .timestamps.teardown_start = $t
        else .teardown_reruns = ((.teardown_reruns // []) + [{start: $t, done: null}]) end' \
        || bench_die "could not record the teardown start in $(bench_manifest) — NOTHING was deleted"
fi
# One instance per delete call, each right after a fresh lookup: the instance that holds the name
# now must be the one the gates passed (same numeric id, GATE_IDS). A name deleted and recreated
# since has a new id: it is not deleted, and neither is anything after it. A short race remains:
# an instance replaced between this lookup and its delete call is still deleted. The calls are
# issued in the background (D22: about 50 s each when serial; gcloud has no --async here, D35);
# the loop after them waits for every one to finish.
ISSUED=(); ISSUED_NAMES=""   # "<zone> <name> <id>" per delete issued; their names
DELETE_PIDS=()               # "<pid> <zone> <name>" per background delete (apply mode)
for z in $(for c in "${CAND_INST[@]+"${CAND_INST[@]}"}"; do echo "${c%% *}"; done | sort -u); do
    for c in "${CAND_INST[@]}"; do
        [ "${c%% *}" = "${z}" ] || continue
        n="${c#* }"
        want="$(printf '%s' "${GATE_IDS}" | awk -v z="${z}" -v n="${n}" '$1 == z && $2 == n { print $3; exit }')"
        if [ "${BENCH_APPLY}" = "1" ]; then
            now_id="$(bench_instance_json "${n}" "${z}" | jq -r '.id // "" | tostring' 2>/dev/null || true)"
            case "${want}" in ''|*[!0-9]*) now_id="${now_id:-not found} (the gates passed no id for it)" ;; esac
            if [ "${now_id}" != "${want}" ]; then
                echo "" >&2
                echo "❌ ${n} (${z}) is now instance ${now_id:-not found}; the gates passed instance ${want:-none} — NOT deleted, nor anything after it." >&2
                echo "   Delete already issued (in the background, not waited for):${ISSUED_NAMES:- none}." >&2
                echo "   Left: ${n}, the instances after it, and every firewall rule, disk, bucket, secret binding and" >&2
                echo "   local item. Re-run the teardown: it checks that name's instance again." >&2
                exit 1
            fi
        else
            echo "    (just before this delete: ${n} must still be instance ${want:-?}, else the teardown stops here)"
        fi
        # gcloud's instances delete has no --async (SDK 588 rejects it; D35): each delete runs
        # synchronously in the background, and the describe loop below is what waits for them.
        if [ "${BENCH_APPLY}" = "1" ]; then
            printf '    +'; printf ' %q' gcloud compute instances delete "${n}" --zone="${z}" --project="${PROJECT_ID}" --quiet; printf '\n'
            ( gcloud compute instances delete "${n}" --zone="${z}" --project="${PROJECT_ID}" --quiet \
                </dev/null >"${TD_TMP}/delete-${n}.out" 2>&1 ) &
            DELETE_PIDS+=("$! ${z} ${n}")
        else
            bench_run gcloud compute instances delete "${n}" --zone="${z}" --project="${PROJECT_ID}" --quiet
        fi
        ISSUED+=("${z} ${n} ${want}"); ISSUED_NAMES="${ISSUED_NAMES} ${n}"
    done
done
# delete_state <zone> <name> <id> — "gone" once describe says the instance is not found (or the name
# now holds another instance), else its status ("?" when describe failed for another reason).
delete_state() {
    local out rc=0 st
    out="$(perl -e 'alarm shift; exec @ARGV' 60 gcloud compute instances describe "$2" --zone="$1" --project="${PROJECT_ID}" \
        --format=json </dev/null 2>"${TD_TMP}/describe.err")" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        if grep -q 'not found' "${TD_TMP}/describe.err" 2>/dev/null; then echo gone; else echo "?"; fi
        return 0
    fi
    st="$(printf '%s' "${out}" | jq -r --arg id "$3" 'if (.id // "" | tostring) == $id then (.status // "?") else "gone" end' 2>/dev/null)" || st=""
    echo "${st:-?}"
}
# One describe per instance still deleting, every DELETE_POLL_SECS, until none is left or
# BENCH_TEARDOWN_DELETE_WAIT_SECS have passed (0: one pass, no wait).
GONE=(); PENDING=(); TD_PENDING=""   # TD_PENDING: "<zone> <name> <status>" per instance still there at the cap
if [ "${#ISSUED[@]}" -gt 0 ] && [ "${BENCH_APPLY}" = "1" ]; then
    echo "    waiting for ${#ISSUED[@]} instance delete(s): a describe each every ${DELETE_POLL_SECS} s, at most ${DELETE_WAIT_SECS} s (BENCH_TEARDOWN_DELETE_WAIT_SECS)"
    PENDING=("${ISSUED[@]}")
    wait_t0="$(bench_now_unix)"
    while :; do
        still=()
        for c in "${PENDING[@]}"; do
            read -r z n want <<< "${c}"
            st="$(delete_state "${z}" "${n}" "${want}")"
            if [ "${st}" = "gone" ]; then GONE+=("${n}"); echo "    ✓ ${n} (${z}) deleted"
            else still+=("${c} ${st}"); fi
        done
        PENDING=()
        for c in "${still[@]+"${still[@]}"}"; do PENDING+=("${c% *}"); done
        [ "${#PENDING[@]}" -gt 0 ] || break
        if [ "$(($(bench_now_unix) - wait_t0))" -ge "${DELETE_WAIT_SECS}" ]; then
            for c in "${still[@]}"; do
                read -r z n want st <<< "${c}"
                echo "    ✗ ${n} (${z}) still there after ${DELETE_WAIT_SECS} s (status ${st}) — the left-nothing checks below count it"
                TD_PENDING="${TD_PENDING}${z} ${n} ${st}"$'\n'
            done
            break
        fi
        sleep "${DELETE_POLL_SECS}"
    done
    # Reap the finished delete calls (a failed call shows here; an instance still there is counted
    # by the left-nothing checks); one still running at the cap is reported, never waited for.
    for c in "${DELETE_PIDS[@]+"${DELETE_PIDS[@]}"}"; do
        read -r pid z n <<< "${c}"
        if kill -0 "${pid}" 2>/dev/null; then
            echo "    ✗ delete of ${n} (${z}) still running (pid ${pid}) — not waited for"
        elif ! wait "${pid}"; then
            echo "    ✗ delete of ${n} (${z}) exited non-zero: $(tail -n 2 "${TD_TMP}/delete-${n}.out" 2>/dev/null | tr '\n' ' ')"
        fi
    done
elif [ "${#ISSUED[@]}" -gt 0 ]; then
    echo "    (then one describe per instance every ${DELETE_POLL_SECS} s until each is gone, at most ${DELETE_WAIT_SECS} s: BENCH_TEARDOWN_DELETE_WAIT_SECS)"
fi
for r in "${CAND_FW[@]+"${CAND_FW[@]}"}"; do
    bench_run gcloud compute firewall-rules delete "${r}" --project="${PROJECT_ID}" --quiet
done
# Orphan disks: re-list after the instances are gone (boot disks auto-delete with them).
if [ "${BENCH_APPLY}" = "1" ]; then
    while IFS= read -r row; do
        [ -n "${row}" ] || continue
        read -r dz dn dl du <<< "${row}"
        case "${dn}" in bench-*) ;; *) continue ;; esac
        [ -z "${du:-}" ] || { bench_warn "disk ${dn} still attached to ${du} — left"; continue; }
        [ "${dl}" = "${BENCH_RUN_ID}" ] || { echo "    - disk ${dn} (${dz}): $(disk_fate "${dl}")"; continue; }
        bench_run gcloud compute disks delete "${dn}" --zone="${dz}" --project="${PROJECT_ID}" --quiet
    done < <(list_disks)
else
    echo "    (orphan disks are re-listed after the instances; only unattached ones labelled bench-run=${BENCH_RUN_ID} are deleted)"
fi
LEFT_BKT=()
for b in "${CAND_BKT[@]+"${CAND_BKT[@]}"}"; do
    first_obj="$(gcloud storage ls "gs://${b}/**" --project="${PROJECT_ID}" 2>/dev/null | head -1 || true)"
    if [ -z "${first_obj}" ]; then
        bench_run gcloud storage buckets delete "gs://${b}" --project="${PROJECT_ID}" --quiet
        continue
    fi
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}/bucket/${b}"
    if bench_run gcloud storage cp -r "gs://${b}/*" "${BENCH_RESULTS_DIR}/bucket/${b}/"; then
        bench_run gcloud storage rm -r "gs://${b}" --project="${PROJECT_ID}"
    else
        # The bucket may hold the only copy of a run's results: never delete it unbacked.
        echo "❌ backup of non-empty gs://${b} failed — bucket LEFT in place: ${b}" >&2
        LEFT_BKT+=("${b}")
    fi
done
for s in "${SECRETS[@]}"; do
    if gcloud secrets get-iam-policy "${s}" --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -e --arg m "serviceAccount:${SERVICE_ACCOUNT}" '[.bindings[]? | .members[]] | index($m)' >/dev/null; then
        bench_run gcloud secrets remove-iam-policy-binding "${s}" --project="${PROJECT_ID}" \
            --member="serviceAccount:${SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor --format=none
    fi
    if [ "${PURGE}" -eq 1 ]; then
        lbl="$(gcloud secrets describe "${s}" --project="${PROJECT_ID}" --format='value(labels.benchmark)' 2>/dev/null || true)"
        case "${s}" in bench-txgen-*) ;; *) bench_die "refusing to purge non bench-txgen secret ${s}" ;; esac
        if [ "${lbl}" = "1" ]; then bench_run gcloud secrets delete "${s}" --project="${PROJECT_ID}" --quiet
        else bench_warn "secret ${s} absent or not labelled benchmark=1 — not purged"; fi
    fi
done
if [ "${WT_PRESENT}" -eq 1 ]; then
    bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" worktree remove --force "${BENCH_CONTRACTS_WORKTREE}"
fi
bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" worktree prune
for br in "${BENCH_BRANCHES[@]+"${BENCH_BRANCHES[@]}"}"; do
    bench_run git -C "${BENCH_CONTRACTS_SRC_DIR}" branch -D "${br}"
done
if [ -d "${BENCH_DIR}/genesis" ]; then
    [ "${BENCH_APPLY}" = "1" ] && mkdir -p "${BENCH_RESULTS_DIR}"
    if [ -e "${BENCH_RESULTS_DIR}/genesis" ]; then
        bench_run mv "${BENCH_DIR}/genesis" "${BENCH_RESULTS_DIR}/genesis.$(date -u +%Y%m%d%H%M%S)"
    else
        bench_run mv "${BENCH_DIR}/genesis" "${BENCH_RESULTS_DIR}/genesis"
    fi
fi
# D21: timestamps.teardown_done once (the first teardown whose deletes all finished); this run's
# teardown_reruns[] entry, when it is one, gets its done time too. An instance still deleting at the
# BENCH_TEARDOWN_DELETE_WAIT_SECS cap leaves both unset and is listed in teardown_pending[] instead
# (a re-run that finds nothing left to wait for writes the done time and drops the list).
if [ "${BENCH_APPLY}" = "1" ] && [ -n "${TD_PENDING}" ]; then
    bench_manifest_jq --arg p "${TD_PENDING}" --arg t "$(bench_now_iso)" '
        .teardown_pending = [$p | split("\n")[] | select(. != "") | split(" ")
                             | {inst: .[1], zone: .[0], status: .[2], at: $t}]' \
        || bench_warn "could not record teardown_pending in $(bench_manifest)"
elif [ "${BENCH_APPLY}" = "1" ]; then
    bench_manifest_jq --arg s "${TD_START}" --arg t "$(bench_now_iso)" '
        .timestamps.teardown_done = (.timestamps.teardown_done // $t)
        | if .teardown_reruns then .teardown_reruns |= map(if .start == $s and .done == null then .done = $t else . end) else . end
        | del(.teardown_pending)' \
        || bench_warn "could not record the teardown end in $(bench_manifest)"
fi

# ================================ node startup provenance =================================
# Informational: which node build the saved logs show each node started (report/provenance.py,
# against the manifest's node_git_sha), written to the manifest as node_startup_check. Runs once
# the log gate has passed (with BENCH_TEARDOWN_SKIP_LOGS=1, on whatever logs were saved) and after
# the deletes, so the fleet is not kept up while the logs are read. Its result never stops the teardown.
node_startup_check() {
    local prov="${DIR}/report/provenance.py" out rc=0 why
    echo ""
    echo ">>> node startup provenance (informational — never blocks the teardown)"
    command -v python3 >/dev/null 2>&1 || { bench_warn "python3 not on PATH — node startup provenance not checked"; return 0; }
    [ -f "${prov}" ] || { bench_warn "${prov} missing — node startup provenance not checked"; return 0; }
    if [ "${BENCH_APPLY}" != "1" ]; then
        bench_run python3 "${prov}" --run-dir "${BENCH_RESULTS_DIR}" --update-manifest
        return 0
    fi
    out="$(python3 "${prov}" --run-dir "${BENCH_RESULTS_DIR}" --update-manifest 2>&1)" || rc=$?
    [ -z "${out}" ] || printf '%s\n' "${out}" | sed 's/^/    /'
    case "${rc}" in
        0) echo "    ✓ node startup provenance ok" ;;
        2) bench_warn "no node startup lines found in the saved logs" ;;
        *)
            bench_warn "node startup provenance mismatch — see manifest.node_startup_check"
            why="$(jq -r '(.node_startup_check.problems // []) | join("; ")' "$(bench_manifest)" 2>/dev/null || true)"
            bench_manifest_note "teardown: node startup provenance mismatch (provenance.py exit ${rc})${why:+: ${why}} — see node_startup_check" || true
            ;;
    esac
    return 0
}
node_startup_check || bench_warn "node startup provenance check failed — teardown continues"

# ================================ final local index =======================================
# Since the gate, the deletes copied the run bucket into results/<run>/bucket/, genesis/ moved in
# and the manifest has grown: analysis/ is written (the node logs are here now), then INDEX.md and
# CHECKSUMS.sha256 again over the final tree. Never blocks.
final_local_index() {
    echo ""
    echo ">>> final local index: ${BENCH_RESULTS_DIR} (informational — never blocks the teardown)"
    bench_local_analysis
    if [ "${BENCH_APPLY}" = "1" ] && jq -e '.archive.kind == "local"' "$(bench_manifest)" >/dev/null 2>&1; then
        bench_local_index --arg t "$(bench_now_iso)" '.archive.final_index_at = $t'
    else
        bench_local_index
    fi
}
final_local_index || bench_warn "final local index failed — the gate's INDEX.md and CHECKSUMS.sha256 stay; re-run the teardown to rewrite them"

# ================================ left-nothing checks =====================================
echo ""
echo ">>> left-nothing checks$([ "${BENCH_APPLY}" = "1" ] || echo ' (current state — dry run deleted nothing)')"
lrc=0; LEFT_N=0
chk() { # <label> <count> [detail] — LEFT_N adds up the counts (TEARDOWN_DONE left=)
    if [ "$2" = "0" ]; then echo "    ✓ $1: none"; else echo "    ✗ $1: $2 ${3:-}"; lrc=1; fi
    case "$2" in ''|*[!0-9]*) LEFT_N=$((LEFT_N + 1)) ;; *) LEFT_N=$((LEFT_N + $2)) ;; esac
}
now_inst="$(gcloud compute instances list --project="${PROJECT_ID}" --format=json)"
chk "instances labelled benchmark=1" "$(printf '%s' "${now_inst}" | jq '[.[] | select((.labels.benchmark // "") == "1")] | length')" \
    "$(printf '%s' "${now_inst}" | jq -r '[.[] | select((.labels.benchmark // "") == "1") | .name] | join(",")')"
chk "instances named bench-*" "$(printf '%s' "${now_inst}" | jq '[.[] | select(.name | test("^bench-"))] | length')"
chk "bench-obs (${BENCH_OBS_INSTANCE})" "$(printf '%s' "${now_inst}" | jq --arg n "${BENCH_OBS_INSTANCE}" '[.[] | select(.name == $n)] | length')"
chk "firewall rules ^bench- or targeting bench-node" "$(gcloud compute firewall-rules list --project="${PROJECT_ID}" --format=json \
    | jq '[.[] | select((.name | test("^bench-")) or ((.targetTags // []) | index("bench-node")))] | length')"
chk "buckets labelled benchmark=1 / named tn-devnet-bench-*" "$(bench_bucket_names | grep -c . || true)" "${LEFT_BKT[*]:+(backup failed, left: ${LEFT_BKT[*]})}"
chk "disks of run ${BENCH_RUN_ID} (labelled benchmark=1 / named bench-*)" "$(list_disks | awk -v r="${BENCH_RUN_ID}" '$3 == r' | grep -c . || true)"
list_disks | awk -v r="${BENCH_RUN_ID}" '$3 != r' | while read -r dz dn dl du; do echo "    ⚠ disk ${dn} (${dz}) left: $(disk_fate "${dl}")"; done
# Whatever the name: bench-obs's boot and data disks carry the run's label and go with it.
run_disks="$(gcloud compute disks list --project="${PROJECT_ID}" --format=json 2>/dev/null \
    | jq -r --arg r "${BENCH_RUN_ID}" '[.[] | select((.labels["bench-run"] // "") == $r) | .name] | "\(length) \(join(","))"')" \
    || run_disks="? (the disk list failed)"
chk "disks labelled bench-run=${BENCH_RUN_ID} (any name)" "${run_disks%% *}" "${run_disks#* }"
chk "local IAP tunnels on :${BENCH_TUNNEL_PORT}, :${BENCH_OBS_PROM_LOCAL_PORT}, :${BENCH_OBS_GRAFANA_LOCAL_PORT} (supervisor, ssh forward or websocket)" "$(pgrep -f "${TUNNEL_PAT}" 2>/dev/null | grep -c . || true)"
chk "contracts worktree" "$([ -e "${BENCH_CONTRACTS_WORKTREE}" ] && echo 1 || echo 0)" "${BENCH_CONTRACTS_WORKTREE}"
chk "bench/r* branches" "$(git -C "${BENCH_CONTRACTS_SRC_DIR}" for-each-ref --format=x 'refs/heads/bench/r*' 2>/dev/null | grep -c . || true)"
acc=0
for s in "${SECRETS[@]}"; do
    gcloud secrets get-iam-policy "${s}" --project="${PROJECT_ID}" --format=json 2>/dev/null \
        | jq -e --arg m "serviceAccount:${SERVICE_ACCOUNT}" '[.bindings[]? | .members[]] | index($m)' >/dev/null && acc=$((acc + 1))
done
chk "compute-SA bindings on bench secrets" "${acc}"
echo "    · results/${BENCH_RUN_ID}/ kept, the only copy (back it up outside the repo): $(_bench_results_totals "${BENCH_RESULTS_DIR}" | awk '{ print $1 " file(s), " $2 " bytes" }')"
echo "    · certification: $(bench_certification_summary "$(bench_manifest)")"
echo "    devnet instances (must all be present):"
for d in "${DENY[@]}"; do
    st="$(printf '%s' "${now_inst}" | jq -r --arg n "${d}" '.[] | select(.name == $n) | .status')"
    pre=""
    [ -f "${BENCH_RESULTS_DIR}/pre-instances.json" ] && pre="$(jq -r --arg n "${d}" '.[] | select(.name == $n) | .status' "${BENCH_RESULTS_DIR}/pre-instances.json")"
    if [ -n "${st}" ]; then echo "      ✓ ${d} ${st}${pre:+ (pre-run ${pre})}"; else echo "      ✗ ${d} MISSING"; lrc=1; fi
done
if [ -f "${BENCH_RESULTS_DIR}/pre-firewall.json" ]; then
    a="$(jq -S '.[] | select(.name == "devnet-allow-consensus")' "${BENCH_RESULTS_DIR}/pre-firewall.json")"
    b="$(gcloud compute firewall-rules describe devnet-allow-consensus --project="${PROJECT_ID}" --format=json 2>/dev/null | jq -S . || true)"
    if [ "${a}" = "${b}" ]; then echo "    ✓ devnet-allow-consensus identical to the run pre-snapshot"; else echo "    ✗ devnet-allow-consensus differs from the run pre-snapshot"; lrc=1; fi
fi
# The last line, for a watcher: deleted = instances confirmed gone, left = the counts above.
if [ "${BENCH_APPLY}" = "1" ]; then
    [ "${lrc}" -eq 0 ] && echo "✓ teardown left nothing behind." || echo "❌ teardown left something behind (✗ above)." >&2
    echo "TEARDOWN_DONE run=${BENCH_RUN_ID} deleted=${#GONE[@]} left=${LEFT_N} at=$(bench_now_iso)"
    exit "${lrc}"
fi
echo "DRY RUN — re-run with --yes to delete the candidates above."
echo "TEARDOWN_DONE run=${BENCH_RUN_ID} deleted=0 left=${LEFT_N} at=$(bench_now_iso) dry_run=1"
