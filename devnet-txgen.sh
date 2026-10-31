#!/usr/bin/env bash
#
# devnet-txgen.sh — deploy runbook Step 16: stand up tn-transaction-generator as a
# PERMANENT, continuous transaction source for devnet.
#
# An idle devnet produces no blocks: eth_blockNumber sits flat and every dashboard,
# indexer and RPC consumer looks broken in the same way a wedged chain does. This VM
# runs the generator in `run` mode (never `blast`), which drives a 100ms tick drawing a
# Poisson count with mean lambda*tick — so lambda is literally tx/sec. The shipped devnet
# tempo is a Markov walk over quiet(0.2)/normal(2.0)/burst(15.0) tx/s with 0.80
# self-transition on normal, plus a 30 tx/s surge fired 30s before each epoch boundary.
# With no --duration, `run` never self-terminates; it exits only on SIGTERM, draining for
# 30s (which is why the unit sets TimeoutStopSec=30).
#
# What this script does, all idempotent:
#   1. preflight        local tooling + the generator's minted secrets + the address book
#   2. age key          ensure the age identity exists, mirror it to Secret Manager
#   3. encrypt          sops-encrypt master.key + children.seed, VERIFY the round trip
#   4. VM               create txgen-devnet (skip if present) + Ops Agent via startup script
#   5. build            ship the source tree, build the static musl binary ON the VM
#   6. install          txgen user, /opt layout, binary, config, secrets, address book
#   7. unit             the repo's hardened unit + the three lines it is missing
#   8. verify           sops round trip AS the txgen user, then --dry-run
#   9. start            enable --now, assert active + the startup log lines
#  10. alloy            journal -> Loki and 127.0.0.1:9090 -> Prometheus, same fleet plumbing
#
# ---------------------------------------------------------------------------------
# THREE DELIBERATE DEVIATIONS from the original plan, each forced by something we hit:
#
#  a) SECRET FILENAMES are secrets/master.sops and secrets/children.sops, NOT *.sops.yaml.
#     The recipe in the generator's docs/deployment.md:60-73 is broken: sops picks its
#     store from the FILE EXTENSION, so `sops --encrypt secrets/master.key >
#     secrets/master.sops.yaml` writes a binary-store envelope that `sops --decrypt` then
#     re-serializes through the YAML store, yielding "data: 0x<key>" instead of the bare
#     key. The generator does raw.trim().trim_start_matches("0x") then hex-decodes
#     (src/wallets/mod.rs:206-211), so that fails at startup; the mnemonic would likewise
#     come back as 25 words and be rejected. Verified both ways locally. A neutral
#     extension keeps the binary store on both ends and round-trips byte-exactly.
#
#  b) THE BINARY IS BUILT ON THE VM. The generator repo is private, so the VM cannot clone
#     it; and the only other host here is arm64 macOS, which cannot produce linux/amd64
#     without emulating a fat-LTO Rust build. We ship a source tarball over IAP instead.
#     vendor/ is excluded: the sol! bindings are written inline (src/bindings.rs), so the
#     75MB forge-lib tree is a RUNTIME dependency (deployments-devnet.json) only.
#
#  c) MACHINE TYPE is e2-medium, not e2-small. The release profile is lto="fat" +
#     codegen-units=1 and the dependency graph builds aws-lc-sys through cmake; 2GB would
#     OOM. The service itself needs ~50MB (MemoryMax=256M is left as shipped).
# ---------------------------------------------------------------------------------
#
# Reaches the VM only over IAP. Needs no new firewall rule: the metrics endpoint binds
# loopback, tn-devnet has no default-allow-ssh, and wg-allow-iap-ssh already admits
# 35.235.240.0/20. The VM carries NO `validator` tag, so devnet-deny-consensus-egress
# (which targets that tag) does not apply and egress to the RPC works on the implied allow.
#
# Usage:
#   ./devnet-txgen.sh                 # DRY RUN: preflight + plan, changes nothing
#   ./devnet-txgen.sh --yes           # full provision
#   ./devnet-txgen.sh --yes --from 6  # resume at a step (1..10)
#   ./devnet-txgen.sh --yes --only 9

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${REPO_DIR}/devnet-lib.sh"

# --- tunables ------------------------------------------------------------------
TXGEN_INSTANCE="${TXGEN_INSTANCE:-txgen-devnet}"
TXGEN_ZONE="${TXGEN_ZONE:-us-west2-a}"
TXGEN_MACHINE_TYPE="${TXGEN_MACHINE_TYPE:-e2-medium}"   # see deviation (c)
TXGEN_DISK_SIZE="${TXGEN_DISK_SIZE:-20}"
TXGEN_IMAGE="${TXGEN_IMAGE:-projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64}"
TXGEN_SRC_DIR="${TXGEN_SRC_DIR:-$(cd "${REPO_DIR}/.." && pwd)/tn-transaction-generator}"
TXGEN_CONTRACTS_DIR="${TXGEN_CONTRACTS_DIR:-$(cd "${REPO_DIR}/.." && pwd)/tn-contracts-devnet-relaunch}"
AGE_KEY_FILE="${AGE_KEY_FILE:-${REPO_DIR}/.secrets/txgen-age-key.txt}"
AGE_KEY_SECRET="${AGE_KEY_SECRET:-devnet-txgen-age-key}"
TXGEN_USER="txgen"
TXGEN_HOME="/opt/tn-transaction-generator"
TXGEN_ETC="/etc/tn-transaction-generator"
TXGEN_UNIT="tn-transaction-generator.service"
ALLOY_VERSION="${ALLOY_VERSION:-1.5.1}"
LAST_STEP=10

# --- args ----------------------------------------------------------------------
CONFIRM=0; FROM=1; ONLY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --yes) CONFIRM=1 ;;
        --from) FROM="${2:?--from needs a step number}"; shift ;;
        --from=*) FROM="${1#*=}" ;;
        --only) ONLY="${2:?--only needs a step number}"; shift ;;
        --only=*) ONLY="${1#*=}" ;;
        *) echo "❌ unknown argument '$1' (supported: --yes, --from <n>, --only <n>)" >&2; exit 1 ;;
    esac
    shift
done
[ "${FORCE:-}" = "true" ] && CONFIRM=1
is_step() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; [ "$1" -ge 1 ] && [ "$1" -le "${LAST_STEP}" ]; }
is_step "${FROM}" || { echo "❌ --from must be 1..${LAST_STEP}" >&2; exit 1; }
[ -n "${ONLY}" ] && { is_step "${ONLY}" || { echo "❌ --only must be 1..${LAST_STEP}" >&2; exit 1; }; }

# Remote helpers bound to this one VM (devnet-lib.sh's helpers take inst+zone).
tx_ssh()   { tn_iap_ssh "${TXGEN_INSTANCE}" "${TXGEN_ZONE}" "$1"; }
tx_stdin() { tn_iap_ssh_stdin "${TXGEN_INSTANCE}" "${TXGEN_ZONE}"; }
tx_scp()   { tn_iap_scp "$1" "${TXGEN_INSTANCE}" "${TXGEN_ZONE}" "$2"; }

STAGE="$(mktemp -d)"
trap 'rm -rf "${STAGE}"' EXIT

# =============================== steps =========================================

step_1() {
    echo ">>> Step 1: preflight"
    for bin in sops age age-keygen gcloud tar jq; do
        command -v "${bin}" >/dev/null 2>&1 || { echo "❌ '${bin}' not on PATH" >&2; return 1; }
    done
    echo "    ✓ local tooling"

    [ -d "${TXGEN_SRC_DIR}" ] || { echo "❌ generator source not found at ${TXGEN_SRC_DIR}" >&2; return 1; }
    for f in Cargo.toml config.devnet.toml systemd/"${TXGEN_UNIT}" secrets/master.key secrets/children.seed; do
        [ -f "${TXGEN_SRC_DIR}/${f}" ] || { echo "❌ missing ${TXGEN_SRC_DIR}/${f}" >&2; return 1; }
    done
    echo "    ✓ generator source + minted secrets present"

    # Shape-check the minted secrets before we encrypt anything. A malformed master key or
    # a short mnemonic is far cheaper to catch here than after the VM is built.
    grep -qE '^0x[0-9a-f]{64}$' "${TXGEN_SRC_DIR}/secrets/master.key" \
        || { echo "❌ secrets/master.key is not a bare 0x<64 hex> key" >&2; return 1; }
    local words; words="$(wc -w < "${TXGEN_SRC_DIR}/secrets/children.seed" | tr -d ' ')"
    case "${words}" in 12|15|18|21|24) : ;; *) echo "❌ children.seed has ${words} words (need 12/15/18/21/24)" >&2; return 1 ;; esac
    echo "    ✓ master.key is 0x<64 hex>; children.seed is ${words} words"

    local book="${TXGEN_CONTRACTS_DIR}/deployments/deployments-devnet.json"
    [ -f "${book}" ] || { echo "❌ address book not found at ${book}" >&2; return 1; }
    # These are exactly the keys src/deployments.rs refuses to start without.
    local missing=()
    for k in .ConsensusRegistry .Issuance .StakeManager .StablecoinManager .WTEL \
             .uniswapV2.UniswapV2Factory .uniswapV2.UniswapV2Router02 \
             .uniswapV3.UniswapV3Factory .uniswapV3.SwapRouter02 \
             .uniswapV4.V4SwapHelper .uniswapV4.V4Quoter .eXYZs.eUSD .eXYZs.eEUR; do
        local v; v="$(jq -r "${k} // empty" "${book}")"
        [ -n "${v}" ] && [ "${v}" != "null" ] || missing+=("${k}")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        echo "❌ address book is missing mandatory keys: ${missing[*]}" >&2
        echo "   Run ./devnet-contracts.sh --yes (Step 15) first." >&2
        return 1
    fi
    echo "    ✓ address book has every mandatory key ($(jq -r '.eXYZs | length' "${book}") eXYZs)"
}

step_2() {
    echo ">>> Step 2: age identity"
    mkdir -p "$(dirname "${AGE_KEY_FILE}")"
    if [ -f "${AGE_KEY_FILE}" ]; then
        echo "    ✓ age key already present at ${AGE_KEY_FILE}"
    else
        ( umask 077; age-keygen -o "${AGE_KEY_FILE}" 2>/dev/null )
        echo "    ✓ generated ${AGE_KEY_FILE}"
    fi
    chmod 600 "${AGE_KEY_FILE}"
    AGE_PUB="$(grep 'public key:' "${AGE_KEY_FILE}" | sed 's/.*public key: //')"
    [ -n "${AGE_PUB}" ] || { echo "❌ could not read the age public key" >&2; return 1; }
    echo "    public key: ${AGE_PUB}"

    # Mirror the identity into Secret Manager. Losing this key means the ciphertext on the
    # VM is undecryptable and the service can never restart — the secret is the backstop.
    if gcloud secrets describe "${AGE_KEY_SECRET}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        echo "    ✓ Secret Manager already holds ${AGE_KEY_SECRET} (not overwritten)"
    else
        gcloud secrets create "${AGE_KEY_SECRET}" --project="${PROJECT_ID}" \
            --replication-policy=automatic --data-file="${AGE_KEY_FILE}" >/dev/null
        echo "    ✓ mirrored the age identity to Secret Manager as ${AGE_KEY_SECRET}"
    fi
}

step_3() {
    echo ">>> Step 3: sops-encrypt the wallet secrets (+ verify the round trip)"
    AGE_PUB="${AGE_PUB:-$(grep 'public key:' "${AGE_KEY_FILE}" | sed 's/.*public key: //')}"

    # NOTE the extensions: .sops, never .sops.yaml — see deviation (a) in the header.
    sops --age "${AGE_PUB}" --encrypt "${TXGEN_SRC_DIR}/secrets/master.key"    > "${STAGE}/master.sops"
    sops --age "${AGE_PUB}" --encrypt "${TXGEN_SRC_DIR}/secrets/children.seed" > "${STAGE}/children.sops"
    chmod 600 "${STAGE}/master.sops" "${STAGE}/children.sops"
    echo "    ✓ encrypted to master.sops + children.sops"

    # Prove the decrypt yields EXACTLY the plaintext. The generator's --dry-run does not
    # touch wallets (src/main.rs:180-183), so this is the only pre-start check of the
    # secret path that exists.
    local out
    out="$(SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}" sops --decrypt "${STAGE}/master.sops")"
    [ "${out}" = "$(cat "${TXGEN_SRC_DIR}/secrets/master.key")" ] \
        || { echo "❌ master round trip is NOT byte-exact — refusing to ship it" >&2; return 1; }
    out="$(SOPS_AGE_KEY_FILE="${AGE_KEY_FILE}" sops --decrypt "${STAGE}/children.sops")"
    [ "${out}" = "$(cat "${TXGEN_SRC_DIR}/secrets/children.seed")" ] \
        || { echo "❌ children round trip is NOT byte-exact — refusing to ship it" >&2; return 1; }
    echo "    ✓ both decrypt byte-exactly (values never printed)"
}

step_4() {
    echo ">>> Step 4: VM ${TXGEN_INSTANCE} (${TXGEN_ZONE}, ${TXGEN_MACHINE_TYPE})"
    if gcloud compute instances describe "${TXGEN_INSTANCE}" --zone="${TXGEN_ZONE}" \
           --project="${PROJECT_ID}" --format='value(name)' >/dev/null 2>&1; then
        echo "    ✓ already exists — reusing"
        return 0
    fi

    # Startup script: Ops Agent (the fleet-wide convention -- every GCP VM installs it and
    # purges the legacy Stackdriver agent) plus the build/runtime packages. The Ops Agent
    # function is MIRRORED from common/ops-agent-install.sh because a GCP startup script
    # runs before any repo exists on the box and so cannot source it; keep the two in sync.
    local startup="${STAGE}/startup-txgen.sh"
    cat > "${startup}" <<'STARTUP'
#!/bin/bash
set -u
exec > >(tee -a /var/log/txgen-startup.log) 2>&1
echo "=== txgen-devnet startup $(date -Is) ==="

install_ops_agent() {
    local SUDO="" pkg tmp
    [ "$(id -u)" -ne 0 ] && SUDO=sudo
    for pkg in stackdriver-agent google-fluentd; do
        if dpkg -s "${pkg}" >/dev/null 2>&1; then
            echo "[ops-agent] removing legacy ${pkg}"
            $SUDO apt-get remove -y "${pkg}" || true
        fi
    done
    if dpkg -s google-cloud-ops-agent >/dev/null 2>&1; then
        echo "[ops-agent] google-cloud-ops-agent already installed"
    else
        echo "[ops-agent] installing google-cloud-ops-agent"
        tmp="$(mktemp -d 2>/dev/null)" || return 0
        if curl -fsSL -o "${tmp}/add-ops-agent-repo.sh" \
                https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh; then
            $SUDO bash "${tmp}/add-ops-agent-repo.sh" --also-install || true
        else
            echo "[ops-agent] WARNING: installer download failed (skipping; non-fatal)"
        fi
        rm -rf "${tmp}" || true
    fi
}

export DEBIAN_FRONTEND=noninteractive
apt-get update -y || true
# Build deps for `cargo build --release --target x86_64-unknown-linux-musl`:
# musl-tools gives musl-gcc; cmake + clang + build-essential are what aws-lc-sys needs.
apt-get install -y --no-install-recommends \
    build-essential pkg-config cmake clang musl-tools ca-certificates curl git jq gnupg || true

install_ops_agent

echo "=== txgen-startup.sh complete $(date -Is) ==="
STARTUP

    gcloud compute instances create "${TXGEN_INSTANCE}" \
        --project="${PROJECT_ID}" \
        --zone="${TXGEN_ZONE}" \
        --machine-type="${TXGEN_MACHINE_TYPE}" \
        --image="${TXGEN_IMAGE}" \
        --boot-disk-size="${TXGEN_DISK_SIZE}GB" \
        --boot-disk-type=pd-balanced \
        --boot-disk-device-name="${TXGEN_INSTANCE}" \
        --scopes=https://www.googleapis.com/auth/cloud-platform \
        --metadata-from-file=startup-script="${startup}" \
        --labels=role=txgen,chain=devnet \
        --no-shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
        --reservation-affinity=any
    # NOTE: no --no-address. tn-devnet has no Cloud NAT, so an ephemeral external IP is
    # what gives this VM egress to https://rpc.devnet.telcoin.network. It carries no
    # ingress-bearing network tag, so nothing public can reach it.
    echo "    ✓ created"
}

step_5() {
    echo ">>> Step 5: ship the source and build the musl binary ON the VM"
    echo "    waiting for SSH over IAP + the startup script to finish..."
    local waited=0
    until tx_ssh 'test -f /var/log/txgen-startup.log && grep -q "txgen-startup.sh complete" /var/log/txgen-startup.log' >/dev/null 2>&1; do
        [ "${waited}" -ge 600 ] && { echo "❌ startup script did not finish within 600s" >&2; \
            echo "   inspect: gcloud compute instances get-serial-port-output ${TXGEN_INSTANCE} --zone=${TXGEN_ZONE} --project=${PROJECT_ID}" >&2; return 1; }
        sleep 20; waited=$((waited + 20))
        echo "      …not ready yet (${waited}s/600s)"
    done
    echo "    ✓ VM ready (build deps + Ops Agent installed)"

    # Tarball the working tree. vendor/ is excluded deliberately: the sol! bindings are
    # inline, so the forge-lib tree is not a build input -- only deployments-devnet.json is
    # needed, and that ships separately in Step 6.
    echo "    packing source (excluding target/, .git/, vendor/, secrets/)"
    tar -C "${TXGEN_SRC_DIR}" \
        --exclude='./target' --exclude='./.git' --exclude='./vendor' \
        --exclude='./secrets/master.key' --exclude='./secrets/children.seed' \
        --exclude='./logs' \
        -czf "${STAGE}/txgen-src.tgz" . 2>/dev/null
    echo "    source tarball: $(du -h "${STAGE}/txgen-src.tgz" | cut -f1)"
    tx_scp "${STAGE}/txgen-src.tgz" "/tmp/txgen-src.tgz"

    echo "    building (fat LTO + aws-lc-sys — expect 15-30 min on ${TXGEN_MACHINE_TYPE})"
    tx_stdin <<'BUILD'
set -euo pipefail
rm -rf /opt/txgen-build && mkdir -p /opt/txgen-build
tar -xzf /tmp/txgen-src.tgz -C /opt/txgen-build
cd /opt/txgen-build

# rustup honours rust-toolchain.toml, which pins 1.94.1 and declares the musl target,
# so the toolchain and target std both land without extra flags.
if ! command -v cargo >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --no-modify-path --default-toolchain none
fi
export PATH="${HOME}/.cargo/bin:${PATH}"
rustup show >/dev/null
rustup target add x86_64-unknown-linux-musl

CC_x86_64_unknown_linux_musl=musl-gcc \
cargo build --release --target x86_64-unknown-linux-musl

BIN=target/x86_64-unknown-linux-musl/release/tn-transaction-generator
test -x "$BIN"
file "$BIN" || true
echo "built: $(ls -la "$BIN")"
BUILD
    echo "    ✓ binary built"
}

step_6() {
    echo ">>> Step 6: install user, layout, binary, config, secrets, address book"

    # config.toml == config.devnet.toml with ONLY the four [wallets] source/path lines
    # changed. Everything else (tempo, epoch surge, metrics, tx-type weights) stays verbatim.
    sed -e 's|^master_source = "plain_file"|master_source = "sops_file"|' \
        -e 's|^master_path = "secrets/master.key"|master_path = "secrets/master.sops"|' \
        -e 's|^children_seed_source = "plain_file"|children_seed_source = "sops_file"|' \
        -e 's|^children_seed_path = "secrets/children.seed"|children_seed_path = "secrets/children.sops"|' \
        "${TXGEN_SRC_DIR}/config.devnet.toml" > "${STAGE}/config.toml"
    grep -q 'master_source = "sops_file"'        "${STAGE}/config.toml" || { echo "❌ config rewrite failed (master_source)" >&2; return 1; }
    grep -q 'master_path = "secrets/master.sops"' "${STAGE}/config.toml" || { echo "❌ config rewrite failed (master_path)" >&2; return 1; }
    grep -q 'children_seed_source = "sops_file"' "${STAGE}/config.toml" || { echo "❌ config rewrite failed (children_seed_source)" >&2; return 1; }
    grep -q 'children_seed_path = "secrets/children.sops"' "${STAGE}/config.toml" || { echo "❌ config rewrite failed (children_seed_path)" >&2; return 1; }
    echo "    ✓ config.toml rendered (only the [wallets] secret source differs from config.devnet.toml)"

    cp "${TXGEN_CONTRACTS_DIR}/deployments/deployments-devnet.json" "${STAGE}/deployments-devnet.json"

    for f in config.toml deployments-devnet.json master.sops children.sops; do
        tx_scp "${STAGE}/${f}" "/tmp/${f}"
    done
    tx_scp "${AGE_KEY_FILE}" "/tmp/age-key.txt"

    TXGEN_USER="${TXGEN_USER}" TXGEN_HOME="${TXGEN_HOME}" TXGEN_ETC="${TXGEN_ETC}" \
    tx_stdin <<'INSTALL'
set -euo pipefail
TXGEN_USER=txgen
TXGEN_HOME=/opt/tn-transaction-generator
TXGEN_ETC=/etc/tn-transaction-generator

# sops is a RUNTIME dependency: the generator shells out to `sops --decrypt`
# (src/wallets/secrets.rs:11-14) with the unit's inherited PATH.
if ! command -v sops >/dev/null 2>&1; then
    SOPS_VER=3.9.4
    curl -fsSL -o /tmp/sops.deb \
        "https://github.com/getsops/sops/releases/download/v${SOPS_VER}/sops_${SOPS_VER}_amd64.deb"
    dpkg -i /tmp/sops.deb
    rm -f /tmp/sops.deb
fi
command -v sops >/dev/null || { echo "sops install failed"; exit 1; }
echo "sops: $(command -v sops) $(sops --version 2>/dev/null | head -1)"

id -u "${TXGEN_USER}" >/dev/null 2>&1 || \
    useradd --system --shell /usr/sbin/nologin --home-dir "${TXGEN_HOME}" "${TXGEN_USER}"

mkdir -p "${TXGEN_HOME}"/{state,secrets,logs} \
         "${TXGEN_HOME}/vendor/tn-contracts/deployments" \
         "${TXGEN_ETC}"

install -m 0755 /opt/txgen-build/target/x86_64-unknown-linux-musl/release/tn-transaction-generator \
        /usr/local/bin/tn-transaction-generator

install -m 0644 /tmp/config.toml "${TXGEN_HOME}/config.toml"
# deployments_path() resolves RELATIVE to cwd, and the unit sets
# WorkingDirectory=${TXGEN_HOME} -- so this exact path is load-bearing.
install -m 0644 /tmp/deployments-devnet.json \
        "${TXGEN_HOME}/vendor/tn-contracts/deployments/deployments-devnet.json"
install -m 0600 /tmp/master.sops   "${TXGEN_HOME}/secrets/master.sops"
install -m 0600 /tmp/children.sops "${TXGEN_HOME}/secrets/children.sops"
install -m 0400 /tmp/age-key.txt   "${TXGEN_ETC}/age-key.txt"

chown -R "${TXGEN_USER}:${TXGEN_USER}" "${TXGEN_HOME}"
chown "${TXGEN_USER}:${TXGEN_USER}" "${TXGEN_ETC}/age-key.txt"
chmod 600 "${TXGEN_HOME}/secrets"/*
rm -f /tmp/config.toml /tmp/deployments-devnet.json /tmp/master.sops /tmp/children.sops /tmp/age-key.txt

echo "--- layout ---"
ls -la "${TXGEN_HOME}" "${TXGEN_HOME}/secrets" "${TXGEN_ETC}"
/usr/local/bin/tn-transaction-generator --version
INSTALL
    echo "    ✓ installed"
}

step_7() {
    echo ">>> Step 7: systemd unit (+ the three lines the shipped unit is missing)"
    # Start from the repo's own hardened unit so we inherit ProtectSystem=strict,
    # MemoryMax=256M, CPUQuota=50%, TimeoutStopSec=30 etc. verbatim, then add:
    #   SOPS_AGE_KEY_FILE  — sops needs the identity; the shipped unit only has a comment
    #   TXGEN_NO_FILE_LOG  — ProtectSystem=strict + ReadWritePaths=.../state makes the
    #                        default logs/txgen-<ts>.log unwritable; journald has stdout
    #   Restart=always     — was on-failure; a clean exit 0 would otherwise leave the
    #                        service down, and this one is meant to live forever
    # StartLimitBurst=0 disables the restart rate limiter, so a transient RPC outage at
    # boot cannot permanently park the unit in failed state.
    cp "${TXGEN_SRC_DIR}/systemd/${TXGEN_UNIT}" "${STAGE}/${TXGEN_UNIT}"
    python3 - "${STAGE}/${TXGEN_UNIT}" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
assert "Restart=on-failure" in s, "unexpected unit: no Restart=on-failure"
s = s.replace("Restart=on-failure", "Restart=always")
marker = "Environment=LOG_FORMAT=json\n"
assert marker in s, "unexpected unit: no LOG_FORMAT line"
s = s.replace(marker, marker +
    "Environment=SOPS_AGE_KEY_FILE=/etc/tn-transaction-generator/age-key.txt\n"
    "Environment=TXGEN_NO_FILE_LOG=1\n")
s = s.replace("[Install]", "StartLimitIntervalSec=0\n\n[Install]")
open(p, "w").write(s)
print("patched unit:")
for line in s.splitlines():
    if line.startswith(("Restart", "Environment=SOPS", "Environment=TXGEN", "StartLimit")):
        print("   ", line)
PY
    tx_scp "${STAGE}/${TXGEN_UNIT}" "/tmp/${TXGEN_UNIT}"
    tx_stdin <<'UNIT'
set -euo pipefail
install -m 0644 /tmp/tn-transaction-generator.service /etc/systemd/system/tn-transaction-generator.service
rm -f /tmp/tn-transaction-generator.service
systemctl daemon-reload
systemd-analyze verify tn-transaction-generator.service 2>&1 | head -5 || true
echo "unit installed"
UNIT
    echo "    ✓ unit installed"
}

step_8() {
    echo ">>> Step 8: verify the secret path AS the txgen user, then --dry-run"
    # --dry-run validates config + address book and exits BEFORE touching wallets or RPC
    # (src/main.rs:180-183), so it can never prove sops works. Check that separately, as
    # the service user, through the same SOPS_AGE_KEY_FILE the unit will set.
    tx_stdin <<'VERIFY'
set -euo pipefail
cd /opt/tn-transaction-generator

echo "--- sops decrypt as txgen (shape only; values never printed) ---"
m="$(sudo -u txgen env SOPS_AGE_KEY_FILE=/etc/tn-transaction-generator/age-key.txt \
        sops --decrypt secrets/master.sops)"
echo "$m" | grep -qE '^0x[0-9a-f]{64}$' \
    && echo "  ✓ master decrypts to a bare 0x<64 hex> key" \
    || { echo "  ❌ master decrypt has the WRONG SHAPE (got ${#m} chars starting '${m:0:6}')"; exit 1; }

c="$(sudo -u txgen env SOPS_AGE_KEY_FILE=/etc/tn-transaction-generator/age-key.txt \
        sops --decrypt secrets/children.sops)"
w="$(echo "$c" | wc -w | tr -d ' ')"
case "$w" in 12|15|18|21|24) echo "  ✓ children seed decrypts to $w words" ;;
             *) echo "  ❌ children seed decrypted to $w words"; exit 1 ;; esac
unset m c

echo "--- --dry-run (config + address book) ---"
sudo -u txgen /usr/local/bin/tn-transaction-generator \
    --config /opt/tn-transaction-generator/config.toml --dry-run 2>&1 | tail -20
VERIFY
    echo "    ✓ secret path and config validated"
}

step_9() {
    echo ">>> Step 9: enable + start, then assert it is really running"
    tx_ssh "sudo systemctl enable --now ${TXGEN_UNIT}" >/dev/null
    echo "    waiting ~45s for the startup sequence..."
    sleep 45
    # Do not trust the enable's own exit code. Assert on the unit state AND on the log
    # lines the generator emits in order (docs/deployment.md:208).
    tx_stdin <<'CHECK'
set -uo pipefail
state="$(systemctl is-active tn-transaction-generator.service || true)"
echo "is-active: ${state}"
echo "--- recent journal ---"
journalctl -u tn-transaction-generator.service --no-pager -n 40 --output=cat | tail -40
echo "--- startup markers ---"
for m in "deployments loaded" "rpc client ready" "master wallet loaded" "child wallets derived" "wallets ready"; do
    if journalctl -u tn-transaction-generator.service --no-pager --output=cat | grep -q "$m"; then
        echo "  ✓ $m"
    else
        echo "  ❌ MISSING: $m"
    fi
done
[ "${state}" = "active" ] || exit 1
CHECK
    echo "    ✓ service active with the expected startup markers"
}

step_10() {
    echo ">>> Step 10: Alloy — journal -> Loki, 127.0.0.1:9090 -> Prometheus"
    echo "    fetching the obs ingest token (${OBS_SECRET_NAME}) — value is NEVER printed"
    local token; token="$(tn_secret "${OBS_SECRET_NAME}")"
    [ -n "${token}" ] || { echo "❌ obs ingest token is empty" >&2; return 1; }

    # Mirrors the fleet's label schema (chain/node) so txgen lands in the same Grafana
    # dashboards and variables as the nodes. Metrics come from the generator's own
    # Prometheus exporter on loopback (src/metrics_server.rs:19-22).
    cat > "${STAGE}/config.alloy" <<'ALLOY'
// txgen-devnet Alloy config — logs from journald, metrics from the generator's
// loopback Prometheus endpoint. Identity + credentials come from /etc/default/alloy.

loki.source.journal "txgen" {
	forward_to    = [loki.process.txgen.receiver]
	relabel_rules = loki.relabel.txgen.rules
	labels        = {
		job     = "txgen",
		chain   = sys.env("TN_CHAIN"),
		service = "txgen",
		node    = sys.env("TN_NODE"),
	}
}

loki.relabel "txgen" {
	forward_to = []

	rule {
		source_labels = ["__journal__systemd_unit"]
		target_label  = "unit"
	}
}

loki.process "txgen" {
	forward_to = [loki.write.central.receiver]

	// The unit sets LOG_FORMAT=json, so the generator's own lines parse directly.
	// Lines from other units simply fail the stage and pass through unchanged.
	stage.json {
		expressions = {
			level     = "level",
			timestamp = "timestamp",
		}
	}

	stage.labels {
		values = {
			level = "",
		}
	}

	stage.timestamp {
		source = "timestamp"
		format = "RFC3339Nano"
	}
}

loki.write "central" {
	endpoint {
		url          = sys.env("OBS_PUSH_URL")
		bearer_token = sys.env("OBS_INGEST_TOKEN")
	}
}

prometheus.scrape "txgen" {
	targets = [{
		__address__ = sys.env("TXGEN_METRICS_ADDR"),
		instance    = sys.env("TN_NODE"),
	}]
	job_name        = "txgen"
	scrape_interval = "30s"
	forward_to      = [prometheus.relabel.txgen.receiver]
}

prometheus.relabel "txgen" {
	forward_to = [prometheus.remote_write.central.receiver]

	rule {
		target_label = "node"
		replacement  = sys.env("TN_NODE")
	}

	rule {
		target_label = "chain"
		replacement  = sys.env("TN_CHAIN")
	}

	rule {
		target_label = "network"
		replacement  = sys.env("TN_CHAIN")
	}

	rule {
		target_label = "service"
		replacement  = "txgen"
	}
}

prometheus.remote_write "central" {
	endpoint {
		url          = sys.env("OBS_METRICS_PUSH_URL")
		bearer_token = sys.env("OBS_INGEST_TOKEN")
	}
}
ALLOY

    # The env file carries the token, so build it in the staging dir (mode 600) and log a
    # redacted twin — same discipline as devnet-observability.sh.
    cat > "${STAGE}/alloy.env" <<EOF
TN_NODE=${TXGEN_INSTANCE}
TN_CHAIN=devnet
TXGEN_METRICS_ADDR=127.0.0.1:9090
OBS_PUSH_URL=${OBS_PUSH_URL}
OBS_METRICS_PUSH_URL=${OBS_METRICS_PUSH_URL}
OBS_INGEST_TOKEN=${token}
EOF
    chmod 600 "${STAGE}/alloy.env"
    echo "    + alloy.env: TN_NODE=${TXGEN_INSTANCE} TN_CHAIN=devnet OBS_INGEST_TOKEN=***REDACTED***"

    tx_scp "${STAGE}/config.alloy" "/tmp/config.alloy"
    tx_scp "${STAGE}/alloy.env"    "/tmp/alloy.env"

    tx_stdin <<'ALLOYINST'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if ! command -v alloy >/dev/null 2>&1; then
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://apt.grafana.com/gpg.key | gpg --dearmor -o /etc/apt/keyrings/grafana.gpg
    echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" \
        > /etc/apt/sources.list.d/grafana.list
    apt-get update -y
    apt-get install -y alloy
fi
install -m 0644 /tmp/config.alloy /etc/alloy/config.alloy
install -m 0600 /tmp/alloy.env    /etc/default/alloy-txgen
rm -f /tmp/config.alloy /tmp/alloy.env

# The packaged unit reads /etc/default/alloy; add ours as a second EnvironmentFile via a
# drop-in rather than editing the packaged unit (survives package upgrades). Alloy must
# also be in systemd-journal to read the journal.
usermod -aG systemd-journal alloy 2>/dev/null || true
mkdir -p /etc/systemd/system/alloy.service.d
cat > /etc/systemd/system/alloy.service.d/10-txgen.conf <<'DROPIN'
[Service]
EnvironmentFile=/etc/default/alloy-txgen
DROPIN

systemctl daemon-reload
systemctl enable --now alloy
sleep 10
echo "alloy is-active: $(systemctl is-active alloy)"
systemctl is-active alloy >/dev/null || { journalctl -u alloy --no-pager -n 30 --output=cat; exit 1; }
ALLOYINST

    echo "    verifying the generator's metrics endpoint answers and Alloy is shipping"
    tx_stdin <<'ALLOYCHECK'
set -uo pipefail
echo "--- generator metrics (loopback) ---"
# Capture-then-filter, NOT `curl | grep | head`: head exits after N lines and SIGPIPEs
# grep, which `||` then reports as "no metrics" even though the scrape succeeded. Same
# pipe hazard devnet-deploy.sh's step 3 documents for the serial-console read.
m="$(curl -s --max-time 5 127.0.0.1:9090/metrics 2>/dev/null)"
if printf '%s' "$m" | grep -q '^txgen_tx_submitted_total'; then
    printf '%s' "$m" | grep -E '^txgen_(tx_submitted_total|mode|wallet_balance_wei)' | head -8
    echo "  ✓ $(printf '%s' "$m" | grep -c '^txgen_tx_submitted_total') txgen_tx_submitted_total series"
else
    echo "  ❌ no txgen_* metrics on 127.0.0.1:9090"
fi
echo "--- alloy shipping counters ---"
curl -s --max-time 5 127.0.0.1:12345/metrics 2>/dev/null \
    | grep -E 'loki_write_sent_bytes_total|prometheus_remote_write.*(samples_total|sent)' | head -5 \
    || echo "  (alloy self-metrics not exposed on :12345 — check 'journalctl -u alloy')"
ALLOYCHECK
    echo "    ✓ observability wired"
}

# =============================== runner ========================================
echo "=========================================="
echo "devnet transaction generator (Step 16)"
echo "Instance:  ${TXGEN_INSTANCE} (${TXGEN_ZONE}, ${TXGEN_MACHINE_TYPE}, ${TXGEN_DISK_SIZE}GB)"
echo "Project:   ${PROJECT_ID}"
echo "Source:    ${TXGEN_SRC_DIR}"
echo "Book:      ${TXGEN_CONTRACTS_DIR}/deployments/deployments-devnet.json"
echo "RPC:       (from config.devnet.toml) https://rpc.devnet.telcoin.network / chain ${CHAIN_ID}"
echo "Mode:      run (continuous). NEVER blast."
if [ -n "${ONLY}" ]; then echo "Scope:     ONLY step ${ONLY}"; else echo "Scope:     steps ${FROM}..${LAST_STEP}"; fi
[ "${CONFIRM}" -eq 1 ] && echo "Confirm:   APPLY (--yes)" || echo "Confirm:   DRY RUN (no --yes)"
echo "=========================================="

if [ "${CONFIRM}" -ne 1 ]; then
    echo ""
    step_1 || exit 1
    cat <<EOF

PLAN (nothing has been changed):
   2. ensure the age identity + mirror it to Secret Manager (${AGE_KEY_SECRET})
   3. sops-encrypt master/children -> *.sops  (binary store; round trip asserted)
   4. create ${TXGEN_INSTANCE} (${TXGEN_MACHINE_TYPE}, ${TXGEN_ZONE}) + Ops Agent
   5. ship the source tarball, build the musl binary on the VM
   6. install user/layout/binary/config/secrets/address book (+ sops)
   7. install the hardened unit + SOPS_AGE_KEY_FILE, TXGEN_NO_FILE_LOG, Restart=always
   8. verify the sops round trip as ${TXGEN_USER}, then --dry-run
   9. systemctl enable --now, assert active + startup markers
  10. Alloy: journald -> Loki, 127.0.0.1:9090 -> Prometheus

DRY RUN only — re-run with --yes to apply.
EOF
    exit 0
fi

run_step() { echo ""; echo "##########################################"; "step_$1"; echo "## step $1 done"; }
if [ -n "${ONLY}" ]; then
    run_step "${ONLY}"
else
    n="${FROM}"
    while [ "${n}" -le "${LAST_STEP}" ]; do run_step "${n}"; n=$((n + 1)); done
fi

cat <<EOF

==========================================
transaction generator live on ${TXGEN_INSTANCE}.
==========================================
  journal:  gcloud compute ssh ${TXGEN_INSTANCE} --zone=${TXGEN_ZONE} --project=${PROJECT_ID} --tunnel-through-iap --command='sudo journalctl -fu ${TXGEN_UNIT}'
  metrics:  ... --command='curl -s 127.0.0.1:9090/metrics | grep txgen_tx_submitted_total'
  stop:     ... --command='sudo systemctl stop ${TXGEN_UNIT}'   (drains cleanly in ~30s)

Grafana alerts worth adding (docs/operations.md:27-33):
  * rate(txgen_tx_submitted_total{outcome="ok"}[5m]) == 0 while txgen_mode != 0   -> critical
  * txgen_wallet_balance_wei{wallet="Master"} < 50e18                             -> warning
EOF
