import { Trans, useLingui } from "@lingui/react/macro";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { api, unwrap, type Schemas } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { ui, Waiting } from "../components/ui";
import styles from "./material.module.css";

type Part = Schemas["CoveragePartOut"];

/**
 * What a course's material covers: one bar per file, its parts coloured by whether a skill teaches them, is
 * left out (with the reason) or is not used yet; each taught part opens its lesson. Loaded when opened.
 */
export function Coverage({ courseId }: { courseId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details className={styles.history} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <Trans id="coverage.title">What your material covers</Trans>
      </summary>
      {open ? <CoverageBody courseId={courseId} /> : null}
    </details>
  );
}

function CoverageBody({ courseId }: { courseId: string }) {
  const q = useQuery({
    queryKey: ["courses", courseId, "coverage"],
    queryFn: () => unwrap(api.GET("/api/courses/{course_id}/coverage", { params: { path: { course_id: courseId } } })),
  });
  if (q.isPending)
    return (
      <Waiting>
        <Trans id="common.loading">Loading…</Trans>
      </Waiting>
    );
  if (q.isError) return <ErrorNotice error={q.error} />;
  const files = q.data.files.filter((f) => f.parts.length > 0);
  if (!files.length)
    return (
      <p className={ui.muted}>
        <Trans id="coverage.empty">Nothing is read yet.</Trans>
      </p>
    );
  return (
    <div className={styles.coverage}>
      <p className={styles.coverageKey}>
        <span className={styles.keyTaught} /> <Trans id="coverage.key.taught">taught</Trans>
        <span className={styles.keySkipped} /> <Trans id="coverage.key.skipped">left out</Trans>
        <span className={styles.keyUnused} /> <Trans id="coverage.key.unused">not used yet</Trans>
      </p>
      {files.map((f) => (
        <FileCoverage key={f.material_id} title={f.title} parts={f.parts} />
      ))}
    </div>
  );
}

const span = (p: Part) => Math.max(1, p.end - p.start + (p.loc_kind === "time" ? 0 : 1));

function FileCoverage({ title, parts }: { title: string; parts: Part[] }) {
  const { t } = useLingui();
  const total = parts.reduce((n, p) => n + span(p), 0);
  const taught = parts.filter((p) => p.status === "taught").reduce((n, p) => n + span(p), 0);
  const share = Math.round((100 * taught) / total);
  const cls = { taught: styles.partTaught, skipped: styles.partSkipped, unused: styles.partUnused };
  return (
    <div className={styles.coverageFile}>
      <p className={styles.coverageHead}>
        <strong>{title}</strong>{" "}
        <span className={ui.muted}>
          <Trans id="coverage.share">{share}% taught</Trans>
        </span>
      </p>
      <div className={styles.coverageBar} aria-hidden="true">
        {parts.map((p, i) => (
          <span key={i} className={cls[p.status]} style={{ flexGrow: span(p) }} title={`${p.where}: ${p.skill ?? p.reason ?? ""}`} />
        ))}
      </div>
      <ul className={styles.coverageList} aria-label={t({ id: "coverage.parts", message: `Parts of ${title}` })}>
        {parts.map((p, i) => (
          <li key={i}>
            <span className={styles.coverageWhere}>{p.where}</span>{" "}
            {p.status === "taught" ? (
              p.lesson_id ? (
                <Link to="/lessons/$lessonId" params={{ lessonId: p.lesson_id }}>
                  {p.skill}
                </Link>
              ) : (
                p.skill
              )
            ) : p.status === "skipped" ? (
              <span className={ui.muted}>
                <Trans id="coverage.skipped">Left out: {p.reason}</Trans>
              </span>
            ) : (
              <span className={ui.muted}>
                <Trans id="coverage.unused">Not used yet</Trans>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
