"""Write the package's JSON Schemas (spec §1, 2020-12) from yuo/sharing/records.py: `uv run scripts/gen_package_schemas.py`
(`--check` to compare only)."""

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from yuo.sharing import records as R

OUT = Path(__file__).resolve().parents[1] / "docs" / "spec" / "schemas"
BASE = "urn:yuo:package:1.0"  # an identifier, not a web address


def schemas() -> dict[str, str]:
    models: dict[str, type[BaseModel]] = {
        "manifest": R.Manifest,
        **{f"record.{k}": m for k, m in R.KINDS.items()},
    }
    out = {}
    for name, model in models.items():
        schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{BASE}:{name}"}
        schema |= model.model_json_schema(mode="validation")
        out[f"{name}.schema.json"] = json.dumps(schema, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    return out


def main() -> int:
    wanted = schemas()
    if "--check" in sys.argv:
        stale = [
            n
            for n, text in wanted.items()
            if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != text
        ]
        extra = sorted(p.name for p in OUT.glob("*.json") if p.name not in wanted)
        if stale or extra:
            print(
                f"package schemas out of date ({stale + extra}): run `uv run scripts/gen_package_schemas.py`"
            )
            return 1
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("*.json"):
        p.unlink()
    for name, text in wanted.items():
        (OUT / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(wanted)} schemas to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
