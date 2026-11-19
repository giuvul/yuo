import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Form } from "react-aria-components";
import { ErrorNotice } from "../components/ErrorNotice";
import { ArrowRightIcon, BookIcon } from "../components/icons";
import { Button, Field, Notice, ui, Waiting } from "../components/ui";
import { GenerationError } from "../onboarding/AiReady";
import { isRecording, useAcceptArrangement, useArrange, type Adherence, type CourseOut, type StudiesOut } from "./api";
import { AdherenceField } from "./labels";
import styles from "./material.module.css";

const FEEDBACK_MAX = 2000;

type Proposal = NonNullable<NonNullable<StudiesOut["arrange"]>["proposal"]>;

/**
 * A path started from the learner's files alone: once they are read, Yuo proposes the path's name and how the
 * files split into courses; the learner changes it in their own words, picks how closely each course keeps to
 * its files, and takes it. Nothing else is sent to the AI provider before that.
 */
export function Arrange({ pathId, studies, inbox }: { pathId: string; studies: StudiesOut; inbox: CourseOut }) {
  const arrange = useArrange(pathId);
  const a = studies.arrange!;
  const files = inbox.materials;
  const reading = files.some((m) => !isRecording(m) && (m.state === "uploading" || m.state === "reading"));
  const usable = files.filter((m) => m.state !== "failed" && m.state !== "uploading").length;
  const working = a.status === "working" || arrange.isPending;

  if (working)
    return (
      <div className={styles.card}>
        <Waiting>
          <Trans id="arrange.working">Looking at your files and suggesting the courses…</Trans>
        </Waiting>
      </div>
    );

  const ask = (
    <Button
      variant={a.proposal ? "secondary" : "primary"}
      small={!!a.proposal}
      isDisabled={reading || usable === 0}
      onPress={() => arrange.mutate(null)}
    >
      {a.proposal ? (
        <Trans id="arrange.again">Suggest again</Trans>
      ) : (
        <>
          <Trans id="arrange.ask">Suggest the courses</Trans>
          <ArrowRightIcon size="1.1em" />
        </>
      )}
    </Button>
  );

  return (
    <>
      {a.status === "failed" ? (
        <Notice tone="warning" role="alert">
          <p>
            <Trans id="arrange.failed">The courses could not be suggested. Try again in a moment.</Trans>
          </p>
          {a.error ? <p className={ui.muted}>{a.error}</p> : null}
        </Notice>
      ) : null}
      {a.proposal ? (
        <Suggestion
          key={a.proposal.title + a.proposal.courses.map((c) => c.title).join("|")}
          pathId={pathId}
          proposal={a.proposal}
          newFiles={a.new_files.length}
          ask={ask}
        />
      ) : (
        <div className={styles.card}>
          <p>
            {usable === 0 ? (
              <Trans id="arrange.empty">Add your files above to start.</Trans>
            ) : (
              <Trans id="arrange.intro">
                When all your files are in, Yuo suggests a name for the path and how to split it into courses. You
                can change it in your own words before anything is planned.
              </Trans>
            )}
          </p>
          <div className={styles.buildBar}>
            {reading ? (
              <Waiting>
                <Trans id="studies.start.busy">Waiting for the files to be read…</Trans>
              </Waiting>
            ) : null}
            {ask}
          </div>
        </div>
      )}
      {arrange.isError ? <GenerationError error={arrange.error} /> : null}
    </>
  );
}

function Suggestion({
  pathId,
  proposal,
  newFiles,
  ask,
}: {
  pathId: string;
  proposal: Proposal;
  newFiles: number;
  ask: React.ReactNode;
}) {
  const { t } = useLingui();
  const arrange = useArrange(pathId);
  const accept = useAcceptArrangement(pathId);
  const [title, setTitle] = useState(proposal.title);
  const [adherence, setAdherence] = useState<Adherence[]>(() => proposal.courses.map(() => "grounded"));
  const [text, setText] = useState("");
  const busy = arrange.isPending || accept.isPending;

  return (
    <div className={styles.card}>
      <h2 className={styles.cardTitle}>
        <Trans id="arrange.title">Suggested path</Trans>
      </h2>
      <Notice role="status">{proposal.message}</Notice>
      <Field
        label={t({ id: "arrange.name", message: "Name of the path" })}
        value={title}
        onChange={setTitle}
        maxLength={120}
        name="path-title"
      />
      <ol className={styles.arranged}>
        {proposal.courses.map((c, i) => (
          <li key={c.title} className={styles.arrangedCourse}>
            <div className={styles.courseHead}>
              <span className={styles.headingIcon}>
                <BookIcon />
              </span>
              <div className={styles.courseTitle}>
                <h3>{c.title}</h3>
                {c.term ? <p className={ui.muted}>{c.term}</p> : null}
              </div>
            </div>
            <ul className={styles.arrangedFiles}>
              {c.files.map((f) => (
                <li key={f.id}>{f.title}</li>
              ))}
            </ul>
            <AdherenceField
              value={adherence[i] ?? "grounded"}
              onChange={(v: Adherence) => setAdherence((xs) => xs.map((x, k) => (k === i ? v : x)))}
            />
          </li>
        ))}
      </ol>

      {newFiles > 0 ? (
        <Notice tone="warning" role="status">
          <div className={ui.row}>
            <Plural
              id="arrange.new-files"
              value={newFiles}
              one="# file was added after this suggestion: ask again to place it."
              other="# files were added after this suggestion: ask again to place them."
            />
            {ask}
          </div>
        </Notice>
      ) : null}

      <Form
        className={styles.feedback}
        onSubmit={(e) => {
          e.preventDefault();
          const value = text.trim();
          if (!value || busy) return;
          arrange.mutate(value, { onSuccess: () => setText("") });
        }}
      >
        <Field
          label={t({ id: "arrange.feedback.label", message: "Anything to change?" })}
          description={t({
            id: "arrange.feedback.description",
            message:
              "For example: “the slides and the book are the same course”, “put the exercises in their own course”, “call it Calculus 1”.",
          })}
          value={text}
          onChange={setText}
          maxLength={FEEDBACK_MAX}
          multiline
          isDisabled={busy}
          name="arrange-feedback"
        />
        <div className={styles.actions}>
          <Button type="submit" variant="secondary" small isDisabled={busy || !text.trim()}>
            <Trans id="arrange.change">Change the suggestion</Trans>
          </Button>
        </div>
      </Form>
      {arrange.isError ? <GenerationError error={arrange.error} /> : null}
      {accept.isError ? <ErrorNotice error={accept.error} /> : null}
      <div className={styles.buildBar}>
        <Button
          isDisabled={busy || newFiles > 0 || !title.trim()}
          onPress={() => accept.mutate({ title: title.trim(), adherence })}
        >
          <Trans id="arrange.accept">Use these courses</Trans>
          <ArrowRightIcon size="1.1em" />
        </Button>
      </div>
    </div>
  );
}
