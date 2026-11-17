#!/usr/bin/env bash
#
# devnet-release-sign.sh — devnet rehearsal of the mainnet release signature. `prepare`
# writes a release manifest for config.sh's image and chain configs, the operator signs
# its SHA256SUMS with GPG on the signing laptop, and `verify` checks that signature with
# gpgv against the release-key allow-list (and every hash) before any node is finalized.
#
# Usage:
#   ./devnet-release-sign.sh prepare [--force]
#   ./devnet-release-sign.sh verify
#   ./devnet-release-sign.sh --help
#
# Release directory: ${RELEASES_DIR}/${RELEASE_TAG} (default <repo>/releases/<tag>):
#   IMAGE_DIGEST    DOCKER_IMAGE and a newline: one line, <repository>@sha256:<64 lower
#                   hex>, the grammar the node scripts accept from a signed release
#                   (tn-node-deployment lib/common.sh _tn_release_fetch).
#   GATEWAY_IMAGE_DIGEST  only when config.sh sets GATEWAY_IMAGE (not empty) AND
#                   TN_GATEWAY_ENABLE=1 (the fleet runs worker gateways): the worker
#                   gateway's image, GATEWAY_IMAGE and a newline, the same one-line grammar.
#                   A fleet with gateways switched off signs no gateway digest: below,
#                   "with GATEWAY_IMAGE" means both, and TN_GATEWAY_ENABLE not 1 reads as
#                   GATEWAY_IMAGE unset.
#   SHA256SUMS      sha256sum format, "<64 hex>  <name>", one line per file, in this
#                   order: IMAGE_DIGEST, GATEWAY_IMAGE_DIGEST (only with GATEWAY_IMAGE),
#                   genesis.yaml (GENESIS_FILE), committee.yaml (COMMITTEE_FILE),
#                   parameters.yaml (PARAMETERS_FILE). With GATEWAY_IMAGE unset or empty
#                   it is the four-name manifest of before, byte for byte. This is the
#                   mainnet shape minus the tarball: a mainnet SHA256SUMS also lists
#                   telcoin-network-<tag>-<triple>.tar.gz and names the chain configs
#                   chain-configs/<network>/<file>. Devnet runs the image by digest, so it
#                   has no tarball, and it names each chain config by the basename finalize
#                   stages on the node. Relative config paths resolve against REPO_ROOT.
#   SHA256SUMS.asc  the signer's ASCII-armored detached signature over SHA256SUMS.
#
# prepare [--force]
#   Needs DOCKER_IMAGE in digest form (and GATEWAY_IMAGE, when set: one still holding a
#   PLACEHOLDER marker is refused) and the three chain configs (devnet-deploy.sh step
#   6 runs it right after ./devnet-genesis-build.sh). When SHA256SUMS already holds
#   exactly this content it changes nothing and keeps SHA256SUMS.asc (it only rewrites a
#   missing or edited IMAGE_DIGEST or GATEWAY_IMAGE_DIGEST, whose hash SHA256SUMS fixes).
#   When the content
#   differs and SHA256SUMS.asc exists, it refuses: that signature is for other files.
#   --force removes the stale SHA256SUMS.asc and writes the new manifest, which then
#   needs a new signature. It prints the one-liner the signer runs on the laptop:
#     ssh <host> 'cat <dir>/SHA256SUMS' > /tmp/SHA256SUMS && gpg --detach-sign --armor \
#       --local-user <RELEASE_SIGNER_FPR> --output /tmp/SHA256SUMS.asc /tmp/SHA256SUMS && \
#       scp /tmp/SHA256SUMS.asc <host>:<dir>/SHA256SUMS.asc
#   <host> is this machine's short hostname; set RELEASE_SIGN_SSH_HOST to the name the
#   laptop's ssh uses for it (an ~/.ssh/config alias, or user@host).
#
# verify
#   SHA256SUMS.asc absent: prints RELEASE_SIG_PENDING on its own stdout line (the signing
#   hint goes to stderr) and exits 3. Otherwise, in a private throwaway GNUPGHOME: every
#   *.asc in RELEASE_KEYS_DIR, plus <repo>/release-keys/*.asc when that directory exists
#   (devnet-only keys), is dearmored into one keyring, and each key's primary fingerprint
#   joins the allow-list. Then
#     gpgv --status-fd 1 --keyring <keyring> SHA256SUMS.asc SHA256SUMS
#   and its status lines are judged: accepted only when a GOODSIG is followed by a
#   VALIDSIG whose last field (the primary key fingerprint, 40 upper-case hex) is on the
#   allow-list (a NEWSIG in between resets it), no line says BADSIG, EXPKEYSIG, REVKEYSIG,
#   EXPSIG, ERRSIG or NO_PUBKEY, and gpgv exits 0. That is the node's
#   _tn_gpg_status_verdict rule made stricter: the node lets a further signature by a key
#   it does not hold (NO_PUBKEY, ERRSIG code 9) through with a warning and ignores gpgv's
#   exit code; devnet has one signer, so any such signature fails here. Anything the node
#   refuses is refused here too. Then SHA256SUMS must name exactly the files above for the
#   current configuration (four, or five with GATEWAY_IMAGE), in that order; `sha256sum -c`
#   checks each against the current file (the digest files in the release directory, the
#   chain configs at their config.sh paths); IMAGE_DIGEST must be one well-formed line
#   equal to config.sh's DOCKER_IMAGE, and GATEWAY_IMAGE_DIGEST (with GATEWAY_IMAGE) one
#   equal to GATEWAY_IMAGE. With GATEWAY_IMAGE set, a signed manifest that does not list
#   GATEWAY_IMAGE_DIGEST (made before the gateway) fails with "the gateway digest is
#   missing": it needs prepare --force and a new signature (unsigned, it is
#   RELEASE_SIG_PENDING like any other manifest).
#   RELEASE_SIGNER_FPR plays no part here: only the allow-list grants trust.
#
# Configuration (config.sh; CONFIG_FILE selects another file, as for every devnet-*.sh):
#   RELEASE_TAG         release name, the release directory's name (required; [A-Za-z0-9._-],
#                       no leading dot)
#   GATEWAY_IMAGE       worker gateway image, <repository>@sha256:<64 hex> (optional; unset
#                       or empty = no GATEWAY_IMAGE_DIGEST, the manifest of before)
#   TN_GATEWAY_ENABLE   1 = the fleet runs worker gateways; anything else (or unset) = the
#                       gateway is not part of the release, as with GATEWAY_IMAGE unset
#   RELEASE_KEYS_DIR    allow-listed public keys (default <repo>/tn-node-deployment/lib/release-keys)
#   RELEASE_SIGNER_FPR  key the printed one-liner signs with (default
#                       4E36D35A4AB61B589861D01AC7173F2377CA7573); informational only
#   RELEASES_DIR        parent of the release directories (default <repo>/releases)
#   RELEASE_SIGN_SSH_HOST  (environment) <host> in the one-liner (default: hostname -s)
#
# Exit codes:
#   0  prepare: manifest written, or already current. verify: signature good by an
#      allow-listed key, every hash matches, IMAGE_DIGEST equals DOCKER_IMAGE (and
#      GATEWAY_IMAGE_DIGEST equals GATEWAY_IMAGE, when set).
#   1  prepare: DOCKER_IMAGE (or a set GATEWAY_IMAGE) not in digest form or still a
#      placeholder, a chain config missing, or SHA256SUMS.asc signs different content (no
#      --force). verify: no manifest, a bad,
#      expired, revoked or unlisted signature (or gpgv failing), a malformed SHA256SUMS,
#      a hash mismatch, a missing file, no usable release key, IMAGE_DIGEST not equal
#      to DOCKER_IMAGE (GATEWAY_IMAGE_DIGEST not equal to GATEWAY_IMAGE), or GATEWAY_IMAGE
#      set and the manifest without GATEWAY_IMAGE_DIGEST.
#   2  usage: unknown command or option, RELEASE_TAG unset or malformed, a config path
#      unset, or a missing tool (sha256sum; for verify also gpg and gpgv).
#   3  verify: SHA256SUMS.asc absent (RELEASE_SIG_PENDING).

set -euo pipefail

usage() { sed -n '2,/^set -euo pipefail/p' "${BASH_SOURCE[0]:-$0}" | sed -e '$d' -e 's/^# \{0,1\}//'; }

CMD="${1:-}"
case "${CMD}" in
    -h|--help|help) usage; exit 0 ;;
    prepare|verify) shift ;;
    "") usage >&2; exit 2 ;;
    *) echo "❌ unknown command '${CMD}' (see --help)" >&2; exit 2 ;;
esac
FORCE=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --force)
            if [ "${CMD}" != prepare ]; then
                echo "❌ --force applies to prepare only (see --help)" >&2; exit 2
            fi
            FORCE=1 ;;
        *) echo "❌ unknown argument '$1' for ${CMD} (see --help)" >&2; exit 2 ;;
    esac
    shift
done

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

RELEASE_TAG="${RELEASE_TAG:-}"
RELEASE_KEYS_DIR="${RELEASE_KEYS_DIR:-${REPO_ROOT}/tn-node-deployment/lib/release-keys}"
RELEASE_SIGNER_FPR="${RELEASE_SIGNER_FPR:-4E36D35A4AB61B589861D01AC7173F2377CA7573}"
RELEASES_DIR="${RELEASES_DIR:-${REPO_ROOT}/releases}"
DEVNET_KEYS_DIR="${REPO_ROOT}/release-keys"   # devnet-only keys, read when present

# The names SHA256SUMS lists, in order. IMAGE_DIGEST first, as on mainnet; the gateway's
# digest right after it when config.sh sets GATEWAY_IMAGE (unset or empty: the four names
# of before, so a release signed before the gateway still verifies).
# The gateway is part of the release only when the fleet runs gateways (TN_GATEWAY_ENABLE=1):
# with gateways switched off GATEWAY_IMAGE reads as unset everywhere below.
GATEWAY_IMAGE="${GATEWAY_IMAGE:-}"
if [ "${TN_GATEWAY_ENABLE:-0}" != 1 ]; then GATEWAY_IMAGE=""; fi
SUM_NAMES_NO_GATEWAY="IMAGE_DIGEST genesis.yaml committee.yaml parameters.yaml"
if [ -n "${GATEWAY_IMAGE}" ]; then
    SUM_NAMES="IMAGE_DIGEST GATEWAY_IMAGE_DIGEST genesis.yaml committee.yaml parameters.yaml"
else
    SUM_NAMES="${SUM_NAMES_NO_GATEWAY}"
fi
# The node's IMAGE_DIGEST grammar (common.sh _tn_release_fetch).
DIGEST_RE='^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$'
SUM_LINE_RE='^[0-9a-f]{64}  [A-Za-z0-9._-]+$'
FPR_RE='^[0-9A-F]{40}$'

if [ -z "${RELEASE_TAG}" ]; then
    echo "❌ RELEASE_TAG unset (config.sh): it names the release directory under ${RELEASES_DIR}" >&2
    exit 2
fi
case "${RELEASE_TAG}" in
    .*|*[!A-Za-z0-9._-]*)
        echo "❌ RELEASE_TAG='${RELEASE_TAG}' is not a plain name ([A-Za-z0-9._-], no leading dot)" >&2
        exit 2 ;;
esac
if [ -z "${GENESIS_FILE:-}" ] || [ -z "${COMMITTEE_FILE:-}" ] || [ -z "${PARAMETERS_FILE:-}" ]; then
    echo "❌ GENESIS_FILE, COMMITTEE_FILE and PARAMETERS_FILE must all be set (config.sh)" >&2
    exit 2
fi

# _abs PATH — PATH as is when absolute, else under REPO_ROOT (a leading ./ dropped).
_abs() {
    case "$1" in
        /*) printf '%s\n' "$1" ;;
        *) printf '%s/%s\n' "${REPO_ROOT}" "${1#./}" ;;
    esac
}

REL_DIR="$(_abs "${RELEASES_DIR}")/${RELEASE_TAG}"
SUMS="${REL_DIR}/SHA256SUMS"
ASC="${REL_DIR}/SHA256SUMS.asc"
IMG="${REL_DIR}/IMAGE_DIGEST"
GW="${REL_DIR}/GATEWAY_IMAGE_DIGEST"
KEYS_DIR="$(_abs "${RELEASE_KEYS_DIR}")"

# _path_for NAME — the file a SHA256SUMS name stands for.
_path_for() {
    case "$1" in
        IMAGE_DIGEST)    printf '%s\n' "${IMG}" ;;
        GATEWAY_IMAGE_DIGEST) printf '%s\n' "${GW}" ;;
        genesis.yaml)    _abs "${GENESIS_FILE}" ;;
        committee.yaml)  _abs "${COMMITTEE_FILE}" ;;
        parameters.yaml) _abs "${PARAMETERS_FILE}" ;;
        *) return 1 ;;
    esac
}

_need_tools() {
    local t miss=""
    for t in "$@"; do
        command -v "${t}" >/dev/null 2>&1 || miss="${miss:+${miss} }${t}"
    done
    if [ -n "${miss}" ]; then
        echo "❌ missing tool(s): ${miss} (GnuPG provides gpg and gpgv, coreutils sha256sum)" >&2
        exit 2
    fi
}

_digest_ok() { [[ "$1" =~ ${DIGEST_RE} ]]; }

# _sha256 FILE — FILE's sha256, 64 hex.
_sha256() {
    local h
    h="$(sha256sum < "$1")" || return 1
    h="${h%% *}"
    [ "${#h}" -eq 64 ] || return 1
    printf '%s\n' "${h}"
}

# _install SRC DST — replace DST with a copy of SRC, mode 0644, by rename.
_install() {
    cp -- "$1" "$2.tmp.$$"
    chmod 0644 "$2.tmp.$$"
    mv -f -- "$2.tmp.$$" "$2"
}

# Private scratch directory (0700; its gnupg/ is the throwaway GNUPGHOME), removed on exit
# after any gpg daemon started for it is stopped.
TMP_DIR=""
_cleanup() {
    if [ -n "${TMP_DIR}" ] && [ -d "${TMP_DIR}" ]; then
        if [ -d "${TMP_DIR}/gnupg" ] && command -v gpgconf >/dev/null 2>&1; then
            GNUPGHOME="${TMP_DIR}/gnupg" gpgconf --kill all >/dev/null 2>&1 || true
        fi
        rm -rf -- "${TMP_DIR}"
    fi
}
trap _cleanup EXIT
trap 'exit 1' HUP INT TERM
_mktmp() {
    TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/devnet-release-sign.XXXXXX")"
    chmod 0700 "${TMP_DIR}"
}

_sign_host() {
    if [ -n "${RELEASE_SIGN_SSH_HOST:-}" ]; then
        printf '%s\n' "${RELEASE_SIGN_SSH_HOST}"
    else
        hostname -s 2>/dev/null || printf '%s\n' "<this-host>"
    fi
}

_print_sign_hint() {
    local host
    host="$(_sign_host)"
    echo "sign SHA256SUMS on the signing laptop (macOS, the key ${RELEASE_SIGNER_FPR} in its gpg):"
    echo "  ssh ${host} 'cat ${SUMS}' > /tmp/SHA256SUMS && gpg --detach-sign --armor --local-user ${RELEASE_SIGNER_FPR} --output /tmp/SHA256SUMS.asc /tmp/SHA256SUMS && scp /tmp/SHA256SUMS.asc ${host}:${ASC}"
    echo "  (<host> = ${host}: set RELEASE_SIGN_SSH_HOST to the name the laptop's ssh uses for this machine)"
}

cmd_prepare() {
    local name path h missing=0 changed=""
    _need_tools sha256sum
    if ! _digest_ok "${DOCKER_IMAGE:-}"; then
        echo "❌ DOCKER_IMAGE='${DOCKER_IMAGE:-}' is not <repository>@sha256:<64 lower-case hex> (config.sh: fill in the pushed digest)" >&2
        exit 1
    fi
    if [ -n "${GATEWAY_IMAGE}" ]; then
        case "${GATEWAY_IMAGE}" in
            *PLACEHOLDER*)
                echo "❌ GATEWAY_IMAGE='${GATEWAY_IMAGE}' still holds a placeholder (config.sh: fill in the pushed gateway digest)" >&2
                exit 1 ;;
        esac
        if ! _digest_ok "${GATEWAY_IMAGE}"; then
            echo "❌ GATEWAY_IMAGE='${GATEWAY_IMAGE}' is not <repository>@sha256:<64 lower-case hex> (config.sh: fill in the pushed gateway digest)" >&2
            exit 1
        fi
    fi
    for name in genesis.yaml committee.yaml parameters.yaml; do
        path="$(_path_for "${name}")"
        if [ ! -f "${path}" ]; then
            echo "❌ missing ${path} (${name}). Run ./devnet-genesis-build.sh first." >&2
            missing=1
        fi
    done
    [ "${missing}" -eq 0 ] || exit 1

    # Build the manifest in private scratch, then compare it with what is on disk.
    _mktmp
    printf '%s\n' "${DOCKER_IMAGE}" > "${TMP_DIR}/IMAGE_DIGEST"
    if [ -n "${GATEWAY_IMAGE}" ]; then printf '%s\n' "${GATEWAY_IMAGE}" > "${TMP_DIR}/GATEWAY_IMAGE_DIGEST"; fi
    : > "${TMP_DIR}/SHA256SUMS"
    for name in ${SUM_NAMES}; do
        case "${name}" in
            IMAGE_DIGEST|GATEWAY_IMAGE_DIGEST) path="${TMP_DIR}/${name}" ;;
            *) path="$(_path_for "${name}")" ;;
        esac
        if ! h="$(_sha256 "${path}")"; then
            echo "❌ cannot hash ${path}" >&2
            exit 1
        fi
        printf '%s  %s\n' "${h}" "${name}" >> "${TMP_DIR}/SHA256SUMS"
    done

    if [ -f "${SUMS}" ] && cmp -s "${TMP_DIR}/SHA256SUMS" "${SUMS}"; then
        if ! cmp -s "${TMP_DIR}/IMAGE_DIGEST" "${IMG}"; then
            _install "${TMP_DIR}/IMAGE_DIGEST" "${IMG}"
            echo "  rewrote ${IMG} (missing or edited; SHA256SUMS fixes its content)"
        fi
        if [ -n "${GATEWAY_IMAGE}" ] && ! cmp -s "${TMP_DIR}/GATEWAY_IMAGE_DIGEST" "${GW}"; then
            _install "${TMP_DIR}/GATEWAY_IMAGE_DIGEST" "${GW}"
            echo "  rewrote ${GW} (missing or edited; SHA256SUMS fixes its content)"
        fi
        echo "✓ release ${RELEASE_TAG}: ${SUMS} already lists this image and these chain configs; unchanged"
        if [ -f "${ASC}" ]; then
            echo "  ${ASC} present (kept)"
        else
            _print_sign_hint
        fi
        echo "next: ./devnet-release-sign.sh verify"
        return 0
    fi

    if [ -e "${ASC}" ] || [ -L "${ASC}" ]; then
        if [ -f "${SUMS}" ]; then
            for name in ${SUM_NAMES}; do
                h="$(awk -v n="${name}" 'substr($0, 67) == n { print substr($0, 1, 64); exit }' "${TMP_DIR}/SHA256SUMS")"
                grep -qxF -- "${h}  ${name}" "${SUMS}" || changed="${changed:+${changed} }${name}"
            done
        fi
        if [ "${FORCE}" -ne 1 ]; then
            echo "❌ SHA256SUMS.asc exists for different content; re-run with --force and re-sign" >&2
            echo "   ${ASC} signs a manifest that no longer matches (changed: ${changed:-the whole manifest})" >&2
            exit 1
        fi
        rm -f -- "${ASC}"
        echo "  --force: removed the stale ${ASC} (changed: ${changed:-the whole manifest})"
    fi

    mkdir -p -- "${REL_DIR}"
    _install "${TMP_DIR}/IMAGE_DIGEST" "${IMG}"
    if [ -n "${GATEWAY_IMAGE}" ]; then
        _install "${TMP_DIR}/GATEWAY_IMAGE_DIGEST" "${GW}"
        _install "${TMP_DIR}/SHA256SUMS" "${SUMS}"
        echo "✓ release ${RELEASE_TAG}: wrote ${IMG}, ${GW} and ${SUMS}"
    else
        _install "${TMP_DIR}/SHA256SUMS" "${SUMS}"
        echo "✓ release ${RELEASE_TAG}: wrote ${IMG} and ${SUMS}"
    fi
    sed 's/^/    /' "${SUMS}"
    _print_sign_hint
    echo "next: ./devnet-release-sign.sh verify"
}

# _keyring_add DIR — dearmor every *.asc in DIR onto the keyring and put each primary key
# fingerprint on the allow-list (the method of common.sh _tn_release_keyring).
KEY_COUNT=0
_keyring_add() {
    local k f
    for k in "$1"/*.asc; do
        if [ ! -f "${k}" ] || [ -L "${k}" ]; then continue; fi
        if ! GNUPGHOME="${TMP_DIR}/gnupg" gpg --batch --no-tty --quiet --dearmor < "${k}" >> "${TMP_DIR}/keyring.gpg" 2>/dev/null; then
            echo "❌ cannot read the release key ${k}" >&2
            exit 1
        fi
        f="$(GNUPGHOME="${TMP_DIR}/gnupg" gpg --batch --no-tty --quiet --with-colons --import-options show-only --import < "${k}" 2>/dev/null \
            | awk -F: '$1 == "pub" { want = 1; next } $1 == "fpr" && want { print $10; want = 0 }')" || f=""
        if [ -z "${f}" ]; then
            echo "❌ no primary key in ${k}" >&2
            exit 1
        fi
        printf '%s\n' "${f}" >> "${TMP_DIR}/allow"
        KEY_COUNT=$((KEY_COUNT + 1))
    done
}

# _sig_verdict ALLOW — judge gpgv status lines on stdin against ALLOW (primary key
# fingerprints, one per line). rc 0 and "GOOD <primary fpr> <key id>" when some GOODSIG
# is followed, with no NEWSIG between, by a VALIDSIG whose last field is in ALLOW and no
# line refuses; else rc 1
# and "<keyword> [<key id>...]": the first BADSIG, EXPKEYSIG, REVKEYSIG, EXPSIG, ERRSIG
# (any rc but 9) or NO_PUBKEY (also ERRSIG rc 9: a key not on the keyring), or NOSIG when
# no allow-listed key made a good signature. The key ids are those of the signatures by
# keys not on the keyring, each once. VALIDSIG_LINE gets the accepted VALIDSIG line.
VALIDSIG_LINE=""
_sig_verdict() {
    local allow="$1" tag kw rest id code fpr good=0 gid="" ok="" okid="" bad="" unknown=""
    while read -r tag kw rest; do
        [ "${tag}" = "[GNUPG:]" ] || continue
        case "${kw}" in
            BADSIG|EXPKEYSIG|REVKEYSIG|EXPSIG)
                [ -n "${bad}" ] || bad="${kw}" ;;
            ERRSIG|NO_PUBKEY)
                # ERRSIG <keyid> <pkalgo> <hashalgo> <class> <time> <rc> [<fpr>]: rc 9 is
                # "no public key", what NO_PUBKEY <keyid> also says.
                read -r id _ _ _ _ code _ <<< "${rest}"
                if [ "${kw}" = NO_PUBKEY ]; then code=9; fi
                if [ "${code}" = 9 ]; then
                    [ -n "${bad}" ] || bad=NO_PUBKEY
                    case " ${unknown} " in
                        *" ${id} "*) ;;
                        *) unknown="${unknown:+${unknown} }${id}" ;;
                    esac
                else
                    [ -n "${bad}" ] || bad=ERRSIG
                fi ;;
            NEWSIG)
                # gpgv starts each signature with NEWSIG: a GOODSIG never carries over.
                good=0 ;;
            GOODSIG)
                good=1
                gid="${rest%% *}" ;;
            VALIDSIG)
                fpr="${rest##* }"
                if [ "${good}" -eq 1 ] && [ -z "${ok}" ] && [[ "${fpr}" =~ ${FPR_RE} ]] && grep -qxF -- "${fpr}" "${allow}"; then
                    ok="${fpr}"; okid="${gid}"
                    VALIDSIG_LINE="${tag} ${kw} ${rest}"
                fi
                good=0 ;;
        esac
    done
    if [ -n "${bad}" ]; then
        printf '%s%s\n' "${bad}" "${unknown:+ ${unknown}}"
        return 1
    fi
    if [ -z "${ok}" ]; then
        printf 'NOSIG%s\n' "${unknown:+ ${unknown}}"
        return 1
    fi
    printf 'GOOD %s %s\n' "${ok}" "${okid}"
}

cmd_verify() {
    local kdirs status verdict vrc=0 grc=0 kw ids why fpr keyid line name path names="" out rc=0 failed=""
    _need_tools gpg gpgv sha256sum
    if [ ! -f "${SUMS}" ] || [ -L "${SUMS}" ]; then
        echo "❌ release ${RELEASE_TAG}: no manifest at ${SUMS}. Run ./devnet-release-sign.sh prepare first." >&2
        exit 1
    fi
    if [ ! -e "${ASC}" ] && [ ! -L "${ASC}" ]; then
        echo "RELEASE_SIG_PENDING"
        echo "release ${RELEASE_TAG}: ${ASC} is absent, so SHA256SUMS is not signed yet." >&2
        _print_sign_hint >&2
        echo "then re-run: ./devnet-release-sign.sh verify" >&2
        exit 3
    fi
    if [ ! -f "${ASC}" ] || [ -L "${ASC}" ]; then
        echo "❌ release ${RELEASE_TAG}: ${ASC} is not a regular file" >&2
        exit 1
    fi
    if [ ! -d "${KEYS_DIR}" ]; then
        echo "❌ RELEASE_KEYS_DIR ${KEYS_DIR} is not a directory (is the tn-node-deployment submodule checked out?)" >&2
        exit 1
    fi

    # 1. The signature, judged against the allow-list.
    _mktmp
    ( umask 077; mkdir -p -- "${TMP_DIR}/gnupg" )
    : > "${TMP_DIR}/keyring.gpg"
    : > "${TMP_DIR}/allow"
    kdirs="${KEYS_DIR}"
    _keyring_add "${KEYS_DIR}"
    if [ -d "${DEVNET_KEYS_DIR}" ] \
        && [ "$(cd "${DEVNET_KEYS_DIR}" && pwd -P)" != "$(cd "${KEYS_DIR}" && pwd -P)" ]; then
        kdirs="${kdirs} + ${DEVNET_KEYS_DIR}"
        _keyring_add "${DEVNET_KEYS_DIR}"
    fi
    if [ "${KEY_COUNT}" -eq 0 ]; then
        echo "❌ no release signing key (*.asc) in ${kdirs}: nothing can verify the release" >&2
        exit 1
    fi
    status="$(GNUPGHOME="${TMP_DIR}/gnupg" gpgv --status-fd 1 --keyring "${TMP_DIR}/keyring.gpg" \
        "${ASC}" "${SUMS}" 2>/dev/null)" || grc=$?
    # Not in $(...): _sig_verdict sets VALIDSIG_LINE, which a subshell would drop.
    _sig_verdict "${TMP_DIR}/allow" <<< "${status}" > "${TMP_DIR}/verdict" || vrc=$?
    verdict="$(cat -- "${TMP_DIR}/verdict")"
    if [ "${vrc}" -ne 0 ]; then
        kw="${verdict%% *}"
        ids=""
        [ "${verdict}" = "${kw}" ] || ids="${verdict#* }"
        case "${kw}" in
            BADSIG)    why="a signature does not match SHA256SUMS (BADSIG)" ;;
            EXPKEYSIG) why="a signature was made by an expired key (EXPKEYSIG)" ;;
            REVKEYSIG) why="a signature was made by a revoked key (REVKEYSIG)" ;;
            EXPSIG)    why="a signature has expired (EXPSIG)" ;;
            ERRSIG)    why="a signature could not be checked (ERRSIG)" ;;
            NO_PUBKEY)
                why="SHA256SUMS.asc carries a signature by key ${ids:-?}, which is not in the allow-list (${kdirs}); devnet accepts no signature by an unlisted key" ;;
            *)         why="no good signature by a key in ${kdirs}" ;;
        esac
        echo "❌ release ${RELEASE_TAG}: SHA256SUMS is not verified: ${why}" >&2
        exit 1
    fi
    # Stricter than the node: gpgv itself must succeed (it fails, for one, on a good
    # signature followed by other OpenPGP data in SHA256SUMS.asc).
    if [ "${grc}" -ne 0 ]; then
        echo "❌ release ${RELEASE_TAG}: SHA256SUMS is not verified: gpgv exited ${grc} (SHA256SUMS.asc must be one clean detached signature)" >&2
        exit 1
    fi
    read -r kw fpr keyid <<< "${verdict}"
    echo "✓ VALIDSIG ${fpr} (key id ${keyid:-?}): a good signature by an allow-listed primary key"
    echo "    ${VALIDSIG_LINE}"

    # 2. The manifest names exactly SUM_NAMES (four files, five with GATEWAY_IMAGE), in order.
    while IFS= read -r line || [ -n "${line}" ]; do
        if [[ ! "${line}" =~ ${SUM_LINE_RE} ]]; then
            echo "❌ release ${RELEASE_TAG}: malformed line in ${SUMS} (want \"<64 hex>  <name>\")" >&2
            exit 1
        fi
        names="${names:+${names} }${line#*  }"
    done < "${SUMS}"
    if [ "${names}" != "${SUM_NAMES}" ]; then
        if [ -n "${GATEWAY_IMAGE}" ] && [ "${names}" = "${SUM_NAMES_NO_GATEWAY}" ]; then
            echo "❌ release ${RELEASE_TAG}: the gateway digest is missing: config.sh sets GATEWAY_IMAGE but ${SUMS} does not list GATEWAY_IMAGE_DIGEST (made before the gateway)" >&2
            echo "   re-run ./devnet-release-sign.sh prepare --force, then sign the new SHA256SUMS" >&2
            exit 1
        fi
        echo "❌ release ${RELEASE_TAG}: ${SUMS} names '${names}', want exactly '${SUM_NAMES}'" >&2
        if [ -z "${GATEWAY_IMAGE}" ]; then
            case " ${names} " in
                *" GATEWAY_IMAGE_DIGEST "*)
                    echo "   the manifest lists a gateway digest but this configuration has no gateway in the release (GATEWAY_IMAGE unset, or TN_GATEWAY_ENABLE not 1): set them, or re-run prepare --force and re-sign" >&2 ;;
            esac
        fi
        exit 1
    fi

    # 3. Every line against the current file: names map to their real paths.
    : > "${TMP_DIR}/check"
    while IFS= read -r line || [ -n "${line}" ]; do
        name="${line#*  }"
        path="$(_path_for "${name}")"
        if [ ! -f "${path}" ]; then
            echo "❌ release ${RELEASE_TAG}: missing ${path} (${name})" >&2
            exit 1
        fi
        printf '%s  %s\n' "${line%%  *}" "${path}" >> "${TMP_DIR}/check"
    done < "${SUMS}"
    out="$(sha256sum -c "${TMP_DIR}/check" 2>&1)" || rc=$?
    if [ "${rc}" -ne 0 ]; then
        printf '%s\n' "${out}" | sed 's/^/    /' >&2
        for name in ${SUM_NAMES}; do
            path="$(_path_for "${name}")"
            printf '%s\n' "${out}" | grep -qxF -- "${path}: OK" || failed="${failed:+${failed} }${name}"
        done
        case " ${failed} " in
            *" genesis.yaml "*|*" committee.yaml "*|*" parameters.yaml "*)
                echo "❌ release ${RELEASE_TAG}: genesis changed since signing: re-run prepare --force and re-sign (mismatch: ${failed})" >&2 ;;
            *" GATEWAY_IMAGE_DIGEST "*)
                echo "❌ release ${RELEASE_TAG}: ${GW} does not match its SHA256SUMS line (mismatch: ${failed}); re-run ./devnet-release-sign.sh prepare" >&2 ;;
            *)
                echo "❌ release ${RELEASE_TAG}: ${IMG} does not match its SHA256SUMS line (mismatch: ${failed:-?}); re-run ./devnet-release-sign.sh prepare" >&2 ;;
        esac
        exit 1
    fi
    echo "✓ SHA256SUMS: ${SUM_NAMES} match the current files"

    # 4. IMAGE_DIGEST is one well-formed line, and the image config.sh deploys.
    if [ "$(awk 'END { print NR }' "${IMG}")" != 1 ] || ! _digest_ok "$(cat -- "${IMG}")"; then
        echo "❌ release ${RELEASE_TAG}: ${IMG} is not one <repository>@sha256:<64 hex> line" >&2
        exit 1
    fi
    printf '%s\n' "${DOCKER_IMAGE:-}" > "${TMP_DIR}/want-image"
    if ! cmp -s "${TMP_DIR}/want-image" "${IMG}"; then
        echo "❌ release ${RELEASE_TAG}: digest mismatch: IMAGE_DIGEST names $(cat -- "${IMG}"), config.sh DOCKER_IMAGE is '${DOCKER_IMAGE:-}'" >&2
        echo "   restore DOCKER_IMAGE, or re-run prepare --force and re-sign for the new image" >&2
        exit 1
    fi
    echo "✓ IMAGE_DIGEST = DOCKER_IMAGE (${DOCKER_IMAGE})"

    # 5. GATEWAY_IMAGE_DIGEST likewise, and the gateway image config.sh deploys.
    if [ -n "${GATEWAY_IMAGE}" ]; then
        if [ "$(awk 'END { print NR }' "${GW}")" != 1 ] || ! _digest_ok "$(cat -- "${GW}")"; then
            echo "❌ release ${RELEASE_TAG}: ${GW} is not one <repository>@sha256:<64 hex> line" >&2
            exit 1
        fi
        printf '%s\n' "${GATEWAY_IMAGE}" > "${TMP_DIR}/want-gateway"
        if ! cmp -s "${TMP_DIR}/want-gateway" "${GW}"; then
            echo "❌ release ${RELEASE_TAG}: digest mismatch: GATEWAY_IMAGE_DIGEST names $(cat -- "${GW}"), config.sh GATEWAY_IMAGE is '${GATEWAY_IMAGE}'" >&2
            echo "   restore GATEWAY_IMAGE, or re-run prepare --force and re-sign for the new image" >&2
            exit 1
        fi
        echo "✓ GATEWAY_IMAGE_DIGEST = GATEWAY_IMAGE (${GATEWAY_IMAGE})"
    fi
    echo "release ${RELEASE_TAG} verified"
}

case "${CMD}" in
    prepare) cmd_prepare ;;
    verify)  cmd_verify ;;
esac
