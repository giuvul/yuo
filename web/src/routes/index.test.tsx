import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, configuredSetup, renderApp } from "../test/renderApp";

describe("home", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists paths and offers a new one", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/paths": () =>
        json([
          {
            id: "p1",
            title: "SQL for analysts",
            subject: "SQL",
            status: "active",
            difficulty: "foundational",
            content_lang: "en",
            created_at: "2026-10-27T10:00:00.000Z",
          },
        ]),
    });
    renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Your paths" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /SQL for analysts/ })).toHaveAttribute("href", "/paths/p1");
    expect(screen.getByRole("link", { name: "New path" })).toHaveAttribute("href", "/paths/new");
    expect(screen.getByRole("link", { name: "Yuo" })).toBeInTheDocument();
    expect(screen.getByText("Synced")).toBeInTheDocument();
  });

  it("goes to setup while no models are bound", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/setup": () => json({ ...configuredSetup, bindings: {} }),
      "GET /api/paths": () => json([]),
    });
    const { router } = renderApp("/");

    await waitFor(() => expect(router.state.location.pathname).toBe("/setup"));
    expect(await screen.findByRole("heading", { level: 1, name: "Set up Yuo" })).toBeInTheDocument();
  });
});
