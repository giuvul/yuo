// What a review question shows once it is resolved, and the dialog to report a question.
import { Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import {
  Dialog,
  Heading,
  Modal,
  ModalOverlay,
} from "react-aria-components";
import type { Graded } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { grove, LeafPop } from "../components/Grove";
import { BookIcon, CheckIcon, LeafIcon } from "../components/icons";
import { Button, ButtonLink, Field, Notice, ui } from "../components/ui";
import { reportItem } from "./api";
import styles from "./review.module.css";
import { MathText } from "../components/MathText";

/** The feedback once a question is resolved: the verdict, why, the idea behind it and where to read it again. */
export function Resolved({ feedback }: { feedback: Graded }) {
  const outcome = feedback.outcome;
  const right = outcome === "first" || outcome === "second";
  const sureAndWrong = outcome !== "first" && (feedback.tries ?? 0) > 0 && feedback.guessing === false;
  const revisit = feedback.revisit;
  const lesson = feedback.lesson_title;
  return (
    <Notice
      tone={right ? "success" : "error"}
      role="status"
      icon={
        outcome === "first" ? (
          <LeafPop>
            <LeafIcon />
          </LeafPop>
        ) : right ? (
          <CheckIcon />
        ) : (
          <BookIcon />
        )
      }
      className={grove.appear}
    >
      <div className={styles.resolved}>
        <p className={styles.verdict}>
          {outcome === "first" ? (
            <Trans id="review.feedback.first">Right, first try.</Trans>
          ) : outcome === "second" ? (
            <Trans id="review.feedback.second">Right on the second try.</Trans>
          ) : (
            <Trans id="review.feedback.revealed">Here is the answer.</Trans>
          )}
        </p>
        {sureAndWrong ? (
          <p>
            <Trans id="review.feedback.sure">You were sure: worth a closer look.</Trans>
          </p>
        ) : null}
        {feedback.solution ? (
          <p className={styles.preWrap}>
            <MathText text={feedback.solution} />
          </p>
        ) : null}
        {feedback.concept ? (
          <p>
            <span className={styles.detailLabel}>
              <Trans id="review.feedback.concept">Idea</Trans>
            </span>{" "}
            <MathText text={feedback.concept} />
          </p>
        ) : null}
        {revisit ? (
          <p>
            <Trans id="review.feedback.revisit">Look again: {revisit}</Trans>
          </p>
        ) : null}
        {feedback.lesson_id ? (
          <p>
            <ButtonLink to="/lessons/$lessonId" params={{ lessonId: feedback.lesson_id }} variant="secondary" small>
              <BookIcon />
              {lesson ? <Trans id="review.feedback.lesson">Lesson: {lesson}</Trans> : <Trans id="review.feedback.lesson.plain">Open the lesson</Trans>}
            </ButtonLink>
          </p>
        ) : null}
      </div>
    </Notice>
  );
}

export function ReportDialog({
  open,
  itemId,
  onClose,
  onReported,
}: {
  open: boolean;
  itemId: string;
  onClose: () => void;
  onReported: () => void;
}) {
  const { t } = useLingui();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await reportItem(itemId, reason.trim());
      setReason("");
      onReported();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <ModalOverlay className={styles.overlay} isOpen={open} onOpenChange={(o) => (o ? undefined : onClose())} isDismissable>
      <Modal>
        <Dialog className={styles.dialog}>
          <Heading slot="title">
            <Trans id="review.report.title">Report this question</Trans>
          </Heading>
          <p className={ui.muted}>
            <Trans id="review.report.body">
              A wrong or unclear question is taken out of your reviews. It does not count in this session.
            </Trans>
          </p>
          <Field
            label={t({ id: "review.report.reason", message: "What is wrong with it? (optional)" })}
            value={reason}
            onChange={setReason}
            maxLength={300}
            multiline
          />
          {error ? <ErrorNotice error={error} /> : null}
          <div className={ui.row}>
            <Button onPress={() => void send()} isDisabled={busy}>
              <Trans id="review.report.send">Report and skip</Trans>
            </Button>
            <Button variant="secondary" onPress={onClose} isDisabled={busy}>
              <Trans id="review.report.cancel">Cancel</Trans>
            </Button>
          </div>
        </Dialog>
      </Modal>
    </ModalOverlay>
  );
}
