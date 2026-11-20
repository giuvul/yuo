// Setup, "Videos": where lesson videos come from. YouTube first (about 10 to 25% on a lesson's cost, no video
// renderer needed), a video made by Yuo (about ten times the lesson), or reading only. Choosing YouTube shows what the learner takes on. Setup saves it as the learner's video.source
// and video.format (Settings > Videos changes them later); New path offers the same cards for one path.
import { Trans, useLingui } from "@lingui/react/macro";
import { useState, type ReactNode } from "react";
import { usePutSetting, useSettings, useSetup } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { BookIcon, PlayIcon, SparkleIcon } from "../components/icons";
import { Badge, ChoiceCards, Notice, ui, Waiting } from "../components/ui";
import { VideoUnavailableText } from "../video/unavailable";

export type VideoChoice = "youtube" | "generated" | "reading";

/** The choice the current settings amount to (a path's own settings aside); YouTube while nothing was chosen. */
export function currentChoice(format: unknown, source: unknown, canMake: boolean, chosen: boolean): VideoChoice {
  if (format === "reading") return "reading";
  if (!chosen) return "youtube";
  if (source === "generated" && canMake) return "generated";
  return "youtube";
}

/** The learner's general choice and whether this install can make videos: what the cards start from. Setup
 * suggests YouTube while nothing was chosen; New path starts on what the setting is in effect. */
export function useVideoChoice({ suggest = false }: { suggest?: boolean } = {}) {
  const settings = useSettings();
  const setup = useSetup();
  const unavailable = setup.data?.video_unavailable ?? null;
  const canMake = unavailable === null;
  const value = (key: string) => settings.data?.find((s) => s.key === key)?.value;
  const chosen = !suggest || settings.data?.find((s) => s.key === "video.source")?.source != null;
  return {
    isPending: settings.isPending || setup.isPending,
    current: currentChoice(value("video.format"), value("video.source"), canMake, chosen),
    format: value("video.format"),
    canMake,
    unavailable,
    desktop: setup.data?.desktop ?? false,
  };
}

/** The four kinds of videos (Yuo's own only where they can be made), with the YouTube disclaimer under them. */
export function VideoChoiceCards({
  label,
  value,
  onChange,
  canMake,
  unavailable,
  desktop,
}: {
  label: string;
  value: VideoChoice;
  onChange: (v: VideoChoice) => void;
  canMake: boolean;
  unavailable: ReturnType<typeof useVideoChoice>["unavailable"];
  desktop: boolean;
}) {
  const { t } = useLingui();
  const choices = [
    {
      value: "youtube" as const,
      icon: <PlayIcon />,
      label: t({ id: "wizard.videos.youtube", message: "Videos from YouTube" }),
      badge: (
        <Badge tone="success">
          <Trans id="wizard.options.recommended">Recommended</Trans>
        </Badge>
      ),
      description: t({
        id: "wizard.videos.youtube.description",
        message:
          "For each lesson Yuo finds a YouTube video that teaches it, picks the right minutes, and writes the lesson from what the video says. A lesson costs about 10 to 25% more than without a video.",
      }),
    },
    ...(canMake
      ? [
          {
            value: "generated" as const,
            icon: <SparkleIcon />,
            label: t({ id: "wizard.videos.generated", message: "Videos made by Yuo" }),
            description: t({
              id: "wizard.videos.generated.description",
              message:
                "Yuo writes, narrates and renders a new short video for each lesson. Each video costs about ten times its lesson.",
            }),
          },
        ]
      : []),
    {
      value: "reading" as const,
      icon: <BookIcon />,
      label: t({ id: "wizard.videos.reading", message: "No videos" }),
      description: t({ id: "wizard.videos.reading.description", message: "Reading lessons only: the lowest usage." }),
    },
  ];
  return (
    <div className={ui.stack}>
      <ChoiceCards label={label} choices={choices} value={value} onChange={onChange} />
      {!canMake && unavailable ? (
        <p className={ui.muted}>
          <VideoUnavailableText reason={unavailable} desktop={desktop} />{" "}
          <Trans id="wizard.videos.youtube-works">Videos from YouTube work here all the same.</Trans>
        </p>
      ) : null}
      {value === "youtube" ? (
        <Notice tone="warning" icon={true} role="note">
          <p>
            <Trans id="youtube.disclaimer">
              Lessons use public YouTube videos: Yuo reads their captions (or, when YouTube refuses them, downloads
              the sound and transcribes it on this computer) to write the lesson, and shows the video in YouTube's own
              player. YouTube's terms do not allow reading its pages or downloading its videos by automated means. You
              use this at your own risk and you are responsible for your use of it.
            </Trans>
          </p>
          <p>
            <Trans id="youtube.privacy">
              The searches send each lesson's topic to YouTube, and a video loads from YouTube when you press play.
            </Trans>
          </p>
        </Notice>
      ) : null}
    </div>
  );
}

/** Setup: the choice saved as the learner's general setting. */
export function VideoChoiceForm({
  onSaved,
  footer,
}: {
  onSaved: () => void;
  footer: (save: () => void, pending: boolean) => ReactNode;
}) {
  const { t } = useLingui();
  const v = useVideoChoice({ suggest: true });
  const put = usePutSetting();
  const [picked, setPicked] = useState<VideoChoice | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);

  if (v.isPending) {
    return (
      <Waiting>
        <Trans id="common.loading">Loading…</Trans>
      </Waiting>
    );
  }
  const choice = picked ?? v.current;

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      if (choice === "reading") {
        await put.mutateAsync({ key: "video.format", value: "reading" });
      } else {
        if (v.format === "reading") await put.mutateAsync({ key: "video.format", value: "when_possible" });
        await put.mutateAsync({ key: "video.source", value: choice });
      }
      onSaved();
    } catch (e) {
      setError(e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={ui.stack}>
      <VideoChoiceCards
        label={t({ id: "wizard.videos.label", message: "Videos with your lessons" })}
        value={choice}
        onChange={setPicked}
        canMake={v.canMake}
        unavailable={v.unavailable}
        desktop={v.desktop}
      />
      <p className={ui.muted}>
        <Trans id="wizard.videos.later">You can change this any time in Settings, under Videos.</Trans>
      </p>
      {error ? <ErrorNotice error={error} /> : null}
      {footer(() => void save(), saving)}
    </div>
  );
}
