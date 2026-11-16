import { Trans, useLingui } from "@lingui/react/macro";
import { useId, useState, type ReactNode } from "react";
import { Checkbox } from "react-aria-components";
import { Button, Notice, ui } from "../components/ui";
import itemStyles from "../items/items.module.css";
import styles from "./auth.module.css";

/** Ten recovery codes, shown once: copy them, confirm they are kept somewhere safe, go on. */
export function RecoveryCodes({ codes, onDone, doneLabel }: { codes: string[]; onDone: () => void; doneLabel: ReactNode }) {
  const { t } = useLingui();
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState<"yes" | "failed" | null>(null);
  const headingId = useId();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      setCopied("yes");
    } catch {
      setCopied("failed");
    }
  };

  return (
    <section className={ui.stack} aria-labelledby={headingId}>
      <h2 id={headingId}>
        <Trans id="auth.codes.title">Your recovery codes</Trans>
      </h2>
      <p>
        <Trans id="auth.codes.intro">
          If you lose your passkey and password, each of these codes signs you in once. They are shown only now: keep
          them somewhere safe, like a password manager or on paper.
        </Trans>
      </p>
      <ol className={styles.codes} aria-label={t({ id: "auth.codes.list", message: "Recovery codes" })}>
        {codes.map((c) => (
          <li key={c} className={styles.code}>
            {c}
          </li>
        ))}
      </ol>
      <div className={ui.row}>
        <Button variant="secondary" onPress={() => void copy()}>
          <Trans id="auth.codes.copy">Copy the codes</Trans>
        </Button>
      </div>
      <div role="status" aria-live="polite">
        {copied === "yes" ? (
          <Notice tone="success">
            <Trans id="auth.codes.copied">Copied.</Trans>
          </Notice>
        ) : copied === "failed" ? (
          <Notice tone="warning">
            <Trans id="auth.codes.copy-failed">Copying did not work here; select the codes and copy them by hand.</Trans>
          </Notice>
        ) : null}
      </div>
      <Checkbox isSelected={saved} onChange={setSaved} className={`${ui.radio} ${itemStyles.checkbox}`}>
        <Trans id="auth.codes.saved">I saved these codes</Trans>
      </Checkbox>
      <div className={ui.row}>
        <Button isDisabled={!saved} onPress={onDone}>
          {doneLabel}
        </Button>
      </div>
    </section>
  );
}
