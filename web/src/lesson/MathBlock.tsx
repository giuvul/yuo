import { useEffect, useRef, useState } from "react";
import styles from "./blocks.module.css";

type Katex = typeof import("katex").default;

let katexPromise: Promise<Katex> | null = null;

/** KaTeX is loaded only when a lesson has math (its own chunk, with its stylesheet). */
function loadKatex(): Promise<Katex> {
  katexPromise ??= Promise.all([import("katex"), import("katex/dist/katex.min.css")]).then(
    ([mod]) => mod.default,
  );
  return katexPromise;
}

/**
 * Renders LaTeX with KaTeX's own DOM renderer into a node React does not manage. This is the one
 * place lesson content becomes markup other than React elements: `trust: false` keeps
 * \href, \includegraphics and HTML extensions off. Until KaTeX loads, or if it fails, the LaTeX
 * source is shown as code.
 */
export function MathBlock({ latex, display }: { latex: string; display: boolean }) {
  const target = useRef<HTMLSpanElement>(null);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setRendered(false);
    loadKatex()
      .then((katex) => {
        if (cancelled || !target.current) return;
        katex.render(latex, target.current, {
          displayMode: display,
          throwOnError: false,
          trust: false,
          strict: "ignore",
          maxSize: 50,
          maxExpand: 500,
          output: "htmlAndMathml",
        });
        setRendered(true);
      })
      .catch(() => {
        /* keep the source fallback */
      });
    return () => {
      cancelled = true;
    };
  }, [latex, display]);

  const Tag = display ? "div" : "span";
  return (
    <Tag className={display ? styles.mathDisplay : styles.mathInline} data-math="">
      <span ref={target} hidden={!rendered} />
      {rendered ? null : <code className={styles.mathSource}>{latex}</code>}
    </Tag>
  );
}
