// Settings (CFG registry): every setting with its value, where it comes from, the default, the
// explanation, example, suggestion, impact tags and a warning when a value weakens learning.
// Learner-level values are edited here (PUT /api/settings/{key}); installation-only settings are
// shown read-only. model.preset lives on /setup; the profile, theme and AI access have their own sections.
// Every section starts closed and a search finds a setting by its name or explanation.
import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { createRoute, Link, useRouterState } from "@tanstack/react-router";
import { useState } from "react";
import {
  Group,
  Input,
  Label,
  SearchField,
} from "react-aria-components";
import type { SettingOut } from "../api/client";
import { useEraseVideoHistory, useSettings, useSetup } from "../api/hooks";
import { ConfirmAction } from "../components/ConfirmAction";
import { Collapsible, openTarget, useOpenHashTarget } from "../components/Collapsible";
import { ErrorNotice } from "../components/ErrorNotice";
import { ChevronRightIcon, KeyIcon, SearchIcon } from "../components/icons";
import { Notice, PageHeader, ui } from "../components/ui";
import {
  AiAccessSection,
  AppearanceSection,
  DesktopSection,
  ProfileSection,
  UpdatesSection,
} from "../onboarding/SettingsSections";
import { rootRoute } from "./root";
import styles from "./settings.module.css";
import { useTutorRefs } from "../tutor/context";
import { VideoUnavailableText } from "../video/unavailable";
import { YouTubeSettings } from "../video/YouTubeSettings";
import { LABELS, SettingRow } from "./SettingRow";

export const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsPage,
});

/** Edited in their own sections (profile, appearance, AI access), so not listed twice. */
const HIDDEN_SETTINGS = new Set([
  "model.preset",
  "ui.theme",
  "session.minutes",
  "learner.interests",
  "ai.local_url",
  "ui.device_scheme", // recorded by the app, not chosen
]);

type Group = { id: string; title: MessageDescriptor; description: MessageDescriptor; keys: string[] };

/** The learning settings by topic, in the order a learner meets them. A key not listed lands in the last group. */
const GROUPS: Group[] = [
  {
    id: "lessons",
    title: msg({ id: "settings.group.lessons", message: "Lessons" }),
    description: msg({ id: "settings.group.lessons.description", message: "Length, your own wishes, lessons prepared ahead" }),
    keys: ["lesson.reading_length", "custom_instructions", "generation.buffer", "material.transcription"],
  },
  {
    id: "videos",
    title: msg({ id: "settings.group.videos", message: "Videos" }),
    description: msg({ id: "settings.group.videos.description3", message: "Whether lessons come as videos, their length, colours and captions" }),
    keys: ["video.format", "video.source", "video.youtube_languages", "video.length", "video.theme", "video.captions", "video.notes_bubble"],
  },
  {
    id: "practice",
    title: msg({ id: "settings.group.practice", message: "Practice and skill tests" }),
    description: msg({ id: "settings.group.practice.description", message: "Question types, when solutions show, the pass mark" }),
    keys: ["practice.types", "practice.solution_after", "skill_test.pass_mark"],
  },
  {
    id: "reviews",
    title: msg({ id: "settings.group.reviews", message: "Reviews" }),
    description: msg({ id: "settings.group.reviews.description", message: "How much and how often you go back over past lessons" }),
    keys: ["reviews.max_per_day", "review.bank_size", "review.desired_retention", "review.max_interval_days", "mastery.decay"],
  },
  {
    id: "tutor",
    title: msg({ id: "settings.group.tutor", message: "Tutor" }),
    description: msg({ id: "settings.group.tutor.description", message: "Name, tone, suggestions and what it remembers" }),
    keys: ["tutor.name", "tutor.tone", "tutor.proactivity", "tutor.muted_triggers", "tutor.test_policy", "tutor.memory"],
  },
  {
    id: "motivation",
    title: msg({ id: "settings.group.motivation", message: "Motivation" }),
    description: msg({ id: "settings.group.motivation.description", message: "Points, streaks and levels" }),
    keys: ["gamification", "streak.grace_days"],
  },
  {
    id: "installation",
    title: msg({ id: "settings.group.installation", message: "This installation" }),
    description: msg({ id: "settings.group.installation.description", message: "Set for everyone on this Yuo by whoever runs it" }),
    keys: ["review.independent", "budget.cap_usd_month", "updates.check"],
  },
];

/** The other sections, found by search through these words too. */
const SECTION_LINKS: { id: string; title: MessageDescriptor; words: MessageDescriptor }[] = [
  {
    id: "profile",
    title: msg({ id: "settings.profile.title", message: "Your profile" }),
    words: msg({ id: "settings.profile.words", message: "name language languages session minutes interests time zone" }),
  },
  {
    id: "appearance",
    title: msg({ id: "settings.appearance.title", message: "Appearance" }),
    words: msg({ id: "settings.appearance.words", message: "theme dark light colours" }),
  },
  {
    id: "ai-access",
    title: msg({ id: "settings.ai.title", message: "AI access" }),
    words: msg({ id: "settings.ai.words", message: "model models Claude Codex OpenRouter key subscription sign in install local" }),
  },
  {
    id: "updates",
    title: msg({ id: "update.title", message: "Updates" }),
    words: msg({ id: "settings.updates.words", message: "version update new" }),
  },
];

function matches(query: string, ...texts: string[]): boolean {
  const words = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const hay = texts.join(" ").toLocaleLowerCase();
  return words.every((w) => hay.includes(w));
}

function VideoNotice() {
  const setup = useSetup();
  const reason = setup.data?.video_unavailable;
  if (!reason) return null;
  return (
    <Notice>
      <VideoUnavailableText reason={reason} desktop={setup.data?.desktop ?? false} />
    </Notice>
  );
}

function LearningGroups({ settings }: { settings: SettingOut[] }) {
  const { i18n } = useLinguiRuntime();
  const shown = settings.filter((s) => !HIDDEN_SETTINGS.has(s.key));
  const known = new Set(GROUPS.flatMap((g) => g.keys));
  return (
    <>
      {GROUPS.map((g, n) => {
        const last = n === GROUPS.length - 1;
        const rows = [
          ...g.keys.map((k) => shown.find((s) => s.key === k)).filter((s): s is SettingOut => s !== undefined),
          ...(last ? shown.filter((s) => !known.has(s.key)) : []),
        ];
        if (rows.length === 0) return null;
        return (
          <Collapsible key={g.id} id={g.id} title={i18n._(g.title)} description={i18n._(g.description)}>
            {g.id === "videos" && settings.find((s) => s.key === "video.source")?.value !== "youtube" ? <VideoNotice /> : null}
            <ul className={styles.list}>
              {rows.map((s) => (
                <SettingRow key={`${s.key}:${JSON.stringify(s.value)}`} setting={s} />
              ))}
            </ul>
            {g.id === "videos" ? <YouTubeSettings settings={settings} /> : null}
            {g.id === "videos" ? <EraseVideoHistory /> : null}
          </Collapsible>
        );
      })}
    </>
  );
}

/** Which videos were watched and how much of each, erased for good. */
function EraseVideoHistory() {
  const erase = useEraseVideoHistory();
  return (
    <div className={ui.stack}>
      {erase.isSuccess ? (
        <p role="status">
          <Trans id="settings.video-history.done">Your video watch history is deleted.</Trans>
        </p>
      ) : (
        <ConfirmAction
          label={<Trans id="settings.video-history.erase">Delete my video watch history</Trans>}
          question={
            <Trans id="settings.video-history.question">
              Delete which videos you watched and how much of each, for good? Lessons and progress stay.
            </Trans>
          }
          confirmLabel={<Trans id="settings.video-history.confirm">Delete the history</Trans>}
          pending={erase.isPending}
          onConfirm={() => erase.mutate()}
        />
      )}
      {erase.isError ? <ErrorNotice error={erase.error} /> : null}
    </div>
  );
}

function SearchResults({ query, settings }: { query: string; settings: SettingOut[] }) {
  const { i18n } = useLinguiRuntime();
  const sections = SECTION_LINKS.filter((x) => matches(query, i18n._(x.title), i18n._(x.words)));
  const rows = settings
    .filter((s) => !HIDDEN_SETTINGS.has(s.key))
    .filter((s) => matches(query, LABELS[s.key] ? i18n._(LABELS[s.key]!) : s.key, s.explanation, s.example));
  if (sections.length === 0 && rows.length === 0) {
    return (
      <p className={ui.muted} role="status">
        <Trans id="settings.search.none">No setting matches “{query}”.</Trans>
      </p>
    );
  }
  return (
    <div className={ui.stack} role="region" aria-live="polite">
      {sections.length > 0 ? (
        <ul className={styles.sectionHits}>
          {sections.map((x) => (
            <li key={x.id}>
              <Link to="/settings" hash={x.id} onClick={() => openTarget(x.id)}>
                {i18n._(x.title)}
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {rows.length > 0 ? (
        <ul className={`${styles.list} ${styles.hits}`}>
          {rows.map((s) => (
            <SettingRow key={`${s.key}:${JSON.stringify(s.value)}`} setting={s} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function SettingsPage() {
  const { t } = useLingui();
  useTutorRefs({ screen: "settings" });
  const settings = useSettings();
  const [query, setQuery] = useState("");
  const hash = useRouterState({ select: (s) => s.location.hash });
  useOpenHashTarget(hash, settings.isSuccess && !query);
  const searching = query.trim().length > 0;
  return (
    <section className={`${ui.stack} ${styles.page}`}>
      <PageHeader
        title={<Trans id="settings.title">Settings</Trans>}
        meta={
          <p>
            <Trans id="settings.intro">Your own settings apply to all your paths unless a path sets its own.</Trans>
          </p>
        }
      />
      <SearchField className={styles.search} value={query} onChange={setQuery}>
        <Label className="visually-hidden">{t({ id: "settings.search.label", message: "Find a setting" })}</Label>
        <SearchIcon className={styles.searchIcon} aria-hidden="true" />
        <Input
          className={`${ui.input} ${styles.searchInput}`}
          placeholder={t({ id: "settings.search.placeholder", message: "Find a setting, e.g. video or tutor" })}
        />
      </SearchField>
      {searching ? (
        settings.isSuccess ? (
          <SearchResults query={query.trim()} settings={settings.data} />
        ) : null
      ) : (
        <>
          <Link to="/settings/devices" className={styles.devices}>
            <span className={styles.devicesIcon} aria-hidden="true">
              <KeyIcon />
            </span>
            <span>
              <Trans id="settings.devices-link">Sign-in and devices: passkeys, password, recovery codes, signed-in devices</Trans>
            </span>
            <ChevronRightIcon className={styles.devicesChevron} />
          </Link>
          <h2 className={styles.groupTitle}>
            <Trans id="settings.you.title">You and this Yuo</Trans>
          </h2>
          <ProfileSection />
          <AppearanceSection />
          <AiAccessSection />
          <UpdatesSection />
          <DesktopSection />
          <h2 id="learning-settings" className={styles.groupTitle}>
            <Trans id="settings.learning.title">Learning settings</Trans>
          </h2>
          {settings.isPending ? (
            <p className={ui.muted}>
              <Trans id="common.loading">Loading…</Trans>
            </p>
          ) : settings.isError ? (
            <ErrorNotice error={settings.error} />
          ) : (
            <LearningGroups settings={settings.data} />
          )}
        </>
      )}
    </section>
  );
}
