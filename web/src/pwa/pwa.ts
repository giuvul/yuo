// The PWA side of the app shell: the service worker registration with an "update ready"
// signal, and the install prompt where the browser offers one (beforeinstallprompt; Chromium only).
import { useSyncExternalStore } from "react";

type Listener = () => void;

function store<T>(initial: T) {
  let value = initial;
  const listeners = new Set<Listener>();
  return {
    get: () => value,
    set(next: T) {
      if (Object.is(next, value)) return;
      value = next;
      for (const l of listeners) l();
    },
    subscribe(l: Listener) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

// --- update -------------------------------------------------------------------------------------------

/** Set when a new version's service worker is waiting; calling it activates it and reloads. */
export const updateReady = store<null | (() => Promise<void>)>(null);

export function useUpdateReady() {
  return useSyncExternalStore(updateReady.subscribe, updateReady.get, updateReady.get);
}

const UPDATE_CHECK_MS = 30 * 60_000;

/** Registers the service worker (built mode only). The new one waits until the learner reloads. */
export async function registerServiceWorker(): Promise<void> {
  if (!import.meta.env.PROD || typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  const { registerSW } = await import("virtual:pwa-register");
  const update = registerSW({
    immediate: true,
    onNeedRefresh() {
      updateReady.set(() => update(true));
    },
    // a tab left open would otherwise only learn of a new version when it is loaded again
    // (a fix deployed to the server would not reach an open tab): look again every half hour and
    // whenever the tab comes back into view
    onRegisteredSW(_url: string, registration: ServiceWorkerRegistration | undefined) {
      if (!registration) return;
      const check = () => void registration.update().catch(() => {});
      setInterval(check, UPDATE_CHECK_MS);
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") check();
      });
    },
    onRegisterError(error: unknown) {
      console.warn("service worker registration failed", error);
    },
  });
}

// --- install ---------------------------------------------------------------------------------------------

/** The `beforeinstallprompt` event (not in the DOM typings: Chromium only). */
type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

export const installPrompt = store<InstallPromptEvent | null>(null);

export function useInstallPrompt() {
  return useSyncExternalStore(installPrompt.subscribe, installPrompt.get, installPrompt.get);
}

/** Keeps the browser's install prompt for the "Install app" button; forgets it once installed. */
export function listenForInstall(target: Window = window): () => void {
  const onPrompt = (e: Event) => {
    e.preventDefault(); // no mini-infobar: the header button offers it
    installPrompt.set(e as InstallPromptEvent);
  };
  const onInstalled = () => installPrompt.set(null);
  target.addEventListener("beforeinstallprompt", onPrompt);
  target.addEventListener("appinstalled", onInstalled);
  return () => {
    target.removeEventListener("beforeinstallprompt", onPrompt);
    target.removeEventListener("appinstalled", onInstalled);
  };
}

export async function install(): Promise<void> {
  const event = installPrompt.get();
  if (!event) return;
  installPrompt.set(null); // a prompt event can be used once
  await event.prompt();
  await event.userChoice;
}
