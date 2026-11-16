// A section that opens and closes (native <details>): long pages such as Settings start with every section
// closed, so the page reads as a table of contents. A link to an id inside one opens it (openTarget).
import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronDownIcon } from "./icons";
import styles from "./Collapsible.module.css";

export function Collapsible({
  id,
  title,
  description,
  children,
  forceOpen = false,
  defaultOpen = false,
  nested = false,
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  /** kept open while true (a search shows its matches) */
  forceOpen?: boolean;
  defaultOpen?: boolean;
  /** inside another section: a level-3 heading and a flatter box */
  nested?: boolean;
}) {
  const headingId = useId();
  const [open, setOpen] = useState(defaultOpen);
  const Heading = nested ? "h3" : "h2";
  return (
    <details
      className={styles.box}
      data-nested={nested || undefined}
      id={id}
      open={open || forceOpen}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary className={styles.summary}>
        <span className={styles.text}>
          <Heading id={headingId} className={styles.title}>
            {title}
          </Heading>
          {description ? <span className={styles.description}>{description}</span> : null}
        </span>
        <ChevronDownIcon className={styles.chevron} aria-hidden="true" />
      </summary>
      <section className={styles.body} aria-labelledby={headingId}>
        {children}
      </section>
    </details>
  );
}

/** Opens every closed section around the element with this id and scrolls to it. */
export function openTarget(id: string): boolean {
  const el = id ? document.getElementById(id) : null;
  if (!el) return false;
  for (let d = el.closest("details"); d; d = d.parentElement?.closest("details") ?? null) d.open = true;
  el.scrollIntoView({ block: "start" });
  // the target may hold the next step (a sign-in button): keyboard users land there too
  if (el.tabIndex < 0 && !el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: true });
  return true;
}

/** Opens the section the URL's #hash points into, once `ready` (its content loaded). */
export function useOpenHashTarget(hash: string, ready: boolean) {
  useEffect(() => {
    if (ready && hash) openTarget(hash.replace(/^#/, ""));
  }, [hash, ready]);
}
