// Why this installation makes no videos (the reason codes of RendererPort.available, yuo/core/media.py), in the
// learner's words. Shown in setup, in Settings and on a lesson without a video (videos
// were skipped without a word before).
import { Trans } from "@lingui/react/macro";

export function VideoUnavailableText({ reason, desktop }: { reason: string; desktop: boolean }) {
  if (desktop) {
    return (
      <Trans id="video.unavailable.desktop">
        The desktop app does not make videos yet, so your lessons are readings with practice and the tutor. Videos need
        the server version of Yuo for now.
      </Trans>
    );
  }
  switch (reason) {
    case "no_container":
      return (
        <Trans id="video.unavailable.no-container">
          The video service is not running, so lessons come as readings for now. Whoever runs this server can start the
          render service from the server's compose file.
        </Trans>
      );
    case "no_sandbox":
      return (
        <Trans id="video.unavailable.no-sandbox">
          This system cannot keep video code away from the network, so Yuo makes no videos here and lessons are readings.
          Videos are code written by the AI and only run shut off from the network.
        </Trans>
      );
    default:
      return (
        <Trans id="video.unavailable.not-installed">
          This installation has no video maker, so lessons are readings with practice and the tutor.
        </Trans>
      );
  }
}
