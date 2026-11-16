// The notes bubble: a floating head over a lesson
// video where the learner jots a question as it comes up, keeps watching, and sends them all to the tutor
// at the end. Each note keeps the moment of the video it was written at.
//
// It behaves like a phone's chat head: drag it anywhere and on release it springs to the nearest side edge
// (a fast fling picks the side it was flung to); while dragging, a dismiss target shows at the bottom and
// pulls the head in when near, and releasing there, off a side edge or with a fling out hides it. A tap (or
// Enter / Space, it is a button) opens the notes, Esc or a tap on the head closes them. In fullscreen it
// renders inside the fullscreen element, so it floats over the video. Its place and whether it is hidden
// stay in this browser; the notes are on the server (the lesson's notes list and the tutor see them).
// The `video.notes_bubble` setting turns it off.
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { keys, useNoteMutations, useNotes } from "../api/hooks";
import type { NoteOut } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { NoteIcon } from "../components/icons";
import { Button } from "../components/ui";
import { useTutorActions, useTutorState } from "../tutor/context";
import { NOTE_MAX } from "../lesson/Notes";
import { mmss } from "../format";
import { readJson, writeJson } from "../storage";
import styles from "./notesBubble.module.css";

const SIZE = 56;
const MARGIN = 12;
const MAGNET = 90; // px from the dismiss target's centre that pulls the head in
const FLING = 0.9; // px/ms: faster than this toward a side picks that side
const POS_KEY = "yuo.notesBubble.pos";
export const HIDDEN_KEY = "yuo.notesBubble.hidden";

type Side = "left" | "right";
type Pos = { side: Side; y: number }; // y: a share of the viewport height, so it survives resizes


function useViewport() {
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  useEffect(() => {
    const r = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", r);
    return () => window.removeEventListener("resize", r);
  }, []);
  return size;
}

/** The fullscreen element while there is one (the player's frame), so the bubble can render inside it. */
function useFullscreenElement(): Element | null {
  const [el, setEl] = useState<Element | null>(() => document.fullscreenElement);
  useEffect(() => {
    const on = () => setEl(document.fullscreenElement);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  return el;
}

type Gesture = { id: number; dx: number; dy: number; sx: number; sy: number; moved: boolean; hist: { x: number; t: number }[] };

export function NotesBubble({
  lessonId,
  versionId,
  videoTime,
  seek,
  onHide,
}: {
  lessonId: string;
  /** the video version the notes are on */
  versionId: string;
  videoTime: () => number | null;
  seek: (seconds: number) => void;
  onHide: () => void;
}) {
  const { t } = useLingui();
  const qc = useQueryClient();
  const tutor = useTutorActions();
  const tutorState = useTutorState();
  const notes = useNotes(lessonId);
  const m = useNoteMutations(lessonId);
  const { w: vw, h: vh } = useViewport();
  const container = useFullscreenElement();
  const [pos, setPos] = useState<Pos>(() => readJson<Pos>(POS_KEY, { side: "right", y: 0.62 }));
  const [drag, setDrag] = useState<{ x: number; y: number } | null>(null);
  const [nearDismiss, setNearDismiss] = useState(false);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [draftAt, setDraftAt] = useState<number | null>(null);
  const [showAsked, setShowAsked] = useState(false);
  const g = useRef<Gesture | null>(null);
  const dragged = useRef(false); // the click that ends a drag is not a tap
  const input = useRef<HTMLTextAreaElement>(null);
  const head = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  // the notes asked about get their message once the tutor has them: read them again when the dock closes
  const tutorWasOpen = useRef(tutorState.open);
  useEffect(() => {
    if (tutorWasOpen.current && !tutorState.open) void qc.invalidateQueries({ queryKey: keys.notes(lessonId) });
    tutorWasOpen.current = tutorState.open;
  }, [tutorState.open, qc, lessonId]);

  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        head.current?.focus();
      }
    };
    // a press outside the panel and the head closes it; an unsaved question stays typed
    const outside = (e: PointerEvent) => {
      const t = e.target as Node | null;
      if (t && (panel.current?.contains(t) || head.current?.contains(t))) return;
      setOpen(false);
    };
    window.addEventListener("keydown", k);
    document.addEventListener("pointerdown", outside, true);
    input.current?.focus();
    return () => {
      window.removeEventListener("keydown", k);
      document.removeEventListener("pointerdown", outside, true);
    };
  }, [open]);

  const restX = pos.side === "left" ? MARGIN : vw - SIZE - MARGIN;
  const restY = Math.min(Math.max(pos.y * vh, MARGIN), vh - SIZE - MARGIN);
  const target = { x: vw / 2 - SIZE / 2, y: vh - SIZE - 36 };

  // --- dragging -----------------------------------------------------------------------------------

  const onPointerDown = (e: ReactPointerEvent) => {
    if (e.button !== 0) return;
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    g.current = { id: e.pointerId, dx: e.clientX - restX, dy: e.clientY - restY, sx: e.clientX, sy: e.clientY, moved: false, hist: [] };
  };
  const onPointerMove = (e: ReactPointerEvent) => {
    const s = g.current;
    if (!s || s.id !== e.pointerId) return;
    if (!s.moved && Math.hypot(e.clientX - s.sx, e.clientY - s.sy) < 6) return;
    if (!s.moved) {
      s.moved = true;
      setOpen(false); // dragging an open bubble closes it
    }
    s.hist = [...s.hist.slice(-5), { x: e.clientX, t: e.timeStamp }];
    const x = e.clientX - s.dx;
    const y = e.clientY - s.dy;
    const near = Math.hypot(x - target.x, y - target.y) < MAGNET;
    setNearDismiss(near);
    setDrag(near ? target : { x, y });
  };
  const onPointerUp = (e: ReactPointerEvent) => {
    const s = g.current;
    g.current = null;
    if (!s || s.id !== e.pointerId || !s.moved) return; // a tap: the click handler toggles
    dragged.current = true;
    const x = e.clientX - s.dx;
    const y = e.clientY - s.dy;
    const h = s.hist;
    const vx = h.length > 1 ? (h[h.length - 1]!.x - h[0]!.x) / Math.max(1, h[h.length - 1]!.t - h[0]!.t) : 0;
    setDrag(null);
    setNearDismiss(false);
    const offEdge = x < -SIZE / 2 || x > vw - SIZE / 2;
    const flungOut = (x < SIZE && vx < -FLING * 1.6) || (x > vw - 2 * SIZE && vx > FLING * 1.6);
    if (Math.hypot(x - target.x, y - target.y) < MAGNET || offEdge || flungOut) {
      onHide();
      return;
    }
    const side: Side = vx > FLING ? "right" : vx < -FLING ? "left" : x + SIZE / 2 < vw / 2 ? "left" : "right";
    const p = { side, y: Math.min(Math.max(y, MARGIN), vh - SIZE - MARGIN) / vh };
    setPos(p);
    writeJson(POS_KEY, p);
  };
  const onClick = () => {
    if (dragged.current) {
      dragged.current = false;
      return;
    }
    setOpen((v) => !v);
  };

  // --- notes --------------------------------------------------------------------------------------

  const videoNotes = (notes.data ?? []).filter((n) => n.rendition_version_id != null);
  const fresh = videoNotes.filter((n) => !n.sent_message_id).sort((a, b) => (a.t_s ?? 0) - (b.t_s ?? 0));
  const asked = videoNotes.filter((n) => n.sent_message_id);

  const add = () => {
    const text = draft.trim();
    if (!text) return;
    const at = draftAt ?? videoTime() ?? 0;
    m.create.mutate(
      { text, rendition_version_id: versionId, t_s: Math.round(at * 10) / 10 },
      {
        onSuccess: () => {
          setDraft("");
          setDraftAt(null);
        },
      },
    );
  };
  const ask = () => {
    setOpen(false);
    tutor.open({
      refs: { lesson_id: lessonId, note_ids: fresh.map((n) => n.id).slice(0, 20) },
      text: t({ id: "notes-bubble.ask.prefill", message: "I wrote these questions while watching the video. Can you go through them with me?" }),
    });
  };

  const x = drag?.x ?? restX;
  const y = drag?.y ?? restY;
  const panelW = Math.min(360, vw - 2 * MARGIN);
  const panelLeft = pos.side === "left" ? MARGIN : vw - panelW - MARGIN;
  const below = restY < vh / 2;
  const panelStyle: CSSProperties = below
    ? { left: panelLeft, top: restY + SIZE + 8, maxHeight: vh - restY - SIZE - 8 - MARGIN, width: panelW }
    : { left: panelLeft, bottom: vh - restY + 8, maxHeight: restY - 8 - MARGIN, width: panelW };
  const atNow = draftAt ?? videoTime() ?? 0;

  const row = (n: NoteOut) => (
    <li key={n.id} className={styles.note} data-asked={n.sent_message_id ? "" : undefined}>
      {n.t_s != null ? (
        <button
          type="button"
          className={styles.at}
          onClick={() => seek(n.t_s!)}
          aria-label={t({ id: "notes-bubble.seek", message: `Play the video from ${mmss(n.t_s)}` })}
        >
          {mmss(n.t_s)}
        </button>
      ) : null}
      <span className={styles.noteText}>{n.text}</span>
      <button
        type="button"
        className={styles.del}
        disabled={m.remove.isPending}
        onClick={() => m.remove.mutate(n.id)}
        aria-label={t({ id: "notes-bubble.delete", message: "Delete this note" })}
      >
        ×
      </button>
    </li>
  );

  return createPortal(
    <div className={styles.layer} data-fullscreen={container ? "" : undefined}>
      {drag ? (
        <div
          className={styles.target}
          data-hot={nearDismiss ? "" : undefined}
          style={{ left: target.x - 4, top: target.y - 4 }}
          aria-hidden="true"
        >
          ×
        </div>
      ) : null}
      {open ? (
        <div
          ref={panel}
          className={styles.panel}
          style={panelStyle}
          role="dialog"
          aria-label={t({ id: "notes-bubble.title", message: "Questions for the tutor" })}
        >
          <div className={styles.panelHead}>
            <strong>
              <Trans id="notes-bubble.title">Questions for the tutor</Trans>
            </strong>
          </div>
          {videoNotes.length === 0 ? (
            <p className={styles.hint}>
              <Trans id="notes-bubble.hint">
                Write a question as it comes up and keep watching. The moment of the video is saved with it; send them
                all to the tutor when you are done.
              </Trans>
            </p>
          ) : null}
          {fresh.length ? <ul className={styles.list}>{fresh.map(row)}</ul> : null}
          <textarea
            ref={input}
            className={styles.input}
            rows={2}
            maxLength={NOTE_MAX}
            value={draft}
            aria-label={t({ id: "notes-bubble.input", message: `Question at ${mmss(atNow)}` })}
            placeholder={t({ id: "notes-bubble.placeholder", message: `Question at ${mmss(atNow)}… (Enter saves)` })}
            onChange={(e) => {
              if (!draft && e.target.value) setDraftAt(videoTime());
              setDraft(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                add();
              }
            }}
          />
          <div className={styles.actions}>
            <Button variant="ghost" small onPress={add} isDisabled={m.create.isPending || !draft.trim()}>
              <Trans id="notes-bubble.save">Save question</Trans>
            </Button>
            <Button small onPress={ask} isDisabled={!fresh.length}>
              {fresh.length ? (
                <Plural id="notes-bubble.ask" value={fresh.length} one="Ask the tutor (#)" other="Ask the tutor (#)" />
              ) : (
                <Trans id="notes-bubble.ask.none">Ask the tutor</Trans>
              )}
            </Button>
          </div>
          {m.create.isError ? <ErrorNotice error={m.create.error} /> : null}
          {m.remove.isError ? <ErrorNotice error={m.remove.error} /> : null}
          {asked.length ? (
            <>
              <button type="button" className={styles.linkBtn} onClick={() => setShowAsked((v) => !v)} aria-expanded={showAsked}>
                {showAsked ? (
                  <Plural id="notes-bubble.asked.hide" value={asked.length} one="Hide # already asked" other="Hide # already asked" />
                ) : (
                  <Plural id="notes-bubble.asked.show" value={asked.length} one="Show # already asked" other="Show # already asked" />
                )}
              </button>
              {showAsked ? <ul className={styles.list}>{asked.map(row)}</ul> : null}
            </>
          ) : null}
        </div>
      ) : null}
      <button
        ref={head}
        type="button"
        className={styles.head}
        data-dragging={drag ? "" : undefined}
        data-open={open ? "" : undefined}
        style={{ transform: `translate(${x}px, ${y}px)` }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onClick={onClick}
        aria-expanded={open}
        aria-label={
          open
            ? t({ id: "notes-bubble.close", message: "Close the questions for the tutor" })
            : t({ id: "notes-bubble.open", message: "Questions for the tutor: tap to open, drag to move or to the × to hide" })
        }
      >
        <NoteIcon />
        {fresh.length ? <span className={styles.badge}>{fresh.length}</span> : null}
      </button>
    </div>,
    container ?? document.body,
  );
}
