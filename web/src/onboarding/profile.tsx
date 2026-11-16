// The learner's profile (GET/PATCH /api/me): name, languages, time zone, session length, interests and
// the theme. Shared by the wizard's "About you" step and Settings.
import { Trans, useLingui } from "@lingui/react/macro";
import { useMemo, useState, type ReactNode } from "react";
import {
  Button as AriaButton,
  ComboBox,
  Group,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  NumberField,
  Popover,
  Radio,
  RadioGroup,
  Select,
  SelectValue,
  Text,
} from "react-aria-components";
import type { MeIn, MeOut, SetupAnswersProfile, Theme } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button, Field, MoreOptions, ui } from "../components/ui";
import { browserLocale, isDefaultProfile, localeName, locales, shippedLocale } from "../i18n";
import itemStyles from "../items/items.module.css";
import { applyTheme } from "../theme";
import { useUpdateMe } from "./api";
import styles from "./onboarding.module.css";

const INTERESTS_MAX = 500;
const SESSION_MIN = 5;
const SESSION_MAX = 120;

/** Languages offered for lessons; the stored one is added when it is not among them. */
const CONTENT_LANGS = ["en", "de", "fr", "es", "it", "pt", "nl", "pl", "cs", "sv", "da", "fi", "nb", "tr", "uk", "ru",
  "ja", "zh", "ko", "hi", "ar"]; // prettier-ignore

/** This browser's time zone, or null when it cannot tell. */
function browserTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

function timeZones(current: string): string[] {
  let zones: string[] = [];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    zones = [];
  }
  const all = new Set(zones);
  all.add("UTC");
  if (current) all.add(current);
  return [...all].sort();
}

type Option = { id: string; name: string };

function SelectField({
  label,
  options,
  value,
  onChange,
  description,
}: {
  label: string;
  options: Option[];
  value: string;
  onChange: (v: string) => void;
  description?: ReactNode;
}) {
  return (
    <Select className={ui.field} selectedKey={value} onSelectionChange={(k) => k !== null && onChange(String(k))}>
      <Label className={ui.label}>{label}</Label>
      <AriaButton className={`${ui.input} ${itemStyles.selectButton}`}>
        <SelectValue />
        <span aria-hidden="true">▾</span>
      </AriaButton>
      {description ? (
        <Text slot="description" className={ui.description}>
          {description}
        </Text>
      ) : null}
      <Popover className={itemStyles.popover}>
        <ListBox className={itemStyles.listbox}>
          {options.map((o) => (
            <ListBoxItem key={o.id} id={o.id} className={itemStyles.option} textValue={o.name}>
              {o.name}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </Select>
  );
}

/** System, light or dark; applied and saved at once. */
export function ThemePicker({ value }: { value: Theme }) {
  const { t } = useLingui();
  const save = useUpdateMe();
  const [theme, setTheme] = useState<Theme>(value);
  const choices: { value: Theme; label: string }[] = [
    { value: "system", label: t({ id: "profile.theme.system", message: "Same as my computer" }) },
    { value: "light", label: t({ id: "profile.theme.light", message: "Light" }) },
    { value: "dark", label: t({ id: "profile.theme.dark", message: "Dark" }) },
  ];
  return (
    <div className={ui.stack}>
      <RadioGroup
        className={ui.radioGroup}
        value={theme}
        onChange={(v) => {
          const next = v as Theme;
          setTheme(next);
          applyTheme(next);
          save.mutate({ theme: next });
        }}
      >
        <Label className={ui.label}>{t({ id: "profile.theme.label", message: "Colours" })}</Label>
        <div className={ui.radioList}>
          {choices.map((c) => (
            <Radio key={c.value} value={c.value} className={ui.radio}>
              {c.label}
            </Radio>
          ))}
        </div>
      </RadioGroup>
      {save.isError ? <ErrorNotice error={save.error} /> : null}
    </div>
  );
}

type ProfileFormProps = {
  me: MeOut;
  submitLabel: ReactNode;
  onSaved?: (me: MeOut) => void;
  /** Settings shows the theme in its own section; the wizard shows it here. */
  withTheme?: boolean;
  /** The wizard: session length and interests behind "More about you", a Back button beside the submit. */
  compact?: boolean;
  secondary?: ReactNode;
  /** The wizard: answers an AI assistant collected before Yuo started (SETUP.md), to start from. */
  prefill?: SetupAnswersProfile | null;
};

export function ProfileForm({ me, submitLabel, onSaved, withTheme, compact, secondary, prefill }: ProfileFormProps) {
  const { t, i18n } = useLingui();
  const save = useUpdateMe();
  const fresh = isDefaultProfile(me); // not saved yet: start from the answers, else the browser's language
  const given = fresh ? (prefill ?? {}) : {};
  const [name, setName] = useState(given.display_name ?? me.display_name);
  const [contentLang, setContentLang] = useState(given.content_lang ?? (fresh ? browserLocale() : me.content_lang));
  const [uiLang, setUiLang] = useState(
    shippedLocale(given.ui_lang ?? "") ?? (fresh ? browserLocale() : (shippedLocale(me.ui_lang) ?? "en")),
  );
  const [tz, setTz] = useState(given.tz ?? (me.tz === "UTC" ? (browserTimeZone() ?? "UTC") : me.tz));
  const [minutes, setMinutes] = useState(given.session_minutes ?? me.session_minutes);
  const [interests, setInterests] = useState(given.interests ?? me.interests);
  const startContent = given.content_lang ?? me.content_lang;
  const startZone = given.tz ?? me.tz;
  const zones = useMemo(() => timeZones(startZone), [startZone]);
  const zoneItems = useMemo(() => zones.map((z) => ({ id: z, name: z })), [zones]);
  const tzValid = zones.includes(tz);

  const langNames = useMemo(() => {
    let names: Intl.DisplayNames | null = null;
    try {
      names = new Intl.DisplayNames([i18n.locale], { type: "language" });
    } catch {
      names = null;
    }
    const codes = CONTENT_LANGS.includes(startContent) ? CONTENT_LANGS : [startContent, ...CONTENT_LANGS];
    return codes.map((id) => ({ id, name: names?.of(id) ?? id }));
  }, [i18n.locale, startContent]);

  const used = interests.length;
  const max = INTERESTS_MAX;

  const optional = (
    <>
      <NumberField
        className={ui.field}
        value={minutes}
        onChange={(v) => setMinutes(Number.isFinite(v) ? v : me.session_minutes)}
        minValue={SESSION_MIN}
        maxValue={SESSION_MAX}
        step={5}
      >
        <Label className={ui.label}>{t({ id: "profile.minutes", message: "Minutes per study session" })}</Label>
        <Group className={styles.numberGroup}>
          <AriaButton slot="decrement" className={`${ui.button} ${ui.secondary} ${ui.small}`}>
            −
          </AriaButton>
          <Input className={`${ui.input} ${styles.numberInput}`} />
          <AriaButton slot="increment" className={`${ui.button} ${ui.secondary} ${ui.small}`}>
            +
          </AriaButton>
        </Group>
        <Text slot="description" className={ui.description}>
          {t({
            id: "profile.minutes.description",
            message: "Yuo plans lessons and reviews to fit this time, from 5 to 120 minutes.",
          })}
        </Text>
      </NumberField>
      <Field
        label={t({ id: "profile.interests", message: "Your interests (optional)" })}
        description={t({
          id: "profile.interests.description",
          message: `${used} of ${max} characters. For example: cycling, cooking, I work in a hospital. This is sent with every lesson request as information about you, so examples can fit your life. Leave it empty to send nothing.`,
        })}
        value={interests}
        onChange={setInterests}
        maxLength={max}
        multiline
        name="interests"
      />
    </>
  );

  return (
    <form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim() || !tzValid) return;
        const change: MeIn = {
          display_name: name.trim(),
          content_lang: contentLang,
          ui_lang: uiLang,
          tz,
          session_minutes: minutes,
          interests: interests.trim(),
        };
        save.mutate(change, { onSuccess: (saved) => onSaved?.(saved) });
      }}
    >
      <Field
        label={t({ id: "profile.name", message: "Your name" })}
        description={t({ id: "profile.name.description", message: "How Yuo and your tutor address you." })}
        value={name}
        onChange={setName}
        isRequired
        maxLength={60}
        name="display_name"
      />
      <SelectField
        label={t({ id: "profile.content-lang", message: "Language of your lessons" })}
        options={langNames}
        value={contentLang}
        onChange={setContentLang}
        description={t({
          id: "profile.content-lang.description",
          message:
            "Yuo writes your lessons, practice questions and videos in this language. A new path uses it; a path you already have keeps its own.",
        })}
      />
      <SelectField
        label={t({ id: "profile.ui-lang", message: "Language of Yuo's screens" })}
        options={locales.map((l) => ({ id: l, name: localeName(l) }))}
        value={uiLang}
        onChange={(v) => setUiLang(shippedLocale(v) ?? "en")}
      />
      <ComboBox
        className={ui.field}
        defaultItems={zoneItems}
        inputValue={tz}
        onInputChange={setTz}
        allowsCustomValue
        isInvalid={!tzValid}
        menuTrigger="focus"
      >
        <Label className={ui.label}>{t({ id: "profile.tz", message: "Time zone" })}</Label>
        <div className={styles.comboRow}>
          <Input className={ui.input} />
          <AriaButton className={`${ui.button} ${ui.secondary} ${ui.small}`}>
            <span aria-hidden="true">▾</span>
          </AriaButton>
        </div>
        <Text slot={tzValid ? "description" : "errorMessage"} className={tzValid ? ui.description : ui.fieldError}>
          {tzValid
            ? t({ id: "profile.tz.description", message: "Used for your daily reviews and streaks. Type a city to search." })
            : t({ id: "profile.tz.invalid", message: "Choose a time zone from the list, for example Europe/Berlin." })}
        </Text>
        <Popover className={itemStyles.popover}>
          <ListBox className={itemStyles.listbox}>
            {(item: Option) => (
              <ListBoxItem id={item.id} className={itemStyles.option} textValue={item.name}>
                {item.name}
              </ListBoxItem>
            )}
          </ListBox>
        </Popover>
      </ComboBox>
      {compact ? (
        <>
          {withTheme ? <ThemePicker value={me.theme} /> : null}
          <MoreOptions
            title={t({ id: "profile.more", message: "Session length and interests (optional)" })}
            defaultExpanded={given.session_minutes !== undefined || given.interests !== undefined}
          >
            {optional}
          </MoreOptions>
        </>
      ) : (
        <>
          {optional}
          {withTheme ? <ThemePicker value={me.theme} /> : null}
        </>
      )}
      {save.isError ? <ErrorNotice error={save.error} /> : null}
      <div className={secondary ? styles.formNav : ui.row}>
        {secondary}
        <div className={ui.row}>
          {save.isSuccess ? (
            <span className={ui.muted} role="status">
              <Trans id="profile.saved">Saved.</Trans>
            </span>
          ) : null}
          <Button type="submit" isDisabled={save.isPending || !name.trim() || !tzValid}>
            {save.isPending ? <Trans id="profile.saving">Saving…</Trans> : submitLabel}
          </Button>
        </div>
      </div>
    </form>
  );
}
