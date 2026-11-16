// The lesson video player: Media Chrome controls over a native <video>. Every other module talks to
// this component only (props in, callbacks out), so a later move to another player touches this
// file alone (06 risk). Captions are never burned into the picture: they are the WebVTT track,
// shown or hidden by the learner, and the choice is reported through `onCaptionsChange`.
import { useEffect, useId, useRef } from "react";
import {
  MediaCaptionsButton,
  MediaControlBar,
  MediaController,
  MediaDurationDisplay,
  MediaFullscreenButton,
  MediaMuteButton,
  MediaPlaybackRateButton,
  MediaPlayButton,
  MediaTimeDisplay,
  MediaTimeRange,
  MediaVolumeRange,
} from "media-chrome/react";
import { setLanguage } from "media-chrome/dist/utils/i18n.js";
import styles from "./video.module.css";

export type VideoPlayerProps = {
  src: string;
  poster?: string;
  captions?: { src: string; lang: string; label: string };
  /** whether captions start shown (the learner's setting) */
  captionsOn: boolean;
  onCaptionsChange?: (on: boolean) => void;
  /** current time while playing, at most about once a second, and on pause / seek */
  onTime?: (seconds: number) => void;
  /** pauses the video whenever this number changes (e.g. the tutor opened) */
  pauseKey?: number;
  /** jumps to `s` seconds and plays whenever `n` changes (a note's moment) */
  seek?: { s: number; n: number };
  /** the accessible name of the group holding the picture and its controls */
  label: string;
  locale: string;
};

const PLAYBACK_RATES = [0.75, 1, 1.25, 1.5, 2];

function captionsShowing(video: HTMLVideoElement): boolean {
  return Array.from(video.textTracks).some(
    (t) => (t.kind === "captions" || t.kind === "subtitles") && t.mode === "showing",
  );
}

export default function VideoPlayer({
  src,
  poster,
  captions,
  captionsOn,
  onCaptionsChange,
  onTime,
  pauseKey,
  seek,
  label,
  locale,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const controllerId = `player-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const callbacks = useRef({ onCaptionsChange, onTime });
  callbacks.current = { onCaptionsChange, onTime };

  useEffect(() => {
    setLanguage(locale); // Media Chrome's own control labels (it ships its own dictionaries)
  }, [locale]);

  // report caption toggles; the first state after load is the one we asked for, not a choice
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let last = captionsOn;
    const onChange = () => {
      const now = captionsShowing(video);
      if (now !== last) {
        last = now;
        callbacks.current.onCaptionsChange?.(now);
      }
    };
    video.textTracks.addEventListener("change", onChange);
    return () => video.textTracks.removeEventListener("change", onChange);
  }, []); // captionsOn is the starting point only

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let lastSent = -1;
    const report = (force: boolean) => {
      const s = video.currentTime;
      if (force || Math.abs(s - lastSent) >= 1) {
        lastSent = s;
        callbacks.current.onTime?.(s);
      }
    };
    const tick = () => report(false);
    const now = () => report(true);
    video.addEventListener("timeupdate", tick);
    video.addEventListener("pause", now);
    video.addEventListener("seeked", now);
    return () => {
      video.removeEventListener("timeupdate", tick);
      video.removeEventListener("pause", now);
      video.removeEventListener("seeked", now);
    };
  }, []);

  // fullscreen takes the picture and the bar below it, not the picture alone
  const frameRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const controller = document.getElementById(controllerId) as (HTMLElement & { fullscreenElement?: Element }) | null;
    if (controller && frameRef.current) controller.fullscreenElement = frameRef.current;
  }, [controllerId]);

  const firstPause = useRef(pauseKey);
  useEffect(() => {
    if (pauseKey === firstPause.current) return;
    videoRef.current?.pause();
  }, [pauseKey]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !seek) return;
    video.currentTime = seek.s;
    void video.play().catch(() => undefined); // a browser that refuses autoplay keeps the new position
  }, [seek?.n]); // a new request, not a new value

  return (
    <div className={styles.player} ref={frameRef} role="group" aria-label={label}>
      {/* the controller is the player's region, labelled by Media Chrome ("video player", translated) */}
      <MediaController
        id={controllerId}
        className={styles.controller}
        defaultSubtitles={captionsOn || undefined}
      >
        <video
          ref={videoRef}
          slot="media"
          src={src}
          poster={poster}
          preload="metadata"
          playsInline
        >
          {captions ? (
            <track
              kind="captions"
              src={captions.src}
              srcLang={captions.lang}
              label={captions.label}
              default={captionsOn}
            />
          ) : null}
        </video>
        {/* a big play target over the picture for the pointer; the bar's play button is the one for keyboards */}
        <MediaPlayButton slot="centered-chrome" className={styles.bigPlay} aria-hidden="true" tabIndex={-1} />
      </MediaController>
      {/* below the picture, not over it: captions keep their place and the controls stay readable */}
      <MediaControlBar className={styles.bar} {...{ mediacontroller: controllerId }}>
        <MediaPlayButton />
        <MediaTimeRange className={styles.range} />
        <MediaTimeDisplay showDuration={false} />
        <MediaDurationDisplay className={styles.duration} />
        <MediaMuteButton />
        <MediaVolumeRange className={styles.volume} />
        <MediaPlaybackRateButton rates={PLAYBACK_RATES} />
        {captions ? <MediaCaptionsButton /> : null}
        <MediaFullscreenButton />
      </MediaControlBar>
    </div>
  );
}
