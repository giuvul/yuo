"""Write the API's OpenAPI document for the web client: `uv run scripts/export_openapi.py` (`--check`)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from yuo.api.app import create_app
from yuo.app.auth_model import Origin

TARGET = Path(__file__).resolve().parents[1] / "web" / "src" / "api" / "openapi.json"


def main() -> int:
    # a stand-in auth: the routes are registered from its origin alone, so the sign-in routes are in the document
    auth = SimpleNamespace(origin=Origin.parse("http://localhost:18765"))
    desktop = SimpleNamespace(
        control_token="", link=str, quit=lambda: None, reopen=bool
    )  # the desktop routes appear in the schema too
    app = create_app(version="dev", health=dict, service=object(), auth=auth, desktop=desktop)
    text = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print(f"{TARGET} is out of date: run `uv run scripts/export_openapi.py`")
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
