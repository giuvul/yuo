import { Plural, Trans } from "@lingui/react/macro";
import { ErrorNotice } from "../components/ErrorNotice";
import { Notice } from "../components/ui";
import { AuthApiError } from "./api";
import { wasCancelled } from "./webauthn";

type AuthStep = "setup-code" | "password" | "recovery" | "passkey" | "other";

/** A refused sign-in step in plain words. Throttling says when to try again and that passkeys still work. */
export function AuthErrorNotice({ error, step }: { error: unknown; step: AuthStep }) {
  if (wasCancelled(error)) {
    return (
      <Notice tone="warning" role="alert">
        <Trans id="auth.error.passkey-cancelled">
          The passkey prompt was closed or timed out. Nothing was changed; you can try again.
        </Trans>
      </Notice>
    );
  }
  if (error instanceof DOMException) {
    const name = error.name;
    return (
      <Notice tone="error" icon={true}>
        <Trans id="auth.error.passkey-browser">This browser could not use a passkey here ({name}).</Trans>
      </Notice>
    );
  }
  if (error instanceof AuthApiError && error.status === 429) {
    const minutes = Math.max(1, Math.ceil((error.retryAfter ?? 900) / 60));
    return (
      <Notice tone="error" icon={true}>
        <Plural
          id="auth.error.throttled"
          value={minutes}
          one="Too many wrong attempts. Try again in # minute. Signing in with a passkey still works."
          other="Too many wrong attempts. Try again in # minutes. Signing in with a passkey still works."
        />
      </Notice>
    );
  }
  if (error instanceof AuthApiError && error.status === 400) {
    switch (step) {
      case "setup-code":
        return (
          <Notice tone="error" icon={true}>
            <Trans id="auth.error.setup-code">
              That setup code does not work. Codes work once and expire after a day; the server prints a new one when
              it starts.
            </Trans>
          </Notice>
        );
      case "password":
        return (
          <Notice tone="error" icon={true}>
            <Trans id="auth.error.password">Wrong password.</Trans>
          </Notice>
        );
      case "recovery":
        return (
          <Notice tone="error" icon={true}>
            <Trans id="auth.error.recovery">That recovery code is not valid or was already used.</Trans>
          </Notice>
        );
      default: {
        const detail = error.message;
        return (
          <Notice tone="error" icon={true}>
            <Trans id="auth.error.refused">That did not work: {detail}</Trans>
          </Notice>
        );
      }
    }
  }
  return <ErrorNotice error={error} />;
}
