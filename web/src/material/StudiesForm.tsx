import { Trans, useLingui } from "@lingui/react/macro";
import { useState, type ReactNode } from "react";
import { Form } from "react-aria-components";
import { ErrorNotice } from "../components/ErrorNotice";
import { ArrowRightIcon, CloseIcon, PlusIcon } from "../components/icons";
import { Button, Field, Notice, ui, Waiting } from "../components/ui";
import { useCreateStudies, type Adherence } from "./api";
import { handOver } from "./handover";
import { DepthField, type Depth } from "../components/DepthField";
import { AdherenceField } from "./labels";
import { FileDrop } from "./Studies";
import styles from "./material.module.css";

type Row = { key: number; title: string; adherence: Adherence };

const MAX_COURSES = 60;

/**
 * A path from the learner's own material, started from the files alone: the drop zone is right here, and the
 * path is made only when the first files are added (so switching back to "A goal" leaves nothing behind). The
 * upload screen then sends them, and Yuo proposes the path's name and its courses from them.
 */
export function MaterialStart({ onCreated, secondary }: { onCreated: (pathId: string) => void; secondary?: ReactNode }) {
  const { t } = useLingui();
  const create = useCreateStudies();
  const [depth, setDepth] = useState<Depth>("standard");
  const start = (files: File[]) =>
    create.mutate(
      { title: "", goal: "", courses: [], depth },
      {
        onSuccess: (r) => {
          handOver(r.path_id, files);
          onCreated(r.path_id);
        },
      },
    );
  return (
    <div className={ui.stack}>
      <p className={ui.muted}>
        <Trans id="arrange.collect.intro">
          Drop everything you study from, for every course: books and notes as PDF, slides, Word or text
          documents, exercises, past exams and recordings. Yuo reads them on this computer first, for free,
          then suggests a name for the path and how to split it into courses.
        </Trans>
      </p>
      <DepthField value={depth} onChange={setDepth} material isDisabled={create.isPending} />
      <FileDrop
        label={t({ id: "studies.drop.label", message: "Drop your material here" })}
        onFiles={start}
        isDisabled={create.isPending}
      />
      {create.isPending ? (
        <Waiting>
          <Trans id="studies.opening">Opening the upload…</Trans>
        </Waiting>
      ) : null}
      <Notice role="note">
        <Trans id="studies.responsibility">
          Upload only material you may use for your own study. Yuo keeps it on this installation and sends the
          parts it needs to your AI provider; what you upload is your responsibility.
        </Trans>
      </Notice>
      {create.isError ? <ErrorNotice error={create.error} /> : null}
      {secondary ? <div className={ui.row}>{secondary}</div> : null}
    </div>
  );
}

/**
 * A path from the learner's own material: what it is about (e.g. "Mechanical Engineering", one path so courses
 * can build on each other) and its courses, which may be university courses, exams, books or topics. Files are added on the next screen.
 */
export function StudiesForm({ onCreated, secondary }: { onCreated: (pathId: string) => void; secondary?: ReactNode }) {
  const { t } = useLingui();
  const create = useCreateStudies();
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [rows, setRows] = useState<Row[]>([{ key: 0, title: "", adherence: "grounded" }]);
  const [next, setNext] = useState(1);

  const change = (key: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const filled = rows.filter((r) => r.title.trim());

  return (
    <Form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (!filled.length) return;
        create.mutate(
          {
            title: title.trim(),
            goal: goal.trim(),
            depth: "standard",
            courses: filled.map((r) => ({
              title: r.title.trim(),
              adherence: r.adherence,
              keep_order: true,
            })),
          },
          { onSuccess: (r) => onCreated(r.path_id) },
        );
      }}
    >
      <Field
        label={t({ id: "studies.field.title", message: "What you study" })}
        description={t({
          id: "studies.field.title.description",
          message:
            "What the path is about, e.g. “Mechanical Engineering” or “Personal finance”: one path, so its courses can build on each other.",
        })}
        value={title}
        onChange={setTitle}
        isRequired
        maxLength={120}
        name="title"
      />
      <Field
        label={t({ id: "studies.field.goal", message: "Your goal (optional)" })}
        description={t({ id: "studies.field.goal.description", message: "For example: pass my exams, or understand these books." })}
        value={goal}
        onChange={setGoal}
        maxLength={600}
        name="goal"
      />

      <fieldset className={styles.courses}>
        <legend className={styles.legend}>
          <Trans id="studies.courses">Courses</Trans>
        </legend>
        <p className={ui.muted}>
          <Trans id="studies.courses.intro">
            Each course becomes a branch of the path: a university course, an exam, a book or a topic. You add
            its books, slides, notes and recordings next.
          </Trans>
        </p>
        {rows.map((r, i) => (
          <div key={r.key} className={styles.courseRow}>
            <div className={styles.courseFields}>
              <Field
                label={t({ id: "studies.course.name", message: "Course" })}
                value={r.title}
                onChange={(v) => change(r.key, { title: v })}
                maxLength={120}
                isRequired={i === 0}
                name={`course-${r.key}`}
              />
            </div>
            <AdherenceField value={r.adherence} onChange={(v) => change(r.key, { adherence: v })} />
            {rows.length > 1 ? (
              <div className={ui.row}>
                <Button
                  variant="ghost"
                  small
                  onPress={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
                  aria-label={t({ id: "studies.course.remove.label", message: `Remove ${r.title || "this course"}` })}
                >
                  <CloseIcon size="1em" />
                  <Trans id="studies.course.remove">Remove</Trans>
                </Button>
              </div>
            ) : null}
          </div>
        ))}
        {rows.length < MAX_COURSES ? (
          <div className={ui.row}>
            <Button
              variant="secondary"
              small
              onPress={() => {
                setRows((rs) => [...rs, { key: next, title: "", adherence: "grounded" }]);
                setNext((n) => n + 1);
              }}
            >
              <PlusIcon size="1em" />
              <Trans id="studies.course.add">Add a course</Trans>
            </Button>
          </div>
        ) : null}
      </fieldset>

      <Notice role="note">
        <Trans id="studies.responsibility">
          Upload only material you may use for your own study. Yuo keeps it on this installation and sends the
          parts it needs to your AI provider; what you upload is your responsibility.
        </Trans>
      </Notice>

      {create.isError ? <ErrorNotice error={create.error} /> : null}
      <div className={secondary ? styles.formNav : ui.row}>
        {secondary ? <div className={ui.row}>{secondary}</div> : null}
        <Button type="submit" isDisabled={create.isPending || !filled.length || !title.trim()}>
          <Trans id="studies.submit">Next: add your material</Trans>
          <ArrowRightIcon size="1.1em" />
        </Button>
      </div>
    </Form>
  );
}
