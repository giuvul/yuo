// Tutor proposals: the tutor never changes the path itself; it proposes, the learner decides.
// A decision is a `tutor.proposal_decided` learning event sent through the outbox, so it also works
// offline; the server applies an accepted one (a lesson request, a difficulty change) when it arrives.
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { ProposalOut } from "../api/client";
import { Button, ButtonLink, Notice, ui } from "../components/ui";
import { useOutbox } from "../outbox/context";
import { refreshAfterDecision, useProposals } from "./api";
import { DIFFICULTIES, PROPOSAL_KINDS, PROPOSAL_STATUS } from "./texts";
import styles from "./tutor.module.css";

type Decision = "accepted" | "rejected";
type Outcome = { decision: Decision; state: "done" | "offline" } | { error: string };

function ChangeDetail({ p }: { p: ProposalOut }) {
  const { i18n } = useLinguiRuntime();
  const c = p.change;
  const str = (k: string) => (typeof c[k] === "string" ? (c[k] as string) : null);
  switch (p.kind) {
    case "add_lesson": {
      const prompt = str("prompt");
      return prompt ? (
        <p>
          <Trans id="tutor.proposal.detail.add-lesson">Lesson about: {prompt}</Trans>
        </p>
      ) : null;
    }
    case "extra_review": {
      const skill = str("skill");
      return skill ? (
        <p>
          <Trans id="tutor.proposal.detail.extra-review">Review the skill: {skill}</Trans>
        </p>
      ) : null;
    }
    case "change_difficulty": {
      const d = str("difficulty");
      const level = d ? i18n._(DIFFICULTIES[d] ?? { id: d }) : null;
      return level ? (
        <p>
          <Trans id="tutor.proposal.detail.difficulty">New difficulty: {level}</Trans>
        </p>
      ) : null;
    }
    default:
      return null;
  }
}

export function ProposalCard({
  proposal,
  compact,
  onDecided,
}: {
  proposal: ProposalOut;
  compact?: boolean;
  onDecided?: (id: string) => void;
}) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const outbox = useOutbox();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const kind = i18n._(PROPOSAL_KINDS[proposal.kind]);
  const decided: Decision | null =
    outcome && "decision" in outcome
      ? outcome.decision
      : proposal.status === "accepted" || proposal.status === "rejected"
        ? proposal.status
        : null;
  const status = decided ?? proposal.status;
  const skillId = typeof proposal.change["skill_id"] === "string" ? (proposal.change["skill_id"] as string) : null;
  const skill = typeof proposal.change["skill"] === "string" ? (proposal.change["skill"] as string) : "";

  const error = outcome && "error" in outcome ? outcome.error : null;

  const decide = async (decision: Decision) => {
    setBusy(true);
    try {
      const event = await outbox.enqueue("tutor.proposal_decided", { proposal_id: proposal.id, decision });
      const result = await outbox.flush();
      const reason = result.rejected[event.id];
      if (reason !== undefined) setOutcome({ error: reason });
      else if (result.accepted.includes(event.id) || result.duplicates.includes(event.id))
        setOutcome({ decision, state: "done" });
      else setOutcome({ decision, state: "offline" });
      onDecided?.(proposal.id);
      refreshAfterDecision(qc, proposal);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article
      className={`${styles.proposal} ${compact ? styles.proposalCompact : ""}`}
      aria-label={t({ id: "tutor.proposal.label", message: `Suggestion: ${kind}` })}
      data-status={status}
    >
      <p className={styles.proposalKind}>
        <strong>{kind}</strong>
        <span className={ui.muted}> · {i18n._(PROPOSAL_STATUS[status])}</span>
      </p>
      <p>{proposal.rationale}</p>
      <ChangeDetail p={proposal} />
      {status === "pending" ? (
        <div className={ui.row}>
          <Button small isDisabled={busy} onPress={() => void decide("accepted")}>
            <Trans id="tutor.proposal.accept">Accept</Trans>
          </Button>
          <Button small variant="secondary" isDisabled={busy} onPress={() => void decide("rejected")}>
            <Trans id="tutor.proposal.reject">Decline</Trans>
          </Button>
        </div>
      ) : null}
      {error !== null ? (
        <Notice tone="error">
          <Trans id="tutor.proposal.error">This decision was not accepted: {error}</Trans>
        </Notice>
      ) : null}
      {outcome && "state" in outcome && outcome.state === "offline" ? (
        <Notice tone="warning" role="status">
          <Trans id="tutor.proposal.offline">You are offline. Your decision is saved and applied when you are back online.</Trans>
        </Notice>
      ) : null}
      {decided === "accepted" && proposal.kind === "add_lesson" ? (
        <p className={ui.muted} role={outcome ? "status" : undefined}>
          <Trans id="tutor.proposal.add-lesson.done">The lesson is requested. It appears under “Your requests” on the path.</Trans>
        </p>
      ) : null}
      {decided === "accepted" && proposal.kind === "extra_review" && skillId ? (
        <div className={ui.row}>
          <ButtonLink
            to="/paths/$pathId/review/session"
            params={{ pathId: proposal.path_id }}
            search={{ size: 5, skill: skillId }}
            small
          >
            {skill ? (
              <Trans id="tutor.proposal.review.start">Start the review of {skill}</Trans>
            ) : (
              <Trans id="tutor.proposal.review.start.plain">Start the review</Trans>
            )}
          </ButtonLink>
        </div>
      ) : null}
    </article>
  );
}

/** The tutor's suggestions for one path, on the path view. Hidden when there are none. */
export function PathProposals({ pathId }: { pathId: string }) {
  const proposals = useProposals(pathId);
  // decided here: stays in place with its confirmation instead of moving to the older ones
  const [recent, setRecent] = useState<Set<string>>(() => new Set());
  const rows = proposals.data ?? [];
  if (!rows.length) return null;
  const pending = rows.filter((p) => p.status === "pending" || recent.has(p.id));
  const decided = rows.filter((p) => p.status !== "pending" && !recent.has(p.id));
  const count = decided.length;
  return (
    <section className={`${ui.card} ${ui.stack}`} aria-labelledby="proposals-title">
      <h2 id="proposals-title" className={styles.sectionTitle}>
        <Trans id="tutor.proposals.title">Suggestions from the tutor</Trans>
      </h2>
      <p className={ui.muted}>
        <Trans id="tutor.proposals.intro">The tutor never changes your path by itself. Accept what helps, decline the rest.</Trans>
      </p>
      {pending.map((p) => (
        <ProposalCard key={p.id} proposal={p} onDecided={(id) => setRecent((r) => new Set(r).add(id))} />
      ))}
      {decided.length ? (
        <details>
          <summary>
            <Trans id="tutor.proposals.decided">Earlier suggestions ({count})</Trans>
          </summary>
          <div className={ui.stack}>
            {decided.map((p) => (
              <ProposalCard key={p.id} proposal={p} compact />
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}
