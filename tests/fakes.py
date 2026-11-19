"""A scripted LLM port: answers every stage with valid (or deliberately broken) JSON, no network.

It remembers the items it wrote, so its blind solver can answer the shuffled view correctly, like a
competent model would.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from yuo.core.llm import Completion, Request, Usage

WORDS = (
    "A join combines rows from two tables when a condition on their columns holds, so the result "
    "shows matching pairs side by side. "
)
TITLES = ["Select", "Filtering", "Inner joins", "Outer joins", "Grouping", "Windows"]


def tree(skills_per_branch: int = 2, lessons_per_skill: int = 1) -> dict[str, Any]:
    branches = []
    prev: str | None = None
    for b in range(2):
        skills = []
        for s in range(skills_per_branch):
            code = f"sql.b{b}.s{s}"
            title = TITLES[(b * skills_per_branch + s) % len(TITLES)]
            skills.append(
                {
                    "code": code,
                    "title": title,
                    "summary": f"{title} in practice.",
                    "requires": [prev] if prev else [],
                    "objectives": [
                        {
                            "code": f"{code}.o1",
                            "statement": f"Write a query using {title.lower()}",
                            "bloom_level": "apply",
                        }
                    ],
                    "lessons": [
                        {"code": f"{code}.l{n}", "title": f"{title}: part {n}"}
                        for n in range(1, lessons_per_skill + 1)
                    ],
                }
            )
            prev = code
        branches.append({"code": f"sql.b{b}", "title": f"Branch {b}", "skills": skills})
    return {"branches": branches}


def lesson(words: int = 1000, title: str = "Select: the basics") -> dict[str, Any]:
    para = WORDS * max(1, round(words / 4 / 22))
    return {
        "title": title,
        "est_minutes": 8,
        "blocks": [
            {"type": "heading", "level": 1, "text": title},
            *[{"type": "paragraph", "text": para} for _ in range(4)],
            {
                "type": "code",
                "language": "sql",
                "text": "SELECT * FROM a JOIN b ON a.id = b.a_id;",
                "caption": None,
            },
        ],
    }


def review(verdict: str = "pass") -> dict[str, Any]:
    issues = (
        []
        if verdict == "pass"
        else [
            {
                "severity": "major",
                "where": "b2",
                "claim": "joins drop rows",
                "correction": "inner joins drop unmatched rows",
            }
        ]
    )
    return {"verdict": verdict, "issues": issues, "level_fit": "fits"}


def item(
    objective: str = "sql.b0.s0.o1", answer: str = "b", prompt: str = "Which clause picks the columns?"
) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "options": [
            {"id": "a", "text": "FROM"},
            {"id": "b", "text": "SELECT list"},
            {"id": "c", "text": "WHERE"},
            {"id": "d", "text": "ORDER BY"},
        ],
        "answer": answer,
        "objective_code": objective,
    }


_count = {"n": 0}


def _uniq() -> int:
    _count["n"] += 1
    return _count["n"]


def draft_for(kind: str, objective: str) -> dict[str, Any]:
    n = _uniq()
    match kind:
        case "mcq":
            return item(objective, prompt=f"Which clause picks the columns? (v{n})")
        case "multi":
            return {
                "prompt": f"Which are join types? Select all. (v{n})",
                "options": [
                    {"id": "a", "text": "INNER"},
                    {"id": "b", "text": "LEFT"},
                    {"id": "c", "text": "SIDEWAYS"},
                    {"id": "d", "text": "DIAGONAL"},
                ],
                "answers": ["a", "b"],
                "objective_code": objective,
            }
        case "cloze":
            return {
                "text": f"A {{{{1}}}} join keeps only matching rows (v{n}).",
                "blanks": [{"n": 1, "answers": ["inner", "INNER JOIN"]}],
                "objective_code": objective,
            }
        case "ordering":
            return {
                "prompt": f"Order the clauses of a query (v{n})",
                "steps": [
                    {"id": "a", "text": "SELECT"},
                    {"id": "b", "text": "FROM"},
                    {"id": "c", "text": "WHERE"},
                ],
                "objective_code": objective,
            }
        case "matching":
            return {
                "prompt": f"Match the join to what it keeps (v{n})",
                "pairs": [
                    {"left": "INNER", "right": "matches only"},
                    {"left": "LEFT", "right": "all left rows"},
                    {"left": "FULL", "right": "all rows"},
                ],
                "objective_code": objective,
            }
        case "flashcard":
            return {
                "front": f"What does an inner join keep? (v{n})",
                "back": "Only matching rows.",
                "objective_code": objective,
            }
        case "short_answer":
            return {
                "prompt": f"Explain what a left join keeps. (v{n})",
                "rubric": [
                    {"point": "keeps all left rows", "weight": 2},
                    {"point": "nulls for no match", "weight": 1},
                ],
                "model_answer": "All rows of the left table, with nulls where nothing matches.",
                "objective_code": objective,
            }
    raise AssertionError(kind)


SENTENCE = "A join pairs each row of one table with the matching rows of the other table by a shared key."


def video_script(scenes: int = 4, per_scene: int = 4, words: int = 240) -> dict[str, Any]:
    n = scenes * per_scene
    reps = max(1, round(words / n / len(SENTENCE.split())))
    return {
        "title": "Joins",
        "scenes": [
            {"id": f"s{i}", "label": f"Part {i}", "segments": [" ".join([SENTENCE] * reps)] * per_scene}
            for i in range(scenes)
        ],
    }


def video_module(ids: list[str], extra: str = "") -> str:
    comps = "\n".join(
        f"const C{i}: React.FC<SceneProps> = ({{segs}}) => {{ const {{at}} = useBeats(segs); {extra}"
        f"return <Center><Pop p={{at(0)}}><div style={{{{fontSize: 64, color: C.text}}}}>Part {i}</div></Pop></Center>; }};"
        for i in range(len(ids))
    )
    entries = ", ".join(f"{sid}: {{label: 'Part {i}', component: C{i}}}" for i, sid in enumerate(ids))
    return (
        "import React from 'react';\nimport {Center, Pop, useBeats} from '../kit';\nimport type {SceneDef, SceneProps} "
        f"from '../kit';\nimport {{C}} from '../theme';\n{comps}\nexport const SCENES: Record<string, SceneDef> = {{{entries}}};\n"
    )


def next_check() -> dict[str, Any]:
    """Three direction questions and a quiz of three; the right option is always the first."""
    return {
        "questions": [
            {"prompt": f"Where next {n}?", "options": [f"choice {n}a", f"choice {n}b"]} for n in (1, 2, 3)
        ],
        "quiz": [
            {
                "topic": f"beyond {n}",
                "prompt": f"Beyond {n}?",
                "options": [f"right {n}", f"wrong {n}a", f"wrong {n}b"],
                "answer": 0,
            }
            for n in (1, 2, 3)
        ],
    }


def next_directions(text: str) -> dict[str, Any]:
    """Deeper, wider and apply; a second proposal (with turned-down titles) gets new titles."""
    again = "turned these down" in text
    tag = " again" if again else ""
    return {
        "directions": [
            {
                "code": f"{k}{'-2' if again else ''}",
                "kind": k,
                "title": f"Go {k}{tag}",
                "reason": f"You asked to go {k}.",
                "preview": [f"{k} skill 1", f"{k} skill 2"],
            }
            for k in ("deeper", "wider", "apply")
        ]
    }


def next_grow(text: str) -> dict[str, Any]:
    """One new branch of two skills; the first builds on the path's first skill."""
    first = re.findall(r"^- [^:]+: ([a-z0-9._-]+) \(", text, re.MULTILINE)[0]

    def skill(n: int, requires: list[str]) -> dict[str, Any]:
        return {
            "code": f"grow.s{n}",
            "title": f"Grown skill {n}",
            "summary": "Builds on what you know.",
            "requires": requires,
            "objectives": [
                {"code": f"grow.s{n}.o1", "statement": f"Apply grown skill {n}", "bloom_level": "apply"}
            ],
            "lessons": [{"code": f"grow.s{n}.l1", "title": f"Grown lesson {n}"}],
        }

    return {
        "branches": [
            {"code": "grow.b0", "title": "Grown branch", "skills": [skill(0, [first]), skill(1, ["grow.s0"])]}
        ]
    }


def level_check() -> dict[str, Any]:
    """Eight questions over levels 1 to 5; the right option is always the first."""
    levels = [1, 1, 2, 2, 3, 4, 4, 5]
    return {
        "questions": [
            {
                "topic": f"topic {n}",
                "level": lvl,
                "prompt": f"Question {n}?",
                "options": [f"right {n}", f"wrong {n}a", f"wrong {n}b"],
                "answer": 0,
            }
            for n, lvl in enumerate(levels, 1)
        ]
    }


def video_reply(script: dict[str, Any] | None = None, tsx: str | None = None) -> str:
    script = script or video_script()
    tsx = tsx if tsx is not None else video_module([s["id"] for s in script["scenes"]])
    return f"```json\n{json.dumps(script)}\n```\n```tsx\n{tsx}```"


TUTOR_REPLY = (
    "Good question. Think about which rows the result keeps, then look at the lesson's second example."
)

TYPE_HINTS = (
    ("single-choice", "mcq"),
    ("selects all", "multi"),
    ("fill-the-gap", "cloze"),
    ("ordering item", "ordering"),
    ("matching item", "matching"),
    ("flashcard", "flashcard"),
    ("short-answer", "short_answer"),
)


def bank_question(codes: list[str], n: int | None = None, answer: str = "c") -> dict[str, Any]:
    """One valid review question (options of similar length, hints and rationales that keep the key)."""
    n = n or _uniq()
    return {
        # distinct words per question: the bank drops questions that repeat one another
        "prompt": "Which join fits a report over " + " ".join(f"table{n}x{k}" for k in range(8)) + "?",
        "options": [
            {"id": "a", "text": "An inner join on the id"},
            {"id": "b", "text": "A cross join of both"},
            {"id": "c", "text": "A left join from customers"},
            {"id": "d", "text": "A self join on customers"},
        ],
        "answer": answer,
        "objective_codes": codes,
        "kind": "scenario" if len(codes) > 1 else "apply",
        "level": 2,
        "concept": "outer joins keep rows",
        "revisit": "Reading, the section on outer joins",
        "hints": [
            "Think about which rows must never disappear.",
            "One table has to be kept whole.",
            "Keep customers whole and attach orders.",
        ],
        "rationales": [
            {"id": "a", "why": "It drops customers that have no order."},
            {"id": "b", "why": "It pairs every customer with every order."},
            {"id": "c", "why": "It keeps every customer and fills the gaps with nulls."},
            {"id": "d", "why": "It compares customers with each other, not with orders."},
        ],
        "explanation": "Only an outer join that keeps the customer side returns customers without orders.",
    }


def bank(request: Request) -> dict[str, Any]:
    """The bank the prompt asks for: N single questions over the lesson's objectives, M cross questions."""
    text = "\n".join(m.content for m in request.messages)
    single = int(re.search(r"Write (\d+) single-lesson questions", text)[1])  # type: ignore[index]
    cross = int(m[1]) if (m := re.search(r"and (\d+) cross-lesson questions", text)) else 0
    own_part = text.split("Objectives of this lesson:\n", 1)[1].split("\n\n", 1)[0]
    own = re.findall(r"^- ([a-z0-9._-]+):", own_part, re.MULTILINE)
    partner_part = text.split("Partner lessons", 1)[1] if "Partner lessons" in text else ""
    partner = [c for c in re.findall(r"^- ([a-z0-9._-]+):", partner_part.split("Lesson:\n")[0], re.MULTILINE)]
    partner = [c for c in partner if c not in own]
    questions = [bank_question([own[i % len(own)]], answer="abcd"[i % 4]) for i in range(single)]
    questions += [bank_question([own[0], partner[i % len(partner)]]) for i in range(cross if partner else 0)]
    return {"questions": questions}


def support() -> dict[str, Any]:
    return {
        "hints": ["Think about what the result looks like.", "It is near the start.", "It names the output."],
        "solution": "Worked solution.",
        "explanations": [],
    }


def blind(answer: Any = "b") -> dict[str, Any]:
    return {"answer": answer, "confidence": "high", "reason": "fake"}


def material_digest(text: str) -> dict[str, Any]:
    codes = re.findall(r'<material chunk="(c\d+)"', text)
    return {
        "digests": [
            {
                "chunk": c,
                "kind": "teaching",
                "summary": f"Chunk {c} explains part of the subject.",
                "concepts": ["derivative", f"concept {c}"],
                "definitions": [],
                "formulas": [],
                "notation": [],
            }
            for c in codes
        ]
    }


def material_outline(text: str) -> dict[str, Any]:
    codes = re.findall(r"^- (c\d+) \[", text, re.MULTILINE)
    topics = [
        {
            "title": f"Topic {n + 1}",
            "summary": "What it teaches.",
            "chunks": codes[i : i + 2],
            "concepts": ["derivative"],
        }
        for n, i in enumerate(range(0, len(codes), 2))
    ]
    return {"topics": topics, "skipped": []}


def course_outline(text: str, extra: bool = False) -> dict[str, Any]:
    code = re.search(r"\(code `([a-z0-9.-]+)`\)", text)
    assert code is not None
    c = code.group(1)
    topics = re.findall(r"^- (m\d+\.t\d+) \[", text, re.MULTILINE)
    skills = []
    prev: str | None = None
    for n, t in enumerate(topics, 1):
        sc = f"{c}.s{n}"
        skills.append(
            {
                "code": sc,
                "title": f"Skill {n}",
                "summary": "Built on the material.",
                "unit": f"Chapter {n}",
                "topics": [t],
                "not_in_material": False,
                "requires": [prev] if prev else [],
                "objectives": [
                    {"code": f"{sc}.o1", "statement": "Explain the idea", "bloom_level": "understand"}
                ],
                "lessons": [{"code": f"{sc}.l1", "title": f"Lesson {n}"}],
            }
        )
        prev = sc
    if extra:
        skills.append(
            {
                "code": f"{c}.extra",
                "title": "A prerequisite",
                "summary": "Not in the material.",
                "unit": "Before",
                "topics": [],
                "not_in_material": True,
                "requires": [],
                "objectives": [
                    {"code": f"{c}.extra.o1", "statement": "Recall it", "bloom_level": "remember"}
                ],
                "lessons": [{"code": f"{c}.extra.l1", "title": "Refresher"}],
            }
        )
    return {"skills": skills, "skipped": []}


def joined_outline(text: str) -> dict[str, Any]:
    """The plan as it was, with a new file's topics: the first joins the first skill, the others are new skills."""
    found = re.search(r"The current plan \(JSON\):\n(.*?)\n\nThe learner checked", text, re.DOTALL)
    assert found is not None
    plan: dict[str, Any] = json.loads(found.group(1))
    code = re.search(r"\(code `([a-z0-9.-]+)`\)", text)
    assert code is not None
    used = {t for sk in plan["skills"] for t in sk["topics"]} | {x.split(":")[0] for x in plan["skipped"]}
    new = [t for t in re.findall(r"^- (m\d+\.t\d+) \[", text, re.MULTILINE) if t not in used]
    if new:
        plan["skills"][0]["topics"].append(new[0])
    for n, t in enumerate(new[1:], 1):
        sc = f"{code.group(1)}.n{t.replace('.', '-')}"
        plan["skills"].append(
            {
                "code": sc,
                "title": f"New skill {n}",
                "summary": "From the new lecture.",
                "unit": "Lecture",
                "topics": [t],
                "not_in_material": False,
                "requires": [plan["skills"][0]["code"]],
                "objectives": [{"code": f"{sc}.o1", "statement": "Explain it", "bloom_level": "understand"}],
                "lessons": [{"code": f"{sc}.l1", "title": f"New lesson {n}"}],
            }
        )
    return plan


def course_links(text: str) -> dict[str, Any]:
    m = re.search(r"Pairs worth checking \(their concepts overlap\): ([a-z0-9.-]+) / ([a-z0-9.-]+)", text)
    if not m:
        return {"requires": [], "related": []}
    return {"requires": [], "related": [{"a": m.group(1), "b": m.group(2), "note": "both use derivatives"}]}


def stage_of(request: Request) -> str:
    text = "\n".join(m.content for m in request.messages)
    for needle, stage in (
        ("is choosing how it goes on", "next_check"),
        ("Propose how a learner's path goes on", "next_directions"),
        ("Grow an existing skill tree", "next_grow"),
        ("Write a short level check", "level_check"),
        ("is checking the plan of their learning path", "tree_revise"),
        ("Summarise each chunk of a learner's study material", "material_digest"),
        ("Group a learner's study material into topics", "material_outline"),
        ("Their text could\nnot be extracted", "material_vision"),
        ("Organise a learner's study material into one learning path", "studies_arrange"),
        ("The learner checked this plan and asked for changes", "course_revise"),
        ("Plan a course of a learner's studies", "course_outline"),
        ("Find where the courses depend on each other", "course_links"),
        ("Plan a learning path", "tree"),
        ("Write one reading lesson", "lesson"),
        ("independent reviewer", "review"),
        ("Write review questions for the lesson", "review_bank"),
        ("Write one practice item", "item"),
        ("Write support for this practice item", "support"),
        ("Answer this practice item", "blind"),
        ("practice items as a learner would see them", "blind_batch"),
        ("Grade a learner's short answer", "grade"),
        ("asks for an extra lesson", "place"),
        ("You are a leak checker", "leak_check"),
        ("You write video lessons as React components", "video_author"),
        ("strict reviewer of short educational explainer videos", "video_visual"),
        ("strict expert reviewer of a short educational explainer video", "video_text"),
        ("check an educational explainer video against the lesson", "video_ground"),
        ("You are a phonetician", "pronounce"),
        ("the Yuo tutor", "tutor"),
    ):
        if needle in text:
            return stage
    return "unknown"


def objective_in(request: Request) -> str:
    text = "\n".join(m.content for m in request.messages)
    m = re.search(r"^- ([a-z0-9._-]+\.o1):", text, re.MULTILINE)
    return m.group(1) if m else "sql.b0.s0.o1"


def kind_of(request: Request) -> str:
    text = "\n".join(m.content for m in request.messages)
    return next(k for hint, k in TYPE_HINTS if hint in text)


@dataclass
class FakeLLM:
    name: str = "openrouter"
    version: str = "test"
    remote: bool = True
    script: dict[str, list[Any]] = field(
        default_factory=dict
    )  # stage -> queued replies (dict, raw str or callable)
    calls: list[tuple[str, Request]] = field(default_factory=list)
    cost_micros: int = 1000
    notional: bool = False
    drafts: list[dict[str, Any]] = field(default_factory=list)
    grade_met: list[bool] | None = None
    wrong_blind: bool = False

    def default(self, stage: str, request: Request) -> Any:
        text = "\n".join(m.content for m in request.messages)
        match stage:
            case "tree":
                return tree()
            case "level_check":
                return level_check()
            case "material_digest":
                return material_digest(text)
            case "material_outline":
                return material_outline(text)
            case "material_vision":
                pages = re.search(r"images of pages ([\d, ]+) of", text)
                assert pages and request.messages[-1].images  # the page images go with the request
                return {
                    "pages": [
                        {
                            "page": int(n),
                            "text": f"$f'(x) = \\lim_{{h \\to 0}} \\frac{{f(x+h) - f(x)}}{{h}}$ on page {n}",
                        }
                        for n in pages.group(1).split(", ")
                    ]
                }
            case "studies_arrange":
                return studies_arrange(text)
            case "course_outline":
                return course_outline(text)
            case "course_revise" if "New material was added" in text:
                return {"changes": ["The new lecture joined the plan."], "outline": joined_outline(text)}
            case "course_revise":
                return {
                    "changes": ["Split the first skill in two."],
                    "outline": course_outline(text, extra=True),
                }
            case "course_links":
                return course_links(text)
            case "tree_revise":
                return {"changes": ["Added a third skill to each branch."], "tree": tree(skills_per_branch=3)}
            case "next_check":
                return next_check()
            case "next_directions":
                return next_directions(text)
            case "next_grow":
                return next_grow(text)
            case "lesson":
                m = re.search(r"Write (\d+) to (\d+) words", text)
                return lesson(words=(int(m[1]) + int(m[2])) // 2 if m else 1000)
            case "review":
                return review()
            case "item":
                return draft_for(kind_of(request), objective_in(request))
            case "review_bank":
                return bank(request)
            case "support":
                item = json.loads(text.rsplit("):\n", 1)[1])
                ids = [o["id"] for o in item.get("options", [])]
                return support() | {"explanations": [{"id": i, "why": f"because {i}"} for i in ids]}
            case "blind":
                return self.solve(json.loads(text.split("\n\n", 1)[1]))
            case "blind_batch":
                views = json.loads(text.split("\n\n", 1)[1].split("\n\nThese items are about", 1)[0])
                return {f"item_{v['n']}": self.solve(v) for v in views}
            case "grade":
                return {
                    "met": self.grade_met or [True, False],
                    "rationale": "Kept all left rows; missed the nulls.",
                }
            case "place":
                codes = re.findall(r"^- ([a-z0-9._-]+):", text, re.MULTILINE)
                return {"skill_code": codes[0], "title": "Requested lesson"}
            case "tutor":
                return TUTOR_REPLY
            case "leak_check":
                return {"leak": False}
            case "video_author":
                return video_reply()
            case "video_visual" | "video_text" | "video_ground":
                return {"overall": 8, "issues": []}
            case "pronounce":
                words = re.findall(r"^- (.+)$", text, re.MULTILINE)
                return {"words": [{"word": w, "ipa": "tɛst"} for w in words]}
        raise AssertionError(stage)

    def solve(self, view: dict[str, Any]) -> dict[str, Any]:
        """Answer the shuffled view from the remembered draft."""
        key = view.get("prompt") or view.get("text")
        d = next(x for x in reversed(self.drafts) if (x.get("prompt") or x.get("text")) == key)
        ans: Any
        if "answer" in d:
            right = next(o["text"] for o in d["options"] if o["id"] == d["answer"])
            ans = next(o["id"] for o in view["options"] if o["text"] == right)
        elif "answers" in d:
            rights = {o["text"] for o in d["options"] if o["id"] in d["answers"]}
            ans = sorted(o["id"] for o in view["options"] if o["text"] in rights)
        elif "blanks" in d:
            ans = [b["answers"][0] for b in d["blanks"]]
        elif "steps" in d:
            ans = [s["id"] for s in d["steps"]]
        else:
            ans = d["pairs"]
        if self.wrong_blind:
            ans = "z" if isinstance(ans, str) else []
        return blind(ans)

    def generate(self, request: Request) -> Completion:
        stage = stage_of(request)
        self.calls.append((stage, request))
        queue = self.script.get(stage)
        reply = queue.pop(0) if queue else self.default(stage, request)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(request)
        if stage == "item" and isinstance(reply, dict):
            self.drafts.append(reply)
        if stage == "review_bank" and isinstance(reply, dict):
            self.drafts.extend(reply.get("questions", []))
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return Completion(
            text=text,
            raw={"fake": True, "stage": stage},
            usage=Usage(1200, 800, 100, self.cost_micros, notional=self.notional),
            model_resolved=request.model,
            provider="fake-provider",
            finish="stop",
        )

    def stream(self, request: Request, on_text: Any) -> Completion:
        """Like generate, delivered in chunks of a few characters (a streaming adapter)."""
        comp = self.generate(request)
        for i in range(0, len(comp.text), 7):
            on_text(comp.text[i : i + 7])
        return comp

    def stages(self) -> list[str]:
        return [s for s, _ in self.calls]


def answer_for(view_item: dict[str, Any], llm: FakeLLM) -> Any:
    """The right answer for an item as the learner sees it (used to simulate a good learner)."""
    t = view_item["type"]
    if t == "flashcard":
        return 3
    if t == "short_answer":
        return "All rows of the left table are kept."
    return llm.solve(view_item["view"])["answer"]


def studies_arrange(text: str) -> dict[str, Any]:
    """Files whose names start with "Physics" make one course, the others another; "one course" in the learner's
    feedback merges them."""
    files = [(int(n), name) for n, name in re.findall(r"^(\d+)\. (.+?) \(", text, re.M)]
    physics = [n for n, name in files if name.lower().startswith("physics")]
    rest = [n for n, _ in files if n not in physics]
    feedback = text.split("asked for changes", 1)[1] if "asked for changes" in text else ""
    if "one course" in feedback:
        courses = [{"title": "Engineering basics", "files": [n for n, _ in files]}]
        message = "All your files are now one course."
    else:
        courses = [
            c
            for c in (
                {"title": "Analysis 1", "term": "Year 1", "files": rest},
                {"title": "Physics 1", "files": physics},
            )
            if c["files"]
        ]
        message = "Your physics files are one course and the analysis files another."
    return {
        "title": "Mechanical Engineering",
        "goal": "Pass the first-year exams.",
        "courses": courses,
        "message": message,
    }
