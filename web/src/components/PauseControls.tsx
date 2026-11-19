// Pausing what Yuo writes ahead (lessons, review questions, videos), to save a subscription or credit for a
// while. A job already in a model call finishes that call first (a video's scene call takes minutes), so the
// card says what is still finishing and how long that step usually takes.
import { Plural, Trans, useLingui as useLinguiMacro } from "@lingui/react/macro";
import { useLingui } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import type { GenerationPause } from "../api/client";
import { usePause, useSetPause } from "../api/hooks";
import { ErrorNotice } from "./ErrorNotice";
import { stepLabel } from "./JobProgress";
import { Button, ChoiceField, Notice, ui } from "./ui";
import styles from "./PauseControls.module.css";

type Scope = "all" | "videos";
type Length = "hour" | "morning" | "resume";

/** When a pause of `length` started now ends, as the API wants it (null: until resumed). */
export function pauseUntil(length: Length, now: Date = new Date()): string | null {
  if (length === "resume") return null;
  if (length === "hour") return new Date(now.getTime() + 3_600_000).toISOString();
  const morning = new Date(now);
  morning.setDate(morning.getDate() + 1);
  morning.setHours(7, 0, 0, 0); // tomorrow at 7 in the learner's own time
  return morning.toISOString();
}

/** The whole control, for the jobs page: choose and pause, or see what waits and resume. */
export function PauseCard() {
  const pause = usePause();
  const set = useSetPause();
  if (!pause.data) return pause.isError ? <ErrorNotice error={pause.error} /> : null;
  return (
    <section className={styles.card} aria-labelledby="pause-title">
      <h2 id="pause-title" className={styles.title}>
        {pause.data.paused ? (
          <Trans id="pause.title.paused">Writing ahead is paused</Trans>
        ) : (
          <Trans id="pause.title">Pause writing ahead</Trans>
        )}
      </h2>
      {pause.data.paused ? (
        <PausedState pause={pause.data} onResume={() => set.mutate({ scope: null, until: null })} busy={set.isPending} />
      ) : (
        <PauseForm onPause={(scope, until) => set.mutate({ scope, until })} busy={set.isPending} />
      )}
      {set.isError ? <ErrorNotice error={set.error} /> : null}
    </section>
  );
}

function PauseForm({ onPause, busy }: { onPause: (scope: Scope, until: string | null) => void; busy: boolean }) {
  const { t } = useLinguiMacro();
  const [scope, setScope] = useState<Scope>("all");
  const [length, setLength] = useState<Length>("resume");
  return (
    <>
      <p className={ui.muted}>
        <Trans id="pause.intro">
          Yuo writes lessons, review questions and videos a little ahead of you. Pause it to save your subscription
          or credit for a while: nothing already written is lost, and it goes on from where it stopped. The tutor,
          grading and anything you start yourself keep working.
        </Trans>
      </p>
      <ChoiceField<Scope>
        label={t({ id: "pause.scope", message: "What to pause" })}
        value={scope}
        onChange={setScope}
        choices={[
          { value: "all", label: t({ id: "pause.scope.all", message: "Lessons, questions and videos" }) },
          { value: "videos", label: t({ id: "pause.scope.videos", message: "Only videos" }) },
        ]}
      />
      <ChoiceField<Length>
        label={t({ id: "pause.length", message: "For how long" })}
        value={length}
        onChange={setLength}
        choices={[
          { value: "hour", label: t({ id: "pause.length.hour", message: "One hour" }) },
          { value: "morning", label: t({ id: "pause.length.morning", message: "Until tomorrow morning" }) },
          { value: "resume", label: t({ id: "pause.length.resume", message: "Until I resume" }) },
        ]}
      />
      <div className={ui.row}>
        <Button isDisabled={busy} onPress={() => onPause(scope, pauseUntil(length))}>
          <Trans id="pause.start">Pause</Trans>
        </Button>
      </div>
    </>
  );
}

function PausedState({ pause, onResume, busy }: { pause: GenerationPause; onResume: () => void; busy: boolean }) {
  const { i18n } = useLingui();
  const until = pause.until ? i18n.date(new Date(pause.until), { weekday: "short", hour: "2-digit", minute: "2-digit" }) : null;
  const n = pause.waiting;
  return (
    <>
      <p>
        {pause.scope === "videos" ? (
          <Trans id="pause.state.videos">Videos wait; lessons and questions keep coming.</Trans>
        ) : (
          <Trans id="pause.state.all">Lessons, review questions and videos wait.</Trans>
        )}{" "}
        {until ? <Trans id="pause.state.until">Until {until}.</Trans> : <Trans id="pause.state.resume">Until you resume.</Trans>}{" "}
        {n > 0 ? <Plural id="pause.state.waiting" value={n} one="# job waits." other="# jobs wait." /> : null}
      </p>
      {pause.finishing.map((f) => (
        <Finishing key={f.job_id} finishing={f} />
      ))}
      <div className={ui.row}>
        <Button isDisabled={busy} onPress={onResume}>
          <Trans id="pause.resume">Resume now</Trans>
        </Button>
      </div>
    </>
  );
}

function Finishing({ finishing: f }: { finishing: GenerationPause["finishing"][number] }) {
  const { i18n } = useLingui();
  const step = stepLabel(f.step, i18n);
  const typical = f.typical_s && f.typical_s >= 60 ? Math.round(f.typical_s / 60) : null;
  const so_far = f.step_s != null && f.step_s >= 60 ? Math.round(f.step_s / 60) : null;
  return (
    <Notice role="status">
      <p>
        {step ? (
          <Trans id="pause.finishing.step">Still finishing one step: {step}.</Trans>
        ) : (
          <Trans id="pause.finishing">Still finishing the step it is in.</Trans>
        )}{" "}
        {typical ? (
          <Plural id="pause.finishing.typical" value={typical} one="It usually takes about # minute" other="It usually takes about # minutes" />
        ) : null}
        {typical && so_far ? (
          <>
            {" "}
            <Plural id="pause.finishing.so-far" value={so_far} one="(# so far)" other="(# so far)" />
          </>
        ) : null}
        {typical ? ". " : null}
        <Trans id="pause.finishing.kept">Then it stops, and what it wrote is kept for when you resume.</Trans>
      </p>
    </Notice>
  );
}

/** A short line where the learner looks first (Home): paused, until when, and the way back. */
export function PauseBanner() {
  const pause = usePause();
  const set = useSetPause();
  const { i18n } = useLingui();
  if (!pause.data?.paused) return null;
  const until = pause.data.until
    ? i18n.date(new Date(pause.data.until), { weekday: "short", hour: "2-digit", minute: "2-digit" })
    : null;
  return (
    <Notice role="status">
      <div className={ui.row}>
        <span>
          {pause.data.scope === "videos" ? (
            <Trans id="pause.banner.videos">Videos are paused.</Trans>
          ) : (
            <Trans id="pause.banner.all">Writing ahead is paused.</Trans>
          )}{" "}
          {until ? <Trans id="pause.state.until">Until {until}.</Trans> : null}{" "}
          <Link to="/jobs">
            <Trans id="pause.banner.details">Details</Trans>
          </Link>
        </span>
        <Button small variant="secondary" isDisabled={set.isPending} onPress={() => set.mutate({ scope: null, until: null })}>
          <Trans id="pause.resume">Resume now</Trans>
        </Button>
      </div>
    </Notice>
  );
}
