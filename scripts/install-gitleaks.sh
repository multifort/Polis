#!/usr/bin/env sh
set -eu

# Install a pinned gitleaks binary for local pre-commit secret scanning.
# Override with:
#   GITLEAKS_VERSION=8.28.0 INSTALL_DIR=/usr/local/bin scripts/install-gitleaks.sh

GITLEAKS_VERSION="${GITLEAKS_VERSION:-8.28.0}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

os="$(uname -s | tr '[:upper:]' '[:lower:]')"
arch="$(uname -m)"

case "$os" in
  darwin) os="darwin" ;;
  linux) os="linux" ;;
  *)
    echo "Unsupported OS: $os" >&2
    exit 1
    ;;
esac

case "$arch" in
  x86_64 | amd64) arch="x64" ;;
  arm64 | aarch64) arch="arm64" ;;
  *)
    echo "Unsupported architecture: $arch" >&2
    exit 1
    ;;
esac

archive="gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz"
base_url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"
tmp_dir="$(mktemp -d)"

cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

mkdir -p "$INSTALL_DIR"

echo "Downloading ${archive}"
curl -fsSL "${base_url}/${archive}" -o "${tmp_dir}/${archive}"

if command -v shasum >/dev/null 2>&1; then
  echo "Verifying checksum"
  curl -fsSL "${base_url}/gitleaks_${GITLEAKS_VERSION}_checksums.txt" \
    -o "${tmp_dir}/checksums.txt"
  expected="$(grep " ${archive}$" "${tmp_dir}/checksums.txt" | awk '{print $1}')"
  actual="$(shasum -a 256 "${tmp_dir}/${archive}" | awk '{print $1}')"
  if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    echo "Checksum verification failed for ${archive}" >&2
    exit 1
  fi
fi

tar -xzf "${tmp_dir}/${archive}" -C "$tmp_dir" gitleaks
install -m 0755 "${tmp_dir}/gitleaks" "${INSTALL_DIR}/gitleaks"

echo "Installed $("${INSTALL_DIR}/gitleaks" version) at ${INSTALL_DIR}/gitleaks"
case ":$PATH:" in
  *":${INSTALL_DIR}:"*) ;;
  *)
    echo "Add ${INSTALL_DIR} to PATH before running pre-commit hooks." >&2
    ;;
esac
