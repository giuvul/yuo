// The tutor's open panel: the policy line, the context chips, the thread and the composer, the memory notice and
// erasing a conversation. tutor/Dock.tsx keeps the button, the peek and the status region.
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button as AriaButton, Tab, TabList, TabPanel, Tabs } from "react-aria-components";
import { ApiError, type ChipKind, type TutorContextIn, type TutorContextOut, type TutorMessage } from "../api/client";
import { ConfirmAction } from "../components/ConfirmAction";
import { ErrorNotice } from "../components/ErrorNotice";
import { CloseIcon, LockIcon, SparkleIcon } from "../components/icons";
import { Badge, Button, Notice, ui } from "../components/ui";
import { readJson, readText, writeJson, writeText } from "../storage";
import { uuid7 } from "../outbox/uuid7";
import {
  applyMessage,
  sendMessage,
  tutorKeys,
  useConversations,
  useEraseConversation,
  useThread,
  useTutorContext,
} from "./api";
import { contextBody, useEvent, useTutorActions, useTutorState, type DockView, type LocalSend } from "./context";
import { DockNudges, useVisibleNudges } from "./Nudges";
import { CHIP_KINDS, NO_SPOILERS_POLICY, POLICIES, REVIEW_POLICIES, SCOPES } from "./texts";
import { Composer, Thread, useChipLabel } from "./Thread";
import styles from "./tutor.module.css";

export const DOCK_ID = "tutor-dock";
const MEMORY_NOTICE_KEY = "yuo.tutor.memory-notice-seen";
type Excludable = NonNullable<TutorContextIn["excluded"]>[number];

/** Sends a message with a client uuid7; a retry reuses the id, so the server answers it once. */
export function useSender() {
  const qc = useQueryClient();
  const tutor = useTutorActions();
  return useEvent(async (s: LocalSend): Promise<TutorMessage | null> => {
    tutor.upsertSend({ ...s, state: "sending" });
    try {
      const m = await sendMessage(s.id, s.text, s.context);
      tutor.dropSend(s.id);
      if (qc.getQueryData(tutorKeys.messages(m.conversation_id)) === undefined) {
        qc.setQueryData(tutorKeys.messages(m.conversation_id), [m]); // a new thread: this is all of it
      }
      applyMessage(qc, m);
      return m;
    } catch (err) {
      if (err instanceof ApiError && err.status < 500) tutor.upsertSend({ ...s, state: "failed", error: err.message });
      else tutor.upsertSend({ ...s, state: "unsent" });
      return null;
    }
  });
}

/** Keeps the sheet above an on-screen keyboard where the browser overlays it (iOS Safari). */
function useKeyboardInset(ref: React.RefObject<HTMLElement | null>, active: boolean) {
  useEffect(() => {
    const vv = window.visualViewport;
    const el = ref.current;
    if (!active || !vv || !el) return;
    const update = () => {
      const inset = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      el.style.setProperty("--tutor-keyboard", `${Math.round(inset)}px`);
    };
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, [ref, active]);
}

/** Policy lines the learner closed, kept on this device: once read, "Ask anything about your path" need not stay
 *. Test and review rules cannot be closed: they change what the tutor will do. */
const DISMISSED_KEY = "yuo.tutor.dismissed-policies";
const INFO_MODES = new Set(["free", "lesson", "setup"]);

const isStrings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

function readDismissed(): string[] {
  return readJson<string[]>(DISMISSED_KEY, [], isStrings);
}

function useDismissedPolicies(): [string[], (policy: string) => void] {
  const [dismissed, setDismissed] = useState(readDismissed);
  const dismiss = (policy: string) => {
    const next = [...new Set([...dismissed, policy])];
    setDismissed(next);
    writeJson(DISMISSED_KEY, next); // storage closed: closed for this visit only
  };
  return [dismissed, dismiss];
}

function PolicyLine({ ctx }: { ctx: TutorContextOut }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const locked = ctx.mode === "test_locked";
  const policy: string = ctx.policy;
  const text = REVIEW_POLICIES[policy] ?? POLICIES[ctx.policy];
  const [dismissed, dismiss] = useDismissedPolicies();
  const closable = INFO_MODES.has(ctx.mode) && !ctx.sealed_by_open_test && !(policy in REVIEW_POLICIES);
  const hidden = closable && dismissed.includes(policy);
  return (
    <div className={styles.policy} data-mode={ctx.mode}>
      {policy === NO_SPOILERS_POLICY ? (
        <p className={styles.noSpoilers}>
          <Badge tone="highlight">
            <LockIcon size="0.85em" />
            <Trans id="tutor.policy.no-spoilers">No spoilers</Trans>
          </Badge>
        </p>
      ) : null}
      {ctx.sealed_by_open_test ? (
        <Notice tone="warning" role="status">
          <Trans id="tutor.policy.open-test">
            A test is open, so the test rules apply on every screen. Finish the test to get full help again.
          </Trans>
        </Notice>
      ) : null}
      {locked || (text && !hidden) ? (
        <div className={styles.policyText}>
          {locked ? (
            <svg className={styles.lock} viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
              <path
                fill="currentColor"
                d="M8 1a3.5 3.5 0 0 0-3.5 3.5V7H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1h-.5V4.5A3.5 3.5 0 0 0 8 1Zm-2 6V4.5a2 2 0 1 1 4 0V7H6Z"
              />
            </svg>
          ) : null}
          {text && !hidden ? <p>{i18n._(text)}</p> : null}
          {text && closable && !hidden ? (
            <AriaButton
              className={styles.policyClose}
              onPress={() => dismiss(policy)}
              aria-label={t({ id: "tutor.policy.dismiss", message: "Hide this note" })}
            >
              <CloseIcon size="0.9em" />
            </AriaButton>
          ) : null}
        </div>
      ) : null}
      {ctx.checked ? (
        <p className={styles.meta}>
          <Trans id="tutor.policy.checked">Replies are checked before you see them, so they appear all at once.</Trans>
        </p>
      ) : null}
    </div>
  );
}

function ContextChips({
  ctx,
  excluded,
  onExclude,
  onInclude,
  onDropSelection,
}: {
  ctx: TutorContextOut;
  excluded: Excludable[];
  onExclude: (k: Excludable) => void;
  onInclude: (k: Excludable) => void;
  onDropSelection: () => void;
}) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const chipLabel = useChipLabel();
  const count = ctx.chips.length;
  return (
    // closed by default: the chips are there to check, not to read every time
    <details className={styles.chipsBox}>
      <summary className={styles.chipsSummary} id="tutor-chips-label">
        <span className={styles.chipsChevron} aria-hidden="true">
          ›
        </span>
        <Trans id="tutor.chips.summary">What the tutor sees with your next message ({count})</Trans>
      </summary>
      {ctx.chips.length ? (
        <ul className={styles.chips} aria-labelledby="tutor-chips-label">
          {ctx.chips.map((c) => {
            const label = chipLabel(c);
            const kind = i18n._(CHIP_KINDS[c.kind]);
            return (
              <li key={`${c.kind}:${c.label}`} className={styles.chip} data-kind={c.kind}>
                <span className={styles.chipText}>{label}</span>
                {c.kind !== "item" ? (
                  <AriaButton
                    className={styles.chipRemove}
                    aria-label={t({ id: "tutor.chip.remove", message: `Remove from the context: ${kind}` })}
                    onPress={() => (c.kind === "selection" ? onDropSelection() : onExclude(c.kind as Excludable))}
                  >
                    <span aria-hidden="true">×</span>
                  </AriaButton>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className={ui.muted}>
          <Trans id="tutor.chips.none">Nothing from this screen.</Trans>
        </p>
      )}
      {excluded.length ? (
        <div className={ui.row}>
          <span className={styles.meta}>
            <Trans id="tutor.chips.removed">Removed:</Trans>
          </span>
          {excluded.map((k: ChipKind) => {
            const kind = i18n._(CHIP_KINDS[k]);
            return (
              <Button key={k} small variant="secondary" onPress={() => onInclude(k as Excludable)}>
                <Trans id="tutor.chip.add-back">Add back: {kind}</Trans>
              </Button>
            );
          })}
        </div>
      ) : null}
    </details>
  );
}

function MemoryNotice({ onClose }: { onClose: () => void }) {
  return (
    <Notice>
      <div className={styles.noticeBody}>
      <p>
        <Trans id="tutor.memory.first-use">
          The tutor remembers lasting things about you, like goals, preferences and mistakes it noticed, to help across
          conversations. You can see, change and delete every entry.
        </Trans>
      </p>
      <div className={ui.row}>
        <Link to="/tutor/memory">
          <Trans id="tutor.memory.first-use.link">Open tutor memory</Trans>
        </Link>
        <Link to="/settings" hash="setting-tutor-memory">
          <Trans id="tutor.memory.first-use.setting">Turn memory off</Trans>
        </Link>
        <Button small variant="secondary" onPress={onClose}>
          <Trans id="tutor.memory.first-use.ok">Got it</Trans>
        </Button>
      </div>
      </div>
    </Notice>
  );
}

export function DockPanel({ onClose, tutorName }: { onClose: () => void; tutorName: string }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const state = useTutorState();
  const tutor = useTutorActions();
  const send = useSender();
  const panelRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  useKeyboardInset(panelRef, true);

  // what the learner removed applies to this screen only
  const refsKey = JSON.stringify({ ...state.refs, ...state.extra });
  const [excludedFor, setExcludedFor] = useState<{ key: string; kinds: Excludable[] }>({ key: "", kinds: [] });
  const excluded = excludedFor.key === refsKey ? excludedFor.kinds : [];
  const setExcluded = (kinds: Excludable[]) => setExcludedFor({ key: refsKey, kinds });

  const body = useMemo(
    () => contextBody(state.refs, state.extra, state.selection, excluded, i18n.locale),
    [refsKey, state.selection, excluded.join(","), i18n.locale],
  );
  const ctx = useTutorContext(body, true);

  // a thread created by the first message here, until the context names it
  const [sentFor, setSentFor] = useState<{ key: string; cid: string } | null>(null);
  const threadId = ctx.data?.conversation_id ?? (sentFor?.key === refsKey ? sentFor.cid : null);
  const view: DockView = state.view;
  const thread = useThread(threadId, view === "thread");
  const all = useThread("all", view === "all");
  const conversations = useConversations(view === "all");
  const shown = (view === "all" ? all.data : thread.data) ?? [];
  const conversationMap = useMemo(
    () => new Map((conversations.data ?? []).map((c) => [c.id, c])),
    [conversations.data],
  );
  const nudges = useVisibleNudges();

  const [memoryNoticeSeen, setMemoryNoticeSeen] = useState(() => readText(MEMORY_NOTICE_KEY) === "1");
  const memoryOn = ctx.data?.chips.some((c) => c.kind === "memory") ?? false;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // keep the newest message in view when the learner is already at the bottom
  const stick = useRef(true);
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stick.current && !state.focusMessage) el.scrollTop = el.scrollHeight;
  }, [shown.length, state.sends.length, state.focusMessage, view]);

  const onSend = (text: string) => {
    const id = uuid7();
    stick.current = true;
    void send({ id, text, context: body, state: "sending" }).then((m) => {
      if (m) {
        setSentFor({ key: refsKey, cid: m.conversation_id });
        void ctx.refetch();
      }
    });
    tutor.clearExtra();
    if (view !== "thread") tutor.setView("thread");
  };

  const scopeLabel = ctx.data ? i18n._(SCOPES[ctx.data.scope]) : "";

  return (
    <aside
      id={DOCK_ID}
      ref={panelRef}
      className={styles.panel}
      aria-labelledby="tutor-dock-title"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !e.defaultPrevented) {
          e.preventDefault();
          onClose();
        }
      }}
    >
      <header className={styles.panelHeader}>
        <h2 id="tutor-dock-title" className={styles.panelTitle}>
          <span className={styles.panelMark} aria-hidden="true">
            <SparkleIcon />
          </span>
          {tutorName}
        </h2>
        <div className={styles.panelActions}>
          <Link to="/tutor/memory" className={styles.headerLink}>
            <Trans id="tutor.memory.link">Tutor memory</Trans>
          </Link>
          <AriaButton
            className={styles.closeButton}
            onPress={onClose}
            aria-label={t({ id: "tutor.dock.close.label", message: "Close the tutor" })}
          >
            <CloseIcon />
          </AriaButton>
        </div>
      </header>

      <div
        className={styles.panelBody}
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {ctx.data ? (
          <div className={styles.contextBox} data-stale={ctx.isPlaceholderData || undefined}>
            <PolicyLine ctx={ctx.data} />
            <ContextChips
              ctx={ctx.data}
              excluded={excluded}
              onExclude={(k) => setExcluded([...excluded.filter((x) => x !== k), k])}
              onInclude={(k) => setExcluded(excluded.filter((x) => x !== k))}
              onDropSelection={tutor.clearSelection}
            />
            {memoryOn && !memoryNoticeSeen ? (
              <MemoryNotice
                onClose={() => {
                  writeText(MEMORY_NOTICE_KEY, "1");
                  setMemoryNoticeSeen(true);
                }}
              />
            ) : null}
          </div>
        ) : ctx.isError ? (
          <Notice tone="warning">
            <Trans id="tutor.context.error">The tutor's context could not be loaded. You can still send a message.</Trans>
          </Notice>
        ) : (
          <p className={ui.muted}>
            <Trans id="common.loading">Loading…</Trans>
          </p>
        )}

        <DockNudges nudges={nudges} />

        <Tabs selectedKey={view} onSelectionChange={(k) => tutor.setView(k as DockView)} className={styles.tabs}>
          <TabList aria-label={t({ id: "tutor.threads.label", message: "Conversations" })} className={styles.tabList}>
            <Tab id="thread" className={styles.tab}>
              {scopeLabel ? (
                <Trans id="tutor.threads.this">This thread ({scopeLabel})</Trans>
              ) : (
                <Trans id="tutor.threads.this.plain">This thread</Trans>
              )}
            </Tab>
            <Tab id="all" className={styles.tab}>
              <Trans id="tutor.threads.all">All</Trans>
            </Tab>
          </TabList>
          <TabPanel id="thread" className={styles.tabPanel}>
            {threadId && thread.isPending ? (
              <p className={ui.muted}>
                <Trans id="common.loading">Loading…</Trans>
              </p>
            ) : (
              <Thread
                messages={thread.data ?? []}
                sends={state.sends}
                tutorName={tutorName}
                focusMessage={state.focusMessage}
                onMessageFocused={tutor.messageFocused}
                onResend={(s) => void send(s)}
                onDiscard={tutor.dropSend}
                label={t({ id: "tutor.thread.label", message: "This conversation" })}
                emptyText={t({
                  id: "tutor.thread.empty",
                  message: "No messages here yet. Ask about what is on your screen.",
                })}
              />
            )}
            {threadId && thread.data?.length ? <EraseThread id={threadId} onErased={() => setSentFor(null)} /> : null}
          </TabPanel>
          <TabPanel id="all" className={styles.tabPanel}>
            {all.isPending ? (
              <p className={ui.muted}>
                <Trans id="common.loading">Loading…</Trans>
              </p>
            ) : (
              <Thread
                messages={all.data ?? []}
                sends={state.sends}
                tutorName={tutorName}
                conversations={conversationMap}
                focusMessage={state.focusMessage}
                onMessageFocused={tutor.messageFocused}
                onResend={(s) => void send(s)}
                onDiscard={tutor.dropSend}
                label={t({ id: "tutor.thread.all.label", message: "All conversations" })}
                emptyText={t({ id: "tutor.thread.all.empty", message: "You have not talked with the tutor yet." })}
              />
            )}
          </TabPanel>
        </Tabs>
      </div>

      <Composer inputRef={inputRef} prefill={state.prefill} onSend={onSend} tutorName={tutorName} />
    </aside>
  );
}

/** The dock, its button, the suggestion peek and the status region. Mounted once in the root layout. */

/** Erase this conversation for good: its messages and what the models wrote for it. */
function EraseThread({ id, onErased }: { id: string; onErased: () => void }) {
  const erase = useEraseConversation();
  return (
    <div className={styles.eraseThread}>
      <ConfirmAction
        label={<Trans id="tutor.thread.erase">Delete this conversation</Trans>}
        question={
          <Trans id="tutor.thread.erase.question">
            Delete every message in this conversation for good? Your notes and tutor memory stay.
          </Trans>
        }
        confirmLabel={<Trans id="tutor.thread.erase.confirm">Delete the conversation</Trans>}
        pending={erase.isPending}
        onConfirm={() => erase.mutate(id, { onSuccess: onErased })}
      />
      {erase.isError ? <ErrorNotice error={erase.error} /> : null}
    </div>
  );
}
