// What a package holds, in words: content tags, record counts, the server's notices and personal
// records. Server values the client does not know fall back to the raw text.
import { msg, plural } from "@lingui/core/macro";
import type { I18n, MessageDescriptor } from "@lingui/core";
import type { ExportFormat, ExportProfile } from "./api";

export const PROFILE: Record<ExportProfile, { label: MessageDescriptor; description: MessageDescriptor }> = {
  full: {
    label: msg({ id: "share.profile.full", message: "Ready to study" }),
    description: msg({
      id: "share.profile.full.description",
      message: "Lessons, questions and the finished videos.",
    }),
  },
  structure: {
    label: msg({ id: "share.profile.structure", message: "Structure and texts" }),
    description: msg({
      id: "share.profile.structure.description",
      message: "Skills, lesson texts and questions, no videos: the recipient's models make the videos.",
    }),
  },
  custom: {
    label: msg({ id: "share.profile.custom", message: "Choose parts" }),
    description: msg({ id: "share.profile.custom.description", message: "Pick the parts to include." }),
  },
};

export const COMPONENT: Record<string, MessageDescriptor> = {
  curriculum: msg({ id: "share.content.curriculum", message: "Skills and structure" }),
  lessons: msg({ id: "share.content.lessons", message: "Lesson texts" }),
  items: msg({ id: "share.content.items", message: "Practice questions" }),
  flashcards: msg({ id: "share.content.flashcards", message: "Flashcards" }),
  "renditions.video": msg({ id: "share.content.videos", message: "Videos" }),
  "renditions.reading": msg({ id: "share.content.readings", message: "Readings" }),
  "renditions.audio": msg({ id: "share.content.audio", message: "Audio" }),
  "renditions.slides": msg({ id: "share.content.slides", message: "Slides" }),
  sources: msg({ id: "share.content.sources", message: "Sources" }),
  assets: msg({ id: "share.content.assets", message: "Media files" }),
  themes: msg({ id: "share.content.themes", message: "Video themes" }),
};

export const FORMAT: Record<ExportFormat, MessageDescriptor> = {
  csv: msg({ id: "share.format.csv", message: "Spreadsheet (CSV)" }),
  "anki-apkg": msg({ id: "share.format.anki", message: "Anki deck" }),
  "moodle-xml": msg({ id: "share.format.moodle", message: "Moodle questions" }),
  readings: msg({ id: "share.format.readings", message: "Readings as web pages and Markdown" }),
  "mp4-webvtt": msg({ id: "share.format.video", message: "Videos with subtitles" }),
  bibtex: msg({ id: "share.format.bibtex", message: "Bibliography (BibTeX)" }),
  "csl-json": msg({ id: "share.format.csl-json", message: "Bibliography (CSL JSON)" }),
};

/** The content tags as words; the `standard.<ext>` tags become one "Standard files" entry. */
export function contentsInWords(i18n: I18n, contents: string[]): string[] {
  const words: string[] = [];
  const standard: string[] = [];
  for (const tag of contents) {
    if (tag.startsWith("standard.")) standard.push(tag.slice("standard.".length).toUpperCase());
    else words.push(COMPONENT[tag] ? i18n._(COMPONENT[tag]) : tag);
  }
  if (standard.length) {
    const list = standard.join(", ");
    words.push(i18n._(msg({ id: "share.content.standard", message: `Standard files (${list})` })));
  }
  return words;
}

const COUNT_ORDER = ["branch", "skill", "objective", "lesson", "item", "rendition", "source", "asset", "theme"];

function countWords(i18n: I18n, kind: string, n: number): string | null {
  switch (kind) {
    case "path":
      return null; // always one
    case "branch":
      return i18n._(msg({ id: "share.count.branch", message: plural(n, { one: "# branch", other: "# branches" }) }));
    case "skill":
      return i18n._(msg({ id: "share.count.skill", message: plural(n, { one: "# skill", other: "# skills" }) }));
    case "objective":
      return i18n._(
        msg({ id: "share.count.objective", message: plural(n, { one: "# learning objective", other: "# learning objectives" }) }),
      );
    case "lesson":
      return i18n._(msg({ id: "share.count.lesson", message: plural(n, { one: "# lesson", other: "# lessons" }) }));
    case "item":
      return i18n._(msg({ id: "share.count.item", message: plural(n, { one: "# question", other: "# questions" }) }));
    case "rendition":
      return i18n._(
        msg({ id: "share.count.rendition", message: plural(n, { one: "# video or reading", other: "# videos and readings" }) }),
      );
    case "source":
      return i18n._(msg({ id: "share.count.source", message: plural(n, { one: "# source", other: "# sources" }) }));
    case "asset":
      return i18n._(msg({ id: "share.count.asset", message: plural(n, { one: "# media file", other: "# media files" }) }));
    case "theme":
      return i18n._(msg({ id: "share.count.theme", message: plural(n, { one: "# video theme", other: "# video themes" }) }));
    default:
      return `${kind}: ${n}`;
  }
}

/** Record counts as words ("3 branches, 12 skills, …"), in a fixed order, zeros left out. */
export function countsInWords(i18n: I18n, counts: Record<string, number>): string[] {
  const kinds = Object.keys(counts).sort((a, b) => {
    const ia = COUNT_ORDER.indexOf(a);
    const ib = COUNT_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  return kinds
    .filter((k) => (counts[k] ?? 0) > 0)
    .map((k) => countWords(i18n, k, counts[k] ?? 0))
    .filter((w): w is string => w !== null);
}

const KIND: Record<string, MessageDescriptor> = {
  lesson: msg({ id: "share.personal.lesson", message: "Lesson" }),
  item: msg({ id: "share.personal.item", message: "Question" }),
  rendition: msg({ id: "share.personal.rendition", message: "Video or reading" }),
  source: msg({ id: "share.personal.source", message: "Source" }),
  asset: msg({ id: "share.personal.asset", message: "Media file" }),
};

/** A personal record as the server names it ("lesson sql.joins.r1") in words: kind and code. */
export function personalInWords(i18n: I18n, entry: string): { kind: string; code: string } {
  const space = entry.indexOf(" ");
  if (space < 0) return { kind: "", code: entry };
  const kind = entry.slice(0, space);
  return { kind: KIND[kind] ? i18n._(KIND[kind]) : kind, code: entry.slice(space + 1) };
}

/** The reader's notices (spec §10, §11) in plain words; unknown ones as the server wrote them. */
export function noticeInWords(i18n: I18n, notice: string): string {
  if (notice === "unsigned package") {
    return i18n._(
      msg({
        id: "import.notice.unsigned",
        message: "This package is not signed, so who made it cannot be checked. Import it only if you trust where it came from.",
      }),
    );
  }
  if (notice.startsWith("signed package")) {
    return i18n._(
      msg({
        id: "import.notice.signed",
        message: "This package is signed, but Yuo cannot check signatures yet, so treat it as unsigned.",
      }),
    );
  }
  const unknown = /^record kinds this version does not know were kept aside: (.*)$/.exec(notice);
  if (unknown) {
    const kinds = unknown[1] ?? "";
    return i18n._(
      msg({
        id: "import.notice.unknown-kinds",
        message: `Parts this version of Yuo does not know were kept aside: ${kinds}`,
      }),
    );
  }
  return notice;
}

/** A byte count for people ("12 MB"), in the reader's locale. */
export function formatBytes(bytes: number, locale: string): string {
  const units = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit++;
  }
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: units[unit],
    unitDisplay: unit === 0 ? "long" : "short",
    maximumFractionDigits: unit === 0 || value >= 10 ? 0 : 1,
  }).format(value);
}

/** A language code as its name in the reader's language ("en" -> "English"), else the code. */
export function languageName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}
