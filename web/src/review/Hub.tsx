// The review hub of one path (3.2.8): how well what was studied is remembered, the sessions to start, memory
// per skill and objective, recent sessions, and the flashcard queue ("Cards"). Also the hub's two entry points on
// the path page: the Review card above the tree and "Review this skill" in a skill's panel.
import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { ToggleButton, ToggleButtonGroup } from "react-aria-components";
import { startReviews } from "../api/hooks";
import { AssessmentRunner } from "../assessment/AssessmentRunner";
import { StartGate } from "../assessment/StartGate";
import { CountUp, GrowingSprout } from "../components/Grove";
import { ArrowRightIcon, LeafIcon, RepeatIcon } from "../components/icons";
import { Seedling } from "../components/illustrations";
import { MasteryBar } from "../components/MasteryBar";
import { Button, ButtonLink, Notice, ui } from "../components/ui";
import { reviewKeys, type HubSkill, type ReviewHub, type ReviewSize } from "./api";
import { MemoryRing, ObjectiveLeaf } from "./primitives";
import styles from "./review.module.css";

const percentOf = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 100);

/** "Writing your review questions": shown while a lesson's questions are on their way. */
function WritingNotice() {
  return (
    <p className={styles.writing} role="status">
      <GrowingSprout />
      <Trans id="review.hub.writing">Writing your review questions. This page updates by itself.</Trans>
    </p>
  );
}

function SizeName({ size }: { size: ReviewSize }) {
  return size === 5 ? (
    <Trans id="review.size.quick">Quick</Trans>
  ) : size === 10 ? (
    <Trans id="review.size.standard">Standard</Trans>
  ) : (
    <Trans id="review.size.deep">Deep</Trans>
  );
}

/** The top of the hub: the memory ring, what is due, and the sessions to start. */
function Overview({ pathId, hub }: { pathId: string; hub: ReviewHub }) {
  const { t, i18n } = useLingui();
  const [branch, setBranch] = useState<string | null>(null);
  const memory = hub.memory ?? 0;
  const percent = percentOf(memory);
  const { due, fading, strong } = hub;
  const open = hub.open_session;
  const limit = hub.allowed_today === 0;
  const primary = hub.sizes.includes(10) ? 10 : hub.sizes[hub.sizes.length - 1];
  const answered = open?.answered ?? 0;
  const size = open?.size ?? 0;

  return (
    <section className={`${ui.card} ${styles.hubTop}`} aria-labelledby="review-memory">
      <MemoryRing
        value={hub.memory}
        label={t({ id: "review.hub.ring", message: `Memory: ${i18n.number(memory, { style: "percent", maximumFractionDigits: 0 })}` })}
      >
        <span className={styles.ringNumber}>
          <CountUp value={percent} formatted={String(percent)} />
          <span className={styles.ringUnit}>%</span>
        </span>
        <span className={styles.ringCaption}>
          <Trans id="review.hub.ring.caption">memory</Trans>
        </span>
      </MemoryRing>
      <div className={styles.hubMain}>
        <h2 id="review-memory" className={styles.hubLead}>
          {due > 0 ? (
            <Plural id="review.hub.lead.due" value={due} one="# idea is due for review" other="# ideas are due for review" />
          ) : fading > 0 ? (
            <Plural id="review.hub.lead.fading" value={fading} one="# idea is starting to fade" other="# ideas are starting to fade" />
          ) : (
            <Trans id="review.hub.lead.fresh">Everything you studied is still fresh</Trans>
          )}
        </h2>
        <ul className={styles.chips}>
          <li className={styles.chip} data-tone={due > 0 ? "due" : undefined}>
            <strong>{due}</strong> <Trans id="review.hub.chip.due">due</Trans>
          </li>
          <li className={styles.chip}>
            <strong>{fading}</strong> <Trans id="review.hub.chip.fading">fading</Trans>
          </li>
          <li className={styles.chip} data-tone="strong">
            <strong>{strong}</strong> <Trans id="review.hub.chip.strong">strong</Trans>
          </li>
        </ul>

        {limit ? (
          <Notice role="status" icon={<LeafIcon />}>
            <Trans id="review.hub.limit">You reached today's review limit. More reviews come tomorrow.</Trans>
          </Notice>
        ) : open ? (
          <div className={styles.starts}>
            <ButtonLink to="/paths/$pathId/review/session" params={{ pathId }}>
              <Trans id="review.hub.continue">
                Continue your session ({answered} of {size})
              </Trans>
              <ArrowRightIcon size="1.1em" />
            </ButtonLink>
          </div>
        ) : hub.sizes.length > 0 ? (
          <>
            {hub.branches.length > 1 ? (
              <div className={styles.focus}>
                <span id="review-focus" className={styles.focusLabel}>
                  <Trans id="review.hub.focus">Focus</Trans>
                </span>
                <ToggleButtonGroup
                  className={styles.focusChips}
                  selectionMode="single"
                  disallowEmptySelection
                  selectedKeys={[branch ?? "all"]}
                  onSelectionChange={(keys) => {
                    const next = [...keys][0];
                    setBranch(typeof next === "string" && next !== "all" ? next : null);
                  }}
                  aria-labelledby="review-focus"
                >
                  <ToggleButton id="all" className={styles.focusChip}>
                    <Trans id="review.hub.focus.all">Everything</Trans>
                  </ToggleButton>
                  {hub.branches.map((b) => (
                    <ToggleButton key={b.id} id={b.id} className={styles.focusChip}>
                      {b.title}
                    </ToggleButton>
                  ))}
                </ToggleButtonGroup>
              </div>
            ) : null}
            <div className={styles.starts}>
              {(hub.sizes as ReviewSize[]).map((n) => (
                <ButtonLink
                  key={n}
                  to="/paths/$pathId/review/session"
                  params={{ pathId }}
                  search={branch ? { size: n, branch } : { size: n }}
                  variant={n === primary ? "primary" : "secondary"}
                >
                  <SizeName size={n} /> <span className={styles.startCount}>{n}</span>
                </ButtonLink>
              ))}
            </div>
          </>
        ) : hub.writing > 0 ? (
          <WritingNotice />
        ) : (
          <p className={ui.muted}>
            <Trans id="review.hub.no-questions">There are no review questions for what you studied yet.</Trans>
          </p>
        )}
      </div>
    </section>
  );
}

function SkillCard({ pathId, skill, canStart }: { pathId: string; skill: HubSkill; canStart: boolean }) {
  const { t, i18n } = useLingui();
  const title = skill.title;
  const pct = (v: number) => i18n.number(v, { style: "percent", maximumFractionDigits: 0 });
  const memory = pct(skill.retrievability);
  return (
    <li className={`${ui.card} ${styles.skillCard}`}>
      <div className={styles.skillHead}>
        <h3 className={styles.skillTitle}>{title}</h3>
        <span className={styles.skillMemory}>
          <Trans id="review.hub.skill.memory">{memory} memory</Trans>
        </span>
      </div>
      <ul className={styles.objectives}>
        {skill.objectives.map((o) => {
          const value = pct(o.retrievability);
          const date = i18n.date(new Date(o.due_at), { dateStyle: "medium" });
          return (
            <li key={o.id} className={styles.objective}>
              <ObjectiveLeaf value={o.retrievability} due={o.due} />
              <span>
                {o.statement}
                <span className={styles.objectiveMeta}>
                  {o.due ? (
                    <>
                      <Trans id="review.hub.objective.memory">{value} remembered</Trans>
                      <span className={styles.dueMark}>
                        <Trans id="review.hub.objective.due">Due</Trans>
                      </span>
                    </>
                  ) : (
                    <Trans id="review.hub.objective.next">
                      {value} remembered · next review {date}
                    </Trans>
                  )}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      {canStart && skill.questions > 0 ? (
        <div>
          <ButtonLink
            to="/paths/$pathId/review/session"
            params={{ pathId }}
            search={{ size: 5, skill: skill.id }}
            variant="secondary"
            small
            aria-label={t({ id: "review.skill.start.label", message: `Review this skill: ${title}` })}
          >
            <RepeatIcon />
            <Trans id="review.skill.start">Review this skill</Trans>
          </ButtonLink>
        </div>
      ) : null}
    </li>
  );
}

/** The flashcard queue of the path, folded into the hub: the cards that are due, run in place. */
function Cards({ pathId, due }: { pathId: string; due: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const start = useCallback(() => startReviews(pathId), [pathId]);
  const refresh = () => void qc.invalidateQueries({ queryKey: reviewKeys.hub(pathId) });
  return (
    <section className={`${ui.card} ${styles.section}`} aria-labelledby="review-cards">
      <div className={styles.sectionRow}>
        <div>
          <h2 id="review-cards" className={styles.sectionTitle}>
            <Trans id="review.cards.title">Cards</Trans>
          </h2>
          <p className={ui.muted}>
            <Plural
              id="review.cards.due"
              value={due}
              one="# flashcard from your practice is due."
              other="# flashcards from your practice are due."
            />
          </p>
        </div>
        {open ? null : (
          <Button variant="secondary" onPress={() => setOpen(true)}>
            <Trans id="review.cards.start">Review cards</Trans>
          </Button>
        )}
      </div>
      {open ? (
        <StartGate
          startKey={`cards:${pathId}`}
          start={start}
          preparing={<Trans id="review.cards.preparing">Preparing your cards…</Trans>}
          empty={(a) => (
            <Notice role="status" icon={<LeafIcon />}>
              {(a.due ?? 0) > 0 ? (
                <Trans id="review.hub.limit">You reached today's review limit. More reviews come tomorrow.</Trans>
              ) : (
                <Trans id="review.cards.none">No cards are due right now. Well done.</Trans>
              )}
            </Notice>
          )}
        >
          {(assessment) => <AssessmentRunner assessment={assessment} onFinished={refresh} />}
        </StartGate>
      ) : null}
    </section>
  );
}

export function Hub({ pathId, hub }: { pathId: string; hub: ReviewHub }) {
  const { i18n } = useLingui();
  const canStart = hub.allowed_today > 0 && hub.open_session === null && hub.sizes.length > 0;
  return (
    <>
      {hub.memory === null ? (
        <section className={`${ui.card} ${styles.empty}`} aria-labelledby="review-empty">
          <Seedling width={112} />
          <h2 id="review-empty" className={styles.emptyTitle}>
            <Trans id="review.hub.empty.title">Nothing to review yet</Trans>
          </h2>
          <p className={ui.muted}>
            <Trans id="review.hub.empty.body">
              Finish a lesson and its ideas appear here. Yuo then brings each one back just before you would forget
              it, with fresh questions every time.
            </Trans>
          </p>
          <ButtonLink to="/paths/$pathId" params={{ pathId }}>
            <Trans id="review.hub.empty.back">Go to the path</Trans>
          </ButtonLink>
        </section>
      ) : (
        <>
          <Overview pathId={pathId} hub={hub} />
          <h2 className={styles.sectionTitle}>
            <Trans id="review.hub.skills">Memory by skill</Trans>
          </h2>
          <ul className={styles.skillGrid}>
            {hub.skills.map((s) => (
              <SkillCard key={s.id} pathId={pathId} skill={s} canStart={canStart} />
            ))}
          </ul>
        </>
      )}

      {hub.cards_due > 0 ? <Cards pathId={pathId} due={hub.cards_due} /> : null}

      {hub.recent.length > 0 ? (
        <section className={`${ui.card} ${styles.section}`} aria-labelledby="review-recent">
          <h2 id="review-recent" className={styles.sectionTitle}>
            <Trans id="review.hub.recent">Recent sessions</Trans>
          </h2>
          <ul className={styles.recent}>
            {hub.recent.map((r) => {
              const first = r.first_try;
              const answered = r.answered;
              return (
                <li key={r.attempt_id}>
                  <span>{i18n.date(new Date(r.finished_at), { dateStyle: "medium", timeStyle: "short" })}</span>
                  <span className={ui.muted}>
                    <Trans id="review.hub.recent.row">
                      {first} of {answered} right on the first try
                    </Trans>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </>
  );
}

/** The Review card on the path page, above the tree: what is due, and the way into the hub. */
export function ReviewEntry({ pathId, hub }: { pathId: string; hub: ReviewHub | undefined }) {
  const { t, i18n } = useLingui();
  if (!hub || hub.memory === null) return null;
  const { due, fading } = hub;
  const percent = percentOf(hub.memory);
  const waiting = hub.questions === 0 && hub.writing > 0;
  return (
    <section className={`${ui.card} ${styles.entry}`} aria-labelledby="path-review">
      <div className={styles.entryMain}>
        <div className={styles.entryRing}>
          <MemoryRing
            value={hub.memory}
            label={t({ id: "review.hub.ring", message: `Memory: ${i18n.number(hub.memory, { style: "percent", maximumFractionDigits: 0 })}` })}
          >
            <span className={styles.ringNumber}>{percent}</span>
          </MemoryRing>
        </div>
        <div className={styles.entryText}>
          <h2 id="path-review" className={styles.entryTitle}>
            <Trans id="review.entry.title">Review</Trans>
          </h2>
          {waiting ? (
            <WritingNotice />
          ) : (
            <p className={ui.muted}>
              {due > 0 || fading > 0 ? (
                <Trans id="review.entry.counts">
                  {due} due · {fading} fading
                </Trans>
              ) : (
                <Trans id="review.entry.fresh">Everything you studied is still fresh.</Trans>
              )}
            </p>
          )}
        </div>
      </div>
      <ButtonLink to="/paths/$pathId/review" params={{ pathId }} variant={due > 0 ? "primary" : "secondary"}>
        <RepeatIcon />
        <Trans id="review.entry.open">Open review</Trans>
      </ButtonLink>
    </section>
  );
}

/** In a skill's panel on the tree (and under a skill in the list): its memory and "Review this skill". */
export function SkillReview({ pathId, hub, skillId }: { pathId: string; hub: ReviewHub | undefined; skillId: string }) {
  const { t } = useLingui();
  const skill = hub?.skills.find((s) => s.id === skillId);
  if (!hub || !skill) return null;
  const title = skill.title;
  const canStart = hub.allowed_today > 0 && skill.questions > 0;
  return (
    <div className={styles.skillExtra}>
      <h3 className={styles.skillExtraHeading}>
        <Trans id="review.skill.memory">Memory</Trans>
      </h3>
      <MasteryBar value={skill.retrievability} label={t({ id: "review.skill.memory.label", message: `Memory of ${title}` })} />
      {canStart ? (
        <div>
          <ButtonLink
            to="/paths/$pathId/review/session"
            params={{ pathId }}
            search={{ size: 5, skill: skill.id }}
            variant="secondary"
            small
            aria-label={t({ id: "review.skill.start.label", message: `Review this skill: ${title}` })}
          >
            <RepeatIcon />
            <Trans id="review.skill.start">Review this skill</Trans>
          </ButtonLink>
        </div>
      ) : null}
    </div>
  );
}
