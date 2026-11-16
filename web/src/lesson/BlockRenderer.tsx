// Renders a stored lesson body with React elements only: text is always a text node, never
// markup. The only exception is math, rendered by KaTeX's own renderer (MathBlock).
import { useLingui } from "@lingui/react/macro";
import { useState, type ReactNode } from "react";
import { parseBody, type Block, type CalloutVariant, type Inline } from "./blocks";
import { MathBlock } from "./MathBlock";
import styles from "./blocks.module.css";

function Inlines({ runs }: { runs: Inline[] }) {
  return (
    <>
      {runs.map((run, i) => {
        let node: ReactNode = run.text;
        if (run.marks.includes("code")) node = <code className={styles.inlineCode}>{node}</code>;
        if (run.marks.includes("italic")) node = <em>{node}</em>;
        if (run.marks.includes("bold")) node = <strong>{node}</strong>;
        return <span key={i}>{node}</span>;
      })}
    </>
  );
}

function CalloutLabel({ variant }: { variant: CalloutVariant }) {
  const { t } = useLingui();
  switch (variant) {
    case "tip":
      return <>{t({ id: "lesson.callout.tip", message: "Tip" })}</>;
    case "warning":
      return <>{t({ id: "lesson.callout.warning", message: "Watch out" })}</>;
    case "example":
      return <>{t({ id: "lesson.callout.example", message: "Example" })}</>;
    case "definition":
      return <>{t({ id: "lesson.callout.definition", message: "Definition" })}</>;
  }
}

function WorkedExampleLabel() {
  const { t } = useLingui();
  return <>{t({ id: "lesson.worked-example.label", message: "Worked example" })}</>;
}

const CALLOUT_CLASS: Record<CalloutVariant, string | undefined> = {
  tip: undefined,
  warning: styles.calloutWarning,
  example: styles.calloutExample,
  definition: styles.calloutDefinition,
};

const HEADINGS = ["h2", "h3", "h4", "h5", "h6"] as const;

function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "heading": {
      // the page title is the h1; body headings start one level below it
      const Tag = HEADINGS[Math.min(Math.max(Math.round(block.level), 1), HEADINGS.length) - 1] ?? "h2";
      return <Tag className={styles.heading}>{block.text}</Tag>;
    }
    case "paragraph":
      return (
        <p className={styles.paragraph}>
          <Inlines runs={block.inlines} />
        </p>
      );
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag className={styles.list}>
          {block.items.map((item, i) => (
            <li key={i}>
              <Inlines runs={item} />
            </li>
          ))}
        </Tag>
      );
    }
    case "code":
      return (
        <figure className={styles.codeFigure}>
          <pre className={styles.code} data-language={block.language || undefined}>
            <code>{block.text}</code>
          </pre>
          {block.caption ? <figcaption className={styles.caption}>{block.caption}</figcaption> : null}
        </figure>
      );
    case "math":
      return <MathBlock latex={block.latex} display={block.display} />;
    case "callout":
      return (
        <aside className={`${styles.callout} ${CALLOUT_CLASS[block.variant] ?? ""}`} data-variant={block.variant}>
          <p className={styles.calloutLabel}>
            <CalloutLabel variant={block.variant} />
          </p>
          <BlockList blocks={block.blocks} />
        </aside>
      );
    case "worked_example":
      return (
        <section className={styles.workedExample}>
          <p className={styles.calloutLabel}>
            <WorkedExampleLabel />
          </p>
          {block.title ? <p className={styles.workedTitle}>{block.title}</p> : null}
          <ol className={styles.steps}>
            {block.steps.map((step, i) => (
              <li key={i}>
                <Inlines runs={step} />
              </li>
            ))}
          </ol>
        </section>
      );
    case "glossary_term":
      return (
        <dl className={styles.glossary}>
          <dt>
            <dfn>{block.term}</dfn>
          </dt>
          <dd>{block.definition}</dd>
        </dl>
      );
  }
}

function BlockList({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => (
        <BlockView key={`${b.bid}-${i}`} block={b} />
      ))}
    </>
  );
}

/**
 * Renders a lesson body as stored; blocks of unknown types are skipped. `after` adds content
 * after each top-level block (used for notes anchored to a block id).
 */
export function LessonBody({ body, after }: { body: unknown; after?: (bid: string) => ReactNode }) {
  const blocks = parseBody(body);
  // the block last tapped: on touch screens its "Add a note here" shows, the others' wait (as hover does with a
  // mouse)
  const [touched, setTouched] = useState<string | null>(null);
  return (
    <div className={styles.body}>
      {after ? (
        blocks.map((b, i) => (
          <div
            key={`${b.bid}-${i}`}
            className={styles.anchored}
            data-bid={b.bid}
            data-touched={touched === b.bid || undefined}
            onClick={() => setTouched(b.bid)}
          >
            <BlockView block={b} />
            {after(b.bid)}
          </div>
        ))
      ) : (
        <BlockList blocks={blocks} />
      )}
    </div>
  );
}
