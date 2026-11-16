// Tutor suggestions. The server decides when one is due (breakpoints only, never in a test,
// capped per session); the client shows it by level: `coach` and `active` as a one-line peek by
// the dock button that says why it appeared, `quiet` as a dot only. Each can be accepted (opens the
// tutor with a prefilled question and the right context), dismissed, or muted for good.
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { api, unwrap, type NudgeOut } from "../api/client";
import { keys as appKeys } from "../api/hooks";
import { Button, ui } from "../components/ui";
import { useDecideNudge, useNudges } from "./api";
import { useTutorActions, type OpenOptions } from "./context";
import styles from "./tutor.module.css";

const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const num = (v: unknown, fallback: number): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

/** Nudges worth showing at all ("off" never reaches the client, but be safe). */
export function useVisibleNudges(): NudgeOut[] {
  const nudges = useNudges();
  return (nudges.data ?? []).filter((n) => n.level !== "off");
}

function NudgeText({ n }: { n: NudgeOut }) {
  const p = n.params;
  switch (n.trigger) {
    case "repeated_error": {
      const objective = str(p["objective"]);
      const misses = num(p["misses"], 2);
      return (
        <Trans id="tutor.nudge.repeated-error">
          You missed “{objective}” {misses} times in this session. Look at it together?
        </Trans>
      );
    }
    case "fast_guessing":
      return (
        <Trans id="tutor.nudge.fast-guessing">
          Your last answers came very fast and some were wrong. Go through the next one slowly together?
        </Trans>
      );
    case "unsent_notes": {
      const notes = num(p["notes"], 1);
      return (
        <Plural
          id="tutor.nudge.unsent-notes"
          value={notes}
          one="You left # note on this lesson that you have not asked about. Ask the tutor now?"
          other="You left # notes on this lesson that you have not asked about. Ask the tutor now?"
        />
      );
    }
    case "failed_test": {
      const skill = str(p["skill"]);
      return (
        <Trans id="tutor.nudge.failed-test">
          The test on {skill} did not pass yet. Plan what to study before the retake?
        </Trans>
      );
    }
  }
}

/** Accept, dismiss and mute; accept opens the dock with a suitable question and context. */
function useNudgeActions() {
  const { t } = useLingui();
  const qc = useQueryClient();
  const decide = useDecideNudge();
  const tutor = useTutorActions();

  const openFor = async (n: NudgeOut): Promise<OpenOptions> => {
    const p = n.params;
    const base = { path_id: n.path_id };
    switch (n.trigger) {
      case "repeated_error": {
        const objective = str(p["objective"]);
        return {
          refs: base,
          text: t({
            id: "tutor.nudge.prefill.repeated-error",
            message: `I keep getting “${objective}” wrong. Can you explain it another way?`,
          }),
        };
      }
      case "fast_guessing":
        return {
          refs: base,
          text: t({ id: "tutor.nudge.prefill.fast-guessing", message: "Can we go through the next question slowly together?" }),
        };
      case "unsent_notes": {
        const lessonId = str(p["lesson_id"]) || null;
        let noteIds: string[] = [];
        if (lessonId) {
          try {
            const notes = await qc.fetchQuery({
              queryKey: appKeys.notes(lessonId),
              queryFn: () =>
                unwrap(api.GET("/api/lessons/{lesson_id}/notes", { params: { path: { lesson_id: lessonId } } })),
            });
            noteIds = notes.filter((x) => x.sent_message_id === null).map((x) => x.id).slice(0, 20);
          } catch {
            noteIds = [];
          }
        }
        return {
          refs: { ...base, lesson_id: lessonId, note_ids: noteIds },
          text: t({ id: "tutor.nudge.prefill.unsent-notes", message: "I left notes on this lesson. Can you go through them with me?" }),
        };
      }
      case "failed_test": {
        const skill = str(p["skill"]);
        return {
          refs: { ...base, skill_id: str(p["skill_id"]) || null },
          text: t({
            id: "tutor.nudge.prefill.failed-test",
            message: `What should I study before I retake the test on ${skill}?`,
          }),
        };
      }
    }
  };

  return {
    accept: async (n: NudgeOut) => {
      decide.mutate({ id: n.id, action: "accept" });
      tutor.open(await openFor(n));
    },
    dismiss: (n: NudgeOut) => decide.mutate({ id: n.id, action: "dismiss" }),
    mute: (n: NudgeOut) => decide.mutate({ id: n.id, action: "mute" }),
  };
}

function NudgeButtons({ n }: { n: NudgeOut }) {
  const a = useNudgeActions();
  return (
    <div className={ui.row}>
      <Button small onPress={() => void a.accept(n)}>
        <Trans id="tutor.nudge.accept">Ask the tutor</Trans>
      </Button>
      <Button small variant="secondary" onPress={() => a.dismiss(n)}>
        <Trans id="tutor.nudge.dismiss">Not now</Trans>
      </Button>
      <Button small variant="secondary" onPress={() => a.mute(n)}>
        <Trans id="tutor.nudge.mute">Don't suggest this</Trans>
      </Button>
    </div>
  );
}

/** The one-line peek beside the closed dock button (coach and active levels). */
export function NudgePeek({ nudge }: { nudge: NudgeOut }) {
  const { t } = useLingui();
  return (
    <section className={styles.peek} aria-label={t({ id: "tutor.nudge.peek.label", message: "Suggestion from the tutor" })}>
      <p className={styles.peekText}>
        <NudgeText n={nudge} />
      </p>
      <NudgeButtons n={nudge} />
    </section>
  );
}

/** All waiting suggestions, inside the open dock (quiet ones are only reachable here). */
export function DockNudges({ nudges }: { nudges: NudgeOut[] }) {
  const { t } = useLingui();
  if (!nudges.length) return null;
  return (
    <section className={styles.dockNudges} aria-label={t({ id: "tutor.nudge.list.label", message: "Suggestions" })}>
      {nudges.map((n) => (
        <div key={n.id} className={styles.dockNudge}>
          <p>
            <NudgeText n={n} />
          </p>
          <NudgeButtons n={n} />
        </div>
      ))}
    </section>
  );
}
