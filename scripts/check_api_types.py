"""CI step: the web client's types must match the exported OpenAPI (`npm run api:types` gives no diff)."""

import hashlib
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
TYPES = WEB / "src" / "api" / "schema.d.ts"


def main() -> int:
    if not (WEB / "tools" / "api-types" / "node_modules").exists():
        subprocess.run(["npm", "ci", "--prefix", "tools/api-types"], cwd=WEB, check=True)
    before = hashlib.sha256(TYPES.read_bytes()).hexdigest() if TYPES.exists() else ""
    subprocess.run(["npm", "run", "-s", "api:types"], cwd=WEB, check=True, capture_output=True)
    if hashlib.sha256(TYPES.read_bytes()).hexdigest() != before:
        print("web/src/api/schema.d.ts was out of date and has been regenerated: review and keep the change")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
