"""A path from the learner's own material: courses, uploads, reading, digests, plans, feedback, links, build."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import fakes
from tests.integration.test_slice import NoPrices, drain, lessons_of
from tests.material_files import make_docx, make_pdf, make_pptx
from yuo.api.app import create_app
from yuo.core.documents import Segment, TranscriptionInterrupted
from yuo.core.errors import Conflict, NotFound
from yuo.core.ids import new_id
from yuo.core.llm import Role
from yuo.db.blobs import BlobStore
from yuo.main import Media, Runtime, start


@pytest.fixture
def llm() -> fakes.FakeLLM:
    return fakes.FakeLLM()


@pytest.fixture
def rt(db_path: Path, llm: fakes.FakeLLM, tmp_path: Path) -> Iterator[Runtime]:
    media = Media(blobs=BlobStore(tmp_path / "blobs"), media_dir=tmp_path / "media")
    r = start(db_path, {"openrouter": llm}, NoPrices(), worker=False, media=media)
    roles: tuple[tuple[Role, str], ...] = (
        ("generator", "deepseek/deepseek-v4-pro"),
        ("reviewer", "qwen/qwen3.8-27b"),
        ("grader", "deepseek/deepseek-v4-pro"),
        ("utility", "deepseek/deepseek-v4-pro"),
    )
    for role, model in roles:
        r.service.bind(role, "openrouter", model)
    yield r
    r.close()


BOOK = make_pdf(
    [f"Chapter page {n}\n" + "The derivative measures change. " * 40 for n in range(1, 7)],
    outline=[("1 Limits", 0), ("2 Derivatives", 3)],
)
NOTES = make_docx(
    [
        ("Heading1", "Kinematics"),
        ("", "Velocity is the derivative of position. " * 30),
        ("Heading1", "Forces"),
        ("", "Newton's second law. " * 30),
    ]
)


def upload(rt: Runtime, course_id: str, name: str, data: bytes, part: int = 4096) -> dict[str, Any]:
    m = rt.service.new_material(course_id, name, len(data))
    out: dict[str, Any] = m
    for off in range(0, len(data), part):
        out = rt.service.upload_part(m["id"], off, data[off : off + part])
    return out


def courses(rt: Runtime) -> tuple[str, dict[str, str]]:
    path_id = rt.service.create_studies(
        "Mechanical Engineering",
        [
            {"title": "Analysis 1", "term": "Year 1", "adherence": "only"},
            {"title": "Physics 1", "term": "Year 1"},
        ],
    )
    view = rt.service.studies_view(path_id)
    return path_id, {c["title"]: c["id"] for c in view["courses"]}


def test_material_is_read_for_free_then_planned_per_course_and_built(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id, ids = courses(rt)
    book = upload(rt, ids["Analysis 1"], "Analisi.pdf", BOOK)
    assert book["state"] == "reading" and book["role"] == "textbook"
    notes = upload(rt, ids["Physics 1"], "Appunti fisica.docx", NOTES)
    assert notes["role"] == "notes"
    drain(rt)

    view = rt.service.studies_view(path_id)
    assert view["status"] == "collecting"
    analysis = next(c for c in view["courses"] if c["title"] == "Analysis 1")
    assert analysis["materials"][0]["state"] == "read" and analysis["materials"][0]["pages"] == 6
    assert analysis["materials"][0]["chunks"] >= 2
    assert view["estimate"]["tokens"] > 0
    assert llm.stages() == []  # reading costs nothing: no model was called before the learner says go

    rt.service.start_studies(path_id)
    drain(rt)
    view = rt.service.studies_view(path_id)
    assert view["status"] == "ready", view
    stages = llm.stages()
    assert stages.count("material_outline") == 2 and stages.count("course_outline") == 2
    assert "course_links" in stages
    analysis = next(c for c in view["courses"] if c["title"] == "Analysis 1")
    plan = analysis["plan"]
    assert plan["status"] == "ready" and plan["skills"] and plan["skills"][0]["sections"] >= 1
    assert view["links"]["related"]  # both courses use derivatives
    assert lessons_of(rt, path_id) == []  # nothing is built before the learner accepts

    # the learner asks for a change in one course
    rt.service.course_feedback(analysis["id"], "Add a refresher on what I should know before")
    assert rt.service.studies_view(path_id)["status"] == "revising"
    drain(rt)
    analysis = rt.service.course_view(analysis["id"])
    assert analysis["plan"]["changes"] == ["Split the first skill in two."]
    assert any(s["not_in_material"] for s in analysis["plan"]["skills"])
    assert analysis["plan"]["feedback"] == ["Add a refresher on what I should know before"]
    revise = next(r for s, r in llm.calls if s == "course_revise")
    assert "Add a refresher" in "\n".join(m.content for m in revise.messages)
    assert rt.service.studies_view(path_id)["status"] == "ready"

    rt.service.build_studies(path_id)
    p = rt.service.path_view(path_id)
    assert p["status"] == "active"
    assert [b["title"] for b in p["branches"]] == ["Analysis 1", "Physics 1"]
    assert lessons_of(rt, path_id)
    with rt.readers.connection() as c:
        anchors = c.execute("SELECT count(*) FROM skill_anchor WHERE path_id = ?", (path_id,)).fetchone()[0]
        related = c.execute("SELECT count(*) FROM skill_link WHERE path_id = ?", (path_id,)).fetchone()[0]
        refresher = c.execute(
            "SELECT optional, extensions ->> '$.yuo.not_in_material' FROM skill WHERE code LIKE '%.extra'"
        ).fetchone()
        built = c.execute(
            "SELECT count(*) FROM course WHERE path_id = ? AND branch_id IS NOT NULL", (path_id,)
        ).fetchone()[0]
    assert anchors >= 2 and related == 1 and built == 2
    assert tuple(refresher) == (1, 1)
    assert rt.service.studies_view(path_id)["status"] == "built"

    # lessons are written from the material: the course's excerpts and its adherence rule, checked against them
    drain(rt)
    lesson_calls = [r for st, r in llm.calls if st == "lesson"]
    assert lesson_calls
    analysis_lesson = next(
        "\n".join(m.content for m in r.messages)
        for r in lesson_calls
        if "Analysis 1" in "\n".join(m.content for m in r.messages)
    )
    assert '<material ref="x1" where="Analisi' in analysis_lesson
    assert "Teach only what these excerpts contain" in analysis_lesson
    review = next(r for st, r in llm.calls if st == "review")
    assert "<material ref=" in "\n".join(m.content for m in review.messages)
    with rt.readers.connection() as c:
        lesson_id = c.execute(
            "SELECT l.id FROM lesson l JOIN skill s ON s.id = l.skill_id WHERE l.path_id = ? AND l.state = 'ready' "
            "AND s.optional = 0 LIMIT 1",
            (path_id,),
        ).fetchone()[0]
    sources = rt.service.lesson_view(lesson_id)["sources"]
    assert sources and sources[0]["loc_kind"] in ("page", "slide") and sources[0]["loc_start"] >= 1

    # coverage: every part of the book is taught by a skill, with the lesson to open
    cov = rt.service.coverage(analysis["id"])
    [book_cov] = cov["files"]
    assert book_cov["title"] == "Analisi" and book_cov["parts"]
    assert {p["status"] for p in book_cov["parts"]} <= {"taught", "skipped", "unused"}
    taught = [p for p in book_cov["parts"] if p["status"] == "taught"]
    assert taught and all(p["skill"] and p["lesson_id"] for p in taught)
    assert taught[0]["where"].startswith("p")

    # its questions are written from the same pages; under "only my material" the blind check answers from them
    items = [(st, "\n".join(m.content for m in r.messages)) for st, r in llm.calls if st == "item"]
    strict = [
        t for _, t in items if "the question and its correct answer must follow from these excerpts" in t
    ]
    assert strict and all('<material ref="x1" where="Analisi' in t for t in strict)
    assert any("Base the question on what these excerpts state." in t for _, t in items)  # Physics: grounded
    blinds = ["\n".join(m.content for m in r.messages) for st, r in llm.calls if st == "blind_batch"]
    assert any("Answer from these excerpts only" in t and "Analisi" in t for t in blinds)
    with rt.readers.connection() as c:
        sourced = c.execute(
            "SELECT count(DISTINCT x.item_version_id) FROM item_version_source x JOIN item_version v ON "
            "v.id = x.item_version_id WHERE v.status = 'passed'"
        ).fetchone()[0]
    assert sourced > 0

    # the tutor on that lesson sees the pages it cites, and shows that it does (a chip the learner can remove)
    rt.service.bind("tutor", "openrouter", "qwen/qwen3.8-27b")
    chips = rt.service.tutor_context({"lesson_id": lesson_id})["chips"]
    cited = sources[0]["title"]
    assert any(ch["kind"] == "material" and cited in ch["label"] for ch in chips)
    rt.service.send_message(new_id(), "Can you explain this again?", {"lesson_id": lesson_id})
    assert rt.service.run_tutor_turn()
    prompt = "\n".join(m.content for m in [r for st, r in llm.calls if st == "tutor"][-1].messages)
    assert "THE LEARNER'S OWN MATERIAL" in prompt and f'<material where="{cited}, ' in prompt
    assert "Appunti fisica" not in prompt  # nothing from the other course for a question about this lesson
    # a question about something elsewhere in the material: a search of all of it finds the page
    rt.service.send_message(new_id(), "How is velocity related to position?", {"lesson_id": lesson_id})
    assert rt.service.run_tutor_turn()
    prompt = "\n".join(m.content for m in [r for st, r in llm.calls if st == "tutor"][-1].messages)
    assert f'<material where="{cited}, ' in prompt and '<material where="Appunti fisica, ' in prompt
    rt.service.send_message(
        new_id(), "And without my files?", {"lesson_id": lesson_id, "excluded": ["material"]}
    )
    assert rt.service.run_tutor_turn()
    prompt = "\n".join(m.content for m in [r for st, r in llm.calls if st == "tutor"][-1].messages)
    assert "<material where=" not in prompt


def test_an_upload_resumes_from_the_bytes_received(rt: Runtime) -> None:
    _, ids = courses(rt)
    m = rt.service.new_material(ids["Physics 1"], "notes.docx", len(NOTES))
    rt.service.upload_part(m["id"], 0, NOTES[:1000])
    with pytest.raises(Exception, match="expected the part at 1000"):
        rt.service.upload_part(m["id"], 0, NOTES[:1000])
    assert rt.service.material_view(m["id"])["received"] == 1000
    done = rt.service.upload_part(m["id"], 1000, NOTES[1000:])
    assert done["state"] == "reading"


def test_unreadable_files_fail_without_stopping_the_course(rt: Runtime) -> None:
    path_id, ids = courses(rt)
    bad = upload(rt, ids["Analysis 1"], "broken.pdf", b"%PDF-1.4 nothing here")
    good = upload(rt, ids["Analysis 1"], "Analisi.pdf", BOOK)
    with pytest.raises(ValueError):
        rt.service.new_material(ids["Analysis 1"], "photo.heic", 100)
    drain(rt)
    assert rt.service.material_view(bad["id"])["state"] == "failed"
    assert rt.service.material_view(good["id"])["state"] == "read"
    rt.service.archive_course(ids["Physics 1"])
    rt.service.start_studies(path_id)
    drain(rt)
    view = rt.service.studies_view(path_id)
    assert view["status"] == "ready" and len(view["courses"]) == 1
    rt.service.delete_material(bad["id"])
    with pytest.raises(NotFound):
        rt.service.material_view(bad["id"])


def test_material_over_http(rt: Runtime) -> None:
    http = TestClient(create_app(version="test", health=dict, service=rt.service))
    created = http.post(
        "/api/studies",
        json={"title": "Engineering", "courses": [{"title": "Analysis 1", "adherence": "only"}]},
    )
    assert created.status_code == 201, created.text
    path_id = created.json()["path_id"]
    view = http.get(f"/api/studies/{path_id}").json()
    course_id = view["courses"][0]["id"]
    m = http.post(
        f"/api/courses/{course_id}/materials", json={"file_name": "a.pdf", "size": len(BOOK)}
    ).json()
    put = http.put(
        f"/api/materials/{m['id']}/upload?offset=0",
        content=BOOK,
        headers={"content-type": "application/octet-stream"},
    )
    assert put.status_code == 200 and put.json()["state"] == "reading"
    drain(rt)
    started = http.post(f"/api/studies/{path_id}/start")
    assert started.status_code == 200
    drain(rt)
    assert http.get(f"/api/studies/{path_id}").json()["status"] == "ready"
    got = http.get(f"/api/materials/{m['id']}/file")
    assert got.status_code == 200 and got.content == BOOK
    assert http.post(f"/api/courses/{course_id}/feedback", json={"text": "more"}).status_code == 200
    drain(rt)
    built = http.post(f"/api/studies/{path_id}/build")
    assert built.status_code == 200 and built.json()["status"] == "built"


class FakeFFmpeg:
    def to_speech(self, src: Path, dst: Path) -> None:
        dst.write_bytes(b"OggS speech of " + src.read_bytes()[:16])

    def duration(self, path: Path) -> float:
        return 1800.0


class FakeTranscriber:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.fast: list[bool] = []
        self.stops = 0  # times it is stopped from outside (out of memory) before it finishes

    def available(self) -> str | None:
        return None

    def transcribe(
        self,
        audio: Path,
        *,
        lang: str | None,
        prompt: str,
        progress: Any,
        fast: bool = False,
        duration_ms: int | None = None,
    ) -> list[Segment]:
        assert audio.read_bytes().startswith(b"OggS")
        if self.stops:
            self.stops -= 1
            raise TranscriptionInterrupted("the transcription was stopped at 5:00; it goes on from there")
        self.prompts.append(prompt)
        self.fast.append(fast)
        progress(0.5)
        return [
            Segment(i * 10_000, (i + 1) * 10_000, f"Today we derive velocity, part {i}. " * 8)
            for i in range(180)
        ]


def test_a_recorded_lecture_is_kept_as_audio_transcribed_and_planned(rt: Runtime, llm: fakes.FakeLLM) -> None:
    rt.service.ctx.ffmpeg = FakeFFmpeg()
    transcriber = FakeTranscriber()
    rt.service.ctx.transcriber = transcriber
    path_id, ids = courses(rt)
    video = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000
    m = upload(rt, ids["Physics 1"], "Lezione 3.mp4", video)
    assert m["role"] == "lecture" and m["kind"] == "video"
    rt.service.archive_course(ids["Analysis 1"])
    drain(rt)
    read = rt.service.material_view(m["id"])
    assert read["state"] == "read" and read["duration_ms"] == 1_800_000
    # transcribed on this machine right away, for free; nothing goes to a model before the learner starts
    assert len(transcriber.prompts) == 1 and read["chunks"] >= 2
    estimate = rt.service.studies_view(path_id)["estimate"]
    assert estimate["audio_minutes"] == 0 and estimate["tokens"] > 0
    assert llm.stages() == []
    with rt.service.material_file(m["id"]) as (path, media, name):
        assert path.read_bytes().startswith(b"OggS") and media == "audio/ogg" and name == "Lezione 3.ogg"
    rt.service.start_studies(path_id)
    drain(rt)
    done = rt.service.material_view(m["id"])
    assert done["state"] == "ready" and done["chunks"] >= 2
    with rt.readers.connection() as c:
        kinds = {
            r[0] for r in c.execute("SELECT loc_kind FROM material_section WHERE material_id = ?", (m["id"],))
        }
        videos = c.execute("SELECT count(*) FROM asset WHERE media_type = 'video/*'").fetchone()[0]
    assert kinds == {"time"} and videos == 0  # the video itself is not kept, only its speech
    assert rt.service.studies_view(path_id)["status"] == "ready"
    plan = rt.service.course_view(ids["Physics 1"])["plan"]
    assert plan is not None and plan["skills"]
    # one 30-minute lecture is a lesson or two, not a course of many small skills
    course_prompt = next(r for st, r in llm.calls if st == "course_outline").messages[-1].content
    assert "Size: 1 to 2 lessons in total" in course_prompt


def test_a_path_from_files_alone_gets_its_name_and_courses_proposed(rt: Runtime, llm: fakes.FakeLLM) -> None:
    path_id = rt.service.create_studies("", [])
    view = rt.service.studies_view(path_id)
    assert view["arrange"]["status"] == "collecting" and len(view["courses"]) == 1
    inbox = view["courses"][0]["id"]
    upload(
        rt, inbox, "Analisi 1 - dispense.pdf", make_pdf(["Limits and derivatives. " * 30], [("1 Limits", 0)])
    )
    upload(rt, inbox, "Physics kinematics.pdf", make_pdf(["Velocity and acceleration. " * 30]))
    with pytest.raises(Conflict):
        rt.service.arrange_studies(path_id)  # the files are not read yet
    drain(rt)
    assert llm.stages() == []  # read on this machine; nothing sent before the learner asks

    asked = rt.service.arrange_studies(path_id)
    assert asked["arrange"]["status"] == "working"
    drain(rt)
    arrange = rt.service.studies_view(path_id)["arrange"]
    assert arrange["status"] == "ready" and arrange["proposal"]["title"] == "Mechanical Engineering"
    assert [(k["title"], [f["title"] for f in k["files"]]) for k in arrange["proposal"]["courses"]] == [
        ("Analysis 1", ["Analisi 1 - dispense"]),
        ("Physics 1", ["Physics kinematics"]),
    ]
    prompt = "\n".join(m.content for m in llm.calls[-1][1].messages)
    assert "Headings: 1 Limits" in prompt and "Begins: <material>Limits and derivatives." in prompt
    with pytest.raises(Conflict):
        rt.service.start_studies(path_id)  # the courses come first

    rt.service.arrange_studies(path_id, "Make it one course, please")
    drain(rt)
    arrange = rt.service.studies_view(path_id)["arrange"]
    assert [k["title"] for k in arrange["proposal"]["courses"]] == ["Engineering basics"]
    assert arrange["rounds"] == [
        {"text": "Make it one course, please", "changes": "All your files are now one course."}
    ]

    late = upload(rt, inbox, "Physics exercises.txt", b"Exercise 1: a car accelerates. " * 20)
    drain(rt)
    assert rt.service.studies_view(path_id)["arrange"]["new_files"] == [late["id"]]
    with pytest.raises(Conflict):
        rt.service.accept_arrangement(path_id)  # the new file is in no course yet
    rt.service.arrange_studies(path_id)
    drain(rt)

    done = rt.service.accept_arrangement(path_id, "Engineering, year 1", ["only"])
    assert done["arrange"] is None and done["title"] == "Engineering, year 1"
    [course] = done["courses"]
    assert (
        course["title"] == "Engineering basics"
        and course["adherence"] == "only"
        and len(course["materials"]) == 3
    )
    assert course["materials"][0]["title"] == "Analisi 1 - dispense"  # in the proposal's order
    with rt.readers.connection() as c:
        assert c.execute("SELECT count(*) FROM course WHERE path_id = ?", (path_id,)).fetchone()[0] == 1
    rt.service.start_studies(path_id)  # then as any path from courses
    drain(rt)
    assert rt.service.studies_view(path_id)["status"] == "ready"


def test_a_stopped_transcription_goes_on_and_a_failed_file_can_be_tried_again(rt: Runtime) -> None:
    rt.service.ctx.ffmpeg = FakeFFmpeg()
    transcriber = FakeTranscriber()
    transcriber.stops = 1
    rt.service.ctx.transcriber = transcriber
    _, ids = courses(rt)
    m = upload(rt, ids["Physics 1"], "Lezione 3.mp4", b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000)

    def retry_now() -> None:
        rt.writer.run(
            lambda c: c.execute("UPDATE generation_job SET next_attempt_at = NULL WHERE status = 'queued'")
        )
        drain(rt)

    drain(rt)  # stopped once: still transcribing, retried after the backoff
    stopped = rt.service.material_view(m["id"])
    assert stopped["state"] == "transcribing" and "goes on from there" in stopped["error"]
    retry_now()
    assert rt.service.material_view(m["id"])["state"] == "read"

    transcriber.stops = 5  # stopped every time: the file fails, with its audio kept
    other = upload(rt, ids["Physics 1"], "Lezione 4.mp4", b"\x00\x00\x00\x18ftypmp42" + b"w" * 5000)
    drain(rt)
    retry_now()
    retry_now()
    failed = rt.service.material_view(other["id"])
    assert failed["state"] == "failed" and "when you try again" in failed["error"]
    transcriber.stops = 0
    again = rt.service.retry_material(other["id"])
    assert again["state"] == "read" and again["error"] is None  # the audio is not read from the video again
    drain(rt)
    assert rt.service.material_view(other["id"])["state"] == "read"
    with pytest.raises(Conflict):
        rt.service.retry_material(other["id"])


def heavy_once(rt: Runtime) -> None:
    assert rt.worker.run_once(urgent="heavy")


def drain_light(rt: Runtime) -> None:
    """Every job but the learner's files (reading, transcribing): a recording still being transcribed."""
    while rt.worker.run_once(urgent=True) or rt.worker.run_once(urgent=False):
        pass


def test_recordings_join_the_plan_then_the_built_path(rt: Runtime, llm: fakes.FakeLLM) -> None:
    rt.service.ctx.ffmpeg = FakeFFmpeg()
    transcriber = FakeTranscriber()
    rt.service.ctx.transcriber = transcriber
    path_id, ids = courses(rt)
    rt.service.archive_course(ids["Analysis 1"])
    physics = ids["Physics 1"]
    video = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000
    lecture = upload(rt, physics, "Lezione 1.mp4", video)
    upload(rt, physics, "Appunti.docx", NOTES)
    heavy_once(rt)  # the notes are read first: seconds, where the recording takes minutes
    assert rt.service.material_view(lecture["id"])["chunks"] == 0

    # the plan does not wait for the recording
    rt.service.start_studies(path_id)
    drain_light(rt)
    course = rt.service.course_view(physics)
    assert course["plan"]["status"] == "ready" and rt.service.studies_view(path_id)["status"] == "ready"
    first = {s["code"] for s in course["plan"]["skills"]}
    assert all(t.startswith("m2.") for s in course["plan"]["skills"] for t in s["topics"])

    # transcribed, it joins the plan by itself, and the learner is told what changed
    drain(rt)
    course = rt.service.course_view(physics)
    assert rt.service.material_view(lecture["id"])["state"] == "ready"
    assert course["plan"]["changes"] == ["The new lecture joined the plan."]
    assert course["plan"]["feedback"] == []  # Yuo's own round is not shown as the learner's request
    assert any(t.startswith("m1.") for s in course["plan"]["skills"] for t in s["topics"])
    assert first < {s["code"] for s in course["plan"]["skills"]}

    rt.service.build_studies(path_id)
    drain(rt)
    with rt.readers.connection() as c:
        skill_one = c.execute(
            "SELECT id FROM skill WHERE path_id = ? AND code = 'physics-1.s1'", (path_id,)
        ).fetchone()[0]
        ready = c.execute(
            "SELECT id FROM lesson WHERE skill_id = ? AND state = 'ready'", (skill_one,)
        ).fetchall()
        skills_before = c.execute("SELECT count(*) FROM skill WHERE path_id = ?", (path_id,)).fetchone()[0]
    assert ready

    # a lecture added after the build: its passages join the skills now; rewrites and new skills wait for a yes
    rt.service.put_setting("material.transcription", "faster", "installation")
    later = upload(rt, physics, "Lezione 2.mp4", video + b"2")
    drain(rt)
    assert transcriber.fast == [False, True]  # the learner chose speed for the hours still to come
    assert rt.service.material_view(later["id"])["state"] == "ready"
    course = rt.service.course_view(physics)
    [update] = course["updates"]
    assert update["materials"] == ["Lezione 2"] and update["changes"] == ["The new lecture joined the plan."]
    assert [x["id"] for x in update["lessons"]] == [r[0] for r in ready]
    assert update["skills"]
    with rt.readers.connection() as c:
        joined = c.execute(
            "SELECT count(*) FROM skill_anchor a JOIN material_section s ON s.id = a.section_id WHERE a.skill_id = ? "
            "AND s.material_id = ? AND a.role = 'supporting'",
            (skill_one, later["id"]),
        ).fetchone()[0]
    assert joined >= 1

    lessons_before = len([st for st, _ in llm.calls if st == "lesson"])
    course = rt.service.decide_update(physics, update["id"], True)
    assert course["updates"] == []
    drain(rt)
    with rt.readers.connection() as c:
        versions = c.execute(
            "SELECT count(*) FROM lesson_version WHERE lesson_id = ? AND status = 'passed'", (ready[0][0],)
        ).fetchone()[0]
        skills_after = c.execute("SELECT count(*) FROM skill WHERE path_id = ?", (path_id,)).fetchone()[0]
    assert versions == 2 and skills_after == skills_before + len(update["skills"])
    rewrite = [r for st, r in llm.calls if st == "lesson"][lessons_before]
    assert "Lezione 2" in "\n".join(m.content for m in rewrite.messages)
    with pytest.raises(Exception, match="already decided"):
        rt.service.decide_update(physics, update["id"], False)


EXAM = make_pdf(["Exam 2024, task 1: compute the derivative of x^3 at x = 2 and explain the change. " * 6])


def test_past_exams_shape_the_questions_and_a_mock_exam_covers_the_course(
    rt: Runtime, llm: fakes.FakeLLM
) -> None:
    from tests.integration.test_study import Learner

    path_id = rt.service.create_studies("Analysis", [{"title": "Analysis 1", "adherence": "only"}])
    course_id = rt.service.studies_view(path_id)["courses"][0]["id"]
    upload(rt, course_id, "Analisi.pdf", BOOK)
    exam = upload(rt, course_id, "Esame 2024.pdf", EXAM)
    assert exam["role"] == "exams"
    drain(rt)
    rt.service.start_studies(path_id)
    drain(rt)
    rt.service.build_studies(path_id)
    drain(rt)

    # a past exam is never a lesson, but its matching tasks are the style of the questions (not of the blind check)
    items = ["\n".join(m.content for m in r.messages) for st, r in llm.calls if st == "item"]
    assert items and any('kind="exam task" where="Esame 2024' in t for t in items)
    blinds = ["\n".join(m.content for m in r.messages) for st, r in llm.calls if st == "blind_batch"]
    assert blinds and not any("exam task" in t for t in blinds)

    # the mock exam: the test banks are written first, then two questions per skill, scored per skill
    first = rt.service.start_mock_exam(course_id)
    assert "job_id" in first
    for _ in range(10):
        drain(rt)
        mock = rt.service.start_mock_exam(course_id)
        if "assessment_id" in mock:
            break
    assert mock["purpose"] == "skill_test"
    with rt.readers.connection() as c:
        skills = c.execute(
            "SELECT count(*) FROM skill s JOIN course k ON k.branch_id = s.branch_id WHERE k.id = ?",
            (course_id,),
        ).fetchone()[0]
    assert len(mock["items"]) == 2 * skills
    outcome = Learner(rt, llm).take(mock)["outcome"]["mock"]
    assert outcome["course_id"] == course_id and outcome["passed"] and len(outcome["skills"]) == skills
    with rt.readers.connection() as c:  # practice for the exam: nothing is marked mastered or failed
        assert (
            c.execute(
                "SELECT count(*) FROM learning_event WHERE type IN ('skill.test_result', 'skill.placed')"
            ).fetchone()[0]
            == 0
        )


def test_pages_with_formulas_are_read_from_their_images_when_asked(rt: Runtime, llm: fakes.FakeLLM) -> None:
    gaps = "The chain rule. " * 40 + "\nThe composite is given by . Its rate at is , and .\na.\nb. , , ,"
    pdf = make_pdf(["The derivative measures change. " * 40, "f'(x)", gaps])
    path_id = rt.service.create_studies("Analysis", [{"title": "Analysis 1"}])
    course_id = rt.service.studies_view(path_id)["courses"][0]["id"]
    m = upload(rt, course_id, "Analisi.pdf", pdf)
    drain(rt)
    m = rt.service.material_view(m["id"])
    assert m["sparse_pages"] == 1 and m["formula_pages"] == 1 and m["vision"] is None
    assert "material_vision" not in llm.stages()  # nothing is sent to a model until the learner asks

    asked = rt.service.read_pages(m["id"])
    assert asked["state"] == "reading" and asked["vision"] == "wanted" and asked["vision_total"] == 2
    drain(rt)
    m = rt.service.material_view(m["id"])
    assert m["state"] == "read" and m["vision"] == "done" and m["vision_pages"] == 2
    with rt.readers.connection() as c:
        text = "\n".join(
            r[0]
            for r in c.execute(
                "SELECT text FROM material_section WHERE material_id = ? AND level = 'chunk'", (m["id"],)
            )
        )
    assert "[p. 2, read from the page image]" in text and "\\lim_{h \\to 0}" in text
    assert "[p. 3, read from the page image]" in text and "given by ." not in text  # replaced, not added to
    with pytest.raises(Conflict):
        rt.service.read_pages(m["id"])

    rt.service.start_studies(path_id)  # the plan is built with what the images said
    work = rt.service.studies_view(path_id)[
        "work"
    ]  # nothing summarised yet: one file's parts, its outline, a plan
    assert work["done"] == 0 and work["total"] > 7 and work["step"] is None
    drain(rt)
    assert rt.service.studies_view(path_id)["status"] == "ready"
    digest = next(r for st, r in llm.calls if st == "material_digest")
    assert "read from the page image" in "\n".join(x.content for x in digest.messages)


def test_a_lecture_is_matched_to_its_slides_and_its_lessons_cite_both(
    rt: Runtime, llm: fakes.FakeLLM
) -> None:
    rt.service.ctx.ffmpeg = FakeFFmpeg()
    rt.service.ctx.transcriber = FakeTranscriber()  # "Today we derive velocity, part N" for 30 minutes
    path_id, ids = courses(rt)
    rt.service.archive_course(ids["Analysis 1"])
    deck = make_pptx(
        [
            ("Course rules", ["Exam dates and office hours"]),
            ("Velocity", ["We derive velocity from position", "Velocity as a derivative"]),
            ("Momentum", ["Conservation of momentum in collisions"]),
        ]
    )
    slides = upload(rt, ids["Physics 1"], "Slides fisica.pptx", deck)
    talk = upload(rt, ids["Physics 1"], "Lezione 3.mp4", b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000)
    assert slides["role"] == "slides"
    drain(rt)
    rt.service.start_studies(path_id)
    drain(rt)
    with rt.readers.connection() as c:
        found = json.loads(
            c.execute(
                "SELECT extensions ->> '$.yuo.slides' FROM material WHERE id = ?", (talk["id"],)
            ).fetchone()[0]
        )
    assert found["material_id"] == slides["id"] and {r[2] for r in found["runs"]} == {2}  # the velocity slide

    rt.service.build_studies(path_id)
    drain(rt)
    with rt.readers.connection() as c:
        lessons = [
            r[0] for r in c.execute("SELECT id FROM lesson WHERE path_id = ? AND state = 'ready'", (path_id,))
        ]
    cites = [rt.service.lesson_view(x)["sources"] for x in lessons]
    both = [s for s in cites if {x["loc_kind"] for x in s} == {"time", "slide"}]
    assert both, cites
    assert any(x["title"] == "Slides fisica" and x["loc_start"] <= 2 <= x["loc_end"] for x in both[0])

    # the slides are removed from the built course: the lessons that cite them are written again without them
    before = len([s for s, _ in llm.calls if s == "lesson"])
    rt.service.delete_material(slides["id"])
    with rt.readers.connection() as c:
        anchors = c.execute(
            "SELECT count(*) FROM skill_anchor a JOIN material_section s ON s.id = a.section_id WHERE s.material_id = ?",
            (slides["id"],),
        ).fetchone()[0]
    assert anchors == 0
    drain(rt)
    assert len([s for s, _ in llm.calls if s == "lesson"]) > before
    after = [rt.service.lesson_view(x)["sources"] for x in lessons]
    assert all(x["title"] != "Slides fisica" for s in after for x in s)
    assert any(x["loc_kind"] == "time" for s in after for x in s)
