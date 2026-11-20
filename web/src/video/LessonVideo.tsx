// The video part of a lesson: the player when the rendition is ready, a calm note while it is
// being made, one muted line when it failed or this installation makes no videos. The reading
// lesson below stays the primary content in every state.
//
// Captions: their starting state is the learner's `video.captions` setting; toggling them
// in the player saves it. While the video plays, its time goes to the tutor context (`video_s`);
// opening the tutor pauses it.
import { Trans, useLingui } from "@lingui/react/macro";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { LessonOut } from "../api/client";
import { usePutSetting, useSettings, useSetup, useVideoAgain } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { DownloadIcon, NoteIcon } from "../components/icons";
import { Button, Notice, ui } from "../components/ui";
import { useTutorRefs, useTutorState } from "../tutor/context";
import styles from "./lessonVideo.module.css";
import { readJson, writeJson } from "../storage";
import { HIDDEN_KEY, NotesBubble } from "./NotesBubble";
import { VideoUnavailableText } from "./unavailable";
import { YouTubeVideo } from "./YouTubeVideo";

const VideoPlayer = lazy(() => import("./VideoPlayer"));

export type Video = NonNullable<LessonOut["video"]>;

const MAKING = new Set<Video["state"]>(["queued", "generating", "in_review"]);
const CAPTIONS_KEY = "video.captions";
const NOTES_BUBBLE_KEY = "video.notes_bubble";

function assetUrl(hash: string): string {
  return `/api/assets/${encodeURIComponent(hash)}`;
}

function exportUrl(versionId: string): string {
  return `/api/renditions/${encodeURIComponent(versionId)}/export`;
}

/** The learner's captions setting; on until the settings say otherwise (the default is on). */
function useCaptionsSetting(): { on: boolean; loaded: boolean } {
  const settings = useSettings();
  if (settings.isPending) return { on: true, loaded: false };
  const v = settings.data?.find((s) => s.key === CAPTIONS_KEY)?.value;
  return { on: typeof v === "boolean" ? v : true, loaded: true };
}

/** Whether the notes bubble is on (on until the settings say otherwise). */
function useNotesBubbleSetting(): boolean {
  const settings = useSettings();
  const v = settings.data?.find((s) => s.key === NOTES_BUBBLE_KEY)?.value;
  return settings.isSuccess && v !== false;
}

function ReadyVideo({ video, lang, lessonId }: { video: Video; lang: string; lessonId: string }) {
  const { t, i18n } = useLingui();
  const captions = useCaptionsSetting();
  const bubbleOn = useNotesBubbleSetting();
  const put = usePutSetting();
  const tutor = useTutorState();
  const [pauseKey, setPauseKey] = useState(0);
  const [videoS, setVideoS] = useState<number | null>(null);
  const [seek, setSeek] = useState<{ s: number; n: number } | undefined>(undefined);
  const [bubbleHidden, setBubbleHidden] = useState(() => readJson<boolean>(HIDDEN_KEY, false));
  const timeRef = useRef<number | null>(null);
  timeRef.current = videoS;
  const wasOpen = useRef(tutor.open);

  // asking pauses: the learner reads the answer, not two things at once
  useEffect(() => {
    if (tutor.open && !wasOpen.current) setPauseKey((k) => k + 1);
    wasOpen.current = tutor.open;
  }, [tutor.open]);

  useTutorRefs(videoS === null ? null : { video_s: Math.round(videoS * 10) / 10 });

  const media = video.assets["video"];
  if (!media) return null;
  const poster = video.assets["poster"];
  const subtitles = video.assets["subtitles"];
  const captionLang = video.lang ?? lang;
  if (!captions.loaded) {
    return (
      <p className={ui.muted}>
        <Trans id="common.loading">Loading…</Trans>
      </p>
    );
  }
  return (
    <Suspense
      fallback={
        <p className={ui.muted}>
          <Trans id="common.loading">Loading…</Trans>
        </p>
      }
    >
      <VideoPlayer
        src={assetUrl(media)}
        poster={poster ? assetUrl(poster) : undefined}
        captions={
          subtitles
            ? {
                src: assetUrl(subtitles),
                lang: captionLang,
                label: t({ id: "video.captions.label", message: "Captions" }),
              }
            : undefined
        }
        captionsOn={captions.on}
        onCaptionsChange={(on) => put.mutate({ key: CAPTIONS_KEY, value: on })}
        onTime={setVideoS}
        pauseKey={pauseKey}
        seek={seek}
        label={t({ id: "video.player.group", message: "Lesson video" })}
        locale={i18n.locale}
      />
      {bubbleOn && video.version_id ? (
        bubbleHidden ? (
          <div className={styles.notesAgain}>
            <Button
              variant="ghost"
              small
              onPress={() => {
                setBubbleHidden(false);
                writeJson(HIDDEN_KEY, false);
              }}
            >
              <NoteIcon />
              <Trans id="notes-bubble.show">Questions for the tutor</Trans>
            </Button>
          </div>
        ) : (
          <NotesBubble
            lessonId={lessonId}
            versionId={video.version_id}
            videoTime={() => timeRef.current}
            seek={(s) => setSeek((p) => ({ s, n: (p?.n ?? 0) + 1 }))}
            onHide={() => {
              setBubbleHidden(true);
              writeJson(HIDDEN_KEY, true);
            }}
          />
        )
      ) : null}
    </Suspense>
  );
}

/** A video that could not be made: the reading lesson has it all, and the learner may ask for it again. */
function FailedVideo({ lessonId }: { lessonId: string }) {
  const again = useVideoAgain(lessonId);
  return (
    <div className={ui.row} data-video="failed">
      <p className={ui.muted}>
        <Trans id="video.failed">There is no video for this lesson this time; the reading lesson below has it all.</Trans>
      </p>
      <Button variant="ghost" small onPress={() => again.mutate()} isDisabled={again.isPending}>
        <Trans id="video.again">Try making the video again</Trans>
      </Button>
      {again.isError ? <ErrorNotice error={again.error} /> : null}
    </div>
  );
}

export function LessonVideo({ lesson }: { lesson: LessonOut }) {
  const youtube = lesson.youtube ?? null;
  if (youtube?.video_id) return <YouTubeVideo lesson={lesson} youtube={youtube} />;
  if (youtube) {
    // a path that uses YouTube videos found none for this lesson: why, and any video Yuo made instead
    return (
      <>
        <YouTubeVideo lesson={lesson} youtube={youtube} />
        <MadeVideo lesson={lesson} />
      </>
    );
  }
  return <MadeVideo lesson={lesson} />;
}

/** The video Yuo made for the lesson, in each of its states. */
function MadeVideo({ lesson }: { lesson: LessonOut }) {
  const video = lesson.video ?? null;
  const reason = lesson.video_unavailable ?? null;
  const desktop = useSetup().data?.desktop ?? false;

  if (reason && (!video || video.state !== "ready")) {
    return (
      <p className={ui.muted} data-video="unavailable">
        <VideoUnavailableText reason={reason} desktop={desktop} />
      </p>
    );
  }
  if (!video || video.state === "planned") return null;
  if (MAKING.has(video.state)) {
    return (
      <Notice role="status">
        <Trans id="video.making">The video is being made; the reading lesson is here meanwhile.</Trans>
      </Notice>
    );
  }
  if (video.state === "failed") return <FailedVideo lessonId={lesson.id} />;
  return (
    <div className={styles.section}>
      <ReadyVideo video={video} lang={lesson.lang ?? "en"} lessonId={lesson.id} />
      {video.version_id ? (
        <p className={styles.links}>
          <a href={exportUrl(video.version_id)} download className={styles.download}>
            <DownloadIcon />
            <Trans id="video.download">Download video (MP4 with subtitles)</Trans>
          </a>
        </p>
      ) : null}
    </div>
  );
}
