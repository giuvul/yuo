import { Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRootRoute, Link, Outlet, useNavigate, useRouter, useRouterState } from "@tanstack/react-router";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Button as AriaButton, Menu, MenuItem, MenuTrigger, Popover, Separator } from "react-aria-components";
import { usePutSetting, useSetup } from "../api/hooks";
import { authKeys, useAuthState, useSignOut } from "../auth/api";
import { authRedirect, showsShell } from "../auth/guard";
import { useLaunchSignIn } from "../auth/launch";
import { activateLocale, browserLocale, isDefaultProfile, shippedLocale } from "../i18n";
import { useMe, useOnboarding } from "../onboarding/api";
import { DesktopSignedOut, StoppedScreen, useAppStopped } from "../onboarding/desktop";
import { applyTheme, DARK_QUERY, lastSentScheme, markSchemeSent } from "../theme";
import { onSessionLost, setupWizard } from "../auth/session";
import { Ambient } from "../components/Grove";
import { Logo } from "../components/Logo";
import { ui } from "../components/ui";
import { useOutbox } from "../outbox/context";
import { InstallButton, ShortcutGuide, UpdateNotice } from "../pwa/PwaControls";
import { install, runningInstalled, useInstallPrompt } from "../pwa/pwa";
import { GearIcon, MoreIcon, PathIcon, RepeatIcon, SignOutIcon } from "../components/icons";
import { JobsIndicator, ReviewsBadge } from "../components/HeaderStatus";
import { SyncIndicator } from "../components/SyncIndicator";
import { useTutorState } from "../tutor/context";
import { TutorDock } from "../tutor/Dock";
import styles from "./root.module.css";

export const rootRoute = createRootRoute({
  component: RootLayout,
});

/** Screens a learner can reach before setup is finished (the wizard itself, Settings). */
const OPEN_BEFORE_SETUP = ["/setup", "/settings", "/sign-in", "/design"];

/**
 * Leads to the setup wizard while no models are bound, or while onboarding is not finished and there is
 * no path yet. A learner who already has paths is not sent there (Home offers "finish setting up").
 */
function SetupGate() {
  const setup = useSetup();
  const onboarding = useOnboarding();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const navigate = useNavigate();
  const noModels = setup.data !== undefined && Object.keys(setup.data.bindings).length === 0;
  const notOnboarded = onboarding.data !== undefined && !onboarding.data.done && !onboarding.data.has_path;
  const open = OPEN_BEFORE_SETUP.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  useEffect(() => {
    if ((noModels || notOnboarded) && !open) void navigate({ to: "/setup", replace: true });
  }, [noModels, notOnboarded, open, navigate]);
  return null;
}

/** The learner's theme and UI language from their profile, applied on load and when changed; while the
 * theme follows the device, the device's light or dark look goes to the server for videos. */
function ProfileEffects() {
  const me = useMe();
  const theme = me.data?.theme;
  // until the profile is saved, the browser's language (main.tsx) stays
  const lang = me.data ? (isDefaultProfile(me.data) ? browserLocale() : me.data.ui_lang) : undefined;
  useEffect(() => {
    if (theme) applyTheme(theme);
  }, [theme]);
  const { mutate: putSetting } = usePutSetting();
  useEffect(() => {
    if (theme !== "system" || typeof matchMedia !== "function") return;
    const media = matchMedia(DARK_QUERY);
    const report = () => {
      const scheme = media.matches ? "dark" : "light";
      if (lastSentScheme() === scheme) return;
      putSetting({ key: "ui.device_scheme", value: scheme }, { onSuccess: () => markSchemeSent(scheme) });
    };
    report();
    media.addEventListener("change", report);
    return () => media.removeEventListener("change", report);
  }, [theme, putSetting]);
  useEffect(() => {
    const locale = shippedLocale(lang);
    if (locale) void activateLocale(locale);
  }, [lang]);
  return null;
}

/**
 * The sign-in guard: reads GET /api/auth/state and sends the learner to /setup (fresh install)
 * or /sign-in (no session, keeping where they were going). A 401 anywhere refetches the state. The
 * outbox flushes again once there is a session.
 */
function useAuthGuard() {
  const launch = useLaunchSignIn();
  const auth = useAuthState();
  const wizard = useSyncExternalStore(setupWizard.subscribe, setupWizard.get, setupWizard.get);
  const location = useRouterState({ select: (s) => s.location });
  const router = useRouter();
  const qc = useQueryClient();
  const outbox = useOutbox();
  const state = auth.data;
  const next = (location.search as { next?: unknown }).next;
  const redirect = launch === "signing-in" ? null : authRedirect(state, location, next);
  const target = redirect ? `${redirect.to}${redirect.search?.next ? `?next=${encodeURIComponent(redirect.search.next)}` : ""}` : null;

  useEffect(() => {
    if (target) router.history.replace(target);
  }, [target, router]);

  useEffect(() => onSessionLost(() => void qc.invalidateQueries({ queryKey: authKeys.state })), [qc]);

  const signedIn = state?.signed_in === true;
  const deviceId = state?.device_id ?? null;
  useEffect(() => {
    if (signedIn) void outbox.resume(deviceId);
  }, [signedIn, deviceId, outbox]);

  return {
    ready: !auth.isPending && target === null && launch !== "signing-in",
    shell: !auth.isPending && launch !== "signing-in" && showsShell(state, wizard),
    desktopSignedOut: launch !== "signing-in" && state?.desktop === true && !state.signed_in,
    launchFailed: launch === "failed",
  };
}

function RootLayout() {
  const { t } = useLingui();
  const { ready, shell, desktopSignedOut, launchFailed } = useAuthGuard();
  const tutor = useTutorState();
  const stopped = useAppStopped();
  // the reading screen keeps the background quieter (a lesson, not its practice)
  const reading = useRouterState({ select: (s) => /^\/lessons\/[^/]+\/?$/.test(s.location.pathname) });
  if (stopped) return <StoppedScreen />;
  return (
    <div className={styles.layout} data-dock={tutor.open && shell ? "open" : "closed"}>
    <Ambient quiet={reading} />
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link to="/" className={styles.brand}>
          <Logo label={t({ id: "app.name", message: "Yuo" })} compact />
        </Link>
        {shell ? (
          <>
            <SetupGate />
            <ProfileEffects />
            <nav className={styles.primary} aria-label={t({ id: "nav.main.label", message: "Main" })}>
              <Link to="/paths" className={styles.navLink}>
                <PathIcon className={styles.navIcon} />
                <Trans id="nav.paths">Paths</Trans>
              </Link>
              <ReviewsBadge className={styles.navLink} iconClassName={styles.navIcon} icon={<RepeatIcon />} />
            </nav>
            <div className={styles.utility}>
              <JobsIndicator />
              <SyncIndicator />
              <Link to="/settings" className={styles.iconLink}>
                <GearIcon />
                <span className={styles.iconLinkText}>
                  <Trans id="nav.settings">Settings</Trans>
                </span>
              </Link>
              <MoreMenu />
            </div>
          </>
        ) : (
          <InstallButton className={styles.navButton} />
        )}
      </header>
      <UpdateNotice />
      <main className={styles.main}>
        {desktopSignedOut ? (
          <DesktopSignedOut failed={launchFailed} />
        ) : ready ? (
          <Outlet />
        ) : (
          <p className={ui.muted} role="status">
            <Trans id="common.loading">Loading…</Trans>
          </p>
        )}
      </main>
      <Credit />
    </div>
    {shell ? <TutorDock /> : null}
    </div>
  );
}

const AUTHOR = "Giuseppe Vulduraro";

/** Who made Yuo, at the foot of every screen. */
function Credit() {
  const name = AUTHOR;
  return (
    <footer className={styles.footer}>
      <span>
        <Trans id="footer.made-by">Made by {name}</Trans>
      </span>
      <a href="https://github.com/giuvul" target="_blank" rel="noopener noreferrer">
        GitHub
      </a>
      <a href="https://giuseppevulduraro.com" target="_blank" rel="noopener noreferrer">
        giuseppevulduraro.com
      </a>
    </footer>
  );
}

/** The rarely used actions, out of the main row: setup (until it is finished), the app shortcut, sign out. Models
 * and the profile change in Settings once setup is done. */
function MoreMenu() {
  const { t } = useLingui();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const canInstall = useInstallPrompt() !== null;
  const [guide, setGuide] = useState(false);
  const onboarding = useOnboarding();
  const setupDone = onboarding.data !== undefined && (onboarding.data.done || onboarding.data.has_path);
  return (
    <>
      <MenuTrigger>
        <AriaButton className={styles.menuButton} aria-label={t({ id: "nav.more", message: "More" })}>
          <MoreIcon />
        </AriaButton>
        <Popover className={styles.menuPopover} placement="bottom end">
          <Menu
            className={styles.menu}
            aria-label={t({ id: "nav.more", message: "More" })}
            disabledKeys={signOut.isPending ? ["sign-out"] : []}
            onAction={(key) => {
              if (key === "setup") void navigate({ to: "/setup" });
              else if (key === "install") {
                if (canInstall) void install();
                else setGuide(true);
              } else if (key === "sign-out") signOut.mutate();
            }}
          >
            {setupDone ? null : (
              <MenuItem id="setup" className={styles.menuItem}>
                <Trans id="nav.setup">Setup</Trans>
              </MenuItem>
            )}
            {runningInstalled() ? null : (
              <MenuItem id="install" className={styles.menuItem}>
                <Trans id="pwa.install">Save app shortcut</Trans>
              </MenuItem>
            )}
            <Separator className={styles.menuSeparator} />
            <MenuItem id="sign-out" className={styles.menuItem} textValue={t({ id: "nav.sign-out", message: "Sign out" })}>
              <SignOutIcon />
              <Trans id="nav.sign-out">Sign out</Trans>
            </MenuItem>
          </Menu>
        </Popover>
      </MenuTrigger>
      <ShortcutGuide isOpen={guide} onOpenChange={setGuide} />
    </>
  );
}
