// The tutor context: every screen publishes references (path, skill, lesson,
// attempt, item); the dock merges them, adds what the learner chose (a text selection, notes) and
// asks the server what the tutor may see. The client only names things; the server resolves them.
//
// Also the dock's state (open, which view, a prefilled message) and messages that have not reached
// the server yet, so they survive closing the dock.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { TutorContextIn } from "../api/client";

type TutorRefs = {
  screen?: string;
  path_id?: string | null;
  skill_id?: string | null;
  lesson_id?: string | null;
  attempt_id?: string | null;
  item_version_id?: string | null;
  note_ids?: string[];
  /** where the lesson video is (seconds), while it plays */
  video_s?: number | null;
};

export type Selection = { text: string; bid: string | null };

export type DockView = "thread" | "all";

/** A message the dock is sending or could not send (network): retried with the same id. */
export type LocalSend = {
  id: string;
  text: string;
  context: TutorContextIn;
  state: "sending" | "unsent" | "failed";
  error?: string;
};

export type OpenOptions = {
  /** text to put in the composer */
  text?: string;
  selection?: Selection;
  /** extra references for the next message (e.g. the skill a suggestion is about) */
  refs?: TutorRefs;
  view?: DockView;
  /** scroll to and focus this message once it is shown */
  messageId?: string;
};

type State = {
  open: boolean;
  view: DockView;
  /** changes whenever a caller asks to put text in the composer */
  prefill: { text: string; n: number } | null;
  selection: Selection | null;
  extra: TutorRefs;
  focusMessage: string | null;
  sends: LocalSend[];
};

type Actions = {
  publish: (id: string, refs: TutorRefs | null) => void;
  open: (opts?: OpenOptions) => void;
  close: () => void;
  toggle: () => void;
  setView: (view: DockView) => void;
  clearSelection: () => void;
  clearExtra: () => void;
  messageFocused: () => void;
  upsertSend: (s: LocalSend) => void;
  dropSend: (id: string) => void;
};

const noop = () => {};
const NO_ACTIONS: Actions = {
  publish: noop,
  open: noop,
  close: noop,
  toggle: noop,
  setView: noop,
  clearSelection: noop,
  clearExtra: noop,
  messageFocused: noop,
  upsertSend: noop,
  dropSend: noop,
};

const ActionsContext = createContext<Actions>(NO_ACTIONS);
const StateContext = createContext<(State & { refs: TutorRefs }) | null>(null);

const INITIAL: State = {
  open: false,
  view: "thread",
  prefill: null,
  selection: null,
  extra: {},
  focusMessage: null,
  sends: [],
};

export function TutorProvider({ children }: { children: ReactNode }) {
  const [layers, setLayers] = useState<Map<string, TutorRefs>>(() => new Map());
  const [state, setState] = useState<State>(INITIAL);
  const prefillN = useRef(0);

  const actions = useMemo<Actions>(
    () => ({
      publish: (id, refs) =>
        setLayers((prev) => {
          const next = new Map(prev);
          if (refs === null) next.delete(id);
          else next.set(id, refs);
          return next;
        }),
      open: (opts = {}) =>
        setState((s) => ({
          ...s,
          open: true,
          view: opts.view ?? (opts.messageId ? "all" : s.view),
          prefill: opts.text !== undefined ? { text: opts.text, n: ++prefillN.current } : s.prefill,
          selection: opts.selection ?? s.selection,
          extra: opts.refs ? { ...s.extra, ...opts.refs } : s.extra,
          focusMessage: opts.messageId ?? s.focusMessage,
        })),
      close: () => setState((s) => ({ ...s, open: false })),
      toggle: () => setState((s) => ({ ...s, open: !s.open })),
      setView: (view) => setState((s) => ({ ...s, view })),
      clearSelection: () => setState((s) => ({ ...s, selection: null })),
      clearExtra: () => setState((s) => ({ ...s, extra: {}, selection: null })),
      messageFocused: () => setState((s) => ({ ...s, focusMessage: null })),
      upsertSend: (send) =>
        setState((s) => ({ ...s, sends: [...s.sends.filter((x) => x.id !== send.id), send] })),
      dropSend: (id) => setState((s) => ({ ...s, sends: s.sends.filter((x) => x.id !== id) })),
    }),
    [],
  );

  const refs = useMemo(() => {
    const merged: TutorRefs = { screen: "other" };
    for (const l of layers.values()) Object.assign(merged, l);
    return merged;
  }, [layers]);

  const value = useMemo(() => ({ ...state, refs }), [state, refs]);

  return (
    <ActionsContext.Provider value={actions}>
      <StateContext.Provider value={value}>{children}</StateContext.Provider>
    </ActionsContext.Provider>
  );
}

/** Stable actions; a no-op outside the provider (components rendered on their own in tests). */
export function useTutorActions(): Actions {
  return useContext(ActionsContext);
}

export function useTutorState(): State & { refs: TutorRefs } {
  const s = useContext(StateContext);
  if (!s) throw new Error("useTutorState outside TutorProvider");
  return s;
}

/** Publishes what this screen shows to the tutor while it is mounted. */
export function useTutorRefs(refs: TutorRefs | null): void {
  const id = useId();
  const { publish } = useTutorActions();
  const json = JSON.stringify(refs);
  useEffect(() => {
    publish(id, json === "null" ? null : (JSON.parse(json) as TutorRefs));
  }, [publish, id, json]);
  useEffect(() => () => publish(id, null), [publish, id]);
}

/** The context body for the server: merged refs, the selection and what the learner removed. */
export function contextBody(
  refs: TutorRefs,
  extra: TutorRefs,
  selection: Selection | null,
  excluded: TutorContextIn["excluded"],
  locale: string,
): TutorContextIn {
  const r = { ...refs, ...extra };
  const body: TutorContextIn = { screen: r.screen ?? "other", locale };
  for (const k of ["path_id", "skill_id", "lesson_id", "attempt_id", "item_version_id"] as const) {
    const v = r[k];
    if (v) body[k] = v;
  }
  if (r.note_ids?.length) body.note_ids = r.note_ids;
  if (typeof r.video_s === "number") body.video_s = r.video_s;
  if (selection) body.selection = { text: selection.text, bid: selection.bid };
  if (excluded?.length) body.excluded = excluded;
  return body;
}

/** A callback that keeps its identity but always runs the latest closure. */
export function useEvent<A extends unknown[], R>(fn: (...args: A) => R): (...args: A) => R {
  const ref = useRef(fn);
  ref.current = fn;
  return useCallback((...args: A) => ref.current(...args), []);
}
