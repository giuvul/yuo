import { Plural, Trans } from "@lingui/react/macro";
import { useOutboxStatus } from "../outbox/context";
import styles from "./SyncIndicator.module.css";

/** "synced / N pending" in the header (shown as synced only once the server has it). */
export function SyncIndicator() {
  const { pending, rejected, offline, syncing, signedOut } = useOutboxStatus();
  const state = pending === 0 ? "synced" : signedOut ? "signed-out" : offline ? "offline" : "pending";
  return (
    <p className={styles.indicator} data-state={state} role="status" aria-live="polite">
      <span className={styles.dot} aria-hidden="true" />
      <span className={styles.text}>
        {pending === 0 ? (
          <Trans id="sync.synced">Synced</Trans>
        ) : (
          <Plural id="sync.pending" value={pending} one="# pending" other="# pending" />
        )}
      </span>
      {pending > 0 && offline && !signedOut ? (
        <span className={styles.extra}>
          <Trans id="sync.offline">offline</Trans>
        </span>
      ) : null}
      {pending > 0 && signedOut ? (
        <span className={styles.extra}>
          <Trans id="sync.signed-out">signed out, kept until you sign in</Trans>
        </span>
      ) : null}
      {pending > 0 && syncing && !offline ? (
        <span className={styles.extra}>
          <Trans id="sync.syncing">syncing</Trans>
        </span>
      ) : null}
      {rejected > 0 ? (
        <span className={styles.extra}>
          <Plural id="sync.rejected" value={rejected} one="# not accepted" other="# not accepted" />
        </span>
      ) : null}
    </p>
  );
}
