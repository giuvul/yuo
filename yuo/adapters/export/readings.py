"""Lessons as readings: one Markdown and one self-contained HTML file per lesson, plus an index of both in
path order. Readers open them anywhere, offline: the HTML has an inline stylesheet, a CSP that forbids
scripts and remote loads, and all text escaped; math stays LaTeX source in `<code>`. Markdown escapes the
punctuation that would turn text into markup or links, and writes `<`, `>`, `&` as entities.
"""

import html
import re
from typing import Any

from yuo.adapters.export._common import (
    AssetFile,
    Files,
    Records,
    clean,
    ordered_lessons,
    path_record,
    represents,
    safe_name,
    skill_order,
)

CALLOUTS = {"tip": "Tip", "warning": "Warning", "example": "Example", "definition": "Definition"}
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|~$])")
_MD_LINE_START = re.compile(r"^(\s*)(\d+)([.)])", re.MULTILINE)
_LANG = re.compile(r"[^A-Za-z0-9_+-]")
STYLE = """
body { font: 17px/1.6 system-ui, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #1d1d1f; }
code, pre { font-family: ui-monospace, monospace; font-size: 0.92em; background: #f3f3f5; border-radius: 4px; }
code { padding: 0.1em 0.3em; } pre { padding: 0.8rem; overflow-x: auto; } pre code { padding: 0; }
.callout { border-left: 4px solid #6b7cff; background: #f5f6ff; padding: 0.5rem 1rem; margin: 1rem 0; }
.callout.warning { border-color: #d9822b; background: #fff6ec; } .label { font-weight: 600; margin: 0; }
.math.display { display: block; text-align: center; margin: 1rem 0; } dt { font-weight: 600; }
.example { border: 1px solid #ddd; border-radius: 6px; padding: 0.5rem 1rem; } .muted { color: #666; }
"""
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'"


def _level(b: dict[str, Any]) -> int:
    """Block headings sit under the lesson title, the one h1."""
    level = b.get("level")
    return (level if level in (1, 2, 3) else 1) + 1


# --- Markdown ----------------------------------------------------------------------------------------


def md(text: Any) -> str:
    """Plain text -> inert Markdown text."""
    out = html.escape(clean(text), quote=False)  # entities: inert in every Markdown flavour
    out = _MD_SPECIAL.sub(r"\\\1", out)
    out = _MD_LINE_START.sub(r"\1\2\\\3", out)
    return re.sub(r"(?m)^(\s*)([-=])", r"\1\\\2", out).replace("\n", " ")


def _md_code_span(text: str) -> str:
    text = clean(text).replace("\n", " ")
    ticks = "`" * (max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") or not text.strip() else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"


def _md_runs(runs: Any) -> str:
    out = []
    for run in runs if isinstance(runs, list) else []:
        text, marks = run.get("text", ""), set(run.get("marks") or [])
        if not str(text).strip():
            out.append(md(text))
            continue
        if "code" in marks:
            s = _md_code_span(text)
        else:
            s = md(text)
            if "italic" in marks:
                s = f"*{s}*"
            if "bold" in marks:
                s = f"**{s}**"
        out.append(s)
    return "".join(out)


def _md_fence(text: str, lang: str = "") -> str:
    text = clean(text)
    fence = "`" * max(3, max((len(r) for r in re.findall(r"`+", text)), default=0) + 1)
    return f"{fence}{_LANG.sub('', lang)}\n{text}\n{fence}"


def _md_blocks(blocks: Any) -> list[str]:
    out: list[str] = []
    for b in blocks if isinstance(blocks, list) else []:
        kind = b.get("type")
        if kind == "heading":
            level = _level(b)
            out.append("#" * level + " " + md(b.get("text")))
        elif kind == "paragraph":
            out.append(_md_runs(b.get("inlines")))
        elif kind == "list":
            ordered = bool(b.get("ordered"))
            out.append(
                "\n".join(
                    (f"{n}. " if ordered else "- ") + _md_runs(item)
                    for n, item in enumerate(b.get("items") or [], start=1)
                )
            )
        elif kind == "code":
            fence = _md_fence(b.get("text", ""), b.get("language") or "")
            out.append(fence + (f"\n\n*{md(b['caption'])}*" if b.get("caption") else ""))
        elif kind == "math":
            out.append(
                _md_fence(b.get("latex", ""), "latex")
                if b.get("display")
                else _md_code_span(b.get("latex", ""))
            )
        elif kind == "callout":
            label = CALLOUTS.get(b.get("variant", ""), "Note")
            inner = "\n\n".join(_md_blocks(b.get("blocks")))
            out.append(
                "\n".join("> " + line if line else ">" for line in f"**{label}:** {inner}".split("\n"))
            )
        elif kind == "worked_example":
            steps = "\n".join(f"{n}. {_md_runs(s)}" for n, s in enumerate(b.get("steps") or [], start=1))
            out.append(f"**Worked example: {md(b.get('title'))}**\n\n{steps}")
        elif kind == "glossary_term":
            out.append(f"**{md(b.get('term'))}**: {md(b.get('definition'))}")
    return out


def _sources(records: Records, version: dict[str, Any]) -> list[dict[str, Any]]:
    by_key = {s.get("key"): s for s in records.get("source", [])}
    keys = sorted({u.get("key") for u in version.get("sources") or [] if u.get("key") in by_key}, key=str)
    return [by_key[k] for k in keys]


def _safe_url(url: Any) -> str | None:
    return url if isinstance(url, str) and re.match(r"^https?://[^\s<>\"']+$", url) else None


def lesson_md(records: Records, version: dict[str, Any]) -> str:
    parts = ["# " + md(version.get("title")), *_md_blocks(version.get("body"))]
    sources = _sources(records, version)
    if sources:
        lines = []
        for s in sources:
            url = _safe_url(s.get("url"))
            lines.append("- " + md(s.get("title")) + (f" <{url}>" if url else ""))
        parts.append("## Sources\n\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n"


# --- HTML --------------------------------------------------------------------------------------------


def h(text: Any) -> str:
    return html.escape(clean(text), quote=True)


def _html_runs(runs: Any) -> str:
    out = []
    for run in runs if isinstance(runs, list) else []:
        s, marks = h(run.get("text", "")), set(run.get("marks") or [])
        if "code" in marks:
            s = f"<code>{s}</code>"
        if "italic" in marks:
            s = f"<em>{s}</em>"
        if "bold" in marks:
            s = f"<strong>{s}</strong>"
        out.append(s)
    return "".join(out)


def _html_blocks(blocks: Any) -> list[str]:
    out: list[str] = []
    for b in blocks if isinstance(blocks, list) else []:
        kind = b.get("type")
        if kind == "heading":
            level = _level(b)
            out.append(f"<h{level}>{h(b.get('text'))}</h{level}>")
        elif kind == "paragraph":
            out.append(f"<p>{_html_runs(b.get('inlines'))}</p>")
        elif kind == "list":
            tag = "ol" if b.get("ordered") else "ul"
            lis = "".join(f"<li>{_html_runs(item)}</li>" for item in b.get("items") or [])
            out.append(f"<{tag}>{lis}</{tag}>")
        elif kind == "code":
            lang = _LANG.sub("", b.get("language") or "")
            cls = f' class="language-{lang}"' if lang else ""
            code = f"<pre><code{cls}>{h(b.get('text'))}</code></pre>"
            if b.get("caption"):
                code = f'<figure>{code}<figcaption class="muted">{h(b["caption"])}</figcaption></figure>'
            out.append(code)
        elif kind == "math":
            if b.get("display"):
                out.append(f'<p><code class="math display">{h(b.get("latex"))}</code></p>')
            else:
                out.append(f'<p><code class="math">{h(b.get("latex"))}</code></p>')
        elif kind == "callout":
            variant = b.get("variant") if b.get("variant") in CALLOUTS else "tip"
            inner = "".join(_html_blocks(b.get("blocks")))
            out.append(
                f'<aside class="callout {variant}"><p class="label">{CALLOUTS[variant]}</p>{inner}</aside>'
            )
        elif kind == "worked_example":
            steps = "".join(f"<li>{_html_runs(s)}</li>" for s in b.get("steps") or [])
            out.append(
                f'<section class="example"><p class="label">Worked example: {h(b.get("title"))}</p>'
                f"<ol>{steps}</ol></section>"
            )
        elif kind == "glossary_term":
            out.append(f"<dl><dt>{h(b.get('term'))}</dt><dd>{h(b.get('definition'))}</dd></dl>")
    return out


def page(title: str, lang: str, body: list[str]) -> str:
    lang = re.sub(r"[^A-Za-z0-9-]", "", lang) or "en"
    head = (
        f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{h(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
    )
    return head + "\n".join(body) + "\n</body>\n</html>\n"


def lesson_html(records: Records, version: dict[str, Any]) -> str:
    body = [f"<h1>{h(version.get('title'))}</h1>", *_html_blocks(version.get("body"))]
    sources = _sources(records, version)
    if sources:
        lis = []
        for s in sources:
            url = _safe_url(s.get("url"))
            link = f' <a href="{h(url)}" rel="noopener noreferrer">{h(url)}</a>' if url else ""
            lis.append(f"<li>{h(s.get('title'))}{link}</li>")
        body.append("<h2>Sources</h2>\n<ul>" + "".join(lis) + "</ul>")
    body.append('<p class="muted"><a href="index.html">All readings</a></p>')
    return page(str(version.get("title", "")), str(version.get("lang", "en")), body)


# --- index -------------------------------------------------------------------------------------------


def _tree(records: Records) -> list[tuple[str, list[tuple[str, list[tuple[str, str]]]]]]:
    """[(branch title, [(skill title, [(lesson code, lesson title)])])] in path order."""
    lessons = ordered_lessons(records)
    rank = skill_order(records)
    skills = sorted(records.get("skill", []), key=lambda s: rank[s["code"]])
    branches = {b["code"]: clean(b.get("title")) for b in records.get("branch", [])}
    out: list[tuple[str, list[tuple[str, list[tuple[str, str]]]]]] = []
    for s in skills:
        mine = [(x["code"], clean(v.get("title"))) for x, v in lessons if x.get("skill") == s["code"]]
        if not mine:
            continue
        branch = branches.get(s.get("branch", ""), "")
        if not out or out[-1][0] != branch:
            out.append((branch, []))
        out[-1][1].append((clean(s.get("title")), mine))
    return out


def export_readings(records: Records, asset: AssetFile) -> Files:
    path = path_record(records)
    title = clean(path.get("title") or path.get("code") or "Readings")
    files: Files = {}
    for lesson, version in ordered_lessons(records):
        code = lesson["code"]
        files[safe_name(f"readings/{code}.md")] = lesson_md(records, version).encode("utf-8")
        files[safe_name(f"readings/{code}.html")] = lesson_html(records, version).encode("utf-8")
    tree = _tree(records)
    md_lines = [f"# {md(title)}"]
    if path.get("goal"):
        md_lines.append(md(path["goal"]))
    html_body = [f"<h1>{h(title)}</h1>"] + ([f"<p>{h(path['goal'])}</p>"] if path.get("goal") else [])
    for branch, skills in tree:
        md_lines.append(f"## {md(branch)}")
        html_body.append(f"<h2>{h(branch)}</h2>")
        for skill, lessons in skills:
            links = "\n".join(f"- [{md(t)}]({safe_name(c)}.md)" for c, t in lessons)
            md_lines.append(f"### {md(skill)}\n\n{links}")
            lis = "".join(f'<li><a href="{safe_name(c)}.html">{h(t)}</a></li>' for c, t in lessons)
            html_body.append(f"<h3>{h(skill)}</h3>\n<ul>{lis}</ul>")
    files["readings/index.md"] = ("\n\n".join(md_lines) + "\n").encode("utf-8")
    files["readings/index.html"] = page(title, str(path.get("content_lang", "en")), html_body).encode("utf-8")
    return files


def represents_readings(records: Records) -> dict[str, Any]:
    return represents("lesson", [x["code"] for x, _ in ordered_lessons(records)])
