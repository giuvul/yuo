// "Ask the tutor about this" for a text selection in the lesson: the
// selection and its block id (`bid`) become a removable chip in the dock.
import { Trans, useLingui } from "@lingui/react/macro";
import { useEffect, useState, type ReactNode, type RefObject } from "react";
import { Button } from "../components/ui";
import { useTutorActions, type Selection } from "./context";
import styles from "./tutor.module.css";

const SELECTION_MAX = 2000;

/** The selection inside `root`, with the bid of the block it starts in. */
function readSelection(root: HTMLElement | null): Selection | null {
  const sel = typeof window === "undefined" ? null : window.getSelection();
  if (!root || !sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return null;
  const text = sel.toString().replace(/\s+/g, " ").trim().slice(0, SELECTION_MAX);
  if (!text) return null;
  const start = range.startContainer;
  const el = start instanceof Element ? start : start.parentElement;
  const bid = el?.closest<HTMLElement>("[data-bid]")?.dataset["bid"] ?? null;
  return { text, bid };
}

export function SelectionAsk({ root, children }: { root: RefObject<HTMLElement | null>; children?: ReactNode }) {
  const { t } = useLingui();
  const tutor = useTutorActions();
  const [selection, setSelection] = useState<Selection | null>(null);

  useEffect(() => {
    const update = () => setSelection(readSelection(root.current));
    document.addEventListener("selectionchange", update);
    return () => document.removeEventListener("selectionchange", update);
  }, [root]);

  if (!selection) return <>{children}</>;
  const quote = selection.text.length > 80 ? `${selection.text.slice(0, 80)}…` : selection.text;
  return (
    <>
      {children}
      {/* pressing the button must not collapse the selection before it is read */}
      <div
        className={styles.selectionBar}
        onMouseDown={(e) => e.preventDefault()}
        role="group"
        aria-label={t({ id: "tutor.selection.label", message: "Selected text" })}
      >
        <span className={styles.selectionQuote}>“{quote}”</span>
        <Button
          small
          onPress={() => {
            tutor.open({ selection });
            window.getSelection()?.removeAllRanges();
            setSelection(null);
          }}
        >
          <Trans id="tutor.selection.ask">Ask the tutor about this</Trans>
        </Button>
      </div>
    </>
  );
}
