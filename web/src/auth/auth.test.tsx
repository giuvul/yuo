import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp, signedInState } from "../test/renderApp";
import type { AuthState, Credential, Device } from "./api";

const CODES = Array.from({ length: 10 }, (_, i) => `ABCDE-FGH${"ABCDEFGHJK"[i]}J`);

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => vi.unstubAllGlobals());

describe("first-run setup", () => {
  it("takes the setup code, a password where passkeys are unavailable, then shows the recovery codes once", async () => {
    let state: AuthState = { signed_in: false, desktop: false, enrolled: false, methods: [], device_id: null, recovery_codes_left: null };
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(state),
      "POST /api/auth/setup": (_r, body) => {
        if ((body as { code: string }).code !== "abcd efgh jkmn pqrs") return json({ detail: "that setup code is not valid" }, 400);
        state = { ...state, signed_in: true, device_id: "d1", recovery_codes_left: 0 };
        return json({ device_id: "d1" });
      },
      "PUT /api/auth/password": () => {
        state = { ...state, enrolled: true, methods: ["password"] };
        return new Response(null, { status: 204 });
      },
      "POST /api/auth/recovery-codes": () => {
        state = { ...state, recovery_codes_left: 10 };
        return json({ codes: CODES });
      },
      "GET /api/paths": () => json([]),
    });
    const user = userEvent.setup();
    const { router } = renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Welcome to Yuo" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/setup");
    expect(screen.queryByRole("button", { name: "More" })).not.toBeInTheDocument(); // no app shell yet

    await user.type(screen.getByRole("textbox", { name: "Setup code" }), "wrong-code");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText(/That setup code does not work/)).toBeInTheDocument();
    await user.clear(screen.getByRole("textbox", { name: "Setup code" }));
    await user.type(screen.getByRole("textbox", { name: "Setup code" }), "abcd efgh jkmn pqrs");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    // jsdom has no WebAuthn: the password is the way in
    expect(await screen.findByRole("heading", { name: "Choose a password" })).toBeInTheDocument();
    expect(screen.getByText(/This browser cannot make passkeys here/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/^New password/), "short");
    await user.type(screen.getByLabelText(/^The same password again/), "short");
    await user.click(screen.getByRole("button", { name: "Save the password" }));
    expect(await screen.findByText("Use at least 10 characters.")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/auth/password")).toBe(false);
    await user.clear(screen.getByLabelText(/^New password/));
    await user.clear(screen.getByLabelText(/^The same password again/));
    await user.type(screen.getByLabelText(/^New password/), "correct horse battery");
    await user.type(screen.getByLabelText(/^The same password again/), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Save the password" }));

    const list = await screen.findByRole("list", { name: "Recovery codes" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(CODES);
    // the wizard keeps the bare layout although the install is enrolled now
    expect(screen.queryByRole("button", { name: "More" })).not.toBeInTheDocument();
    const go = screen.getByRole("button", { name: "Continue to Yuo" });
    expect(go).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "I saved these codes" }));
    await user.click(go);

    expect(await screen.findByRole("heading", { level: 1, name: "Your paths" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "More" })).toBeInTheDocument(); // the app shell: "Sign out" is in this menu
    expect(calls.filter((c) => c.path === "/api/auth/recovery-codes")).toHaveLength(1);
    expect(calls.find((c) => c.path === "/api/auth/setup")?.body).toMatchObject({ device_label: expect.any(String) });
  });
});

describe("sign-in", () => {
  it("sends a signed-out learner to /sign-in and back after the password; explains throttling", async () => {
    let state: AuthState = { ...signedInState, signed_in: false, device_id: null, recovery_codes_left: null, methods: ["passkey", "password"] };
    let tries = 0;
    mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(state),
      "POST /api/auth/sign-in/password": (_r, body) => {
        tries++;
        if (tries === 2) return new Response(JSON.stringify({ detail: "too many" }), { status: 429, headers: { "Retry-After": "540" } });
        if ((body as { password: string }).password !== "correct horse battery") return json({ detail: "wrong password" }, 400);
        state = { ...signedInState, methods: ["passkey", "password"] };
        return json({ device_id: "d1" });
      },
    });
    const user = userEvent.setup();
    const { router } = renderApp("/jobs");

    expect(await screen.findByRole("heading", { level: 1, name: "Sign in to Yuo" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(router.state.location.search).toEqual({ next: "/jobs" });
    // jsdom has no WebAuthn, so the password form is first
    await user.type(screen.getByLabelText(/^Password/), "nope");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Wrong password.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/Try again in 9 minutes\. Signing in with a passkey still works\./)).toBeInTheDocument();

    await user.clear(screen.getByLabelText(/^Password/));
    await user.type(screen.getByLabelText(/^Password/), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/jobs"));
    expect(await screen.findByRole("button", { name: "More" })).toBeInTheDocument();
  });

  it("signs in with a recovery code", async () => {
    let state: AuthState = { ...signedInState, signed_in: false, device_id: null };
    const { calls } = mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(state),
      "POST /api/auth/sign-in/recovery": () => {
        state = signedInState;
        return json({ device_id: "d1" });
      },
      "GET /api/paths": () => json([]),
    });
    const user = userEvent.setup();
    renderApp("/sign-in");
    await user.click(await screen.findByRole("button", { name: "Use a recovery code" }));
    await user.type(screen.getByRole("textbox", { name: /^Recovery code/ }), "abcde-fghjk");
    await user.click(screen.getByRole("button", { name: "Sign in with the code" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Your paths" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/auth/sign-in/recovery")?.body).toMatchObject({ code: "abcde-fghjk" });
  });

  it("goes to /sign-in when an API call says the session ended (401)", async () => {
    let state: AuthState = signedInState;
    mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(state),
      "GET /api/jobs": () => {
        state = { ...signedInState, signed_in: false, device_id: null };
        return json({ detail: "sign in first" }, 401);
      },
    });
    const { router } = renderApp("/jobs");
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in to Yuo" })).toBeInTheDocument();
    expect(router.state.location.search).toEqual({ next: "/jobs" });
  });

  it("adds the CSRF header to unsafe requests of the API client", async () => {
    const { fetchMock } = mockApi({ ...appRoutes, "GET /api/paths": () => json([]) });
    const { api } = await import("../api/client");
    await api.POST("/api/devices", { body: { label: "x" } });
    await api.GET("/api/jobs");
    const sent = fetchMock.mock.calls.map((c) => c[0] as Request);
    expect(sent.find((r) => r.method === "POST")?.headers.get("X-Yuo-Request")).toBe("1");
    expect(sent.find((r) => r.method === "GET")?.headers.get("X-Yuo-Request")).toBeNull();
  });
});

describe("sign-in and devices page", () => {
  const credentials: Credential[] = [
    { id: "c1", kind: "passkey", label: "Chrome on Android", created_at: "2026-10-29T08:00:00Z", last_used_at: "2026-10-29T09:00:00Z" },
    { id: "c2", kind: "password", label: "Password", created_at: "2026-10-29T08:05:00Z", last_used_at: null },
  ];
  const devices: Device[] = [
    { id: "d1", label: "Chrome on Linux", user_agent: "Mozilla/5.0 (X11; Linux x86_64)", first_seen: "2026-10-29T08:00:00Z", last_seen: "2026-10-29T10:00:00Z", sessions: 1, current: true },
    { id: "d2", label: "Safari on iPhone", user_agent: "Mozilla/5.0 (iPhone)", first_seen: "2026-10-29T08:30:00Z", last_seen: "2026-10-29T09:30:00Z", sessions: 1, current: false },
  ];

  function routes(over: Record<string, () => Response> = {}) {
    let list = [...devices];
    let creds = [...credentials];
    let state: AuthState = { ...signedInState, recovery_codes_left: 2, methods: ["passkey", "password"] };
    return mockApi({
      ...appRoutes,
      "GET /api/auth/state": () => json(state),
      "GET /api/auth/credentials": () => json(creds),
      "GET /api/auth/devices": () => json(list),
      "DELETE /api/auth/devices/d2": () => {
        list = list.filter((d) => d.id !== "d2");
        return new Response(null, { status: 204 });
      },
      "DELETE /api/auth/credentials/c2": () => {
        creds = creds.filter((c) => c.id !== "c2");
        return new Response(null, { status: 204 });
      },
      "POST /api/auth/recovery-codes": () => {
        state = { ...state, recovery_codes_left: 10 };
        return json({ codes: CODES });
      },
      "POST /api/auth/sign-out": () => {
        state = { ...state, signed_in: false, device_id: null };
        return new Response(null, { status: 204 });
      },
      ...over,
    });
  }

  it("lists the ways to sign in and removes one after confirming", async () => {
    const { calls } = routes();
    const user = userEvent.setup();
    renderApp("/settings/devices");
    expect(await screen.findByRole("heading", { level: 1, name: "Sign-in and devices" })).toBeInTheDocument();
    const ways = within(screen.getByRole("region", { name: "Ways to sign in" }));
    expect(await ways.findByText("Chrome on Android")).toBeInTheDocument();
    expect(ways.getByText(/not used yet/)).toBeInTheDocument();
    expect(ways.getByRole("button", { name: "Change password" })).toBeInTheDocument();
    expect(ways.queryByRole("button", { name: "Add a passkey" })).not.toBeInTheDocument(); // no WebAuthn in jsdom

    await user.click(ways.getByRole("button", { name: "Remove Password" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(ways.getByRole("button", { name: "Remove Password for good" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/auth/credentials/c2")).toBe(true));
    // one way left: it cannot be removed
    expect(await ways.findByText(/This is your only way to sign in/)).toBeInTheDocument();
    expect(ways.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
  });

  it("shows the codes left and makes new ones after confirming", async () => {
    const { calls } = routes();
    const user = userEvent.setup();
    renderApp("/settings/devices");
    const codes = within(await screen.findByRole("region", { name: "Recovery codes" }));
    expect(await codes.findByText("2 recovery codes left.")).toBeInTheDocument();
    expect(codes.getByText(/Make new codes so you can still get in/)).toBeInTheDocument();
    await user.click(codes.getByRole("button", { name: "Make new recovery codes" }));
    expect(codes.getByText(/Your current codes will stop working/)).toBeInTheDocument();
    await user.click(codes.getByRole("button", { name: "Make new codes" }));
    const list = await codes.findByRole("list", { name: "Recovery codes" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(10);
    await user.click(codes.getByRole("checkbox", { name: "I saved these codes" }));
    await user.click(codes.getByRole("button", { name: "Done" }));
    expect(await codes.findByText("10 recovery codes left.")).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/auth/recovery-codes")).toHaveLength(1);
  });

  it("marks this device, signs another out after confirming, and signs out", async () => {
    const { calls } = routes();
    const user = userEvent.setup();
    const { router } = renderApp("/settings/devices");
    const region = within(await screen.findByRole("region", { name: "Devices" }));
    const items = await region.findAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText("This device")).toBeInTheDocument();
    expect(within(items[1]!).queryByText("This device")).not.toBeInTheDocument();

    await user.click(region.getByRole("button", { name: "Sign out Safari on iPhone" }));
    await user.click(region.getByRole("button", { name: "Yes, sign out Safari on iPhone" }));
    expect(await region.findByText("Safari on iPhone was signed out.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/auth/devices/d2")).toBe(true);
    await waitFor(() => expect(region.getAllByRole("listitem")).toHaveLength(1));

    await user.click(region.getByRole("button", { name: "Sign out of this device" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in to Yuo" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(calls.some((c) => c.path === "/api/auth/sign-out")).toBe(true);
  });
});
