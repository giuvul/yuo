// /setup: on a server the sign-in setup (code, passkey, recovery codes) comes first; then the environment
// wizard: your computer -> recommendation with the cost of a typical path for every option
// -> AI access and applying the models -> about you -> the first path. Resumes from the
// onboarding milestones (GET /api/onboarding).
import { Trans, useLingui } from "@lingui/react/macro";
import { createRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import type { OnboardingOut, Preset, ProbeOut, RecommendationOut, SetupOut } from "../api/client";
import { useSetup } from "../api/hooks";
import { useAuthState } from "../auth/api";
import { setupWizard } from "../auth/session";
import { SetupFlow } from "../auth/SetupFlow";
import { ErrorNotice } from "../components/ErrorNotice";
import { ArrowLeftIcon, ArrowRightIcon, CloudIcon, CoinsIcon, ComputerIcon, KeyIcon, SparkleIcon } from "../components/icons";
import { Badge, Button, ChoiceCards, MoreOptions, Notice, Stepper, ui, Waiting } from "../components/ui";
import { ConsentBox, LocalModelSteps, OpenRouterKeyForm, useConnectLocal } from "../onboarding/access";
import { CliAccess } from "../onboarding/CliAccess";
import {
  needsFor,
  useAccess,
  useChoosePreset,
  useCli,
  useDiscardSetupAnswers,
  useFinishOnboarding,
  useMe,
  useOnboarding,
  useProbe,
  useProviders,
  useRecommendation,
  useSetupAnswers,
} from "../onboarding/api";
import { ProbeSummary } from "../onboarding/ProbeSummary";
import { isDefaultProfile } from "../i18n";
import { ProfileForm } from "../onboarding/profile";
import {
  OptionEstimate,
  PRESET_NAMES,
  PRESET_SUMMARIES,
  ReasonText,
  VENDOR_OPTION,
  VENDOR_OPTION_NAME,
  VENDOR_OPTION_SUMMARY,
} from "../onboarding/texts";
import { VendorAccess } from "../onboarding/vendor";
import { SetupWarnings } from "../onboarding/vendorModels";
import styles from "../onboarding/onboarding.module.css";
import { useTutorRefs } from "../tutor/context";
import { NewPathForm } from "./pathNew";
import { rootRoute } from "./root";

export const setupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/setup",
  component: SetupRoute,
});

function SetupRoute() {
  const auth = useAuthState();
  const wizard = useSyncExternalStore(setupWizard.subscribe, setupWizard.get, setupWizard.get);
  const s = auth.data;
  if (s && !s.desktop && (!s.enrolled || !s.signed_in || wizard)) return <SetupFlow state={s} />;
  return <EnvironmentWizard />;
}

/** What the learner picks on the recommendation step: a preset, or their own key from a model vendor. */
export type Choice = Preset | typeof VENDOR_OPTION;

const STEPS = ["computer", "recommendation", "access", "about", "path"] as const;
type StepId = (typeof STEPS)[number];

/** Where a returning learner picks up: the first milestone not reached yet. */
function resumeStep(o: OnboardingOut): StepId {
  if (!o.probed) return "computer";
  if (!o.models_chosen) return "recommendation";
  if (!o.profile_done) return "about";
  if (o.done) return "recommendation"; // set up already: here to change the models
  return "path";
}

function EnvironmentWizard() {
  useTutorRefs({ screen: "setup" });
  const onboarding = useOnboarding();
  return (
    <section className={`${ui.stack} ${styles.wizard}`}>
      <h1 className={`${ui.pageTitle} ${styles.wizardTitle}`}>
        <Trans id="wizard.title">Set up Yuo</Trans>
      </h1>
      {onboarding.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : onboarding.isError ? (
        <ErrorNotice error={onboarding.error} />
      ) : (
        <Wizard initial={resumeStep(onboarding.data)} onboarding={onboarding.data} />
      )}
    </section>
  );
}

function Wizard({ initial, onboarding }: { initial: StepId; onboarding: OnboardingOut }) {
  const { t } = useLingui();
  const [step, setStep] = useState<StepId>(initial);
  const [choice, setChoice] = useState<Choice | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  const index = STEPS.indexOf(step);
  const number = index + 1;
  const total = STEPS.length;

  const titles: Record<StepId, string> = {
    computer: t({ id: "wizard.step.computer", message: "Your computer" }),
    recommendation: t({ id: "wizard.step.recommendation", message: "Recommendation" }),
    access: t({ id: "wizard.step.access", message: "AI access" }),
    about: t({ id: "wizard.step.about", message: "About you" }),
    path: t({ id: "wizard.step.path", message: "Your first path" }),
  };

  // move focus to the new step's heading (not on the first render)
  useEffect(() => {
    if (moved.current) headingRef.current?.focus();
    moved.current = true;
  }, [step]);

  const go = (to: StepId) => setStep(to);
  const back = index > 0 ? () => go(STEPS[index - 1]!) : null;
  const next = () => go(STEPS[Math.min(index + 1, total - 1)]!);

  return (
    <div className={ui.stack}>
      <nav aria-label={t({ id: "wizard.steps.label", message: "Setup steps" })}>
        <Stepper
          steps={STEPS.map((s, i) => ({
            id: s,
            label: titles[s],
            state: i < index ? "done" : i === index ? "current" : "todo",
          }))}
          doneLabel={t({ id: "wizard.steps.done", message: "(done)" })}
        />
      </nav>
      <div className={`${ui.card} ${ui.stack} ${styles.stepCard}`}>
        <div className={styles.stepHead}>
          <p className={ui.eyebrow}>
            <Trans id="wizard.step.of">
              Step {number} of {total}
            </Trans>
          </p>
          <h2 ref={headingRef} tabIndex={-1} className={styles.stepTitle}>
            {titles[step]}
          </h2>
        </div>

      {step === "computer" ? <ComputerStep back={back} next={next} /> : null}
      {step === "recommendation" ? (
        <RecommendationStep choice={choice} onChoice={setChoice} back={back} next={next} />
      ) : null}
      {step === "access" ? <AccessStep choice={choice} back={back} next={next} /> : null}
      {step === "about" ? <AboutStep back={back} next={next} /> : null}
      {step === "path" ? <PathStep back={back} hasPath={onboarding.has_path} /> : null}
      </div>
    </div>
  );
}

/** The step's footer: Back on the leading side, the step's actions (the primary one last) on the trailing side. */
function StepNav({ back, children }: { back: (() => void) | null; children?: ReactNode }) {
  return (
    <div className={styles.stepNav}>
      {back ? <BackButton onPress={back} /> : <span />}
      <div className={styles.stepActions}>{children}</div>
    </div>
  );
}

function BackButton({ onPress }: { onPress: () => void }) {
  return (
    <Button variant="secondary" onPress={onPress}>
      <ArrowLeftIcon size="1.1em" />
      <Trans id="wizard.back">Back</Trans>
    </Button>
  );
}

function NextButton({
  onPress,
  isDisabled,
  describedBy,
}: {
  onPress: () => void;
  isDisabled?: boolean;
  describedBy?: string;
}) {
  return (
    <Button onPress={onPress} isDisabled={isDisabled} aria-describedby={describedBy}>
      <Trans id="wizard.next">Next</Trans>
      <ArrowRightIcon size="1.1em" />
    </Button>
  );
}

// --- a. your computer ---------------------------------------------------------------------------------

function ComputerStep({ back, next }: { back: (() => void) | null; next: () => void }) {
  const probe = useProbe(true);
  return (
    <div className={ui.stack}>
      <p className={ui.muted}>
        <Trans id="wizard.computer.intro.short">
          Yuo looks at this computer to suggest how to write your lessons. Nothing leaves this computer.
        </Trans>
      </p>
      {probe.isFetching ? (
        <div className={ui.panel}>
          <Waiting>
            <Trans id="wizard.computer.checking">Checking your computer. This takes a few seconds…</Trans>
          </Waiting>
        </div>
      ) : null}
      {probe.isError ? <ErrorNotice error={probe.error} /> : null}
      {probe.data && !probe.isFetching ? <ProbeSummary probe={probe.data} /> : null}
      <StepNav back={back}>
        {probe.data && !probe.isFetching ? (
          <Button variant="secondary" onPress={() => void probe.refetch()}>
            <Trans id="wizard.computer.again">Check again</Trans>
          </Button>
        ) : null}
        {probe.isError ? (
          <Button variant="secondary" onPress={() => void probe.refetch()}>
            <Trans id="wizard.computer.retry">Try again</Trans>
          </Button>
        ) : null}
        <NextButton onPress={next} isDisabled={!probe.data || probe.isFetching} />
      </StepNav>
    </div>
  );
}

// --- b. recommendation --------------------------------------------------------------------------------

function RecommendationStep({
  choice,
  onChoice,
  back,
  next,
}: {
  choice: Choice | null;
  onChoice: (p: Choice) => void;
  back: (() => void) | null;
  next: () => void;
}) {
  const rec = useRecommendation();
  const value = choice ?? rec.data?.preset ?? null;
  return (
    <div className={ui.stack}>
      {rec.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : rec.isError ? (
        <ErrorNotice error={rec.error} />
      ) : (
        <Options rec={rec.data} value={value} onChange={onChoice} />
      )}
      <StepNav back={back}>
        <NextButton
          onPress={() => {
            if (value && choice === null) onChoice(value);
            next();
          }}
          isDisabled={!value}
        />
      </StepNav>
    </div>
  );
}

const PRESET_ICONS: Record<Preset, ReactNode> = {
  claude: <SparkleIcon />,
  codex: <SparkleIcon />,
  local: <ComputerIcon />,
  open: <CloudIcon />,
};

function Options({
  rec,
  value,
  onChange,
}: {
  rec: RecommendationOut;
  value: Choice | null;
  onChange: (p: Choice) => void;
}) {
  const { t, i18n } = useLingui();
  const recommended = i18n._(PRESET_NAMES[rec.preset]);
  const reasonsId = useId();
  const choices = [
    ...rec.options.map((o, i) => ({
      value: o.preset as Choice,
      icon: PRESET_ICONS[o.preset],
      label: i18n._(PRESET_NAMES[o.preset]),
      badge:
        i === 0 ? (
          <Badge tone="success">
            <Trans id="wizard.options.recommended">Recommended</Trans>
          </Badge>
        ) : null,
      description: i18n._(PRESET_SUMMARIES[o.preset]),
      extra: (
        <>
          {(o.preset === "claude" || o.preset === "codex") && !rec.probe.clis[o.preset] ? (
            <span className={styles.optionNote} data-testid={`not-installed-${o.preset}`}>
              <Trans id="wizard.options.not-installed">
                Its program is not on this computer yet. Yuo will help you install it.
              </Trans>
            </span>
          ) : null}
          <span className={styles.optionEstimate}>
            <CoinsIcon size="1.1rem" className={styles.optionEstimateIcon} />
            <OptionEstimate preset={o.preset} estimate={o.estimate} />
          </span>
        </>
      ),
      describedBy: i === 0 ? reasonsId : undefined,
    })),
    {
      value: VENDOR_OPTION as Choice,
      icon: <KeyIcon />,
      label: i18n._(VENDOR_OPTION_NAME),
      description: i18n._(VENDOR_OPTION_SUMMARY),
    },
  ];
  return (
    <div className={ui.stack}>
      <div className={`${ui.panel} ${styles.why}`}>
        <SparkleIcon className={styles.whyIcon} />
        <div className={styles.whyBody}>
          <p>
            <Trans id="wizard.recommendation.lead.short">
              We recommend <strong>{recommended}</strong> for this computer.
            </Trans>
          </p>
          <MoreOptions title={t({ id: "wizard.recommendation.why", message: "Why this one?" })}>
            <ul id={reasonsId} className={styles.reasons}>
              {rec.reasons.map((r, i) => (
                <li key={`${r.code}-${i}`}>
                  <ReasonText reason={r} />
                </li>
              ))}
            </ul>
          </MoreOptions>
        </div>
      </div>
      <ChoiceCards
        label={t({ id: "wizard.options.label", message: "How Yuo writes your lessons" })}
        choices={choices}
        value={value}
        onChange={onChange}
      />
      <p className={`${ui.muted} ${styles.small}`}>
        <Trans id="wizard.options.later">You can change this later in Settings.</Trans>
      </p>
    </div>
  );
}

// --- c + d. AI access, then apply the preset ---------------------------------------------------------

function AccessStep({ choice, back, next }: { choice: Choice | null; back: (() => void) | null; next: () => void }) {
  if (choice === VENDOR_OPTION) return <VendorAccessStep back={back} next={next} />;
  return <PresetAccessStep choice={choice} back={back} next={next} />;
}

/** The option picked on the previous step, as a quiet line at the top of the access step. */
function Chosen({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <p className={styles.chosen}>
      <span className={styles.chosenIcon}>{icon}</span>
      <span>{children}</span>
    </p>
  );
}

function VendorAccessStep({ back, next }: { back: (() => void) | null; next: () => void }) {
  const { i18n } = useLingui();
  const providers = useProviders();
  const [applied, setApplied] = useState<SetupOut | null>(null);
  const name = i18n._(VENDOR_OPTION_NAME);
  return (
    <div className={ui.stack}>
      <Chosen icon={<KeyIcon />}>
        <Trans id="wizard.access.for">You chose: {name}</Trans>
      </Chosen>
      {providers.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : providers.isError ? (
        <ErrorNotice error={providers.error} />
      ) : (
        <VendorAccess providers={providers.data} onApplied={setApplied} />
      )}
      <StepNav back={back}>{applied ? <NextButton onPress={next} /> : null}</StepNav>
    </div>
  );
}

function PresetAccessStep({
  choice,
  back,
  next,
}: {
  choice: Preset | null;
  back: (() => void) | null;
  next: () => void;
}) {
  const rec = useRecommendation();
  const access = useAccess();
  const preset = choice ?? rec.data?.preset ?? null;
  if (rec.isPending || (access.isPending && !access.isError)) {
    return (
      <Waiting>
        <Trans id="common.loading">Loading…</Trans>
      </Waiting>
    );
  }
  if (rec.isError) return <ErrorNotice error={rec.error} />;
  if (!preset) return null;
  return <AccessFor preset={preset} probe={rec.data.probe} back={back} next={next} />;
}

function AccessFor({
  preset,
  probe,
  back,
  next,
}: {
  preset: Preset;
  probe: ProbeOut;
  back: (() => void) | null;
  next: () => void;
}) {
  const { i18n } = useLingui();
  const access = useAccess();
  const reprobe = useProbe(false);
  const choose = useChoosePreset();
  const local = useConnectLocal();
  const [agreed, setAgreed] = useState(false);
  const [applied, setApplied] = useState<SetupOut | null>(null);
  const waitId = useId();
  const needs = needsFor(preset, probe, access.data);
  // keep the key form (and its "accepted, credit left" note) after the key has satisfied the need
  const [keyAsked] = useState(() => needs.includes("openrouter_key"));
  const name = i18n._(PRESET_NAMES[preset]);
  const blocking = needs.filter((n) => n !== "consent" || !agreed);
  const cli = preset === "claude" || preset === "codex" ? preset : null;
  // the subscription's program: asked once the preset is saved; null = this server has nothing to check
  const program = useCli(applied ? cli : null);
  // a program that is there but did not say whether it is signed in (Codex) may go on: Yuo will try
  const programReady =
    !cli ||
    program.data === null ||
    program.data?.ready === true ||
    (program.data?.installed === true && program.data.logged_in === null);
  const programName = program.data?.name ?? "";

  const apply = async () => {
    if (preset === "local" && !access.data?.local) await local.connect(probe);
    const setup = await choose.mutateAsync({ preset, consent: cli !== null && agreed });
    setApplied(setup);
  };

  return (
    <div className={ui.stack}>
      <Chosen icon={PRESET_ICONS[preset]}>
        <Trans id="wizard.access.for">You chose: {name}</Trans>
      </Chosen>
      {needs.length === 0 && !keyAsked ? (
        <p className={ui.muted}>
          <Trans id="wizard.access.nothing">Nothing else is needed for this choice.</Trans>
        </p>
      ) : null}
      {keyAsked || needs.includes("openrouter_key") ? <OpenRouterKeyForm /> : null}
      {needs.includes("local_server") || needs.includes("local_model") || preset === "local" ? (
        <LocalModelSteps probe={probe} checking={reprobe.isFetching} onCheckAgain={() => void reprobe.refetch()} />
      ) : null}
      {cli && needs.includes("consent") ? <ConsentBox cli={cli} agreed={agreed} onChange={setAgreed} /> : null}
      {access.isError ? <ErrorNotice error={access.error} /> : null}

      {applied && programReady && program.data?.logged_in !== null ? (
        <Notice tone="success" role="status">
          <Trans id="wizard.access.applied">Done. Yuo uses {name} from now on.</Trans>
        </Notice>
      ) : applied ? (
        <p role="status" className={ui.muted}>
          <Trans id="wizard.access.applied.pending">Saved: Yuo will use {name}. Finish the steps below to go on.</Trans>
        </p>
      ) : null}
      {applied ? <SetupWarnings setup={applied} /> : null}
      {applied && cli ? <CliAccess cli={cli} /> : null}
      {choose.isError ? <ErrorNotice error={choose.error} /> : null}
      {local.mutation.isError ? <ErrorNotice error={local.mutation.error} /> : null}

      <StepNav back={back}>
        {applied ? (
          <>
            {!programReady && program.data ? (
              <span className={`${ui.muted} ${styles.small}`} id={waitId}>
                {program.data.installed ? (
                  <Trans id="wizard.access.wait.sign-in">Sign in to {programName} to go on.</Trans>
                ) : (
                  <Trans id="wizard.access.wait.install">Install {programName} to go on.</Trans>
                )}
              </span>
            ) : null}
            <NextButton onPress={next} isDisabled={!programReady} describedBy={programReady ? undefined : waitId} />
          </>
        ) : (
          <Button
            isDisabled={blocking.length > 0 || choose.isPending || local.mutation.isPending}
            onPress={() => void apply().catch(() => undefined)}
          >
            {choose.isPending || local.mutation.isPending ? (
              <Trans id="wizard.access.applying">Saving…</Trans>
            ) : (
              <Trans id="wizard.access.apply">Use this and continue</Trans>
            )}
          </Button>
        )}
      </StepNav>
    </div>
  );
}

// --- answers an AI assistant collected before Yuo started (SETUP.md) ---------------------------------------

/** Says the step starts from the assistant's answers, with a way to start empty instead (the file is deleted). */
function AnswersNote() {
  const discard = useDiscardSetupAnswers();
  return (
    <Notice>
      <div className={ui.stack}>
        <p>
          <Trans id="wizard.answers.note">
            Filled in from the answers your AI assistant collected. Check them and change anything before you go on.
          </Trans>
        </p>
        <div className={ui.row}>
          <Button variant="secondary" small isDisabled={discard.isPending} onPress={() => discard.mutate()}>
            <Trans id="wizard.answers.clear">Start empty instead</Trans>
          </Button>
        </div>
        {discard.isError ? <ErrorNotice error={discard.error} /> : null}
      </div>
    </Notice>
  );
}

// --- e. about you ---------------------------------------------------------------------------------------

function AboutStep({ back, next }: { back: (() => void) | null; next: () => void }) {
  const me = useMe();
  const answers = useSetupAnswers();
  const prefill = me.data && isDefaultProfile(me.data) ? (answers.data?.profile ?? null) : null;
  return (
    <div className={ui.stack}>
      <p className={ui.muted}>
        <Trans id="wizard.about.intro">A few things about you, so lessons fit. You can change all of this in Settings.</Trans>
      </p>
      {prefill ? <AnswersNote /> : null}
      {me.isPending || answers.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : me.isError ? (
        <ErrorNotice error={me.error} />
      ) : (
        <ProfileForm
          key={prefill ? "answers" : "plain"}
          me={me.data}
          prefill={prefill}
          withTheme
          compact
          submitLabel={
            <>
              <Trans id="wizard.about.save">Save and continue</Trans>
              <ArrowRightIcon size="1.1em" />
            </>
          }
          secondary={back ? <BackButton onPress={back} /> : null}
          onSaved={next}
        />
      )}
      {me.isPending || me.isError ? <StepNav back={back} /> : null}
    </div>
  );
}

// --- f. the first path ------------------------------------------------------------------------------------

function PathStep({ back, hasPath }: { back: (() => void) | null; hasPath: boolean }) {
  const navigate = useNavigate();
  const finish = useFinishOnboarding();
  const setup = useSetup();
  const waitlist = setup.data?.waitlist_url;
  const answers = useSetupAnswers();
  const prefill = hasPath ? null : (answers.data?.first_path ?? null);
  const done = (to: () => void) => finish.mutate(undefined, { onSuccess: to });

  return (
    <div className={ui.stack}>
      <p className={ui.muted}>
        <Trans id="wizard.path.intro.short">
          Last step: tell Yuo what you want to learn. It plans the skills and lessons, then writes the first ones.
        </Trans>
      </p>
      {prefill ? <AnswersNote /> : null}
      {answers.isPending && !hasPath ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : (
        <NewPathForm
          key={prefill ? "answers" : "plain"}
          prefill={prefill}
          onCreated={(pathId) => done(() => void navigate({ to: "/paths/$pathId", params: { pathId } }))}
          secondary={
            <>
              {back ? <BackButton onPress={back} /> : null}
              {hasPath ? (
                <Button variant="ghost" isDisabled={finish.isPending} onPress={() => done(() => void navigate({ to: "/" }))}>
                  <Trans id="wizard.path.skip">Finish without a new path</Trans>
                </Button>
              ) : null}
            </>
          }
        />
      )}
      {finish.isError ? <ErrorNotice error={finish.error} /> : null}
      {waitlist && waitlist.startsWith("https://") ? (
        <p className={`${ui.muted} ${styles.small}`}>
          <Trans id="wizard.path.waitlist">
            Would you rather not run Yuo on your own computer? A hosted version may come later.
          </Trans>{" "}
          <a href={waitlist} target="_blank" rel="noopener noreferrer">
            <Trans id="wizard.path.waitlist.link">Tell us you are interested (opens a form in a new tab)</Trans>
          </a>
        </p>
      ) : null}
    </div>
  );
}
