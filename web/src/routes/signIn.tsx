// Sign in: a passkey first; a password or a recovery code as the fallbacks.
import { LogoMark } from "../components/Logo";
import { Trans, useLingui } from "@lingui/react/macro";
import { createRoute, useNavigate } from "@tanstack/react-router";
import { useId, useState } from "react";
import { useAuthState, useSignInPasskey, useSignInPassword, useSignInRecovery } from "../auth/api";
import { AuthErrorNotice } from "../auth/AuthError";
import { safeNext } from "../auth/guard";
import { SecretField } from "../auth/PasswordForm";
import { passkeysSupported } from "../auth/webauthn";
import { Button, Notice, ui } from "../components/ui";
import styles from "../auth/auth.module.css";
import { rootRoute } from "./root";

type Search = { next?: string };

export const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sign-in",
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search["next"] === "string" ? { next: search["next"] } : {},
  component: SignInPage,
});

type Mode = "passkey" | "password" | "recovery";

function SignInPage() {
  const { t } = useLingui();
  const { next } = signInRoute.useSearch();
  const navigate = useNavigate();
  const state = useAuthState();
  const hasPasskey = passkeysSupported();
  const methods = state.data?.methods ?? [];
  const [mode, setMode] = useState<Mode>(hasPasskey ? "passkey" : "password");
  const headingId = useId();

  const done = () => void navigate({ to: safeNext(next) ?? "/", replace: true });

  return (
    <section className={`${ui.stack} ${styles.narrow}`} aria-labelledby={headingId}>
      <span className={styles.mark}>
        <LogoMark size={44} />
      </span>
      <h1 id={headingId} className={ui.pageTitle}>
        <Trans id="auth.sign-in.title">Sign in to Yuo</Trans>
      </h1>
      <p className={styles.tagline}>
        <Trans id="brand.tagline">Learn anything. Grow your skills.</Trans>
      </p>
      {mode === "passkey" ? <PasskeySignIn onDone={done} /> : null}
      {mode === "password" ? <PasswordSignIn onDone={done} /> : null}
      {mode === "recovery" ? <RecoverySignIn onDone={done} /> : null}
      {!hasPasskey && methods.length > 0 && !methods.includes("password") ? (
        <Notice tone="info">
          <Trans id="auth.sign-in.no-passkeys">
            This browser cannot use passkeys here and no password is set. Use a recovery code, or sign in on a device
            with your passkey and set a password there.
          </Trans>
        </Notice>
      ) : null}
      <nav className={styles.others} aria-label={t({ id: "auth.sign-in.other", message: "Other ways to sign in" })}>
        {mode !== "passkey" && hasPasskey ? (
          <Button variant="secondary" onPress={() => setMode("passkey")}>
            <Trans id="auth.sign-in.use-passkey">Use a passkey</Trans>
          </Button>
        ) : null}
        {mode !== "password" ? (
          <Button variant="secondary" onPress={() => setMode("password")}>
            <Trans id="auth.sign-in.use-password">Use password</Trans>
          </Button>
        ) : null}
        {mode !== "recovery" ? (
          <Button variant="secondary" onPress={() => setMode("recovery")}>
            <Trans id="auth.sign-in.use-recovery">Use a recovery code</Trans>
          </Button>
        ) : null}
      </nav>
    </section>
  );
}

function PasskeySignIn({ onDone }: { onDone: () => void }) {
  const sign = useSignInPasskey();
  return (
    <div className={ui.stack}>
      <p>
        <Trans id="auth.sign-in.passkey.intro">Use the passkey you made for Yuo on this or another device.</Trans>
      </p>
      {sign.isError ? <AuthErrorNotice error={sign.error} step="passkey" /> : null}
      <div className={ui.row}>
        <Button isDisabled={sign.isPending} onPress={() => sign.mutate(undefined, { onSuccess: onDone })}>
          <Trans id="auth.sign-in.passkey.submit">Sign in with a passkey</Trans>
        </Button>
      </div>
      {sign.isPending ? (
        <p className={ui.muted} role="status">
          <Trans id="auth.sign-in.passkey.waiting">Follow your browser's prompt…</Trans>
        </p>
      ) : null}
    </div>
  );
}

function PasswordSignIn({ onDone }: { onDone: () => void }) {
  const { t } = useLingui();
  const sign = useSignInPassword();
  const [password, setPassword] = useState("");
  return (
    <form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (password) sign.mutate(password, { onSuccess: onDone });
      }}
    >
      <SecretField
        label={t({ id: "auth.sign-in.password.label", message: "Password" })}
        value={password}
        onChange={setPassword}
        autoComplete="current-password"
        autoFocus
      />
      {sign.isError ? <AuthErrorNotice error={sign.error} step="password" /> : null}
      <div className={ui.row}>
        <Button type="submit" isDisabled={sign.isPending || !password}>
          <Trans id="auth.sign-in.password.submit">Sign in</Trans>
        </Button>
      </div>
    </form>
  );
}

function RecoverySignIn({ onDone }: { onDone: () => void }) {
  const { t } = useLingui();
  const sign = useSignInRecovery();
  const [code, setCode] = useState("");
  return (
    <form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (code.trim()) sign.mutate(code, { onSuccess: onDone });
      }}
    >
      <SecretField
        label={t({ id: "auth.sign-in.recovery.label", message: "Recovery code" })}
        description={t({
          id: "auth.sign-in.recovery.hint",
          message: "One of the ten codes you saved. Each works once; make new ones in Sign-in and devices.",
        })}
        value={code}
        onChange={setCode}
        autoComplete="one-time-code"
        autoFocus
      />
      {sign.isError ? <AuthErrorNotice error={sign.error} step="recovery" /> : null}
      <div className={ui.row}>
        <Button type="submit" isDisabled={sign.isPending || !code.trim()}>
          <Trans id="auth.sign-in.recovery.submit">Sign in with the code</Trans>
        </Button>
      </div>
    </form>
  );
}
