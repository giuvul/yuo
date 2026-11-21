/** Telling the learner about a new release: the banner under the header, the steps for a Docker install (a
 * container cannot pull its own image, so the person or their agent runs two commands on the host), and the
 * wait for the restarted desktop app. Settings > Updates holds the full section (SettingsSections.tsx). */

import { msg } from "@lingui/core/macro";
import { Trans, useLingui } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { UpdateOut } from "../api/client";
import { Button, ButtonLink, Notice, ui, Waiting } from "../components/ui";
import { ErrorNotice } from "../components/ErrorNotice";
import { serverVersion, useDownloadUpdate, useRestartForUpdate, useUpdateStatus } from "./api";
import { Command } from "./CliAccess";
import styles from "./onboarding.module.css";

/** Indirection so tests can watch the reload after a restart. */
export const page = { reload: () => window.location.reload() };
const HEALTH_POLL_MS = 2_000;
/** An open tab learns of a release the server found (it looks after each start and daily). */
const STATUS_POLL_MS = 60 * 60_000;
const DISMISSED_KEY = "yuo.release.dismissed";

/** After "restart to install": poll the server until it answers with another version, then reload. */
export function useReloadAfterRestart(current: string | null) {
  const [restarting, setRestarting] = useState(false);
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
  return { restarting, begin: () => setRestarting(true) };
}

const DOCKER_COMMAND = "docker compose pull && docker compose up -d";

/** The text an AI agent with a shell on the host can follow. Commands stay in English; the rest is translated. */
function useAgentPrompt(latest: string, imageLine: string): string {
  const { i18n } = useLingui();
  return i18n._(
    msg({
      id: "update.agent.prompt",
      message: `Please update my self-hosted Yuo, which runs with Docker Compose, to version ${latest}.

1. Find the folder where Yuo was set up: it has compose.yaml and a .env file with a YUO_IMAGE line (in Yuo's release files it is packaging/container). If you cannot find it, ask me.
2. Show me the current YUO_IMAGE line, then change only that line to: ${imageLine}
3. In that folder run: docker compose pull
   then: docker compose up -d
4. Wait up to 3 minutes until docker compose ps shows the yuo service as healthy, then run: docker compose exec yuo yuo --version
   It should print ${latest}.
5. Tell me what you changed and what came out.

Rules: never run docker compose down -v, docker volume rm or any prune command, and never delete or edit anything in Yuo's data volume: it holds all my learning data, and Yuo backs it up by itself before it moves to a new version. If a step fails, stop, show me the last 100 lines of docker compose logs yuo, and ask me before trying anything else.`,
    }),
  );
}

/** How to update a Docker install, step by step, and the same steps as a prompt for an agent. */
export function ContainerUpdateSteps({ status }: { status: UpdateOut }) {
  const latest = status.latest ?? "";
  const imageLine = status.image ? `YUO_IMAGE=${status.image}` : `YUO_IMAGE=…:${latest}`;
  const prompt = useAgentPrompt(latest, imageLine);
  return (
    <div className={ui.stack}>
      <p>
        <Trans id="update.docker.intro">
          Yuo runs in Docker here, and a program cannot replace the container it runs in, so the update is two
          commands on the computer or server where Yuo runs. It takes a minute or two. Your data stays where it
          is, and Yuo backs it up before it moves to the new version.
        </Trans>
      </p>
      <ol className={styles.steps}>
        <li>
          <Trans id="update.docker.step.folder">
            Open a terminal on that computer and go to the folder you set Yuo up in: the one with compose.yaml
            and .env (in Yuo's release files it is packaging/container).
          </Trans>
        </li>
        <li>
          {status.image ? (
            <Trans id="update.docker.step.image">In .env, change the YUO_IMAGE line to:</Trans>
          ) : (
            <Trans id="update.docker.step.image-version">
              In .env, change the version at the end of the YUO_IMAGE line (after the colon) to {latest}:
            </Trans>
          )}
          <Command text={imageLine} />
        </li>
        <li>
          <Trans id="update.docker.step.pull">Download the new version and restart Yuo with it:</Trans>
          <Command text={DOCKER_COMMAND} />
        </li>
        <li>
          <Trans id="update.docker.step.check">
            After a minute, reload this page: the Updates section in Settings says you have version {latest}.
          </Trans>
        </li>
      </ol>
      <p className={ui.muted}>
        <Trans id="update.docker.careful">
          If something goes wrong, never delete Yuo's data volume (yuo_data): it holds everything you learned.
          The output of docker compose logs --tail 100 yuo says what happened.
        </Trans>
      </p>
      <h3 className={styles.subTitle}>
        <Trans id="update.agent.title">Let an AI agent do it</Trans>
      </h3>
      <p>
        <Trans id="update.agent.intro">
          If you use an agent that can run commands on that computer (Claude Code, Codex or similar), copy this
          and paste it to the agent:
        </Trans>
      </p>
      <Command text={prompt} wrap />
    </div>
  );
}

function dismissed(): string | null {
  try {
    return localStorage.getItem(DISMISSED_KEY);
  } catch {
    return null;
  }
}

/** Under the header when a newer release is out: install it on the desktop, the steps on a server. "Not now"
 * hides it until the next release. */
export function ReleaseNotice() {
  const status = useUpdateStatus({ refetchInterval: STATUS_POLL_MS });
  const download = useDownloadUpdate();
  const restart = useRestartForUpdate();
  const s = status.data;
  const { restarting, begin } = useReloadAfterRestart(s?.current ?? null);
  const [hidden, setHidden] = useState(dismissed);
  if (!s || !s.available || !s.latest || hidden === s.latest) return null;
  const latest = s.latest;
  const busy = download.isPending || restart.isPending;

  const install = async () => {
    if (s.staged !== latest) await download.mutateAsync();
    await restart.mutateAsync();
    begin();
  };
  const notNow = () => {
    try {
      localStorage.setItem(DISMISSED_KEY, latest);
    } catch {
      // storage blocked: hidden until the page loads again
    }
    setHidden(latest);
  };

  return (
    <div role="status">
      <Notice tone="info">
        {restarting ? (
          <Waiting>
            <Trans id="update.banner.restarting">
              Yuo is restarting with version {latest}… This page reloads by itself when it is ready.
            </Trans>
          </Waiting>
        ) : (
          <div className={ui.row}>
            <span>
              {s.can_install ? (
                <Trans id="update.banner.desktop">Yuo {latest} is out. Installing it takes a minute.</Trans>
              ) : (
                <Trans id="update.banner.server">
                  Yuo {latest} is out. Updating takes a minute on the computer where Yuo runs.
                </Trans>
              )}
            </span>
            {s.can_install ? (
              <Button small isDisabled={busy} onPress={() => void install().catch(() => {})}>
                {download.isPending ? (
                  <Trans id="update.downloading">Downloading…</Trans>
                ) : (
                  <Trans id="update.banner.install">Install and restart</Trans>
                )}
              </Button>
            ) : (
              <ButtonLink to="/settings" hash="updates" small>
                <Trans id="update.banner.how">How to update</Trans>
              </ButtonLink>
            )}
            <Button small variant="secondary" isDisabled={busy} onPress={notNow}>
              <Trans id="update.banner.later">Not now</Trans>
            </Button>
          </div>
        )}
        {download.isError ? <ErrorNotice error={download.error} /> : null}
        {restart.isError ? <ErrorNotice error={restart.error} /> : null}
      </Notice>
    </div>
  );
}
