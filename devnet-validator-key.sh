#!/usr/bin/env bash
#
# devnet-validator-key.sh — create a validator's execution key; its private key lives only in
# Secret Manager.
#
# A validator's BLS proof of possession binds its BLS key to an execution address, and the
# ConsensusRegistry calls that make it a validator (stake, activate) are sent FROM that address,
# so every validator needs an ECDSA execution key. This script creates one with `cast wallet new`,
# stores the private key as the Secret Manager secret devnet-<nodeN>-validator-pk (PROJECT_ID),
# reads it back through the import path devnet-stake-node5.sh uses, to prove the stored key
# belongs to the address, and prints the address and the secret name, never the key. With
# --apply it also writes the address into config.sh and funds it in testnet_accounts.yaml.
# Background, rotation and the checklist for a new devnet: docs/validator-key-provisioning.md.
#
# Usage:
#   ./devnet-validator-key.sh <nodeN>                    # create + store the key; SHOW the file edits
#   ./devnet-validator-key.sh <nodeN> --apply            # create + store the key; MAKE the file edits
#   ./devnet-validator-key.sh <nodeN> --rotate --apply   # the same, when the secret already exists
#
#   <nodeN>    one of config.sh NODE_NAMES; its index i selects EXECUTION_ADDRESSES[i]
#   --apply    replace EXECUTION_ADDRESSES[i] in ${CONFIG_FILE:-config.sh} (a placeholder or an
#              old address) with the new address, and fund it with 1,000,100 TEL (stake
#              1,000,000 + gas) in ${GENESIS_WORKSPACE}/testnet_accounts.yaml. An entry for the
#              same address is left alone; with --rotate, the entry tagged
#              "# <nodeN> execution key" is replaced.
#   --rotate   accept a secret that already exists: the new key becomes its newest version
#              (tn_secret reads `latest`). Older versions stay enabled until disabled by hand.
#
# Without --apply the key IS still created and stored; only the two file edits are shown
# instead of made. Apply that diff by hand, or re-run with --rotate --apply (a newer key).
#
# Nothing is created when: <nodeN> is not in NODE_NAMES; node5's secret name differs from
# NODE5_VALIDATOR_PK_SECRET; the secret exists and --rotate is absent; or the edits cannot be
# rendered and checked (the EXECUTION_ADDRESSES line is missing, duplicated or not a list of
# quoted words, or element i is neither a placeholder nor a 0x address; the accounts file is
# missing; a tagged entry exists and --rotate is absent).
#
# KEY HANDLING. The private key never goes on argv, into the environment, into a file, or to
# stdout/stderr. The `cast wallet new --json` output is held in one unexported shell variable;
# the key is cut out of it on a pipe straight into tn_secret_set (gcloud --data-file=-), and the
# variable is unset. The read-back pipes tn_secret into `devnet-stake-node5.py import-key`
# (cast keystore import on a private pty, in a 0700 temp dir that the EXIT trap removes).
# The script refuses to run under `set -x`.
#
# Exit codes: 0 ok, 1 failure, 2 usage.

set -euo pipefail
case "$-" in
    *x*) echo "❌ refusing to run under 'set -x' (xtrace would log the key)" >&2; exit 1 ;;
esac

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
HELPER="${REPO_DIR}/devnet-stake-node5.py"
ZERO_ADDR="0x0000000000000000000000000000000000000000"

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]:-$0}" | sed '$d' | sed 's/^# \{0,1\}//'; }
die() { echo "❌ $*" >&2; exit 1; }

# --- args -----------------------------------------------------------------------
NODE=""
APPLY=0
ROTATE=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1 ;;
        --rotate) ROTATE=1 ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "❌ unknown option '$1' (see --help)" >&2; exit 2 ;;
        *)
            [ -z "${NODE}" ] || { echo "❌ one node at a time (got '${NODE}' and '$1')" >&2; exit 2; }
            NODE="$1" ;;
    esac
    shift
done
[ -n "${NODE}" ] || { usage >&2; exit 2; }

# shellcheck source=/dev/null
source "${REPO_DIR}/devnet-lib.sh"
CONFIG_PATH="${CONFIG_FILE:-${REPO_DIR}/config.sh}"     # the file devnet-lib.sh just sourced
ACCOUNTS="${GENESIS_WORKSPACE:-${REPO_DIR}}/testnet_accounts.yaml"

IDX=""
_i=0
for _n in "${NODE_NAMES[@]}"; do
    if [ "${_n}" = "${NODE}" ]; then IDX="${_i}"; break; fi
    _i=$((_i + 1))
done
[ -n "${IDX}" ] || { echo "❌ unknown node '${NODE}' (config.sh NODE_NAMES: ${NODE_NAMES[*]})" >&2; exit 2; }
[ "${IDX}" -lt "${#EXECUTION_ADDRESSES[@]}" ] || die "config.sh EXECUTION_ADDRESSES has no element ${IDX} for ${NODE}"
SECRET="devnet-${NODE}-validator-pk"
# devnet-stake-node5.sh loads node 5's key from NODE5_VALIDATOR_PK_SECRET: the two names must agree.
if [ "${NODE}" = "node5" ] && [ "${SECRET}" != "${NODE5_VALIDATOR_PK_SECRET:-}" ]; then
    die "config.sh NODE5_VALIDATOR_PK_SECRET='${NODE5_VALIDATOR_PK_SECRET:-}' but this script stores node5's key as '${SECRET}'; devnet-stake-node5.sh would not find it"
fi
OLD_ADDR="${EXECUTION_ADDRESSES[${IDX}]}"

for _c in cast gcloud python3 diff awk; do
    command -v "${_c}" >/dev/null 2>&1 || die "${_c} not found on PATH"
done
[ -f "${HELPER}" ] || die "${HELPER} not found (it imports the key for the read-back check)"
[ -f "${CONFIG_PATH}" ] || die "config file ${CONFIG_PATH} not found"
[ -f "${ACCOUNTS}" ] || die "accounts file ${ACCOUNTS} not found"
if [ "${APPLY}" -eq 1 ]; then
    [ -w "${CONFIG_PATH}" ] || die "--apply: ${CONFIG_PATH} is not writable"
    [ -w "${ACCOUNTS}" ] || die "--apply: ${ACCOUNTS} is not writable"
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/devnet-validator-key.XXXXXX")"
cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
PY="${TMP}/edit.py"

# --- python: wallet JSON fields, the config.sh edit, the testnet_accounts.yaml edit -----
cat > "${PY}" <<'PY'
import json
import re
import sys

ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
STAKE_PLUS_GAS_WEI = 1000100 * 10**18          # 1,000,000 TEL stake + 100 TEL gas
ARRAY_RE = re.compile(r"^export EXECUTION_ADDRESSES=\((.*)\)[ \t]*$")
ENTRY_RE = re.compile(r'^"(0x[0-9a-fA-F]{40})":[ \t]*(?:#[ \t]*(.*?))?[ \t]*$')


def fail(msg):
    print(f"devnet-validator-key: {msg}", file=sys.stderr)
    sys.exit(1)


def wallet(field):
    """`cast wallet new --json` on stdin. Error messages name keys and types, never a value."""
    try:
        item = json.load(sys.stdin)
    except Exception as e:
        fail(f"cast wallet new --json printed no JSON ({type(e).__name__})")
    if isinstance(item, dict) and "data" in item:          # cast 1.8: {"data":[{...}],"success":...}
        if item.get("success") is False:
            fail("cast wallet new --json reported success=false")
        item = item["data"]
    if isinstance(item, list):                              # older cast: [{...}]
        if len(item) != 1:
            fail(f"expected one wallet in the cast output, got {len(item)}")
        item = item[0]
    if not isinstance(item, dict):
        fail(f"unexpected cast output shape ({type(item).__name__})")
    addr = item.get("address")
    if not isinstance(addr, str) or not ADDR_RE.match(addr):
        fail(f"no 0x-prefixed 20-byte 'address' in the cast output (keys: {sorted(item)})")
    key = item.get("private_key", item.get("privateKey"))
    if not isinstance(key, str):
        fail(f"no 'private_key' in the cast output (keys: {sorted(item)})")
    key = key.strip()
    if not key.startswith("0x"):
        key = "0x" + key
    if not KEY_RE.match(key):
        fail("the cast 'private_key' is not 32 bytes of hex (value not shown)")
    if field == "address":
        sys.stdout.write(addr.lower() + "\n")
    elif field == "private_key":
        sys.stdout.write(key.lower())                       # no newline: stored byte for byte
    elif field != "check":
        fail(f"unknown field {field!r}")


def config(path, idx, addr, out):
    """Replace element idx of the one `export EXECUTION_ADDRESSES=(...)` line; print the old value."""
    idx = int(idx)
    if not ADDR_RE.match(addr):
        fail(f"{addr!r} is not an address")
    with open(path) as f:
        lines = f.read().splitlines(keepends=True)
    hits = [n for n, line in enumerate(lines) if ARRAY_RE.match(line.rstrip("\r\n"))]
    if len(hits) != 1:
        fail(f"{path}: expected exactly one 'export EXECUTION_ADDRESSES=(...)' line, found {len(hits)}")
    n = hits[0]
    line = lines[n]
    m = ARRAY_RE.match(line.rstrip("\r\n"))
    body = m.group(1)
    if re.sub(r'"[^"]*"', "", body).strip():
        fail(f"{path}:{n + 1}: EXECUTION_ADDRESSES is not a list of double-quoted words")
    toks = list(re.finditer(r'"([^"]*)"', body))
    if idx >= len(toks):
        fail(f"{path}:{n + 1}: EXECUTION_ADDRESSES has {len(toks)} elements, no index {idx}")
    t = toks[idx]
    if not (t.group(1).startswith("PLACEHOLDER_") or ADDR_RE.match(t.group(1))):
        fail(f"{path}:{n + 1}: EXECUTION_ADDRESSES[{idx}] is {t.group(1)!r}, neither a placeholder nor a 0x address; fix it by hand")
    new_body = body[:t.start(1)] + addr + body[t.end(1):]
    lines[n] = line[:m.start(1)] + new_body + line[m.end(1):]
    with open(out, "w") as f:
        f.write("".join(lines))
    print(t.group(1))


def accounts(path, node, addr, rotate, out):
    """Fund addr in testnet_accounts.yaml; print append | replace <old> | present."""
    addr = addr.lower()
    rotate = rotate == "1"
    with open(path) as f:
        text = f.read()
    lines = text.splitlines(keepends=True)
    blocks = []                                             # [first line, end line, address, comment]
    for n, line in enumerate(lines):
        m = ENTRY_RE.match(line.rstrip("\r\n"))
        if m:
            blocks.append([n, n + 1, m.group(1), m.group(2) or ""])
        elif blocks and blocks[-1][1] == n and line[:1] in (" ", "\t"):
            blocks[-1][1] = n + 1
    tag = re.compile(r"^" + re.escape(node) + r" execution key\b")
    same = [b for b in blocks if b[2].lower() == addr]
    tagged = [b for b in blocks if tag.match(b[3]) and b[2].lower() != addr]
    if len(tagged) > 1:
        fail(f"{path}: {len(tagged)} entries are tagged '# {node} execution key'; fix by hand")
    if tagged and not rotate:
        fail(f"{path}:{tagged[0][0] + 1} already funds {node}'s execution key {tagged[0][2]}; pass --rotate to replace that entry")
    if same and tagged:
        fail(f"{path} funds {addr} AND a different '# {node} execution key' entry; fix by hand")
    balance = hex(STAKE_PLUS_GAS_WEI)
    entry = [f'"{addr}": # {node} execution key (stake 1,000,000 TEL + gas)\n',
             f'  balance: "{balance}"\n']
    if same:
        action, new_lines, gone = "present", lines, None
    elif tagged:
        b = tagged[0]
        action, new_lines, gone = f"replace {b[2]}", lines[:b[0]] + entry + lines[b[1]:], b[2]
    else:
        new_lines = list(lines)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        action, new_lines, gone = "append", new_lines + entry, None
    new_text = "".join(new_lines)
    check(text, new_text, addr, action, gone, balance)
    with open(out, "w") as f:
        f.write(new_text)
    print(action)


def check(old_text, new_text, addr, action, gone, balance):
    """The rendered file must parse to the old mapping, minus `gone`, plus addr (exactly once)."""
    try:
        import yaml
    except ImportError:
        print("devnet-validator-key: PyYAML is not installed; the accounts edit is checked as text only", file=sys.stderr)
        count = lambda t: sum(1 for x in t.splitlines() if ENTRY_RE.match(x))
        want = count(old_text) + (1 if action == "append" else 0)
        if count(new_text) != want:
            fail(f"rendered accounts file has {count(new_text)} entries, expected {want}")
        return
    try:
        old = yaml.safe_load(old_text)
        new = yaml.safe_load(new_text)
    except yaml.YAMLError as e:
        fail(f"accounts YAML does not parse: {e}")
    if not isinstance(old, dict) or not isinstance(new, dict):
        fail("accounts YAML is not a mapping of address -> account")
    expected = dict(old)
    if gone is not None:
        del expected[gone]
    if action != "present":
        expected[addr] = {"balance": balance}
    if new != expected:
        fail("rendered accounts file does not parse to the old accounts plus the new entry")
    keys = [k for k in new if isinstance(k, str) and k.lower() == addr]
    if len(keys) != 1:
        fail(f"{addr} appears {len(keys)} times (case-insensitive) in the rendered accounts file")
    if action == "present":
        try:
            have = int(str(new[keys[0]].get("balance", "0")), 0)
        except (AttributeError, ValueError):
            have = 0
        if have < STAKE_PLUS_GAS_WEI:
            print(f"devnet-validator-key: WARNING {addr} is already in the accounts file with less than 1,000,100 TEL; left alone", file=sys.stderr)


def main():
    a = sys.argv[1:]
    if a[:1] == ["wallet"] and len(a) == 2:
        wallet(a[1])
    elif a[:1] == ["config"] and len(a) == 5:
        config(*a[1:])
    elif a[:1] == ["accounts"] and len(a) == 6:
        accounts(*a[1:])
    else:
        fail(f"usage error: {a[:1]}")


main()
PY

# --- helpers --------------------------------------------------------------------
# placeholder_count <file>: occurrences of the PLACEHOLDER_ marker anywhere in the file
placeholder_count() { { grep -o 'PLACEHOLDER_' "$1" || true; } | wc -l | tr -d '[:space:]'; }
# gate_count <file>: non-comment lines holding the marker (the devnet-deploy.sh gate)
gate_count() {
    { grep -n 'PLACEHOLDER_' "$1" || true; } | { grep -v -E '^[0-9]+:[[:space:]]*#' || true; } | wc -l | tr -d '[:space:]'
}
# list_addrs <config>: EXECUTION_ADDRESSES as bash sees it after sourcing <config>, one per line
list_addrs() {
    # shellcheck disable=SC2016  # $1 and the array expand in the child bash, on purpose
    bash -c 'source "$1" >/dev/null 2>&1 || exit 1; printf "%s\n" "${EXECUTION_ADDRESSES[@]}"' list_addrs "$1"
}
# show_diff <old> <new>: unified diff; rc 1 (files differ) is the expected case
show_diff() {
    local rc=0
    diff -u "$1" "$2" | sed 's/^/      /' || rc=$?
    [ "${rc}" -le 1 ] || die "diff ${1} ${2} failed (rc ${rc})"
}

# render <addr>: write ${TMP}/config.new + ${TMP}/accounts.new for <addr> and check both.
# Sets RENDER_OLD (the EXECUTION_ADDRESSES element replaced) and RENDER_ACCOUNTS
# (append | replace <old> | present). rc 1, reason on stderr, on any failed check.
render() {
    local addr="$1" old_list new_list want_list before after want
    RENDER_OLD="$(python3 -I "${PY}" config "${CONFIG_PATH}" "${IDX}" "${addr}" "${TMP}/config.new")" || return 1
    bash -n "${TMP}/config.new" || { echo "❌ the edited config fails bash -n" >&2; return 1; }
    old_list="$(list_addrs "${CONFIG_PATH}")" || { echo "❌ sourcing ${CONFIG_PATH} failed" >&2; return 1; }
    new_list="$(list_addrs "${TMP}/config.new")" || { echo "❌ sourcing the edited config failed" >&2; return 1; }
    if [ "$(printf '%s\n' "${old_list}" | sed -n "$((IDX + 1))p")" != "${RENDER_OLD}" ]; then
        echo "❌ ${CONFIG_PATH}: the EXECUTION_ADDRESSES line parsed here is not the one bash sources" >&2
        return 1
    fi
    want_list="$(printf '%s\n' "${old_list}" | awk -v n="$((IDX + 1))" -v a="${addr}" 'NR == n { $0 = a } { print }')"
    if [ "${new_list}" != "${want_list}" ]; then
        echo "❌ the edited config does not source to EXECUTION_ADDRESSES with only element ${IDX} changed" >&2
        return 1
    fi
    before="$(placeholder_count "${CONFIG_PATH}")"
    after="$(placeholder_count "${TMP}/config.new")"
    case "${RENDER_OLD}" in
        PLACEHOLDER_*) want=$((before - 1)) ;;
        *) want="${before}" ;;
    esac
    if [ "${after}" -ne "${want}" ]; then
        echo "❌ PLACEHOLDER_ count in the edited config is ${after}, expected ${want} (was ${before})" >&2
        return 1
    fi
    RENDER_ACCOUNTS="$(python3 -I "${PY}" accounts "${ACCOUNTS}" "${NODE}" "${addr}" "${ROTATE}" "${TMP}/accounts.new")" || return 1
    # devnet-genesis-build.sh's own funding check, verbatim
    grep -qi "^\"${addr}\":" "${TMP}/accounts.new" || { echo "❌ ${addr} is not a key in the edited accounts file" >&2; return 1; }
}

echo ">>> ${NODE}: execution key -> Secret Manager ${SECRET} (project ${PROJECT_ID})"
echo "    config:   ${CONFIG_PATH}  (EXECUTION_ADDRESSES[${IDX}] = ${OLD_ADDR})"
echo "    accounts: ${ACCOUNTS}"

# --- 1. preflight: everything that can refuse, before a key exists -------------
if gcloud secrets describe "${SECRET}" --project="${PROJECT_ID}" >/dev/null 2>&1 </dev/null; then
    [ "${ROTATE}" -eq 1 ] || die "Secret Manager ${SECRET} already exists; no key was created. Pass --rotate to add a new key as its newest version (docs/validator-key-provisioning.md, Rotation)"
    echo "    ${SECRET} exists; --rotate: the new key becomes its newest version"
fi
# The same render + checks as step 4, for a stand-in address: a file problem stops the run here.
render "${ZERO_ADDR}" || die "preflight: the config/accounts edits cannot be made (above); no key was created"

# --- 2. create the key and store it ---------------------------------------------
# Again here: the check at the top ran before config.sh was sourced, and a sourced file can
# turn xtrace on, which would trace the wallet JSON (the private key) to stderr.
case "$-" in
    *x*) die "xtrace was turned on after start-up (by ${CONFIG_PATH}?); refusing to create a key under 'set -x'" ;;
esac
unset wallet_json
wallet_json="$(cast wallet new --json </dev/null)" || die "cast wallet new --json failed; nothing was stored"
export -n wallet_json
if ! printf '%s' "${wallet_json}" | python3 -I "${PY}" wallet check; then
    unset wallet_json
    die "unexpected cast wallet new --json output (above); nothing was stored"
fi
ADDR="$(printf '%s' "${wallet_json}" | python3 -I "${PY}" wallet address)"
if ! printf '%s' "${wallet_json}" | python3 -I "${PY}" wallet private_key | tn_secret_set "${SECRET}"; then
    unset wallet_json
    die "storing the key in ${SECRET} failed; no file was edited. If ${SECRET} now exists without a version, re-run with --rotate"
fi
unset wallet_json
echo "    ✓ new key ${ADDR} stored as ${SECRET}"

# --- 3. read back through devnet-stake-node5.sh's own import path ---------------
mkdir -m 700 "${TMP}/ks"
if ! got="$(tn_secret "${SECRET}" | python3 "${HELPER}" import-key --dir "${TMP}/ks" --name readback --expect "${ADDR}")"; then
    die "read-back: the newest version of ${SECRET} does not import as ${ADDR} (reason above; no file was edited). Re-run with --rotate"
fi
rm -rf "${TMP}/ks"
echo "    ✓ read back: the newest version of ${SECRET} is the key for ${got}"

# --- 4. the config.sh + testnet_accounts.yaml edits -----------------------------
render "${ADDR}" || die "the key is stored (${SECRET} = ${ADDR}) but the edits failed (above); make them by hand"
echo ""
echo ">>> EXECUTION_ADDRESSES[${IDX}]: ${RENDER_OLD} -> ${ADDR}"
show_diff "${CONFIG_PATH}" "${TMP}/config.new"
case "${RENDER_ACCOUNTS}" in
    present) echo ">>> testnet_accounts.yaml: ${ADDR} is already funded; left alone" ;;
    append) echo ">>> testnet_accounts.yaml: add ${ADDR} with 1,000,100 TEL"
            show_diff "${ACCOUNTS}" "${TMP}/accounts.new" ;;
    *) echo ">>> testnet_accounts.yaml: ${RENDER_ACCOUNTS#replace } -> ${ADDR} (1,000,100 TEL)"
       show_diff "${ACCOUNTS}" "${TMP}/accounts.new" ;;
esac
case "${RENDER_OLD}" in
    PLACEHOLDER_*) ;;
    *) echo "⚠️  ${RENDER_OLD} was a real address: a genesis or node-info built from it still funds and binds it" ;;
esac

if [ "${APPLY}" -eq 1 ]; then
    cp "${TMP}/config.new" "${CONFIG_PATH}"
    cp "${TMP}/accounts.new" "${ACCOUNTS}"
    if ! cmp -s "${TMP}/config.new" "${CONFIG_PATH}" || ! cmp -s "${TMP}/accounts.new" "${ACCOUNTS}"; then
        die "the files on disk differ from the checked edits after the copy"
    fi
    [ "$(list_addrs "${CONFIG_PATH}" | sed -n "$((IDX + 1))p")" = "${ADDR}" ] \
        || die "${CONFIG_PATH} does not source to EXECUTION_ADDRESSES[${IDX}] = ${ADDR}"
    echo "    ✓ applied; ${CONFIG_PATH} still has $(gate_count "${CONFIG_PATH}") non-comment PLACEHOLDER_ line(s) (devnet-deploy.sh needs 0)"
else
    echo ""
    echo "DRY RUN for the files (no --apply): ${CONFIG_PATH} and ${ACCOUNTS} are unchanged."
    echo "The new key IS stored in ${SECRET}. Make the edits by hand, or re-run with --rotate --apply (a newer key)."
fi

echo ""
echo "Next: keygen binds ${NODE}'s proof of possession to EXECUTION_ADDRESSES[${IDX}], so (re-)run keygen"
echo "for ${NODE} after this (devnet-deploy.sh step 5) and rebuild genesis."
[ "${NODE}" = "node5" ] && echo "devnet-stake-node5.sh loads ${SECRET} to stake and activate node 5."
echo ""
echo "address: ${ADDR}"
echo "secret:  ${SECRET}"
