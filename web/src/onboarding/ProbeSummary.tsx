// The machine probe in plain words (wizard step "Your computer").
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import type { ProbeOut } from "../api/client";
import { useSetup } from "../api/hooks";
import { VideoUnavailableText } from "../video/unavailable";
import { OS_NAMES, SERVER_NAMES } from "./texts";
import styles from "./onboarding.module.css";

export function ProbeSummary({ probe }: { probe: ProbeOut }) {
  const { t, i18n } = useLingui();
  const setup = useSetup();
  const gb = (v: number) => i18n.number(v, { maximumFractionDigits: v < 10 ? 1 : 0 });
  const os = `${OS_NAMES[probe.os] ?? probe.os} ${probe.os_version}`.trim();
  const memory = probe.memory_gb === null ? null : gb(probe.memory_gb);
  const disk = probe.disk_free_gb === null ? null : gb(probe.disk_free_gb);
  const gflops = probe.bench.cpu_gflops;
  const speed = gflops === null ? null : i18n.number(gflops, { maximumFractionDigits: 0 });
  const unknown = t({ id: "wizard.computer.unknown", message: "Could not be read" });

  const cli = (name: "claude" | "codex") => {
    if (!(name in probe.clis)) return t({ id: "wizard.computer.cli.missing", message: "Not found" });
    const version = probe.clis[name];
    return version
      ? t({ id: "wizard.computer.cli.found-version", message: `Found (version ${version})` })
      : t({ id: "wizard.computer.cli.found", message: "Found" });
  };

  return (
    <dl className={styles.summary}>
      <dt>
        <Trans id="wizard.computer.os">System</Trans>
      </dt>
      <dd>{os}</dd>

      <dt>
        <Trans id="wizard.computer.memory">Memory</Trans>
      </dt>
      <dd>{memory === null ? unknown : <Trans id="wizard.computer.memory.value">{memory} GB</Trans>}</dd>

      <dt>
        <Trans id="wizard.computer.gpu">Graphics card</Trans>
      </dt>
      <dd>
        {probe.gpus.length === 0 ? (
          <Trans id="wizard.computer.gpu.none">None found that can run AI models</Trans>
        ) : (
          <ul className={styles.plainList}>
            {probe.gpus.map((g, i) => {
              const gpu = g.name;
              const vram = g.memory_gb === null ? null : gb(g.memory_gb);
              return (
                <li key={`${g.name}-${i}`}>
                  {g.kind === "apple" ? (
                    <Trans id="wizard.computer.gpu.apple">{gpu}, sharing the computer's memory</Trans>
                  ) : vram === null ? (
                    gpu
                  ) : (
                    <Trans id="wizard.computer.gpu.value">
                      {gpu} with {vram} GB of its own memory
                    </Trans>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </dd>

      <dt>
        <Trans id="wizard.computer.disk">Free disk space</Trans>
      </dt>
      <dd>{disk === null ? unknown : <Trans id="wizard.computer.disk.value">{disk} GB</Trans>}</dd>

      <dt>
        <Trans id="wizard.computer.claude">Claude Code app</Trans>
      </dt>
      <dd>{cli("claude")}</dd>

      <dt>
        <Trans id="wizard.computer.codex">Codex app</Trans>
      </dt>
      <dd>{cli("codex")}</dd>

      <dt>
        <Trans id="wizard.computer.servers">AI model apps on this computer</Trans>
      </dt>
      <dd>
        {probe.servers.length === 0 ? (
          <Trans id="wizard.computer.servers.none">None running</Trans>
        ) : (
          <ul className={styles.plainList}>
            {probe.servers.map((s) => {
              const server = SERVER_NAMES[s.name] ?? s.name;
              const count = s.models.length;
              return (
                <li key={s.name}>
                  {server}:{" "}
                  <Plural id="wizard.computer.server.models" value={count} one="# model" other="# models" />
                </li>
              );
            })}
          </ul>
        )}
      </dd>

      {setup.data ? (
        <>
          <dt>
            <Trans id="wizard.computer.video">Video lessons</Trans>
          </dt>
          <dd>
            {setup.data.video_unavailable ? (
              <VideoUnavailableText reason={setup.data.video_unavailable} desktop={setup.data.desktop} />
            ) : (
              <Trans id="wizard.computer.video.ready">Yuo can make videos here</Trans>
            )}
          </dd>
        </>
      ) : null}

      <dt>
        <Trans id="wizard.computer.speed">Speed test</Trans>
      </dt>
      <dd>
        {speed === null ? (
          <Trans id="wizard.computer.speed.none">Did not run</Trans>
        ) : (
          <Trans id="wizard.computer.speed.value">About {speed} billion calculations a second</Trans>
        )}
      </dd>
    </dl>
  );
}
