"""Learning from the learner's own material: the studies (a path from courses), courses, uploads, the plan
per course with feedback, and building it."""

from typing import Any

import anyio
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from yuo.api import schemas as S
from yuo.api.bodies import (
    ArrangeAcceptIn,
    ArrangeIn,
    CourseChangeIn,
    CourseIn,
    MaterialChangeIn,
    MaterialIn,
    PreviewFeedbackIn,
    StudiesIn,
)

MAX_PART = 16 * 1024 * 1024


def router(svc: Any) -> APIRouter:
    r = APIRouter()

    @r.post("/api/studies", status_code=201, response_model=S.StudiesCreated)
    def post_studies(body: StudiesIn) -> dict[str, str]:
        """A path for the learner's studies, with its courses; the material is added next."""
        courses = [c.model_dump(mode="json") for c in body.courses]
        path_id = svc.create_studies(
            body.title, courses, goal=body.goal, content_lang=body.content_lang, depth=body.depth
        )
        return {"path_id": path_id}

    @r.get("/api/studies/{path_id}", response_model=S.StudiesOut)
    def get_studies(path_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.studies_view(path_id)
        return result

    @r.post("/api/studies/{path_id}/courses", status_code=201, response_model=S.CourseOut)
    def post_course(path_id: str, body: CourseIn) -> dict[str, Any]:
        result: dict[str, Any] = svc.add_course(path_id, body.model_dump(mode="json"))
        return result

    @r.post("/api/studies/{path_id}/arrange", response_model=S.StudiesOut)
    def post_arrange(path_id: str, body: ArrangeIn) -> dict[str, Any]:
        """Propose the path's name and courses from the files added so far, or change the proposal."""
        result: dict[str, Any] = svc.arrange_studies(path_id, body.feedback)
        return result

    @r.post("/api/studies/{path_id}/arrange/accept", response_model=S.StudiesOut)
    def post_arrange_accept(path_id: str, body: ArrangeAcceptIn) -> dict[str, Any]:
        """Take the proposal: the courses are made and the files move into them."""
        result: dict[str, Any] = svc.accept_arrangement(path_id, body.title, list(body.adherence))
        return result

    @r.post("/api/studies/{path_id}/start", response_model=S.StudiesOut)
    def post_start(path_id: str) -> dict[str, Any]:
        """The learner confirms: the material is read once and each course planned."""
        result: dict[str, Any] = svc.start_studies(path_id)
        return result

    @r.post("/api/studies/{path_id}/build", response_model=S.StudiesOut)
    def post_build(path_id: str) -> dict[str, Any]:
        """The learner accepts the plan: one branch per course, and the first lessons are written."""
        result: dict[str, Any] = svc.build_studies(path_id)
        return result

    @r.post("/api/studies/{path_id}/links/retry", response_model=S.StudiesOut)
    def post_links_retry(path_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.retry_links(path_id)
        return result

    @r.patch("/api/courses/{course_id}", response_model=S.CourseOut)
    def patch_course(course_id: str, body: CourseChangeIn) -> dict[str, Any]:
        change = body.model_dump(mode="json", exclude_unset=True)
        result: dict[str, Any] = svc.update_course(course_id, change)
        return result

    @r.delete("/api/courses/{course_id}", status_code=204)
    def delete_course(course_id: str) -> Response:
        svc.archive_course(course_id)
        return Response(status_code=204)

    @r.post("/api/courses/{course_id}/feedback", response_model=S.CourseOut)
    def post_course_feedback(course_id: str, body: PreviewFeedbackIn) -> dict[str, Any]:
        """What is missing, wrong or should go deeper in this course's plan: it is revised with it."""
        result: dict[str, Any] = svc.course_feedback(course_id, body.text)
        return result

    @r.post("/api/courses/{course_id}/undo", response_model=S.CourseOut)
    def post_course_undo(course_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.undo_course(course_id)
        return result

    @r.post("/api/courses/{course_id}/retry", response_model=S.CourseOut)
    def post_course_retry(course_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.retry_course(course_id)
        return result

    @r.post("/api/materials/{material_id}/read-pages", response_model=S.MaterialOut)
    def post_read_pages(material_id: str) -> dict[str, Any]:
        """Read a PDF's pages with little text (formulas, figures) from their images, with the generation model."""
        result: dict[str, Any] = svc.read_pages(material_id)
        return result

    @r.post("/api/materials/{material_id}/retry", response_model=S.MaterialOut)
    def post_retry_material(material_id: str) -> dict[str, Any]:
        """Read or transcribe a file that failed again, from what was uploaded."""
        result: dict[str, Any] = svc.retry_material(material_id)
        return result

    @r.post("/api/courses/{course_id}/mock-exam", response_model=S.AssessmentOut | S.JobStarted)
    def post_mock_exam(course_id: str) -> dict[str, Any]:
        """A mock exam over the whole course; a job id while some skills' questions are still being written."""
        result: dict[str, Any] = svc.start_mock_exam(course_id)
        return result

    @r.get("/api/courses/{course_id}/coverage", response_model=S.CoverageOut)
    def get_coverage(course_id: str) -> dict[str, Any]:
        """Which parts of each file the path teaches, which it leaves out (and why), which it does not use yet."""
        result: dict[str, Any] = svc.coverage(course_id)
        return result

    @r.post("/api/courses/{course_id}/updates/{update_id}/apply", response_model=S.CourseOut)
    def post_course_update_apply(course_id: str, update_id: str) -> dict[str, Any]:
        """Yes to what new files add to a built course: those lessons are rewritten with them, new skills added."""
        result: dict[str, Any] = svc.decide_update(course_id, update_id, True)
        return result

    @r.post("/api/courses/{course_id}/updates/{update_id}/dismiss", response_model=S.CourseOut)
    def post_course_update_dismiss(course_id: str, update_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.decide_update(course_id, update_id, False)
        return result

    @r.post("/api/courses/{course_id}/materials", status_code=201, response_model=S.MaterialOut)
    def post_material(course_id: str, body: MaterialIn) -> dict[str, Any]:
        """Start an upload; the file follows in parts (`PUT /api/materials/{id}/upload`)."""
        result: dict[str, Any] = svc.new_material(course_id, body.file_name, body.size, body.role, body.title)
        return result

    @r.put("/api/materials/{material_id}/upload", response_model=S.MaterialOut)
    async def put_upload(material_id: str, offset: int, request: Request) -> dict[str, Any]:
        """One part of the file as the raw body, at `offset` (the bytes the server has); 409 says where to resume."""
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_PART:
                raise HTTPException(413, "a part can be at most 16 MB")
        result: dict[str, Any] = await anyio.to_thread.run_sync(
            svc.upload_part, material_id, offset, bytes(data)
        )
        return result

    @r.get("/api/materials/{material_id}", response_model=S.MaterialOut)
    def get_material(material_id: str) -> dict[str, Any]:
        result: dict[str, Any] = svc.material_view(material_id)
        return result

    @r.patch("/api/materials/{material_id}", response_model=S.MaterialOut)
    def patch_material(material_id: str, body: MaterialChangeIn) -> dict[str, Any]:
        """Correct a file's role (textbook, slides, ...) or name."""
        result: dict[str, Any] = svc.update_material(material_id, body.role, body.title)
        return result

    @r.delete("/api/materials/{material_id}", status_code=204)
    def delete_material(material_id: str) -> Response:
        svc.delete_material(material_id)
        return Response(status_code=204)

    @r.get("/api/materials/{material_id}/file", response_class=FileResponse)
    def get_material_file(material_id: str) -> FileResponse:
        """The learner's own file (a recording as its audio), opened at a page or minute by the client."""
        with svc.material_file(material_id) as (path, media_type, name):
            return FileResponse(
                path, media_type=media_type, filename=name, content_disposition_type="inline",
                headers={"Cache-Control": "private, max-age=3600"},
            )  # fmt: skip

    return r
