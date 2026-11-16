import { Trans } from "@lingui/react/macro";
import { ApiError } from "../api/client";
import { Notice } from "./ui";

/** A failed request in plain words: offline, not found, restarting, or the server's own message. */
export function ErrorNotice({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return (
        <Notice tone="error" icon={true}>
          <Trans id="error.not-found">This could not be found. It may have been removed.</Trans>
        </Notice>
      );
    }
    // a proxy's own 502/503/504 (no answer from Yuo behind it, e.g. while it restarts after an update)
    if ([502, 503, 504].includes(error.status) && error.message === `HTTP ${error.status}`) {
      return (
        <Notice tone="error" icon={true}>
          <Trans id="error.restarting">Yuo is restarting or cannot be reached right now. Try again in a moment.</Trans>
        </Notice>
      );
    }
    const detail = error.message;
    return (
      <Notice tone="error" icon={true}>
        <Trans id="error.server">The server could not do this: {detail}</Trans>
      </Notice>
    );
  }
  return (
    <Notice tone="error" icon={true}>
      <Trans id="error.network">Yuo's server cannot be reached. Check that it is running, then try again.</Trans>
    </Notice>
  );
}
