import { Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRoute } from "@tanstack/react-router";
import { type ReactNode, useEffect, useState } from "react";
import type { NextDirection, NextOut } from "../api/client";
import { keys, useAnswerNext, useChooseNext, useNext, useNextStep, usePath } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { SproutIcon } from "../components/icons";
import { BackLink, Badge, Button, ButtonLink, ChoiceField, Field, Notice, PageHeader, ui, Waiting } from "../components/ui";
import { GenerationError } from "../onboarding/AiReady";
import { useTutorRefs } from "../tutor/context";
import styles from "./nextSteps.module.css";
import { rootRoute } from "./root";

export const nextStepsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/$pathId/next",
  component: NextStepsPage,
});

/** "What next?": questions and a short quiz written for this path, then 2 or 3 directions; the path grows
 * only after the learner confirms one. */
function NextStepsPage() {
  const { pathId } = nextStepsRoute.useParams();
  useTutorRefs({ screen: "tree", path_id: pathId });
  const path = usePath(pathId);
  const next = useNext(pathId);
  const qc = useQueryClient();
  const status = next.data?.status;
  useEffect(() => {
    if (status === "done") void qc.invalidateQueries({ queryKey: keys.path(pathId) });
  }, [status, pathId, qc]);

  const back = (
    <BackLink to="/paths/$pathId" params={{ pathId }}>
      {path.data?.title ?? <Trans id="next.back">Back to the path</Trans>}
    </BackLink>
  );
  return (
    <section className={ui.stack}>
      <PageHeader back={back} title={<Trans id="next.title">What next?</Trans>} />
      {next.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : next.isError ? (
        <ErrorNotice error={next.error} />
      ) : (
        <Checkpoint pathId={pathId} data={next.data} />
      )}
    </section>
  );
}

function Checkpoint({ pathId, data }: { pathId: string; data: NextOut }) {
  const step = useNextStep(pathId);
  const error = step.isError ? <GenerationError error={step.error} /> : null;
  switch (data.status) {
    case "preparing":
    case "proposing":
    case "growing":
      return <Writing pathId={pathId} data={data} />;
    case "ready":
      return <Questions pathId={pathId} data={data} />;
    case "proposed":
      return <Directions pathId={pathId} data={data} />;
    default:
      return (
        <div className={ui.stack}>
          {data.status === "done" && data.added.length > 0 ? (
            <Notice tone="success" role="status" icon={true}>
              <p>
                <Trans id="next.done">Added to your path: {data.added.join(", ")}. The first new lessons are on their way.</Trans>
              </p>
              <p>
                <ButtonLink to="/paths/$pathId" params={{ pathId }} small>
                  <Trans id="next.done.open">Open the path</Trans>
                </ButtonLink>
              </p>
            </Notice>
          ) : null}
          <Intro data={data} />
          {error}
          <div className={ui.row}>
            <Button isDisabled={step.isPending} onPress={() => step.mutate("start")}>
              <Trans id="next.start">Start</Trans>
            </Button>
          </div>
        </div>
      );
  }
}

function Intro({ data }: { data: NextOut }) {
  const d = data.diagnosis;
  const done = d.lessons_done;
  const left = d.lessons_left;
  return (
    <div className={`${ui.card} ${styles.card}`}>
      <div className={styles.heading}>
        <span className={styles.headingIcon} aria-hidden="true">
          <SproutIcon />
        </span>
        <p>
          <Trans id="next.intro">
            Yuo asks you a few questions about where you want to go and gives you a short quiz on what comes next.
            Then it suggests two or three directions. Nothing changes in your path until you choose one.
          </Trans>
        </p>
      </div>
      <h2 className={styles.subtitle}>
        <Trans id="next.so-far">So far</Trans>
      </h2>
      <ul className={styles.facts}>
        <li>
          <Trans id="next.fact.lessons">
            {done} lessons studied, {left} still planned
          </Trans>
        </li>
        {d.finished_branches.length > 0 ? (
          <li>
            <Trans id="next.fact.finished">Finished: {d.finished_branches.join(", ")}</Trans>
          </li>
        ) : null}
        {d.strong.length > 0 ? (
          <li>
            <Trans id="next.fact.strong">Strong: {d.strong.join(", ")}</Trans>
          </li>
        ) : null}
        {d.weak.length > 0 || d.shaky.length > 0 ? (
          <li>
            <Trans id="next.fact.weak">Worth another look: {[...d.weak, ...d.shaky].join(", ")}</Trans>
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function Writing({ pathId, data }: { pathId: string; data: NextOut }) {
  const step = useNextStep(pathId);
  const text: Record<string, ReactNode> = {
    preparing: <Trans id="next.writing.questions">Writing questions for you. This takes about a minute.</Trans>,
    proposing: <Trans id="next.writing.directions">Finding directions that fit your answers…</Trans>,
    growing: <Trans id="next.writing.branches">Adding the new branches to your path…</Trans>,
  };
  if (data.failed) {
    return (
      <div className={ui.stack}>
        <Notice tone="warning" role="alert" icon={true}>
          <Trans id="next.failed">This step could not be finished. Try again, or close the checkpoint for now.</Trans>
        </Notice>
        {step.isError ? <GenerationError error={step.error} /> : null}
        <div className={ui.row}>
          <Button isDisabled={step.isPending} onPress={() => step.mutate("retry")}>
            <Trans id="next.retry">Try again</Trans>
          </Button>
          {data.status !== "growing" ? (
            <Button variant="ghost" isDisabled={step.isPending} onPress={() => step.mutate("dismiss")}>
              <Trans id="next.close">Not now</Trans>
            </Button>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <div className={ui.panel} aria-busy="true">
      <Waiting>{text[data.status]}</Waiting>
    </div>
  );
}

const DONT_KNOW = "dont-know";

function Questions({ pathId, data }: { pathId: string; data: NextOut }) {
  const { t } = useLingui();
  const answer = useAnswerNext(pathId);
  const step = useNextStep(pathId);
  const [quiz, setQuiz] = useState<(string | null)[]>(() => data.quiz.map(() => null));
  const [picks, setPicks] = useState<(string | null)[]>(() => data.questions.map(() => null));
  const [texts, setTexts] = useState<string[]>(() => data.questions.map(() => ""));
  const complete = quiz.every((a) => a !== null);
  const submit = () =>
    answer.mutate({
      quiz: quiz.map((a) => (a === null || a === DONT_KNOW ? null : Number(a))),
      answers: data.questions.map((_, i) => ({
        option: picks[i] === null ? null : Number(picks[i]),
        text: texts[i]?.trim() ?? "",
      })),
    });
  const set = <T,>(xs: T[], i: number, v: T) => xs.map((x, j) => (j === i ? v : x));

  return (
    <form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (complete) submit();
      }}
    >
      <section className={`${ui.card} ${styles.card}`} aria-labelledby="next-where">
        <h2 id="next-where" className={styles.subtitle}>
          <Trans id="next.where.title">Where do you want to go?</Trans>
        </h2>
        <p className={ui.muted}>
          <Trans id="next.where.intro">Pick what fits, or say it in your own words. You can leave any question out.</Trans>
        </p>
        {data.questions.map((q, i) => (
          <div key={i} className={styles.question}>
            <ChoiceField
              label={q.prompt}
              stacked
              choices={q.options.map((o, n) => ({ value: String(n), label: o }))}
              value={picks[i] ?? null}
              onChange={(v) => setPicks(set(picks, i, v))}
              isDisabled={answer.isPending}
            />
            <Field
              label={t({ id: "next.where.own", message: "Or in your own words (optional)" })}
              value={texts[i] ?? ""}
              onChange={(v) => setTexts(set(texts, i, v))}
              maxLength={300}
            />
          </div>
        ))}
      </section>
      <section className={`${ui.card} ${styles.card}`} aria-labelledby="next-quiz">
        <h2 id="next-quiz" className={styles.subtitle}>
          <Trans id="next.quiz.title">A quick look ahead</Trans>
        </h2>
        <p className={ui.muted}>
          <Trans id="next.quiz.intro">
            These go a little beyond what you have studied. “I don’t know yet” is a good answer: it shows where to go.
          </Trans>
        </p>
        {data.quiz.map((q, i) => (
          <div key={i} className={styles.question}>
            {q.topic ? <span className={ui.eyebrow}>{q.topic}</span> : null}
            <ChoiceField
              label={q.prompt}
              stacked
              choices={[
                ...q.options.map((o, n) => ({ value: String(n), label: o })),
                { value: DONT_KNOW, label: t({ id: "next.quiz.dont-know", message: "I don’t know yet" }) },
              ]}
              value={quiz[i] ?? null}
              onChange={(v) => setQuiz(set(quiz, i, v))}
              isDisabled={answer.isPending}
            />
          </div>
        ))}
      </section>
      {answer.isError ? <GenerationError error={answer.error} /> : null}
      <div className={ui.row}>
        <Button type="submit" isDisabled={!complete || answer.isPending}>
          <Trans id="next.submit">See my directions</Trans>
        </Button>
        <Button variant="ghost" isDisabled={answer.isPending || step.isPending} onPress={() => step.mutate("dismiss")}>
          <Trans id="next.close">Not now</Trans>
        </Button>
      </div>
      {!complete ? (
        <p className={ui.muted}>
          <Trans id="next.submit.hint">Answer every quiz question to go on.</Trans>
        </p>
      ) : null}
    </form>
  );
}

function DirectionKind({ kind }: { kind: NextDirection["kind"] }) {
  switch (kind) {
    case "deeper":
      return <Trans id="next.kind.deeper">Go deeper</Trans>;
    case "wider":
      return <Trans id="next.kind.wider">Go wider</Trans>;
    case "apply":
      return <Trans id="next.kind.apply">Put it to use</Trans>;
    case "fix":
      return <Trans id="next.kind.fix">Fix weak spots</Trans>;
  }
}

function Directions({ pathId, data }: { pathId: string; data: NextOut }) {
  const choose = useChooseNext(pathId);
  const step = useNextStep(pathId);
  const [picked, setPicked] = useState<string | null>(null);
  const r = data.quiz_result;
  const busy = choose.isPending || step.isPending;
  return (
    <div className={ui.stack}>
      {r ? (
        <p className={ui.muted}>
          <Trans id="next.quiz.result">
            Quiz: {r.right} of {r.total} right.
          </Trans>{" "}
          {r.ready.length > 0 ? <Trans id="next.quiz.ready">Ready for: {r.ready.join(", ")}.</Trans> : null}
        </p>
      ) : null}
      <h2 className={styles.subtitle}>
        <Trans id="next.directions.title">Choose a direction</Trans>
      </h2>
      <ul className={styles.directions}>
        {data.directions.map((d, i) => (
          <li key={d.code} className={`${ui.card} ${styles.direction}`} data-kind={d.kind}>
            <div className={styles.directionHead}>
              <span className={styles.kind}>
                <DirectionKind kind={d.kind} />
              </span>
              {i === 0 ? (
                <Badge tone="highlight">
                  <Trans id="next.directions.best">Best match</Trans>
                </Badge>
              ) : null}
            </div>
            <h3 className={styles.directionTitle}>{d.title}</h3>
            <p>{d.reason}</p>
            <p className={ui.muted}>
              <Trans id="next.directions.adds">Would add: {d.preview.join(", ")}</Trans>
            </p>
            {picked === d.code ? (
              <div className={styles.confirm} role="group" aria-label={d.title}>
                <p>
                  <Trans id="next.confirm">
                    Add this to your path? New branches are added after the ones you have; your progress stays.
                  </Trans>
                </p>
                <div className={ui.row}>
                  <Button small isDisabled={busy} onPress={() => choose.mutate(d.code)}>
                    <Trans id="next.confirm.yes">Add to my path</Trans>
                  </Button>
                  <Button small variant="ghost" isDisabled={busy} onPress={() => setPicked(null)}>
                    <Trans id="next.confirm.no">Cancel</Trans>
                  </Button>
                </div>
              </div>
            ) : (
              <div>
                <Button small variant="secondary" isDisabled={busy} onPress={() => setPicked(d.code)}>
                  <Trans id="next.choose">Choose this direction</Trans>
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {choose.isError ? <GenerationError error={choose.error} /> : null}
      {step.isError ? <GenerationError error={step.error} /> : null}
      <div className={ui.row}>
        <Button variant="secondary" isDisabled={busy} onPress={() => step.mutate("others")}>
          <Trans id="next.others">None of these fits</Trans>
        </Button>
        <Button variant="ghost" isDisabled={busy} onPress={() => step.mutate("dismiss")}>
          <Trans id="next.close">Not now</Trans>
        </Button>
      </div>
    </div>
  );
}
