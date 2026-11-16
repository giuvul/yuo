// "Can Yuo write right now?" in the places that start generation: a short notice with the way to Settings
// when the chosen subscription's program is missing or signed out (GET /api/setup/ai-ready, 409 ai_not_ready).
import { Trans } from "@lingui/react/macro";
import { Link } from "@tanstack/react-router";
import { isAiNotReady, type AiReadyOut } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { Notice } from "../components/ui";
import { useAiReady } from "./api";
import { CliAccess } from "./CliAccess";
import { CLI_NAMES } from "./texts";
import styles from "./CliAccess.module.css";

type Blocker = { cli: string; reason: string | null };

/** The first program that keeps generation from starting, or null when nothing does. */
export function blockerOf(ready: AiReadyOut | undefined): Blocker | null {
  if (!ready || ready.ready) return null;
  const c = ready.clis.find((x) => !x.ready);
  return c ? { cli: c.cli, reason: c.reason } : null;
}

/** "Sign in to Claude Code in Settings to continue", as a link to that program's card in Settings. */
export function FixInSettings({ cli, reason }: Blocker) {
  const name = CLI_NAMES[cli] ?? cli;
  return (
    <Link to="/settings" hash={`cli-${cli}`}>
      {reason === "not_installed" ? (
        <Trans id="ai-ready.fix.install">Install {name} in Settings to continue</Trans>
      ) : (
        <Trans id="ai-ready.fix.sign-in">Sign in to {name} in Settings to continue</Trans>
      )}
    </Link>
  );
}

/** What is wrong, in one sentence. */
export function BlockerText({ cli, reason }: Blocker) {
  const name = CLI_NAMES[cli] ?? cli;
  return reason === "not_installed" ? (
    <Trans id="ai-ready.what.not-installed">Yuo cannot write right now: {name} is not installed.</Trans>
  ) : (
    <Trans id="ai-ready.what.signed-out">Yuo cannot write right now: {name} is not signed in.</Trans>
  );
}

function AiNotReadyNotice({ cli, reason }: Blocker) {
  return (
    <Notice tone="warning" icon={true} role="alert">
      <p>
        <BlockerText cli={cli} reason={reason} />
      </p>
      <p>
        <FixInSettings cli={cli} reason={reason} />
      </p>
    </Notice>
  );
}

/** A failed generation start: the way to Settings for a missing program or sign-in, else the plain error. */
export function GenerationError({ error }: { error: unknown }) {
  if (isAiNotReady(error)) return <AiNotReadyNotice cli={error.cli ?? "claude"} reason={error.reason} />;
  return <ErrorNotice error={error} />;
}

/** On a page that is not about writing (Home): a small warning while the chosen program is not ready. */
export function AiReadyWarning({ enabled = true }: { enabled?: boolean }) {
  const ready = useAiReady(enabled);
  const blocker = enabled ? blockerOf(ready.data) : null;
  return blocker ? <AiNotReadyNotice {...blocker} /> : null;
}

/** Before a path is written: what is missing, with the program's card to fix it right here. */
export function AiReadyCards({ ready }: { ready: AiReadyOut }) {
  const waiting = ready.clis.filter((c) => !c.ready);
  if (waiting.length === 0) return null;
  return (
    <div className={styles.group}>
      <Notice tone="warning" icon={true}>
        <Trans id="ai-ready.before-path">
          Before Yuo can write your path: the program of your subscription has to be installed and signed in.
        </Trans>
      </Notice>
      {waiting.map((c) => (
        <CliAccess key={c.cli} cli={c.cli} initial={c} />
      ))}
    </div>
  );
}
