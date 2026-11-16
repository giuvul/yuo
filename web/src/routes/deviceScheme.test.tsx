// While the app theme follows the device, the device's light or dark look goes to
// the server once, so a video set to match the app comes out like the app.
import { waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, closeApps, meState, renderApp } from "../test/renderApp";

beforeAll(async () => {
  await activateLocale("en");
});

function deviceIs(dark: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: dark && query.includes("dark"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

beforeEach(() => localStorage.clear());
afterEach(async () => {
  vi.unstubAllGlobals();
  await closeApps();
});

const NO_CONTENT = () => new Response(null, { status: 204 });

describe("the device's light or dark look", () => {
  it("is sent once while the app follows the device", async () => {
    deviceIs(true);
    const api = mockApi({ ...appRoutes, "PUT /api/settings/ui.device_scheme": NO_CONTENT });
    renderApp("/settings");
    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/settings/ui.device_scheme")).toBe(true));
    const put = api.calls.find((c) => c.path === "/api/settings/ui.device_scheme")!;
    expect(put.method).toBe("PUT");
    expect(put.body).toMatchObject({ value: "dark", level: "learner" });
    await waitFor(() => expect(localStorage.getItem("yuo.device-scheme")).toBe("dark"));

    await closeApps();
    const again = mockApi({ ...appRoutes, "PUT /api/settings/ui.device_scheme": NO_CONTENT });
    renderApp("/settings");
    await waitFor(() => expect(again.calls.some((c) => c.path === "/api/me")).toBe(true));
    expect(again.calls.some((c) => c.path === "/api/settings/ui.device_scheme")).toBe(false); // unchanged: not sent
  });

  it("is not sent when the app has its own theme", async () => {
    deviceIs(true);
    const api = mockApi({
      ...appRoutes,
      "GET /api/me": () => json({ ...meState, theme: "light" }),
      "PUT /api/settings/ui.device_scheme": NO_CONTENT,
    });
    renderApp("/settings");
    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/me")).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    expect(api.calls.some((c) => c.path === "/api/settings/ui.device_scheme")).toBe(false);
  });
});
