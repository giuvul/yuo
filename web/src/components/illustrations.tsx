// The illustration set (Yuo Brand Identity, section 10): flat vector drawings in the Grove colours. Decorative
// (aria-hidden); the text beside them carries the meaning. Colours come from the illustration tokens, so both
// themes work. No mascots, no confetti, no gradients.
import type { ReactNode } from "react";
import s from "./illustrations.module.css";

type Props = { width?: number | string; className?: string };

function Frame({ viewBox, width, className, children }: Props & { viewBox: string; children: ReactNode }) {
  return (
    <svg className={`${s.illus} ${className ?? ""}`} viewBox={viewBox} width={width} aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

/** A two-leaf sprout on a small mound: empty states, a path that has just been planted. */
export function Seedling({ width = 120, className }: Props) {
  return (
    <Frame viewBox="0 0 120 96" width={width} className={className}>
      <path className={s.ground} d="M8 88c8-16 26-25 52-25s44 9 52 25z" />
      <path className={s.mid} d="M30 88c6-11 17-17 30-17s24 6 30 17z" />
      <path className={s.deepLine} strokeWidth="5" d="M60 76V46" />
      <path className={s.deep} d="M59 50C38 51 26 40 24 20c20-1 33 9 35 30z" />
      <path className={s.mid} d="M61 44c1-19 12-30 32-31 1 19-11 31-32 31z" />
    </Frame>
  );
}

/** A mature tree with a rounded canopy: a finished path, mastery. */
export function GroveTree({ width = 140, className }: Props) {
  return (
    <Frame viewBox="0 0 140 120" width={width} className={className}>
      <path className={s.ground} d="M6 112c12-12 34-18 64-18s52 6 64 18z" />
      <path className={s.barkLine} strokeWidth="7" d="M70 106V62" />
      <path className={s.barkLine} strokeWidth="4" d="M70 80L52 62M70 72l16-14" />
      <circle className={s.mid} cx="46" cy="50" r="24" />
      <circle className={s.mid} cx="94" cy="50" r="24" />
      <circle className={s.mid} cx="70" cy="34" r="27" />
      <circle className={s.soft} cx="58" cy="30" r="13" />
      <circle className={s.soft} cx="92" cy="44" r="10" />
      <circle className={s.deep} cx="76" cy="58" r="11" />
      <circle className={s.deep} cx="38" cy="56" r="8" />
    </Frame>
  );
}

/** A small stack of books with a seedling on top: reading, a lesson being prepared. */
export function BookStack({ width = 120, className }: Props) {
  return (
    <Frame viewBox="0 0 120 100" width={width} className={className}>
      <rect className={s.clay} x="14" y="76" width="92" height="16" rx="5" />
      <rect className={s.paper} x="22" y="80" width="80" height="8" rx="2" />
      <rect className={s.deep} x="22" y="58" width="80" height="16" rx="5" />
      <rect className={s.paper} x="26" y="62" width="72" height="8" rx="2" />
      <rect className={s.mid} x="18" y="40" width="80" height="16" rx="5" />
      <rect className={s.paper} x="26" y="44" width="68" height="8" rx="2" />
      <path className={s.deepLine} strokeWidth="4" d="M60 40V24" />
      <path className={s.deep} d="M59 27C46 27 39 21 38 9c12 0 20 6 21 18z" />
      <path className={s.mid} d="M61 23c1-11 8-17 20-17 0 11-8 17-20 17z" />
    </Frame>
  );
}

/** Rolling hills, a curved path, small trees and a Pollen sun: the path ahead. */
export function Landscape({ width = 320, className }: Props) {
  return (
    <Frame viewBox="0 0 320 140" width={width} className={className}>
      <rect className={s.paper} width="320" height="140" rx="16" />
      <circle className={s.sun} cx="250" cy="34" r="16" />
      <path className={s.ground} d="M0 84c40-26 88-30 140-12 54 18 110 12 180-16v84H0z" />
      <path className={s.soft} d="M0 104c50-22 96-22 150-6 60 18 110 14 170-8v50H0z" />
      <path className={s.mid} d="M0 124c60-16 120-14 180 0 50 12 96 10 140-4v20H0z" />
      <path className={s.paper} d="M150 140c-6-16 6-24 26-30 22-7 30-16 22-30l8-2c12 16 2 30-22 38-18 6-24 12-18 24z" />
      <path className={s.barkLine} strokeWidth="4" d="M62 100V84M276 96V78" />
      <circle className={s.deep} cx="62" cy="74" r="14" />
      <circle className={s.mid} cx="276" cy="68" r="13" />
      <circle className={s.deep} cx="286" cy="76" r="8" />
    </Frame>
  );
}
