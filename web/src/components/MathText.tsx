// Text that may hold inline maths written as LaTeX between single dollar signs (the rule the models follow,
// yuo/app/stages.py MATH_RULE): the maths is rendered by KaTeX, everything else stays a text node.
import { Fragment } from "react";
import { MathBlock } from "../lesson/MathBlock";

// the same rule as the server's (yuo/content/lesson_body.py MATH): no space just inside the dollars, so an
// amount like "$5 and $10" stays text
const MATH = /(?<![\\$])\$(?=\S)([^$\n]+?)(?<=\S)\$(?!\$)/g;

export type MathPart = { math: boolean; text: string };

export function mathParts(text: string): MathPart[] {
  const out: MathPart[] = [];
  let at = 0;
  for (const m of text.matchAll(MATH)) {
    if (m.index > at) out.push({ math: false, text: text.slice(at, m.index) });
    out.push({ math: true, text: m[1] ?? "" });
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push({ math: false, text: text.slice(at) });
  return out;
}

/** The text with its $...$ parts as rendered maths. */
export function MathText({ text }: { text: string }) {
  if (!text.includes("$")) return <>{text}</>;
  return (
    <>
      {mathParts(text).map((p, i) =>
        p.math ? <MathBlock key={i} latex={p.text} display={false} /> : <Fragment key={i}>{p.text}</Fragment>,
      )}
    </>
  );
}

/** The text as a screen reader or a label should say it: the LaTeX source without its dollar signs. */
export function plainMath(text: string): string {
  return mathParts(text)
    .map((p) => p.text)
    .join("");
}
