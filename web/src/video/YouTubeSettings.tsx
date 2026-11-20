// Settings > Videos, when lessons use YouTube videos (video.source): what the learner takes on (YouTube's terms
// do not allow reading its pages by automated means), and an optional YouTube Data API key for the searches.
import { Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { FieldError, Input, Label, Text, TextField } from "react-aria-components";
import type { SettingOut } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button, Notice, ui } from "../components/ui";
import { useAccess, useRemoveYouTubeKey, useSetYouTubeKey } from "../onboarding/api";

const KEYS_URL = "https://console.cloud.google.com/apis/library/youtube.googleapis.com";

export function YouTubeSettings({ settings }: { settings: SettingOut[] }) {
  const source = settings.find((s) => s.key === "video.source")?.value;
  if (source !== "youtube") return null;
  return (
    <div className={ui.stack} data-youtube-settings>
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
      <YouTubeKey />
    </div>
  );
}

function YouTubeKey() {
  const { t } = useLingui();
  const access = useAccess();
  const save = useSetYouTubeKey();
  const remove = useRemoveYouTubeKey();
  const [key, setKey] = useState("");
  const isSet = access.data?.youtube ?? false;
  const malformed = key.trim() !== "" && !key.trim().startsWith("AIza");

  return (
    <form
      className={ui.stack}
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        const value = key.trim();
        if (!value || malformed) return;
        save.mutate(value, { onSuccess: () => setKey("") });
      }}
    >
      <p>
        {isSet ? (
          <Trans id="youtube.key.set">A YouTube key is set: searches use YouTube's API, about 100 lessons a day.</Trans>
        ) : (
          <Trans id="youtube.key.none">
            Optional: with a YouTube Data API key, searches go through YouTube's API (free, about 100 lessons a day).
            Without one, Yuo searches YouTube's site directly.
          </Trans>
        )}{" "}
        <a href={KEYS_URL} target="_blank" rel="noopener noreferrer">
          <Trans id="youtube.key.link">Get a key in Google Cloud (opens in a new tab)</Trans>
        </a>
      </p>
      <TextField
        type="password"
        value={key}
        onChange={(v) => {
          setKey(v);
          if (save.isError) save.reset();
        }}
        autoComplete="off"
        isInvalid={malformed}
        className={ui.field}
        spellCheck="false"
      >
        <Label className={ui.label}>
          {isSet
            ? t({ id: "youtube.key.label.replace", message: "New YouTube key" })
            : t({ id: "youtube.key.label", message: "YouTube key" })}
        </Label>
        <Input className={ui.input} autoCapitalize="none" autoCorrect="off" />
        <Text slot="description" className={ui.description}>
          {t({ id: "youtube.key.hint", message: "It starts with AIza." })}
        </Text>
        <FieldError className={ui.fieldError}>
          {malformed ? t({ id: "youtube.key.format", message: "That does not look like a Google API key. It starts with AIza." }) : null}
        </FieldError>
      </TextField>
      <div className={ui.row}>
        <Button type="submit" isDisabled={!key.trim() || malformed || save.isPending}>
          {save.isPending ? (
            <Trans id="youtube.key.checking">Checking the key…</Trans>
          ) : (
            <Trans id="youtube.key.save">Check and save the key</Trans>
          )}
        </Button>
        {isSet ? (
          <Button variant="secondary" onPress={() => remove.mutate()} isDisabled={remove.isPending}>
            <Trans id="youtube.key.remove">Remove the key</Trans>
          </Button>
        ) : null}
      </div>
      {save.isSuccess ? (
        <p role="status">
          <Trans id="youtube.key.saved">The key works and is saved.</Trans>
        </p>
      ) : null}
      {save.isError ? <ErrorNotice error={save.error} /> : null}
      {remove.isError ? <ErrorNotice error={remove.error} /> : null}
    </form>
  );
}
