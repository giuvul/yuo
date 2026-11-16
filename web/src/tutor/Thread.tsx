// The conversation in the dock: learner messages (queued ones can be edited or taken back), tutor
// replies (pending with stage and elapsed time, streamed text when the mode allows it, failed with
// the reason and Retry), template replies from the catalog, proposals and memory notes.
import { plural } from "@lingui/core/macro";
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState, type RefObject } from "react";
import { Label, TextArea, TextField, Text } from "react-aria-components";
import type { Chip, ConversationOut, TutorMessage } from "../api/client";
import { Button, ui } from "../components/ui";
import { useMessageActions, useProposal } from "./api";
import { useTutorActions, type LocalSend } from "./context";
import { liveReplies, useLiveReply } from "./live";
import { ProposalCard } from "./Proposals";
import { CHIP_KINDS, REVIEW_TEMPLATES, SCOPES, STAGES, TEMPLATES, errorText } from "./texts";
import { SendIcon } from "../components/icons";
import styles from "./tutor.module.css";

const MESSAGE_MAX = 4000;

/** Turns a context chip into words ("Lesson: Joins"); the item chip's position is localised. */
export function useChipLabel(): (c: Chip) => string {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  return (c: Chip) => {
    const kind = i18n._(CHIP_KINDS[c.kind]);
    switch (c.kind) {
      case "item": {
        const n = c.n;
        const total = c.of;
        if (typeof n !== "number" || typeof total !== "number")
          return t({ id: "tutor.chip.item.plain", message: "This question" });
        return t({ id: "tutor.chip.item", message: `Question ${n} of ${total}` });
      }
      case "notes": {
        const count = c.n ?? 0;
        return t({ id: "tutor.chip.notes", message: plural(count, { one: "# note", other: "# notes" }) });
      }
      case "memory":
        return kind;
      case "selection": {
        const text = c.label;
        return t({ id: "tutor.chip.selection", message: `Selected: “${text}”` });
      }
      default: {
        const label = c.label;
        return t({ id: "tutor.chip.default", message: `${kind}: ${label}` });
      }
    }
  };
}

/** "seconds since" that ticks once a second; not a live region (the status region announces). */
function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.round((now - since) / 1000));
  return (
    <span className={styles.elapsed}>
      <Trans id="tutor.pending.elapsed">{seconds} s</Trans>
    </span>
  );
}

function PendingReply({ m, tutorName }: { m: TutorMessage; tutorName: string }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const live = useLiveReply(m.id);
  const since = live?.since ?? liveReplies.seen(m.id).since;
  const { withdraw } = useMessageActions();
  const stage = live?.stage ?? "thinking";
  return (
    <div className={styles.pending} aria-busy="true">
      <p className={styles.stage}>
        <span className={styles.dots} aria-hidden="true" />
        <span>{i18n._(STAGES[stage])}</span>
        <Elapsed since={since} />
      </p>
      {live?.text ? <p className={styles.text}>{live.text}</p> : null}
      <div className={ui.row}>
        <Button
          small
          variant="secondary"
          isDisabled={withdraw.isPending}
          onPress={() => withdraw.mutate(m.id, { onSuccess: () => liveReplies.done(m.id) })}
          aria-label={t({ id: "tutor.pending.cancel.label", message: `Stop ${tutorName}'s reply` })}
        >
          <Trans id="tutor.pending.cancel">Stop</Trans>
        </Button>
      </div>
    </div>
  );
}

function MessageProposal({ id }: { id: string }) {
  const proposal = useProposal(id);
  return proposal.data ? <ProposalCard proposal={proposal.data} compact /> : null;
}

function TutorBody({ m, tutorName, questions }: { m: TutorMessage; tutorName: string; questions: string[] }) {
  const { i18n } = useLinguiRuntime();
  const { retry } = useMessageActions();
  const tutor = useTutorActions();
  if (m.status === "streaming" || m.status === "queued") return <PendingReply m={m} tutorName={tutorName} />;
  if (m.status === "withdrawn") {
    return (
      <div className={ui.stack}>
        <p className={styles.meta}>
          <Trans id="tutor.cancelled">You stopped this reply.</Trans>
        </p>
        {questions.length ? (
          <div className={ui.row}>
            <Button small variant="secondary" onPress={() => tutor.open({ text: questions.join("\n\n") })}>
              <Trans id="tutor.cancelled.again">Ask again</Trans>
            </Button>
          </div>
        ) : null}
      </div>
    );
  }
  if (m.status === "failed") {
    return (
      <div className={styles.failed}>
        <p>
          <strong>
            <Trans id="tutor.failed.title">No answer this time.</Trans>
          </strong>{" "}
          {i18n._(errorText(m.error))}
        </p>
        <div className={ui.row}>
          <Button small isDisabled={retry.isPending} onPress={() => retry.mutate(m.id)}>
            <Trans id="tutor.failed.retry">Retry</Trans>
          </Button>
        </div>
      </div>
    );
  }
  const template = m.template ? (TEMPLATES[m.template] ?? REVIEW_TEMPLATES[m.template]) : undefined;
  const remembered = m.memory_ids.length;
  return (
    <>
      <p className={styles.text}>{template ? i18n._(template) : m.text}</p>
      {m.guard === "checked" || m.guard === "blocked" ? (
        <p className={styles.meta}>
          <Trans id="tutor.guard.checked">Checked for answer leaks before it was shown.</Trans>
        </p>
      ) : null}
      {m.proposal_id ? <MessageProposal id={m.proposal_id} /> : null}
      {remembered > 0 ? (
        <p className={styles.meta}>
          <Plural
            id="tutor.memory.noted"
            value={remembered}
            one="Remembered # thing about you."
            other="Remembered # things about you."
          />{" "}
          <Link to="/tutor/memory">
            <Trans id="tutor.memory.link">Tutor memory</Trans>
          </Link>
        </p>
      ) : null}
    </>
  );
}

function QueuedEditor({ m, onDone }: { m: TutorMessage; onDone: () => void }) {
  const { t } = useLingui();
  const { edit } = useMessageActions();
  const [text, setText] = useState(m.text);
  return (
    <form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) edit.mutate({ id: m.id, text: text.trim() }, { onSuccess: onDone });
      }}
    >
      <TextField value={text} onChange={setText} maxLength={MESSAGE_MAX} className={ui.field} autoFocus>
        <Label className={ui.label}>{t({ id: "tutor.queued.edit.label", message: "Edit your message" })}</Label>
        <TextArea className={`${ui.input} ${styles.editArea}`} />
      </TextField>
      <div className={ui.row}>
        <Button type="submit" small isDisabled={!text.trim() || edit.isPending}>
          <Trans id="tutor.queued.save">Save</Trans>
        </Button>
        <Button small variant="secondary" onPress={onDone}>
          <Trans id="tutor.queued.cancel">Cancel</Trans>
        </Button>
      </div>
      {edit.isError ? (
        <p className={styles.errorText} role="alert">
          <Trans id="tutor.queued.edit.failed">It was answered before the change arrived.</Trans>
        </p>
      ) : null}
    </form>
  );
}

function LearnerBody({ m }: { m: TutorMessage }) {
  const { t } = useLingui();
  const { withdraw } = useMessageActions();
  const chipLabel = useChipLabel();
  const [editing, setEditing] = useState(false);
  const context = m.chips.filter((c) => c.kind !== "memory").map(chipLabel).join(" · ");
  if (editing && m.status === "queued") return <QueuedEditor m={m} onDone={() => setEditing(false)} />;
  return (
    <>
      <p className={styles.text}>{m.text}</p>
      {context ? (
        <p className={styles.meta}>
          <Trans id="tutor.message.context">Asked with: {context}</Trans>
        </p>
      ) : null}
      {m.status === "queued" ? (
        <div className={ui.row}>
          <span className={styles.badge}>
            <Trans id="tutor.queued">Queued</Trans>
          </span>
          <Button small variant="secondary" onPress={() => setEditing(true)}>
            <Trans id="tutor.queued.edit">Edit</Trans>
          </Button>
          <Button
            small
            variant="secondary"
            isDisabled={withdraw.isPending}
            onPress={() => withdraw.mutate(m.id)}
            aria-label={t({ id: "tutor.queued.withdraw.label", message: "Take back this message" })}
          >
            <Trans id="tutor.queued.withdraw">Take back</Trans>
          </Button>
        </div>
      ) : null}
    </>
  );
}

function threadLine(c: ConversationOut | undefined, i18n: ReturnType<typeof useLinguiRuntime>["i18n"]): string {
  if (!c) return "";
  const scope = i18n._(SCOPES[c.scope]);
  return c.title ? `${scope}: ${c.title}` : scope;
}

type ThreadProps = {
  messages: TutorMessage[];
  sends: LocalSend[];
  tutorName: string;
  /** "All" view: a context line wherever the thread changes */
  conversations?: Map<string, ConversationOut>;
  focusMessage: string | null;
  onMessageFocused: () => void;
  onResend: (s: LocalSend) => void;
  onDiscard: (id: string) => void;
  emptyText: string;
  label: string;
};

export function Thread({
  messages,
  sends,
  tutorName,
  conversations,
  focusMessage,
  onMessageFocused,
  onResend,
  onDiscard,
  emptyText,
  label,
}: ThreadProps) {
  const { i18n } = useLinguiRuntime();
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (!focusMessage) return;
    const el = [...(listRef.current?.querySelectorAll<HTMLElement>("[data-message-id]") ?? [])].find(
      (x) => x.dataset["messageId"] === focusMessage,
    );
    if (!el) return;
    el.scrollIntoView?.({ block: "center" });
    el.focus();
    onMessageFocused();
  }, [focusMessage, messages, onMessageFocused]);

  const texts = new Map(messages.filter((x) => x.role === "learner").map((x) => [x.id, x.text]));
  const questionsFor = (m: TutorMessage) =>
    m.answers.map((id) => texts.get(id)).filter((x): x is string => !!x);

  if (!messages.length && !sends.length) return <p className={ui.muted}>{emptyText}</p>;
  let lastConversation: string | null = null;
  return (
    <ol className={styles.thread} aria-label={label} ref={listRef}>
      {messages.map((m) => {
        const line =
          conversations && m.conversation_id !== lastConversation
            ? threadLine(conversations.get(m.conversation_id), i18n)
            : "";
        lastConversation = m.conversation_id;
        const mine = m.role === "learner";
        return (
          <li key={m.id} className={styles.entry}>
            {line ? <p className={styles.threadLine}>{line}</p> : null}
            <div
              className={mine ? styles.mine : styles.theirs}
              data-message-id={m.id}
              data-status={m.status}
              tabIndex={-1}
            >
              <p className={styles.author}>
                {mine ? <Trans id="tutor.author.you">You</Trans> : tutorName}
              </p>
              {mine ? <LearnerBody m={m} /> : <TutorBody m={m} tutorName={tutorName} questions={questionsFor(m)} />}
            </div>
          </li>
        );
      })}
      {sends.map((s) => {
        const error = s.error ?? "";
        return (
        <li key={s.id} className={styles.entry}>
          <div className={styles.mine} data-status={s.state}>
            <p className={styles.author}>
              <Trans id="tutor.author.you">You</Trans>
            </p>
            <p className={styles.text}>{s.text}</p>
            {s.state === "sending" ? (
              <p className={styles.meta}>
                <Trans id="tutor.send.sending">Sending…</Trans>
              </p>
            ) : (
              <>
                <p className={styles.errorText}>
                  {s.state === "unsent" ? (
                    <Trans id="tutor.send.unsent">Not sent: the server cannot be reached. It is sent when you are back online.</Trans>
                  ) : (
                    <Trans id="tutor.send.failed">Not sent: {error}</Trans>
                  )}
                </p>
                <div className={ui.row}>
                  <Button small onPress={() => onResend(s)}>
                    <Trans id="tutor.send.again">Send again</Trans>
                  </Button>
                  <Button small variant="secondary" onPress={() => onDiscard(s.id)}>
                    <Trans id="tutor.send.discard">Discard</Trans>
                  </Button>
                </div>
              </>
            )}
          </div>
        </li>
        );
      })}
    </ol>
  );
}

export function Composer({
  inputRef,
  prefill,
  onSend,
  tutorName,
}: {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  prefill: { text: string; n: number } | null;
  onSend: (text: string) => void;
  tutorName: string;
}) {
  const { t } = useLingui();
  const [text, setText] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const prefillN = prefill?.n ?? 0;
  const prefillText = prefill?.text ?? "";
  useEffect(() => {
    if (!prefillN) return;
    setText(prefillText);
    inputRef.current?.focus();
  }, [prefillN, prefillText, inputRef]);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    onSend(value);
    setText("");
    inputRef.current?.focus(); // the Send button disables itself; keep the learner in the composer
  };

  return (
    <form
      ref={formRef}
      className={styles.composer}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <TextField value={text} onChange={setText} maxLength={MESSAGE_MAX} className={styles.composerField}>
        <Label className="visually-hidden">
          {t({ id: "tutor.composer.label", message: `Message to ${tutorName}` })}
        </Label>
        <TextArea
          ref={inputRef}
          className={`${ui.input} ${styles.composerInput}`}
          rows={2}
          placeholder={t({ id: "tutor.composer.placeholder", message: "Ask a question…" })}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <Text slot="description" className="visually-hidden">
          {t({ id: "tutor.composer.help", message: "Enter sends, Shift+Enter starts a new line." })}
        </Text>
      </TextField>
      <Button type="submit" isDisabled={!text.trim()}>
        <SendIcon />
        <Trans id="tutor.composer.send">Send</Trans>
      </Button>
    </form>
  );
}
