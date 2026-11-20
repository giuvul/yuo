// A lesson's YouTube video (setting video.source): the stretch that teaches the lesson, in YouTube's own player.
// Nothing loads from YouTube until the learner presses play (privacy, and a fast page); then the
// youtube-nocookie player starts at the stretch and stops at its end. While it plays, a line under it keeps the
// stretch in view: where the video is, how long is left of the lesson's part, and a way back to its start. The
// position comes from the player's own messages (its documented postMessage protocol, enablejsapi=1): no YouTube
// script is loaded into the page. "Another video" turns this one down: the next video found is used and the
// lesson is written again for it, while this version stays readable.
import { Trans, useLingui } from "@lingui/react/macro";
import { useEffect, useRef, useState, type RefObject } from "react";
import type { LessonOut } from "../api/client";
import { useAnotherVideo } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { PlayIcon } from "../components/icons";
import { Button, Progress, ui } from "../components/ui";
import styles from "./youTubeVideo.module.css";

export type YouTube = NonNullable<LessonOut["youtube"]>;

const TERMS = "https://www.youtube.com/t/terms";
const PLAYER = "https://www.youtube-nocookie.com";
const NEAR_S = 3; // this close to the stretch's start counts as at it

function mmss(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function embedUrl(yt: YouTube, lang: string, origin?: string): string {
  const q = new URLSearchParams({ autoplay: "1", rel: "0", hl: lang, cc_lang_pref: lang, start: String(yt.start_s) });
  if (yt.end_s) q.set("end", String(yt.end_s));
  if (origin) {
    q.set("enablejsapi", "1"); // the player tells this page where it is (see usePlayerTime)
    q.set("origin", origin);
  }
  return `${PLAYER}/embed/${encodeURIComponent(yt.video_id ?? "")}?${q.toString()}`;
}

function send(frame: RefObject<HTMLIFrameElement | null>, message: Record<string, unknown>) {
  frame.current?.contentWindow?.postMessage(JSON.stringify({ ...message, id: 1, channel: "widget" }), PLAYER);
}

/** Where the embedded player is, in seconds (null until it says), and a way to move it. */
function usePlayerTime(frame: RefObject<HTMLIFrameElement | null>, active: boolean) {
  const [now, setNow] = useState<number | null>(null);
  const heard = useRef(false);
  useEffect(() => {
    if (!active) return;
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== PLAYER || e.source !== frame.current?.contentWindow) return;
      let data: { event?: string; info?: { currentTime?: unknown } } | null = null;
      try {
        data = typeof e.data === "string" ? JSON.parse(e.data) : e.data;
      } catch {
        return;
      }
      const time = data?.event === "infoDelivery" ? data.info?.currentTime : undefined;
      if (typeof time === "number") {
        heard.current = true;
        setNow(time);
      }
    };
    window.addEventListener("message", onMessage);
    // the player answers "listening" once it is ready: ask until it does
    const ask = window.setInterval(() => {
      if (heard.current) window.clearInterval(ask);
      else send(frame, { event: "listening" });
    }, 1000);
    return () => {
      window.removeEventListener("message", onMessage);
      window.clearInterval(ask);
    };
  }, [active, frame]);
  const seek = (s: number) => {
    send(frame, { event: "command", func: "seekTo", args: [s, true] });
    send(frame, { event: "command", func: "playVideo", args: [] });
  };
  return { now, seek };
}

/** Under the playing video: the lesson's part, where the video is in it, and the way back to its start. */
function Stretch({ youtube, span, now, onBack }: { youtube: YouTube; span: string; now: number | null; onBack: () => void }) {
  const { t } = useLingui();
  const start = youtube.start_s;
  const end = youtube.end_s;
  const at = now == null ? null : Math.floor(now);
  const atText = at == null ? "" : mmss(at);
  const startText = mmss(start);
  const endText = end == null ? "" : mmss(end);
  let where = null;
  if (at != null && at < start - NEAR_S) {
    where = <Trans id="youtube.stretch.before">At {atText}: the lesson's part starts at {startText}.</Trans>;
  } else if (at != null && end != null && at > end) {
    where = (
      <Trans id="youtube.stretch.after">
        The lesson's part ended at {endText}. Keep watching if you like, or go on with the lesson.
      </Trans>
    );
  } else if (at != null && end != null) {
    const leftText = mmss(Math.max(0, end - at));
    where = <Trans id="youtube.stretch.left">At {atText}: {leftText} left, until {endText}.</Trans>;
  }
  const away = at != null && (at < start - NEAR_S || at > start + NEAR_S);
  return (
    <div className={styles.stretch} data-youtube-stretch>
      <p className={styles.stretchSpan}>{span}</p>
      {at != null && end != null && at >= start - NEAR_S && at <= end ? (
        <Progress
          value={Math.max(0, at - start)}
          max={Math.max(1, end - start)}
          label={t({ id: "youtube.stretch.progress", message: "Through the lesson's part of the video" })}
          showValue={false}
        />
      ) : null}
      {where ? (
        <p className={ui.muted} aria-live="polite">
          {where}
        </p>
      ) : null}
      {away ? (
        <div>
          <Button variant="ghost" small onPress={onBack}>
            <Trans id="youtube.stretch.back">Back to {startText}</Trans>
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function AnotherVideo({ lessonId, busy, label }: { lessonId: string; busy: boolean; label: "another" | "again" }) {
  const another = useAnotherVideo(lessonId);
  const waiting = busy || another.isSuccess;
  return (
    <div className={ui.stack}>
      {waiting ? (
        <p className={ui.muted} role="status">
          <Trans id="youtube.writing">Yuo is looking for another video and writing the lesson again for it; this version stays until then.</Trans>
        </p>
      ) : (
        <div>
          <Button variant="ghost" small onPress={() => another.mutate()} isDisabled={another.isPending}>
            {label === "another" ? (
              <Trans id="youtube.another">Another video</Trans>
            ) : (
              <Trans id="youtube.look-again">Look for a video again</Trans>
            )}
          </Button>
        </div>
      )}
      {another.isError ? <ErrorNotice error={another.error} /> : null}
    </div>
  );
}

/** Why a lesson of a path that uses YouTube videos has none this time. */
function NoVideo({ note }: { note: NonNullable<YouTube["note"]> }) {
  switch (note) {
    case "blocked":
      return (
        <Trans id="youtube.note.blocked">
          YouTube refused this server's request for the videos' captions, so this lesson was written without a video.
        </Trans>
      );
    case "quota":
      return (
        <Trans id="youtube.note.quota">
          The YouTube key's searches for today are used up, so this lesson was written without a video. Try again tomorrow.
        </Trans>
      );
    case "bad_key":
      return (
        <Trans id="youtube.note.bad-key">
          YouTube refused the key set in Settings, so this lesson was written without a video.
        </Trans>
      );
    case "network":
      return <Trans id="youtube.note.network">YouTube could not be reached, so this lesson was written without a video.</Trans>;
    default:
      return <Trans id="youtube.note.none">No YouTube video taught this lesson well, so it is a reading lesson.</Trans>;
  }
}

export function YouTubeVideo({ lesson, youtube }: { lesson: LessonOut; youtube: YouTube }) {
  const { t } = useLingui();
  const [playing, setPlaying] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  const player = usePlayerTime(frame, playing);
  const busy = lesson.state === "queued" || lesson.state === "generating";
  const lang = lesson.lang ?? "en";

  if (!youtube.video_id) {
    return (
      <div className={styles.note} data-youtube="none">
        <p className={ui.muted}>
          <NoVideo note={youtube.note ?? "none"} />
        </p>
        <AnotherVideo lessonId={lesson.id} busy={busy} label="again" />
      </div>
    );
  }
  const span =
    youtube.end_s != null
      ? t({ id: "youtube.span", message: `Watch ${mmss(youtube.start_s)} to ${mmss(youtube.end_s)}` })
      : t({ id: "youtube.from", message: `Watch from ${mmss(youtube.start_s)}` });
  const watch = `https://www.youtube.com/watch?v=${encodeURIComponent(youtube.video_id)}&t=${youtube.start_s}s`;

  return (
    <section className={styles.section} aria-label={t({ id: "youtube.label", message: "Video for this lesson" })} data-youtube="video">
      {youtube.gone ? (
        <p className={ui.muted}>
          <Trans id="youtube.gone">This video is no longer on YouTube, or no longer allowed in other sites.</Trans>
        </p>
      ) : playing ? (
        <div className={styles.frame}>
          <iframe
            ref={frame}
            src={embedUrl(youtube, lang, window.location.origin)}
            title={youtube.title ?? span}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        </div>
      ) : (
        <button type="button" className={styles.facade} onClick={() => setPlaying(true)}>
          <span className={styles.play} aria-hidden="true">
            <PlayIcon />
          </span>
          <span className={styles.facadeTitle}>{youtube.title}</span>
          <span className={styles.facadeMeta}>
            {youtube.channel} · {span}
          </span>
          <span className={styles.facadeHint}>
            <Trans id="youtube.loads">Plays from YouTube: nothing loads from YouTube until you press play.</Trans>
          </span>
        </button>
      )}
      {playing && !youtube.gone ? (
        <Stretch youtube={youtube} span={span} now={player.now} onBack={() => player.seek(youtube.start_s)} />
      ) : null}
      <p className={styles.links}>
        <a href={watch} target="_blank" rel="noreferrer noopener">
          <Trans id="youtube.open">Open on YouTube</Trans>
        </a>
        <a href={TERMS} target="_blank" rel="noreferrer noopener">
          <Trans id="youtube.terms">YouTube Terms of Service</Trans>
        </a>
      </p>
      <AnotherVideo lessonId={lesson.id} busy={busy} label="another" />
    </section>
  );
}
