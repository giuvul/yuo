// One EventSource for the app: tutor replies, their progress and streamed text, nudges and
// job changes. The stream only notifies; the API stays the record. On `reset` (the server could not
// replay what this tab missed) the tutor state is loaded again. The browser reconnects by itself and
// sends Last-Event-ID; polling in the hooks remains the fallback while the stream is down.
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import type { NudgeOut, TutorMessage } from "../api/client";
import { keys as appKeys } from "../api/hooks";
import { addNudges, applyMessage, tutorKeys } from "./api";
import { liveReplies, type LiveReplies, type Stage } from "./live";

const STREAM_URL = "/api/stream";

const STAGES = new Set<Stage>(["thinking", "writing", "checking"]);

function parse(e: Event): Record<string, unknown> | null {
  try {
    const data = JSON.parse((e as MessageEvent<string>).data) as unknown;
    return data && typeof data === "object" ? (data as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/** Subscribes `source` to the app's handlers; returns an unsubscribe function. */
function wireStream(source: EventTarget, qc: QueryClient, live: LiveReplies = liveReplies): () => void {
  const handlers: Record<string, (data: Record<string, unknown>) => void> = {
    "tutor.message": (d) => {
      if (typeof d["id"] !== "string" || typeof d["conversation_id"] !== "string") return;
      const m = d as unknown as TutorMessage;
      if (m.role === "tutor" && m.status !== "streaming" && m.status !== "queued") live.done(m.id);
      applyMessage(qc, m);
    },
    "tutor.delta": (d) => {
      if (typeof d["message_id"] === "string" && typeof d["text"] === "string") live.delta(d["message_id"], d["text"]);
    },
    "tutor.progress": (d) => {
      const stage = d["stage"] as Stage;
      if (typeof d["message_id"] === "string" && STAGES.has(stage)) live.progress(d["message_id"], stage);
    },
    nudge: (d) => {
      if (typeof d["id"] === "string" && typeof d["trigger"] === "string") addNudges(qc, [d as unknown as NudgeOut]);
    },
    job: () => {
      void qc.invalidateQueries({ queryKey: appKeys.jobs });
      void qc.invalidateQueries({ queryKey: ["paths"] });
      void qc.invalidateQueries({ queryKey: ["lessons"] }); // a lesson or its video (rendition) finished
    },
    reset: () => {
      live.clear();
      void qc.invalidateQueries({ queryKey: tutorKeys.all });
      void qc.invalidateQueries({ queryKey: tutorKeys.nudges });
      void qc.invalidateQueries({ queryKey: appKeys.jobs });
      void qc.invalidateQueries({ queryKey: ["paths"] });
    },
  };
  const listeners = Object.entries(handlers).map(([kind, handle]) => {
    const l = (e: Event) => {
      const data = parse(e);
      if (data) handle(data);
    };
    source.addEventListener(kind, l);
    return [kind, l] as const;
  });
  return () => {
    for (const [kind, l] of listeners) source.removeEventListener(kind, l);
  };
}

/** Opens the app's event stream while mounted (once, in the root layout). */
export function useEventStream(): void {
  const qc = useQueryClient();
  useEffect(() => {
    const ES = (globalThis as { EventSource?: typeof EventSource }).EventSource;
    if (typeof ES !== "function") return; // no stream (old browser, tests): polling still works
    const source = new ES(STREAM_URL);
    const unwire = wireStream(source, qc);
    return () => {
      unwire();
      source.close();
    };
  }, [qc]);
}
