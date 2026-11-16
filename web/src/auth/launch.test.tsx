import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp, signedInState } from "../test/renderApp";
import type { AuthState } from "./api";
import { launchCode } from "./launch";

const CODE = "Lc0dE-abcdefghijklmnop";

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

const desktopOut: AuthState = {
  ...signedInState,
  desktop: true,
  enrolled: false,
  signed_in: false,
  methods: [],
  device_id: null,
  recovery_codes_left: null,
};

describe("desktop sign-in", () => {
  it("reads the code from the fragment", () => {
    expect(launchCode("#launch=abc123")).toBe("abc123");
    expect(launchCode("#x=1&launch=abc123")).toBe("abc123");
    expect(launchCode("")).toBeNull();
    expect(launchCode("#launch=")).toBeNull();
  });

  it("trades the launch code for a session once and removes it from the address bar", async () => {
    let state = desktopOut;
    window.history.replaceState(null, "", `/#launch=${CODE}`);
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(state),
      "POST /api/auth/launch": (_r, body) => {
        if ((body as { code: string }).code !== CODE) return json({ detail: "that link does not work" }, 400);
        state = { ...state, signed_in: true, device_id: "d1" };
        return json({ device_id: "d1" });
      },
      "GET /api/paths": () => json([]),
    });
    renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Your paths" })).toBeInTheDocument();
    expect(window.location.hash).toBe("");
    expect(calls.filter((c) => c.path === "/api/auth/launch")).toEqual([
      { method: "POST", path: "/api/auth/launch", body: { code: CODE } },
    ]);
    expect(screen.queryByRole("heading", { name: "Welcome to Yuo" })).not.toBeInTheDocument();
  });

  it("never shows the passkey setup on the desktop: signed out, it has a signed-in tab opened and follows it", async () => {
    let state = desktopOut;
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(state),
      "POST /api/desktop/open": () => {
        state = { ...state, signed_in: true, device_id: "d1" }; // the new tab signed this browser in
        return json(null, 202);
      },
      "GET /api/paths": () => json([]),
    });
    renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Signing you in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Welcome to Yuo" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Setup code" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "Your paths" }, { timeout: 4000 })).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/desktop/open")).toEqual([
      { method: "POST", path: "/api/desktop/open", body: { auto: true } },
    ]);
  });

  it("opens a signed-in tab from the button, and says when one opened a moment ago", async () => {
    let opened = 0;
    mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(desktopOut),
      "POST /api/desktop/open": () =>
        ++opened > 1 ? json({ detail: "Yuo was opened a moment ago" }, 429) : json(null, 202),
    });
    const user = userEvent.setup();
    renderApp("/");
    const button = await screen.findByRole("button", { name: "Open Yuo signed in" });
    await user.click(button);
    expect(await screen.findByText("A new tab is opening. If your browser asks, allow it.")).toBeInTheDocument();
    await user.click(button);
    expect(
      await screen.findByText("Yuo opened a tab a moment ago. Look for it, or try again in a few seconds."),
    ).toBeInTheDocument();
  });

  it("says when a launch link was already used", async () => {
    window.history.replaceState(null, "", `/#launch=${CODE}`);
    mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(desktopOut),
      "POST /api/auth/launch": () => json({ detail: "that link does not work" }, 400),
    });
    renderApp("/");
    expect(await screen.findByText("This link has already been used or is too old.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Signing you in" })).toBeInTheDocument();
    await waitFor(() => expect(window.location.hash).toBe(""));
  });

  it("keeps the sign-in setup on a server (desktop false)", async () => {
    mockApi({
      ...appRoutes,
      "GET /api/auth/state": () =>
        json({ ...signedInState, signed_in: false, enrolled: false, methods: [], device_id: null }),
    });
    renderApp("/");
    expect(await screen.findByRole("heading", { level: 1, name: "Welcome to Yuo" })).toBeInTheDocument();
  });
});
