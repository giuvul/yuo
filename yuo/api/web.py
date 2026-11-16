"""The built web app served by the API process (one origin for the app, the API and the passkeys).

Files under the build directory are served as they are; any other path that is not `/api` gets `index.html`, so
the app's own routes work on reload. Hashed assets are cached for a year, the shell never (a new release shows
at once).
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


def mount(app: FastAPI, root: Path | None) -> None:
    if root is None:
        return
    base = root.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def get_web(path: str) -> FileResponse:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "not found")
        target = (base / path).resolve()
        if path and target.is_file() and target.is_relative_to(base):
            immutable = target.is_relative_to(base / "assets")
            cache = "public, max-age=31536000, immutable" if immutable else "no-cache"
            return FileResponse(target, headers=HEADERS | {"Cache-Control": cache})
        return FileResponse(base / "index.html", headers=HEADERS | {"Cache-Control": "no-cache"})
