import { Trans } from "@lingui/react/macro";
import { useState } from "react";
import { Button as AriaButton } from "react-aria-components";
import { Button, Notice, ui } from "../components/ui";
import { install, useInstallPrompt, useUpdateReady } from "./pwa";

/** "Save app shortcut" in the header, only where the browser offers installing (hidden otherwise). */
export function InstallButton({ className }: { className?: string }) {
  const prompt = useInstallPrompt();
  if (!prompt) return null;
  return (
    <AriaButton className={className} onPress={() => void install()}>
      <Trans id="pwa.install">Save app shortcut</Trans>
    </AriaButton>
  );
}

/** A new version is ready: the learner reloads when it suits them (nothing is lost: the outbox keeps events). */
export function UpdateNotice() {
  const update = useUpdateReady();
  const [busy, setBusy] = useState(false);
  if (!update) return null;
  return (
    <div role="status">
      <Notice tone="info">
        <div className={ui.row}>
          <span>
            <Trans id="pwa.update.text">A new version of Yuo is ready.</Trans>
          </span>
          <Button
            small
            isDisabled={busy}
            onPress={() => {
              setBusy(true);
              void update();
            }}
          >
            <Trans id="pwa.update.reload">Reload to update</Trans>
          </Button>
        </div>
      </Notice>
    </div>
  );
}
