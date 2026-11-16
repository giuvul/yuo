// Sign-in and devices: passkeys and the password (add, remove, change), recovery codes (how many
// are left, make new ones), the devices with a session (this one marked; sign others out) and sign out.
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { createRoute } from "@tanstack/react-router";
import { useId, useState } from "react";
import {
  useAddPasskey,
  useAuthState,
  useCredentials,
  useDevices,
  useNewRecoveryCodes,
  useRemoveCredential,
  useRevokeDevice,
  useSignOut,
  type Credential,
  type Device,
} from "../auth/api";
import { AuthErrorNotice } from "../auth/AuthError";
import { deviceLabel } from "../auth/deviceLabel";
import { PasswordForm } from "../auth/PasswordForm";
import { RecoveryCodes } from "../auth/RecoveryCodes";
import { passkeysSupported } from "../auth/webauthn";
import styles from "../auth/auth.module.css";
import { ConfirmAction } from "../components/ConfirmAction";
import { BackLink, Button, Notice, PageHeader, ui } from "../components/ui";
import { useTutorRefs } from "../tutor/context";
import { rootRoute } from "./root";

export const devicesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings/devices",
  component: DevicesPage,
});

function DevicesPage() {
  useTutorRefs({ screen: "settings" });
  return (
    <section className={ui.stack}>
      <PageHeader
        back={
          <BackLink to="/settings">
            <Trans id="nav.settings">Settings</Trans>
          </BackLink>
        }
        title={<Trans id="devices.title">Sign-in and devices</Trans>}
      />
      <Credentials />
      <Recovery />
      <Devices />
    </section>
  );
}

function useWhen() {
  const { i18n } = useLingui();
  return (at: string) => i18n.date(new Date(at), { dateStyle: "medium", timeStyle: "short" });
}

// --- ways to sign in --------------------------------------------------------------------------------

function Credentials() {
  const { t } = useLingui();
  const list = useCredentials();
  const add = useAddPasskey();
  const [password, setPassword] = useState(false);
  const [saved, setSaved] = useState<"passkey" | "password" | null>(null);
  const headingId = useId();
  const creds = list.data ?? [];
  const hasPassword = creds.some((c) => c.kind === "password");

  return (
    <section className={`${ui.card} ${ui.stack}`} aria-labelledby={headingId}>
      <h2 id={headingId}>
        <Trans id="devices.credentials.title">Ways to sign in</Trans>
      </h2>
      {list.isError ? <AuthErrorNotice error={list.error} step="other" /> : null}
      <ul className={styles.list}>
        {creds.map((c) => (
          <CredentialRow key={c.id} credential={c} only={creds.length === 1} />
        ))}
      </ul>
      <div role="status" aria-live="polite">
        {saved === "passkey" ? (
          <Notice tone="success">
            <Trans id="devices.credentials.passkey-added">Passkey added.</Trans>
          </Notice>
        ) : saved === "password" ? (
          <Notice tone="success">
            <Trans id="devices.credentials.password-saved">Password saved.</Trans>
          </Notice>
        ) : null}
      </div>
      {add.isError ? <AuthErrorNotice error={add.error} step="passkey" /> : null}
      <div className={ui.row}>
        {passkeysSupported() ? (
          <Button
            isDisabled={add.isPending}
            onPress={() => {
              setSaved(null);
              add.mutate(deviceLabel(), { onSuccess: () => setSaved("passkey") });
            }}
          >
            <Trans id="devices.credentials.add-passkey">Add a passkey</Trans>
          </Button>
        ) : null}
        <Button
          variant="secondary"
          aria-expanded={password}
          onPress={() => {
            setSaved(null);
            setPassword((v) => !v);
          }}
        >
          {hasPassword ? (
            <Trans id="devices.credentials.change-password">Change password</Trans>
          ) : (
            <Trans id="devices.credentials.set-password">Set a password</Trans>
          )}
        </Button>
      </div>
      {password ? (
        <PasswordForm
          submitLabel={t({ id: "devices.credentials.password-submit", message: "Save the password" })}
          onSaved={() => {
            setPassword(false);
            setSaved("password");
          }}
        />
      ) : null}
    </section>
  );
}

function CredentialRow({ credential: c, only }: { credential: Credential; only: boolean }) {
  const when = useWhen();
  const remove = useRemoveCredential();
  const label = c.label;
  const added = when(c.created_at);
  const used = c.last_used_at ? when(c.last_used_at) : null;
  return (
    <li className={styles.item}>
      <div className={styles.itemHead}>
        <strong>{label}</strong>
        <span className={styles.badge}>
          {c.kind === "passkey" ? (
            <Trans id="devices.credentials.kind.passkey">Passkey</Trans>
          ) : (
            <Trans id="devices.credentials.kind.password">Password</Trans>
          )}
        </span>
      </div>
      <p className={ui.muted}>
        <Trans id="devices.credentials.added">Added {added}</Trans>
        {" · "}
        {used ? (
          <Trans id="devices.credentials.used">last used {used}</Trans>
        ) : (
          <Trans id="devices.credentials.never-used">not used yet</Trans>
        )}
      </p>
      {only ? (
        <p className={ui.muted}>
          <Trans id="devices.credentials.only">This is your only way to sign in; add another before removing it.</Trans>
        </p>
      ) : (
        <ConfirmAction
          label={<Trans id="devices.credentials.remove">Remove {label}</Trans>}
          groupLabel={label}
          confirmLabel={<Trans id="devices.credentials.remove.confirm">Remove {label} for good</Trans>}
          pending={remove.isPending}
          onConfirm={() => remove.mutate(c.id)}
        />
      )}
      {remove.isError ? <AuthErrorNotice error={remove.error} step="other" /> : null}
    </li>
  );
}

// --- recovery codes -----------------------------------------------------------------------------------

function Recovery() {
  const state = useAuthState();
  const make = useNewRecoveryCodes();
  const [showing, setShowing] = useState(false);
  const headingId = useId();
  const left = state.data?.recovery_codes_left ?? 0;

  return (
    <section className={`${ui.card} ${ui.stack}`} aria-labelledby={headingId}>
      <h2 id={headingId}>
        <Trans id="devices.codes.title">Recovery codes</Trans>
      </h2>
      {showing && make.data ? (
        <RecoveryCodes
          codes={make.data.codes}
          doneLabel={<Trans id="devices.codes.done">Done</Trans>}
          onDone={() => {
            setShowing(false);
            make.reset();
          }}
        />
      ) : (
        <>
          <p>
            <Plural
              id="devices.codes.left"
              value={left}
              _0="No recovery codes left."
              one="# recovery code left."
              other="# recovery codes left."
            />
          </p>
          {left <= 3 ? (
            <Notice tone="warning">
              <Trans id="devices.codes.low">Make new codes so you can still get in if you lose your passkey.</Trans>
            </Notice>
          ) : null}
          {make.isError ? <AuthErrorNotice error={make.error} step="other" /> : null}
          <ConfirmAction
            small={false}
            label={<Trans id="devices.codes.new">Make new recovery codes</Trans>}
            question={
              <Trans id="devices.codes.confirm-text">Your current codes will stop working. Make ten new ones?</Trans>
            }
            confirmLabel={<Trans id="devices.codes.confirm">Make new codes</Trans>}
            pending={make.isPending}
            onConfirm={() => make.mutate(undefined, { onSuccess: () => setShowing(true) })}
          />
        </>
      )}
    </section>
  );
}

// --- devices --------------------------------------------------------------------------------------------

function Devices() {
  const list = useDevices();
  const signOut = useSignOut();
  const [revoked, setRevoked] = useState<string | null>(null);
  const headingId = useId();

  return (
    <section className={`${ui.card} ${ui.stack}`} aria-labelledby={headingId}>
      <h2 id={headingId}>
        <Trans id="devices.list.title">Devices</Trans>
      </h2>
      <p className={ui.muted}>
        <Trans id="devices.list.intro">
          Every browser you signed in with. Signing a device out ends its sessions; it has to sign in again.
        </Trans>
      </p>
      {list.isError ? <AuthErrorNotice error={list.error} step="other" /> : null}
      <div role="status" aria-live="polite">
        {revoked ? (
          <Notice tone="success">
            <Trans id="devices.list.revoked">{revoked} was signed out.</Trans>
          </Notice>
        ) : null}
      </div>
      <ul className={styles.list}>
        {(list.data ?? []).map((d) => (
          <DeviceRow key={d.id} device={d} onRevoked={() => setRevoked(d.label)} onSignOut={() => signOut.mutate()} />
        ))}
      </ul>
      {signOut.isError ? <AuthErrorNotice error={signOut.error} step="other" /> : null}
    </section>
  );
}

function DeviceRow({ device: d, onRevoked, onSignOut }: { device: Device; onRevoked: () => void; onSignOut: () => void }) {
  const when = useWhen();
  const revoke = useRevokeDevice();
  const label = d.label;
  const seen = when(d.last_seen);
  const first = when(d.first_seen);
  return (
    <li className={styles.item} data-current={d.current || undefined}>
      <div className={styles.itemHead}>
        <strong>{label}</strong>
        {d.current ? (
          <span className={styles.badge}>
            <Trans id="devices.list.this">This device</Trans>
          </span>
        ) : null}
      </div>
      <p className={ui.muted}>
        <Trans id="devices.list.seen">Last active {seen} · first signed in {first}</Trans>
      </p>
      {d.user_agent ? <p className={`${ui.muted} ${styles.agent}`}>{d.user_agent}</p> : null}
      {d.current ? (
        <div className={ui.row}>
          <Button small variant="secondary" onPress={onSignOut}>
            <Trans id="devices.list.sign-out">Sign out of this device</Trans>
          </Button>
        </div>
      ) : (
        <ConfirmAction
          label={<Trans id="devices.list.revoke">Sign out {label}</Trans>}
          groupLabel={label}
          confirmLabel={<Trans id="devices.list.revoke.confirm">Yes, sign out {label}</Trans>}
          pending={revoke.isPending}
          onConfirm={() => revoke.mutate(d.id, { onSuccess: onRevoked })}
        />
      )}
      {revoke.isError ? <AuthErrorNotice error={revoke.error} step="other" /> : null}
    </li>
  );
}
