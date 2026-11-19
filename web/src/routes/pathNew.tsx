import { Plural, Trans, useLingui } from "@lingui/react/macro";
import { useQueryClient } from "@tanstack/react-query";
import { createRoute, useNavigate } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { Form } from "react-aria-components";
import { isAiNotReady, type EstimateOut, type GoalType, type SetupAnswersPath } from "../api/client";
import { useCreatePath, useEstimate } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { GOAL_TYPE } from "../components/labels";
import { ArrowRightIcon, BookIcon, CheckIcon, CoinsIcon, SparkleIcon, SproutIcon } from "../components/icons";
import { Button, ChoiceCards, ChoiceCardsMulti, Field, MoreOptions, Notice, ui, Waiting } from "../components/ui";
import { DepthField, type Depth } from "../components/DepthField";
import { rootRoute } from "./root";
import { useTutorRefs } from "../tutor/context";
import { AiReadyCards } from "../onboarding/AiReady";
import { m7Keys, useAiReady } from "../onboarding/api";
import { CliAccess } from "../onboarding/CliAccess";
import { PlanMeterNow, meterCli } from "../onboarding/PlanMeter";
import { PlanUsageList } from "../onboarding/PlanUsage";
import styles from "./pathNew.module.css";
import { MaterialStart } from "../material/StudiesForm";

export const pathNewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths/new",
  component: NewPathPage,
});

/** Lessons the estimate is shown for: a typical first path. */
const ESTIMATE_LESSONS = 20;
const CUSTOM_INSTRUCTIONS_MAX = 1000;

function Estimate({ estimate }: { estimate: EstimateOut }) {
  const { i18n } = useLingui();
  const usd = (v: number) => i18n.number(v, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const low = usd(estimate.low_usd);
  const high = usd(estimate.high_usd);
  const lessons = ESTIMATE_LESSONS;
  const showBilled = estimate.high_usd > 0 || estimate.notional_usd <= 0;

  return (
    <div className={`${ui.panel} ${styles.estimate}`} role="status">
      <CoinsIcon className={styles.estimateIcon} />
      <div className={styles.estimateBody}>
        <p className={styles.estimateTitle}>
          <strong>
            <Plural
              id="path.new.estimate.title"
              value={lessons}
              one="Estimated cost for # lesson"
              other="Estimated cost for # lessons"
            />
          </strong>
        </p>
        {showBilled ? (
          <p className={styles.estimateAmount}>
            <Trans id="path.new.estimate.billed">
              about {low}–{high} billed
            </Trans>
          </p>
        ) : null}
        {estimate.notional_usd > 0 ? (
          <div>
            <Trans id="path.new.estimate.plan">
              No extra cost on your subscription; it uses part of your plan's limits:
            </Trans>
            {(["claude-cli", "codex-cli"] as const)
              .filter((cli) => estimate.lines.some((l) => l.adapter === cli && !l.billed))
              .map((cli) => (
                <div key={cli}>
                  <PlanUsageList rows={estimate.plan_usage ?? []} cli={cli} />
                  <PlanMeterNow cli={meterCli(cli)} />
                </div>
              ))}
          </div>
        ) : null}
        {estimate.missing.length > 0 ? (
          <p className={ui.muted}>
            <Trans id="path.new.estimate.missing">
              Some steps have no known price yet, so the real cost can be higher.
            </Trans>
          </p>
        ) : null}
      </div>
    </div>
  );
}

function NewPathPage() {
  useTutorRefs({ screen: "new_path" });
  const navigate = useNavigate();
  return (
    <section className={`${ui.stack} ${styles.page}`}>
      <h1 className={ui.pageTitle}>
        <Trans id="path.new.title">New learning path</Trans>
      </h1>
      <p className={ui.muted}>
        <Trans id="path.new.intro.preview">
          Name what you want to learn and what you want to be able to do. A few questions then show what you
          already know, and Yuo plans the path from there. You see the plan and can change it before anything
          is written.
        </Trans>
      </p>
      <div className={ui.card}>
        <NewPathForm onCreated={(pathId) => void navigate({ to: "/paths/$pathId", params: { pathId } })} />
      </div>
    </section>
  );
}

const GOAL_ICONS: Record<GoalType, ReactNode> = {
  exam: <CheckIcon />,
  practical: <SproutIcon />,
  understanding: <BookIcon />,
  curiosity: <SparkleIcon />,
};

type Start = "goal" | "courses";

/**
 * The new-path form: from a goal (described in words), or from the learner's own courses and material.
 * Also the wizard's last step, which puts Back and "finish without a path" in `secondary`.
 */
export function NewPathForm({
  onCreated,
  secondary,
  prefill,
}: {
  onCreated: (pathId: string) => void;
  secondary?: ReactNode;
  prefill?: SetupAnswersPath | null;
}) {
  const { t } = useLingui();
  const [start, setStart] = useState<Start>("goal");
  return (
    <div className={ui.stack}>
      <ChoiceCards
        label={t({ id: "path.new.start", message: "Start from" })}
        choices={[
          {
            value: "goal" as const,
            label: t({ id: "path.new.start.goal", message: "A goal" }),
            description: t({
              id: "path.new.start.goal.description",
              message: "Describe what you want to learn; Yuo plans it and writes the lessons.",
            }),
            icon: <SparkleIcon />,
          },
          {
            value: "courses" as const,
            label: t({ id: "path.new.start.courses", message: "My own material" }),
            description: t({
              id: "path.new.start.courses.description",
              message: "Build on your books, slides, notes and recordings: for a degree, an exam, or anything you are reading.",
            }),
            icon: <BookIcon />,
          },
        ]}
        value={start}
        onChange={setStart}
        compact
      />
      {start === "goal" ? (
        <GoalPathForm onCreated={onCreated} secondary={secondary} prefill={prefill} />
      ) : (
        <MaterialStart onCreated={onCreated} secondary={secondary} />
      )}
    </div>
  );
}

function GoalPathForm({
  onCreated,
  secondary,
  prefill,
}: {
  onCreated: (pathId: string) => void;
  secondary?: ReactNode;
  /** The wizard: the first path an AI assistant collected before Yuo started (SETUP.md). */
  prefill?: SetupAnswersPath | null;
}) {
  const { t, i18n } = useLingui();
  const estimate = useEstimate(ESTIMATE_LESSONS);
  const create = useCreatePath();
  const qc = useQueryClient();
  // asked before anything is written: a missing program or sign-in is a step here, not a failed path
  const aiReady = useAiReady();
  const blocked = aiReady.data?.ready === false;
  // the server still said no (the sign-in ended between the check and the click): the same card
  const refused = isAiNotReady(create.error) ? create.error : null;
  const refusedCli = refused?.cli === "claude" || refused?.cli === "codex" ? refused.cli : null;
  const [title, setTitle] = useState(prefill?.title ?? "");
  const [goal, setGoal] = useState(prefill?.goal ?? "");
  const [goalTypes, setGoalTypes] = useState<GoalType[]>([prefill?.goal_type ?? "understanding"]);
  const [depth, setDepth] = useState<Depth>("standard");
  const [instructions, setInstructions] = useState(prefill?.custom_instructions ?? "");

  const goalChoices = (Object.keys(GOAL_TYPE) as GoalType[]).map((value) => ({
    value,
    label: i18n._(GOAL_TYPE[value]),
    icon: GOAL_ICONS[value],
  }));
  const used = instructions.length;
  const max = CUSTOM_INSTRUCTIONS_MAX;

  return (
    <Form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        if (blocked) return;
        create.mutate(
          {
            title: title.trim(),
            subject: "", // the server uses the title; the level check sets the level
            difficulty: "foundational",
            goal: goal.trim(),
            goal_type: goalTypes[0] ?? "understanding",
            goal_types: goalTypes,
            depth,
            custom_instructions: instructions.trim(),
            level_check: true,
            preview: true,
          },
          {
            onSuccess: (r) => onCreated(r.path_id),
            onError: (e) => {
              if (isAiNotReady(e)) void qc.invalidateQueries({ queryKey: m7Keys.aiReady });
            },
          },
        );
      }}
    >
      {blocked && aiReady.data ? <AiReadyCards ready={aiReady.data} /> : null}
      <Field
        label={t({ id: "path.new.field.title", message: "Title" })}
        description={t({ id: "path.new.field.title.description.topic", message: "What you want to learn, e.g. “SQL for analysts” or “Spanish for travel”." })}
        value={title}
        onChange={setTitle}
        isRequired
        maxLength={120}
        name="title"
      />
      <Field
        label={t({ id: "path.new.field.goal", message: "Your goal" })}
        description={t({
          id: "path.new.field.goal.description",
          message: "What you want to be able to do at the end.",
        })}
        value={goal}
        onChange={setGoal}
        isRequired
        maxLength={600}
        multiline
        name="goal"
      />
      <ChoiceCardsMulti
        label={t({ id: "path.new.field.goal-type", message: "Why are you learning this?" })}
        description={t({ id: "path.new.field.goal-type.description", message: "Choose all that apply." })}
        choices={goalChoices}
        value={goalTypes}
        onChange={setGoalTypes}
        required
      />
      <DepthField value={depth} onChange={setDepth} />
      <MoreOptions
        title={t({ id: "path.new.more-options", message: "More options" })}
        defaultExpanded={Boolean(prefill?.custom_instructions)}
      >
        <Field
          label={t({ id: "path.new.field.instructions", message: "Custom instructions (optional)" })}
          description={t({
            id: "path.new.field.instructions.description",
            message: `${used} of ${max} characters. For example: use Python examples, keep lessons short.`,
          })}
          value={instructions}
          onChange={setInstructions}
          maxLength={max}
          multiline
          name="custom_instructions"
        />
      </MoreOptions>

      {estimate.data ? <Estimate estimate={estimate.data} /> : null}
      {estimate.isPending ? (
        <div className={ui.panel}>
          <Waiting>
            <Trans id="path.new.estimate.loading">Working out the cost…</Trans>
          </Waiting>
        </div>
      ) : null}
      {estimate.isError ? (
        <p className={ui.muted}>
          <Trans id="path.new.estimate.unavailable">The cost estimate is not available right now.</Trans>
        </p>
      ) : null}

      {refused && !blocked ? (
        <div className={ui.stack}>
          <Notice tone="warning" icon={true} role="alert">
            <Trans id="path.new.not-ready">
              Yuo could not start your path: the program of your subscription is not ready. Fix it here, then
              choose Create path again.
            </Trans>
          </Notice>
          {refusedCli ? <CliAccess cli={refusedCli} /> : null}
        </div>
      ) : create.isError && !refused ? (
        <ErrorNotice error={create.error} />
      ) : null}

      <div className={secondary ? styles.formNav : ui.row}>
        {secondary ? <div className={ui.row}>{secondary}</div> : null}
        <Button type="submit" isDisabled={create.isPending || blocked}>
          {create.isPending ? (
            <Trans id="path.new.submitting">Creating…</Trans>
          ) : (
            <>
              <Trans id="path.new.submit">Create path</Trans>
              <ArrowRightIcon size="1.1em" />
            </>
          )}
        </Button>
      </div>
    </Form>
  );
}
