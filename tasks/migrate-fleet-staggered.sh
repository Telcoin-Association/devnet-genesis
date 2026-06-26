#!/usr/bin/env bash
# =============================================================================
# migrate-fleet-staggered.sh -- ONE-TIME staggered rollout of the unified-naming
# migration (tn-node-deployment/migrate-node-naming.sh) across the devnet fleet.
#
# Safe by construction:
#   * READ-ONLY PRE-CHECK per node decides skip-vs-migrate. An already-migrated
#     node (telcoin.service present, no legacy telcoin-{observer,validator}.service)
#     is SKIPPED without ever being stopped -- so re-running is a no-op (idempotent),
#     and node5/observer-5 (already migrated) is left untouched.
#   * STAGGERED: one node at a time, observer(s) first then validators. The 4
#     validators are a BFT committee -- taking more than one down at once would drop
#     below quorum (3/4) and halt consensus, so we NEVER stop the next node until the
#     previous one is back and healthy.
#   * HEALTH-GATED: after each migration we verify telcoin.service is active, RPC
#     answers, and the block height is advancing. Any failure ABORTS the rollout
#     (no cascade). migrate-node-naming.sh itself self-rolls-back on failure
#     (restores + restarts the legacy service), so a bad node recovers on its own.
#   * Delivers the CURRENT LOCAL migrate-node-naming.sh + its lib/ deps to each node
#     (tar over IAP scp), so this tests exactly the working-tree version regardless
#     of what `update-scripts.sh` has pulled / whether origin/main was pushed.
#
# USAGE (run from the repo root or from tasks/):
#   bash tasks/migrate-fleet-staggered.sh             # interactive: confirm before each node
#   bash tasks/migrate-fleet-staggered.sh --dry-run   # PRE-CHECK only -- prints the plan, changes nothing
#   bash tasks/migrate-fleet-staggered.sh --yes       # auto-proceed between nodes (still health-gated + abort-on-fail)
#   bash tasks/migrate-fleet-staggered.sh --only node3 # one node only (node1..node5 or an instance name)
#
# REQUIRES: gcloud (authenticated, IAP access to tn-devnet) and passwordless sudo on
# the nodes (the existing tasks/*.sh fleet drivers already rely on both).
# =============================================================================

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
# shellcheck source=/dev/null
source config.sh

MIGRATE_SRC="${REPO_ROOT}/tn-node-deployment/migrate-node-naming.sh"
LIB_DIR="${REPO_ROOT}/tn-node-deployment/lib"
# lib files migrate-node-naming.sh may source (common.sh -> fallback.sh always;
# observability.sh / testnet-addons.env are lazy, bundled defensively).
LIB_FILES=(common.sh fallback.sh observability.sh testnet-addons.env)

# --- options -----------------------------------------------------------------
AUTO_YES=false
DRY_RUN=false
ONLY=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)     AUTO_YES=true; shift ;;
        -n|--dry-run) DRY_RUN=true; shift ;;
        --only)       ONLY="${2:-}"; shift 2 ;;
        -h|--help)    sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# --- pretty print ------------------------------------------------------------
c_g=$'\033[0;32m'; c_r=$'\033[0;31m'; c_y=$'\033[1;33m'; c_b=$'\033[0;34m'; c_0=$'\033[0m'
ok()   { echo "  ${c_g}[OK]${c_0}    $*"; }
err()  { echo "  ${c_r}[FAIL]${c_0}  $*" >&2; }
warn() { echo "  ${c_y}[WARN]${c_0}  $*"; }
info() { echo "  ${c_b}->${c_0}     $*"; }
hdr()  { echo ""; echo "${c_b}==== $* ====${c_0}"; }

confirm() { # confirm "<prompt>" -> 0 if yes. Auto-yes under --yes.
    [[ "$AUTO_YES" == true ]] && return 0
    local a; read -r -p "  ${c_y}?${c_0} $1 [y/N] " a
    [[ "$a" =~ ^[Yy]$ ]]
}

# --- gcloud helpers (mirror tasks/run-on-all.sh: real gcloud + IAP tunnel) ----
NOISE='NumPy|increase the (performance|TCP)|cloud\.google\.com/iap|Updating project ssh metadata|Waiting for SSH key|^WARNING: *$|^$'

tn_ssh() {  # tn_ssh <idx> ; remote script on STDIN -> remote bash. Echoes remote stdout/stderr (de-noised).
    local i="$1"
    gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" --project="${PROJECT_ID}" \
        --tunnel-through-iap --quiet --ssh-flag="-o ConnectTimeout=25" --command='bash -s' 2>&1 \
        | grep -vE "$NOISE"
}

tn_scp() {  # tn_scp <idx> <localfile> <remote-abs-path>
    gcloud compute scp "$2" "${INSTANCE_NAMES[$1]}:$3" --zone="${ZONES[$1]}" --project="${PROJECT_ID}" \
        --tunnel-through-iap --quiet --scp-flag="-o ConnectTimeout=25" 2>&1 \
        | grep -vE "$NOISE" || true
}

# --- remote probes (read-only) ----------------------------------------------
# Echo: STATE legacy=<role|none> unified=<yes|no> rpc_port=<n>
probe_state() {
    tn_ssh "$1" <<'RS'
legacy=none
for r in validator observer; do [ -f "/etc/systemd/system/telcoin-$r.service" ] && legacy="$r"; done
unified=no; [ -f /etc/systemd/system/telcoin.service ] && unified=yes
rp=$(sudo -n grep -hE '^RPC_PORT=' /etc/telcoin/.node-meta /etc/telcoin/validator/.node-meta /etc/telcoin/observer/.node-meta 2>/dev/null | head -1 | cut -d= -f2)
echo "STATE legacy=${legacy} unified=${unified} rpc_port=${rp:-8545}"
RS
}

# Echo: VERIFY active=<state> rpc_port=<n> block=<hex|none> advancing=<yes|no>
# Polls up to ~60s for the block height to advance (a restarted committee validator
# needs a moment to resync + rejoin consensus).
verify_health() {
    tn_ssh "$1" <<'RS'
rp=$(sudo -n grep -hE '^RPC_PORT=' /etc/telcoin/.node-meta 2>/dev/null | head -1 | cut -d= -f2); rp=${rp:-8545}
active=$(systemctl is-active telcoin 2>/dev/null || echo inactive)
rpc(){ curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
  "http://localhost:${rp}" 2>/dev/null | grep -o '0x[0-9a-fA-F]*' | head -1; }
adv=no; last=""
for _ in 1 2 3 4 5 6; do
  b=$(rpc)
  if [ -n "$b" ] && [ -n "$last" ] && [ $((b)) -gt $((last)) ]; then adv=yes; last=$b; break; fi
  [ -n "$b" ] && last=$b
  sleep 10
done
echo "VERIFY active=${active} rpc_port=${rp} block=${last:-none} advancing=${adv}"
RS
}

# --- migration delivery + run ------------------------------------------------
# scp the staged bundle tarball, extract to a temp dir on the node, run it as root
# non-interactively, clean up. Echo: MIGRATE_RC=<rc>  (rc 0 = success).
run_migration() {
    local i="$1" ts; ts="$(date +%s)"
    local remote_tgz="/tmp/tn-mig-${ts}.tgz"
    tn_scp "$i" "$BUNDLE_TGZ" "$remote_tgz"
    # Pass the tarball path as $1 to a remote bash reading the script on stdin. The
    # heredoc is quoted ('RS') so nothing expands locally; only $remote_tgz (in
    # --command) is local. mktemp -> extract -> run as root non-interactively -> clean up.
    gcloud compute ssh "${INSTANCE_NAMES[$i]}" --zone="${ZONES[$i]}" --project="${PROJECT_ID}" \
        --tunnel-through-iap --quiet --ssh-flag="-o ConnectTimeout=25" \
        --command="bash -s -- ${remote_tgz}" 2>&1 <<'RS' | grep -vE "$NOISE"
set -u
tgz="$1"
d="$(mktemp -d)" || { echo "MIGRATE_RC=91"; exit 91; }
tar xzf "$tgz" -C "$d" || { echo "MIGRATE_RC=92"; exit 92; }
sudo -n TN_ASSUME_YES=true bash "$d/migrate-node-naming.sh" --yes
rc=$?
rm -rf "$d" "$tgz"
echo "MIGRATE_RC=${rc}"
RS
}

# --- build the migration bundle once -----------------------------------------
[[ -f "$MIGRATE_SRC" ]] || { err "migrate-node-naming.sh not found at $MIGRATE_SRC"; exit 1; }
command -v gcloud >/dev/null 2>&1 || { err "gcloud not found on PATH"; exit 1; }

STAGE="$(mktemp -d)"; BUNDLE_TGZ="$(mktemp -u).tgz"
trap 'rm -rf "$STAGE" "$BUNDLE_TGZ"' EXIT
mkdir -p "$STAGE/lib"
cp "$MIGRATE_SRC" "$STAGE/migrate-node-naming.sh"
for f in "${LIB_FILES[@]}"; do [[ -f "${LIB_DIR}/${f}" ]] && cp "${LIB_DIR}/${f}" "$STAGE/lib/${f}"; done
tar czf "$BUNDLE_TGZ" -C "$STAGE" .
MIG_VER="$(grep -m1 'readonly SCRIPT_VERSION=' "$MIGRATE_SRC" | cut -d'"' -f2)"

# --- build the node order: observers first (canary/skip), then validators ----
order=()
[[ -n "$ONLY" ]] && {
    found=-1
    for i in "${!INSTANCE_NAMES[@]}"; do
        [[ "$ONLY" == "${NODE_NAMES[$i]}" || "$ONLY" == "${INSTANCE_NAMES[$i]}" ]] && found=$i
    done
    [[ $found -ge 0 ]] || { err "--only '$ONLY' did not match any node (try node1..node5 or an instance name)"; exit 2; }
    order=("$found")
}
if [[ -z "$ONLY" ]]; then
    for i in "${!NODE_ROLES[@]}"; do [[ "${NODE_ROLES[$i]}" == "observer" ]] && order+=("$i"); done
    for i in "${!NODE_ROLES[@]}"; do [[ "${NODE_ROLES[$i]}" != "observer" ]] && order+=("$i"); done
fi

# =============================================================================
# PHASE 0 -- read-only fleet pre-check (touches nothing)
# =============================================================================
hdr "Telcoin devnet -- unified-naming migration (migrate-node-naming.sh v${MIG_VER})"
MODE=INTERACTIVE; [[ "$AUTO_YES" == true ]] && MODE=AUTO; [[ "$DRY_RUN" == true ]] && MODE=DRY-RUN
info "Project: ${PROJECT_ID}   Mode: ${MODE}"
info "Order (staggered, one at a time): $(for i in "${order[@]}"; do printf '%s ' "${NODE_NAMES[$i]}"; done)"
echo ""
need_migrate=()
printf "  %-7s %-20s %-10s %-22s\n" "NODE" "INSTANCE" "ROLE" "STATE"
printf "  %-7s %-20s %-10s %-22s\n" "----" "--------" "----" "-----"
for i in "${order[@]}"; do
    line="$(probe_state "$i" | grep '^STATE ' | head -1 || true)"
    legacy="$(sed -n 's/.*legacy=\([^ ]*\).*/\1/p' <<<"$line")"; legacy="${legacy:-?}"
    unified="$(sed -n 's/.*unified=\([^ ]*\).*/\1/p' <<<"$line")"; unified="${unified:-?}"
    if [[ "$legacy" == none && "$unified" == yes ]]; then
        disp="${c_g}already migrated${c_0}"
    elif [[ "$legacy" != none && "$legacy" != "?" ]]; then
        disp="${c_y}LEGACY telcoin-${legacy} -> migrate${c_0}"; need_migrate+=("$i")
    elif [[ "$legacy" == "?" ]]; then
        disp="${c_r}unreachable / probe failed${c_0}"
    else
        disp="${c_r}no telcoin unit found -- skip${c_0}"
    fi
    printf "  %-7s %-20s %-10s %b\n" "${NODE_NAMES[$i]}" "${INSTANCE_NAMES[$i]}" "${NODE_ROLES[$i]}" "$disp"
done
echo ""
info "${#need_migrate[@]} node(s) need migration; the rest are skipped untouched."

if [[ "$DRY_RUN" == true ]]; then
    ok "Dry run complete -- nothing was changed."
    exit 0
fi
if [[ ${#need_migrate[@]} -eq 0 ]]; then
    ok "Nothing to migrate. Fleet already unified."
    exit 0
fi
if ! confirm "Proceed with the staggered migration of ${#need_migrate[@]} node(s)?"; then
    info "Aborted by operator -- no changes made."
    exit 0
fi

# =============================================================================
# PHASE 1 -- staggered rollout
# =============================================================================
migrated=(); skipped=()
for i in "${order[@]}"; do
    name="${NODE_NAMES[$i]}"; inst="${INSTANCE_NAMES[$i]}"; role="${NODE_ROLES[$i]}"
    hdr "Node ${name} (${inst}, ${role})"

    # Re-probe live (state may have changed since Phase 0; this is the "check before
    # stopping" gate -- an already-migrated node is never stopped).
    line="$(probe_state "$i" | grep '^STATE ' | head -1 || true)"
    legacy="$(sed -n 's/.*legacy=\([^ ]*\).*/\1/p' <<<"$line")"; legacy="${legacy:-?}"
    unified="$(sed -n 's/.*unified=\([^ ]*\).*/\1/p' <<<"$line")"; unified="${unified:-?}"

    if [[ "$legacy" == none && "$unified" == yes ]]; then
        ok "Already migrated (telcoin.service, no legacy unit) -- SKIP, not stopping it."
        skipped+=("$name"); continue
    fi
    if [[ "$legacy" == "?" ]]; then
        err "Could not probe ${name} (SSH/sudo failed). ABORTING rollout."; exit 1
    fi
    if [[ "$legacy" == none ]]; then
        warn "No telcoin-{observer,validator}.service and no telcoin.service -- non-standard. SKIP."
        skipped+=("$name"); continue
    fi

    info "Legacy telcoin-${legacy} detected. Migration will: stop -> relocate dirs -> rewrite"
    info "unit+wrapper (strip --observer) -> open P2P 49590/49594 -> start + verify RPC."
    if [[ "$role" == "validator" ]]; then
        warn "This is a COMMITTEE validator -- brief downtime. The other 3 keep quorum (3/4)."
    fi
    if ! confirm "Migrate ${name} now?"; then
        info "Skipped ${name} by operator choice."; skipped+=("$name"); continue
    fi

    out="$(run_migration "$i")"
    echo "$out" | grep -vE '^MIGRATE_RC=' | sed 's/^/    /'
    rc="$(grep -oE 'MIGRATE_RC=[0-9]+' <<<"$out" | tail -1 | cut -d= -f2)"; rc="${rc:-1}"
    if [[ "$rc" != "0" ]]; then
        err "Migration FAILED on ${name} (rc=${rc}). It self-rolled-back to the legacy"
        err "service (verify with: bash tasks/verify-all.sh / journalctl -u telcoin-${legacy})."
        err "ABORTING the rollout -- no further nodes touched."
        exit 1
    fi
    ok "migrate-node-naming.sh completed on ${name}."

    # Health gate before moving on -- keeps the committee at >=3/4 by ensuring this
    # node is back before the next one stops.
    info "Verifying ${name} is active and following consensus (up to ~60s)..."
    v="$(verify_health "$i" | grep '^VERIFY ' | head -1 || true)"
    active="$(sed -n 's/.*active=\([^ ]*\).*/\1/p' <<<"$v")"
    advancing="$(sed -n 's/.*advancing=\([^ ]*\).*/\1/p' <<<"$v")"
    block="$(sed -n 's/.*block=\([^ ]*\).*/\1/p' <<<"$v")"
    info "  ${v#VERIFY }"
    if [[ "$active" != "active" ]]; then
        err "${name}: telcoin.service is '${active:-unknown}' after migration. ABORTING rollout."
        exit 1
    fi
    if [[ "$advancing" != "yes" ]]; then
        warn "${name}: service active + RPC reachable, but block height not advancing yet (${block})."
        warn "It may still be resyncing. Do NOT migrate the next node until this one catches up."
        if [[ "$AUTO_YES" == true ]]; then
            warn "Auto mode: continuing, but watch this node (journalctl -u telcoin -f)."
        elif ! confirm "Proceed to the next node anyway?"; then
            err "Halting rollout so you can inspect ${name}."; exit 1
        fi
    else
        ok "${name} migrated and advancing (block ${block})."
    fi
    migrated+=("$name")

    # Staggered gate: pause before the next node (no prompt after the last one).
    last_idx="${order[$(( ${#order[@]} - 1 ))]}"
    if [[ "$i" != "$last_idx" ]]; then
        confirm "Continue to the next node?" || { info "Stopping here at your request."; break; }
    fi
done

# =============================================================================
# SUMMARY
# =============================================================================
hdr "Migration summary"
ok "Migrated (${#migrated[@]}): ${migrated[*]:-none}"
info "Skipped  (${#skipped[@]}): ${skipped[*]:-none}"
echo ""
info "Verify the whole fleet:  bash tasks/verify-all.sh"
info "Per-node logs:           gcloud compute ssh <instance> --tunnel-through-iap --command 'journalctl -u telcoin -n 50 --no-pager'"
info "Backups (.bak.<ts>) are left on each migrated node under /etc/systemd/system and /opt/telcoin -- delete once confident."
