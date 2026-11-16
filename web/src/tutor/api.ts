// Tutor API: queries, mutations and the cache updates shared by the HTTP replies and the event
// stream. Messages live in one cache entry per thread (`conversation id`) plus one for the "All"
// timeline; a message from either source is merged into every list it belongs to.
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import {
  api,
  unwrap,
  type MemoryKind,
  type NudgeOut,
  type ProposalOut,
  type TutorContextIn,
  type TutorMessage,
} from "../api/client";
import { keys as appKeys } from "../api/hooks";

export const tutorKeys = {
  all: ["tutor"] as const,
  context: (body: TutorContextIn) => ["tutor", "context", body] as const,
  messages: (conversationId: string | "all") => ["tutor", "messages", conversationId] as const,
  conversations: ["tutor", "conversations"] as const,
  memory: ["tutor", "memory"] as const,
  nudges: ["nudges"] as const,
  proposals: (pathId: string) => ["paths", pathId, "proposals"] as const,
  proposal: (id: string) => ["proposals", id] as const,
};

/** Poll a thread this often while a reply is pending (the event stream is the fast path). */
const THREAD_POLL_MS = 2_000;

export const PENDING_STATUSES = new Set<TutorMessage["status"]>(["queued", "streaming"]);

function hasPending(messages: TutorMessage[] | undefined): boolean {
  return !!messages?.some((m) => PENDING_STATUSES.has(m.status));
}

function order(a: TutorMessage, b: TutorMessage): number {
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? -1 : 1;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/**
 * Merge one message into a list: replace by id, drop it when withdrawn, keep time order. A reply
 * also settles the learner messages it answers: the server marks them done when it starts the
 * turn but announces only the reply, so they would otherwise stay "queued" here.
 */
export function mergeMessage(list: TutorMessage[], m: TutorMessage): TutorMessage[] {
  const answered = m.role === "tutor" ? new Set(m.answers) : null;
  const rest = list
    .filter((x) => x.id !== m.id)
    .map((x) => (answered?.has(x.id) && x.status === "queued" ? { ...x, status: "done" as const } : x));
  // a taken-back question and a retried failed reply leave the thread; a cancelled reply stays
  if (m.status === "withdrawn" && (m.role !== "tutor" || m.retried)) return rest;
  return [...rest, m].sort(order);
}

type MessageListener = (m: TutorMessage) => void;
const messageListeners = new Set<MessageListener>();

/** Hears every message applied to the cache (the announcer and the unread badge use it). */
export function onTutorMessage(l: MessageListener): () => void {
  messageListeners.add(l);
  return () => messageListeners.delete(l);
}

/** Applies a message (from a reply or the stream) to the cached thread and the "All" timeline. */
export function applyMessage(qc: QueryClient, m: TutorMessage): void {
  for (const l of messageListeners) l(m);
  let known = false;
  for (const key of [tutorKeys.messages(m.conversation_id), tutorKeys.messages("all")]) {
    const list = qc.getQueryData<TutorMessage[]>(key);
    if (list === undefined) continue;
    if (key[2] !== "all") known = true;
    qc.setQueryData<TutorMessage[]>(key, mergeMessage(list, m));
  }
  if (!known) {
    // a thread the dock has not loaded (maybe a new one): the context names it once it exists
    void qc.invalidateQueries({ queryKey: ["tutor", "context"] });
    void qc.invalidateQueries({ queryKey: tutorKeys.conversations });
  }
}

export function useTutorContext(body: TutorContextIn, enabled: boolean) {
  return useQuery({
    queryKey: tutorKeys.context(body),
    queryFn: () => unwrap(api.POST("/api/tutor/context", { body })),
    enabled,
    staleTime: 0,
    retry: false,
    placeholderData: keepPreviousData,
  });
}

export function useThread(conversationId: string | null, enabled = true) {
  const key = conversationId ?? "none";
  return useQuery({
    queryKey: tutorKeys.messages(key),
    queryFn: () =>
      conversationId === null
        ? Promise.resolve([] as TutorMessage[])
        : key === "all"
          ? unwrap(api.GET("/api/tutor/messages", { params: { query: {} } }))
          : unwrap(api.GET("/api/tutor/messages", { params: { query: { conversation_id: conversationId } } })),
    enabled,
    staleTime: 5_000,
    refetchInterval: (q) => (hasPending(q.state.data) ? THREAD_POLL_MS : false),
  });
}

export function useConversations(enabled = true) {
  return useQuery({
    queryKey: tutorKeys.conversations,
    queryFn: () => unwrap(api.GET("/api/tutor/conversations", { params: { query: {} } })),
    enabled,
  });
}

export function sendMessage(id: string, text: string, context: TutorContextIn): Promise<TutorMessage> {
  return unwrap(api.POST("/api/tutor/messages", { body: { id, text, context } }));
}

export function useMessageActions() {
  const qc = useQueryClient();
  const edit = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      unwrap(api.PATCH("/api/tutor/messages/{message_id}", { params: { path: { message_id: id } }, body: { text } })),
    onSuccess: (m) => applyMessage(qc, m),
  });
  const withdraw = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/tutor/messages/{message_id}", { params: { path: { message_id: id } } })),
    onSuccess: (m) => applyMessage(qc, m),
  });
  const retry = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.POST("/api/tutor/messages/{message_id}/retry", { params: { path: { message_id: id } } })),
    onSuccess: (r) => {
      // the stream announces these too; applying them here makes the reply immediate
      applyMessage(qc, r.retried);
      for (const m of r.requeued) applyMessage(qc, m);
    },
  });
  return { edit, withdraw, retry };
}

/** Erase one conversation with its messages; every tutor view reads again. */
export function useEraseConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/tutor/conversations/{conversation_id}", { params: { path: { conversation_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tutor"] }),
  });
}

// --- memory ------------------------------------------------------------------------------

export function useMemory() {
  return useQuery({
    queryKey: tutorKeys.memory,
    queryFn: () => unwrap(api.GET("/api/tutor/memory")),
  });
}

async function noContent(call: Promise<{ error?: unknown; response: Response }>): Promise<void> {
  await unwrap(call as Promise<{ data?: undefined; error?: unknown; response: Response }>);
}

export function useMemoryMutations() {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: tutorKeys.memory });
  const add = useMutation({
    mutationFn: (body: { kind: MemoryKind; text: string }) => unwrap(api.POST("/api/tutor/memory", { body })),
    onSuccess: refresh,
  });
  const edit = useMutation({
    mutationFn: ({ id, text }: { id: string; text: string }) =>
      noContent(api.PATCH("/api/tutor/memory/{memory_id}", { params: { path: { memory_id: id } }, body: { text } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      noContent(api.DELETE("/api/tutor/memory/{memory_id}", { params: { path: { memory_id: id } } })),
    onSuccess: refresh,
  });
  return { add, edit, remove };
}

// --- proposals ---------------------------------------------------------------------------

export function useProposals(pathId: string) {
  return useQuery({
    queryKey: tutorKeys.proposals(pathId),
    queryFn: () => unwrap(api.GET("/api/paths/{path_id}/proposals", { params: { path: { path_id: pathId } } })),
    retry: false,
  });
}

/** One proposal, for its card in the thread. */
export function useProposal(proposalId: string | null) {
  return useQuery({
    queryKey: tutorKeys.proposal(proposalId ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/proposals/{proposal_id}", { params: { path: { proposal_id: proposalId ?? "" } } })),
    enabled: proposalId !== null,
    retry: false,
  });
}

export function refreshAfterDecision(qc: QueryClient, p: ProposalOut): void {
  void qc.invalidateQueries({ queryKey: tutorKeys.proposals(p.path_id) });
  void qc.invalidateQueries({ queryKey: tutorKeys.proposal(p.id) });
  void qc.invalidateQueries({ queryKey: appKeys.requests(p.path_id) });
  void qc.invalidateQueries({ queryKey: appKeys.path(p.path_id) });
  void qc.invalidateQueries({ queryKey: appKeys.jobs });
}

// --- nudges ------------------------------------------------------------------------------

export function useNudges() {
  return useQuery({
    queryKey: tutorKeys.nudges,
    queryFn: () => unwrap(api.GET("/api/nudges")),
    retry: false,
    staleTime: 60_000,
  });
}

/** Adds nudges from a flush reply or the stream; the same nudge can arrive from both. */
export function addNudges(qc: QueryClient, incoming: NudgeOut[]): void {
  if (!incoming.length) return;
  qc.setQueryData<NudgeOut[]>(tutorKeys.nudges, (list = []) => {
    const seen = new Set(list.map((n) => n.id));
    return [...incoming.filter((n) => !seen.has(n.id)), ...list];
  });
}

export function useDecideNudge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: string; action: "accept" | "dismiss" | "mute" }) =>
      noContent(
        api.POST("/api/nudges/{nudge_id}/{action}", { params: { path: { nudge_id: id, action } } }),
      ),
    onMutate: ({ id }) => {
      qc.setQueryData<NudgeOut[]>(tutorKeys.nudges, (list) => list?.filter((n) => n.id !== id));
    },
    onSettled: (_d, _e, { action }) => {
      if (action === "mute") void qc.invalidateQueries({ queryKey: appKeys.settings });
    },
  });
}

/** The tutor's name from the settings (tutor.name), or null for the default. */
export function useTutorName(enabled: boolean): string | null {
  const settings = useQuery({
    queryKey: appKeys.settings,
    queryFn: () => unwrap(api.GET("/api/settings", { params: { query: {} } })),
    enabled,
    retry: false,
  });
  const v = settings.data?.find((s) => s.key === "tutor.name")?.value;
  return typeof v === "string" && v.trim() ? v.trim() : null;
}
