// First run: the one-time setup code from the server's console signs in, then the learner adds a
// passkey (or a password where passkeys are unavailable) and keeps ten recovery codes.
import { LogoMark } from "../components/Logo";
import { Trans, useLingui } from "@lingui/react/macro";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";
import { Button, Notice, ui } from "../components/ui";
import { useAddPasskey, useNewRecoveryCodes, useRedeemSetupCode, type AuthState } from "./api";
import { AuthErrorNotice } from "./AuthError";
import { deviceLabel } from "./deviceLabel";
import { PasswordForm, SecretField } from "./PasswordForm";
import { RecoveryCodes } from "./RecoveryCodes";
import { setupWizard } from "./session";
import { passkeysSupported } from "./webauthn";
import styles from "./auth.module.css";

type Step = "code" | "credential" | "password" | "codes";

export function SetupFlow({ state }: { state: AuthState }) {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(state.signed_in ? "credential" : "code");
  const number = step === "code" ? 1 : step === "codes" ? 3 : 2;
  const headingId = useId();

  useEffect(() => {
    setupWizard.set(true);
  }, []);

  const finish = () => {
    setupWizard.set(false);
    void navigate({ to: "/" });
  };

  return (
    <section className={`${ui.stack} ${styles.narrow}`} aria-labelledby={headingId}>
      <span className={styles.mark}>
        <LogoMark size={44} />
      </span>
      <h1 id={headingId} className={ui.pageTitle}>
        <Trans id="auth.setup.title">Welcome to Yuo</Trans>
      </h1>
      <p className={styles.tagline}>
        <Trans id="brand.tagline">Learn anything. Grow your skills.</Trans>
      </p>
      <p className={ui.muted}>
        <Trans id="auth.setup.step">Step {number} of 3</Trans>
      </p>
      {step === "code" ? <CodeStep onDone={() => setStep("credential")} /> : null}
      {step === "credential" ? (
        <PasskeyStep onDone={() => setStep("codes")} onPassword={() => setStep("password")} />
      ) : null}
      {step === "password" ? <PasswordStep onDone={() => setStep("codes")} /> : null}
      {step === "codes" ? <CodesStep onDone={finish} /> : null}
    </section>
  );
}

function CodeStep({ onDone }: { onDone: () => void }) {
  const { t } = useLingui();
  const redeem = useRedeemSetupCode();
  const [code, setCode] = useState("");
  return (
    <form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (code.trim()) redeem.mutate(code, { onSuccess: onDone });
      }}
    >
      <p>
        <Trans id="auth.setup.code.intro">
          To make sure this install is yours, type the setup code that the Yuo server printed in its console when it
          started. It looks like ABCD-EFGH-JKLM-NPQR.
        </Trans>
      </p>
      <SecretField
        label={t({ id: "auth.setup.code.label", message: "Setup code" })}
        description={t({
          id: "auth.setup.code.hint",
          message: "Lost it? Run `yuo setup-code` on the server for a new one.",
        })}
        value={code}
        onChange={setCode}
        autoComplete="one-time-code"
        autoFocus
      />
      {redeem.isError ? <AuthErrorNotice error={redeem.error} step="setup-code" /> : null}
      <div className={ui.row}>
        <Button type="submit" isDisabled={redeem.isPending || !code.trim()}>
          <Trans id="auth.setup.code.submit">Continue</Trans>
        </Button>
      </div>
    </form>
  );
}

function PasskeyStep({ onDone, onPassword }: { onDone: () => void; onPassword: () => void }) {
  const add = useAddPasskey();
  if (!passkeysSupported()) return <PasswordStep onDone={onDone} noPasskeys />;
  return (
    <div className={ui.stack}>
      <h2>
        <Trans id="auth.setup.passkey.title">Add a passkey</Trans>
      </h2>
      <p>
        <Trans id="auth.setup.passkey.intro">
          A passkey lets you sign in with this device's fingerprint, face or screen lock. Nothing to remember, and it
          cannot be phished.
        </Trans>
      </p>
      {add.isError ? <AuthErrorNotice error={add.error} step="passkey" /> : null}
      <div className={ui.row}>
        <Button isDisabled={add.isPending} onPress={() => add.mutate(deviceLabel(), { onSuccess: onDone })}>
          <Trans id="auth.setup.passkey.add">Add a passkey</Trans>
        </Button>
        <Button variant="secondary" onPress={onPassword}>
          <Trans id="auth.setup.passkey.use-password">Use a password instead</Trans>
        </Button>
      </div>
      {add.isPending ? (
        <p className={ui.muted} role="status">
          <Trans id="auth.setup.passkey.waiting">Follow your browser's prompt…</Trans>
        </p>
      ) : null}
    </div>
  );
}

function PasswordStep({ onDone, noPasskeys }: { onDone: () => void; noPasskeys?: boolean }) {
  const { t } = useLingui();
  return (
    <div className={ui.stack}>
      <h2>
        <Trans id="auth.setup.password.title">Choose a password</Trans>
      </h2>
      {noPasskeys ? (
        <Notice tone="info">
          <Trans id="auth.setup.password.no-passkeys">
            This browser cannot make passkeys here, so choose a password. You can add a passkey later from another
            device.
          </Trans>
        </Notice>
      ) : null}
      <PasswordForm onSaved={onDone} submitLabel={t({ id: "auth.setup.password.submit", message: "Save the password" })} />
    </div>
  );
}

function CodesStep({ onDone }: { onDone: () => void }) {
  const make = useNewRecoveryCodes();
  const { mutate } = make;
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // once, also under StrictMode: a second call would replace the codes shown
    started.current = true;
    mutate();
  }, [mutate]);
  if (make.data) {
    return (
      <RecoveryCodes
        codes={make.data.codes}
        onDone={onDone}
        doneLabel={<Trans id="auth.setup.done">Continue to Yuo</Trans>}
      />
    );
  }
  if (make.isError) {
    return (
      <div className={ui.stack}>
        <AuthErrorNotice error={make.error} step="other" />
        <div className={ui.row}>
          <Button onPress={() => mutate()}>
            <Trans id="auth.setup.codes.retry">Try again</Trans>
          </Button>
        </div>
      </div>
    );
  }
  return (
    <p className={ui.muted} role="status">
      <Trans id="auth.setup.codes.making">Making your recovery codes…</Trans>
    </p>
  );
}
