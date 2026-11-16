// Small styled wrappers over React Aria Components. Labels are passed in already
// translated; this module has no strings of its own.
import { createLink } from "@tanstack/react-router";
import { forwardRef, type AnchorHTMLAttributes, type ReactNode } from "react";
import {
  Button as AriaButton,
  Disclosure,
  DisclosurePanel,
  FieldError,
  Input,
  Label,
  Radio,
  RadioGroup,
  Text,
  TextArea,
  TextField,
  type ButtonProps as AriaButtonProps,
} from "react-aria-components";
import { AlertIcon, ArrowLeftIcon, CheckIcon, CloseIcon } from "./icons";
import styles from "./ui.module.css";

type Variant = "primary" | "secondary" | "ghost";

function buttonClass(variant: Variant = "primary", small = false): string {
  return [
    styles.button,
    variant === "secondary" && styles.secondary,
    variant === "ghost" && styles.ghost,
    small && styles.small,
  ]
    .filter(Boolean)
    .join(" ");
}

type ButtonProps = Omit<AriaButtonProps, "className"> & { variant?: Variant; small?: boolean };

export function Button({ variant, small, ...props }: ButtonProps) {
  return <AriaButton {...props} className={buttonClass(variant, small)} />;
}

type AnchorProps = AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant; small?: boolean };

const StyledAnchor = forwardRef<HTMLAnchorElement, AnchorProps>(function StyledAnchor(
  { variant, small, className: _ignored, ...props },
  ref,
) {
  return <a ref={ref} {...props} className={buttonClass(variant, small)} />;
});

/** A router link that looks like a button. */
export const ButtonLink = createLink(StyledAnchor);

const BackAnchor = forwardRef<HTMLAnchorElement, AnchorHTMLAttributes<HTMLAnchorElement>>(function BackAnchor(
  { className: _ignored, children, ...props },
  ref,
) {
  return (
    <a ref={ref} {...props} className={styles.backLink}>
      <ArrowLeftIcon size="1.1em" />
      <span>{children}</span>
    </a>
  );
});

/** "← Back to …": the quiet way up from a page (a router link with a leading arrow). */
export const BackLink = createLink(BackAnchor);

/**
 * The top of a page: an optional way back, an eyebrow, the h1, a line of meta and actions on the trailing side
 * (they wrap below the title on a phone).
 */
export function PageHeader({
  back,
  eyebrow,
  title,
  meta,
  actions,
  titleId,
}: {
  back?: ReactNode;
  eyebrow?: ReactNode;
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  titleId?: string;
}) {
  return (
    <header className={styles.pageHeader}>
      {back ? <nav className={styles.pageBack}>{back}</nav> : null}
      <div className={styles.pageHeaderRow}>
        <div className={styles.pageHeaderMain}>
          {eyebrow ? <p className={styles.eyebrow}>{eyebrow}</p> : null}
          <h1 id={titleId} className={styles.pageTitle}>
            {title}
          </h1>
          {meta ? <div className={styles.pageMeta}>{meta}</div> : null}
        </div>
        {actions ? <div className={styles.row}>{actions}</div> : null}
      </div>
    </header>
  );
}

type FieldProps = {
  label: string;
  description?: ReactNode;
  value: string;
  onChange: (value: string) => void;
  isRequired?: boolean;
  maxLength?: number;
  name?: string;
  multiline?: boolean;
  errorMessage?: string;
};

export function Field({ label, description, multiline, errorMessage, ...props }: FieldProps) {
  return (
    <TextField {...props} className={styles.field}>
      <Label className={styles.label}>{label}</Label>
      {multiline ? (
        <TextArea className={`${styles.input} ${styles.textarea}`} />
      ) : (
        <Input className={styles.input} />
      )}
      {description ? (
        <Text slot="description" className={styles.description}>
          {description}
        </Text>
      ) : null}
      <FieldError className={styles.fieldError}>{errorMessage}</FieldError>
    </TextField>
  );
}

export type Choice<T extends string> = { value: T; label: string; description?: string };

/** After an answer is checked: the right choice, and a chosen one that was not right. */
export type ChoiceMark = "right" | "wrong";

type ChoiceFieldProps<T extends string> = {
  label: string;
  choices: Choice<T>[];
  value: T | null;
  onChange: (value: T) => void;
  isDisabled?: boolean;
  stacked?: boolean;
  /** marks shown after checking, with the words read for them (the icon is decorative) */
  marks?: Partial<Record<T, ChoiceMark>>;
  markLabels?: Record<ChoiceMark, string>;
};

export function ChoiceField<T extends string>({
  label,
  choices,
  value,
  onChange,
  isDisabled,
  stacked,
  marks,
  markLabels,
}: ChoiceFieldProps<T>) {
  return (
    <RadioGroup
      className={styles.radioGroup}
      value={value}
      onChange={(v) => onChange(v as T)}
      isDisabled={isDisabled}
    >
      <Label className={styles.label}>{label}</Label>
      <div className={stacked ? styles.radioListStacked : styles.radioList}>
        {choices.map((c) => {
          const mark = marks?.[c.value];
          return (
            <Radio key={c.value} value={c.value} className={styles.radio} data-mark={mark}>
              <span className={styles.radioText}>
                {c.label}
                {c.description ? <span className={styles.description}> {c.description}</span> : null}
              </span>
              {mark ? <ChoiceMarkView mark={mark} label={markLabels?.[mark]} /> : null}
            </Radio>
          );
        })}
      </div>
    </RadioGroup>
  );
}

/** The icon and the words after a checked choice ("right answer", "your answer"). */
export function ChoiceMarkView({ mark, label }: { mark: ChoiceMark; label?: string }) {
  return (
    <span className={styles.choiceMark} data-mark={mark}>
      {mark === "right" ? <CheckIcon size="1rem" /> : <CloseIcon size="1rem" />}
      {label ? <span className={styles.choiceMarkText}>{label}</span> : null}
    </span>
  );
}

type Tone = "info" | "warning" | "error" | "success";
type NoticeProps = {
  tone?: Tone;
  children: ReactNode;
  role?: string;
  /** a leading icon: `true` for the tone's own (check, alert), or any icon */
  icon?: ReactNode | true;
  /** extra classes, e.g. a one-off motion from Grove.tsx (`grove.appear`, `grove.nudge`) */
  className?: string;
};

const TONE_ICON: Record<Tone, ReactNode> = {
  info: null,
  success: <CheckIcon />,
  warning: <AlertIcon />,
  error: <AlertIcon />,
};

export function Notice({ tone = "info", children, role, icon, className }: NoticeProps) {
  const toneClass = {
    info: "",
    warning: styles.noticeWarning,
    error: styles.noticeError,
    success: styles.noticeSuccess,
  }[tone];
  const shownIcon = icon === true ? TONE_ICON[tone] : icon;
  return (
    <div
      className={`${styles.notice} ${toneClass} ${shownIcon ? styles.noticeWithIcon : ""} ${className ?? ""}`}
      role={role ?? (tone === "error" ? "alert" : undefined)}
    >
      {shownIcon ? (
        <>
          <span className={styles.noticeIcon} aria-hidden="true">
            {shownIcon}
          </span>
          <div className={styles.noticeBody}>{children}</div>
        </>
      ) : (
        children
      )}
    </div>
  );
}

/** A bar from 0 to `max`; pollen while growing, forest when full. `label` names it for screen readers. */
export function Progress({
  value,
  max = 100,
  label,
  showValue = true,
}: {
  value: number;
  max?: number;
  label: string;
  showValue?: boolean;
}) {
  const pct = max > 0 ? Math.max(0, Math.min(100, Math.round((value / max) * 100))) : 0;
  return (
    <div
      className={`${styles.progress} ${pct === 100 ? styles.progressDone : ""}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
    >
      <span className={styles.progressTrack}>
        <span className={styles.progressFill} style={{ inlineSize: `${pct}%` }} />
      </span>
      {showValue ? <span className={styles.progressValue}>{pct}%</span> : null}
    </div>
  );
}

/** A small turning ring beside text that says what is happening (the text is the accessible part). */
export function Waiting({ children }: { children: ReactNode }) {
  return (
    <p className={styles.waiting} role="status">
      <span className={styles.spinner} aria-hidden="true" />
      <span>{children}</span>
    </p>
  );
}

type StepState = "done" | "current" | "todo";
export type Step = { id: string; label: ReactNode; state: StepState };

/**
 * Numbered steps joined by a line: done ones carry a check, the current one is filled (aria-current="step").
 * `vertical` stacks them (a progress list, e.g. a path being planned); `doneLabel` is read after a done step.
 */
export function Stepper({
  steps,
  label,
  vertical,
  doneLabel,
}: {
  steps: Step[];
  label?: string;
  vertical?: boolean;
  doneLabel?: string;
}) {
  return (
    <ol className={`${styles.stepper} ${vertical ? styles.stepperVertical : ""}`} aria-label={label}>
      {steps.map((s, i) => (
        <li
          key={s.id}
          className={styles.step}
          data-state={s.state}
          aria-current={s.state === "current" ? "step" : undefined}
        >
          <span className={styles.stepMarker} aria-hidden="true">
            {s.state === "done" ? <CheckIcon size="0.95rem" /> : vertical ? null : i + 1}
          </span>
          <span className={styles.stepLabel}>{s.label}</span>
          {s.state === "done" && doneLabel ? <span className="visually-hidden">{doneLabel}</span> : null}
        </li>
      ))}
    </ol>
  );
}

type CardChoice<T extends string> = {
  value: T;
  label: ReactNode;
  description?: ReactNode;
  /** a decorative icon on the leading side */
  icon?: ReactNode;
  /** next to the label, e.g. "Recommended" */
  badge?: ReactNode;
  /** below the description, e.g. a cost estimate */
  extra?: ReactNode;
  describedBy?: string;
};

/**
 * Radio cards: an icon, a name and a line of description, the radio on the trailing side; the selected card
 * is outlined in forest. `compact` lays short choices out in a grid of small cards.
 */
export function ChoiceCards<T extends string>({
  label,
  choices,
  value,
  onChange,
  compact,
  isDisabled,
}: {
  label: ReactNode;
  choices: CardChoice<T>[];
  value: T | null;
  onChange: (value: T) => void;
  compact?: boolean;
  isDisabled?: boolean;
}) {
  return (
    <RadioGroup
      className={styles.radioGroup}
      value={value}
      onChange={(v) => onChange(v as T)}
      isDisabled={isDisabled}
    >
      <Label className={styles.label}>{label}</Label>
      <div className={compact ? styles.choiceGrid : styles.radioListStacked}>
        {choices.map((c) => (
          <Radio
            key={c.value}
            value={c.value}
            className={`${styles.choiceCard} ${compact ? styles.choiceCardCompact : ""}`}
            aria-describedby={c.describedBy}
          >
            {c.icon ? <span className={styles.choiceIcon}>{c.icon}</span> : null}
            <span className={styles.choiceBody}>
              <span className={styles.choiceName}>
                {c.label}
                {c.badge}
              </span>
              {c.description ? <span className={styles.choiceDescription}>{c.description}</span> : null}
              {c.extra ? <span className={styles.choiceExtra}>{c.extra}</span> : null}
            </span>
            <span className={styles.choiceRadio} aria-hidden="true" />
          </Radio>
        ))}
      </div>
    </RadioGroup>
  );
}

/** Optional or secondary content behind a quiet "more" toggle (React Aria Disclosure). */
export function MoreOptions({
  title,
  children,
  defaultExpanded,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultExpanded?: boolean;
}) {
  return (
    <Disclosure className={styles.more} defaultExpanded={defaultExpanded}>
      <AriaButton slot="trigger" className={styles.moreTrigger}>
        <svg className={styles.moreChevron} viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
          <path d="M6 3.5L10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {title}
      </AriaButton>
      <DisclosurePanel className={styles.morePanel}>{children}</DisclosurePanel>
    </Disclosure>
  );
}

export function Badge({ tone, children }: { tone?: "highlight" | "success"; children: ReactNode }) {
  const toneClass = tone === "highlight" ? styles.badgeHighlight : tone === "success" ? styles.badgeSuccess : "";
  return <span className={`${styles.badge} ${toneClass}`}>{children}</span>;
}

export { styles as ui };
