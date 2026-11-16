// A button that asks once before doing something that cannot be undone: the inline two-step pattern of the
// devices screen, in one place. The question appears in place of the button, with
// the confirming button first and Cancel beside it; focus moves to the question's buttons. Without a question (a
// row whose own name says what goes) the two buttons stand alone, grouped under `groupLabel`.
import { Trans } from "@lingui/react/macro";
import { useId, useState, type ReactNode } from "react";
import { Button } from "./ui";
import ui from "./ui.module.css";

export function ConfirmAction({
  label,
  question,
  groupLabel,
  confirmLabel,
  onConfirm,
  pending = false,
  small = true,
}: {
  label: ReactNode;
  question?: ReactNode;
  groupLabel?: string;
  confirmLabel: ReactNode;
  onConfirm: () => void;
  pending?: boolean;
  small?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const id = useId();
  if (!asking) {
    return (
      <div className={ui.row}>
        <Button small={small} variant="secondary" onPress={() => setAsking(true)}>
          {label}
        </Button>
      </div>
    );
  }
  const buttons = (
    <>
      <Button small={small} isDisabled={pending} autoFocus onPress={onConfirm}>
        {confirmLabel}
      </Button>
      <Button small={small} variant="secondary" isDisabled={pending} onPress={() => setAsking(false)}>
        <Trans id="confirm.cancel">Cancel</Trans>
      </Button>
    </>
  );
  if (question === undefined) {
    return (
      <div className={ui.row} role="group" aria-label={groupLabel}>
        {buttons}
      </div>
    );
  }
  return (
    <div className={ui.stack} role="group" aria-labelledby={id}>
      <p id={id}>{question}</p>
      <div className={ui.row}>{buttons}</div>
    </div>
  );
}
