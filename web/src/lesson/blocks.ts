// The stored lesson body (yuo/content/lesson_body.py `to_body`). The API types it as
// a list of free-form objects, so the reader narrows each block here (a trust boundary: bodies
// can come from imported packages). Anything that does not match renders nothing.

type Mark = "bold" | "italic" | "code";
export type Inline = { text: string; marks: Mark[] };

export type Block =
  | { type: "heading"; bid: string; level: number; text: string }
  | { type: "paragraph"; bid: string; inlines: Inline[] }
  | { type: "list"; bid: string; ordered: boolean; items: Inline[][] }
  | { type: "code"; bid: string; language: string; text: string; caption: string | null }
  | { type: "math"; bid: string; latex: string; display: boolean }
  | { type: "callout"; bid: string; variant: CalloutVariant; blocks: Block[] }
  | { type: "worked_example"; bid: string; title: string; steps: Inline[][] }
  | { type: "glossary_term"; bid: string; term: string; definition: string };

export type CalloutVariant = "tip" | "warning" | "example" | "definition";

const MARKS = new Set<string>(["bold", "italic", "code"]);
const VARIANTS = new Set<string>(["tip", "warning", "example", "definition"]);

type Raw = Record<string, unknown>;

const isObj = (v: unknown): v is Raw => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);

function inline(v: unknown): Inline | null {
  if (!isObj(v)) return null;
  const text = str(v["text"]);
  if (text === null) return null;
  const marks = Array.isArray(v["marks"])
    ? (v["marks"].filter((m) => typeof m === "string" && MARKS.has(m)) as Mark[])
    : [];
  return { text, marks };
}

function inlines(v: unknown): Inline[] | null {
  if (!Array.isArray(v)) return null;
  return v.map(inline).filter((x): x is Inline => x !== null);
}

/** Paragraph-like content: inline runs, or a plain string (the draft form). */
function runs(v: unknown): Inline[] | null {
  const s = str(v);
  return s !== null ? [{ text: s, marks: [] }] : inlines(v);
}

function runLists(v: unknown): Inline[][] | null {
  if (!Array.isArray(v)) return null;
  return v.map(runs).filter((x): x is Inline[] => x !== null);
}

function parseBlock(v: unknown, index = 0, depth = 0): Block | null {
  if (!isObj(v)) return null;
  const bid = str(v["bid"]) ?? `i${index}`;
  switch (v["type"]) {
    case "heading": {
      const text = str(v["text"]);
      const level = typeof v["level"] === "number" ? v["level"] : 2;
      return text === null ? null : { type: "heading", bid, level, text };
    }
    case "paragraph": {
      const content = runs(v["inlines"] ?? v["text"]);
      return content ? { type: "paragraph", bid, inlines: content } : null;
    }
    case "list": {
      const items = runLists(v["items"]);
      return items ? { type: "list", bid, ordered: v["ordered"] === true, items } : null;
    }
    case "code": {
      const text = str(v["text"]);
      return text === null
        ? null
        : { type: "code", bid, text, language: str(v["language"]) ?? "", caption: str(v["caption"]) };
    }
    case "math": {
      const latex = str(v["latex"]);
      return latex === null ? null : { type: "math", bid, latex, display: v["display"] !== false };
    }
    case "callout": {
      if (depth > 4) return null; // nested callouts are allowed, unbounded nesting is not
      const variant = str(v["variant"]);
      const nested = Array.isArray(v["blocks"])
        ? parseBody(v["blocks"], depth + 1)
        : runs(v["text"])
          ? [{ type: "paragraph" as const, bid: `${bid}.1`, inlines: runs(v["text"]) ?? [] }]
          : [];
      return {
        type: "callout",
        bid,
        variant: variant && VARIANTS.has(variant) ? (variant as CalloutVariant) : "tip",
        blocks: nested,
      };
    }
    case "worked_example": {
      const steps = runLists(v["steps"]);
      return steps ? { type: "worked_example", bid, title: str(v["title"]) ?? "", steps } : null;
    }
    case "glossary_term": {
      const term = str(v["term"]);
      const definition = str(v["definition"]);
      return term === null || definition === null ? null : { type: "glossary_term", bid, term, definition };
    }
    default:
      return null; // unknown or not yet supported (diagram, image, exercise_ref, ext)
  }
}

export function parseBody(body: unknown, depth = 0): Block[] {
  if (!Array.isArray(body)) return [];
  return body.map((b, i) => parseBlock(b, i, depth)).filter((b): b is Block => b !== null);
}
