// The Yuo logo (Yuo Brand Identity, section 3): the wordmark "yuo" whose Y is a sprouting seedling, and the Y on
// its own as the symbol. The geometry comes from the approved master files (logoPaths.ts, generated). Colours
// follow the theme: Forest with a Moss right leaf on light, one-colour Mist on dark; `tone="inverse"` is the
// app-icon treatment (Mist with a Moss leaf) for Forest surfaces.
import { LOGO, SYMBOL } from "./logoPaths";
import styles from "./Logo.module.css";

type Tone = "theme" | "inverse";

function Art({ art, height, tone, className }: { art: typeof LOGO; height: number; tone: Tone; className?: string }) {
  return (
    <svg
      className={`${styles.art} ${className ?? ""}`}
      data-tone={tone}
      width={(height * art.width) / art.height}
      height={height}
      viewBox={art.viewBox}
      aria-hidden="true"
      focusable="false"
    >
      {art.body.map((d) => (
        <path key={d.slice(0, 24)} fillRule="evenodd" d={d} />
      ))}
      <path className={styles.leaf} d={art.leaf} />
    </svg>
  );
}

/** The sprouting Y alone: compact navigation, cards, empty states. `size` is its height in px. */
export function LogoMark({ size = 28, tone = "theme" }: { size?: number; tone?: Tone }) {
  return <Art art={SYMBOL} height={size} tone={tone} />;
}

/**
 * The wordmark; `label` is the accessible name (the product name, translated by the caller). With `compact` it
 * becomes the symbol alone on a phone.
 */
export function Logo({ label, height = 34, compact }: { label: string; height?: number; compact?: boolean }) {
  return (
    <span className={styles.logo} data-compact={compact || undefined}>
      <span className="visually-hidden">{label}</span>
      <Art art={LOGO} height={height} tone="theme" className={styles.full} />
      {compact ? <Art art={SYMBOL} height={height} tone="theme" className={styles.symbol} /> : null}
    </span>
  );
}
