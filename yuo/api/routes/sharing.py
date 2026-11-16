"""Packages (spec 1.0): export, upload, import."""

import re
import uuid
from typing import Any

import anyio
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from yuo.api import schemas as S
from yuo.api.bodies import (
    ExportIn,
    ImportIn,
)

log = structlog.get_logger(__name__)
MAX_UPLOAD = 10 * 1024**3


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.post("/api/paths/{path_id}/export-preview", response_model=S.ExportPreviewOut)
    def post_export_preview(path_id: str, body: ExportIn) -> dict[str, Any]:
        result: dict[str, Any] = svc.export_preview(
            path_id,
            profile=body.profile,
            components=set(body.components) or None,
            include_personal=body.include_personal,
        )
        return result

    @r.post("/api/paths/{path_id}/export", response_class=FileResponse)
    def post_export(path_id: str, body: ExportIn) -> FileResponse:
        """The package as a `.yuo.zip` download (removed from the server once sent)."""
        out = svc.package_dir / f"export-{uuid.uuid4().hex}.yuo.zip"
        manifest = svc.export_package(
            path_id, out, profile=body.profile, components=set(body.components) or None,
            include_personal=body.include_personal, formats=body.formats,
        )  # fmt: skip
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", manifest["title"]).strip("-") or "path"
        return FileResponse(
            out,
            media_type="application/zip",
            filename=f"{name}.yuo.zip",
            background=BackgroundTask(out.unlink, missing_ok=True),
        )

    @r.post("/api/packages", response_model=S.PackageUploadOut)
    async def post_package(request: Request) -> dict[str, Any]:
        """Upload a package as the raw request body (`application/zip`); answers with what an import would do.
        Nothing is imported until `POST /api/packages/{token}/import`."""
        svc.sweep_packages()  # uploads older than a day that were never imported or cancelled
        token = uuid.uuid4().hex
        target = svc.upload_file(token)
        size = 0
        with target.open("wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    f.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(413, "the package is larger than 10 GB")
                f.write(chunk)
        try:
            preview = await anyio.to_thread.run_sync(svc.preview_package, target)
        except Exception as e:  # PackageError and friends: refused, shown to the learner
            log.warning("package.refused", error=str(e)[:300], exc_info=True)
            svc.drop_upload(token)
            return {"token": token, "preview": None, "error": str(e)[:500]}
        return {"token": token, "preview": preview, "error": None}

    @r.post("/api/packages/{token}/import", response_model=S.ImportedOut)
    def post_import(token: str, body: ImportIn) -> dict[str, str]:
        file = svc.upload_file(token)
        if not file.exists():
            raise HTTPException(404, "upload the package again")
        try:
            return {"path_id": svc.import_package(file, mode=body.mode)}
        finally:
            svc.drop_upload(token)

    @r.delete("/api/packages/{token}", status_code=204)
    def delete_package(token: str) -> None:
        svc.drop_upload(token)

    return r
