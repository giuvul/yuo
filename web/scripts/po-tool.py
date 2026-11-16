"""Helper for translating the UI catalogs (src/locales/README.md) a chunk at a time.

    python3 scripts/po-tool.py todo <lang> [limit]       JSON list of untranslated ids with the English text
    python3 scripts/po-tool.py fill <lang> <file.json>   merge {"id": "translation"} into <lang>/messages.po
    python3 scripts/po-tool.py check <lang>              missing translations and placeholder mismatches

The check compares the placeholders ({name}, ICU argument names, #, <0>...</0>) of each translation with the
English text; `npm run i18n:check` then compiles every catalog strictly.
"""

import json
import re
import sys
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "src" / "locales"
TOKEN = re.compile(r"\{\s*([A-Za-z0-9_]+)\s*[,}]|</?\d+>|<\d+/>")


def _unquote(s: str) -> str:
    s = s.strip()[1:-1]
    return re.sub(r'\\(.)', lambda m: {"n": "\n", "t": "\t"}.get(m[1], m[1]), s)


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def parse(path: Path) -> tuple[str, list[dict[str, object]]]:
    """The header block and the entries in file order: comments, id, translation."""
    blocks = path.read_text(encoding="utf-8").split("\n\n")
    header, entries = blocks[0], []
    for block in blocks[1:]:
        lines = [x for x in block.split("\n") if x]
        if not lines:
            continue
        comments = [x for x in lines if x.startswith("#")]
        body = [x for x in lines if not x.startswith("#")]
        i = next(n for n, x in enumerate(body) if x.startswith("msgstr"))
        msgid = "".join(_unquote(x.removeprefix("msgid ")) for x in body[:i])
        msgstr = "".join(_unquote(x.removeprefix("msgstr ")) for x in body[i:])
        entries.append({"comments": comments, "id": msgid, "str": msgstr})
    return header, entries


def write(path: Path, header: str, entries: list[dict[str, object]]) -> None:
    out = [header]
    for e in entries:
        out.append("\n".join([*e["comments"], f"msgid {_quote(str(e['id']))}", f"msgstr {_quote(str(e['str']))}"]))  # type: ignore[misc]
    path.write_text("\n\n".join(out) + "\n", encoding="utf-8")


def tokens(s: str) -> list[str]:
    found = [m[1] or m[0] for m in TOKEN.finditer(s)]
    if "plural," in s or "select," in s:
        found += ["#"] * s.count("#")
    return sorted(found)


def english() -> dict[str, str]:
    return {str(e["id"]): str(e["str"]) for e in parse(LOCALES / "en" / "messages.po")[1]}


def main() -> int:
    cmd, lang = sys.argv[1], sys.argv[2]
    path = LOCALES / lang / "messages.po"
    header, entries = parse(path)
    en = english()
    if cmd == "todo":
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 120
        todo = [
            {"id": e["id"], "en": en[str(e["id"])], "notes": [c[3:] for c in e["comments"] if c.startswith("#. ")]}  # type: ignore[attr-defined]
            for e in entries
            if not e["str"] and str(e["id"]) in en
        ]
        print(json.dumps({"left": len(todo), "items": todo[:limit]}, ensure_ascii=False, indent=0))
    elif cmd == "fill":
        new = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        n = 0
        for e in entries:
            if e["id"] in new and isinstance(new[e["id"]], str) and new[e["id"]].strip():
                e["str"] = new[e["id"]]
                n += 1
        write(path, header, entries)
        print(f"filled {n}; unknown ids: {sorted(set(new) - {e['id'] for e in entries})}")
    elif cmd == "check":
        missing = [e["id"] for e in entries if not e["str"]]
        bad = [
            {"id": e["id"], "en": en[str(e["id"])], "tr": e["str"]}
            for e in entries
            if e["str"] and str(e["id"]) in en and tokens(str(e["str"])) != tokens(en[str(e["id"])])
        ]
        print(json.dumps({"missing": len(missing), "placeholder_mismatch": bad}, ensure_ascii=False, indent=1))
        return 1 if missing or bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
