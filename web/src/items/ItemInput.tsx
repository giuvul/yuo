// Item renderers for the seven exercise types. Each is keyboard-usable: ordering uses move
// up/down buttons, matching uses a select menu per row (no drag-only UI). Item text is shown as
// plain text, never markup.
import { useLingui } from "@lingui/react/macro";
import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import {
  Button as AriaButton,
  Checkbox,
  CheckboxGroup,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Select,
  SelectValue,
  TextArea,
  TextField,
} from "react-aria-components";
import { useState } from "react";
import type { Item } from "../api/client";
import { fetchReveal } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button } from "../components/ui";
import { ChoiceField, ChoiceMarkView, ui, type ChoiceMark } from "../components/ui";
import { clozeParts, move, RATINGS, type Draft } from "./answers";
import styles from "./items.module.css";

type Props = {
  item: Item;
  draft: Draft;
  onChange: (d: Draft) => void;
  disabled?: boolean;
  /** the graded answer key once the answer is checked: choices are then marked right / wrong */
  correct?: unknown;
};

const asIds = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : typeof v === "string" ? [v] : [];

/** Right choices, and chosen ones that were not right; nothing before the answer is checked. */
export function choiceMarks(correct: unknown, chosen: string[]): Partial<Record<string, ChoiceMark>> | undefined {
  if (correct === undefined || correct === null) return undefined;
  const right = new Set(asIds(correct));
  const marks: Partial<Record<string, ChoiceMark>> = {};
  for (const id of right) marks[id] = "right";
  for (const id of chosen) if (!right.has(id)) marks[id] = "wrong";
  return marks;
}

function useMarkLabels(): Record<ChoiceMark, string> {
  const { t } = useLingui();
  return {
    right: t({ id: "item.mark.right", message: "Right answer" }),
    wrong: t({ id: "item.mark.wrong", message: "Your answer" }),
  };
}

const RATING_LABEL: Record<number, MessageDescriptor> = {
  1: msg({ id: "item.flashcard.rating.again", message: "Again" }),
  2: msg({ id: "item.flashcard.rating.hard", message: "Hard" }),
  3: msg({ id: "item.flashcard.rating.good", message: "Good" }),
  4: msg({ id: "item.flashcard.rating.easy", message: "Easy" }),
};

/** The question text of an item (cloze and flashcards carry it in their own fields). */
export function itemPrompt(item: Item): string {
  switch (item.type) {
    case "cloze":
      return "";
    case "flashcard":
      return item.view.front;
    default:
      return item.view.prompt;
  }
}

function Mcq({ item, draft, onChange, disabled, correct }: Props) {
  const { t } = useLingui();
  const markLabels = useMarkLabels();
  if (item.type !== "mcq" || draft.type !== "mcq") return null;
  return (
    <ChoiceField
      label={t({ id: "item.answer.label", message: "Your answer" })}
      choices={item.view.options.map((o) => ({ value: o.id, label: `${o.id}. ${o.text}` }))}
      value={draft.choice}
      onChange={(choice) => onChange({ type: "mcq", choice })}
      isDisabled={disabled}
      stacked
      marks={choiceMarks(correct, draft.choice ? [draft.choice] : [])}
      markLabels={markLabels}
    />
  );
}

function Multi({ item, draft, onChange, disabled, correct }: Props) {
  const { t } = useLingui();
  const markLabels = useMarkLabels();
  if (item.type !== "multi" || draft.type !== "multi") return null;
  const marks = choiceMarks(correct, draft.choices);
  return (
    <CheckboxGroup
      className={ui.radioGroup}
      value={draft.choices}
      onChange={(choices) => onChange({ type: "multi", choices })}
      isDisabled={disabled}
    >
      <Label className={ui.label}>{t({ id: "item.multi.label", message: "Select all that apply" })}</Label>
      <div className={ui.radioListStacked}>
        {item.view.options.map((o) => {
          const mark = marks?.[o.id];
          return (
            <Checkbox key={o.id} value={o.id} className={`${ui.radio} ${styles.checkbox}`} data-mark={mark}>
              <span className={ui.radioText}>{`${o.id}. ${o.text}`}</span>
              {mark ? <ChoiceMarkView mark={mark} label={markLabels[mark]} /> : null}
            </Checkbox>
          );
        })}
      </div>
    </CheckboxGroup>
  );
}

function Cloze({ item, draft, onChange, disabled }: Props) {
  const { t } = useLingui();
  if (item.type !== "cloze" || draft.type !== "cloze") return null;
  const set = (i: number, v: string) =>
    onChange({ type: "cloze", gaps: draft.gaps.map((g, j) => (j === i ? v : g)) });
  return (
    <p className={styles.cloze}>
      {clozeParts(item.view.text).map((part, k) => {
        if (typeof part === "string") return <span key={k}>{part}</span>;
        const i = part - 1;
        if (i < 0 || i >= draft.gaps.length) return <span key={k}>…</span>;
        const n = part;
        return (
          <TextField
            key={k}
            className={styles.gap}
            value={draft.gaps[i] ?? ""}
            onChange={(v) => set(i, v)}
            isDisabled={disabled}
            aria-label={t({ id: "item.cloze.gap", message: `Gap ${n}` })}
          >
            <Input className={`${ui.input} ${styles.gapInput}`} />
          </TextField>
        );
      })}
    </p>
  );
}

function Ordering({ item, draft, onChange, disabled }: Props) {
  const { t } = useLingui();
  if (item.type !== "ordering" || draft.type !== "ordering") return null;
  const text = new Map(item.view.steps.map((s) => [s.id, s.text]));
  const last = draft.order.length - 1;
  return (
    <div className={ui.stack}>
      <p className={ui.label} id={`order-${item.item_version_id}`}>
        {t({ id: "item.ordering.label", message: "Put the steps in order" })}
      </p>
      <ol className={styles.ordering} aria-labelledby={`order-${item.item_version_id}`}>
        {draft.order.map((id, i) => {
          const step = text.get(id) ?? id;
          return (
            <li key={id} className={styles.orderRow}>
              <span className={styles.orderText}>{step}</span>
              <span className={ui.row}>
                <AriaButton
                  className={`${ui.button} ${ui.secondary} ${ui.small}`}
                  isDisabled={disabled || i === 0}
                  onPress={() => onChange({ type: "ordering", order: move(draft.order, i, i - 1) })}
                  aria-label={t({ id: "item.ordering.up", message: `Move up: ${step}` })}
                >
                  ↑
                </AriaButton>
                <AriaButton
                  className={`${ui.button} ${ui.secondary} ${ui.small}`}
                  isDisabled={disabled || i === last}
                  onPress={() => onChange({ type: "ordering", order: move(draft.order, i, i + 1) })}
                  aria-label={t({ id: "item.ordering.down", message: `Move down: ${step}` })}
                >
                  ↓
                </AriaButton>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Matching({ item, draft, onChange, disabled }: Props) {
  const { t } = useLingui();
  if (item.type !== "matching" || draft.type !== "matching") return null;
  return (
    <div className={styles.matching}>
      {item.view.left.map((left) => (
        <Select
          key={left}
          className={styles.matchRow}
          selectedKey={draft.pairs[left] ?? null}
          onSelectionChange={(key) =>
            onChange({ type: "matching", pairs: { ...draft.pairs, [left]: String(key) } })
          }
          isDisabled={disabled}
          placeholder={t({ id: "item.matching.placeholder", message: "Choose a match" })}
        >
          <Label className={styles.matchLeft}>{left}</Label>
          <AriaButton className={`${ui.input} ${styles.selectButton}`}>
            <SelectValue />
            <span aria-hidden="true">▾</span>
          </AriaButton>
          <Popover className={styles.popover}>
            <ListBox className={styles.listbox}>
              {item.view.right.map((right) => (
                <ListBoxItem key={right} id={right} className={styles.option} textValue={right}>
                  {right}
                </ListBoxItem>
              ))}
            </ListBox>
          </Popover>
        </Select>
      ))}
    </div>
  );
}

function Flashcard({ item, draft, onChange, disabled }: Props) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (item.type !== "flashcard" || draft.type !== "flashcard") return null;

  if (draft.back === null) {
    const reveal = async () => {
      setLoading(true);
      setError(null);
      try {
        const { back } = await fetchReveal(item.item_version_id);
        onChange({ ...draft, back });
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    };
    return (
      <div className={ui.stack}>
        <p className={ui.muted}>
          {t({ id: "item.flashcard.recall", message: "Recall the answer in your head, then turn the card." })}
        </p>
        <div>
          <Button onPress={() => void reveal()} isDisabled={disabled || loading}>
            {t({ id: "item.flashcard.show", message: "Show answer" })}
          </Button>
        </div>
        {error ? <ErrorNotice error={error} /> : null}
      </div>
    );
  }

  const back = draft.back;
  return (
    <div className={ui.stack}>
      <div className={styles.cardBack}>
        <p className={styles.label}>{t({ id: "item.flashcard.back", message: "Answer" })}</p>
        <p className={styles.preWrap}>{back}</p>
      </div>
      <ChoiceField
        label={t({
          id: "item.flashcard.rate",
          message: "How well did you know it?",
        })}
        choices={RATINGS.map((r) => ({ value: String(r), label: i18n._(RATING_LABEL[r]!) }))}
        value={draft.rating === null ? null : String(draft.rating)}
        onChange={(v) => onChange({ ...draft, rating: Number(v) })}
        isDisabled={disabled}
      />
    </div>
  );
}

function ShortAnswer({ item, draft, onChange, disabled }: Props) {
  const { t } = useLingui();
  if (item.type !== "short_answer" || draft.type !== "short_answer") return null;
  return (
    <TextField
      className={ui.field}
      value={draft.text}
      onChange={(text) => onChange({ type: "short_answer", text })}
      isDisabled={disabled}
      maxLength={4000}
    >
      <Label className={ui.label}>{t({ id: "item.short-answer.label", message: "Your answer (one to three sentences)" })}</Label>
      <TextArea className={`${ui.input} ${ui.textarea}`} />
    </TextField>
  );
}

/** The input part of an item; the prompt is rendered by the caller (see itemPrompt). */
export function ItemInput(props: Props) {
  switch (props.item.type) {
    case "mcq":
      return <Mcq {...props} />;
    case "multi":
      return <Multi {...props} />;
    case "cloze":
      return <Cloze {...props} />;
    case "ordering":
      return <Ordering {...props} />;
    case "matching":
      return <Matching {...props} />;
    case "flashcard":
      return <Flashcard {...props} />;
    case "short_answer":
      return <ShortAnswer {...props} />;
    default:
      return null;
  }
}
