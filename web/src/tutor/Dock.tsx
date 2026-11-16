// The ever-present tutor dock: one floating button on every screen
// that opens a side panel on wide screens and a bottom sheet on phones. Ctrl/Cmd+J toggles it, Esc
// closes it, focus moves into the composer on open and back where it was on close. Never modal: the
// page stays usable beside it. One polite status region announces "answering" and finished replies.
import { plural } from "@lingui/core/macro";
import { useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button as AriaButton } from "react-aria-components";
import { type TutorMessage } from "../api/client";
import { ChatIcon } from "../components/icons";
import { useOutbox } from "../outbox/context";
import {
  addNudges,
  onTutorMessage,
  PENDING_STATUSES,
  useTutorName,
} from "./api";
import { useEvent, useTutorActions, useTutorState } from "./context";
import { NudgePeek, useVisibleNudges } from "./Nudges";
import { useEventStream } from "./stream";
import { REVIEW_TEMPLATES, TEMPLATES, errorText } from "./texts";
import styles from "./tutor.module.css";
import { DOCK_ID, DockPanel, useSender } from "./DockPanel";

/** Announces "answering" and finished replies politely; counts replies that land while closed. */
function useReplyAnnouncements(open: boolean) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const qc = useQueryClient();
  const [announcement, setAnnouncement] = useState("");
  const [unread, setUnread] = useState(0);
  const openRef = useRef(open);
  openRef.current = open;
  const seen = useRef(new Map<string, TutorMessage["status"]>());

  const see = useEvent((m: TutorMessage) => {
    if (m.role !== "tutor") return;
    const before = seen.current.get(m.id);
    seen.current.set(m.id, m.status);
    if (before === m.status) return;
    if (before === undefined && PENDING_STATUSES.has(m.status)) {
      setAnnouncement(t({ id: "tutor.announce.answering", message: "The tutor is answering." }));
    } else if (before !== undefined && PENDING_STATUSES.has(before) && m.status === "done") {
      const template = m.template ? (TEMPLATES[m.template] ?? REVIEW_TEMPLATES[m.template]) : undefined;
      const text = template ? i18n._(template) : m.text;
      const preview = text.length > 300 ? `${text.slice(0, 300)}…` : text;
      setAnnouncement(t({ id: "tutor.announce.done", message: `Answer ready: ${preview}` }));
      if (!openRef.current) setUnread((n) => n + 1);
    } else if (before !== undefined && PENDING_STATUSES.has(before) && m.status === "failed") {
      const reason = i18n._(errorText(m.error));
      setAnnouncement(t({ id: "tutor.announce.failed", message: `The tutor could not answer. ${reason}` }));
      if (!openRef.current) setUnread((n) => n + 1);
    }
  });

  useEffect(() => {
    const offMessages = onTutorMessage(see);
    const offCache = qc.getQueryCache().subscribe((ev) => {
      if (ev.type !== "updated" || ev.action.type !== "success") return;
      const key = ev.query.queryKey;
      if (key[0] !== "tutor" || key[1] !== "messages") return;
      for (const m of (ev.query.state.data as TutorMessage[] | undefined) ?? []) see(m);
    });
    return () => {
      offMessages();
      offCache();
    };
  }, [qc, see]);

  useEffect(() => {
    if (open) setUnread(0);
  }, [open]);

  return { announcement, unread };
}

export function TutorDock() {
  const { t } = useLingui();
  const qc = useQueryClient();
  const outbox = useOutbox();
  const state = useTutorState();
  const tutor = useTutorActions();
  const send = useSender();
  const fabRef = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const name = useTutorName(state.open) ?? t({ id: "tutor.name.default", message: "Tutor" });
  const { announcement, unread } = useReplyAnnouncements(state.open);
  const nudges = useVisibleNudges();
  const peek = nudges.find((n) => n.level === "coach" || n.level === "active");
  const waiting = nudges.length > 0;

  useEventStream();

  // nudges in the ingest reply; an answer changes what the tutor may say about the item
  useEffect(
    () =>
      outbox.onFlush((r) => {
        addNudges(qc, r.nudges);
        if (r.accepted.length) void qc.invalidateQueries({ queryKey: ["tutor", "context"] });
      }),
    [outbox, qc],
  );

  // messages that could not be sent go out again when the browser is back online
  const resendAll = useEvent(() => {
    for (const s of state.sends) if (s.state === "unsent") void send(s);
  });
  useEffect(() => {
    window.addEventListener("online", resendAll);
    return () => window.removeEventListener("online", resendAll);
  }, [resendAll]);

  // Ctrl/Cmd+J anywhere toggles the dock
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "j") {
        e.preventDefault();
        tutor.toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tutor]);

  // React Aria's Button does not pass these through; the shortcut is announced and shown on hover
  const shortcutHint = t({ id: "tutor.fab.shortcut", message: "Open the tutor (Ctrl+J)" });
  useEffect(() => {
    fabRef.current?.setAttribute("aria-keyshortcuts", "Control+J Meta+J");
    fabRef.current?.setAttribute("title", shortcutHint);
  }, [state.open, shortcutHint]);

  // focus goes back where it was before the dock opened
  const wasOpen = useRef(state.open);
  useEffect(() => {
    if (state.open && !wasOpen.current) {
      const active = document.activeElement;
      returnTo.current = active instanceof HTMLElement && active !== document.body ? active : null;
    }
    if (!state.open && wasOpen.current) {
      const target = returnTo.current;
      if (target && target.isConnected && !target.closest(`#${DOCK_ID}`)) target.focus();
      else fabRef.current?.focus();
    }
    wasOpen.current = state.open;
  }, [state.open]);

  return (
    <>
      <div role="status" className="visually-hidden">
        {announcement}
      </div>
      {state.open ? (
        <DockPanel onClose={tutor.close} tutorName={name} />
      ) : (
        <div className={styles.launcher}>
          {peek ? <NudgePeek nudge={peek} /> : null}
          <AriaButton
            ref={fabRef}
            className={styles.fab}
            onPress={() => tutor.open()}
            aria-expanded={false}
          >
            <span aria-hidden="true" className={styles.fabIcon}>
              <ChatIcon />
            </span>
            <span className={styles.fabName}>{name}</span>
            {unread > 0 ? (
              <span className={styles.fabBadge}>
                <span aria-hidden="true">{unread}</span>
                <span className="visually-hidden">
                  {t({ id: "tutor.fab.unread", message: plural(unread, { one: ", # new reply", other: ", # new replies" }) })}
                </span>
              </span>
            ) : waiting && !peek ? (
              <span className={styles.fabDot}>
                <span className="visually-hidden">
                  {t({ id: "tutor.fab.suggestion", message: ", a suggestion is waiting" })}
                </span>
              </span>
            ) : null}
          </AriaButton>
        </div>
      )}
    </>
  );
}
