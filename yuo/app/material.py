"""Learning from the learner's own material. A part of the application service.

A path built from courses: one course per exam, each with files (books, slides, notes, recordings). The
learner uploads them, Yuo reads them (free, on this machine), and when the learner says go, digests them, plans
each course on its material and links the courses. The learner checks the plan per course, asks for changes
in their own words, and builds it: one branch per course, each skill anchored in the chunks it is built on.

Jobs: `material` (one file: read, then transcribe, digest and outline once the path is started; on the heavy
thread), `course` (one course's plan, or its revision), `course_links` (the links between courses).
"""

import json
import re
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import structlog

from yuo.adapters.ingest import kind_of, read_document
from yuo.adapters.ingest.pdf import page_images
from yuo.app.context import AppContext, Part
from yuo.app.material_stages import (
    ROLE_NAMES,
    arrange_spec,
    course_revise_spec,
    course_spec,
    digest_spec,
    links_spec,
    outline_spec,
    vision_spec,
)
from yuo.app.ports import Buffer, Learners, Models, PathInputs
from yuo.app.repo import get_path, path_state, save_path_state
from yuo.core import clock
from yuo.core.documents import Extracted, Page, ReadError, TranscriptionInterrupted
from yuo.core.enums import DataClass, EntityKind
from yuo.core.errors import Conflict, InvalidInput, NotFound
from yuo.core.hashing import bytes_hash
from yuo.core.ids import new_id
from yuo.curriculum.courses import CourseOutline
from yuo.curriculum.tree import (
    CODE,
    BranchDraft,
    LessonPlan,
    ObjectiveDraft,
    SkillDraft,
    TreeDraft,
    apply_tree,
)
from yuo.generation.jobs import MAX_ATTEMPTS, URGENT_PRIORITY, Job, enqueue
from yuo.generation.runner import StageFailed
from yuo.material import align as al
from yuo.material import chunks as ch
from yuo.material.drafts import ChunkDigest
from yuo.setup import settings

log = structlog.get_logger(__name__)

ROLES = ("textbook", "slides", "lecture", "notes", "exercises", "exams", "other")
ADHERENCE = ("only", "grounded", "open")
MAX_UPLOAD = 4 * 1024**3  # one file; a long lecture video is about 2 GB
MAX_PART = 16 * 1024**2  # one upload request
DIGEST_BUDGET = 6000  # chunk tokens per digest call
LESSON_BUDGET = 9000  # chunk tokens a lesson is written from
VISION_MAX_PAGES = (
    300  # pages of one file read from their images: those with little text, then the most formulas
)
VISION_BATCH = 3  # page images per call (a whole page written out is up to about 1500 tokens)
EXAMPLE_CHARS = 3000  # of one past exam or exercise chunk, as a style example for questions
FEEDBACK_MAX = 2000
ROUNDS_MAX = 12
WAITING = ("uploading", "reading", "read", "transcribing", "digesting", "outlining")
RECORDING = ("audio", "video")
DOC_PRIORITY = 10  # a document is read before the next recording is transcribed: it takes seconds


def _rows(c: sqlite3.Connection, sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def _slug(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24].strip("-") or "course"
    base = re.sub(r"^[^a-z0-9]+", "", base) or "course"
    code, n = base, 2
    while code in taken or not CODE.match(code):
        code = f"{base}-{n}"
        n += 1
    return code


def _guess_role(file_name: str, kind: str) -> str:
    name = file_name.lower()
    if kind in ("audio", "video"):
        return "lecture"
    if kind == "pptx" or any(w in name for w in ("slide", "lucid", "diapo", "folien")):
        return "slides"
    if any(w in name for w in ("exam", "esame", "examen", "prüfung", "pruefung", "compito", "test")):
        return "exams"
    if any(w in name for w in ("exercis", "eserciz", "ejercic", "übung", "uebung", "problem")):
        return "exercises"
    if any(w in name for w in ("note", "appunt", "apunte", "notiz", "dispens")):
        return "notes"
    return "textbook"


class Materials(Part):
    def __init__(
        self, ctx: AppContext, *, learners: Learners, models: Models, paths: PathInputs, buffer: Buffer
    ) -> None:
        super().__init__(ctx)
        self.learners = learners
        self.models = models
        self.paths = paths
        self.buffer = buffer

    @property
    def uploads(self) -> Path:
        d = self.media_dir.parent / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- courses -------------------------------------------------------------------------------------

    def create_studies(
        self, title: str, courses: list[dict[str, Any]], *, goal: str = "", content_lang: str | None = None
    ) -> str:
        """A path for the learner's studies, with its courses; the material is added next. Without courses, the
        learner adds all of it first, to one holding course, and the path's name and courses are proposed from
        it (`arrange_studies`)."""
        title = title.strip() or "My material"
        learner = self.learners.ensure_learner()
        if not courses:
            # choosing "my own material" opens the upload screen at once: a path from files still untouched
            # (no file, no proposal) is opened again rather than a second empty one made
            with self.readers.connection() as c:
                row = c.execute(
                    "SELECT p.id FROM path p JOIN course k ON k.path_id = p.id AND k.archived_at IS NULL "
                    "AND json_extract(k.extensions, '$.yuo.inbox') = 1 WHERE p.learner_id = ? "
                    "AND p.status = 'draft' AND json_extract(p.extensions, '$.yuo.arrange.status') = 'collecting' "
                    "AND json_array_length(json_extract(p.extensions, '$.yuo.arrange.rounds')) = 0 "
                    "AND NOT EXISTS (SELECT 1 FROM material m WHERE m.path_id = p.id) "
                    "ORDER BY p.created_at DESC LIMIT 1",
                    (learner,),
                ).fetchone()
            if row is not None:
                return str(row[0])
        path_id = new_id()

        def unit(c: sqlite3.Connection) -> None:
            lang = (
                content_lang
                or c.execute("SELECT default_content_lang FROM learner WHERE id = ?", (learner,)).fetchone()[
                    0
                ]
            )
            now = clock.now()
            c.execute(
                "INSERT INTO path (id, code, learner_id, title, subject, goal, goal_type, target_date, difficulty, "
                "content_lang, status, authorship, acquired_via, package_id, translation_of_path_id, "
                "structure_version, licence, authors, extensions, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'exam', NULL, 'intermediate', ?, 'draft', 'generated', 'local', NULL, NULL, "
                "0, 'CC-BY-4.0', '[]', json(?), ?, ?)",
                (
                    path_id,
                    f"path-{path_id[-12:]}",
                    learner,
                    title,
                    title,
                    goal or title,
                    lang,
                    json.dumps({"yuo": {"origin": "courses", "preview": {"status": "collecting"}}}),
                    now,
                    now,
                ),
            )
            for course in courses:
                self._insert_course(c, path_id, course)
            if not courses:
                inbox = self._insert_course(c, path_id, {"title": INBOX_TITLE})
                c.execute(
                    'UPDATE course SET extensions = json(\'{"yuo": {"inbox": true}}\') WHERE id = ?', (inbox,)
                )
                save_path_state(c, path_id, "arrange", {"status": "collecting", "rounds": []})

        self.writer.run(unit)
        return path_id

    # --- a path from the learner's files: its name and courses proposed --------------------------------

    def _inbox(self, c: sqlite3.Connection, path_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = c.execute(
            "SELECT * FROM course WHERE path_id = ? AND archived_at IS NULL AND "
            "json_extract(extensions, '$.yuo.inbox') = 1",
            (path_id,),
        ).fetchone()
        return row

    def arrange_studies(self, path_id: str, feedback: str | None = None) -> dict[str, Any]:
        """Propose the path's name and its courses from the files added so far, or change the proposal in the
        learner's words (`feedback`). One call to the generation model; the files were read on this machine."""
        self.models.require_ai_ready()
        text = (feedback or "").strip()

        def unit(c: sqlite3.Connection) -> None:
            p = self._studies(c, path_id)
            inbox = self._inbox(c, path_id)
            if inbox is None:
                raise Conflict("the courses of this path are set already")
            state = path_state(p, "arrange") or {"rounds": []}
            if state.get("status") == "working":
                raise Conflict("a proposal is being written")
            files = c.execute(
                "SELECT kind, state FROM material WHERE course_id = ? AND state != 'failed'", (inbox["id"],)
            ).fetchall()
            if not files:
                raise InvalidInput("add some material first")
            if any(f["state"] in ("uploading", "reading") and f["kind"] not in RECORDING for f in files):
                raise Conflict("wait until the files are read")
            rounds = list(state.get("rounds", []))
            if text:
                if not state.get("proposal"):
                    raise InvalidInput("there is no proposal to change yet")
                rounds = [*rounds, {"text": text[:2000], "changes": None}][-ROUNDS_MAX:]
            save_path_state(
                c,
                path_id,
                "arrange",
                state | {"status": "working", "rounds": rounds, "error": None},
                touch=True,
            )
            enqueue(c, "course", EntityKind.COURSE, inbox["id"], priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.studies_view(path_id)

    def _arrange(self, job: Job, inbox: sqlite3.Row) -> None:
        path_id = inbox["path_id"]
        with self.readers.connection() as c:
            p = get_path(c, path_id)
            state = path_state(p, "arrange") or {}
            if state.get("status") != "working":
                return
            files = c.execute(
                "SELECT id, file_name, title, kind, role, pages, duration_ms, state FROM material "
                "WHERE course_id = ? AND state != 'failed' ORDER BY position",
                (inbox["id"],),
            ).fetchall()
            described = [_describe_file(c, k, f) for k, f in enumerate(files, 1)]
        ids = [f["id"] for f in files]
        feedback = [r["text"] for r in state.get("rounds", [])]
        previous = state.get("proposal")
        if previous:  # the model sees its proposal with file numbers, as it wrote it
            number = {mid: k for k, mid in enumerate(ids, 1)}
            previous = previous | {
                "courses": [
                    c | {"files": [number[m] for m in c["files"] if m in number]} for c in previous["courses"]
                ]
            }
        try:
            out = self.runner.run(
                job.id,
                arrange_spec(len(ids)),
                self.models.binding("generator"),
                {
                    "files": "\n\n".join(described),
                    "lang": p["content_lang"],
                    "feedback": feedback,
                    "previous": previous,
                },
                data_class=DataClass.FREE_TEXT,
            ).value
        except StageFailed as e:
            if not e.retryable:
                failed = state | {"status": "failed", "error": str(e)[:500]}
                self.writer.run(lambda c: save_path_state(c, path_id, "arrange", failed))
            raise
        proposal = {
            "title": out.title.strip()[:120],
            "goal": out.goal.strip()[:600],
            "courses": [
                {
                    "title": k.title.strip()[:120],
                    "term": k.term.strip()[:60],
                    "files": [ids[f - 1] for f in k.files],
                }
                for k in out.courses
            ],
            "message": out.message.strip(),
        }

        def unit(c: sqlite3.Connection) -> None:
            now = path_state(get_path(c, path_id), "arrange") or {}
            rounds = list(now.get("rounds", []))
            if rounds and rounds[-1].get("changes") is None:
                rounds[-1] = rounds[-1] | {"changes": proposal["message"]}
            save_path_state(
                c,
                path_id,
                "arrange",
                now | {"status": "ready", "proposal": proposal, "rounds": rounds},
                touch=True,
            )

        self.writer.run(unit)

    def accept_arrangement(
        self, path_id: str, title: str | None = None, adherence: list[str] | None = None
    ) -> dict[str, Any]:
        """The learner takes the proposal: the path gets its name, the courses are made (with the adherence
        chosen for each, in order) and the files move into them. The material is then read and planned as on
        any path from courses."""

        def unit(c: sqlite3.Connection) -> None:
            self._studies(c, path_id)
            inbox = self._inbox(c, path_id)
            state = path_state(get_path(c, path_id), "arrange") or {}
            proposal = state.get("proposal")
            if inbox is None or state.get("status") != "ready" or not proposal:
                raise Conflict("there is no proposal to take")
            files = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM material WHERE course_id = ? AND state != 'failed'", (inbox["id"],)
                )
            ]
            placed = {m for k in proposal["courses"] for m in k["files"]}
            if [m for m in files if m not in placed]:
                raise Conflict("files were added after the proposal: ask for a new one")
            name = (title or "").strip()[:120] or proposal["title"]
            c.execute(
                "UPDATE path SET title = ?, subject = ?, goal = ?, updated_at = ? WHERE id = ?",
                (name, name, proposal["goal"] or name, clock.now(), path_id),
            )
            first: str | None = None
            for n, k in enumerate(proposal["courses"]):
                choice = adherence[n] if adherence and n < len(adherence) else "grounded"
                cid = self._insert_course(
                    c, path_id, {"title": k["title"], "term": k["term"], "adherence": choice}
                )
                first = first or cid
                for pos, mid in enumerate(m for m in k["files"] if m in files):
                    c.execute(
                        "UPDATE material SET course_id = ?, position = ?, updated_at = ? WHERE id = ?",
                        (cid, pos, clock.now(), mid),
                    )
            c.execute(  # what is left failed: it stays in sight in the first course, to try again or remove
                "UPDATE material SET course_id = ?, position = 1000 + position WHERE course_id = ?",
                (first, inbox["id"]),
            )
            c.execute("DELETE FROM course WHERE id = ?", (inbox["id"],))
            save_path_state(c, path_id, "arrange", state | {"status": "accepted"}, touch=True)

        self.writer.run(unit)
        return self.studies_view(path_id)

    def _insert_course(self, c: sqlite3.Connection, path_id: str, course: dict[str, Any]) -> str:
        title = str(course.get("title", "")).strip()
        if not title:
            raise InvalidInput("a course needs a name")
        adherence = course.get("adherence", "grounded")
        if adherence not in ADHERENCE:
            raise InvalidInput(f"adherence must be one of {', '.join(ADHERENCE)}")
        taken = {r[0] for r in c.execute("SELECT code FROM course WHERE path_id = ?", (path_id,))}
        pos = c.execute(
            "SELECT coalesce(max(position) + 1, 0) FROM course WHERE path_id = ?", (path_id,)
        ).fetchone()[0]
        cid = new_id()
        c.execute(
            "INSERT INTO course (id, path_id, code, title, term, exam_date, adherence, keep_order, position, branch_id, "
            "outline, extensions, created_at, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '{}', ?, NULL)",
            (
                cid,
                path_id,
                _slug(title, taken),
                title[:120],
                (str(course.get("term") or "").strip() or None),
                course.get("exam_date") or None,
                adherence,
                int(bool(course.get("keep_order", True))),
                pos,
                clock.now(),
            ),
        )
        return cid

    def add_course(self, path_id: str, course: dict[str, Any]) -> dict[str, Any]:
        def unit(c: sqlite3.Connection) -> str:
            self._studies(c, path_id)
            return self._insert_course(c, path_id, course)

        cid = self.writer.run(unit)
        return self.course_view(cid)

    def update_course(self, course_id: str, change: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "term", "exam_date", "adherence", "keep_order"}

        def unit(c: sqlite3.Connection) -> None:
            row = self._course(c, course_id)
            if row["branch_id"] is not None and {"adherence", "keep_order"} & change.keys():
                pass  # applies to the lessons written from now on
            for key, value in change.items():
                if key not in allowed:
                    continue
                if key == "adherence" and value not in ADHERENCE:
                    raise InvalidInput(f"adherence must be one of {', '.join(ADHERENCE)}")
                if key == "keep_order":
                    value = int(bool(value))
                if key == "title" and not str(value).strip():
                    raise InvalidInput("a course needs a name")
                c.execute(f"UPDATE course SET {key} = ? WHERE id = ?", (value, course_id))

        self.writer.run(unit)
        return self.course_view(course_id)

    def archive_course(self, course_id: str) -> None:
        def unit(c: sqlite3.Connection) -> None:
            row = self._course(c, course_id)
            if row["branch_id"] is not None:
                raise InvalidInput("this course is built into the path already")
            c.execute("UPDATE course SET archived_at = ? WHERE id = ?", (clock.now(), course_id))

        self.writer.run(unit)

    def _course(self, c: sqlite3.Connection, course_id: str) -> sqlite3.Row:
        row: sqlite3.Row | None = c.execute("SELECT * FROM course WHERE id = ?", (course_id,)).fetchone()
        if row is None:
            raise NotFound(f"no such course {course_id}")
        return row

    def _studies(self, c: sqlite3.Connection, path_id: str) -> sqlite3.Row:
        p = get_path(c, path_id)
        if (json.loads(p["extensions"] or "{}").get("yuo") or {}).get("origin") != "courses":
            raise InvalidInput("this path is not built from courses")
        return p

    # --- uploads -------------------------------------------------------------------------------------

    def new_material(
        self, course_id: str, file_name: str, size: int, role: str | None = None, title: str | None = None
    ) -> dict[str, Any]:
        """Start an upload: the file is sent next in parts (`upload_part`)."""
        file_name = Path(file_name).name.strip()[:200]
        kind = kind_of(file_name)
        if kind is None:
            raise InvalidInput(
                "Yuo reads PDF, PowerPoint (.pptx), Word (.docx), Markdown and text files, and audio or video "
                "recordings"
            )
        if not 0 < size <= MAX_UPLOAD:
            raise InvalidInput(f"a file can be at most {MAX_UPLOAD // 1024**3} GB")
        if role is not None and role not in ROLES:
            raise InvalidInput(f"role must be one of {', '.join(ROLES)}")
        if self.blobs is None:
            raise Conflict("this installation has no file store")
        free = shutil.disk_usage(self.uploads).free
        if free < size * 2 + 512 * 1024**2:
            raise Conflict("not enough free disk space for this file")
        mid, sid = new_id(), new_id()

        def unit(c: sqlite3.Connection) -> None:
            course = self._course(c, course_id)
            now = clock.now()
            name = (title or Path(file_name).stem).strip()[:200] or file_name
            c.execute(
                "INSERT INTO source (id, key, kind, title, url, accessed_at, published_at, citation, data_class, "
                "extensions) VALUES (?, ?, ?, ?, NULL, ?, NULL, '{}', 'F', '{}')",
                (sid, f"material-{mid}", "video" if kind in ("audio", "video") else "upload", name, now),
            )
            pos = c.execute(
                "SELECT coalesce(max(position) + 1, 0) FROM material WHERE course_id = ?", (course_id,)
            ).fetchone()[0]
            c.execute(
                "INSERT INTO material (id, path_id, course_id, source_id, role, kind, title, file_name, asset_hash, "
                "size_bytes, pages, duration_ms, keep_original, state, progress, error, outline, position, extensions, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, 0, 'uploading', 0, NULL, "
                "NULL, ?, json(?), ?, ?)",
                (
                    mid,
                    course["path_id"],
                    course_id,
                    sid,
                    role or _guess_role(file_name, kind),
                    kind,
                    name,
                    file_name,
                    size,
                    pos,
                    json.dumps({"yuo": {"received": 0}}),
                    now,
                    now,
                ),
            )

        self.writer.run(unit)
        return self.material_view(mid)

    def upload_part(self, material_id: str, offset: int, data: bytes) -> dict[str, Any]:
        """Append a part at `offset` (the bytes received so far); the last part starts reading the file."""
        if len(data) > MAX_PART:
            raise InvalidInput(f"a part can be at most {MAX_PART // 1024**2} MB")
        with self.readers.connection() as c:
            m = c.execute(
                "SELECT state, size_bytes, extensions FROM material WHERE id = ?", (material_id,)
            ).fetchone()
        if m is None:
            raise NotFound(f"no such material {material_id}")
        if m["state"] != "uploading":
            raise InvalidInput("this file is already uploaded")
        part = self.uploads / f"{material_id}.part"
        have = part.stat().st_size if part.exists() else 0
        if offset != have:
            raise Conflict(f"expected the part at {have}")  # the client resumes from here
        if have + len(data) > m["size_bytes"]:
            raise InvalidInput("more bytes than the file's size")
        with part.open("ab") as f:
            f.write(data)
        have += len(data)
        done = have == m["size_bytes"]
        if done:
            self._received(material_id, part)
        return self.material_view(material_id) | {"received": have}

    def _received(self, material_id: str, part: Path) -> None:
        assert self.blobs is not None
        digest = _put_file(self.blobs, part)

        def unit(c: sqlite3.Connection) -> None:
            m = c.execute("SELECT kind, size_bytes FROM material WHERE id = ?", (material_id,)).fetchone()
            media = {"pdf": "application/pdf", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                     "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     "text": "text/plain", "audio": "audio/*", "video": "video/*"}.get(m["kind"], "application/octet-stream")  # fmt: skip
            c.execute(
                "INSERT OR IGNORE INTO asset (hash, media_type, kind, bytes, stored_at, retention_class, evicted_at, "
                "data_class, created_at) VALUES (?, ?, ?, ?, ?, 'keep', NULL, 'F', ?)",
                (digest, media, m["kind"] if m["kind"] in ("audio", "video") else "document", m["size_bytes"],
                 str(self.blobs.path(digest)) if self.blobs else None, clock.now()),
            )  # fmt: skip
            c.execute(
                "UPDATE material SET asset_hash = ?, state = 'reading', updated_at = ? WHERE id = ?",
                (digest, clock.now(), material_id),
            )
            # read on this machine right away, for free; documents go ahead of recordings (seconds, not minutes)
            enqueue(c, "material", EntityKind.MATERIAL, material_id,
                    priority=0 if m["kind"] in RECORDING else DOC_PRIORITY)  # fmt: skip

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()

    def read_pages(self, material_id: str) -> dict[str, Any]:
        """The learner asks for a PDF's pages with little text (formulas, figures) to be read from their images
        by the generation model; the course is planned again when it had a plan. Not once a course is built."""

        def unit(c: sqlite3.Connection) -> None:
            m = c.execute(
                "SELECT course_id, kind, state, extensions FROM material WHERE id = ?", (material_id,)
            ).fetchone()
            if m is None:
                raise NotFound(material_id)
            ext = json.loads(m["extensions"] or "{}").get("yuo", {})
            if m["kind"] != "pdf" or not (ext.get("sparse") or ext.get("formulas")):
                raise InvalidInput(
                    "only a PDF's pages with little text or missing formulas can be read from their images"
                )
            if m["state"] not in ("read", "ready") or ext.get("vision") in ("wanted", "done"):
                raise Conflict("these pages are being read or were read already")
            course = self._course(c, m["course_id"])
            if course["branch_id"] is not None:
                raise InvalidInput("this course is built already")
            c.execute(
                "UPDATE material SET state = 'reading', progress = 0, updated_at = ?, "
                "extensions = json_set(extensions, '$.yuo.vision', 'wanted') WHERE id = ?",
                (clock.now(), material_id),
            )
            enqueue(c, "material", EntityKind.MATERIAL, material_id, priority=DOC_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.material_view(material_id)

    def retry_material(self, material_id: str) -> dict[str, Any]:
        """Read or transcribe a file again after it failed, from what was uploaded (a recording's audio is kept,
        and its transcription goes on from where it stopped)."""

        def unit(c: sqlite3.Connection) -> None:
            m = c.execute(
                "SELECT kind, state, asset_hash FROM material WHERE id = ?", (material_id,)
            ).fetchone()
            if m is None:
                raise NotFound(material_id)
            if m["state"] != "failed":
                raise Conflict("only a file that failed can be tried again")
            if m["asset_hash"] is None:
                raise InvalidInput("this file was not uploaded completely: add it again")
            audio = (
                m["kind"] in RECORDING
                and c.execute(
                    "SELECT 1 FROM asset WHERE hash = ? AND kind = 'audio'", (m["asset_hash"],)
                ).fetchone()
            )
            c.execute(
                "UPDATE material SET state = ?, progress = 0, error = NULL, updated_at = ? WHERE id = ?",
                ("read" if audio else "reading", clock.now(), material_id),
            )
            enqueue(c, "material", EntityKind.MATERIAL, material_id, priority=DOC_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.material_view(material_id)

    def update_material(
        self, material_id: str, role: str | None = None, title: str | None = None
    ) -> dict[str, Any]:
        """Correct a file's role or name; the course's plan is made again when it already had one."""
        if role is not None and role not in ROLES:
            raise InvalidInput(f"role must be one of {', '.join(ROLES)}")

        def unit(c: sqlite3.Connection) -> None:
            m = c.execute("SELECT course_id FROM material WHERE id = ?", (material_id,)).fetchone()
            if m is None:
                raise NotFound(material_id)
            course = self._course(c, m["course_id"])
            if course["branch_id"] is not None:
                raise InvalidInput("this course is built already")
            if role is not None:
                c.execute(
                    "UPDATE material SET role = ?, updated_at = ? WHERE id = ?",
                    (role, clock.now(), material_id),
                )
            if title is not None and title.strip():
                c.execute(
                    "UPDATE material SET title = ?, updated_at = ? WHERE id = ?",
                    (title.strip()[:200], clock.now(), material_id),
                )
            outline = json.loads(course["outline"] or "{}")
            if outline.get("status") == "ready":  # plan it again with the corrected file
                c.execute("UPDATE course SET outline = NULL WHERE id = ?", (course["id"],))
                if self._started(c, course["path_id"]):
                    self._queue_course(c, course["id"])

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.material_view(material_id)

    def delete_material(self, material_id: str) -> None:
        def unit(c: sqlite3.Connection) -> str | None:
            m = c.execute("SELECT * FROM material WHERE id = ?", (material_id,)).fetchone()
            if m is None:
                raise NotFound(material_id)
            # a built course: the lessons written from it are written again without it (readable meanwhile), and
            # its pages leave the skills and the questions that cite them
            for lid, state, raw in c.execute(
                "SELECT l.id, l.state, l.extensions ->> '$.yuo.sources' FROM lesson l WHERE l.path_id = ? AND "
                "EXISTS (SELECT 1 FROM json_each(l.extensions, '$.yuo.sources') j WHERE j.value ->> 'material_id' = ?)",
                (m["path_id"], material_id),
            ).fetchall():
                kept = [x for x in json.loads(raw) if x.get("material_id") != material_id]
                c.execute(
                    "UPDATE lesson SET extensions = json_set(extensions, '$.yuo.sources', json(?)) WHERE id = ?",
                    (json.dumps(kept), lid),
                )
                busy = c.execute(
                    "SELECT 1 FROM generation_job WHERE target_id = ? AND status IN ('queued', 'running', "
                    "'waiting_resource')",
                    (lid,),
                ).fetchone()
                if state == "ready" and not busy:
                    c.execute("UPDATE lesson SET state = 'queued' WHERE id = ?", (lid,))
                    enqueue(c, "lesson", EntityKind.LESSON, lid)
            mine = "SELECT id FROM material_section WHERE material_id = ?"
            c.execute(f"DELETE FROM skill_anchor WHERE section_id IN ({mine})", (material_id,))
            c.execute(f"DELETE FROM item_version_source WHERE section_id IN ({mine})", (material_id,))
            c.execute("DELETE FROM material_section WHERE material_id = ?", (material_id,))
            c.execute("DELETE FROM material WHERE id = ?", (material_id,))
            c.execute("DELETE FROM source WHERE id = ?", (m["source_id"],))
            c.execute(
                "UPDATE course SET outline = NULL WHERE id = ? AND branch_id IS NULL", (m["course_id"],)
            )  # the plan is made again without it
            if self._started(c, m["path_id"]):
                self._queue_course(c, m["course_id"])
            h = m["asset_hash"]
            if h and not c.execute("SELECT 1 FROM material WHERE asset_hash = ? LIMIT 1", (h,)).fetchone():
                c.execute("DELETE FROM asset WHERE hash = ? AND data_class = 'F'", (h,))
                return str(h)
            return None

        gone = self.writer.run(unit)
        (self.uploads / f"{material_id}.part").unlink(missing_ok=True)
        if gone and self.blobs is not None:
            self.blobs.delete(gone)

    # --- views ---------------------------------------------------------------------------------------

    def material_view(self, material_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            m = c.execute(
                "SELECT id, course_id, role, kind, title, file_name, size_bytes, pages, duration_ms, state, progress, "
                "error, extensions, outline IS NOT NULL AS outlined FROM material WHERE id = ?",
                (material_id,),
            ).fetchone()
            if m is None:
                raise NotFound(material_id)
            stats = c.execute(
                "SELECT count(*), coalesce(sum(tokens), 0) FROM material_section WHERE material_id = ? AND level = 'chunk'",
                (material_id,),
            ).fetchone()
        out = dict(m)
        ext = json.loads(out.pop("extensions") or "{}").get("yuo", {})
        part = self.uploads / f"{material_id}.part"
        out["received"] = (
            part.stat().st_size if m["state"] == "uploading" and part.exists() else m["size_bytes"]
        )
        out["chunks"], out["tokens"] = stats[0], stats[1]
        out["sparse_pages"] = len(ext.get("sparse", []))
        out["formula_pages"] = len(ext.get("formulas", {}))
        out["vision"] = ext.get("vision")
        out["vision_pages"] = ext.get("vision_pages", 0)
        out["vision_total"] = len(vision_pages(ext)) if ext.get("vision") == "wanted" else 0
        out["outlined"] = bool(out["outlined"])
        return out

    def course_view(self, course_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            row = self._course(c, course_id)
            materials = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM material WHERE course_id = ? ORDER BY position", (course_id,)
                )
            ]
            job = c.execute(
                "SELECT id, status FROM generation_job WHERE kind = 'course' AND target_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (course_id,),
            ).fetchone()
            outline = json.loads(row["outline"]) if row["outline"] else None
            updates = [self._update_view(c, outline or {}, u) for u in (outline or {}).get("updates", [])]
        status = (outline or {}).get("status", "none")
        writing = status in ("drafting", "revising")
        return {
            "id": row["id"],
            "code": row["code"],
            "title": row["title"],
            "term": row["term"],
            "exam_date": row["exam_date"],
            "adherence": row["adherence"],
            "keep_order": bool(row["keep_order"]),
            "built": row["branch_id"] is not None,
            "materials": [self.material_view(m) for m in materials],
            "plan": _plan_view(outline),
            "job_id": job["id"] if job is not None and writing else None,
            "failed": writing and job is not None and job["status"] == "failed",
            "updates": [u for u in updates if u["status"] == "pending"],
        }

    @staticmethod
    def _update_view(c: sqlite3.Connection, outline: dict[str, Any], u: dict[str, Any]) -> dict[str, Any]:
        titles = {sk["code"]: sk["title"] for sk in outline.get("plan", {}).get("skills", [])}
        lessons = []
        for lid in u["lessons"]:
            r = c.execute(
                "SELECT coalesce(v.title, l.extensions ->> '$.yuo.planned_title', l.code) FROM lesson l LEFT JOIN "
                "lesson_version v ON v.id = l.current_version_id WHERE l.id = ?",
                (lid,),
            ).fetchone()
            if r:
                lessons.append({"id": lid, "title": r[0]})
        return {
            "id": u["id"],
            "at": u["at"],
            "materials": u["materials"],
            "changes": u["changes"],
            "lessons": lessons,
            "skills": [titles.get(code, code) for code in u["skills"]],
            "status": u["status"],
        }

    def studies_view(self, path_id: str) -> dict[str, Any]:
        with self.readers.connection() as c:
            p = self._studies(c, path_id)
            ids = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM course WHERE path_id = ? AND archived_at IS NULL ORDER BY position",
                    (path_id,),
                )
            ]
            state = path_state(p, "preview") or {}
            links_job = c.execute(
                "SELECT id, status FROM generation_job WHERE kind = 'course_links' AND target_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (path_id,),
            ).fetchone()
        courses = [self.course_view(i) for i in ids]
        status = state.get("status", "collecting")
        if status in ("collecting", "drafting", "ready", "revising"):
            status = _studies_status(state, courses, links_job)
        arrange = path_state(p, "arrange")
        return {
            "path_id": path_id,
            "title": p["title"],
            "status": status,
            "arrange": _arrange_view(arrange, courses)
            if arrange and arrange.get("status") != "accepted"
            else None,
            "courses": courses,
            "links": state.get("links", {"requires": [], "related": []}),
            "estimate": self._estimate(path_id) if status == "collecting" else None,
            "links_failed": links_job is not None and links_job["status"] == "failed",
            "work": self._work(path_id, courses, state) if status in ("drafting", "revising") else None,
        }

    def _work(self, path_id: str, courses: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        """How far reading and planning has got, for a progress bar: each part of a file summarised counts
        one, each file outlined two, each course planned five and the links between courses two. `step` is
        what runs now (a file being read, a course being planned, or the links)."""
        live = {c["id"]: c for c in courses if not c["built"]}
        with self.readers.connection() as c:
            files = c.execute(
                "SELECT m.id, m.title, m.state, m.course_id, m.outline IS NOT NULL AS outlined, "
                "count(s.id) AS parts, count(s.digest) AS digested FROM material m "
                "LEFT JOIN material_section s ON s.material_id = m.id AND s.level = 'chunk' "
                "WHERE m.path_id = ? AND m.state != 'failed' GROUP BY m.id ORDER BY m.position",
                (path_id,),
            ).fetchall()
        done = total = 0
        step: dict[str, Any] | None = None
        for f in files:
            if f["course_id"] not in live or f["parts"] == 0:
                continue  # built, or a recording still being transcribed: it joins later
            total += f["parts"] + 2
            done += f["digested"] + (2 if f["outlined"] else 0)
            if step is None and f["state"] in ("digesting", "outlining"):
                step = {"kind": "file", "title": f["title"], "done": f["digested"], "total": f["parts"]}
        for course in live.values():
            total += 5
            plan = course["plan"]
            if plan is not None and plan["status"] == "ready":
                done += 5
            elif step is None and plan is not None:
                step = {"kind": "course", "title": course["title"], "done": 0, "total": 0}
        if len(live) >= 2:
            total += 2
            if state.get("links_status") != "linking" and all(
                k["plan"] is not None and k["plan"]["status"] == "ready" for k in live.values()
            ):
                done += 2
            elif step is None and state.get("links_status") == "linking":
                step = {"kind": "links", "title": "", "done": 0, "total": 0}
        return {"done": min(done, total), "total": total, "step": step}

    def _estimate(self, path_id: str) -> dict[str, Any]:
        """What reading the material once costs in tokens, before the learner says go."""
        with self.readers.connection() as c:
            docs = c.execute(
                "SELECT coalesce(sum(s.tokens), 0) FROM material_section s JOIN material m ON m.id = s.material_id "
                "WHERE m.path_id = ? AND s.level = 'chunk'",
                (path_id,),
            ).fetchone()[0]
            audio_ms = c.execute(  # recordings not transcribed yet (a transcript's tokens count above)
                "SELECT coalesce(sum(duration_ms), 0) FROM material m WHERE path_id = ? AND kind IN ('audio','video') "
                "AND state IN ('read','transcribing') AND NOT EXISTS (SELECT 1 FROM material_section s WHERE "
                "s.material_id = m.id)",
                (path_id,),
            ).fetchone()[0]
        speech = int(audio_ms / 60000 * 200)  # about 150 words a minute
        return {"tokens": docs + speech, "audio_minutes": round(audio_ms / 60000)}

    # --- start: read everything once, then plan ---------------------------------------------------------

    def start_studies(self, path_id: str) -> dict[str, Any]:
        """The learner confirms: the material is digested and each course planned."""
        self.models.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            p = self._studies(c, path_id)
            state = path_state(p, "preview") or {}
            if state.get("status") not in (None, "collecting"):
                raise InvalidInput("the material is already being read")
            if self._inbox(c, path_id) is not None:
                raise Conflict("take or change the proposed courses first")
            if not c.execute(
                "SELECT 1 FROM material m JOIN course k ON k.id = m.course_id WHERE m.path_id = ? AND "
                "k.archived_at IS NULL AND m.state != 'failed' LIMIT 1",
                (path_id,),
            ).fetchone():
                raise InvalidInput("add some material first")
            save_path_state(
                c, path_id, "preview", state | {"status": "drafting", "started_at": clock.now()}, touch=True
            )
            for (cid,) in c.execute(
                "SELECT id FROM course WHERE path_id = ? AND archived_at IS NULL", (path_id,)
            ).fetchall():
                self._queue_course(c, cid)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.studies_view(path_id)

    def _started(self, c: sqlite3.Connection, path_id: str) -> bool:
        state = path_state(get_path(c, path_id), "preview") or {}
        return state.get("status") not in (None, "collecting")

    def _queue_course(self, c: sqlite3.Connection, course_id: str) -> None:
        """Bring a course up to date (its read files digested, then planned, or joined to its plan): one job
        waiting per course is enough, it sees every file that is ready when it runs."""
        if c.execute(
            "SELECT 1 FROM generation_job WHERE kind = 'course' AND target_id = ? AND status IN "
            "('queued', 'waiting_resource') LIMIT 1",
            (course_id,),
        ).fetchone():
            return
        enqueue(c, "course", EntityKind.COURSE, course_id, priority=URGENT_PRIORITY)

    def _plannable(self, c: sqlite3.Connection, course_id: str) -> bool:
        """A course is planned once its documents are read, without waiting for its recordings: they join the
        plan as they are transcribed. A course of recordings only waits for its first two."""
        rows = c.execute("SELECT kind, state FROM material WHERE course_id = ?", (course_id,)).fetchall()
        docs = [r["state"] for r in rows if r["kind"] not in RECORDING and r["state"] != "uploading"]
        if any(st not in ("ready", "failed") for st in docs):
            return False
        if "ready" in docs:
            return True
        recs = [r["state"] for r in rows if r["kind"] in RECORDING and r["state"] != "failed"]
        ready = recs.count("ready")
        return ready > 0 and ready >= min(2, len(recs))

    # --- the material job ------------------------------------------------------------------------------

    def handle_material(self, job: Job) -> None:
        mid = job.target_id
        try:
            self._material(job)
        except TranscriptionInterrupted as e:  # goes on where it stopped, after the job's backoff
            if job.attempt >= MAX_ATTEMPTS:
                self._set(mid, state="failed", error=f"{e} when you try again"[:500])
                self._after_material(mid)
            else:
                self._set(mid, error=str(e)[:500])
            raise StageFailed(str(e), retryable=True) from e
        except (ReadError, StageFailed) as e:
            if isinstance(e, StageFailed) and e.retryable:
                raise
            self._set(mid, state="failed", error=str(e)[:500])
            self._after_material(mid)
            if isinstance(e, StageFailed):
                raise

    def _material(self, job: Job) -> None:
        """Read a file on this machine, and transcribe a recording: free, so it starts on upload, before the
        learner says go. What costs (digests, the plan) is the course job's, after the start."""
        mid = job.target_id
        with self.readers.connection() as c:
            m = c.execute("SELECT * FROM material WHERE id = ?", (mid,)).fetchone()
        if m is None:
            return
        if m["state"] == "reading" and not self._has_chunks(mid):
            self._read(m)
            with self.readers.connection() as c:
                m = c.execute("SELECT * FROM material WHERE id = ?", (mid,)).fetchone()
        if json.loads(m["extensions"] or "{}").get("yuo", {}).get("vision") == "wanted":
            self._vision(job, m)
        if m["kind"] in RECORDING and m["state"] in ("read", "transcribing") and not self._has_chunks(mid):
            self._transcribe(m)
            self._set(mid, state="read", progress=1.0)
        self._after_material(mid)

    def _has_chunks(self, mid: str) -> bool:
        with self.readers.connection() as c:
            return (
                c.execute("SELECT 1 FROM material_section WHERE material_id = ? LIMIT 1", (mid,)).fetchone()
                is not None
            )

    def _set(self, mid: str, **fields: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.writer.run(
            lambda c: c.execute(
                f"UPDATE material SET {cols}, updated_at = ? WHERE id = ?",
                (*fields.values(), clock.now(), mid),
            )
        )

    def _read(self, m: sqlite3.Row) -> None:
        """Extract the text (documents) or the audio (recordings), on this machine."""
        assert self.blobs is not None
        src = self.blobs.path(m["asset_hash"])
        if m["kind"] in ("audio", "video"):
            self._read_recording(m, src)
            return
        ex = read_document(src, m["kind"])
        self._store_sections(m["id"], ex)
        self._set(
            m["id"],
            state="read",
            pages=ex.count,
            progress=0.0,
            extensions=json.dumps({"yuo": {"sparse": ex.sparse, "formulas": ex.formulas}}),
        )
        (self.uploads / f"{m['id']}.part").unlink(missing_ok=True)

    def _vision(self, job: Job, m: sqlite3.Row) -> None:
        """Pages with little text or missing formulas, read from their images by the generation model; what it
        reads takes the place of the page's text, and the file is split, digested and outlined again with it."""
        assert self.blobs is not None
        mid = m["id"]
        pages = vision_pages(json.loads(m["extensions"])["yuo"])
        src = self.blobs.path(m["asset_hash"])
        work = self.uploads / f"{mid}.pages"
        work.mkdir(parents=True, exist_ok=True)
        readings: dict[int, str] = {}
        failed = False
        try:
            gen = self.models.binding("generator")
            for k in range(0, len(pages), VISION_BATCH):
                batch = pages[k : k + VISION_BATCH]
                files = page_images(src, batch, work)
                try:
                    out = self.runner.run(
                        job.id,
                        vision_spec(batch),
                        gen,
                        {
                            "title": m["title"],
                            "role": m["role"],
                            "pages": batch,
                            "images": [str(f) for f in files],
                            "image_hashes": [bytes_hash(f.read_bytes()) for f in files],
                        },
                        data_class=DataClass.FREE_TEXT,
                    )
                except StageFailed as e:
                    if e.retryable:
                        raise
                    log.info("material.vision_failed", material=mid, error=str(e)[:200])
                    failed = True
                    break
                finally:
                    for f in files:
                        f.unlink(missing_ok=True)
                readings.update({r.page: r.text.strip() for r in out.value.pages if r.text.strip()})
                self._set(mid, progress=round(min(k + VISION_BATCH, len(pages)) / len(pages), 3))
        finally:
            shutil.rmtree(work, ignore_errors=True)

        if readings:
            ex = read_document(src, "pdf")
            pages_read = [
                Page(
                    p.start, p.end, f"[p. {p.start}, read from the page image]\n{readings[p.start]}", p.title
                )
                if p.start in readings
                else p
                for p in ex.pages
            ]
            self._store_sections(mid, replace(ex, pages=pages_read))

        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                "UPDATE material SET state = 'read', progress = 1.0, outline = NULL, updated_at = ?, extensions = "
                "json_set(extensions, '$.yuo.vision', ?, '$.yuo.vision_pages', ?) WHERE id = ?",
                (clock.now(), "failed" if failed and not readings else "done", len(readings), mid),
            )
            course = self._course(c, m["course_id"])
            if json.loads(course["outline"] or "{}").get("status") == "ready":  # plan it again with the pages
                c.execute("UPDATE course SET outline = NULL WHERE id = ?", (course["id"],))

        self.writer.run(unit)

    def _align_course(self, course_id: str) -> None:
        """Which slide each recorded lecture of the course is on, when the course has slides: the deck that
        matches a recording best, kept in the recording's extensions. Local and free; done again only when a
        file changed."""
        with self.readers.connection() as c:
            files = c.execute(
                "SELECT id, kind, role, asset_hash, extensions FROM material WHERE course_id = ? AND state = 'ready' "
                "ORDER BY position",
                (course_id,),
            ).fetchall()
            decks = [m for m in files if m["role"] == "slides" and m["kind"] not in RECORDING]
            talks = [m for m in files if m["kind"] in RECORDING]
            if not decks or not talks:
                return
            chunks = {
                m["id"]: [
                    (r["loc_start"], r["loc_end"], r["text"] or "") for r in self._chunk_rows(c, m["id"])
                ]
                for m in talks
            }
        assert self.blobs is not None
        slides: dict[str, dict[int, str]] = {}
        for d in decks:
            try:
                ex = read_document(self.blobs.path(d["asset_hash"]), d["kind"])
            except ReadError, OSError:
                continue
            slides[d["id"]] = {p.start: p.text for p in ex.pages if p.text.strip()}
        for t in talks:
            key = bytes_hash("|".join([t["asset_hash"], *sorted(d["asset_hash"] for d in decks)]).encode())
            ext = json.loads(t["extensions"] or "{}").get("yuo", {})
            if (ext.get("slides") or {}).get("key") == key:
                continue
            paras = al.paragraphs(chunks[t["id"]])
            best: dict[str, Any] = {"key": key, "material_id": None, "runs": []}
            covered = 0
            for d in decks:
                runs = al.align(paras, slides.get(d["id"], {}))
                span = sum(r[1] - r[0] for r in runs)
                if span > covered:
                    covered, best = (
                        span,
                        {"key": key, "material_id": d["id"], "runs": [list(r) for r in runs]},
                    )
            self._set_ext(t["id"], "slides", best)

    def _set_ext(self, mid: str, key: str, value: Any) -> None:
        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                f"UPDATE material SET extensions = json_set(extensions, '$.yuo.{key}', json(?)) WHERE id = ?",
                (json.dumps(value), mid),
            )

        self.writer.run(unit)

    def _slide_sources(self, c: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        """For the parts of a recording a lesson is written from, the slides shown meanwhile (the alignment)."""
        out: list[dict[str, Any]] = []
        maps: dict[str, Any] = {}
        for r in rows:
            if r["loc_kind"] != "time":
                continue
            if r["material_id"] not in maps:
                ext = c.execute(
                    "SELECT extensions FROM material WHERE id = ?", (r["material_id"],)
                ).fetchone()[0]
                maps[r["material_id"]] = json.loads(ext or "{}").get("yuo", {}).get("slides")
            found = maps[r["material_id"]]
            if not found or not found.get("material_id"):
                continue
            shown = al.slides_at([tuple(x) for x in found["runs"]], r["loc_start"], r["loc_end"])
            if shown is None:
                continue
            deck = c.execute(
                "SELECT m.id, m.title, m.kind, s.id AS section_id, s.loc_kind FROM material m JOIN material_section s "
                "ON s.material_id = m.id WHERE m.id = ? AND s.level = 'chunk' AND s.loc_start <= ? "
                "ORDER BY s.loc_start DESC LIMIT 1",
                (found["material_id"], shown[0]),
            ).fetchone()
            if deck is None:
                continue
            out.append(
                {
                    "section_id": deck["section_id"],
                    "material_id": deck["id"],
                    "title": deck["title"],
                    "kind": deck["kind"],
                    "loc_kind": deck["loc_kind"],
                    "loc_start": shown[0],
                    "loc_end": shown[1],
                    "where": ch.locator(deck["loc_kind"], shown[0], shown[1]),
                }
            )
        return out

    def _read_recording(self, m: sqlite3.Row, src: Path) -> None:
        if self.ffmpeg is None:
            raise ReadError("recordings need ffmpeg, which this installation does not have")
        work = self.uploads / f"{m['id']}.opus"
        try:
            self.ffmpeg.to_speech(src, work)
            duration = int(self.ffmpeg.duration(work) * 1000)
            assert self.blobs is not None
            audio = _put_file(self.blobs, work)
        finally:
            work.unlink(missing_ok=True)
        old = m["asset_hash"]

        def unit(c: sqlite3.Connection) -> None:
            c.execute(
                "INSERT OR IGNORE INTO asset (hash, media_type, kind, bytes, stored_at, retention_class, evicted_at, "
                "data_class, created_at) VALUES (?, 'audio/ogg', 'audio', ?, NULL, 'keep', NULL, 'F', ?)",
                (audio, self.blobs.path(audio).stat().st_size if self.blobs else 0, clock.now()),
            )
            keep = m["keep_original"] and m["kind"] == "video"
            c.execute(
                "UPDATE material SET asset_hash = ?, duration_ms = ?, state = 'read', updated_at = ?, "
                "extensions = json_set(extensions, '$.yuo.original', ?) WHERE id = ?",
                (audio, duration, clock.now(), old if keep else None, m["id"]),
            )
            if (
                not keep
                and old != audio
                and not c.execute(
                    "SELECT 1 FROM material WHERE asset_hash = ? AND id != ? LIMIT 1", (old, m["id"])
                ).fetchone()
            ):
                c.execute("DELETE FROM asset WHERE hash = ? AND data_class = 'F'", (old,))

        self.writer.run(unit)
        if not (m["keep_original"] and m["kind"] == "video") and self.blobs is not None and old != audio:
            self.blobs.delete(old)
        (self.uploads / f"{m['id']}.part").unlink(missing_ok=True)

    def _transcribe(self, m: sqlite3.Row) -> None:
        transcriber = self.ctx.transcriber
        why = (
            "recordings cannot be transcribed on this installation"
            if transcriber is None
            else transcriber.available()
        )
        if why:
            raise ReadError(why)
        self._set(m["id"], state="transcribing", progress=0.0)
        assert self.blobs is not None
        audio = self.blobs.path(m["asset_hash"])
        with self.readers.connection() as c:
            lang = c.execute("SELECT content_lang FROM path WHERE id = ?", (m["path_id"],)).fetchone()[0]
            terms = self._course_terms(c, m["course_id"])
            fast = settings.effective(c, "material.transcription", {})[0] == "faster"

        def progress(done: float) -> None:
            self._set(m["id"], progress=round(min(max(done, 0.0), 1.0), 3))

        segments = transcriber.transcribe(
            audio,
            lang=lang,
            prompt=", ".join(terms[:40]),
            progress=progress,
            fast=fast,
            duration_ms=m["duration_ms"],
        )
        pages = [Page(s.start_ms, s.end_ms, s.text.strip()) for s in segments if s.text.strip()]
        if not pages:
            raise ReadError("no speech was found in this recording")
        ex = Extracted(
            "time", _join_speech(pages), [], title=m["title"], count=m["duration_ms"] or pages[-1].end
        )
        self._store_sections(m["id"], ex)

    def _course_terms(self, c: sqlite3.Connection, course_id: str) -> list[str]:
        """Terms from the course's other material, already digested: they help the transcription."""
        seen: dict[str, None] = {}
        for (digest,) in c.execute(
            "SELECT s.digest FROM material_section s JOIN material m ON m.id = s.material_id WHERE m.course_id = ? "
            "AND s.digest IS NOT NULL LIMIT 200",
            (course_id,),
        ):
            for term in json.loads(digest).get("concepts", []):
                seen.setdefault(term, None)
        return list(seen)

    def _store_sections(self, mid: str, ex: Extracted) -> None:
        drafts = ch.split(ex)
        if not drafts:
            raise ReadError(
                "no text was found in this file (a scanned PDF needs OCR, which Yuo cannot do yet)"
            )

        def unit(c: sqlite3.Connection) -> None:
            c.execute("DELETE FROM material_section WHERE material_id = ?", (mid,))
            ids: list[str] = []
            for pos, d in enumerate(drafts):
                sid = new_id()
                ids.append(sid)
                c.execute(
                    "INSERT INTO material_section (id, material_id, parent_id, position, level, title, loc_kind, "
                    "loc_start, loc_end, text, tokens, digest, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "NULL, ?)",
                    (
                        sid,
                        mid,
                        ids[d.parent] if d.parent is not None else None,
                        pos,
                        d.level,
                        d.title[:300],
                        ex.loc_kind,
                        d.start,
                        d.end,
                        d.text,
                        ch.tokens(d.text or ""),
                        bytes_hash(d.text.encode()) if d.text else None,
                    ),
                )

        self.writer.run(unit)

    def _chunk_rows(self, c: sqlite3.Connection, mid: str) -> list[sqlite3.Row]:
        return c.execute(
            "SELECT id, position, loc_kind, loc_start, loc_end, text, tokens, digest FROM material_section "
            "WHERE material_id = ? AND level = 'chunk' ORDER BY position",
            (mid,),
        ).fetchall()

    def _digest(self, job: Job, mid: str) -> None:
        with self.readers.connection() as c:
            m = c.execute("SELECT title, role, state FROM material WHERE id = ?", (mid,)).fetchone()
            rows = self._chunk_rows(c, mid)
        if m["state"] not in ("digesting",) and all(r["digest"] for r in rows):
            return
        self._set(mid, state="digesting")
        util = self.models.binding("utility")
        codes = {r["id"]: f"c{n}" for n, r in enumerate(rows, 1)}
        todo = [r for r in rows if not r["digest"]]
        groups = ch.batches([r["tokens"] for r in todo], DIGEST_BUDGET)
        done = len(rows) - len(todo)
        for g in groups:
            batch = [todo[i] for i in g]
            batch_codes = [codes[r["id"]] for r in batch]
            out = self.runner.run(
                job.id,
                digest_spec(batch_codes),
                util,
                {
                    "title": m["title"],
                    "role": m["role"],
                    "chunks": [
                        {
                            "code": codes[r["id"]],
                            "loc": ch.locator(r["loc_kind"], r["loc_start"], r["loc_end"]),
                            "text": r["text"],
                        }
                        for r in batch
                    ],
                },
                data_class=DataClass.FREE_TEXT,
            )
            by_code = {d.chunk: d for d in out.value.digests}

            def unit(
                c: sqlite3.Connection,
                batch: list[sqlite3.Row] = batch,
                by_code: dict[str, ChunkDigest] = by_code,
            ) -> None:
                for r in batch:
                    d = by_code[codes[r["id"]]]
                    c.execute(
                        "UPDATE material_section SET digest = json(?) WHERE id = ?",
                        (json.dumps(d.model_dump(exclude={"chunk"}), ensure_ascii=False), r["id"]),
                    )

            self.writer.run(unit)
            done += len(batch)
            self._set(mid, progress=round(done / max(len(rows), 1), 3))

    def _outline(self, job: Job, mid: str) -> None:
        with self.readers.connection() as c:
            m = c.execute("SELECT title, role, outline FROM material WHERE id = ?", (mid,)).fetchone()
            rows = self._chunk_rows(c, mid)
            chapters = [
                r[0]
                for r in c.execute(
                    "SELECT title FROM material_section WHERE material_id = ? AND level = 'chapter' ORDER BY position",
                    (mid,),
                )
            ]
        if m["outline"]:
            self._set(mid, state="ready", progress=1.0)
            return
        self._set(mid, state="outlining")
        codes = [f"c{n}" for n in range(1, len(rows) + 1)]
        ids = {f"c{n}": r["id"] for n, r in enumerate(rows, 1)}
        locs = {f"c{n}": (r["loc_kind"], r["loc_start"], r["loc_end"]) for n, r in enumerate(rows, 1)}
        digests = []
        for code, r in zip(codes, rows, strict=True):
            d = json.loads(r["digest"])
            digests.append({"code": code, "loc": ch.locator(*locs[code]), **d})
        out = self.runner.run(
            job.id,
            outline_spec(codes),
            self.models.binding("utility"),
            {"title": m["title"], "role": m["role"], "chapters": chapters[:60], "digests": digests},
            data_class=DataClass.FREE_TEXT,
        )
        topics = []
        for n, t in enumerate(out.value.topics, 1):
            first, last = locs[t.chunks[0]], locs[t.chunks[-1]]
            topics.append(
                {
                    "code": f"t{n}",
                    "title": t.title,
                    "summary": t.summary,
                    "concepts": t.concepts,
                    "sections": [ids[x] for x in t.chunks],
                    "loc": ch.locator(first[0], first[1], last[2]),
                    "teaching": any(
                        json.loads(rows[codes.index(x)]["digest"]).get("kind") == "teaching" for x in t.chunks
                    ),
                }
            )
        skipped = [{"sections": [ids[x] for x in s.chunks], "reason": s.reason} for s in out.value.skipped]
        self._set(
            mid,
            outline=json.dumps({"topics": topics, "skipped": skipped}, ensure_ascii=False),
            state="ready",
            progress=1.0,
        )

    def _after_material(self, mid: str) -> None:
        def unit(c: sqlite3.Connection) -> None:
            row = c.execute("SELECT path_id, course_id FROM material WHERE id = ?", (mid,)).fetchone()
            if row is not None and self._started(c, row[0]):
                self._queue_course(c, row[1])

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()

    # --- the course job: plan, or revise with feedback -------------------------------------------------

    def _course_inputs(
        self, c: sqlite3.Connection, course: sqlite3.Row
    ) -> tuple[dict[str, Any], dict[str, list[str]], set[str], list[str]]:
        inputs, _ = self.paths.path_inputs(c, course["path_id"])
        materials = []
        used: list[str] = []
        topic_map: dict[str, list[str]] = {}
        teaching: set[str] = set()
        for m in c.execute(
            "SELECT id, title, role, outline, position FROM material WHERE course_id = ? AND state = 'ready' "
            "ORDER BY position",
            (course["id"],),
        ).fetchall():
            used.append(m["id"])
            outline = json.loads(m["outline"])
            topics = []
            k = m["position"] + 1  # stable: a file read later does not renumber the others' topics
            for t in outline["topics"]:
                code = f"m{k}.{t['code']}"
                topic_map[code] = t["sections"]
                if t.get("teaching", True) and m["role"] not in ("exercises", "exams"):
                    teaching.add(code)
                topics.append({"code": code, "loc": t["loc"], "title": t["title"], "summary": t["summary"]})
            materials.append({"title": m["title"], "role": m["role"], "topics": topics})
        lessons_cap = max(10, min(150, len(teaching) * 2 + 4))
        return (
            {
                k: inputs[k]
                for k in (
                    "subject",
                    "goal",
                    "difficulty",
                    "goal_type",
                    "lang",
                    "custom_instructions",
                    "interests",
                )
                if k in inputs
            }
            | {
                "course": course["title"],
                "code": course["code"],
                "term": course["term"],
                "exam_date": course["exam_date"],
                "adherence": course["adherence"],
                "keep_order": bool(course["keep_order"]),
                "materials": materials,
                "max_lessons": lessons_cap,
            },
            topic_map,
            teaching,
            used,
        )

    def handle_course(self, job: Job) -> None:
        """Bring a course up to date: digest its read files (documents first), then plan it once it can be
        planned, revise it with the learner's feedback, or join files read since into its plan."""
        with self.readers.connection() as c:
            course = self._course(c, job.target_id)
            inbox = (json.loads(course["extensions"] or "{}").get("yuo") or {}).get("inbox")
            started = self._started(c, course["path_id"])
        if inbox and course["archived_at"] is None:  # the files of a path whose courses are proposed
            self._arrange(job, course)
            return
        with self.readers.connection() as c:
            if course["archived_at"] is not None or not started:
                return
            todo = [
                r[0]
                for r in c.execute(
                    "SELECT id FROM material WHERE course_id = ? AND state IN ('read', 'digesting', 'outlining') "
                    "ORDER BY kind IN ('audio', 'video'), position",
                    (course["id"],),
                )
            ]
        for mid in todo:
            if not self._has_chunks(mid):
                continue  # a recording waiting for its transcription: its own job queues this one again
            try:
                self._digest(job, mid)
                self._outline(job, mid)
            except StageFailed as e:
                if e.retryable:
                    raise
                self._set(mid, state="failed", error=str(e)[:500])
        self._align_course(course["id"])

        def decide(c: sqlite3.Connection) -> dict[str, Any] | None:
            row = self._course(c, job.target_id)
            outline = json.loads(row["outline"]) if row["outline"] else None
            if outline is None:
                if row["branch_id"] is not None or not self._plannable(c, row["id"]):
                    return None
                outline = {"status": "drafting", "rounds": []}
            elif outline.get("status") == "ready":
                new = self._unattached(c, row, outline)
                if not new:
                    return None
                outline = outline | {
                    "status": "revising",
                    "rounds": [
                        *outline.get("rounds", []),
                        self._joining_round(new, built=row["branch_id"] is not None),
                    ][-ROUNDS_MAX:],
                }
            elif outline.get("status") not in ("drafting", "revising"):
                return None
            c.execute(
                "UPDATE course SET outline = json(?) WHERE id = ?",
                (json.dumps(outline, ensure_ascii=False), row["id"]),
            )
            return outline

        outline = self.writer.run(decide)
        if outline is None:
            return
        with self.readers.connection() as c:
            course = self._course(c, job.target_id)
            inputs, topic_map, teaching, used = self._course_inputs(c, course)
        if not topic_map:
            raise StageFailed("none of this course's files could be read")
        gen = self.models.binding("generator")
        args = (course["code"], set(topic_map), teaching, course["adherence"], inputs["max_lessons"])
        if outline["status"] == "revising":
            feedback = [r["text"] for r in outline.get("rounds", [])]
            revised = self.runner.run(
                job.id,
                course_revise_spec(*args),
                gen,
                inputs | {"outline": outline["plan"], "feedback": feedback},
                data_class=DataClass.FREE_TEXT,
            )
            plan, changes = revised.value.outline, revised.value.changes
        else:
            plan = self.runner.run(
                job.id, course_spec(*args), gen, inputs, data_class=DataClass.FREE_TEXT
            ).value
            changes = []

        def unit(c: sqlite3.Connection) -> None:
            row = self._course(c, job.target_id)
            now = json.loads(row["outline"] or "{}")
            if now.get("status") not in ("drafting", "revising"):
                return
            history = now.get("history", [])
            if now.get("plan"):
                history = [*history, now["plan"]][-ROUNDS_MAX:]
            new_plan = plan.model_dump(mode="json")
            done = now | {
                "status": "ready",
                "plan": new_plan,
                "topics": topic_map,
                "topic_names": {
                    t["code"]: f"{m['title']}, {t['loc']}: {t['title']}"
                    for m in inputs["materials"]
                    for t in m["topics"]
                },
                "changes": changes,
                "history": history,
                "version": now.get("version", 0) + 1,
                "materials": used,
            }
            if row["branch_id"] is not None:  # built: what the new files add waits for the learner's yes
                done = self._propose(c, row, now, done, used)
            c.execute(
                "UPDATE course SET outline = json(?) WHERE id = ?",
                (json.dumps(done, ensure_ascii=False), job.target_id),
            )
            if row["branch_id"] is None:
                self._maybe_link(c, row["path_id"])
            if self._unattached(c, row, done):  # a file was read while this ran: join it next
                self._queue_course(c, row["id"])

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()

    def _unattached(
        self, c: sqlite3.Connection, course: sqlite3.Row, outline: dict[str, Any]
    ) -> list[sqlite3.Row]:
        """Files read since the plan was made (a plan from before this was recorded counts all as joined)."""
        if "materials" not in outline:
            return []
        joined = set(outline["materials"])
        return [
            r
            for r in c.execute(
                "SELECT id, title, position FROM material WHERE course_id = ? AND state = 'ready' ORDER BY position",
                (course["id"],),
            ).fetchall()
            if r["id"] not in joined
        ]

    @staticmethod
    def _joining_round(new: list[sqlite3.Row], *, built: bool) -> dict[str, Any]:
        names = ", ".join(f"“{r['title']}” (topics m{r['position'] + 1}.*)" for r in new)
        text = (
            f"(From Yuo, not the learner.) New material was added: {names}. Put its topics into the plan: into the "
            "skills they belong to, or into new skills where they teach something the plan does not have yet. "
            "Keep everything else as it is."
        )
        if built:
            text += (
                " The learner is already studying this course: do not remove, rename or reorder its skills."
            )
        return {"text": text, "at": clock.now(), "auto": True}

    def _propose(
        self,
        c: sqlite3.Connection,
        course: sqlite3.Row,
        before: dict[str, Any],
        after: dict[str, Any],
        used: list[str],
    ) -> dict[str, Any]:
        """A built course got new files: their passages join the skills they belong to now (lessons not written
        yet use them); rewriting lessons already written and adding new skills wait for the learner's yes."""
        joined = set(before.get("materials", []))
        new_files = [m for m in used if m not in joined]
        if not new_files:
            return after
        marks = ",".join("?" * len(new_files))
        files = c.execute(
            f"SELECT title, position FROM material WHERE id IN ({marks}) ORDER BY position", new_files
        ).fetchall()
        prefixes = tuple(f"m{r['position'] + 1}." for r in files)
        built = dict(
            c.execute(
                "SELECT code, id FROM skill WHERE branch_id = ? AND archived_at IS NULL",
                (course["branch_id"],),
            ).fetchall()
        )
        waiting = {code for u in after.get("updates", []) if u["status"] == "pending" for code in u["skills"]}
        lessons: list[str] = []
        skills: list[str] = []
        for sk in after["plan"]["skills"]:
            added = [t for t in sk.get("topics", []) if t.startswith(prefixes)]
            if sk["code"] in built:
                for t in added:
                    for sid in after["topics"].get(t, []):
                        c.execute(
                            "INSERT OR IGNORE INTO skill_anchor (skill_id, section_id, path_id, role) VALUES (?, ?, ?, "
                            "'supporting')",
                            (built[sk["code"]], sid, course["path_id"]),
                        )
                if added:
                    lessons += [
                        r[0]
                        for r in c.execute(
                            "SELECT id FROM lesson WHERE skill_id = ? AND kind = 'core' AND state = 'ready' "
                            "ORDER BY position",
                            (built[sk["code"]],),
                        )
                    ]
            elif sk["code"] not in waiting:
                skills.append(sk["code"])
        if not lessons and not skills:
            return after
        update = {
            "id": new_id(),
            "at": clock.now(),
            "materials": [r["title"] for r in files],
            "changes": after.get("changes", []),
            "lessons": lessons,
            "skills": skills,
            "status": "pending",
        }
        return after | {"updates": [*after.get("updates", []), update][-ROUNDS_MAX:]}

    def decide_update(self, course_id: str, update_id: str, accept: bool) -> dict[str, Any]:
        """The learner's answer to what new files add to a built course: rewrite those lessons with them and
        add the new skills, or leave the path as it is."""
        if accept:
            self.models.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            course = self._course(c, course_id)
            outline = json.loads(course["outline"] or "{}")
            update = next((u for u in outline.get("updates", []) if u["id"] == update_id), None)
            if update is None:
                raise NotFound(update_id)
            if update["status"] != "pending":
                raise InvalidInput("this change was already decided")
            update["status"] = "applied" if accept else "dismissed"
            if accept:
                self._add_skills(c, course, outline, update["skills"])
                for lid in update["lessons"]:
                    busy = c.execute(
                        "SELECT 1 FROM generation_job WHERE target_id = ? AND status IN "
                        "('queued', 'running', 'waiting_resource')",
                        (lid,),
                    ).fetchone()
                    if not busy:
                        c.execute(
                            "UPDATE lesson SET state = 'queued' WHERE id = ? AND state = 'ready'", (lid,)
                        )
                        enqueue(c, "lesson", EntityKind.LESSON, lid)
                self.buffer.top_up_buffer(c, course["path_id"])
            else:  # the skills it proposed leave the plan, so they are not proposed again
                gone = set(update["skills"])
                outline["plan"]["skills"] = [
                    sk | {"requires": [r for r in sk.get("requires", []) if r not in gone]}
                    for sk in outline["plan"]["skills"]
                    if sk["code"] not in gone
                ]
            c.execute(
                "UPDATE course SET outline = json(?) WHERE id = ?",
                (json.dumps(outline, ensure_ascii=False), course_id),
            )

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.course_view(course_id)

    def _add_skills(
        self, c: sqlite3.Connection, course: sqlite3.Row, outline: dict[str, Any], codes: list[str]
    ) -> None:
        """New skills from new material, at the end of the course's branch, with their lessons planned."""
        todo = [sk for sk in outline["plan"]["skills"] if sk["code"] in codes]
        if not todo:
            return
        path_id, branch_id = course["path_id"], course["branch_id"]
        ids = dict(c.execute("SELECT code, id FROM skill WHERE path_id = ?", (path_id,)).fetchall())
        todo = [sk for sk in todo if sk["code"] not in ids]
        pos = c.execute(
            "SELECT coalesce(max(position) + 1, 0) FROM skill WHERE branch_id = ?", (branch_id,)
        ).fetchone()[0]
        for n, sk in enumerate(todo):
            ids[sk["code"]] = sid = new_id()
            extra = bool(sk.get("not_in_material"))
            c.execute(
                "INSERT INTO skill (id, branch_id, path_id, code, title, summary, position, mastery_threshold, "
                "optional, merged_into_skill_id, extensions, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, "
                "json(?), NULL)",
                (sid, branch_id, path_id, sk["code"], sk["title"], sk["summary"], pos + n, int(extra),
                 json.dumps({"yuo": {"unit": sk.get("unit", ""), "not_in_material": extra}})),
            )  # fmt: skip
            for opos, o in enumerate(sk["objectives"]):
                c.execute(
                    "INSERT INTO learning_objective (id, skill_id, path_id, code, statement, bloom_level, position, "
                    "extensions, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', NULL)",
                    (new_id(), sid, path_id, o["code"], o["statement"], o["bloom_level"], opos),
                )
            for lpos, lp in enumerate(sk["lessons"]):
                c.execute(
                    "INSERT INTO lesson (id, skill_id, path_id, code, kind, position, state, current_version_id, "
                    "extensions) VALUES (?, ?, ?, ?, 'core', ?, 'planned', NULL, ?)",
                    (
                        new_id(),
                        sid,
                        path_id,
                        lp["code"],
                        lpos,
                        json.dumps({"yuo": {"planned_title": lp["title"]}}),
                    ),
                )
            first = True
            for t in sk.get("topics", []):
                for sec in outline.get("topics", {}).get(t, []):
                    c.execute(
                        "INSERT OR IGNORE INTO skill_anchor (skill_id, section_id, path_id, role) VALUES (?, ?, ?, ?)",
                        (sid, sec, path_id, "primary" if first else "supporting"),
                    )
                first = False
        for sk in todo:
            for r in sk.get("requires", []):
                if r in ids and r != sk["code"]:
                    c.execute(
                        "INSERT OR IGNORE INTO skill_prerequisite (skill_id, requires_skill_id, path_id) VALUES (?, ?, ?)",
                        (ids[sk["code"]], ids[r], path_id),
                    )
        base = c.execute("SELECT structure_version FROM path WHERE id = ?", (path_id,)).fetchone()[0]
        c.execute(
            "INSERT INTO path_change (id, path_id, base_structure_version, structure_version, ops, origin, proposal_id, "
            "device_id, at) VALUES (?, ?, ?, ?, json(?), 'learner', NULL, NULL, ?)",
            (new_id(), path_id, base, base + 1,
             json.dumps([{"op": "add_skills", "branch": course["code"], "skills": todo}], ensure_ascii=False),
             clock.now()),
        )  # fmt: skip
        c.execute(
            "UPDATE path SET structure_version = ?, updated_at = ? WHERE id = ?",
            (base + 1, clock.now(), path_id),
        )

    def course_feedback(self, course_id: str, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise InvalidInput("say what to change")
        if len(text) > FEEDBACK_MAX:
            raise InvalidInput(f"at most {FEEDBACK_MAX} characters")
        self.models.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            course = self._course(c, course_id)
            outline = json.loads(course["outline"] or "{}")
            if outline.get("status") != "ready" or course["branch_id"] is not None:
                raise InvalidInput("this course's plan is not waiting for feedback")
            rounds = [*outline.get("rounds", []), {"text": text, "at": clock.now()}][-ROUNDS_MAX:]
            c.execute(
                "UPDATE course SET outline = json(?) WHERE id = ?",
                (
                    json.dumps(outline | {"status": "revising", "rounds": rounds}, ensure_ascii=False),
                    course_id,
                ),
            )
            enqueue(c, "course", EntityKind.COURSE, course_id, priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.course_view(course_id)

    def undo_course(self, course_id: str) -> dict[str, Any]:
        def unit(c: sqlite3.Connection) -> None:
            course = self._course(c, course_id)
            outline = json.loads(course["outline"] or "{}")
            history = outline.get("history", [])
            if outline.get("status") != "ready" or not history or course["branch_id"] is not None:
                raise InvalidInput("there is no earlier plan")
            new = outline | {
                "plan": history[-1],
                "history": history[:-1],
                "rounds": outline.get("rounds", [])[:-1],
                "changes": [],
                "version": outline.get("version", 1) + 1,
            }
            c.execute(
                "UPDATE course SET outline = json(?) WHERE id = ?",
                (json.dumps(new, ensure_ascii=False), course_id),
            )

        self.writer.run(unit)
        return self.course_view(course_id)

    def retry_course(self, course_id: str) -> dict[str, Any]:
        self.models.require_ai_ready()

        def unit(c: sqlite3.Connection) -> None:
            course = self._course(c, course_id)
            outline = json.loads(course["outline"] or "{}")
            if outline.get("status") not in ("drafting", "revising"):
                raise InvalidInput("this course's plan is not being written")
            enqueue(c, "course", EntityKind.COURSE, course_id, priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.course_view(course_id)

    # --- links between courses -----------------------------------------------------------------------

    def _maybe_link(self, c: sqlite3.Connection, path_id: str) -> None:
        """When every course has a ready plan and there are two or more, find the links between them (without
        waiting for recordings still being transcribed: they join the plans later)."""
        rows = c.execute(
            "SELECT outline FROM course WHERE path_id = ? AND archived_at IS NULL", (path_id,)
        ).fetchall()
        if len(rows) < 2:
            return
        if any(not r[0] or json.loads(r[0]).get("status") != "ready" for r in rows):
            return
        state = path_state(get_path(c, path_id), "preview") or {}
        save_path_state(c, path_id, "preview", state | {"links_status": "linking"})
        enqueue(c, "course_links", EntityKind.PATH, path_id, priority=URGENT_PRIORITY)

    def handle_links(self, job: Job) -> None:
        with self.readers.connection() as c:
            p = get_path(c, job.target_id)
            inputs, _ = self.paths.path_inputs(c, job.target_id)
            courses = []
            course_of: dict[str, str] = {}
            existing: dict[str, list[str]] = {}
            concepts: dict[str, set[str]] = {}
            for row in c.execute(
                "SELECT code, title, outline FROM course WHERE path_id = ? AND archived_at IS NULL ORDER BY position",
                (job.target_id,),
            ).fetchall():
                outline = json.loads(row["outline"] or "{}")
                if outline.get("status") != "ready":
                    return  # a course is being revised: its job links again when it is done
                skills = []
                for s in outline["plan"]["skills"]:
                    terms = self._skill_concepts(c, outline, s)
                    concepts[s["code"]] = {t.lower() for t in terms}
                    course_of[s["code"]] = row["code"]
                    existing[s["code"]] = list(s["requires"])
                    skills.append({"code": s["code"], "title": s["title"], "concepts": terms or [s["title"]]})
                courses.append({"title": row["title"], "skills": skills})
        pairs = _candidate_pairs(concepts, course_of)
        out = self.runner.run(
            job.id,
            links_spec(course_of, existing),
            self.models.binding("generator"),
            {"lang": inputs["lang"], "courses": courses, "pairs": pairs[:80]},
            data_class=DataClass.CONTENT,
        )

        def unit(c: sqlite3.Connection) -> None:
            state = path_state(get_path(c, job.target_id), "preview") or {}
            save_path_state(
                c,
                job.target_id,
                "preview",
                state | {"links": out.value.model_dump(mode="json"), "links_status": "ready"},
                touch=True,
            )

        self.writer.run(unit)
        del p

    def _skill_concepts(
        self, c: sqlite3.Connection, outline: dict[str, Any], skill: dict[str, Any]
    ) -> list[str]:
        sections = [sid for t in skill.get("topics", []) for sid in outline.get("topics", {}).get(t, [])]
        seen: dict[str, None] = {}
        for sid in sections[:12]:
            row = c.execute("SELECT digest FROM material_section WHERE id = ?", (sid,)).fetchone()
            if row and row[0]:
                for term in json.loads(row[0]).get("concepts", [])[:6]:
                    seen.setdefault(term, None)
        return list(seen)[:12]

    def retry_links(self, path_id: str) -> dict[str, Any]:
        def unit(c: sqlite3.Connection) -> None:
            self._studies(c, path_id)
            enqueue(c, "course_links", EntityKind.PATH, path_id, priority=URGENT_PRIORITY)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.studies_view(path_id)

    # --- build ---------------------------------------------------------------------------------------

    def build_studies(self, path_id: str) -> dict[str, Any]:
        """The learner accepts the plan: each course with a ready plan becomes a branch; lessons follow."""

        def unit(c: sqlite3.Connection) -> None:
            p = self._studies(c, path_id)
            rows = c.execute(
                "SELECT * FROM course WHERE path_id = ? AND archived_at IS NULL AND branch_id IS NULL ORDER BY position",
                (path_id,),
            ).fetchall()
            ready = [r for r in rows if r["outline"] and json.loads(r["outline"]).get("status") == "ready"]
            if not ready:
                raise InvalidInput("no course has a plan ready to build")
            state = path_state(p, "preview") or {}
            self._build(c, path_id, ready, state.get("links") or {})
            c.execute(
                "UPDATE path SET status = 'active', updated_at = ? WHERE id = ?", (clock.now(), path_id)
            )
            save_path_state(
                c, path_id, "preview", state | {"status": "built", "built_at": clock.now()}, touch=True
            )
            self.buffer.top_up_buffer(c, path_id)

        self.writer.run(unit)
        if self.worker:
            self.worker.wake()
        return self.studies_view(path_id)

    def _build(
        self, c: sqlite3.Connection, path_id: str, courses: list[sqlite3.Row], links: dict[str, Any]
    ) -> None:
        existing = {r[0] for r in c.execute("SELECT code FROM skill WHERE path_id = ?", (path_id,))}
        branches = []
        plans: dict[str, tuple[sqlite3.Row, dict[str, Any]]] = {}
        for row in courses:
            outline = json.loads(row["outline"])
            plan = CourseOutline.model_validate(outline["plan"])
            plans[row["code"]] = (row, outline)
            skills = [
                SkillDraft(
                    code=s.code,
                    title=s.title,
                    summary=s.summary,
                    requires=[
                        r for r in s.requires if r not in existing or r in {x.code for x in plan.skills}
                    ],
                    objectives=[
                        ObjectiveDraft(code=o.code, statement=o.statement, bloom_level=o.bloom_level)
                        for o in s.objectives
                    ],
                    lessons=[LessonPlan(code=lp.code, title=lp.title) for lp in s.lessons],
                )
                for s in plan.skills
            ]
            branches.append(BranchDraft(code=row["code"], title=row["title"], skills=skills))
        grow: dict[str, object] | None = (
            {"kind": "courses"}
            if c.execute("SELECT 1 FROM branch WHERE path_id = ? LIMIT 1", (path_id,)).fetchone()
            else None
        )
        apply_tree(c, path_id, TreeDraft(branches=branches), grow=grow)
        ids = dict(c.execute("SELECT code, id FROM skill WHERE path_id = ?", (path_id,)).fetchall())
        for code, (row, outline) in plans.items():
            branch_id = c.execute(
                "SELECT id FROM branch WHERE path_id = ? AND code = ?", (path_id, code)
            ).fetchone()[0]
            c.execute(
                "UPDATE branch SET extensions = json_set(extensions, '$.yuo.course', json(?)) WHERE id = ?",
                (json.dumps({"id": row["id"], "term": row["term"], "exam_date": row["exam_date"],
                             "adherence": row["adherence"], "keep_order": bool(row["keep_order"])}), branch_id),
            )  # fmt: skip
            c.execute("UPDATE course SET branch_id = ? WHERE id = ?", (branch_id, row["id"]))
            for s in outline["plan"]["skills"]:
                c.execute(
                    "UPDATE skill SET extensions = json_set(extensions, '$.yuo.unit', ?, '$.yuo.not_in_material', json(?)), "
                    "optional = ? WHERE id = ?",
                    (
                        s.get("unit", ""),
                        json.dumps(bool(s.get("not_in_material"))),
                        int(bool(s.get("not_in_material"))),
                        ids[s["code"]],
                    ),
                )
                first = True
                for t in s.get("topics", []):
                    for sid in outline["topics"].get(t, []):
                        c.execute(
                            "INSERT OR IGNORE INTO skill_anchor (skill_id, section_id, path_id, role) VALUES (?, ?, ?, ?)",
                            (ids[s["code"]], sid, path_id, "primary" if first else "supporting"),
                        )
                    first = False
        for r in links.get("requires", []):
            if r["skill"] in ids and r["requires"] in ids:
                c.execute(
                    "INSERT OR IGNORE INTO skill_prerequisite (skill_id, requires_skill_id, path_id) VALUES (?, ?, ?)",
                    (ids[r["skill"]], ids[r["requires"]], path_id),
                )
        for x in links.get("related", []):
            if x["a"] in ids and x["b"] in ids and x["a"] != x["b"]:
                c.execute(
                    "INSERT OR IGNORE INTO skill_link (skill_id, other_skill_id, path_id, kind, note) VALUES (?, ?, ?, 'related', ?)",
                    (ids[x["a"]], ids[x["b"]], path_id, x.get("note")),
                )

    # --- coverage: which parts of each file the path teaches ----------------------------------------------

    def coverage(self, course_id: str) -> dict[str, Any]:
        """Per file, its parts in order: taught by a skill (with the lesson to open), left out (with the reason),
        or not used yet. Before an exam it answers "have I covered everything?"."""
        with self.readers.connection() as c:
            course = self._course(c, course_id)
            outline = json.loads(course["outline"] or "{}")
            skill_of: dict[str, dict[str, Any]] = {}
            if course["branch_id"] is not None:  # built: the anchors say which skill teaches a part
                for r in c.execute(
                    "SELECT a.section_id, s.id, s.title, a.role FROM skill_anchor a JOIN skill s ON s.id = a.skill_id "
                    "WHERE s.branch_id = ? AND s.archived_at IS NULL ORDER BY a.role = 'supporting'",
                    (course["branch_id"],),
                ):
                    skill_of.setdefault(r[0], {"skill_id": r[1], "skill": r[2]})
            else:  # planned: the plan's topics
                topics = outline.get("topics", {})
                for sk in (outline.get("plan") or {}).get("skills", []):
                    for t in sk.get("topics", []):
                        for sid in topics.get(t, []):
                            skill_of.setdefault(sid, {"skill_id": None, "skill": sk["title"]})
            lessons: dict[
                str, str
            ] = {}  # section -> the lesson that cites it (else the skill's first lesson)
            if course["branch_id"] is not None:
                for lid, src in c.execute(
                    "SELECT l.id, l.extensions ->> '$.yuo.sources' FROM lesson l JOIN skill s ON s.id = l.skill_id "
                    "WHERE s.branch_id = ? AND l.extensions ->> '$.yuo.sources' IS NOT NULL ORDER BY l.position",
                    (course["branch_id"],),
                ):
                    for x in json.loads(src):
                        lessons.setdefault(x["section_id"], lid)
                first = dict(
                    c.execute(
                        "SELECT s.id, (SELECT l.id FROM lesson l WHERE l.skill_id = s.id AND l.kind = 'core' "
                        "ORDER BY l.position LIMIT 1) FROM skill s WHERE s.branch_id = ?",
                        (course["branch_id"],),
                    ).fetchall()
                )
            files = []
            for m in c.execute(
                "SELECT id, title, kind, role, state, pages, duration_ms, outline FROM material WHERE course_id = ? "
                "ORDER BY position",
                (course_id,),
            ).fetchall():
                skipped: dict[str, str] = {}
                for x in json.loads(m["outline"] or "{}").get("skipped", []):
                    for sid in x["sections"]:
                        skipped[sid] = x["reason"]
                parts = []
                for r in c.execute(
                    "SELECT id, loc_kind, loc_start, loc_end FROM material_section WHERE material_id = ? AND "
                    "level = 'chunk' ORDER BY position",
                    (m["id"],),
                ):
                    taught = skill_of.get(r["id"])
                    part: dict[str, Any] = {
                        "loc_kind": r["loc_kind"],
                        "start": r["loc_start"],
                        "end": r["loc_end"],
                        "where": ch.locator(r["loc_kind"], r["loc_start"], r["loc_end"]),
                        "status": "taught" if taught else "skipped" if r["id"] in skipped else "unused",
                        "skill": taught["skill"] if taught else None,
                        "lesson_id": None,
                        "reason": skipped.get(r["id"]) if not taught else None,
                    }
                    if taught and course["branch_id"] is not None:
                        part["lesson_id"] = lessons.get(r["id"]) or first.get(taught["skill_id"])
                    parts.append(part)
                files.append(
                    {
                        "material_id": m["id"],
                        "title": m["title"],
                        "kind": m["kind"],
                        "role": m["role"],
                        "ready": m["state"] == "ready",
                        "parts": _merge_parts(parts),
                    }
                )
        return {"course_id": course_id, "title": course["title"], "files": files}

    # --- lessons built on the material ------------------------------------------------------------------

    def lesson_material(
        self, c: sqlite3.Connection, skill_id: str, lesson_id: str, budget: int = LESSON_BUDGET
    ) -> dict[str, Any] | None:
        """The excerpts a lesson is written from: its share of the skill's chunks (the skill's lessons split
        them in order), within `budget` tokens, with the course's adherence and the material's notation."""
        rows = c.execute(
            "SELECT s.id, s.material_id, s.loc_kind, s.loc_start, s.loc_end, s.text, s.tokens, s.digest, a.role, "
            "m.title AS material, m.kind FROM skill_anchor a JOIN material_section s ON s.id = a.section_id "
            "JOIN material m ON m.id = s.material_id WHERE a.skill_id = ? AND s.text IS NOT NULL "
            "ORDER BY m.position, s.position",
            (skill_id,),
        ).fetchall()
        if not rows:
            return None
        course = c.execute(
            "SELECT k.title, k.adherence FROM skill sk JOIN course k ON k.branch_id = sk.branch_id WHERE sk.id = ?",
            (skill_id,),
        ).fetchone()
        lessons = [
            r[0]
            for r in c.execute(
                "SELECT id FROM lesson WHERE skill_id = ? AND kind = 'core' ORDER BY position", (skill_id,)
            )
        ]
        primary = [r for r in rows if r["role"] == "primary"] or rows
        if lesson_id in lessons and len(lessons) > 1:  # each lesson its part of the skill's chunks, in order
            k, n = lessons.index(lesson_id), len(lessons)
            size = -(-len(primary) // n)
            primary = primary[k * size : (k + 1) * size] or primary[-1:]
        chosen: list[sqlite3.Row] = []
        used = 0
        for r in primary + [r for r in rows if r not in primary]:
            if used + r["tokens"] > budget and chosen:
                break
            chosen.append(r)
            used += r["tokens"]
        notation: dict[str, None] = {}
        for r in chosen:
            for n in json.loads(r["digest"] or "{}").get("notation", []):
                notation.setdefault(n, None)
        return {
            "course": course["title"] if course else "",
            "adherence": course["adherence"] if course else "grounded",
            "chunks": [
                {
                    "ref": f"x{i}",
                    "where": f"{r['material']}, {ch.locator(r['loc_kind'], r['loc_start'], r['loc_end'])}",
                    "text": r["text"],
                }
                for i, r in enumerate(chosen, 1)
            ],
            "notation": list(notation)[:30],
            "sources": [
                {
                    "section_id": r["id"],
                    "material_id": r["material_id"],
                    "title": r["material"],
                    "kind": r["kind"],
                    "loc_kind": r["loc_kind"],
                    "loc_start": r["loc_start"],
                    "loc_end": r["loc_end"],
                    "where": ch.locator(r["loc_kind"], r["loc_start"], r["loc_end"]),
                }
                for r in chosen
            ]
            + self._slide_sources(c, chosen),  # a lecture's part: the slides shown meanwhile
        }

    def exam_examples(self, c: sqlite3.Connection, skill_id: str, limit: int = 3) -> list[dict[str, str]]:
        """Tasks from the course's past exams and exercise sheets that match a skill (full-text ranking on its
        title and objectives): style examples for its questions, never lesson material."""
        row = c.execute(
            "SELECT k.id, sk.title FROM skill sk JOIN course k ON k.branch_id = sk.branch_id WHERE sk.id = ?",
            (skill_id,),
        ).fetchone()
        if row is None:
            return []
        text = " ".join(
            [row["title"]]
            + [
                r[0]
                for r in c.execute(
                    "SELECT statement FROM learning_objective WHERE skill_id = ? AND archived_at IS NULL",
                    (skill_id,),
                )
            ]
        )
        words = {w.lower() for w in re.findall(r"\w{4,}", text) if not w.isdigit()}
        if not words:
            return []
        query = " OR ".join(f'"{w}"' for w in sorted(words)[:40])
        rows = c.execute(
            "SELECT s.text, s.loc_kind, s.loc_start, s.loc_end, m.title FROM material_fts f "
            "JOIN material_section s ON s.rowid = f.rowid JOIN material m ON m.id = s.material_id "
            "WHERE material_fts MATCH ? AND m.course_id = ? AND m.role IN ('exams', 'exercises') AND "
            "m.state = 'ready' AND s.level = 'chunk' ORDER BY f.rank LIMIT ?",
            (query, row["id"], limit),
        ).fetchall()
        return [
            {
                "where": f"{r['title']}, {ch.locator(r['loc_kind'], r['loc_start'], r['loc_end'])}",
                "text": r["text"][:EXAMPLE_CHARS],
            }
            for r in rows
        ]

    # --- serving the learner's own file ------------------------------------------------------------------

    @contextmanager
    def material_file(self, material_id: str) -> Iterator[tuple[Path, str, str]]:
        """The stored file (the original, or the audio of a recording): path, media type, download name."""
        with self.readers.connection() as c:
            m = c.execute(
                "SELECT m.asset_hash, m.kind, m.file_name, a.media_type FROM material m JOIN asset a ON a.hash = m.asset_hash "
                "WHERE m.id = ?",
                (material_id,),
            ).fetchone()
        if m is None or self.blobs is None:
            raise NotFound(material_id)
        path = self.blobs.path(m["asset_hash"])
        if not path.exists():
            raise NotFound(material_id)
        media = m["media_type"] if "*" not in m["media_type"] else "application/octet-stream"
        name = m["file_name"] or "material"
        if m["kind"] in ("audio", "video"):
            media, name = "audio/ogg", Path(name).stem + ".ogg"
        yield path, media, name


def _studies_status(state: dict[str, Any], courses: list[dict[str, Any]], links_job: Any) -> str:
    if state.get("status", "collecting") == "collecting":
        return "collecting"
    live = [c for c in courses if not c["built"]]
    plans = [c["plan"] for c in live]
    if any(p is not None and p["status"] == "revising" for p in plans):
        return "revising"
    if live and all(p is not None and p["status"] == "ready" for p in plans):
        if len(live) >= 2 and state.get("links_status") == "linking":
            return "drafting"
        return "ready"
    return "drafting"


def _plan_view(outline: dict[str, Any] | None) -> dict[str, Any] | None:
    if outline is None:
        return None
    plan = outline.get("plan")
    topics: dict[str, list[str]] = outline.get("topics", {})
    return {
        "status": outline.get("status", "drafting"),
        "version": outline.get("version", 0),
        "skills": [
            {
                "code": s["code"],
                "title": s["title"],
                "summary": s["summary"],
                "unit": s.get("unit", ""),
                "not_in_material": bool(s.get("not_in_material")),
                "requires": s.get("requires", []),
                "topics": s.get("topics", []),
                "sections": sum(len(topics.get(t, [])) for t in s.get("topics", [])),
                "lessons": [{"code": lp["code"], "title": lp["title"]} for lp in s.get("lessons", [])],
            }
            for s in (plan or {}).get("skills", [])
        ],
        "skipped": [_skipped(x, outline.get("topic_names", {})) for x in (plan or {}).get("skipped", [])],
        "changes": outline.get("changes", []),
        "feedback": [r["text"] for r in outline.get("rounds", []) if not r.get("auto")],
        "can_undo": bool(outline.get("history")),
    }


def _skipped(entry: str, names: dict[str, str]) -> str:
    """ "m1.t3: not in the exam" as the learner reads it: the file, where, the topic, and the reason."""
    code, _, reason = entry.partition(":")
    name = names.get(code.strip())
    return f"{name} ({reason.strip()})" if name and reason.strip() else name or entry


def _candidate_pairs(concepts: dict[str, set[str]], course_of: dict[str, str]) -> list[tuple[str, str]]:
    """Skill pairs of different courses whose key terms overlap, the strongest overlaps first."""
    scored = []
    codes = sorted(concepts)
    for i, a in enumerate(codes):
        for b in codes[i + 1 :]:
            if course_of[a] == course_of[b]:
                continue
            shared = len(concepts[a] & concepts[b])
            if shared:
                scored.append((shared, a, b))
    scored.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [(a, b) for _, a, b in scored]


def _join_speech(pages: list[Page]) -> list[Page]:
    """Speech segments of a few seconds joined into stretches of about a minute, for the splitter."""
    out: list[Page] = []
    buf: list[Page] = []
    for p in pages:
        buf.append(p)
        if buf[-1].end - buf[0].start >= 60_000:
            out.append(Page(buf[0].start, buf[-1].end, " ".join(x.text for x in buf)))
            buf = []
    if buf:
        out.append(Page(buf[0].start, buf[-1].end, " ".join(x.text for x in buf)))
    return out


def _put_file(blobs: Any, src: Path) -> str:
    """Move a file into the content-addressed store (hashing it in pieces, never all in memory)."""
    import hashlib

    h = hashlib.sha256()
    with src.open("rb") as f:
        while piece := f.read(1024 * 1024):
            h.update(piece)
    digest = h.hexdigest()
    target: Path = blobs.path(digest)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        shutil.copyfile(src, tmp)
        tmp.replace(target)
    src.unlink(missing_ok=True)
    return digest


def _merge_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Neighbouring parts with the same status, skill and lesson become one (pp. 3-9 rather than 3-5, 6-9)."""
    out: list[dict[str, Any]] = []
    for p in parts:
        last = out[-1] if out else None
        same = last is not None and all(
            last[k] == p[k] for k in ("status", "skill", "lesson_id", "reason", "loc_kind")
        )
        if same and last is not None:
            last["end"] = max(last["end"], p["end"])
            last["where"] = ch.locator(last["loc_kind"], last["start"], last["end"])
        else:
            out.append(dict(p))
    return out


def vision_pages(ext: dict[str, Any]) -> list[int]:
    """The pages of a PDF read from their images, in order: every page with little text, then those missing
    the most of their formulas, up to VISION_MAX_PAGES."""
    sparse = list(ext.get("sparse", []))[:VISION_MAX_PAGES]
    formulas = sorted(
        ((int(p), share) for p, share in (ext.get("formulas") or {}).items()), key=lambda x: (-x[1], x[0])
    )
    rest = [p for p, _ in formulas[: VISION_MAX_PAGES - len(sparse)]]
    return sorted(set(sparse) | set(rest))


INBOX_TITLE = "Your material"
BEGINNING_CHARS = 600
HEADINGS = 15


def _describe_file(c: sqlite3.Connection, k: int, f: sqlite3.Row) -> str:
    """One file, for the model that proposes the courses: its name, what it is, its headings and how it begins."""
    size = (
        f"{round((f['duration_ms'] or 0) / 60000)} min"
        if f["kind"] in RECORDING
        else f"{f['pages']} {'slides' if f['kind'] == 'pptx' else 'pages'}"
        if f["pages"]
        else f["kind"]
    )
    head = f"{k}. {f['file_name']} ({f['kind']}, {size}, {ROLE_NAMES.get(f['role'], 'study material')})"
    titles = [
        r[0]
        for r in c.execute(
            "SELECT title FROM material_section WHERE material_id = ? AND level != 'chunk' AND title != '' "
            "ORDER BY position LIMIT ?",
            (f["id"], HEADINGS),
        )
    ]
    first = c.execute(
        "SELECT text FROM material_section WHERE material_id = ? AND level = 'chunk' ORDER BY position LIMIT 1",
        (f["id"],),
    ).fetchone()
    lines = [head]
    if titles:
        lines.append("   Headings: " + "; ".join(t[:80] for t in titles))
    if first and first[0]:
        lines.append(f"   Begins: <material>{' '.join(first[0].split())[:BEGINNING_CHARS]}</material>")
    elif f["kind"] in RECORDING:
        lines.append("   (still being transcribed: judge by its name)")
    return "\n".join(lines)


def _arrange_view(state: dict[str, Any], courses: list[dict[str, Any]]) -> dict[str, Any]:
    """The proposal with each file's name, and which files came after it."""
    files = {m["id"]: m for k in courses for m in k["materials"]}
    proposal = state.get("proposal")
    placed: set[str] = set()
    view = None
    if proposal:
        placed = {m for k in proposal["courses"] for m in k["files"]}
        view = {
            "title": proposal["title"],
            "goal": proposal["goal"],
            "message": proposal["message"],
            "courses": [
                {
                    "title": k["title"],
                    "term": k["term"] or None,
                    "files": [
                        {"id": m, "title": files[m]["title"], "kind": files[m]["kind"]}
                        for m in k["files"]
                        if m in files
                    ],
                }
                for k in proposal["courses"]
            ],
        }
    return {
        "status": state.get("status", "collecting"),
        "proposal": view,
        "rounds": [{"text": r["text"], "changes": r.get("changes")} for r in state.get("rounds", [])],
        "error": state.get("error"),
        "new_files": [m["id"] for m in files.values() if m["id"] not in placed and m["state"] != "failed"]
        if proposal
        else [],
    }
