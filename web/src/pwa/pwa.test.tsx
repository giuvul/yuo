import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "@lingui/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale, i18n } from "../i18n";
import { InstallButton, UpdateNotice } from "./PwaControls";
import { installPrompt, listenForInstall, updateReady } from "./pwa";

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
    await userEvent.click(screen.getByRole("button", { name: "Reload to update" }));
    expect(update).toHaveBeenCalledTimes(1);
  });
});
