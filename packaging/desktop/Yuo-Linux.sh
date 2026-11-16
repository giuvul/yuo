#!/usr/bin/env bash
# Yuo for Linux: double-click (or "Run as program"). Installs uv (pinned, hash-checked), then Yuo, then opens it.
set -euo pipefail
UV_VERSION=0.13.1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YUO_HOME="${YUO_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/yuo-desktop}"
case "$(uname -m)" in
  x86_64|amd64) ASSET=uv-x86_64-unknown-linux-gnu; SHA=eadd9d27c134ab5ac1ffd4473b97a741407f3ea238288f03121fc4deddf90220 ;;
  aarch64|arm64) ASSET=uv-aarch64-unknown-linux-gnu; SHA=9041c73c99fdc5892cf128140beb354eca9231d502068cc36e6cb53a8e59ad14 ;;
  *) echo "  Yuo needs a 64-bit Intel/AMD or ARM computer."; read -rp "  Press Enter to close." _; exit 1 ;;
esac
UV="$YUO_HOME/uv/$UV_VERSION/uv"
fail() { echo; echo "  $1"; echo "  Details: $YUO_HOME/logs/launcher.log"; read -rp "  Press Enter to close." _; exit 1; }
if [ ! -x "$UV" ]; then
  echo "  Getting uv $UV_VERSION (the tool that installs Python and Yuo)..."
  mkdir -p "$YUO_HOME/uv/$UV_VERSION"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  curl -fsSL --proto '=https' -o "$TMP/uv.tar.gz" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ASSET.tar.gz" \
    || fail "Could not download uv. Check the internet connection and start Yuo again."
  echo "$SHA  $TMP/uv.tar.gz" | sha256sum -c --quiet - || fail "The uv download did not match its checksum; nothing was installed."
  tar -xzf "$TMP/uv.tar.gz" -C "$TMP"
  mv "$TMP/$ASSET/uv" "$UV"
fi
export YUO_HOME YUO_UV="$UV" UV_PYTHON_INSTALL_DIR="$YUO_HOME/python" UV_CACHE_DIR="$YUO_HOME/cache" UV_NO_CONFIG=1
ls -d "$YUO_HOME"/python/cpython-3.14* >/dev/null 2>&1 || echo "  Getting Python 3.14 (first start only, about 30 MB)..."
"$UV" run --no-project --quiet --python 3.14 --python-preference only-managed "$HERE/app/launcher.py" || fail "Yuo stopped with an error."
