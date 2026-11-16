import { describe, expect, it } from "vitest";
import type { AuthState } from "./api";
import { deviceLabel } from "./deviceLabel";
import { authRedirect, safeNext, showsShell } from "./guard";

const state = (patch: Partial<AuthState>): AuthState => ({
  signed_in: true,
  desktop: false,
  enrolled: true,
  methods: ["passkey"],
  device_id: "d1",
  recovery_codes_left: 10,
  ...patch,
});
const at = (pathname: string, search = "") => ({ pathname, href: pathname + search });

describe("auth guard", () => {
  it("leaves the screen alone while the state is unknown", () => {
    expect(authRedirect(undefined, at("/paths/p1"))).toBeNull();
  });

  it("sends a fresh install to /setup, and stays there", () => {
    const fresh = state({ enrolled: false, signed_in: false, methods: [] });
    expect(authRedirect(fresh, at("/"))).toEqual({ to: "/setup" });
    expect(authRedirect(fresh, at("/sign-in"))).toEqual({ to: "/setup" });
    expect(authRedirect(fresh, at("/setup"))).toBeNull();
    // signed in with the setup code but no credential yet: still the setup
    expect(authRedirect(state({ enrolled: false }), at("/settings"))).toEqual({ to: "/setup" });
  });

  it("sends a signed-out learner to /sign-in and remembers where they were going", () => {
    const out = state({ signed_in: false, device_id: null });
    expect(authRedirect(out, at("/paths/p1", "?tab=x"))).toEqual({ to: "/sign-in", search: { next: "/paths/p1?tab=x" } });
    expect(authRedirect(out, at("/"))).toEqual({ to: "/sign-in" });
    expect(authRedirect(out, at("/setup"))).toEqual({ to: "/sign-in" });
    expect(authRedirect(out, at("/sign-in"))).toBeNull();
  });

  it("sends a signed-in learner away from /sign-in to a safe next path", () => {
    expect(authRedirect(state({}), at("/sign-in"), "/paths/p1")).toEqual({ to: "/paths/p1" });
    expect(authRedirect(state({}), at("/sign-in"), "//evil.example/x")).toEqual({ to: "/" });
    expect(authRedirect(state({}), at("/sign-in"), "https://evil.example")).toEqual({ to: "/" });
    expect(authRedirect(state({}), at("/paths/p1"))).toBeNull();
  });

  it("accepts only same-app paths as next", () => {
    expect(safeNext("/paths/p1/review/session?skill=s1")).toBe("/paths/p1/review/session?skill=s1");
    for (const bad of ["//x", "/\\x", "http://x", "x", 5, null, "/sign-in", "/setup"]) expect(safeNext(bad)).toBeNull();
  });

  it("shows the app shell only with a session, outside the first-run wizard", () => {
    expect(showsShell(state({}), false)).toBe(true);
    expect(showsShell(state({}), true)).toBe(false);
    expect(showsShell(state({ signed_in: false }), false)).toBe(false);
    expect(showsShell(state({ enrolled: false }), false)).toBe(false);
    expect(showsShell(undefined, false)).toBe(true); // server unreachable: cached screens still work
  });

  it("never sends a desktop learner to the passkey setup or the sign-in screen", () => {
    const out = state({ desktop: true, enrolled: false, signed_in: false, methods: [] });
    expect(authRedirect(out, at("/"))).toBeNull();
    expect(authRedirect(out, at("/setup"))).toBeNull();
    const signedIn = state({ desktop: true, enrolled: false, methods: [] });
    expect(authRedirect(signedIn, at("/settings"))).toBeNull();
    expect(authRedirect(signedIn, at("/sign-in"), "/progress")).toEqual({ to: "/progress" });
    expect(showsShell(signedIn, false)).toBe(true);
    expect(showsShell(out, false)).toBe(false);
  });
});

describe("device label", () => {
  it("names browser and system", () => {
    expect(
      deviceLabel(
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
      ),
    ).toBe("Chrome on Android");
    expect(
      deviceLabel(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
      ),
    ).toBe("Safari on iPhone");
    expect(deviceLabel("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0")).toBe(
      "Firefox on Windows",
    );
    expect(
      deviceLabel(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0",
      ),
    ).toBe("Edge on Mac");
    expect(deviceLabel("curl/8")).toBe("Browser");
  });
});
