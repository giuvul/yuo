// Desktop sign-in: the launcher opens http://127.0.0.1:PORT/#launch=CODE. The code sits in the URL
// fragment, so it never reaches a server log or a Referer; the app trades it for a session once
// (POST /api/auth/launch) and removes it from the address bar at once, so a reload or a copied link
// does not carry it.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { authFetch, signedIn, type SignedIn } from "./api";

/** The launch code in a URL fragment ("#launch=CODE", maybe among other fragment parameters), or null. */
export function launchCode(hash: string): string | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const code = params.get("launch");
  return code && code.trim() ? code.trim() : null;
}

let running: Promise<SignedIn> | null = null;

/** Reads and strips the fragment once, then redeems it; one request however often it is called. */
function redeemFromFragment(): Promise<SignedIn> | null {
  if (running) return running;
  if (typeof window === "undefined") return null;
  const code = launchCode(window.location.hash);
  if (!code) return null;
  window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  running = authFetch<SignedIn>("POST", "/api/auth/launch", { code }).finally(() => {
    running = null;
  });
  return running;
}

type LaunchState = "none" | "signing-in" | "failed";

/** Runs the launch sign-in when the page was opened with a launch link. */
export function useLaunchSignIn(): LaunchState {
  const qc = useQueryClient();
  const [state, setState] = useState<LaunchState>(() =>
    typeof window !== "undefined" && launchCode(window.location.hash) ? "signing-in" : "none",
  );

  useEffect(() => {
    const pending = redeemFromFragment();
    if (!pending) return;
    let live = true;
    pending.then(
      async () => {
        await signedIn(qc);
        if (live) setState("none");
      },
      () => {
        if (live) setState("failed");
      },
    );
    return () => {
      live = false;
    };
  }, [qc]);

  return state;
}
