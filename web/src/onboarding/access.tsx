// AI access (yuo/app/access.py): an OpenRouter key, the model server on this computer, and the consent
// for a subscription app. Shared by the wizard's "AI access" step and Settings.
import { Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Checkbox, FieldError, Input, Label, Text, TextField } from "react-aria-components";
import { ApiError, type KeyOut, type ProbeOut } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button, Notice, ui } from "../components/ui";
import itemStyles from "../items/items.module.css";
import { LOCAL_DEFAULT_URL, LOCAL_MODEL, useConsentText, useSetLocalServer, useSetOpenRouterKey } from "./api";
import { CONSENT_TEXTS, CONSENT_VERSION } from "./texts";
import styles from "./onboarding.module.css";

const OPENROUTER_KEYS_URL = "https://openrouter.ai/keys";
const OLLAMA_DOWNLOAD_URL = "https://ollama.com/download";

function KeySaved({ info }: { info: KeyOut }) {
  const { i18n } = useLingui();
  const left = info.limit_remaining;
  const credit = left === null ? "" : i18n.number(left, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  return (
    <Notice tone="success" role="status">
      <p>
        <Trans id="access.key.saved">OpenRouter accepted the key. It is saved on this computer and is not shown again.</Trans>
      </p>
      <p>
        {left === null ? (
          <Trans id="access.key.no-limit">This key has no spending limit.</Trans>
        ) : (
          <Trans id="access.key.credit">Credit left on this key: {credit}</Trans>
        )}
      </p>
    </Notice>
  );
}

/** Enter (or replace) the OpenRouter key; it is checked with OpenRouter, then never shown again. */
export function OpenRouterKeyForm({ replacing, onSaved }: { replacing?: boolean; onSaved?: (info: KeyOut) => void }) {
  const { t } = useLingui();
  const save = useSetOpenRouterKey();
  const [key, setKey] = useState("");
  const error = save.error;
  const refused = error instanceof ApiError && error.status === 400;
  const malformed = error instanceof ApiError && error.status === 422;
  const fieldError = refused
    ? t({
        id: "access.key.refused",
        message: "OpenRouter did not accept this key. Check that you copied all of it and that it is still active.",
      })
    : malformed
      ? t({ id: "access.key.format", message: "That does not look like an OpenRouter key. It starts with sk-or-." })
      : undefined;

  return (
    <div className={ui.stack}>
      <form
        className={ui.stack}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const value = key.trim();
          if (!value) return;
          save.mutate(value, {
            onSuccess: (info) => {
              setKey("");
              onSaved?.(info);
            },
          });
        }}
      >
        <p>
          <Trans id="access.key.intro">
            Create a key on OpenRouter's website, then paste it here. Yuo checks it with OpenRouter and keeps it on
            this computer.
          </Trans>{" "}
          <a href={OPENROUTER_KEYS_URL} target="_blank" rel="noopener noreferrer">
            <Trans id="access.key.link">Get a key at openrouter.ai/keys (opens in a new tab)</Trans>
          </a>
        </p>
        <TextField
          type="password"
          value={key}
          onChange={(v) => {
            setKey(v);
            if (save.isError) save.reset();
          }}
          autoComplete="off"
          isInvalid={!!fieldError}
          isRequired
          className={ui.field}
          spellCheck="false"
        >
          <Label className={ui.label}>
            {replacing
              ? t({ id: "access.key.label.replace", message: "New OpenRouter key" })
              : t({ id: "access.key.label", message: "OpenRouter key" })}
          </Label>
          <Input className={ui.input} autoCapitalize="none" autoCorrect="off" />
          <Text slot="description" className={ui.description}>
            {t({ id: "access.key.hint", message: "It starts with sk-or-." })}
          </Text>
          <FieldError className={ui.fieldError}>{fieldError}</FieldError>
        </TextField>
        <div className={ui.row}>
          <Button type="submit" isDisabled={!key.trim() || save.isPending}>
            {save.isPending ? (
              <Trans id="access.key.checking">Checking the key…</Trans>
            ) : (
              <Trans id="access.key.save">Check and save the key</Trans>
            )}
          </Button>
        </div>
      </form>
      {error && !refused && !malformed ? <ErrorNotice error={error} /> : null}
      {save.data ? <KeySaved info={save.data} /> : null}
    </div>
  );
}

/** The model server on this computer: how to get Ollama and the model, without a terminal. */
export function LocalModelSteps({
  probe,
  checking,
  onCheckAgain,
}: {
  probe: ProbeOut;
  checking: boolean;
  onCheckAgain: () => void;
}) {
  const server = probe.servers.find((s) => s.name === "ollama");
  const hasModel = !!server?.models.includes(LOCAL_MODEL);
  const model = LOCAL_MODEL;
  return (
    <div className={ui.stack}>
      {server && hasModel ? (
        <Notice tone="success" role="status">
          <Trans id="access.local.ready">The Ollama app is running and has the model {model}.</Trans>
        </Notice>
      ) : (
        <>
          <p>
            {server ? (
              <Trans id="access.local.no-model">The Ollama app is running, but the model is not there yet.</Trans>
            ) : (
              <Trans id="access.local.no-server">
                To run the model on this computer, Yuo uses the free Ollama app. It is not running yet.
              </Trans>
            )}
          </p>
          <ol className={styles.steps}>
            {server ? null : (
              <>
                <li>
                  <Trans id="access.local.step.install">Download the Ollama app and install it like any other app:</Trans>{" "}
                  <a href={OLLAMA_DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">
                    <Trans id="access.local.step.install.link">ollama.com/download (opens in a new tab)</Trans>
                  </a>
                </li>
                <li>
                  <Trans id="access.local.step.open">Open the Ollama app.</Trans>
                </li>
              </>
            )}
            <li>
              <Trans id="access.local.step.model">
                In the Ollama app, find the model {model} and download it. It is about 18 GB, so this can take a
                while.
              </Trans>
            </li>
            <li>
              <Trans id="access.local.step.check">When the download has finished, come back here and choose Check again.</Trans>
            </li>
          </ol>
        </>
      )}
      <div className={ui.row}>
        <Button variant="secondary" isDisabled={checking} onPress={onCheckAgain}>
          {checking ? (
            <Trans id="access.local.checking">Checking…</Trans>
          ) : (
            <Trans id="access.local.check-again">Check again</Trans>
          )}
        </Button>
      </div>
    </div>
  );
}

/** Connects Yuo to the model server the probe found (PUT /api/setup/access/local). */
export function useConnectLocal() {
  const put = useSetLocalServer();
  return {
    mutation: put,
    connect: (probe: ProbeOut) => {
      const server = probe.servers.find((s) => s.name === "ollama");
      return put.mutateAsync(server?.url ?? LOCAL_DEFAULT_URL);
    },
  };
}

/** The consent text for a subscription app, in the learner's language, with "I agree". */
export function ConsentBox({
  cli,
  agreed,
  onChange,
}: {
  cli: "claude" | "codex";
  agreed: boolean;
  onChange: (v: boolean) => void;
}) {
  const { i18n, t } = useLingui();
  const text = useConsentText(cli);
  // a newer server text than the translated one: show the English original the yes is recorded for
  const body = text.data && text.data.version !== CONSENT_VERSION ? text.data.text : i18n._(CONSENT_TEXTS[cli]);
  return (
    <div className={`${ui.panel} ${ui.stack}`}>
      <h3 className={styles.subTitle}>
        <Trans id="access.consent.title">Before Yuo uses your subscription</Trans>
      </h3>
      <p>{body}</p>
      {text.isError ? <ErrorNotice error={text.error} /> : null}
      <Checkbox className={`${ui.radio} ${itemStyles.checkbox}`} isSelected={agreed} onChange={onChange}>
        {t({ id: "access.consent.agree", message: "I agree" })}
      </Checkbox>
    </div>
  );
}
