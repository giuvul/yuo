// Small formatting helpers shared across screens.

/** Seconds as m:ss (a video moment): 75.4 -> "1:15". */
export const mmss = (s: number): string => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
