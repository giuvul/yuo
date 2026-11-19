import { Trans, useLingui } from "@lingui/react/macro";
import { type ReactNode, useState } from "react";
import { Button as AriaButton } from "react-aria-components";
import type { LevelCheckOut } from "../api/client";
import { useAnswerLevelCheck, useLevelCheck, useRetryLevelCheck } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { QuestionIcon, SproutIcon } from "../components/icons";
import { Button, Notice, Progress, ui, Waiting } from "../components/ui";
import { BlockerText, blockerOf, FixInSettings, GenerationError } from "../onboarding/AiReady";
import { useAiReady } from "../onboarding/api";
import styles from "./levelCheck.module.css";
import { MathText } from "../components/MathText";

/** Before the path is planned: a few questions, one at a time, so the path starts where the learner is. */
export function LevelCheck({ pathId }: { pathId: string }) {
  const check = useLevelCheck(pathId);
  const answer = useAnswerLevelCheck(pathId);
  const retry = useRetryLevelCheck(pathId);
  // why the questions could not be written, when it is the subscription's program (missing, signed out)
  const aiReady = useAiReady(check.data?.failed === true);
  const blocker = check.data?.failed ? blockerOf(aiReady.data) : null;

  if (check.isError) return <ErrorNotice error={check.error} />;
  const data = check.data;
  const skip = (
    <Button variant="ghost" small isDisabled={answer.isPending} onPress={() => answer.mutate({ skip: true })}>
      <Trans id="level-check.skip">Skip it and start from the basics</Trans>
    </Button>
  );

  if (!data || data.status === "preparing") {
    return (
      <section className={styles.card} aria-busy={!data?.failed}>
        <Heading />
        {data?.failed ? (
          blocker ? (
            <Notice tone="warning" role="alert" icon={true}>
              <p>
                <Trans id="level-check.failed.not-ready">The questions could not be written.</Trans>{" "}
                <BlockerText {...blocker} />
              </p>
              <p>
                <FixInSettings {...blocker} />
              </p>
              <p>
                <Trans id="level-check.failed.then-retry">
                  After that, come back and try again, or skip the check: the path then starts from the basics.
                </Trans>
              </p>
            </Notice>
          ) : (
            <Notice tone="warning" role="alert">
              <Trans id="level-check.failed.retry">
                The questions could not be written. Try again, or skip the check: the path then starts from the
                basics.
              </Trans>
            </Notice>
          )
        ) : (
          <div className={ui.panel}>
            <Waiting>
              <Trans id="level-check.preparing">
                Writing a few questions to see where your path should start. This takes about a minute.
              </Trans>
            </Waiting>
          </div>
        )}
        {answer.isError ? <GenerationError error={answer.error} /> : null}
        {retry.isError ? <GenerationError error={retry.error} /> : null}
        <div className={styles.footer}>
          {skip}
          {data?.failed ? (
            <Button small isDisabled={retry.isPending || answer.isPending} onPress={() => retry.mutate()}>
              <Trans id="level-check.retry">Try again</Trans>
            </Button>
          ) : null}
        </div>
      </section>
    );
  }

  if (data.status === "ready") {
    return (
      <Questions
        check={data}
        busy={answer.isPending}
        onDone={(answers) => answer.mutate({ answers })}
        skip={skip}
        error={answer.isError ? <GenerationError error={answer.error} /> : null}
      />
    );
  }

  return null;
}

function Heading() {
  return (
    <div className={styles.heading}>
      <span className={styles.headingIcon}>
        <SproutIcon />
      </span>
      <h2>
        <Trans id="level-check.title">What do you already know?</Trans>
      </h2>
    </div>
  );
}

const LETTERS = "ABCDEFGHIJ";

function Questions({
  check,
  busy,
  onDone,
  skip,
  error,
}: {
  check: LevelCheckOut;
  busy: boolean;
  onDone: (answers: (number | null)[]) => void;
  skip: ReactNode;
  error: ReactNode;
}) {
  const { t } = useLingui();
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const total = check.questions.length;
  const n = answers.length;
  const q = check.questions[n];

  const choose = (value: number | null) => {
    const next = [...answers, value];
    setAnswers(next);
    if (next.length === total) onDone(next);
  };

  if (!q) {
    return (
      <section className={styles.card}>
        <Heading />
        <div className={ui.panel}>
          <Waiting>
            <Trans id="level-check.sending">Saving your answers…</Trans>
          </Waiting>
        </div>
        {error}
      </section>
    );
  }

  const question = n + 1;
  return (
    <section className={styles.card} aria-labelledby="level-check-prompt">
      <Heading />
      <p className={ui.muted}>
        <Trans id="level-check.intro">
          Answer honestly; “I don’t know yet” is a good answer. Your path starts from what you don’t know.
        </Trans>
      </p>
      <div className={styles.progressRow}>
        <p className={styles.counter}>
          <Trans id="level-check.counter">
            Question {question} of {total}
          </Trans>
        </p>
        <Progress
          value={n}
          max={total}
          showValue={false}
          label={t({ id: "level-check.progress", message: "Questions answered" })}
        />
      </div>
      <div className={styles.question} key={n}>
        {q.topic ? <span className={ui.eyebrow}>{q.topic}</span> : null}
        <p id="level-check-prompt" className={styles.prompt}>
          <MathText text={q.prompt} />
        </p>
        <div className={styles.options}>
          {q.options.map((option, i) => (
            <AriaButton key={i} className={styles.option} isDisabled={busy} onPress={() => choose(i)}>
              <span className={styles.letter} aria-hidden="true">
                {LETTERS[i] ?? i + 1}
              </span>
              <span className={styles.optionText}>
                <MathText text={option} />
              </span>
            </AriaButton>
          ))}
          <AriaButton className={`${styles.option} ${styles.dontKnow}`} isDisabled={busy} onPress={() => choose(null)}>
            <span className={styles.letter} aria-hidden="true">
              <QuestionIcon size="1.1rem" />
            </span>
            <span className={styles.optionText}>
              <Trans id="level-check.dont-know">I don’t know yet</Trans>
            </span>
          </AriaButton>
        </div>
      </div>
      {error}
      <div className={styles.footer}>{skip}</div>
    </section>
  );
}
