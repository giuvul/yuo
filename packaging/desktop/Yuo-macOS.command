#!/usr/bin/env bash
# Yuo for macOS (Apple silicon): double-click; the first time, allow it in System Settings > Privacy & Security. Installs uv (pinned, hash-checked), then Yuo, then opens it.
# UNTESTED: shipped without a test on a real Mac; please report what happens.
set -euo pipefail
UV_VERSION=0.13.1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YUO_HOME="${YUO_HOME:-$HOME/Library/Application Support/Yuo}"
case "$(uname -m)" in
  arm64) ASSET=uv-aarch64-apple-darwin; SHA=cfe454573412ff7380d15fc7dae5997ab53ffce72fce0a78e91ddbc84001acd2 ;;
  *) echo "  Yuo for macOS needs a Mac with Apple silicon (M1 or later): some of its parts are not built for Intel Macs."; read -rp "  Press Enter to close." _; exit 1 ;;
esac
UV="$YUO_HOME/uv/$UV_VERSION/uv"
fail() { echo; echo "  $1"; echo "  Details: $YUO_HOME/logs/launcher.log"; read -rp "  Press Enter to close." _; exit 1; }
if [ ! -x "$UV" ]; then
  echo "  Getting uv $UV_VERSION (the tool that installs Python and Yuo)..."
  mkdir -p "$YUO_HOME/uv/$UV_VERSION"
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  curl -fsSL --proto '=https' -o "$TMP/uv.tar.gz" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ASSET.tar.gz" \
    || fail "Could not download uv. Check the internet connection and start Yuo again."
  echo "$SHA  $TMP/uv.tar.gz" | shasum -a 256 -c --quiet - || fail "The uv download did not match its checksum; nothing was installed."
  tar -xzf "$TMP/uv.tar.gz" -C "$TMP"
  mv "$TMP/$ASSET/uv" "$UV"
fi
export YUO_HOME YUO_UV="$UV" UV_PYTHON_INSTALL_DIR="$YUO_HOME/python" UV_CACHE_DIR="$YUO_HOME/cache" UV_NO_CONFIG=1
ls -d "$YUO_HOME"/python/cpython-3.14* >/dev/null 2>&1 || echo "  Getting Python 3.14 (first start only, about 30 MB)..."
"$UV" run --no-project --quiet --python 3.14 --python-preference only-managed "$HERE/app/launcher.py" || fail "Yuo stopped with an error."
