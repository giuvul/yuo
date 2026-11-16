# Desktop release

Yuo on a learner's own computer: one zip, one double-click file per OS, no terminal typing. This folder is what goes into the zip; `scripts/build_desktop.py` assembles it.

| File | What it does |
|---|---|
| `Yuo-Windows.bat` | Fetches uv (pinned version, SHA-256 written in the file), checks Smart App Control, runs the launcher |
| `Yuo-macOS.command` | The same for Apple silicon Macs. **Untested**: shipped without a run on a real Mac |
| `Yuo-Linux.sh` | The same for Linux x64 and arm64; tested on the build server |
| `launcher.py` | Standard library only: install, start, update, roll back (see its docstring) |
| `guide/index.html` | What the OS warnings look like and what to click; where data lives |

## Build

The release workflow (`.github/workflows/release.yml`) builds and publishes it on every version tag. By hand:

    (cd web && npm run build)
    uv run scripts/third_party_licenses.py
    uv run scripts/build_desktop.py --base-url https://github.com/giuvul/yuo/releases/download/vX.Y.Z \
        --feed https://github.com/giuvul/yuo/releases/latest/download/latest.json \
        --notes-url https://github.com/giuvul/yuo/releases/tag/vX.Y.Z

Writes `dist/desktop/yuo-X.Y.Z-desktop.zip`, `SHA256SUMS` and `latest.json`. The release publishes all three,
with a build provenance attestation (Sigstore) for each file.

## Release feed (`latest.json`)

    {"version": "1.0.1", "published_at": "2026-11-20T10:00:00Z", "notes_url": "https://...",
     "desktop": {"url": "https://.../yuo-1.0.1-desktop.zip", "sha256": "<64 hex>", "bytes": 3012345}}

The installed app reads it at most once a day (off in Settings), downloads the zip over https only,
checks size and SHA-256, and stages it in `data/updates/`. "Restart to install" exits with code 75; the launcher
installs the staged release beside the current one and starts it. The new version becomes current only once it
serves; if it stops first, the launcher restores the backup the migration made and starts the previous version.

## Pinned uv

uv 0.13.1 (2026-10-14). To move the pin: pick a release at least two weeks old, take the six `.sha256` files
from its GitHub release (Windows x64/arm64 zip, macOS arm64/x64 and Linux x64/arm64 tar.gz) and update the
version and hashes in the three scripts.

## Platforms

- Windows 10 (1803+) and 11, x64 and arm64: uses the built-in `curl.exe`, `tar.exe` and `certutil`. Confirmed
  working on Windows (install, setup, Codex, lessons and a skill check).
- macOS: Apple silicon only. Several dependencies publish no CPython 3.14 wheels for Intel Macs.
- Linux: x64 and arm64, glibc.
- Video lessons are not part of the desktop release yet (the renderer needs Node and a browser); lessons are
  readings with practice, and the tutor works.
