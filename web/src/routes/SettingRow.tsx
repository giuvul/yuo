// One setting in Settings: its editor, its explanation, where its value comes from and what changing it does.
import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  Button as AriaButton,
  Checkbox,
  CheckboxGroup,
  Group,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  NumberField,
  Popover,
  Select,
  SelectValue,
  Switch,
} from "react-aria-components";
import type { ItemType, SettingOut } from "../api/client";
import { usePutSetting } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button, Field, Notice, ui } from "../components/ui";
import itemStyles from "../items/items.module.css";
import { TRIGGER_NAMES } from "../tutor/texts";
import styles from "./settings.module.css";

type Editor =
  | { kind: "switch" }
  | { kind: "number"; min: number; max: number; step: number; percent?: boolean }
  | { kind: "select"; options: { value: string; label: MessageDescriptor }[] }
  | { kind: "types" }
  /** a list of known values (e.g. muted suggestion kinds): one checkbox each */
  | { kind: "literals"; options: { value: string; label: MessageDescriptor }[]; empty: MessageDescriptor }
  | { kind: "text"; max: number; singleLine?: boolean };

const ITEM_TYPES: { value: ItemType; label: MessageDescriptor }[] = [
  { value: "mcq", label: msg({ id: "item-type.mcq", message: "Single choice" }) },
  { value: "multi", label: msg({ id: "item-type.multi", message: "Multiple choice" }) },
  { value: "cloze", label: msg({ id: "item-type.cloze", message: "Fill the gap" }) },
  { value: "ordering", label: msg({ id: "item-type.ordering", message: "Put in order" }) },
  { value: "matching", label: msg({ id: "item-type.matching", message: "Matching" }) },
  { value: "flashcard", label: msg({ id: "item-type.flashcard", message: "Flashcard" }) },
  { value: "short_answer", label: msg({ id: "item-type.short-answer", message: "Short answer" }) },
];

/** Editors for known keys; the API does not describe types or ranges. */
const EDITORS: Record<string, Editor> = {
  "skill_test.pass_mark": { kind: "number", min: 0.5, max: 1, step: 0.05, percent: true },
  "generation.buffer": { kind: "number", min: 1, max: 10, step: 1 },
  "reviews.max_per_day": { kind: "number", min: 0, max: 500, step: 1 },
  "review.bank_size": { kind: "number", min: 4, max: 20, step: 1 },
  "review.desired_retention": { kind: "number", min: 0.7, max: 0.97, step: 0.01, percent: true },
  "review.max_interval_days": { kind: "number", min: 0, max: 365, step: 1 },
  "streak.grace_days": { kind: "number", min: 0, max: 3, step: 1 },
  gamification: {
    kind: "select",
    options: [
      { value: "off", label: msg({ id: "settings.gamification.off", message: "Off" }) },
      { value: "minimal", label: msg({ id: "settings.gamification.minimal", message: "Minimal (tree progress only)" }) },
      { value: "full", label: msg({ id: "settings.gamification.full", message: "Full (XP, streaks, levels)" }) },
    ],
  },
  "practice.solution_after": {
    kind: "select",
    options: [
      { value: "attempt", label: msg({ id: "settings.solution.attempt", message: "After an attempt" }) },
      { value: "any_time", label: msg({ id: "settings.solution.any-time", message: "Any time" }) },
    ],
  },
  "lesson.reading_length": {
    kind: "select",
    options: [
      { value: "short", label: msg({ id: "settings.length.short", message: "Short" }) },
      { value: "medium", label: msg({ id: "settings.length.medium", message: "Medium" }) },
      { value: "long", label: msg({ id: "settings.length.long", message: "Long" }) },
    ],
  },
  "material.transcription": {
    kind: "select",
    options: [
      { value: "accurate", label: msg({ id: "settings.transcription.accurate", message: "More accurate" }) },
      { value: "faster", label: msg({ id: "settings.transcription.faster", message: "Faster" }) },
    ],
  },
  "practice.types": { kind: "types" },
  custom_instructions: { kind: "text", max: 1000 },
  "tutor.proactivity": {
    kind: "select",
    options: [
      { value: "off", label: msg({ id: "settings.proactivity.off", message: "Off (only answers you)" }) },
      { value: "quiet", label: msg({ id: "settings.proactivity.quiet", message: "Quiet (a dot on the tutor button)" }) },
      { value: "coach", label: msg({ id: "settings.proactivity.coach", message: "Coach (a short offer now and then)" }) },
      { value: "active", label: msg({ id: "settings.proactivity.active", message: "Active (offers more often)" }) },
    ],
  },
  "tutor.test_policy": {
    kind: "select",
    options: [
      { value: "locked", label: msg({ id: "settings.test-policy.locked", message: "Locked (wording only)" }) },
      { value: "hints", label: msg({ id: "settings.test-policy.hints", message: "Hints with cost" }) },
    ],
  },
  "tutor.tone": {
    kind: "select",
    options: [
      { value: "neutral", label: msg({ id: "settings.tone.neutral", message: "Neutral" }) },
      { value: "warm", label: msg({ id: "settings.tone.warm", message: "Warm" }) },
      { value: "direct", label: msg({ id: "settings.tone.direct", message: "Direct" }) },
    ],
  },
  "video.format": {
    kind: "select",
    options: [
      { value: "reading", label: msg({ id: "settings.video-format.reading", message: "Reading only" }) },
      { value: "when_possible", label: msg({ id: "settings.video-format.when-possible", message: "Video when possible" }) },
      { value: "always", label: msg({ id: "settings.video-format.always", message: "Always a video" }) },
    ],
  },
  "video.source": {
    kind: "select",
    options: [
      { value: "generated", label: msg({ id: "settings.video-source.generated", message: "Made by Yuo" }) },
      { value: "youtube", label: msg({ id: "settings.video-source.youtube", message: "From YouTube" }) },
    ],
  },
  "video.youtube_languages": {
    kind: "select",
    options: [
      { value: "mine", label: msg({ id: "settings.youtube-languages.mine", message: "Only in the path's language" }) },
      { value: "also_english", label: msg({ id: "settings.youtube-languages.also-english", message: "Also in English" }) },
    ],
  },
  "video.length": {
    kind: "select",
    options: [
      { value: "short", label: msg({ id: "settings.video-length.short", message: "Short" }) },
      { value: "medium", label: msg({ id: "settings.video-length.medium", message: "Medium" }) },
      { value: "long", label: msg({ id: "settings.video-length.long", message: "Long" }) },
    ],
  },
  "video.theme": {
    kind: "select",
    options: [
      { value: "match_app", label: msg({ id: "settings.video-theme.match-app", message: "Match the app" }) },
      { value: "light", label: msg({ id: "settings.video-theme.light", message: "Light" }) },
      { value: "dark", label: msg({ id: "settings.video-theme.dark", message: "Dark" }) },
    ],
  },
  "video.captions": { kind: "switch" },
  "video.notes_bubble": { kind: "switch" },
  "tutor.name": { kind: "text", max: 30, singleLine: true },
  "tutor.memory": { kind: "switch" },
  "tutor.muted_triggers": {
    kind: "literals",
    options: Object.entries(TRIGGER_NAMES).map(([value, label]) => ({ value, label })),
    empty: msg({ id: "settings.muted.none", message: "None" }),
  },
};

export const LABELS: Record<string, MessageDescriptor> = {
  "review.independent": msg({ id: "settings.key.review-independent", message: "Independent reviewer" }),
  "lesson.reading_length": msg({ id: "settings.key.reading-length", message: "Lesson length" }),
  "material.transcription": msg({ id: "settings.key.transcription", message: "Transcribing recordings" }),
  "budget.cap_usd_month": msg({ id: "settings.key.budget", message: "Monthly budget cap" }),
  custom_instructions: msg({ id: "settings.key.custom-instructions", message: "Custom instructions" }),
  "generation.buffer": msg({ id: "settings.key.buffer", message: "Lessons prepared ahead" }),
  "skill_test.pass_mark": msg({ id: "settings.key.pass-mark", message: "Skill test pass mark" }),
  "reviews.max_per_day": msg({ id: "settings.key.reviews-per-day", message: "Reviews per day" }),
  "review.bank_size": msg({ id: "settings.key.review-bank-size", message: "Review questions per lesson" }),
  "review.desired_retention": msg({ id: "settings.key.review-retention", message: "Target recall at review time" }),
  "review.max_interval_days": msg({
    id: "settings.key.review-max-interval",
    message: "Longest gap between reviews (days, 0 = no limit)",
  }),
  "mastery.decay": msg({ id: "settings.key.decay", message: "Mastery fades without review" }),
  "practice.solution_after": msg({ id: "settings.key.solution-after", message: "Show solutions" }),
  gamification: msg({ id: "settings.key.gamification", message: "Game elements" }),
  "streak.grace_days": msg({ id: "settings.key.grace-days", message: "Streak grace days" }),
  "practice.types": msg({ id: "settings.key.practice-types", message: "Question types" }),
  "video.format": msg({ id: "settings.key.video-format", message: "Lesson videos" }),
  "video.source": msg({ id: "settings.key.video-source", message: "Where videos come from" }),
  "video.youtube_languages": msg({ id: "settings.key.youtube-languages", message: "YouTube video languages" }),
  "video.length": msg({ id: "settings.key.video-length", message: "Video length" }),
  "video.theme": msg({ id: "settings.key.video-theme", message: "Video colours" }),
  "video.captions": msg({ id: "settings.key.video-captions", message: "Video captions" }),
  "video.notes_bubble": msg({ id: "settings.key.video-notes-bubble", message: "Questions bubble on videos" }),
  "tutor.proactivity": msg({ id: "settings.key.tutor-proactivity", message: "Tutor suggestions" }),
  "tutor.test_policy": msg({ id: "settings.key.tutor-test-policy", message: "Tutor during skill tests" }),
  "tutor.name": msg({ id: "settings.key.tutor-name", message: "Tutor's name" }),
  "tutor.tone": msg({ id: "settings.key.tutor-tone", message: "Tutor's tone" }),
  "tutor.memory": msg({ id: "settings.key.tutor-memory", message: "Tutor memory" }),
  "tutor.muted_triggers": msg({ id: "settings.key.tutor-muted", message: "Suggestions you turned off" }),
  "updates.check": msg({ id: "settings.key.updates-check", message: "Check for updates" }),
};

const SOURCES: Record<string, MessageDescriptor> = {
  installation: msg({ id: "settings.source.installation", message: "set for this installation" }),
  learner: msg({ id: "settings.source.learner", message: "your setting" }),
  path: msg({ id: "settings.source.path", message: "set for a path" }),
  lesson: msg({ id: "settings.source.lesson", message: "set for a lesson" }),
};

const IMPACTS: Record<string, MessageDescriptor> = {
  cost: msg({ id: "settings.impact.cost", message: "cost" }),
  time: msg({ id: "settings.impact.time", message: "time" }),
  learning: msg({ id: "settings.impact.learning", message: "learning" }),
  privacy: msg({ id: "settings.impact.privacy", message: "privacy" }),
};

/** The element id of a setting, for links like /settings#setting-tutor-memory. */
function settingAnchor(key: string): string {
  return `setting-${key.replace(/[^a-z0-9]+/gi, "-")}`;
}

function editorFor(s: SettingOut): Editor | null {
  const known = EDITORS[s.key];
  if (known) return known;
  const v = s.value ?? s.default;
  if (typeof v === "boolean") return { kind: "switch" };
  if (typeof v === "number") return { kind: "number", min: -1e9, max: 1e9, step: Number.isInteger(v) ? 1 : 0.01 };
  if (typeof v === "string") return { kind: "text", max: 1000 };
  return null;
}

function formatValue(value: unknown, i18n: ReturnType<typeof useLinguiRuntime>["i18n"], editor: Editor | null): string {
  if (value === null || value === undefined) return "—";
  if (editor?.kind === "number" && editor.percent && typeof value === "number") {
    return i18n.number(value, { style: "percent" });
  }
  if (editor?.kind === "select") {
    const o = editor.options.find((x) => x.value === value);
    if (o) return i18n._(o.label);
  }
  if (typeof value === "boolean") return value ? i18n._(msg({ id: "settings.on", message: "On" })) : i18n._(msg({ id: "settings.off", message: "Off" }));
  if (Array.isArray(value)) {
    if (editor?.kind === "literals") {
      if (!value.length) return i18n._(editor.empty);
      const names = new Map(editor.options.map((o) => [o.value, i18n._(o.label)]));
      return value.map((v) => names.get(String(v)) ?? String(v)).join(", ");
    }
    const names = new Map(ITEM_TYPES.map((t) => [t.value as string, i18n._(t.label)]));
    return value.map((v) => names.get(String(v)) ?? String(v)).join(", ");
  }
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function ValueEditor({
  editor,
  label,
  value,
  onChange,
}: {
  editor: Editor;
  label: string;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  switch (editor.kind) {
    case "switch":
      return (
        <Switch className={styles.switch} isSelected={value === true} onChange={onChange}>
          <span className={styles.track} aria-hidden="true">
            <span className={styles.thumb} />
          </span>
          {label}
        </Switch>
      );
    case "number":
      return (
        <NumberField
          className={ui.field}
          value={typeof value === "number" ? value : Number.NaN}
          onChange={onChange}
          minValue={editor.min}
          maxValue={editor.max}
          step={editor.step}
          formatOptions={editor.percent ? { style: "percent" } : { maximumFractionDigits: 2 }}
        >
          <Label className={ui.label}>{label}</Label>
          <Group className={styles.numberGroup}>
            <AriaButton slot="decrement" className={`${ui.button} ${ui.secondary} ${ui.small}`}>
              −
            </AriaButton>
            <Input className={`${ui.input} ${styles.numberInput}`} />
            <AriaButton slot="increment" className={`${ui.button} ${ui.secondary} ${ui.small}`}>
              +
            </AriaButton>
          </Group>
        </NumberField>
      );
    case "select":
      return (
        <Select
          className={ui.field}
          selectedKey={typeof value === "string" ? value : null}
          onSelectionChange={(k) => onChange(String(k))}
        >
          <Label className={ui.label}>{label}</Label>
          <AriaButton className={`${ui.input} ${itemStyles.selectButton}`}>
            <SelectValue />
            <span aria-hidden="true">▾</span>
          </AriaButton>
          <Popover className={itemStyles.popover}>
            <ListBox className={itemStyles.listbox}>
              {editor.options.map((o) => (
                <ListBoxItem key={o.value} id={o.value} className={itemStyles.option} textValue={i18n._(o.label)}>
                  {i18n._(o.label)}
                </ListBoxItem>
              ))}
            </ListBox>
          </Popover>
        </Select>
      );
    case "types": {
      const all = value === null || value === undefined;
      const chosen = Array.isArray(value) ? value.map(String) : ITEM_TYPES.map((x) => x.value);
      return (
        <div className={ui.stack}>
          <Switch className={styles.switch} isSelected={all} onChange={(on) => onChange(on ? null : chosen)}>
            <span className={styles.track} aria-hidden="true">
              <span className={styles.thumb} />
            </span>
            {t({ id: "settings.types.all", message: "Use all question types" })}
          </Switch>
          {all ? null : (
            <CheckboxGroup className={ui.radioGroup} value={chosen} onChange={onChange}>
              <Label className={ui.label}>{label}</Label>
              <div className={ui.radioList}>
                {ITEM_TYPES.map((x) => (
                  <Checkbox key={x.value} value={x.value} className={`${ui.radio} ${itemStyles.checkbox}`}>
                    {i18n._(x.label)}
                  </Checkbox>
                ))}
              </div>
            </CheckboxGroup>
          )}
        </div>
      );
    }
    case "literals": {
      const chosen = Array.isArray(value) ? value.map(String) : [];
      return (
        <CheckboxGroup className={ui.radioGroup} value={chosen} onChange={onChange}>
          <Label className={ui.label}>{label}</Label>
          <div className={ui.radioListStacked}>
            {editor.options.map((x) => (
              <Checkbox key={x.value} value={x.value} className={`${ui.radio} ${itemStyles.checkbox}`}>
                {i18n._(x.label)}
              </Checkbox>
            ))}
          </div>
        </CheckboxGroup>
      );
    }
    case "text":
      return (
        <Field
          label={label}
          value={typeof value === "string" ? value : ""}
          onChange={onChange}
          maxLength={editor.max}
          multiline={!editor.singleLine}
        />
      );
  }
}

export function SettingRow({ setting }: { setting: SettingOut }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const put = usePutSetting();
  const [draft, setDraft] = useState<unknown>(setting.value);
  const [dirty, setDirty] = useState(false);
  const editor = editorFor(setting);
  const label = LABELS[setting.key] ? i18n._(LABELS[setting.key]!) : setting.key;
  const editable = setting.levels.includes("learner") && editor !== null;
  const source = setting.source ? (SOURCES[setting.source] ? i18n._(SOURCES[setting.source]!) : setting.source) : null;
  const current = formatValue(setting.value, i18n, editor);
  const fallback = formatValue(setting.default, i18n, editor);

  return (
    <li className={styles.setting} data-key={setting.key} id={settingAnchor(setting.key)}>
      <h3 className={styles.title}>{label}</h3>
      <p>{setting.explanation}</p>
      {setting.key === "tutor.memory" ? (
        <p>
          <Link to="/tutor/memory">
            <Trans id="settings.tutor-memory.link">See and edit what the tutor remembers</Trans>
          </Link>
        </p>
      ) : null}
      <p className={ui.muted}>
        {source ? (
          <Trans id="settings.current.source">
            Now: {current} ({source})
          </Trans>
        ) : (
          <Trans id="settings.current.default">Now: {current} (default)</Trans>
        )}
        {" · "}
        <Trans id="settings.default">Default: {fallback}</Trans>
      </p>
      {setting.impact.length > 0 ? (
        <ul className={styles.tags} aria-label={t({ id: "settings.impact.label", message: "Affects" })}>
          {setting.impact.map((x) => (
            <li key={x} className={styles.tag}>
              {IMPACTS[x] ? i18n._(IMPACTS[x]!) : x}
            </li>
          ))}
        </ul>
      ) : null}
      {setting.weakens_learning ? (
        <Notice tone="warning">
          <Trans id="settings.weakens">Weakens learning:</Trans> {setting.weakens_learning}
        </Notice>
      ) : null}
      <details>
        <summary>
          <Trans id="settings.more">Example and suggestion</Trans>
        </summary>
        <p>{setting.example}</p>
        <p className={ui.muted}>{setting.suggestion}</p>
      </details>

      {editable && editor ? (
        <form
          className={styles.editor}
          onSubmit={(e) => {
            e.preventDefault();
            put.mutate({ key: setting.key, value: draft }, { onSuccess: () => setDirty(false) });
          }}
        >
          <ValueEditor
            editor={editor}
            label={label}
            value={draft}
            onChange={(v) => {
              setDraft(v);
              setDirty(true);
              put.reset();
            }}
          />
          <div className={ui.row}>
            <Button
              type="submit"
              small
              isDisabled={!dirty || put.isPending}
              aria-label={t({ id: "settings.save.label", message: `Save ${label}` })}
            >
              <Trans id="settings.save">Save</Trans>
            </Button>
            {put.isSuccess && !dirty ? (
              <span className={ui.muted} role="status">
                <Trans id="settings.saved">Saved.</Trans>
              </span>
            ) : null}
          </div>
          {put.isError ? <ErrorNotice error={put.error} /> : null}
        </form>
      ) : (
        <p className={ui.muted}>
          <Trans id="settings.read-only">This is set for the whole installation.</Trans>
        </p>
      )}
    </li>
  );
}
