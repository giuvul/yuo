import { Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { FieldError, Input, Label, Text, TextField } from "react-aria-components";
import { Button, ui } from "../components/ui";
import { useSetPassword } from "./api";
import { AuthErrorNotice } from "./AuthError";

const MIN_PASSWORD = 10;

type SecretFieldProps = {
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
  description?: string;
  errorMessage?: string | null;
  autoFocus?: boolean;
};

/** A password or code input (React Aria TextField) with a label, a hint and an error. */
export function SecretField({ label, value, onChange, autoComplete, description, errorMessage, autoFocus }: SecretFieldProps) {
  return (
    <TextField
      type={autoComplete.includes("password") ? "password" : "text"}
      value={value}
      onChange={onChange}
      autoComplete={autoComplete}
      isInvalid={!!errorMessage}
      isRequired
      autoFocus={autoFocus}
      className={ui.field}
      spellCheck="false"
    >
      <Label className={ui.label}>{label}</Label>
      <Input className={ui.input} autoCapitalize="none" autoCorrect="off" />
      {description ? (
        <Text slot="description" className={ui.description}>
          {description}
        </Text>
      ) : null}
      <FieldError className={ui.fieldError}>{errorMessage}</FieldError>
    </TextField>
  );
}

/** Set (or replace) the password: at least ten characters, typed twice. */
export function PasswordForm({ onSaved, submitLabel }: { onSaved: () => void; submitLabel: string }) {
  const { t } = useLingui();
  const save = useSetPassword();
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [checked, setChecked] = useState(false);

  const tooShort = password.length < MIN_PASSWORD;
  const mismatch = password !== again;

  return (
    <form
      className={ui.stack}
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        setChecked(true);
        if (tooShort || mismatch) return;
        save.mutate(password, {
          onSuccess: () => {
            setPassword("");
            setAgain("");
            setChecked(false);
            onSaved();
          },
        });
      }}
    >
      <SecretField
        label={t({ id: "auth.password.new", message: "New password" })}
        description={t({ id: "auth.password.hint", message: "At least 10 characters. A long phrase is easiest to remember." })}
        value={password}
        onChange={setPassword}
        autoComplete="new-password"
        errorMessage={checked && tooShort ? t({ id: "auth.password.too-short", message: "Use at least 10 characters." }) : null}
      />
      <SecretField
        label={t({ id: "auth.password.again", message: "The same password again" })}
        value={again}
        onChange={setAgain}
        autoComplete="new-password"
        errorMessage={checked && !tooShort && mismatch ? t({ id: "auth.password.mismatch", message: "The two passwords differ." }) : null}
      />
      {save.isError ? <AuthErrorNotice error={save.error} step="other" /> : null}
      <div className={ui.row}>
        <Button type="submit" isDisabled={save.isPending}>
          {submitLabel}
        </Button>
      </div>
      {save.isPending ? (
        <p className={ui.muted} role="status">
          <Trans id="auth.password.saving">Saving…</Trans>
        </p>
      ) : null}
    </form>
  );
}
