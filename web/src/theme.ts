// The colour theme: "system" follows the operating system (prefers-color-scheme), "light" and
// "dark" win over it both ways through `html[data-theme]` (tokens.css). The learner's choice lives in
// GET /api/me; a copy in localStorage only lets index.html set it before the first paint.
import type { Theme } from "./api/client";
import { forget, readText, writeText } from "./storage";

export const THEME_KEY = "yuo.theme";

export function isTheme(v: unknown): v is Theme {
  return v === "system" || v === "light" || v === "dark";
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset["theme"];
  else root.dataset["theme"] = theme;
  // storage closed (private mode): the API copy still applies on every load
  if (theme === "system") forget(THEME_KEY);
  else writeText(THEME_KEY, theme);
}

// While the theme follows the device, the server learns which look the device shows, so a video set to
// match the app is made light or dark like the app. Sent only when it changes.
export const DARK_QUERY = "(prefers-color-scheme: dark)";
const SCHEME_KEY = "yuo.device-scheme";

type Scheme = "light" | "dark";

export function lastSentScheme(): Scheme | null {
  const v = readText(SCHEME_KEY);
  return v === "light" || v === "dark" ? v : null;
}

export function markSchemeSent(scheme: Scheme): void {
  writeText(SCHEME_KEY, scheme); // storage closed: it is sent again on the next visit, which is harmless
}
