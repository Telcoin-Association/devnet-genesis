#!/usr/bin/env bash
#
# build-probe-bin.sh — build the mdbx-writeback-probe release binary for the one-VM GCE probe
# (benchmark-probe.sh) inside a Debian bookworm Rust container.
#
# Why a container: the binary must start on the probe VM's Ubuntu 24.04 (glibc 2.39). A binary linked on
# a build host with a newer glibc asks for symbol versions the VM does not have and will not start.
# Bookworm has glibc 2.36, so what it links runs on noble. The probe crate's build script runs bindgen,
# which needs libclang, so the container installs libclang-dev before cargo runs.
#
# The crate is mounted READ-ONLY at /src. Cargo's home (registry and git checkouts) and the target dir
# live under the output dir, so a second build reuses them and nothing is written anywhere else. The
# container runs as root (apt needs it) and hands the output dir back to the caller's uid at the end.
# Network: the container fetches the image (once), the apt packages and the crates Cargo.lock pins.
#
# Output (in --out):
#   mdbx-writeback-probe   the binary
#   build-info.txt         key=value lines: binary_sha256, source_sha256, image, image_id, glibc_max,
#                          rustc, built_utc (benchmark-probe.sh reads it and records it in the manifest)
# stdout ends with two lines the caller can grep:
#   BINARY_SHA256 <hex>
#   SOURCE_SHA256 <hex>
# The source hash is the sha256 of a list of "<sha256>  <path>" lines, one per file of the crate's
# Cargo.toml, Cargo.lock and src/ (paths relative to the crate, sorted, LC_ALL=C), so it changes when any
# source file changes and does not depend on where the crate lives.
#
# Usage:
#   build-probe-bin.sh --crate <dir> --out <dir> [--image <ref>] [--print]
#     --crate  the probe crate (Cargo.toml, Cargo.lock, src/)
#     --out    output directory (created if absent)
#     --image  the build image [rust:1.94-bookworm]; must be a Debian bookworm image
#     --print  print the docker command and the container script; run nothing, write nothing
# Needs: docker (local daemon), sha256sum or shasum, and find/sort.
set -euo pipefail

CRATE="" OUT="" IMAGE="rust:1.94-bookworm" PRINT=0
BIN_NAME="mdbx-writeback-probe"
# The newest glibc symbol version the probe VM's Ubuntu 24.04 provides.
GLIBC_LIMIT="2.39"

die() { echo "build-probe-bin: $*" >&2; exit 2; }

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        --crate) [ $# -ge 2 ] || die "--crate needs a value"; CRATE="$2"; shift 2 ;;
        --out) [ $# -ge 2 ] || die "--out needs a value"; OUT="$2"; shift 2 ;;
        --image) [ $# -ge 2 ] || die "--image needs a value"; IMAGE="$2"; shift 2 ;;
        --print) PRINT=1; shift ;;
        *) die "unknown argument '$1' (try --help)" ;;
    esac
done
[ -n "${CRATE}" ] || die "--crate is required"
[ -n "${OUT}" ] || die "--out is required"
case "${IMAGE}" in *bookworm*) ;; *) die "--image '${IMAGE}' is not a bookworm image (the binary must link against glibc <= ${GLIBC_LIMIT})" ;; esac
[ -f "${CRATE}/Cargo.toml" ] && [ -f "${CRATE}/Cargo.lock" ] && [ -d "${CRATE}/src" ] \
    || die "${CRATE} is not the probe crate (needs Cargo.toml, Cargo.lock and src/)"
CRATE="$(cd "${CRATE}" && pwd -P)"

sha256_of() {   # sha256_of <file> — the hex digest only
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{ print $1 }'
    else shasum -a 256 "$1" | awk '{ print $1 }'; fi
}

# source_sha256 — the crate's source hash (see the header).
source_sha256() {
    local list f
    list="$(mktemp)"
    (
        cd "${CRATE}"
        { printf '%s\n' Cargo.toml Cargo.lock; find src -type f; } | LC_ALL=C sort | while IFS= read -r f; do
            printf '%s  %s\n' "$(sha256_of "${f}")" "${f}"
        done
    ) > "${list}"
    sha256_of "${list}"
    rm -f "${list}"
}

# The container's script. $1 = the caller's uid:gid, $2 = the glibc limit.
# shellcheck disable=SC2016  # the container's shell expands these
CONTAINER_SCRIPT='set -eu
trap "chown -R \"$1\" /out 2>/dev/null || true" EXIT
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends libclang-dev >/dev/null
export CARGO_HOME=/out/cargo-home CARGO_TARGET_DIR=/out/target
cargo build --release --locked --manifest-path /src/Cargo.toml
cp /out/target/release/mdbx-writeback-probe /out/mdbx-writeback-probe.new
mv -f /out/mdbx-writeback-probe.new /out/mdbx-writeback-probe
g="$(objdump -T /out/mdbx-writeback-probe | grep -o "GLIBC_[0-9][0-9.]*" | sed "s/^GLIBC_//" | sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)"
echo "glibc_max=${g}" > /out/.glibc
rustc --version | sed "s/^/rustc=/" >> /out/.glibc
lo="$(printf "%s\n%s\n" "${g}" "$2" | sort -t. -k1,1n -k2,2n | tail -n 1)"
[ "${lo}" = "$2" ] || { echo "the binary needs glibc ${g} > $2" >&2; exit 3; }'

DOCKER_ARGV=(docker run --rm -v "${CRATE}:/src:ro" -v "<out>:/out" "${IMAGE}" bash -c "<container script>" build "<uid>:<gid>" "${GLIBC_LIMIT}")

if [ "${PRINT}" = 1 ]; then
    echo "== build-probe-bin plan (nothing is run or written)"
    echo "crate: ${CRATE}"
    echo "out:   ${OUT}"
    printf 'docker:'; printf ' %q' "${DOCKER_ARGV[@]}"; printf '\n'
    echo "----- container script -----"
    printf '%s\n' "${CONTAINER_SCRIPT}"
    echo "----- end container script -----"
    echo "then: build-info.txt in the out dir, BINARY_SHA256 and SOURCE_SHA256 on stdout"
    exit 0
fi

command -v docker >/dev/null 2>&1 || die "docker is not on PATH"
mkdir -p "${OUT}"
OUT="$(cd "${OUT}" && pwd -P)"
SRC_SHA="$(source_sha256)"
echo "build-probe-bin: crate ${CRATE} (source sha256 ${SRC_SHA}), image ${IMAGE}, out ${OUT}"
rm -f "${OUT}/${BIN_NAME}" "${OUT}/build-info.txt" "${OUT}/.glibc"
docker run --rm -v "${CRATE}:/src:ro" -v "${OUT}:/out" "${IMAGE}" \
    bash -c "${CONTAINER_SCRIPT}" build "$(id -u):$(id -g)" "${GLIBC_LIMIT}"
[ -s "${OUT}/${BIN_NAME}" ] || die "the container finished but ${OUT}/${BIN_NAME} is missing"
[ "${SRC_SHA}" = "$(source_sha256)" ] || die "the crate's sources changed during the build; build again"
BIN_SHA="$(sha256_of "${OUT}/${BIN_NAME}")"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "${IMAGE}" 2>/dev/null)" || IMAGE_ID=""
{
    printf 'binary_sha256=%s\n' "${BIN_SHA}"
    printf 'source_sha256=%s\n' "${SRC_SHA}"
    printf 'image=%s\n' "${IMAGE}"
    printf 'image_id=%s\n' "${IMAGE_ID}"
    cat "${OUT}/.glibc"
    printf 'built_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${OUT}/build-info.txt"
rm -f "${OUT}/.glibc"
cat "${OUT}/build-info.txt"
echo "BINARY_SHA256 ${BIN_SHA}"
echo "SOURCE_SHA256 ${SRC_SHA}"
