// The route guard: every screen needs a session except the first-run setup and sign-in.
// Fresh install (nothing enrolled) -> /setup; enrolled but signed out -> /sign-in, remembering where
// the learner was going; signed in on /sign-in -> back to where they were going.
// Desktop: starting Yuo from its launcher is the sign-in, so there is no setup or sign-in screen to
// send anyone to; signed out, the layout asks to start Yuo again from its launcher.
import type { AuthState } from "./api";

const SIGN_IN = "/sign-in";
const SETUP = "/setup";

type Redirect = { to: string; search?: { next?: string } };

/** Only same-app paths: no scheme, no protocol-relative `//host`, no backslash tricks. */
export function safeNext(next: unknown): string | null {
  if (typeof next !== "string" || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  if (next === SIGN_IN || next.startsWith(`${SIGN_IN}?`) || next === SETUP) return null;
  return next;
}

export function authRedirect(state: AuthState | undefined, location: { pathname: string; href: string }, next?: unknown): Redirect | null {
  if (!state) return null; // unknown (loading or unreachable): leave the screen alone
  const { pathname } = location;
  if (state.desktop) {
    if (!state.signed_in) return null; // the layout shows "start Yuo again from its launcher"
    return pathname === SIGN_IN ? { to: safeNext(next) ?? "/" } : null;
  }
  if (!state.enrolled) return pathname === SETUP ? null : { to: SETUP };
  if (!state.signed_in) {
    if (pathname === SIGN_IN) return null;
    const back = safeNext(location.href);
    return back && back !== "/" ? { to: SIGN_IN, search: { next: back } } : { to: SIGN_IN };
  }
  if (pathname === SIGN_IN) return { to: safeNext(next) ?? "/" };
  return null;
}

/** The app shell (header, tutor, stream) only runs with a session; the first-run wizard keeps it off. */
export function showsShell(state: AuthState | undefined, wizardActive: boolean): boolean {
  if (!state) return true; // unreachable server: show the shell so cached screens and the outbox still work
  if (state.desktop) return state.signed_in;
  return state.enrolled && state.signed_in && !wizardActive;
}
