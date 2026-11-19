import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { DropZone, FileTrigger, Form, Text, type DropZoneProps } from "react-aria-components";
import { ConfirmAction } from "../components/ConfirmAction";
import { ErrorNotice } from "../components/ErrorNotice";
import { ArrowRightIcon, BookIcon, CloseIcon, PlusIcon, UploadIcon } from "../components/icons";
import { Badge, Button, ButtonLink, Field, Notice, Progress, ui, Waiting } from "../components/ui";
import { GenerationError } from "../onboarding/AiReady";
import {
  ACCEPT,
  awaitsTranscription,
  isRecording,
  studiesKey,
  uploadFile,
  useAddCourse,
  useArchiveCourse,
  useCourseChange,
  useCourseStep,
  useCourseUpdate,
  useDeleteMaterial,
  useReadPages,
  useRetryMaterial,
  useMaterialChange,
  useStudies,
  useStudiesStep,
  type Adherence,
  type CourseOut,
  type CoursePlanOut,
  type CourseUpdateOut,
  type MaterialOut,
  type MaterialRole,
  type StudiesOut,
} from "./api";
import { Arrange } from "./Arrange";
import { takeOver } from "./handover";
import { audioOnly, hasSeparableAudio } from "./audioOnly";
import { Coverage } from "./Coverage";
import { ADHERENCE, AWAITS_TRANSCRIPTION, AdherenceField, ROLE, STATE } from "./labels";
import styles from "./material.module.css";

type DropEvent = Parameters<NonNullable<DropZoneProps["onDrop"]>>[0];
type Sending = { name: string; received: number; size: number; error?: unknown; preparing?: boolean };

const FEEDBACK_MAX = 2000;

/**
 * A path from the learner's own material: courses and their files, reading them, then the plan per course,
 * changed in the learner's own words, and building it. Recordings are transcribed in the background and join
 * the plan (or, once built, the path) as each one is ready. Built, it lists the files and what new ones add.
 */
export function Studies({ pathId }: { pathId: string }) {
  const studies = useStudies(pathId);
  const step = useStudiesStep(pathId);
  if (studies.isPending) {
    return (
      <Waiting>
        <Trans id="common.loading">Loading…</Trans>
      </Waiting>
    );
  }
  if (studies.isError) return <ErrorNotice error={studies.error} />;
  const s = studies.data;
  const collecting = s.status === "collecting";
  const built = s.status === "built";
  const reviewing = s.status === "ready" || s.status === "revising";
  const anyReady = s.courses.some((c) => c.plan?.status === "ready");
  const inbox = s.arrange ? s.courses[0] : undefined;

  if (s.arrange && inbox)
    return (
      <section className={ui.stack}>
        <div className={styles.card}>
          <h2 className={styles.cardTitle}>
            <Trans id="arrange.step">Add all your material</Trans>
          </h2>
          <p className={ui.muted}>
            <Trans id="arrange.collect.intro">
              Drop everything you study from, for every course: books and notes as PDF, slides, Word or text
              documents, exercises, past exams and recordings. Yuo reads them on this computer first, for free,
              then suggests a name for the path and how to split it into courses.
            </Trans>
          </p>
        </div>
        <Course pathId={pathId} course={inbox} collecting inbox />
        <Arrange pathId={pathId} studies={s} inbox={inbox} />
      </section>
    );

  return (
    <section className={ui.stack}>
      <div className={styles.card}>
        {built ? null : (
          <h2 className={styles.cardTitle}>
            {collecting ? (
              <Trans id="studies.step.collect">Your courses and material</Trans>
            ) : (
              <Trans id="studies.step.plan">Your plan, course by course</Trans>
            )}
          </h2>
        )}
        <p className={ui.muted}>
          {collecting ? (
            <Trans id="studies.collect.intro">
              Add each course's files: books and notes as PDF, slides (PDF or PowerPoint), Word or text
              documents, and recordings. Yuo reads them on this computer first, for free; nothing is sent to
              your AI provider until you start.
            </Trans>
          ) : built ? (
            <Trans id="studies.built.intro">
              Add files to a course at any time. Yuo reads them, adds them to the lessons not written yet, and
              suggests what they change in the rest.
            </Trans>
          ) : reviewing ? (
            <Trans id="studies.plan.intro">
              This is what Yuo will build from your material. Nothing is written yet: for each course, tell Yuo
              what is missing, wrong or should go deeper. When it fits, build it.
            </Trans>
          ) : (
            <Trans id="studies.drafting.intro">
              Yuo is reading your material and planning each course. This page updates by itself; you can leave
              and come back.
            </Trans>
          )}
        </p>
        {collecting ? (
          <Notice role="note">
            <Trans id="studies.collect.tip">
              Tip: start with the syllabus, the book or the slides. They are read in seconds and give the plan
              its shape. Recordings take longer (about a quarter of their length): they are transcribed in the
              background and join the plan one by one, so you do not have to wait for them.
            </Trans>
          </Notice>
        ) : null}
      </div>

      {s.courses.map((c) => (
        <Course key={c.id} pathId={pathId} course={c} collecting={collecting} built={built} />
      ))}

      {collecting ? <AddCourse pathId={pathId} /> : null}
      {s.links.related.length + s.links.requires.length > 0 && !collecting && !built ? <Links studies={s} /> : null}
      {s.links_failed && !collecting && !built ? (
        <Notice tone="warning" role="alert">
          <div className={ui.row}>
            <Trans id="studies.links.failed">The links between your courses could not be found.</Trans>
            <Button small variant="secondary" onPress={() => step.mutate("links")}>
              <Trans id="preview.retry">Try again</Trans>
            </Button>
          </div>
        </Notice>
      ) : null}

      {collecting ? <Start studies={s} onStart={() => step.mutate("start")} pending={step.isPending} /> : null}
      {!collecting && !built ? (
        <div className={styles.buildBar}>
          {s.status === "drafting" || s.status === "revising" ? <WorkProgress work={s.work} /> : null}
          <Button isDisabled={!anyReady || s.status !== "ready" || step.isPending} onPress={() => step.mutate("build")}>
            <Trans id="studies.build">Build the path</Trans>
            <ArrowRightIcon size="1.1em" />
          </Button>
        </div>
      ) : null}
      {step.isError ? <GenerationError error={step.error} /> : null}
    </section>
  );
}

/** Reading and planning: a bar over every file's parts, outlines and course plans, and what runs now. */
function WorkProgress({ work }: { work: StudiesOut["work"] }) {
  const { t } = useLingui();
  if (!work || work.total === 0)
    return (
      <Waiting>
        <Trans id="studies.drafting">Reading and planning…</Trans>
      </Waiting>
    );
  const step = work.step;
  const title = step?.title ?? "";
  const done = step?.done ?? 0;
  const total = step?.total ?? 0;
  return (
    <div className={styles.work} role="status">
      <span className={styles.workLabel}>
        {step?.kind === "file" ? (
          <Trans id="studies.work.file">
            Reading {title}: part {done} of {total}
          </Trans>
        ) : step?.kind === "course" ? (
          <Trans id="studies.work.course">Planning {title}</Trans>
        ) : step?.kind === "links" ? (
          <Trans id="studies.work.links">Finding how your courses build on each other</Trans>
        ) : (
          <Trans id="studies.drafting">Reading and planning…</Trans>
        )}
      </span>
      <Progress value={work.done} max={work.total} label={t({ id: "studies.work.label", message: "Reading and planning" })} />
    </div>
  );
}

function Start({ studies, onStart, pending }: { studies: StudiesOut; onStart: () => void; pending: boolean }) {
  const files = studies.courses.flatMap((c) => c.materials);
  // recordings do not hold the start back: they are transcribed in the background and join the plan later
  const busy = files.some((m) => !isRecording(m) && (m.state === "uploading" || m.state === "reading"));
  const usable = files.filter((m) => m.state !== "failed" && m.state !== "uploading").length;
  const minutes = studies.estimate?.audio_minutes ?? 0;
  return (
    <div className={styles.card}>
      {usable === 0 ? (
        <p className={ui.muted}>
          <Trans id="studies.start.empty">Add at least one file to start.</Trans>
        </p>
      ) : minutes > 0 ? (
        <p>
          <Plural
            id="studies.estimate.audio"
            value={minutes}
            one="# minute of recordings is still being transcribed on this computer; it joins the plan when it is ready."
            other="# minutes of recordings are still being transcribed on this computer; they join the plan when they are ready."
          />
        </p>
      ) : null}
      <div className={styles.buildBar}>
        {busy ? (
          <Waiting>
            <Trans id="studies.start.busy">Waiting for the files to be read…</Trans>
          </Waiting>
        ) : null}
        <Button isDisabled={pending || busy || usable === 0} onPress={onStart}>
          <Trans id="studies.start">Read my material and plan</Trans>
          <ArrowRightIcon size="1.1em" />
        </Button>
      </div>
    </div>
  );
}

/** Where files are dropped or chosen; `onFiles` gets them all at once. */
export function FileDrop({ label, onFiles, isDisabled }: { label: string; onFiles: (files: File[]) => void; isDisabled?: boolean }) {
  const onDrop = async (e: DropEvent) => {
    const files: File[] = [];
    for (const item of e.items) if (item.kind === "file") files.push(await item.getFile());
    if (files.length) onFiles(files);
  };
  return (
    <DropZone
      className={styles.dropZone}
      aria-label={label}
      isDisabled={isDisabled}
      getDropOperation={() => "copy"}
      onDrop={(e) => void onDrop(e)}
    >
      <Text slot="label" className={ui.muted}>
        <Trans id="material.drop">Drop files here, or</Trans>
      </Text>
      <FileTrigger
        allowsMultiple
        acceptedFileTypes={ACCEPT.split(",")}
        onSelect={(list) => {
          if (list && list.length) onFiles(Array.from(list));
        }}
      >
        <Button variant="secondary" small isDisabled={isDisabled}>
          <UploadIcon size="1em" />
          <Trans id="material.choose">Choose files</Trans>
        </Button>
      </FileTrigger>
    </DropZone>
  );
}

function Course({
  pathId,
  course,
  collecting,
  built = false,
  inbox = false,
}: {
  pathId: string;
  course: CourseOut;
  collecting: boolean;
  built?: boolean;
  /** the files of a path whose courses are proposed from them: no course name or settings yet */
  inbox?: boolean;
}) {
  const { t, i18n } = useLingui();
  const [sending, setSending] = useState<Record<string, Sending>>({});
  const [editing, setEditing] = useState(false);
  const archive = useArchiveCourse(pathId);
  const change = useCourseChange(pathId);
  const qc = useQueryClient();

  const send = async (files: File[]) => {
    for (const file of files) {
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      setSending((s) => ({ ...s, [key]: { name: file.name, received: 0, size: file.size, preparing: hasSeparableAudio(file) } }));
      try {
        // a lecture's video is not kept: only its sound is sent, when it can be taken out here
        const upload = (await audioOnly(file)) ?? file;
        await uploadFile(course.id, upload, (received) =>
          setSending((s) => ({ ...s, [key]: { name: file.name, received, size: upload.size } })),
        );
        setSending((s) => {
          const { [key]: _, ...rest } = s;
          return rest;
        });
      } catch (error) {
        setSending((s) => ({ ...s, [key]: { name: file.name, received: 0, size: file.size, error } }));
      }
      void qc.invalidateQueries({ queryKey: studiesKey(pathId) }); // the file is listed and read
    }
  };

  // files chosen on the new-path form before this path existed (material/handover.ts)
  useEffect(() => {
    if (!inbox) return;
    const handed = takeOver(pathId);
    if (handed.length) void send(handed);
    // once, on opening
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pending = Object.entries(sending);
  const meta = i18n._(ADHERENCE[course.adherence].label);
  const recordings = course.materials.filter((m) => isRecording(m) && m.state !== "failed");
  const transcribed = recordings.filter((m) => m.chunks > 0 || m.state === "ready").length;
  const total = recordings.length;
  return (
    <article className={styles.card} aria-label={inbox ? t({ id: "arrange.files", message: "Your files" }) : course.title}>
      {inbox ? null : (
        <div className={styles.courseHead}>
          <span className={styles.headingIcon}>
            <BookIcon />
          </span>
          <div className={styles.courseTitle}>
            <h3>{course.title}</h3>
            <p className={ui.muted}>{meta}</p>
          </div>
          {collecting ? (
            <div className={ui.row}>
              <Button variant="ghost" small onPress={() => setEditing((v) => !v)}>
                <Trans id="studies.course.settings">Settings</Trans>
              </Button>
            </div>
          ) : null}
        </div>
      )}

      {editing && collecting ? (
        <div className={styles.settings}>
          <AdherenceField
            value={course.adherence}
            onChange={(v: Adherence) => change.mutate({ id: course.id, change: { adherence: v } })}
            isDisabled={change.isPending}
          />
          <div className={ui.row}>
            <Button variant="ghost" small onPress={() => archive.mutate(course.id)} isDisabled={archive.isPending}>
              <CloseIcon size="1em" />
              <Trans id="studies.course.drop">Remove this course</Trans>
            </Button>
          </div>
          {archive.isError ? <ErrorNotice error={archive.error} /> : null}
        </div>
      ) : null}

      {course.materials.length > 0 || pending.length > 0 ? (
        <ul className={styles.files}>
          {course.materials.map((m) => (
            <MaterialRow key={m.id} pathId={pathId} m={m} editable={collecting} removable={course.built && built} />
          ))}
          {pending.map(([key, p]) => (
            <li key={key} className={styles.file}>
              <span className={styles.fileName}>{p.name}</span>
              {p.error ? (
                <ErrorNotice error={p.error} />
              ) : p.preparing ? (
                <Waiting>
                  <Trans id="material.audio-only">Taking the sound out of the video: only that is uploaded…</Trans>
                </Waiting>
              ) : (
                <Progress
                  value={p.received}
                  max={p.size}
                  label={t({ id: "material.uploading.label", message: `Uploading ${p.name}` })}
                />
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {!collecting && transcribed < total ? (
        <p className={ui.muted}>
          {course.built ? (
            <Trans id="studies.recordings.built">
              {transcribed} of {total} recordings transcribed. Each one adds to the path when it is ready.
            </Trans>
          ) : (
            <Trans id="studies.recordings.plan">
              {transcribed} of {total} recordings transcribed. Each one joins the plan when it is ready.
            </Trans>
          )}
        </p>
      ) : null}

      {!course.built || built ? (
        <FileDrop
          label={t({ id: "material.drop.label", message: `Drop files for ${course.title} here` })}
          onFiles={(files) => void send(files)}
        />
      ) : null}

      {!collecting ? <CoursePlan pathId={pathId} course={course} /> : null}
      {!collecting && (course.built || course.plan?.status === "ready") ? <Coverage courseId={course.id} /> : null}
    </article>
  );
}

const VISION_MAX_PAGES = 300;

/** Pages being read from their images: how many are done, of how many (the model reads a few per call). */
function VisionProgress({ m }: { m: MaterialOut }) {
  const { t } = useLingui();
  const total = m.vision_total;
  const done = Math.min(total, Math.round(m.progress * total));
  return (
    <div className={styles.work} role="status">
      <span className={styles.workLabel}>
        {total > 0 ? (
          <Trans id="material.vision.progress">
            Reading pages from their images: {done} of {total}
          </Trans>
        ) : (
          <Trans id="material.vision.wanted">Reading the pages with formulas and figures from their images…</Trans>
        )}
      </span>
      {total > 0 ? (
        <Progress
          value={done}
          max={total}
          label={t({ id: "material.vision.progress.label", message: `Pages read from their images: ${m.title}` })}
        />
      ) : null}
    </div>
  );
}

/**
 * Pages with little text (formulas, figures or scans) and pages whose formulas are missing from their text
 * (drawn as shapes). A PDF's can be read from their images by the generation model, when the learner asks (one
 * call per page), before the course is built; it is recommended only for the pages missing their formulas.
 */
function SparsePages({ pathId, m, editable }: { pathId: string; m: MaterialOut; editable: boolean }) {
  const read = useReadPages(pathId);
  if (m.vision === "done")
    return (
      <p className={ui.muted}>
        <Plural
          id="material.vision.done"
          value={m.vision_pages}
          one="# page was read from its image (formulas and figures)."
          other="# pages were read from their images (formulas and figures)."
        />
      </p>
    );
  if (m.vision === "wanted") return <VisionProgress m={m} />;
  const offer = editable && m.kind === "pdf" && (m.state === "read" || m.state === "ready");
  const flagged = m.sparse_pages + m.formula_pages;
  const pages = Math.min(flagged, VISION_MAX_PAGES);
  return (
    <div className={styles.sparse}>
      <p className={ui.muted}>
        {m.vision === "failed" ? (
          <Trans id="material.vision.failed">
            The model could not read these pages. It may not accept images; try another generation model.
          </Trans>
        ) : offer ? (
          <>
            {m.formula_pages > 0 ? (
              <Plural
                id="material.formulas.pdf"
                value={m.formula_pages}
                one="# page has formulas or symbols missing from its text (drawn as shapes, not letters): lessons from it would have gaps. Reading it from its image is recommended."
                other="# pages have formulas or symbols missing from their text (drawn as shapes, not letters): lessons from them would have gaps. Reading them from their images is recommended."
              />
            ) : null}{" "}
            {m.sparse_pages > 0 ? (
              <Plural
                id="material.sparse.pdf"
                value={m.sparse_pages}
                one="# page has little text: probably formulas or a figure."
                other="# pages have little text: probably formulas or figures."
              />
            ) : null}
          </>
        ) : (
          <>
            {m.formula_pages > 0 ? (
              <Plural
                id="material.formulas"
                value={m.formula_pages}
                one="# page has formulas missing from its text: Yuo reads only the words around them."
                other="# pages have formulas missing from their text: Yuo reads only the words around them."
              />
            ) : null}{" "}
            {m.sparse_pages > 0 ? (
              <Plural
                id="material.sparse"
                value={m.sparse_pages}
                one="# page has little text (a picture or a scan): Yuo cannot read it yet."
                other="# pages have little text (pictures or scans): Yuo cannot read them yet."
              />
            ) : null}
          </>
        )}
      </p>
      {offer ? (
        <>
          <Button variant="secondary" small isDisabled={read.isPending} onPress={() => read.mutate(m.id)}>
            <Plural
              id="material.vision.read"
              value={pages}
              one="Read it from its image"
              other="Read them from their images"
            />
          </Button>
          <p className={ui.muted}>
            <Trans id="material.vision.then">
              The generation model looks at the pages, then the course is planned again with them.
            </Trans>
          </p>
          {flagged > VISION_MAX_PAGES ? (
            <p className={ui.muted}>
              <Trans id="material.vision.capped">
                Only the {pages} pages missing the most are read; the others keep their text.
              </Trans>
            </p>
          ) : null}
          {read.isError ? <ErrorNotice error={read.error} /> : null}
        </>
      ) : null}
    </div>
  );
}

function MaterialRow({
  pathId,
  m,
  editable,
  removable = false,
}: {
  pathId: string;
  m: MaterialOut;
  editable: boolean;
  /** a built course's file: removing it writes its lessons again without it */
  removable?: boolean;
}) {
  const { t, i18n } = useLingui();
  const change = useMaterialChange(pathId);
  const remove = useDeleteMaterial(pathId);
  const retry = useRetryMaterial(pathId);
  const working = m.state === "transcribing" || m.state === "digesting" || m.state === "outlining";
  const size =
    m.kind === "audio" || m.kind === "video"
      ? m.duration_ms
        ? t({ id: "material.minutes", message: `${Math.round(m.duration_ms / 60000)} min` })
        : null
      : m.pages
        ? m.kind === "pptx"
          ? t({ id: "material.slides", message: `${m.pages} slides` })
          : t({ id: "material.pages", message: `${m.pages} pages` })
        : null;
  return (
    <li className={styles.file}>
      <div className={styles.fileHead}>
        <span className={styles.fileName}>{m.title}</span>
        {size ? <span className={ui.muted}>{size}</span> : null}
        <Badge tone={m.state === "ready" ? "success" : undefined}>
          {i18n._(awaitsTranscription(m) ? AWAITS_TRANSCRIPTION : STATE[m.state])}
        </Badge>
      </div>
      {working ? (
        <Progress value={m.progress * 100} label={i18n._(STATE[m.state])} />
      ) : m.state === "reading" && m.vision !== "wanted" ? (
        <Waiting>{i18n._(STATE.reading)}</Waiting>
      ) : null}
      {m.state === "failed" && m.error ? <p className={styles.error}>{m.error}</p> : null}
      {m.state === "failed" ? (
        <div className={styles.fileActions}>
          <Button small variant="secondary" isDisabled={retry.isPending} onPress={() => retry.mutate(m.id)}>
            <Trans id="material.retry">Try again</Trans>
          </Button>
          {retry.isError ? <ErrorNotice error={retry.error} /> : null}
        </div>
      ) : null}
      {m.sparse_pages + m.formula_pages > 0 && m.state !== "failed" ? <SparsePages pathId={pathId} m={m} editable={editable} /> : null}
      {editable ? (
        <div className={styles.fileActions}>
          <label className={styles.roleLabel}>
            <span>
              <Trans id="material.role">This is</Trans>
            </span>
            <select
              className={styles.select}
              value={m.role}
              disabled={change.isPending}
              onChange={(e) => change.mutate({ id: m.id, role: e.target.value as MaterialRole })}
            >
              {(Object.keys(ROLE) as MaterialRole[]).map((r) => (
                <option key={r} value={r}>
                  {i18n._(ROLE[r])}
                </option>
              ))}
            </select>
          </label>
          <Button
            variant="ghost"
            small
            isDisabled={remove.isPending}
            onPress={() => remove.mutate(m.id)}
            aria-label={t({ id: "material.remove.label", message: `Remove ${m.title}` })}
          >
            <CloseIcon size="1em" />
            <Trans id="material.remove">Remove</Trans>
          </Button>
        </div>
      ) : removable ? (
        <ConfirmAction
          label={<Trans id="material.remove.built">Remove</Trans>}
          question={
            <Trans id="material.remove.built.question">
              Remove {m.title}? The lessons written from it are written again without it; you can read them as they
              are until then.
            </Trans>
          }
          confirmLabel={<Trans id="material.remove.built.confirm">Remove the file</Trans>}
          pending={remove.isPending}
          onConfirm={() => remove.mutate(m.id)}
        />
      ) : null}
      {remove.isError ? <ErrorNotice error={remove.error} /> : null}
    </li>
  );
}

function AddCourse({ pathId }: { pathId: string }) {
  const { t } = useLingui();
  const add = useAddCourse(pathId);
  const [title, setTitle] = useState("");
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <div className={ui.row}>
        <Button variant="secondary" onPress={() => setOpen(true)}>
          <PlusIcon size="1em" />
          <Trans id="studies.course.add">Add a course</Trans>
        </Button>
      </div>
    );
  }
  return (
    <Form
      className={styles.card}
      onSubmit={(e) => {
        e.preventDefault();
        if (!title.trim()) return;
        add.mutate(
          { title: title.trim(), adherence: "grounded", keep_order: true },
          {
            onSuccess: () => {
              setTitle("");
              setOpen(false);
            },
          },
        );
      }}
    >
      <div className={styles.courseFields}>
        <Field
          label={t({ id: "studies.course.name", message: "Course" })}
          value={title}
          onChange={setTitle}
          isRequired
          maxLength={120}
          name="course"
        />
      </div>
      {add.isError ? <ErrorNotice error={add.error} /> : null}
      <div className={ui.row}>
        <Button type="submit" small isDisabled={add.isPending || !title.trim()}>
          <Trans id="studies.course.add.submit">Add</Trans>
        </Button>
        <Button variant="ghost" small onPress={() => setOpen(false)}>
          <Trans id="confirm.cancel">Cancel</Trans>
        </Button>
      </div>
    </Form>
  );
}

function CoursePlan({ pathId, course }: { pathId: string; course: CourseOut }) {
  const { t } = useLingui();
  const step = useCourseStep(pathId);
  const [text, setText] = useState("");
  const plan = course.plan;
  if (course.built) {
    return (
      <div className={ui.stack}>
        <p className={ui.muted}>
          <Trans id="studies.course.built">Built into the path.</Trans>
        </p>
        <p>
          <ButtonLink
            to="/paths/$pathId/courses/$courseId/mock-exam"
            params={{ pathId, courseId: course.id }}
            variant="secondary"
            small
          >
            <Trans id="studies.course.mock">Take a mock exam</Trans>
          </ButtonLink>
        </p>
        {course.updates.map((u) => (
          <Update key={u.id} pathId={pathId} courseId={course.id} update={u} />
        ))}
      </div>
    );
  }
  if (!plan || plan.status === "drafting" || plan.skills.length === 0) {
    const reading = course.materials.some(
      (m) => !isRecording(m) && m.state !== "ready" && m.state !== "failed" && m.state !== "uploading",
    );
    const onlyRecordings = !plan && !reading && course.materials.some((m) => isRecording(m) && m.state !== "ready");
    return course.failed ? (
      <div className={ui.stack}>
        <Notice tone="warning" role="alert">
          <Trans id="studies.course.failed">This course's plan could not be written. Try again in a moment.</Trans>
        </Notice>
        <div className={ui.row}>
          <Button small onPress={() => step.mutate({ id: course.id, step: "retry" })}>
            <Trans id="preview.retry">Try again</Trans>
          </Button>
        </div>
      </div>
    ) : (
      <Waiting>
        {reading ? (
          <Trans id="studies.course.reading">Reading the material…</Trans>
        ) : onlyRecordings ? (
          <Trans id="studies.course.recordings">The plan starts when the first recordings are transcribed…</Trans>
        ) : (
          <Trans id="studies.course.planning">Planning this course…</Trans>
        )}
      </Waiting>
    );
  }
  const revising = plan.status === "revising";
  const busy = revising || step.isPending;
  return (
    <div className={styles.plan}>
      {plan.changes.length > 0 ? (
        <Notice role="status">
          <div className={ui.stack}>
            <strong>
              <Trans id="preview.changed">What changed</Trans>
            </strong>
            <ul className={styles.changes}>
              {plan.changes.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
            {plan.can_undo ? (
              <div className={ui.row}>
                <Button variant="ghost" small isDisabled={busy} onPress={() => step.mutate({ id: course.id, step: "undo" })}>
                  <Trans id="preview.undo">Go back to the previous plan</Trans>
                </Button>
              </div>
            ) : null}
          </div>
        </Notice>
      ) : null}
      <CourseSkills plan={plan} />
      <Form
        className={styles.feedback}
        onSubmit={(e) => {
          e.preventDefault();
          const value = text.trim();
          if (!value || busy) return;
          step.mutate({ id: course.id, step: "feedback", text: value }, { onSuccess: () => setText("") });
        }}
      >
        <Field
          label={t({ id: "studies.feedback.label", message: `Anything missing, wrong, or that should go deeper in ${course.title}?` })}
          description={t({
            id: "studies.feedback.description",
            message: "For example: “chapter 7 is not in the exam”, “more on Fourier series”, “split the long skills”.",
          })}
          value={text}
          onChange={setText}
          maxLength={FEEDBACK_MAX}
          multiline
          isDisabled={busy}
          name={`feedback-${course.id}`}
        />
        {revising ? (
          course.failed ? (
            <div className={ui.row}>
              <Notice tone="warning" role="alert">
                <Trans id="preview.revise-failed">The plan could not be changed. Try again in a moment.</Trans>
              </Notice>
              <Button small onPress={() => step.mutate({ id: course.id, step: "retry" })}>
                <Trans id="preview.retry">Try again</Trans>
              </Button>
            </div>
          ) : (
            <Waiting>
              <Trans id="preview.revising">Changing the plan…</Trans>
            </Waiting>
          )
        ) : null}
        {step.isError ? <GenerationError error={step.error} /> : null}
        <div className={styles.actions}>
          <Button type="submit" variant="secondary" small isDisabled={busy || !text.trim()}>
            <Trans id="preview.change">Change the plan</Trans>
          </Button>
        </div>
      </Form>
    </div>
  );
}

function CourseSkills({ plan }: { plan: CoursePlanOut }) {
  const titles = new Map(plan.skills.map((s) => [s.code, s.title] as const));
  const lessons = plan.skills.reduce((n, s) => n + s.lessons.length, 0);
  const skills = plan.skills.length;
  const units: [string, CoursePlanOut["skills"]][] = [];
  for (const s of plan.skills) {
    const last = units.at(-1);
    if (last && last[0] === s.unit) last[1].push(s);
    else units.push([s.unit, [s]]);
  }
  return (
    <div className={styles.skillsBlock}>
      <p className={styles.counts}>
        <Plural id="preview.count.skills" value={skills} one="# skill" other="# skills" />
        {" · "}
        <Plural id="preview.count.lessons" value={lessons} one="# lesson" other="# lessons" />
      </p>
      {units.map(([unit, inUnit], i) => (
        <div key={`${unit}-${i}`} className={styles.unit}>
          {unit ? <h4>{unit}</h4> : null}
          <ol className={styles.skills}>
            {inUnit.map((s) => {
              const after = s.requires
                .map((r) => titles.get(r))
                .filter(Boolean)
                .join(", ");
              return (
                <li key={s.code} className={styles.skill}>
                  <span className={styles.skillTitle}>
                    {s.title}
                    {s.not_in_material ? (
                      <>
                        {" "}
                        <Badge tone="highlight">
                          <Trans id="studies.skill.added">Added by Yuo</Trans>
                        </Badge>
                      </>
                    ) : null}
                  </span>
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
        </div>
      ))}
      {plan.skipped.length > 0 ? (
        <details className={styles.history}>
          <summary>
            <Plural id="studies.skipped" value={plan.skipped.length} one="# part left out" other="# parts left out" />
          </summary>
          <ul>
            {plan.skipped.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </details>
      ) : null}
      {plan.feedback.length > 0 ? (
        <details className={styles.history}>
          <summary>
            <Plural id="preview.history" value={plan.feedback.length} one="Your request so far" other="Your # requests so far" />
          </summary>
          <ol>
            {plan.feedback.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  );
}

function Links({ studies }: { studies: StudiesOut }) {
  const title = new Map(
    studies.courses.flatMap((c) => (c.plan?.skills ?? []).map((s) => [s.code, `${s.title} (${c.title})`] as const)),
  );
  const name = (code: string) => title.get(code) ?? code;
  return (
    <div className={styles.card}>
      <h3>
        <Trans id="studies.links">How your courses connect</Trans>
      </h3>
      <ul className={styles.linkList}>
        {studies.links.requires.map((r, i) => (
          <li key={`r${i}`}>
            <Trans id="studies.links.requires">
              {name(r.skill)} comes after {name(r.requires)}
            </Trans>
            {r.why ? <span className={ui.muted}>: {r.why}</span> : null}
          </li>
        ))}
        {studies.links.related.map((r, i) => (
          <li key={`x${i}`}>
            <Trans id="studies.links.related">
              {name(r.a)} and {name(r.b)}
            </Trans>
            {r.note ? <span className={ui.muted}>: {r.note}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What files added to a built course bring: the lessons to rewrite with them and new skills, on a yes. */
function Update({ pathId, courseId, update }: { pathId: string; courseId: string; update: CourseUpdateOut }) {
  const decide = useCourseUpdate(pathId);
  const files = update.materials.join(", ");
  const lessons = update.lessons.map((l) => l.title).join(", ");
  const skills = update.skills.join(", ");
  return (
    <Notice role="status">
      <div className={ui.stack}>
        <strong>
          <Trans id="studies.update.title">New from {files}</Trans>
        </strong>
        {update.changes.length > 0 ? (
          <ul className={styles.changes}>
            {update.changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        ) : null}
        {update.lessons.length > 0 ? (
          <p>
            <Trans id="studies.update.lessons">Rewrite these lessons with it: {lessons}</Trans>
          </p>
        ) : null}
        {update.skills.length > 0 ? (
          <p>
            <Trans id="studies.update.skills">Add these skills: {skills}</Trans>
          </p>
        ) : null}
        {decide.isError ? <GenerationError error={decide.error} /> : null}
        <div className={ui.row}>
          <Button
            small
            isDisabled={decide.isPending}
            onPress={() => decide.mutate({ courseId, updateId: update.id, accept: true })}
          >
            <Trans id="studies.update.apply">Apply</Trans>
          </Button>
          <Button
            small
            variant="ghost"
            isDisabled={decide.isPending}
            onPress={() => decide.mutate({ courseId, updateId: update.id, accept: false })}
          >
            <Trans id="studies.update.dismiss">Not now</Trans>
          </Button>
        </div>
      </div>
    </Notice>
  );
}
