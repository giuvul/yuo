// A subscription's program on the machine that runs Yuo (Claude Code, Codex): is it installed, is it signed
// in, and the one next step when it is not (yuo/adapters/cli_access.py). Shown in the wizard after the
// consent, in Settings, and before a path is written, so a missing sign-in is never a failed lesson.
import { Trans, useLingui } from "@lingui/react/macro";
import { useId, useRef, useState, type ReactNode } from "react";
import { Input, Label, TextField } from "react-aria-components";
import type { CliId, CliOut } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { GrowingSprout } from "../components/Grove";
import { AlertIcon, CheckIcon, CodeIcon, KeyIcon } from "../components/icons";
import { Button, MoreOptions, Notice, ui, Waiting } from "../components/ui";
import { useCli, useCliActions } from "./api";
import styles from "./CliAccess.module.css";

/** How a learner opens a shell inside the server's container (the image's service is called `yuo`). */
const CONTAINER_EXEC = "docker compose exec yuo";

export type CliHandlers = {
  onInstall: () => void;
  onLogin: () => void;
  onSendCode: (code: string) => void;
  onCancelLogin: () => void;
  onCheck: () => void;
  /** "Check again" is asking */
  checking?: boolean;
  /** a step was just asked for and its answer is not here yet */
  starting?: boolean;
  /** a request of ours that failed (the server could not be reached, or refused) */
  error?: unknown;
};

/** The program's status from the server, with the steps wired to the API. Nothing when there is nothing to check. */
export function CliAccess({ cli, initial }: { cli: CliId; initial?: CliOut }) {
  const status = useCli(cli, initial);
  const actions = useCliActions(cli);
  if (status.isPending) {
    return (
      <Waiting>
        <Trans id="common.loading">Loading…</Trans>
      </Waiting>
    );
  }
  if (status.isError) return <ErrorNotice error={status.error} />;
  if (!status.data) return null; // this server does not manage the programs
  const failed = [actions.install, actions.login, actions.sendCode, actions.cancelLogin, actions.check].find(
    (m) => m.isError,
  );
  return (
    <CliAccessView
      cli={status.data}
      onInstall={() => actions.install.mutate()}
      onLogin={() => actions.login.mutate()}
      onSendCode={(code) => actions.sendCode.mutate(code)}
      onCancelLogin={() => actions.cancelLogin.mutate()}
      onCheck={() => actions.check.mutate()}
      checking={actions.check.isPending}
      starting={actions.install.isPending || actions.login.isPending || actions.sendCode.isPending}
      error={failed?.error}
    />
  );
}

type Tone = "ready" | "todo" | "busy" | "unknown";

/** The card itself, from a status and handlers (also the static samples on /design). */
export function CliAccessView({ cli: c, ...h }: { cli: CliOut } & CliHandlers) {
  const titleId = useId();
  const name = c.name;
  const installing = !c.installed && c.install.state === "running";
  const login = c.login.state;
  const signingIn =
    c.installed &&
    (login === "running" || login === "waiting_code" || login === "waiting_browser" || login === "waiting_device");

  let tone: Tone;
  let title: ReactNode;
  let body: ReactNode;
  if (!c.installed) {
    tone = installing ? "busy" : "todo";
    title = installing ? (
      <Trans id="cli.state.installing">Installing {name}</Trans>
    ) : (
      <Trans id="cli.state.not-installed">{name} is not installed yet</Trans>
    );
    body = installing ? <Installing /> : <NotInstalled c={c} h={h} />;
  } else if (c.logged_in === true) {
    tone = "ready";
    title = <Trans id="cli.state.ready">{name} is installed and signed in</Trans>;
    body = <ReadyMeta c={c} />;
  } else if (signingIn) {
    tone = "busy";
    title = <Trans id="cli.state.signing-in">Signing in to {name}</Trans>;
    body = <SigningIn c={c} h={h} />;
  } else if (c.logged_in === false) {
    tone = "todo";
    title = <Trans id="cli.state.signed-out">{name} is installed, but not signed in</Trans>;
    body = <SignedOut c={c} h={h} />;
  } else {
    tone = "unknown";
    title = <Trans id="cli.state.installed">{name} is installed</Trans>;
    body = (
      <>
        <Notice>
          <Trans id="cli.unknown.note">
            Yuo could not confirm the sign-in; it will try. If lessons fail, sign in to {name} and check again.
          </Trans>
        </Notice>
        <Manual c={c} h={h} kind="login" quiet />
      </>
    );
  }

  return (
    <section className={styles.card} aria-labelledby={titleId} data-tone={tone} data-testid={`cli-${c.cli}`}>
      <div className={styles.head} aria-live="polite">
        <span className={styles.mark} aria-hidden="true">
          {tone === "ready" ? (
            <CheckIcon />
          ) : !c.installed ? (
            <CodeIcon />
          ) : tone === "busy" ? (
            <GrowingSprout />
          ) : tone === "unknown" ? (
            <AlertIcon />
          ) : (
            <KeyIcon />
          )}
        </span>
        <h3 id={titleId} className={styles.title}>
          {title}
        </h3>
      </div>
      {body}
      {h.error ? <ErrorNotice error={h.error} /> : null}
    </section>
  );
}

function ReadyMeta({ c }: { c: CliOut }) {
  const version = c.version;
  if (!version && !c.account) return null;
  return (
    <p className={styles.meta}>
      {version ? <Trans id="cli.ready.version">Version {version}</Trans> : null}
      {version && c.account ? " · " : null}
      {c.account}
    </p>
  );
}

function Installing() {
  return (
    <div className={ui.panel}>
      <p className={styles.working} role="status">
        <GrowingSprout />
        <span>
          <Trans id="cli.install.running">Installing… this can take a minute.</Trans>
        </span>
      </p>
    </div>
  );
}

function NotInstalled({ c, h }: { c: CliOut; h: CliHandlers }) {
  const { t } = useLingui();
  const name = c.name;
  const failed = c.install.state === "failed";
  return (
    <>
      <p>
        <Trans id="cli.install.why">
          Your subscription works through {name}, a program from its maker that runs on the machine where Yuo runs.
        </Trans>
      </p>
      {failed ? (
        <Notice tone="error" icon={true}>
          <p>
            <Trans id="cli.install.failed">
              The installer did not finish. You can install {name} yourself, see below.
            </Trans>
          </p>
          {c.install.error ? <p className={styles.detail}>{c.install.error}</p> : null}
        </Notice>
      ) : null}
      {c.can_install ? (
        <>
          <div className={ui.row}>
            <Button variant={failed ? "secondary" : undefined} isDisabled={h.starting} onPress={h.onInstall}>
              {failed ? (
                <Trans id="cli.install.retry">Try the installer again</Trans>
              ) : (
                <Trans id="cli.install.start">Install {name}</Trans>
              )}
            </Button>
          </div>
          <MoreOptions
            key={failed ? "open" : "closed"}
            title={t({ id: "cli.manual.title", message: "Do it yourself" })}
            defaultExpanded={failed}
          >
            <Manual c={c} h={h} kind="install" quiet={!failed} />
          </MoreOptions>
        </>
      ) : (
        <Manual c={c} h={h} kind="install" />
      )}
    </>
  );
}

function SignedOut({ c, h }: { c: CliOut; h: CliHandlers }) {
  const { t } = useLingui();
  const name = c.name;
  const failed = c.login.state === "failed";
  return (
    <>
      <p>
        <Trans id="cli.login.why">
          Sign in to {name} with the account that has your subscription. Yuo never sees your password.
        </Trans>
      </p>
      {failed ? (
        <Notice tone="error" icon={true}>
          <p>
            <Trans id="cli.login.failed">The sign-in did not finish. You can start it again.</Trans>
          </p>
          {c.login.error ? <p className={styles.detail}>{c.login.error}</p> : null}
        </Notice>
      ) : null}
      {c.can_login ? (
        <>
          <div className={ui.row}>
            <Button isDisabled={h.starting} onPress={h.onLogin}>
              <Trans id="cli.login.start">Sign in to {name}</Trans>
            </Button>
          </div>
          <MoreOptions title={t({ id: "cli.manual.title", message: "Do it yourself" })}>
            <Manual c={c} h={h} kind="login" quiet />
          </MoreOptions>
        </>
      ) : (
        <Manual c={c} h={h} kind="login" />
      )}
    </>
  );
}

function SigningIn({ c, h }: { c: CliOut; h: CliHandlers }) {
  const { t } = useLingui();
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const state = c.login.state;
  const url = c.login.url && c.login.url.startsWith("https://") ? c.login.url : null;
  const cancel = (
    <Button variant="ghost" small onPress={h.onCancelLogin}>
      <Trans id="cli.login.cancel">Cancel the sign-in</Trans>
    </Button>
  );

  if (state === "waiting_code") {
    return (
      <>
        <ol className={styles.steps}>
          <li>
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer">
                {c.cli === "claude" ? (
                  <Trans id="cli.login.open.claude">Open the Claude sign-in page (opens in a new tab)</Trans>
                ) : (
                  <Trans id="cli.login.open">Open the sign-in page (opens in a new tab)</Trans>
                )}
              </a>
            ) : (
              <Trans id="cli.login.no-link">The sign-in page did not come through. Cancel and start again.</Trans>
            )}
          </li>
          <li>
            <Trans id="cli.login.step.sign-in">Sign in there and allow the access. The page then shows a code.</Trans>
          </li>
          <li>
            <Trans id="cli.login.step.code">Copy the code and paste it here.</Trans>
          </li>
        </ol>
        <form
          className={styles.codeForm}
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            const value = code.trim();
            if (!value) return;
            // the code is used once: out of the field (and the page) as soon as it is sent
            setCode("");
            setSent(true);
            h.onSendCode(value);
          }}
        >
          <TextField value={code} onChange={setCode} className={ui.field} autoComplete="off" spellCheck="false">
            <Label className={ui.label}>
              {t({ id: "cli.login.code.label", message: "Paste the code from that page" })}
            </Label>
            <Input className={ui.input} autoCapitalize="none" autoCorrect="off" />
          </TextField>
          <Button type="submit" isDisabled={!code.trim() || h.starting}>
            <Trans id="cli.login.code.send">Send the code</Trans>
          </Button>
        </form>
        {c.login.error ? (
          <Notice tone="error" icon={true}>
            <p>
              <Trans id="cli.login.code.refused">That code did not work. Copy it again from the sign-in page.</Trans>
            </p>
            <p className={styles.detail}>{c.login.error}</p>
          </Notice>
        ) : null}
        <div className={ui.row}>{cancel}</div>
      </>
    );
  }

  if (state === "waiting_device") {
    // the program gave a one-time code: the learner enters it on the maker's page, and the program goes on
    return (
      <>
        <ol className={styles.steps}>
          <li>
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer">
                <Trans id="cli.login.open">Open the sign-in page (opens in a new tab)</Trans>
              </a>
            ) : (
              <Trans id="cli.login.no-link">The sign-in page did not come through. Cancel and start again.</Trans>
            )}
          </li>
          <li>
            <Trans id="cli.login.device.enter">Sign in there and enter this one-time code when the page asks:</Trans>
            {c.login.code ? (
              <Command text={c.login.code} label={t({ id: "cli.login.device.code", message: "One-time code" })} />
            ) : null}
          </li>
          <li>
            <Trans id="cli.login.device.wait">Come back here. Yuo notices the sign-in and goes on by itself.</Trans>
          </li>
        </ol>
        <div className={ui.panel}>
          <Waiting>
            <Trans id="cli.login.device.waiting">Waiting for you to finish on the sign-in page…</Trans>
          </Waiting>
        </div>
        <p className={styles.after}>
          <Trans id="cli.login.device.hint">
            If the page refuses the code, device sign-in may be switched off for your account. Turn it on in your
            account's security settings, then start the sign-in again.
          </Trans>
        </p>
        <div className={ui.row}>{cancel}</div>
      </>
    );
  }

  return (
    <>
      <div className={ui.panel}>
        <Waiting>
          {state === "waiting_browser" ? (
            <Trans id="cli.login.browser">
              A browser window has opened on this computer. Sign in there; Yuo waits and goes on by itself.
            </Trans>
          ) : sent ? (
            <Trans id="cli.login.checking-code">Checking the code…</Trans>
          ) : (
            <Trans id="cli.login.starting">Starting the sign-in…</Trans>
          )}
        </Waiting>
      </div>
      <div className={ui.row}>{cancel}</div>
    </>
  );
}

/** The manual way: where to run the command, the command with Copy, the maker's guide, and "Check again". */
function Manual({ c, h, kind, quiet }: { c: CliOut; h: CliHandlers; kind: "install" | "login"; quiet?: boolean }) {
  const name = c.name;
  const shell = `${CONTAINER_EXEC} sh`;
  // inside a container the sign-in is one command from outside; the installer is run in a shell inside it
  const login = c.container ? `${CONTAINER_EXEC} ${c.login_command}` : c.login_command;
  const command = kind === "install" ? c.install_command : login;
  return (
    <div className={styles.manual}>
      <p>
        {c.container && kind === "install" ? (
          <Trans id="cli.manual.where.container">
            Run this inside the Yuo container. For example, open a shell in it with <code>{shell}</code>, then run:
          </Trans>
        ) : c.container ? (
          <Trans id="cli.manual.where.container-login">Run this in a terminal on the machine that runs Yuo:</Trans>
        ) : c.os === "windows" ? (
          <Trans id="cli.manual.where.windows">Run this in PowerShell on the computer that runs Yuo:</Trans>
        ) : (
          <Trans id="cli.manual.where.terminal">Run this in a terminal on the computer that runs Yuo:</Trans>
        )}
      </p>
      <Command text={command} />
      <p className={styles.after}>
        {kind === "install" ? (
          <Trans id="cli.manual.after.install">When it has finished, choose Check again.</Trans>
        ) : (
          <Trans id="cli.manual.after.login">When you have signed in, choose Check again.</Trans>
        )}{" "}
        <a href={c.docs_url} target="_blank" rel="noopener noreferrer">
          <Trans id="cli.manual.docs">The {name} guide (opens in a new tab)</Trans>
        </a>
      </p>
      <div className={ui.row}>
        <Button variant={quiet ? "secondary" : undefined} isDisabled={h.checking} onPress={h.onCheck}>
          {h.checking ? (
            <Trans id="cli.check.checking">Checking…</Trans>
          ) : (
            <Trans id="cli.check.again">Check again</Trans>
          )}
        </Button>
      </div>
    </div>
  );
}

/** A command to copy: the clipboard when the browser allows it, else the text is selected to copy by hand. */
function Command({ text, label }: { text: string; label?: string }) {
  const ref = useRef<HTMLElement>(null);
  const [copied, setCopied] = useState<"yes" | "failed" | null>(null);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied("yes");
    } catch {
      selectText(ref.current);
      setCopied("failed");
    }
  };
  return (
    <div className={styles.command}>
      <pre className={styles.commandText} aria-label={label}>
        <code ref={ref}>{text}</code>
      </pre>
      <Button variant="secondary" small onPress={() => void copy()}>
        <Trans id="cli.command.copy">Copy</Trans>
      </Button>
      <p className={styles.copied} role="status" aria-live="polite">
        {copied === "yes" ? (
          <Trans id="cli.command.copied">Copied.</Trans>
        ) : copied === "failed" ? (
          <Trans id="cli.command.copy-failed">
            Copying did not work here. The command is selected: copy it by hand.
          </Trans>
        ) : null}
      </p>
    </div>
  );
}

function selectText(el: HTMLElement | null) {
  if (!el) return;
  try {
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
  } catch {
    // nothing to select with: the text stays readable
  }
}
