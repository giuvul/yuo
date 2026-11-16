import { afterEach, describe, expect, it, vi } from "vitest";
import { browserLocale, isDefaultProfile, localeName, locales, shippedLocale } from "./i18n";

afterEach(() => vi.unstubAllGlobals());

describe("UI languages", () => {
  it("ships English, Italian, Spanish, Portuguese and German, each named in its own language", () => {
    expect([...locales].sort()).toEqual(["de", "en", "es", "it", "pt"]);
    expect(locales.map(localeName)).toEqual(expect.arrayContaining(["Deutsch", "Español", "Italiano", "Português"]));
    expect(shippedLocale("pt-BR")).toBe("pt");
    expect(shippedLocale("fr")).toBeNull();
  });

  it("starts in the first shipped browser language until the profile is saved", () => {
    vi.stubGlobal("navigator", { languages: ["fr-FR", "it-IT", "en"], language: "fr-FR" });
    expect(browserLocale()).toBe("it");
    vi.stubGlobal("navigator", { languages: ["ja"], language: "ja" });
    expect(browserLocale()).toBe("en");
    expect(isDefaultProfile({ ui_lang: "en", tz: "UTC" })).toBe(true);
    expect(isDefaultProfile({ ui_lang: "en", tz: "Europe/Rome" })).toBe(false);
  });
});
