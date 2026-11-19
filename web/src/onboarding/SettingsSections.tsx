// Settings sections: your profile, appearance, AI access, updates and, on the
// desktop app, "Stop Yuo".
import type { MessageDescriptor } from "@lingui/core";
import { msg } from "@lingui/core/macro";
import { Trans, useLingui } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { useEffect, useId, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { useSetup } from "../api/hooks";
import { Collapsible, useOpenHashTarget } from "../components/Collapsible";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button, Field, Notice, ui } from "../components/ui";
import { OpenRouterKeyForm } from "./access";
import { CliAccess } from "./CliAccess";
import { PlanMeters } from "./PlanMeter";
import { VendorKeys } from "./vendor";
import { OpenRouterModels } from "./vendorModels";
import {
  serverVersion,
  useAccess,
  useAiReady,
  useCheckForUpdate,
  useDownloadUpdate,
  useMe,
  useProviders,
  useRemoveOpenRouterKey,
  useRestartForUpdate,
  useSetLocalServer,
  useUpdateStatus,
} from "./api";
import { StopYuo } from "./desktop";
import { ProfileForm, ThemePicker } from "./profile";
import styles from "./onboarding.module.css";

function Section({
  title,
  description,
  children,
  id,
}: {
  title: ReactNode;
  description: ReactNode;
  children: ReactNode;
  id: string;
}) {
  return (
    <Collapsible id={id} title={title} description={description}>
      {children}
    </Collapsible>
  );
}

function Loading() {
  return (
    <p className={ui.muted} role="status">
      <Trans id="common.loading">Loading…</Trans>
    </p>
  );
}

// --- profile and appearance -------------------------------------------------------------------------

export function ProfileSection() {
  const me = useMe();
  return (
    <Section
      id="profile"
      title={<Trans id="settings.profile.title">Your profile</Trans>}
      description={<Trans id="settings.profile.description">Name, languages, session length and interests</Trans>}
    >
      {me.isPending ? (
        <Loading />
      ) : me.isError ? (
        <ErrorNotice error={me.error} />
      ) : (
        <ProfileForm me={me.data} submitLabel={<Trans id="settings.profile.save">Save your profile</Trans>} />
      )}
    </Section>
  );
}

export function AppearanceSection() {
  const me = useMe();
  return (
    <Section
      id="appearance"
      title={<Trans id="settings.appearance.title">Appearance</Trans>}
      description={<Trans id="settings.appearance.description">Light, dark or as your system is set</Trans>}
    >
      {me.isPending ? <Loading /> : me.isError ? <ErrorNotice error={me.error} /> : <ThemePicker value={me.data.theme} />}
    </Section>
  );
}

// --- AI access -------------------------------------------------------------------------------------------

const CLI_NAMES: Record<string, string> = { claude: "Claude Code", codex: "Codex" };

const ROLE_NAMES: Record<string, MessageDescriptor> = {
  generator: msg({ id: "settings.ai.role.generator", message: "Writes lessons" }),
  reviewer: msg({ id: "settings.ai.role.reviewer", message: "Checks lessons" }),
  grader: msg({ id: "settings.ai.role.grader", message: "Grades answers" }),
  utility: msg({ id: "settings.ai.role.utility", message: "Small tasks" }),
  tutor: msg({ id: "settings.ai.role.tutor", message: "Tutor" }),
};

/** How a model is reached, after its name in "Models in use". */
const ADAPTER_NAMES: Record<string, string> = {
  "claude-cli": "Claude Code",
  "codex-cli": "Codex",
  openrouter: "OpenRouter",
};
/** Claude Code names a model family; it runs that family's newest version. */
const CLI_ALIASES = new Set(["opus", "sonnet", "haiku"]);

/** The hash targets inside this section that appear only once its data has loaded. */
const LATE_TARGET = /^(cli-[a-z]+|own-keys|openrouter-access)$/;

export function AiAccessSection() {
  const { i18n } = useLingui();
  const access = useAccess();
  const providers = useProviders();
  const setup = useSetup();
  // installed? signed in? A sign-out later is fixed here
  const ready = useAiReady();
  const programs = ready.data?.clis ?? [];
  const bindings = Object.entries(setup.data?.bindings ?? {});
  // "Sign in to Claude Code in Settings" links to the program's card itself, which shows up only after the
  // section's data has loaded (landing on the section's top meant a long scroll)
  const hash = useRouterState({ select: (s) => s.location.hash }).replace(/^#/, "");
  useOpenHashTarget(LATE_TARGET.test(hash) ? hash : "", access.isSuccess && !ready.isPending && !setup.isPending);
  return (
    <Section
      id="ai-access"
      title={<Trans id="settings.ai.title">AI access</Trans>}
      description={
        <Trans id="settings.ai.description">The models that write your lessons, and how Yuo reaches them</Trans>
      }
    >
      <div className={styles.parts}>
        {bindings.length > 0 ? (
          <div className={`${styles.part} ${ui.stack}`}>
            <h3 className={styles.subTitle}>
              <Trans id="settings.ai.models">Models in use</Trans>
            </h3>
            <ul className={`${styles.plainList} ${styles.modelsInUse}`}>
              {bindings.map(([role, b]) => (
                <li key={role}>
                  <strong>{ROLE_NAMES[role] ? i18n._(ROLE_NAMES[role]) : role}:</strong>{" "}
                  <ModelInUse adapter={b["adapter"] ?? ""} model={b["model"] ?? ""} resolved={b["resolved"]} />
                </li>
              ))}
            </ul>
            <p>
              <Link to="/setup">
                <Trans id="settings.ai.change">Change the models that write your lessons</Trans>
              </Link>
            </p>
          </div>
        ) : null}
        {access.isPending ? (
          <Loading />
        ) : access.isError ? (
          <ErrorNotice error={access.error} />
        ) : (
          <>
            <div className={`${styles.part} ${ui.stack}`}>
              <h3 className={styles.subTitle}>
                <Trans id="settings.ai.apps">Subscription apps</Trans>
              </h3>
              {programs.length > 0 ? (
                // the programs the chosen models run through, each with its state and the step to fix it
                <div className={ui.stack} id="ai-programs">
                  {programs.map((c) => (
                    <div key={c.cli} id={`cli-${c.cli}`}>
                      <CliAccess cli={c.cli} initial={c} />
                    </div>
                  ))}
                </div>
              ) : (
                <p>
                  {access.data.clis.length === 0 ? (
                    <Trans id="settings.ai.apps.none">No Claude Code or Codex app was found on this computer.</Trans>
                  ) : (
                    <AppsFound clis={access.data.clis} />
                  )}
                </p>
              )}
              <PlanMeters clis={access.data.clis} />
            </div>
            <div className={styles.part}>
              <Collapsible
                nested
                id="own-keys"
                title={<Trans id="settings.ai.vendors.title">Your own API keys</Trans>}
                description={
                  <Trans id="settings.ai.own-keys.description">
                    OpenRouter, a model vendor or a model app on this computer, instead of a subscription
                  </Trans>
                }
              >
                <div className={styles.parts}>
                  <div className={styles.part} id="openrouter-access">
                    <OpenRouterAccess
                      hasKey={access.data.openrouter}
                      current={{
                        main: openRouterModel(setup.data?.bindings, "generator"),
                        reviewer: openRouterModel(setup.data?.bindings, "reviewer"),
                      }}
                    />
                  </div>
                  {providers.isError ? (
                    <div className={styles.part}>
                      <ErrorNotice error={providers.error} />
                    </div>
                  ) : providers.data && providers.data.length > 0 ? (
                    <div className={styles.part}>
                      <VendorKeys providers={providers.data} />
                    </div>
                  ) : null}
                  <div className={styles.part}>
                    <LocalAccess url={access.data.local_url} connected={access.data.local} />
                  </div>
                </div>
              </Collapsible>
            </div>
          </>
        )}
      </div>
    </Section>
  );
}

/** "claude-opus-5-5 (opus, through Claude Code)": the exact version when a call has named it. */
function ModelInUse({ adapter, model, resolved }: { adapter: string; model: string; resolved?: string | undefined }) {
  const via = ADAPTER_NAMES[adapter];
  if (resolved) {
    return (
      <>
        <span>{resolved}</span>{" "}
        <span className={ui.muted}>
          {via ? (
            <Trans id="settings.ai.model.resolved-via">
              ({model}, through {via})
            </Trans>
          ) : (
            <>({model})</>
          )}
        </span>
      </>
    );
  }
  return (
    <>
      <span>{model}</span>{" "}
      {adapter === "claude-cli" && CLI_ALIASES.has(model) ? (
        <span className={ui.muted}>
          <Trans id="settings.ai.model.alias">
            (the newest version, through Claude Code; the exact one shows here after Yuo first uses it)
          </Trans>
        </span>
      ) : via ? (
        <span className={ui.muted}>
          <Trans id="settings.ai.model.via">(through {via})</Trans>
        </span>
      ) : null}
    </>
  );
}

function AppsFound({ clis }: { clis: string[] }) {
  const apps = clis.map((c) => CLI_NAMES[c] ?? c).join(", ");
  return <Trans id="settings.ai.apps.found">Found on this computer: {apps}</Trans>;
}

/** The model a role uses, when it runs through OpenRouter. */
function openRouterModel(bindings: Record<string, Record<string, string>> | undefined, role: string) {
  const b = bindings?.[role];
  return b && b["adapter"] === "openrouter" ? b["model"] : undefined;
}

function OpenRouterAccess({ hasKey, current }: { hasKey: boolean; current: { main?: string; reviewer?: string } }) {
  const remove = useRemoveOpenRouterKey();
  const writer = current.main;
  const checker = current.reviewer ?? current.main;
  const [choosing, setChoosing] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const confirmId = useId();
  return (
    <div className={ui.stack}>
      <h4 className={styles.partTitle}>OpenRouter</h4>
      {hasKey ? (
        <>
          <p>
            <Trans id="settings.ai.key.set">A key is saved on this computer. It is never shown again.</Trans>
          </p>
          <p className={ui.muted}>
            {writer ? (
              <Trans id="settings.ai.openrouter.in-use">
                In use: {writer} writes, {checker} checks. Any model on OpenRouter can be chosen.
              </Trans>
            ) : (
              <Trans id="settings.ai.openrouter.not-in-use">
                No model runs through OpenRouter now. Choose the models to use this key.
              </Trans>
            )}
          </p>
          {replacing ? (
            <OpenRouterKeyForm replacing onSaved={() => setReplacing(false)} />
          ) : confirming ? (
            <div className={ui.stack} role="group" aria-labelledby={confirmId}>
              <p id={confirmId}>
                <Trans id="settings.ai.key.remove.confirm-text">
                  Remove the key? Models through OpenRouter stop working until you add a key again.
                </Trans>
              </p>
              <div className={ui.row}>
                <Button
                  isDisabled={remove.isPending}
                  onPress={() => remove.mutate(undefined, { onSuccess: () => setConfirming(false) })}
                >
                  <Trans id="settings.ai.key.remove.confirm">Yes, remove the key</Trans>
                </Button>
                <Button variant="secondary" onPress={() => setConfirming(false)}>
                  <Trans id="settings.ai.key.remove.cancel">Keep it</Trans>
                </Button>
              </div>
            </div>
          ) : choosing ? (
            <>
              <OpenRouterModels current={current} />
              <div className={ui.row}>
                <Button variant="secondary" onPress={() => setChoosing(false)}>
                  <Trans id="settings.ai.vendor.close">Close</Trans>
                </Button>
              </div>
            </>
          ) : (
            <div className={ui.row}>
              <Button onPress={() => setChoosing(true)}>
                <Trans id="settings.ai.openrouter.choose">Choose the models</Trans>
              </Button>
              <Button variant="secondary" onPress={() => setReplacing(true)}>
                <Trans id="settings.ai.key.replace">Replace the key</Trans>
              </Button>
              <Button variant="secondary" onPress={() => setConfirming(true)}>
                <Trans id="settings.ai.key.remove">Remove the key</Trans>
              </Button>
            </div>
          )}
          {remove.isError ? <ErrorNotice error={remove.error} /> : null}
        </>
      ) : (
        <>
          <p>
            <Trans id="settings.ai.key.none">No OpenRouter key is saved.</Trans>
          </p>
          <OpenRouterKeyForm />
        </>
      )}
    </div>
  );
}

function LocalAccess({ url, connected }: { url: string | null; connected: boolean }) {
  const { t } = useLingui();
  const put = useSetLocalServer();
  const [draft, setDraft] = useState(url ?? "http://127.0.0.1:11434/v1");
  const invalid = put.error instanceof ApiError && put.error.status === 422;
  return (
    <div className={ui.stack}>
      <h4 className={styles.partTitle}>
        <Trans id="settings.ai.local.title">Model app on this computer</Trans>
      </h4>
      <p>
        {url && connected ? (
          <Trans id="settings.ai.local.connected">Connected to {url}</Trans>
        ) : url ? (
          <Trans id="settings.ai.local.saved">Saved address: {url}. It did not answer since Yuo started.</Trans>
        ) : (
          <Trans id="settings.ai.local.none">No model app on this computer is connected.</Trans>
        )}
      </p>
      <form
        className={ui.stack}
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) put.mutate(draft.trim());
        }}
      >
        <Field
          label={t({ id: "settings.ai.local.url", message: "Address of the model app" })}
          description={t({
            id: "settings.ai.local.url.description",
            message: "The Ollama app on this computer answers at http://127.0.0.1:11434/v1.",
          })}
          value={draft}
          onChange={(v) => {
            setDraft(v);
            put.reset();
          }}
          maxLength={100}
          errorMessage={
            invalid
              ? t({ id: "settings.ai.local.invalid", message: "Use an address on this computer, like http://127.0.0.1:11434/v1." })
              : undefined
          }
        />
        <div className={ui.row}>
          <Button type="submit" variant="secondary" isDisabled={put.isPending || !draft.trim()}>
            {put.isPending ? (
              <Trans id="settings.ai.local.connecting">Connecting…</Trans>
            ) : (
              <Trans id="settings.ai.local.connect">Connect</Trans>
            )}
          </Button>
        </div>
      </form>
      {invalid ? (
        <Notice tone="error">
          <Trans id="settings.ai.local.invalid-notice">That address is not on this computer.</Trans>
        </Notice>
      ) : put.isError ? (
        <ErrorNotice error={put.error} />
      ) : null}
      {put.data ? (
        <Notice tone="success" role="status">
          <LocalModels models={put.data.models} />
        </Notice>
      ) : null}
    </div>
  );
}

function LocalModels({ models }: { models: string[] }) {
  const list = models.join(", ");
  return <Trans id="settings.ai.local.ok">Connected. Models there: {list}</Trans>;
}

// --- updates ---------------------------------------------------------------------------------------------

/** Indirection so tests can watch the reload after a restart. */
export const page = { reload: () => window.location.reload() };
const HEALTH_POLL_MS = 2_000;

export function UpdatesSection() {
  const { i18n } = useLingui();
  const status = useUpdateStatus();
  const check = useCheckForUpdate();
  const download = useDownloadUpdate();
  const restart = useRestartForUpdate();
  const [restarting, setRestarting] = useState(false);
  const current = status.data?.current ?? null;
  const health = useQuery({
    queryKey: ["health", "after-restart"],
    queryFn: serverVersion,
    enabled: restarting,
    refetchInterval: HEALTH_POLL_MS,
    staleTime: 0,
    gcTime: 0,
  });
  const answered = health.data ?? null;

  useEffect(() => {
    if (restarting && answered !== null && answered !== current) page.reload();
  }, [restarting, answered, current]);

  const title = <Trans id="update.title">Updates</Trans>;
  const updatesDescription = <Trans id="update.description">Your version of Yuo and newer ones</Trans>;
  if (status.isPending) {
    return (
      <Section id="updates" title={title} description={updatesDescription}>
        <Loading />
      </Section>
    );
  }
  const noUpdates = status.isError && status.error instanceof ApiError && status.error.status === 404;
  if (status.isError && !noUpdates) {
    return (
      <Section id="updates" title={title} description={updatesDescription}>
        <ErrorNotice error={status.error} />
      </Section>
    );
  }
  if (restarting) {
    return (
      <Section id="updates" title={title} description={updatesDescription}>
        <Notice role="status">
          <Trans id="update.restarting">Yuo is restarting… This page reloads by itself when the new version is ready.</Trans>
        </Notice>
      </Section>
    );
  }

  const s = status.data;
  const version = s?.current ?? "";
  const latest = s?.latest ?? "";
  const published = s?.published_at ? formatDate(s.published_at, i18n) : null;
  const busy = check.isPending || download.isPending || restart.isPending;
  const staged = !!s?.staged && s.staged === s.latest;

  return (
    <Section id="updates" title={title} description={updatesDescription}>
      {s ? (
        <p>
          <Trans id="update.current">You have version {version}.</Trans>
        </p>
      ) : null}
      {!s || !s.feed ? (
        <p className={ui.muted}>
          <Trans id="update.no-feed">This build does not check for updates.</Trans>
        </p>
      ) : (
        <>
          {s.available ? (
            <Notice role="status">
              <p>
                <Trans id="update.available">Version {latest} is available.</Trans>
                {published ? (
                  <>
                    {" "}
                    <Trans id="update.published">Published {published}.</Trans>
                  </>
                ) : null}
              </p>
              {s.notes_url ? (
                <p>
                  <a href={s.notes_url} target="_blank" rel="noopener noreferrer">
                    <Trans id="update.notes">What is new (opens in a new tab)</Trans>
                  </a>
                </p>
              ) : null}
            </Notice>
          ) : s.latest ? (
            <p className={ui.muted}>
              <Trans id="update.newest">This is the newest version.</Trans>
            </p>
          ) : (
            <p className={ui.muted}>
              <Trans id="update.unknown">Yuo has not checked for a newer version yet.</Trans>
            </p>
          )}

          {s.available && !s.can_install ? (
            <p>
              <Trans id="update.container.how">
                To update, in the folder packaging/container set YUO_IMAGE in .env to the new version, then run
                docker compose pull and docker compose up -d.
              </Trans>
            </p>
          ) : null}
          {!s.can_install ? (
            <p className={ui.muted}>
              <Trans id="update.container.restart">
                Yuo runs in Docker here and starts by itself whenever Docker runs. On a computer, turn on “Start
                Docker Desktop when you sign in” in Docker Desktop's settings, so Yuo is there after a restart.
              </Trans>
            </p>
          ) : null}
          {s.available && s.can_install && staged ? (
            <p>
              <Trans id="update.staged">
                The new version is downloaded and checked. Yuo installs it when it restarts, which takes a minute.
              </Trans>
            </p>
          ) : null}

          <div className={ui.row}>
            <Button variant="secondary" isDisabled={busy} onPress={() => check.mutate()}>
              {check.isPending ? <Trans id="update.checking">Checking…</Trans> : <Trans id="update.check">Check now</Trans>}
            </Button>
            {s.available && s.can_install && !staged ? (
              <Button isDisabled={busy} onPress={() => download.mutate()}>
                {download.isPending ? (
                  <Trans id="update.downloading">Downloading…</Trans>
                ) : (
                  <Trans id="update.download">Download</Trans>
                )}
              </Button>
            ) : null}
            {s.available && s.can_install && staged ? (
              <Button isDisabled={busy} onPress={() => restart.mutate(undefined, { onSuccess: () => setRestarting(true) })}>
                <Trans id="update.restart">Restart to install</Trans>
              </Button>
            ) : null}
          </div>
        </>
      )}
      {check.isError ? <ErrorNotice error={check.error} /> : null}
      {download.isError ? <ErrorNotice error={download.error} /> : null}
      {restart.isError ? <ErrorNotice error={restart.error} /> : null}
    </Section>
  );
}

function formatDate(iso: string, i18n: { date: (d: Date, o: Intl.DateTimeFormatOptions) => string }): string | null {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : i18n.date(d, { dateStyle: "medium" });
}

// --- the desktop app ---------------------------------------------------------------------------------

export function DesktopSection() {
  const setup = useSetup();
  if (!setup.data?.desktop) return null;
  return (
    <Section
      id="desktop"
      title={<Trans id="settings.desktop.title">Yuo on this computer</Trans>}
      description={<Trans id="settings.desktop.description">Stop Yuo when you are done</Trans>}
    >
      <StopYuo />
    </Section>
  );
}
