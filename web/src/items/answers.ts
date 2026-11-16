// Answer shapes per item type (assessment.response_given `answer`, yuo/assessment/types.py) and
// how to read the `correct` value of a grade back into something to show. The item views never
// contain the key; `correct` only arrives with a grade.
import type { Item } from "../api/client";
import type { Answer } from "../outbox/events";

type Pair = { left: string; right: string };

/** What the learner has entered so far, per type. */
export type Draft =
  | { type: "mcq"; choice: string | null }
  | { type: "multi"; choices: string[] }
  | { type: "cloze"; gaps: string[] }
  | { type: "ordering"; order: string[] }
  | { type: "matching"; pairs: Record<string, string> }
  | { type: "flashcard"; back: string | null; rating: number | null }
  | { type: "short_answer"; text: string };

export function emptyDraft(item: Item): Draft {
  switch (item.type) {
    case "mcq":
      return { type: "mcq", choice: null };
    case "multi":
      return { type: "multi", choices: [] };
    case "cloze":
      return { type: "cloze", gaps: Array.from({ length: Math.max(0, item.view.gaps) }, () => "") };
    case "ordering":
      return { type: "ordering", order: item.view.steps.map((s) => s.id) };
    case "matching":
      return { type: "matching", pairs: {} };
    case "flashcard":
      return { type: "flashcard", back: null, rating: null };
    case "short_answer":
      return { type: "short_answer", text: "" };
  }
}

/** The answer to send, or null while the draft is incomplete. */
export function toAnswer(item: Item, draft: Draft): Answer | null {
  switch (draft.type) {
    case "mcq":
      return draft.choice;
    case "multi": {
      if (item.type !== "multi" || draft.choices.length === 0) return null;
      const order = item.view.options.map((o) => o.id);
      return [...draft.choices].sort((a, b) => order.indexOf(a) - order.indexOf(b));
    }
    case "cloze":
      return draft.gaps.every((g) => g.trim() !== "") ? draft.gaps.map((g) => g.trim()) : null;
    case "ordering":
      return [...draft.order];
    case "matching": {
      if (item.type !== "matching") return null;
      const pairs = item.view.left.map((left) => ({ left, right: draft.pairs[left] ?? "" }));
      return pairs.every((p) => p.right !== "") ? pairs : null;
    }
    case "flashcard":
      return draft.back === null ? null : draft.rating; // rate only after seeing the back
    case "short_answer":
      return draft.text.trim() === "" ? null : draft.text.trim();
  }
}

/** Splits cloze text at {{n}} markers: strings and gap numbers (1-based). */
export function clozeParts(text: string): (string | number)[] {
  const out: (string | number)[] = [];
  const re = /\{\{(\d+)\}\}/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(Number(m[1]));
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length || from === to) return list;
  const next = [...list];
  const [x] = next.splice(from, 1);
  next.splice(to, 0, x as T);
  return next;
}

const asStrings = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : typeof v === "string" ? [v] : [];

/** The right answer as lines of text to show after grading. */
export function correctLines(item: Item, correct: unknown): string[] {
  switch (item.type) {
    case "mcq":
    case "multi": {
      const text = new Map(item.view.options.map((o) => [o.id, o.text]));
      return asStrings(correct).map((id) => `${id}. ${text.get(id) ?? ""}`.trim());
    }
    case "ordering": {
      const text = new Map(item.view.steps.map((s) => [s.id, s.text]));
      return asStrings(correct).map((id) => text.get(id) ?? id);
    }
    case "matching":
      return Array.isArray(correct)
        ? correct
            .filter((p): p is Pair => !!p && typeof p === "object" && "left" in p && "right" in p)
            .map((p) => `${p.left} → ${p.right}`)
        : [];
    case "cloze":
    case "flashcard":
    case "short_answer":
      return asStrings(correct);
  }
}

export const RATINGS = [1, 2, 3, 4] as const;
