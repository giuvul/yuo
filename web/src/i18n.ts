import { i18n, type Messages } from "@lingui/core";

// The shipped UI languages. Adding one is three steps (src/locales/README.md): the catalog folder
// src/locales/<code>/messages.po, an entry here, and its name in its own language.
const LOCALES = {
  en: { name: "English", load: () => import("./locales/en/messages.po") },
  de: { name: "Deutsch", load: () => import("./locales/de/messages.po") },
  es: { name: "Español", load: () => import("./locales/es/messages.po") },
  it: { name: "Italiano", load: () => import("./locales/it/messages.po") },
  pt: { name: "Português", load: () => import("./locales/pt/messages.po") },
} satisfies Record<string, { name: string; load: () => Promise<{ messages: Messages }> }>;

type Locale = keyof typeof LOCALES;
const sourceLocale: Locale = "en";
export const locales = Object.keys(LOCALES) as Locale[];

/** A language's own name ("Deutsch", not "German"), for the language picker. */
export function localeName(locale: Locale): string {
  return LOCALES[locale].name;
}

/** The shipped locale for a stored language tag ("de-AT" -> "de" when only "de" ships), or null. */
export function shippedLocale(tag: string | null | undefined): Locale | null {
  if (!tag) return null;
  const lower = tag.toLowerCase();
  const exact = locales.find((l) => l.toLowerCase() === lower);
  return exact ?? locales.find((l) => l === lower.split("-")[0]) ?? null;
}

/** The first shipped locale among the browser's languages, else English: the UI language before the learner
 * has a profile (the setup wizard, the sign-in page). */
export function browserLocale(): Locale {
  const tags = typeof navigator === "undefined" ? [] : (navigator.languages ?? [navigator.language]);
  for (const tag of tags) {
    const locale = shippedLocale(tag);
    if (locale) return locale;
  }
  return sourceLocale;
}

/** A profile nobody has saved yet still has the server's defaults (English, UTC). */
export function isDefaultProfile(me: { ui_lang: string; tz: string }): boolean {
  return me.ui_lang === "en" && me.tz === "UTC";
}

// Catalogs are PO files compiled on import by @lingui/vite-plugin; each locale is its own lazy chunk.
export async function activateLocale(locale: Locale): Promise<void> {
  if (i18n.locale === locale) return;
  const { messages } = await LOCALES[locale].load();
  i18n.loadAndActivate({ locale, messages });
  document.documentElement.lang = locale;
}

export { i18n };
