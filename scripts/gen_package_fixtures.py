"""Write the package conformance fixtures (spec §14) to docs/spec/fixtures: `uv run scripts/gen_package_fixtures.py`."""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.package_fixtures import EXPECT, build  # noqa: E402

OUT = ROOT / "docs" / "spec" / "fixtures"


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    build(OUT)
    (OUT / "expected.json").write_text(json.dumps(EXPECT, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(EXPECT)} fixtures to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
