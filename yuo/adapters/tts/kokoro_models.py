"""The Kokoro voice model files: where they come from, their pinned hashes, and the download.

Standard library only: the container build runs this file on its own (`python kokoro_models.py DIR`), so the
image layer holding the model is rebuilt only when this file changes, not with every release of Yuo.
"""

import sys
from pathlib import Path

MODEL_SHA256 = {
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{name}"


def fetch_models(model_dir: Path) -> list[str]:
    """Download the voice model files that are missing, each checked against its pinned SHA-256 before it is
    kept. Returns the names downloaded."""
    import hashlib
    import urllib.request

    model_dir.mkdir(parents=True, exist_ok=True)
    got = []
    for name, sha in MODEL_SHA256.items():
        target = model_dir / name
        if target.exists():
            continue
        tmp = model_dir / f".{name}.part"
        digest = hashlib.sha256()
        with urllib.request.urlopen(MODEL_URL.format(name=name), timeout=60) as r, tmp.open("wb") as f:  # noqa: S310 (fixed https URL)
            while chunk := r.read(1 << 20):
                digest.update(chunk)
                f.write(chunk)
        if digest.hexdigest() != sha:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"{name}: checksum mismatch, download refused")
        tmp.replace(target)
        got.append(name)
    return got


if __name__ == "__main__":
    got = fetch_models(Path(sys.argv[1]))
    print(f"{sys.argv[1]}: {', '.join(got) if got else 'already there'}")
