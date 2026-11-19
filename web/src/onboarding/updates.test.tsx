import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { UpdateOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, configuredSetup, renderApp } from "../test/renderApp";
import { appStopped } from "./desktop";
import { page } from "./SettingsSections";

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  appStopped.set(false);
});

const status = (patch: Partial<UpdateOut>): UpdateOut => ({
  current: "1.0.0",
  feed: true,
  latest: null,
  published_at: null,
  notes_url: null,
  available: false,
  staged: null,
  can_install: true,
  ...patch,
});

async function updatesSection() {
  const s = within((await screen.findByRole("heading", { level: 2, name: "Updates" })).closest("section")!);
  await s.findByText(/You have version/);
  return s;
}

describe("updates in Settings", () => {
  it("says when this build does not check for updates", async () => {
    mockApi({ ...appRoutes, "GET /api/settings": () => json([]), "GET /api/update": () => json(status({ feed: false })) });
    renderApp("/settings");
    const s = await updatesSection();
    expect(s.getByText("You have version 1.0.0.")).toBeInTheDocument();
    expect(s.getByText("This build does not check for updates.")).toBeInTheDocument();
    expect(s.queryByRole("button", { name: "Check now" })).not.toBeInTheDocument();
  });

  it("checks now, tells a server to pull the new image", async () => {
    let st = status({ can_install: false });
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/update": () => json(st),
      "POST /api/update/check": () => {
        st = { ...st, latest: "1.1.0", available: true, notes_url: "https://releases.example/1.1.0" };
        return json(st);
      },
    });
    const u = userEvent.setup();
    renderApp("/settings");
    const s = await updatesSection();
    expect(s.getByText("Yuo has not checked for a newer version yet.")).toBeInTheDocument();
    await u.click(s.getByRole("button", { name: "Check now" }));
    expect(await s.findByText("Version 1.1.0 is available.")).toBeInTheDocument();
    expect(s.getByText(/set YUO_IMAGE in .env to the new version/)).toBeInTheDocument();
    expect(s.getByText(/starts by itself whenever Docker runs/)).toBeInTheDocument();
    expect(s.getByRole("link", { name: /What is new/ })).toHaveAttribute("target", "_blank");
    expect(s.queryByRole("button", { name: "Download" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/update/check")).toBe(true);
  });

  it("downloads, restarts, waits for the new version and reloads", async () => {
    let st = status({ latest: "1.1.0", available: true });
    let health = "1.0.0";
    const reload = vi.spyOn(page, "reload").mockImplementation(() => {});
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/update": () => json(st),
      "POST /api/update/download": () => {
        st = { ...st, staged: "1.1.0" };
        return json(st);
      },
      "POST /api/update/restart": () => {
        health = "1.1.0";
        return json(null, 202);
      },
      "GET /api/health": () => json({ status: "ok", version: health }),
    });
    const u = userEvent.setup();
    renderApp("/settings");
    const s = await updatesSection();
    expect(s.queryByRole("button", { name: "Restart to install" })).not.toBeInTheDocument();
    await u.click(s.getByRole("button", { name: "Download" }));
    expect(await s.findByText(/downloaded and checked/)).toBeInTheDocument();
    await u.click(s.getByRole("button", { name: "Restart to install" }));
    expect(await screen.findByText(/Yuo is restarting/)).toBeInTheDocument();
    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(calls.some((c) => c.path === "/api/health")).toBe(true);
  });
});

describe("Stop Yuo (desktop)", () => {
  it("is only on the desktop, asks first, then shows that Yuo has stopped", async () => {
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup": () => json({ ...configuredSetup, desktop: true }),
      "POST /api/desktop/quit": () => json(null, 202),
    });
    const u = userEvent.setup();
    renderApp("/settings");
    await u.click(await screen.findByRole("button", { name: "Stop Yuo" }));
    expect(screen.getByText(/Stop Yuo now\?/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/desktop/quit")).toBe(false);
    await u.click(screen.getByRole("button", { name: "Yes, stop Yuo" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Yuo has stopped" })).toBeInTheDocument();
    expect(screen.getByText(/You can close this tab/)).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/desktop/quit")).toHaveLength(1);
  });

  it("is not offered on a server", async () => {
    mockApi({ ...appRoutes, "GET /api/settings": () => json([]) });
    renderApp("/settings");
    expect(await screen.findByRole("heading", { level: 2, name: "Updates" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop Yuo" })).not.toBeInTheDocument();
  });
});

describe("AI access in Settings", () => {
  it("replaces and removes the OpenRouter key and lists the apps found", async () => {
    let access = { openrouter: true, local_url: null as string | null, local: false, clis: ["claude"], consent: {} };
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/access": () => json(access),
      "DELETE /api/setup/access/openrouter": () => {
        access = { ...access, openrouter: false };
        return new Response(null, { status: 204 });
      },
    });
    const u = userEvent.setup();
    renderApp("/settings");
    expect(await screen.findByText("A key is saved on this computer. It is never shown again.")).toBeInTheDocument();
    expect(screen.getByText("Found on this computer: Claude Code")).toBeInTheDocument();
    expect(screen.getByText("Writes lessons:")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Remove the key" }));
    await u.click(screen.getByRole("button", { name: "Yes, remove the key" }));
    expect(await screen.findByText("No OpenRouter key is saved.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "DELETE" && c.path === "/api/setup/access/openrouter")).toHaveLength(1);
  });

  it("offers a new key in place of the saved one, as a hidden field", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/settings": () => json([]),
      "GET /api/setup/access": () => json({ openrouter: true, local_url: null, local: false, clis: [], consent: {} }),
    });
    const u = userEvent.setup();
    renderApp("/settings");
    await u.click(await screen.findByRole("button", { name: "Replace the key" }));
    expect(screen.getByLabelText(/^New OpenRouter key/)).toHaveAttribute("type", "password");
    expect(screen.getByText("No Claude Code or Codex app was found on this computer.")).toBeInTheDocument();
  });
});
