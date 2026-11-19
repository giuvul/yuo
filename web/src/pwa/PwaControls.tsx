import { Trans, useLingui } from "@lingui/react/macro";
import { useEffect, useState } from "react";
import { Button as AriaButton, Dialog, Heading, Modal, ModalOverlay } from "react-aria-components";
import { Button, Notice, ui, Waiting } from "../components/ui";
import { serverVersion } from "../onboarding/api";
import { install, shortcutBrowser, useInstallPrompt, useUpdateReady, type ShortcutBrowser } from "./pwa";
import styles from "./pwa.module.css";

/** "Save app shortcut" in the header, only where the browser offers installing (hidden otherwise). */
export function InstallButton({ className }: { className?: string }) {
  const prompt = useInstallPrompt();
  if (!prompt) return null;
  return (
    <AriaButton className={className} onPress={() => void install()}>
      <Trans id="pwa.install">Save app shortcut</Trans>
    </AriaButton>
  );
}

const UPDATED_FLAG = "yuo.updated";
/** If the new worker has not taken over by then (the page was not controlled yet, a stuck worker), load it anyway. */
export const RELOAD_FALLBACK_MS = 5000;

/** A new version is ready: the learner reloads when it suits them (nothing is lost: the outbox keeps events).
 * While it updates the notice says the page reloads by itself; after the reload it says which version runs now. */
export function UpdateNotice() {
  const update = useUpdateReady();
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState<string | null>(null);
  useEffect(() => {
    let flagged = false;
    try {
      flagged = sessionStorage.getItem(UPDATED_FLAG) === "1";
      sessionStorage.removeItem(UPDATED_FLAG);
    } catch {
      // storage blocked: no confirmation, the update itself still works
    }
    if (flagged) void serverVersion().then((v) => setUpdated(v ?? ""));
  }, []);

  if (update) {
    return (
      <div role="status">
        <Notice tone="info">
          {busy ? (
            <Waiting>
              <Trans id="pwa.update.running">Updating Yuo… the page reloads by itself in a moment.</Trans>
            </Waiting>
          ) : (
            <div className={ui.row}>
              <span>
                <Trans id="pwa.update.text">A new version of Yuo is ready.</Trans>
              </span>
              <Button
                small
                onPress={() => {
                  try {
                    sessionStorage.setItem(UPDATED_FLAG, "1");
                  } catch {
                    // see above
                  }
                  setBusy(true);
                  void update();
                  window.setTimeout(() => window.location.reload(), RELOAD_FALLBACK_MS);
                }}
              >
                <Trans id="pwa.update.reload">Reload to update</Trans>
              </Button>
            </div>
          )}
        </Notice>
      </div>
    );
  }
  if (updated === null) return null;
  return (
    <div role="status">
      <Notice tone="success">
        <div className={ui.row}>
          <span>
            {updated ? (
              <Trans id="pwa.update.done.version">Yuo is up to date: version {updated}.</Trans>
            ) : (
              <Trans id="pwa.update.done">Yuo is up to date.</Trans>
            )}
          </span>
          <Button small variant="ghost" onPress={() => setUpdated(null)}>
            <Trans id="pwa.update.done.close">OK</Trans>
          </Button>
        </div>
      </Notice>
    </div>
  );
}

/** How to keep Yuo one click away when the browser does not offer installing by itself (Firefox and Safari never
 * do; Chromium not when it is already installed or the address is not secure). */
export function ShortcutGuide({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useLingui();
  const browser = shortcutBrowser();
  return (
    <ModalOverlay className={styles.overlay} isDismissable isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal className={styles.modal}>
        <Dialog className={styles.dialog} aria-label={t({ id: "pwa.guide.title", message: "Save Yuo as a shortcut" })}>
          {({ close }) => (
            <>
              <Heading slot="title" className={styles.title}>
                <Trans id="pwa.guide.title">Save Yuo as a shortcut</Trans>
              </Heading>
              <GuideSteps browser={browser} />
              <div className={styles.actions}>
                <Button variant="secondary" onPress={close}>
                  <Trans id="pwa.guide.close">Close</Trans>
                </Button>
              </div>
            </>
          )}
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}

function GuideSteps({ browser }: { browser: ShortcutBrowser }) {
  switch (browser) {
    case "firefox":
      return (
        <>
          <p className={ui.muted}>
            <Trans id="pwa.guide.firefox.intro">
              Firefox on a computer cannot save a site as an app. To open Yuo in one click:
            </Trans>
          </p>
          <ol className={styles.steps}>
            <li>
              <Trans id="pwa.guide.firefox.bookmark">
                Bookmark this page with Ctrl+D (⌘D on a Mac) and choose the Bookmarks Toolbar as its folder.
              </Trans>
            </li>
            <li>
              <Trans id="pwa.guide.firefox.pin">
                Or right-click this tab and choose Pin Tab: it opens with Firefox every time.
              </Trans>
            </li>
            <li>
              <Trans id="pwa.guide.firefox.other">
                For an app with its own window and icon, open this same address in Chrome or Edge and choose Save
                app shortcut there.
              </Trans>
            </li>
          </ol>
        </>
      );
    case "firefox-android":
      return (
        <ol className={styles.steps}>
          <li>
            <Trans id="pwa.guide.firefox-android.menu">Open the Firefox menu (⋮).</Trans>
          </li>
          <li>
            <Trans id="pwa.guide.firefox-android.add">Choose Add to Home screen.</Trans>
          </li>
        </ol>
      );
    case "ios":
      return (
        <ol className={styles.steps}>
          <li>
            <Trans id="pwa.guide.ios.share">Tap the Share button (the square with an arrow).</Trans>
          </li>
          <li>
            <Trans id="pwa.guide.ios.add">Choose Add to Home Screen, then Add.</Trans>
          </li>
        </ol>
      );
    case "safari":
      return (
        <ol className={styles.steps}>
          <li>
            <Trans id="pwa.guide.safari.dock">In the menu bar, choose File, then Add to Dock.</Trans>
          </li>
          <li>
            <Trans id="pwa.guide.safari.old">
              No Add to Dock? Safari before version 17 cannot do it: bookmark this page with ⌘D instead.
            </Trans>
          </li>
        </ol>
      );
    case "chromium":
      return (
        <>
          <p className={ui.muted}>
            <Trans id="pwa.guide.chromium.intro">
              The browser did not offer installing right now: Yuo may already be installed, or the address is not
              a secure one (an address like localhost or https works).
            </Trans>
          </p>
          <ol className={styles.steps}>
            <li>
              <Trans id="pwa.guide.chromium.icon">
                Look for the install icon at the right end of the address bar, or open the browser menu and choose
                Install Yuo (in Chrome: Cast, save and share, then Install page as app).
              </Trans>
            </li>
            <li>
              <Trans id="pwa.guide.chromium.bookmark">Otherwise, bookmark this page with Ctrl+D (⌘D on a Mac).</Trans>
            </li>
          </ol>
        </>
      );
    default:
      return (
        <p className={ui.muted}>
          <Trans id="pwa.guide.other">
            Bookmark this page, or use your browser's menu to add it to your home screen or desktop.
          </Trans>
        </p>
      );
  }
}
