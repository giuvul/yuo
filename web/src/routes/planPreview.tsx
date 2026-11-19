import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Form } from "react-aria-components";
import type { PlanTree } from "../api/client";
import { usePreview, usePreviewStep } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { ArrowRightIcon, SproutIcon } from "../components/icons";
import { Button, Field, Notice, ui, Waiting } from "../components/ui";
import { GenerationError } from "../onboarding/AiReady";
import styles from "./planPreview.module.css";

const FEEDBACK_MAX = 2000;

/** Before a path is built: the plan, changed with the learner's own words until it fits, then built. */
export function PlanPreview({ pathId }: { pathId: string }) {
  const { t } = useLingui();
  const preview = usePreview(pathId);
  const step = usePreviewStep(pathId);
  const [text, setText] = useState("");

  if (preview.isError) return <ErrorNotice error={preview.error} />;
  const data = preview.data;

  if (!data || data.status === "drafting" || !data.tree) {
    return (
      <section className={styles.card} aria-busy={!data?.failed}>
        <Heading />
        {data?.failed ? (
          <>
            <Notice tone="warning" role="alert">
              <Trans id="preview.failed">The plan could not be written. Try again in a moment.</Trans>
            </Notice>
            <div className={ui.row}>
              <Button small isDisabled={step.isPending} onPress={() => step.mutate({ step: "retry" })}>
                <Trans id="preview.retry">Try again</Trans>
              </Button>
            </div>
          </>
        ) : (
          <div className={ui.panel}>
            <Waiting>
              <Trans id="preview.drafting">Planning your path. This takes about a minute.</Trans>
            </Waiting>
          </div>
        )}
        {step.isError ? <GenerationError error={step.error} /> : null}
      </section>
    );
  }

  const revising = data.status === "revising";
  const busy = revising || step.isPending;
  return (
    <section className={styles.card} aria-busy={revising && !data.failed}>
      <Heading />
      <p className={ui.muted}>
        <Trans id="preview.intro">
          This is what Yuo will build. Nothing is written yet: tell Yuo what is missing, wrong or should go
          deeper, and it changes the plan. When it fits, build it.
        </Trans>
      </p>

      {data.changes.length > 0 ? (
        <Notice role="status">
          <div className={ui.stack}>
            <strong>
              <Trans id="preview.changed">What changed</Trans>
            </strong>
            <ul className={styles.changes}>
              {data.changes.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
            <div className={ui.row}>
              <Button variant="ghost" small isDisabled={busy} onPress={() => step.mutate({ step: "undo" })}>
                <Trans id="preview.undo">Go back to the previous plan</Trans>
              </Button>
            </div>
          </div>
        </Notice>
      ) : null}

      <Plan tree={data.tree} />

      <Form
        className={styles.feedback}
        onSubmit={(e) => {
          e.preventDefault();
          const value = text.trim();
          if (!value || busy) return;
          step.mutate({ step: "feedback", text: value }, { onSuccess: () => setText("") });
        }}
      >
        <Field
          label={t({ id: "preview.feedback.label", message: "Anything missing, wrong, or that should go deeper?" })}
          description={t({
            id: "preview.feedback.description",
            message: "For example: “add a part on window functions”, “less theory, more exercises”, “drop the history”.",
          })}
          value={text}
          onChange={setText}
          maxLength={FEEDBACK_MAX}
          multiline
          isDisabled={busy}
          name="feedback"
        />
        {revising ? (
          data.failed ? (
            <div className={ui.stack}>
              <Notice tone="warning" role="alert">
                <Trans id="preview.revise-failed">The plan could not be changed. Try again in a moment.</Trans>
              </Notice>
              <div className={ui.row}>
                <Button small isDisabled={step.isPending} onPress={() => step.mutate({ step: "retry" })}>
                  <Trans id="preview.retry">Try again</Trans>
                </Button>
              </div>
            </div>
          ) : (
            <Waiting>
              <Trans id="preview.revising">Changing the plan…</Trans>
            </Waiting>
          )
        ) : null}
        {step.isError ? <GenerationError error={step.error} /> : null}
        <div className={styles.actions}>
          <Button type="submit" variant="secondary" isDisabled={busy || !text.trim()}>
            <Trans id="preview.change">Change the plan</Trans>
          </Button>
          <Button isDisabled={busy} onPress={() => step.mutate({ step: "build" })}>
            <Trans id="preview.build">Build it</Trans>
            <ArrowRightIcon size="1.1em" />
          </Button>
        </div>
      </Form>

      {data.feedback.length > 0 ? (
        <details className={styles.history}>
          <summary>
            <Plural
              id="preview.history"
              value={data.feedback.length}
              one="Your request so far"
              other="Your # requests so far"
            />
          </summary>
          <ol>
            {data.feedback.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ol>
        </details>
      ) : null}
    </section>
  );
}

function Heading() {
  return (
    <div className={styles.heading}>
      <span className={styles.headingIcon}>
        <SproutIcon />
      </span>
      <h2>
        <Trans id="preview.title">Your plan</Trans>
      </h2>
    </div>
  );
}

/** The plan as a readable outline: branches, their skills with summaries, lessons and what comes first. */
export function Plan({ tree }: { tree: PlanTree }) {
  const titles = new Map(tree.branches.flatMap((b) => b.skills.map((s) => [s.code, s.title] as const)));
  const skills = tree.branches.reduce((n, b) => n + b.skills.length, 0);
  const lessons = tree.branches.reduce((n, b) => n + b.skills.reduce((m, s) => m + s.lessons.length, 0), 0);
  const branches = tree.branches.length;
  return (
    <div className={styles.plan}>
      <p className={styles.counts}>
        <Plural id="preview.count.branches" value={branches} one="# branch" other="# branches" />
        {" · "}
        <Plural id="preview.count.skills" value={skills} one="# skill" other="# skills" />
        {" · "}
        <Plural id="preview.count.lessons" value={lessons} one="# lesson" other="# lessons" />
      </p>
      {tree.branches.map((b) => (
        <section key={b.code} className={styles.branch}>
          <h3>{b.title}</h3>
          <ol className={styles.skills}>
            {b.skills.map((s) => {
              const after = s.requires.map((r) => titles.get(r) ?? r).join(", ");
              return (
                <li key={s.code} className={styles.skill}>
                  <span className={styles.skillTitle}>{s.title}</span>
                  <span className={styles.summary}>{s.summary}</span>
                  {s.lessons.length > 1 ? (
                    <ul className={styles.lessons}>
                      {s.lessons.map((l) => (
                        <li key={l.code}>{l.title}</li>
                      ))}
                    </ul>
                  ) : null}
                  {after ? (
                    <span className={styles.after}>
                      <Trans id="preview.after">After: {after}</Trans>
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
