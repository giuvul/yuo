import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@lingui/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale, i18n } from "../i18n";
import { InstallButton, RELOAD_FALLBACK_MS, ShortcutGuide, UpdateNotice } from "./PwaControls";
import { installPrompt, listenForInstall, shortcutBrowser, updateReady } from "./pwa";

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  installPrompt.set(null);
  updateReady.set(null);
});

const wrap = (ui: React.ReactNode) => render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);

describe("install and update", () => {
  it("offers Save app shortcut only after the browser's install prompt, and uses it once", async () => {
    const stop = listenForInstall();
    wrap(<InstallButton />);
    expect(screen.queryByRole("button", { name: "Save app shortcut" })).not.toBeInTheDocument();

    const prompt = vi.fn(async () => {});
    const event = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), {
      prompt,
      userChoice: Promise.resolve({ outcome: "accepted" as const }),
    });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Save app shortcut" }));
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Save app shortcut" })).not.toBeInTheDocument();
    stop();
  });

  it("shows Reload to update when a new version waits", async () => {
    wrap(<UpdateNotice />);
    expect(screen.queryByText(/A new version/)).not.toBeInTheDocument();
    const update = vi.fn(async () => {});
    act(() => updateReady.set(update));
    expect(screen.getByText("A new version of Yuo is ready.")).toBeInTheDocument();
    const reload = vi.fn();
    const location = window.location;
    Object.defineProperty(window, "location", { configurable: true, value: { ...location, reload } });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await userEvent.click(screen.getByRole("button", { name: "Reload to update" }));
      expect(update).toHaveBeenCalledTimes(1);
      // the learner sees it working and knows not to reload by hand
      expect(screen.getByText(/Updating Yuo… the page reloads by itself/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Reload to update" })).not.toBeInTheDocument();
      expect(sessionStorage.getItem("yuo.updated")).toBe("1");
      act(() => vi.advanceTimersByTime(RELOAD_FALLBACK_MS));
      expect(reload).toHaveBeenCalledTimes(1); // the worker never took over: the page reloads anyway
    } finally {
      vi.useRealTimers();
      Object.defineProperty(window, "location", { configurable: true, value: location });
    }
  });

  it("says which version runs after the reload, once", async () => {
    sessionStorage.setItem("yuo.updated", "1");
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ version: "1.2.0" })));
    try {
      wrap(<UpdateNotice />);
      expect(await screen.findByText("Yuo is up to date: version 1.2.0.")).toBeInTheDocument();
      expect(sessionStorage.getItem("yuo.updated")).toBeNull();
      await userEvent.click(screen.getByRole("button", { name: "OK" }));
      expect(screen.queryByText(/up to date/)).not.toBeInTheDocument();
    } finally {
      fetch.mockRestore();
    }
  });
});

describe("the shortcut guide", () => {
  const firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0";
  it("knows the browsers that never offer installing", () => {
    expect(shortcutBrowser(firefox)).toBe("firefox");
    expect(shortcutBrowser("Mozilla/5.0 (Android 14; Mobile; rv:140.0) Gecko/140.0 Firefox/140.0")).toBe("firefox-android");
    expect(
      shortcutBrowser("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"),
    ).toBe("ios");
    expect(
      shortcutBrowser("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"),
    ).toBe("safari");
    expect(
      shortcutBrowser("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0"),
    ).toBe("chromium");
  });

  it("shows Firefox how to keep Yuo one click away", async () => {
    const ua = vi.spyOn(navigator, "userAgent", "get").mockReturnValue(firefox);
    try {
      wrap(<ShortcutGuide isOpen onOpenChange={() => {}} />);
      expect(screen.getByRole("heading", { name: "Save Yuo as a shortcut" })).toBeInTheDocument();
      expect(screen.getByText(/Firefox on a computer cannot save a site as an app/)).toBeInTheDocument();
      expect(screen.getByText(/Pin Tab/)).toBeInTheDocument();
    } finally {
      ua.mockRestore();
    }
  });
});
