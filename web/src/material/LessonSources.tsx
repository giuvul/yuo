import { Trans, useLingui } from "@lingui/react/macro";
import type { LessonOut } from "../api/client";
import { BookIcon } from "../components/icons";
import styles from "./material.module.css";

type Source = NonNullable<LessonOut["sources"]>[number];

const mmss = (ms: number) => {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/** Opens the learner's own file where the lesson comes from: a PDF at its page, a recording at its minute. */
function href(s: Source): string {
  const base = `/api/materials/${s.material_id}/file`;
  if (s.loc_kind === "page" && s.kind === "pdf") return `${base}#page=${s.loc_start}`;
  if (s.loc_kind === "time") return `${base}#t=${Math.floor(s.loc_start / 1000)}`;
  return base;
}

/** "From your material": the files of the learner this lesson was written from, and where in them. */
export function LessonSources({ sources }: { sources: Source[] }) {
  const { t } = useLingui();
  if (!sources.length) return null;
  const where = (s: Source) => {
    const a = s.loc_start;
    const b = s.loc_end;
    if (s.loc_kind === "time") return `${mmss(a)}-${mmss(b)}`;
    if (s.loc_kind === "slide")
      return a === b
        ? t({ id: "sources.slide", message: `slide ${a}` })
        : t({ id: "sources.slides", message: `slides ${a}-${b}` });
    return a === b
      ? t({ id: "sources.page", message: `p. ${a}` })
      : t({ id: "sources.pages", message: `pp. ${a}-${b}` });
  };
  return (
    <section className={styles.sources} aria-labelledby="lesson-sources">
      <h2 id="lesson-sources" className={styles.sourcesTitle}>
        <BookIcon />
        <Trans id="sources.title">From your material</Trans>
      </h2>
      <ul>
        {sources.map((s) => (
          <li key={s.material_id}>
            <a href={href(s)} target="_blank" rel="noopener noreferrer">
              {s.title}
            </a>
            , {where(s)}
          </li>
        ))}
      </ul>
    </section>
  );
}
