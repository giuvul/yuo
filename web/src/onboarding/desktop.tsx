// The desktop app: the page for a signed-out tab (opens a signed-in one), and "Stop Yuo"
// with the screen that follows it.
import { LogoMark } from "../components/Logo";
import { Trans } from "@lingui/react/macro";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState, useSyncExternalStore } from "react";
import { AuthApiError, authFetch, authKeys, type AuthState } from "../auth/api";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button, Notice, ui } from "../components/ui";
import { useQuitDesktop } from "./api";
import styles from "./onboarding.module.css";

type Listener = () => void;
let stopped = false;
const listeners = new Set<Listener>();

/** Set once Yuo has been stopped from this tab: the layout then shows only the "stopped" screen. */
export const appStopped = {
  get: (): boolean => stopped,
  set(v: boolean): void {
    if (v === stopped) return;
    stopped = v;
    for (const l of listeners) l();
  },
  subscribe(l: Listener): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
};

export function useAppStopped(): boolean {
  return useSyncExternalStore(appStopped.subscribe, appStopped.get, appStopped.get);
}

export function StoppedScreen() {
  return (
    <section className={styles.stopped} role="status">
      <span className={styles.stoppedMark}>
        <LogoMark size={48} />
      </span>
      <h1 className={ui.pageTitle}>
        <Trans id="desktop.stopped.title">Yuo has stopped</Trans>
      </h1>
      <p>
        <Trans id="desktop.stopped.body">You can close this tab. To use Yuo again, start it from its launcher.</Trans>
      </p>
    </section>
  );
}

let askedOnce = false;

/** Asks the server to open Yuo signed in, in a new tab (POST /api/desktop/open); 429 = opened a moment ago. */
function openSignedIn(auto: boolean): Promise<void> {
  return authFetch<void>("POST", "/api/desktop/open", { auto });
}

/** Desktop and signed out, for example when the link the launcher opened got lost behind a browser's
 * first-run screens: the server opens a signed-in tab (once on its own, then from the button), and this tab
 * follows as soon as the browser is signed in. */
export function DesktopSignedOut({ failed }: { failed: boolean }) {
  useQuery({
    queryKey: authKeys.state,
    queryFn: () => authFetch<AuthState>("GET", "/api/auth/state"),
    refetchInterval: 2000,
    retry: false,
  });
  const open = useMutation({ mutationFn: () => openSignedIn(false) });
  useEffect(() => {
    if (askedOnce) return;
    askedOnce = true;
    openSignedIn(true).catch(() => undefined);
  }, []);
  const tooSoon = open.error instanceof AuthApiError && open.error.status === 429;
  return (
    <section className={`${ui.stack} ${styles.wizard}`}>
      <h1 className={ui.pageTitle}>
        <Trans id="desktop.signed-out.signing-in">Signing you in</Trans>
      </h1>
      {failed ? (
        <Notice tone="warning">
          <Trans id="desktop.signed-out.failed">This link has already been used or is too old.</Trans>
        </Notice>
      ) : null}
      <p>
        <Trans id="desktop.signed-out.opening">
          Yuo opens itself signed in, in a new tab of this browser. This tab continues on its own once that is done.
        </Trans>
      </p>
      <div className={ui.row}>
        <Button isDisabled={open.isPending} onPress={() => open.mutate()}>
          <Trans id="desktop.signed-out.open">Open Yuo signed in</Trans>
        </Button>
      </div>
      {open.isSuccess ? (
        <Notice role="status">
          <Trans id="desktop.signed-out.opened">A new tab is opening. If your browser asks, allow it.</Trans>
        </Notice>
      ) : tooSoon ? (
        <Notice role="status">
          <Trans id="desktop.signed-out.too-soon">
            Yuo opened a tab a moment ago. Look for it, or try again in a few seconds.
          </Trans>
        </Notice>
      ) : open.isError ? (
        <ErrorNotice error={open.error} />
      ) : null}
      <p className={ui.muted}>
        <Trans id="desktop.signed-out.fallback">
          If nothing opens, start Yuo again from its launcher (the Yuo-Windows / Yuo-macOS / Yuo-Linux file, or the Yuo
          menu entry).
        </Trans>
      </p>
    </section>
  );
}

/** Settings, desktop only: stop the Yuo server on this computer, after a confirmation. */
export function StopYuo() {
  const quit = useQuitDesktop();
  const [confirming, setConfirming] = useState(false);
  const textId = useId();
  return (
    <div className={ui.stack}>
      <p>
        <Trans id="desktop.stop.intro">
          Yuo keeps running in the background while this tab is closed, so it can prepare lessons. Stop it when you do
          not need it.
        </Trans>
      </p>
      {confirming ? (
        <div className={ui.stack} role="group" aria-labelledby={textId}>
          <p id={textId}>
            <Trans id="desktop.stop.confirm-text">
              Stop Yuo now? Lessons that are being written wait until you start it again.
            </Trans>
          </p>
          <div className={ui.row}>
            <Button
              isDisabled={quit.isPending}
              onPress={() => quit.mutate(undefined, { onSuccess: () => appStopped.set(true) })}
            >
              <Trans id="desktop.stop.confirm">Yes, stop Yuo</Trans>
            </Button>
            <Button variant="secondary" onPress={() => setConfirming(false)}>
              <Trans id="desktop.stop.cancel">Keep it running</Trans>
            </Button>
          </div>
        </div>
      ) : (
        <div className={ui.row}>
          <Button variant="secondary" onPress={() => setConfirming(true)}>
            <Trans id="desktop.stop">Stop Yuo</Trans>
          </Button>
        </div>
      )}
      {quit.isError ? <ErrorNotice error={quit.error} /> : null}
    </div>
  );
}
