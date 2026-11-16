// The design catalogue: every primitive in every state, in the current theme. A page
// for builders, not learners: it is not linked from the app and its text is not translated. Open /design and
// switch the theme with the buttons to see both.
import { createRoute } from "@tanstack/react-router";
import { useState } from "react";
import { LogoMark, Logo } from "../components/Logo";
import * as icons from "../components/icons";
import { BookIcon, CloudIcon, ComputerIcon, KeyIcon, LeafIcon } from "../components/icons";
import { BookStack, GroveTree, Landscape, Seedling } from "../components/illustrations";
import { CountUp, grove, GrowingCheck, GrowingSprout, LeafPop, LeafWatermark, VineDivider } from "../components/Grove";
import { MasteryBar } from "../components/MasteryBar";
import {
  BackLink,
  Badge,
  Button,
  ChoiceCards,
  ChoiceField,
  Field,
  MoreOptions,
  Notice,
  PageHeader,
  Progress,
  Stepper,
  Waiting,
  ui,
} from "../components/ui";
import type { CliOut } from "../api/client";
import { CliAccessView } from "../onboarding/CliAccess";
import { LARGE_TREE, SMALL_TREE } from "../path/fixtures";
import { LazyPathGraph } from "../path/LazyPathGraph";
import { NodeSample } from "../path/TreeNode";
import { MemoryRing, ObjectiveLeaf, OptionButton, ProgressVine } from "../review/primitives";
import review from "../review/review.module.css";
import { rootRoute } from "./root";
import styles from "./design.module.css";

export const designRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/design",
  component: DesignPage,
});

/** A full-size sample of the path graph on its own page, to judge it at every width (/design/tree). */
export const designTreeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/design/tree",
  component: DesignTreePage,
});

function DesignTreePage() {
  return (
    <section className={ui.stack}>
      <h1 className={ui.pageTitle}>Path graph, full size</h1>
      <p className={ui.muted}>
        Five branches, twenty-one skills, prerequisites across branches, every state. Sample data: the lesson buttons
        lead nowhere.
      </p>
      <LazyPathGraph path={LARGE_TREE.path} progress={LARGE_TREE.progress} />
    </section>
  );
}

const COLORS = [
  "bg",
  "surface",
  "surface-muted",
  "border",
  "border-strong",
  "fg",
  "muted",
  "accent",
  "accent-hover",
  "link",
  "focus",
  "highlight",
  "leaf",
  "success",
  "success-bg",
  "warning",
  "warning-bg",
  "danger",
  "danger-bg",
  "info-bg",
  "code-bg",
  "track",
  "media-bg",
  "media-bar",
  "scrim",
  "pattern-leaf",
  "logo-leaf",
  "mote",
  "twig",
];
const SIZES = ["4xl", "3xl", "2xl", "xl", "lg", "md", "sm", "xs"];

const CLI_NOOP = {
  onInstall: () => undefined,
  onLogin: () => undefined,
  onSendCode: () => undefined,
  onCancelLogin: () => undefined,
  onCheck: () => undefined,
};

const CLI_BASE: CliOut = {
  cli: "claude",
  name: "Claude Code",
  needed: true,
  installed: false,
  version: null,
  logged_in: null,
  account: null,
  ready: false,
  reason: "not_installed",
  detail: null,
  os: "linux",
  container: false,
  can_install: true,
  can_login: true,
  code_login: true,
  install_command: "curl -fsSL https://claude.ai/install.sh | bash",
  login_command: "claude auth login",
  docs_url: "https://docs.claude.com/en/docs/claude-code/setup",
  install: { state: "idle", url: null, code: null, error: null },
  login: { state: "idle", url: null, code: null, error: null },
};
const CLI_INSTALLED: CliOut = {
  ...CLI_BASE,
  installed: true,
  version: "2.1.0",
  logged_in: false,
  reason: "not_logged_in",
};
const CLI_CODEX_INSTALLED = { installed: true, version: "0.42.0" };
const CLI_CODEX: CliOut = {
  ...CLI_BASE,
  cli: "codex",
  name: "Codex",
  os: "windows",
  can_install: false,
  can_login: true,
  code_login: false,
  install_command: "irm https://chatgpt.com/codex/install.ps1 | iex",
  login_command: "codex login",
  docs_url: "https://developers.openai.com/codex/cli",
};

const CLI_SAMPLES: [string, CliOut][] = [
  ["Not installed", CLI_BASE],
  ["Installing", { ...CLI_BASE, install: { state: "running", url: null, code: null, error: null } }],
  [
    "Install failed, in a container",
    {
      ...CLI_BASE,
      container: true,
      install: { state: "failed", url: null, code: null, error: "the installer needs curl or wget" },
    },
  ],
  ["Not installed, by hand", CLI_CODEX],
  ["Not signed in", CLI_INSTALLED],
  [
    "Sign-in: paste the code",
    {
      ...CLI_INSTALLED,
      login: { state: "waiting_code", url: "https://claude.ai/oauth/authorize?sample=1", code: null, error: null },
    },
  ],
  [
    "Sign-in: browser on this computer",
    {
      ...CLI_INSTALLED,
      os: "windows",
      code_login: false,
      login: { state: "waiting_browser", url: null, code: null, error: null },
    },
  ],
  [
    "Sign-in: one-time code",
    {
      ...CLI_CODEX,
      ...CLI_CODEX_INSTALLED,
      logged_in: false,
      reason: "not_logged_in",
      login: { state: "waiting_device", url: "https://auth.openai.com/codex/device", code: "FQ9C-SNGC4", error: null },
    },
  ],
  [
    "Sign-in failed",
    { ...CLI_INSTALLED, login: { state: "failed", url: null, code: null, error: "the sign-in took too long" } },
  ],
  [
    "Signed out, by hand",
    { ...CLI_CODEX, ...CLI_CODEX_INSTALLED, can_login: false, logged_in: false, reason: "not_logged_in" },
  ],
  ["Sign-in not confirmed", { ...CLI_CODEX, ...CLI_CODEX_INSTALLED, logged_in: null, ready: true, reason: null }],
  ["Ready", { ...CLI_INSTALLED, logged_in: true, ready: true, reason: null, account: "Max plan" }],
];

function setTheme(theme: "light" | "dark" | null) {
  const root = document.documentElement;
  if (theme) root.dataset["theme"] = theme;
  else delete root.dataset["theme"];
}

function DesignPage() {
  const [text, setText] = useState("");
  const [choice, setChoice] = useState<"a" | "b" | "c">("a");
  const [card, setCard] = useState<"local" | "open" | "key">("open");
  const [replay, setReplay] = useState(0);
  return (
    <section className={ui.stack}>
      <div className={ui.row}>
        <h1 className={ui.pageTitle}>Design catalogue</h1>
        <Button small variant="secondary" onPress={() => setTheme("light")}>
          Light
        </Button>
        <Button small variant="secondary" onPress={() => setTheme("dark")}>
          Dark
        </Button>
        <Button small variant="ghost" onPress={() => setTheme(null)}>
          System
        </Button>
      </div>

      <h2>Page header</h2>
      <div className={ui.card}>
        <PageHeader
          back={<BackLink to="/design">Back to the path</BackLink>}
          eyebrow="Eyebrow"
          title="What is a tree?"
          meta={<span>About 6 minutes</span>}
          actions={
            <Button small variant="secondary">
              Action
            </Button>
          }
        />
      </div>

      <h2>Logo</h2>
      <p className={ui.muted}>
        The approved wordmark and the sprouting Y on its own. Forest with a Moss right leaf on light, one-colour Mist
        on dark; on a Forest surface the app icon's treatment. Tagline: Learn anything. Grow your skills.
      </p>
      <div className={ui.row}>
        <Logo label="Yuo" height={56} />
        <LogoMark size={56} />
        <span className={styles.forestTile}>
          <LogoMark size={40} tone="inverse" />
        </span>
        <img src="/icon.svg" alt="" width={64} height={64} />
        <img src="/favicon.svg" alt="" width={32} height={32} />
        <img src="/favicon.svg" alt="" width={16} height={16} />
      </div>

      <h2>Icons</h2>
      <p className={ui.muted}>Filled shapes for things, plain strokes for direction and action.</p>
      <div className={styles.iconGrid}>
        {Object.entries(icons).map(([name, Icon]) => (
          <span key={name} className={styles.iconCell}>
            <Icon size={24} />
            <code>{name.replace(/Icon$/, "")}</code>
          </span>
        ))}
      </div>

      <h2>Illustrations</h2>
      <div className={ui.row}>
        <Seedling />
        <GroveTree />
        <BookStack />
        <Landscape />
      </div>

      <h2>Colours (semantic)</h2>
      <div className={styles.swatches}>
        {COLORS.map((c) => (
          <div key={c} className={styles.swatch}>
            <span className={styles.chip} style={{ background: `var(--yuo-color-${c})` }} />
            <code>{c}</code>
          </div>
        ))}
      </div>

      <h2>Type</h2>
      <div className={ui.stack}>
        {SIZES.map((s) => (
          <div key={s} className={styles.typeRow}>
            <code>{s}</code>
            <span style={{ fontSize: `var(--yuo-text-${s})` }} className={s.endsWith("xl") ? styles.display : undefined}>
              Your path starts here
            </span>
          </div>
        ))}
        <p className={styles.reading}>
          Reading text sits in a column of about seventy characters, with a generous line height, so a lesson reads
          like a good book. <em>Italic</em>, <strong>bold</strong> and <code>inline code</code> keep the rhythm.
        </p>
        <span className={ui.eyebrow}>Eyebrow label</span>
      </div>

      <h2>Buttons</h2>
      <div className={ui.row}>
        <Button>Start lesson</Button>
        <Button variant="secondary">Save progress</Button>
        <Button variant="ghost">Skip</Button>
        <Button isDisabled>Disabled</Button>
        <Button small>Small</Button>
        <Button small variant="secondary">
          Small secondary
        </Button>
      </div>

      <h2>Fields and choices</h2>
      <div className={styles.grid}>
        <Field label="Title" description="What you want to learn." value={text} onChange={setText} />
        <Field label="Required" value="" onChange={() => {}} isRequired errorMessage="Fill this in." />
        <ChoiceField
          label="Checked answer (marks)"
          stacked
          isDisabled
          value="b"
          onChange={() => {}}
          marks={{ a: "right", b: "wrong" }}
          markLabels={{ right: "Right answer", wrong: "Your answer" }}
          choices={[
            { value: "a", label: "a. O(n)" },
            { value: "b", label: "b. O(n²)" },
            { value: "c", label: "c. O(1)" },
          ]}
        />
        <ChoiceField
          label="Choice cards"
          stacked
          value={choice}
          onChange={setChoice}
          choices={[
            { value: "a", label: "Recommended", description: "Selected state" },
            { value: "b", label: "Another option" },
            { value: "c", label: "A third option" },
          ]}
        />
      </div>

      <h2>Choice cards</h2>
      <ChoiceCards
        label="How Yuo writes your lessons"
        value={card}
        onChange={setCard}
        choices={[
          { value: "local", icon: <ComputerIcon />, label: "On this computer", description: "Nothing leaves it." },
          {
            value: "open",
            icon: <CloudIcon />,
            label: "Through a provider",
            badge: <Badge tone="success">Recommended</Badge>,
            description: "Pay per use.",
            extra: <span className={ui.panel}>About $0.12 to $0.40 for a typical path.</span>,
          },
          { value: "key", icon: <KeyIcon />, label: "Your own key", description: "Billed by the vendor." },
        ]}
      />
      <ChoiceCards
        label="Compact"
        compact
        value={card}
        onChange={setCard}
        choices={[
          { value: "local", icon: <BookIcon />, label: "Understand it well" },
          { value: "open", icon: <CloudIcon />, label: "Out of curiosity" },
          { value: "key", icon: <KeyIcon />, label: "Pass an exam" },
        ]}
      />

      <h2>Steps</h2>
      <Stepper
        steps={[
          { id: "a", label: "Your computer", state: "done" },
          { id: "b", label: "Recommendation", state: "current" },
          { id: "c", label: "AI access", state: "todo" },
          { id: "d", label: "About you", state: "todo" },
        ]}
      />
      <Stepper
        vertical
        steps={[
          { id: "a", label: "Your answers are in", state: "done" },
          { id: "b", label: "Planning the skills and lessons", state: "current" },
          { id: "c", label: "Writing your first lessons", state: "todo" },
        ]}
      />
      <MoreOptions title="More options (optional)">
        <p>Secondary fields live here, out of the way.</p>
      </MoreOptions>

      <h2>Feedback</h2>
      <Notice>Information: your path is being planned.</Notice>
      <Notice tone="success">Good job! You got it right.</Notice>
      <Notice tone="warning">The questions could not be written. You can skip the check.</Notice>
      <Notice tone="error">Not quite. Try again or review the lesson.</Notice>
      <Notice tone="success" icon={<LeafIcon />}>
        <p>
          <strong>Correct.</strong>
        </p>
        <p>With an icon: the tone's own (icon) or any line icon.</p>
      </Notice>
      <Notice tone="error" icon>
        Not quite. The right answer is a.
      </Notice>
      <Waiting>Writing a few questions. This takes about a minute.</Waiting>
      <div className={styles.grid}>
        <Progress label="Arrays" value={100} />
        <Progress label="Trees" value={62} />
        <Progress label="Graphs" value={0} />
        <MasteryBar label="Mastery, full" value={1} />
        <MasteryBar label="Mastery, partial" value={0.62} />
        <MasteryBar label="Mastery, mastered by its test" value={0.8} done />
      </div>
      <div className={ui.row}>
        <Badge>3 due</Badge>
        <Badge tone="highlight">Current</Badge>
        <Badge tone="success">Mastered</Badge>
      </div>

      <h2>Motion and details</h2>
      <p className={ui.muted}>
        Quiet and nature-themed: the leaf pattern sliding slowly behind this page, growth on first view, small moments after an
        answer. Loops move transform and opacity only; under reduced motion nothing loops and nothing is hidden.
      </p>
      <div className={ui.row}>
        <Button small variant="secondary" onPress={() => setReplay((n) => n + 1)}>
          Replay the one-off moments
        </Button>
        <span className={styles.pill}>
          <GrowingSprout />
          Generating…
        </span>
      </div>
      <div key={replay} className={styles.grid}>
        <Notice
          tone="success"
          role="status"
          icon={
            <LeafPop>
              <LeafIcon />
            </LeafPop>
          }
          className={grove.appear}
        >
          <p>
            <strong>Correct.</strong> A leaf pops and three small leaves drift off.
          </p>
        </Notice>
        <Notice tone="error" icon className={grove.nudge}>
          <p>
            <strong>Not quite.</strong> A gentle nudge, nothing alarming.
          </p>
        </Notice>
        <Notice tone="success" icon={<GrowingCheck />} className={grove.appear}>
          Lesson marked as done: the check draws in, a leaf unfurls.
        </Notice>
        <div className={`${ui.card} ${styles.countCard}`}>
          <span className={ui.eyebrow}>Count-up</span>
          <span className={styles.countValue}>
            <CountUp value={1240} formatted="1,240" />
          </span>
          <span className={ui.muted}>XP in total</span>
        </div>
        <div className={styles.barStack}>
          <Progress label="Fills on mount" value={72} />
          <MasteryBar label="Mastery fills on mount" value={0.45} />
        </div>
      </div>
      <VineDivider />
      <div className={`${ui.card} ${styles.watermarkCard}`}>
        <LeafWatermark />
        <span className={ui.eyebrow}>Leaf watermark</span>
        <p>Empty states and the "your path is growing" card carry a large, very faint leaf in a corner.</p>
      </div>

      <h2>Skill tree</h2>
      <p className={ui.muted}>
        The node set: four round states, and a mastered skill that needs review (a Clay ring and mark). An open node
        shows mastery so far as an arc; small marks say a lesson is being written or could not be written. Below, a
        small sample graph (the start in the middle, a hub per branch): select a node to light the route to it, drag
        one aside, choose a hub to frame its branch. A full-size sample is at /design/tree.
      </p>
      <div className={styles.nodeSet}>
        <NodeSample kind="done">Completed</NodeSample>
        <NodeSample kind="current" current>
          Current
        </NodeSample>
        <NodeSample kind="open">Next</NodeSample>
        <NodeSample kind="locked">Locked</NodeSample>
        <NodeSample kind="review">Needs review</NodeSample>
        <NodeSample kind="open" mastery={0.6}>
          Open, 60% mastery
        </NodeSample>
        <NodeSample kind="open" badge="writing">
          Lesson being written
        </NodeSample>
        <NodeSample kind="open" badge="failed">
          Lesson failed
        </NodeSample>
      </div>
      <LazyPathGraph contained path={SMALL_TREE.path} progress={SMALL_TREE.progress} />

      <h2>Review</h2>
      <p className={ui.muted}>
        The review screens' own pieces. A state is never colour alone: each has a shape or an icon, and words for
        screen readers.
      </p>
      <h3>Memory ring</h3>
      <div className={ui.row}>
        <MemoryRing value={0.62} label="Memory: 62%">
          <span className={review.ringNumber}>
            <CountUp value={62} formatted="62" />
            <span className={review.ringUnit}>%</span>
          </span>
          <span className={review.ringCaption}>memory</span>
        </MemoryRing>
        <MemoryRing value={0.94} label="Memory: 94%">
          <span className={review.ringNumber}>
            94<span className={review.ringUnit}>%</span>
          </span>
          <span className={review.ringCaption}>strong</span>
        </MemoryRing>
        <MemoryRing small value={null} label="Nothing studied yet">
          <span className={review.ringCaption}>empty</span>
        </MemoryRing>
      </div>
      <h3>Objective leaf</h3>
      <ul className={review.objectives}>
        {[
          { v: 0.97, due: false, text: "Filter rows with WHERE", meta: "97% remembered · next review 2 Dec 2026" },
          { v: 0.74, due: false, text: "Join two tables on a key", meta: "74% remembered · next review 15 Nov 2026" },
          { v: 0.41, due: true, text: "Tell an inner join from a left join", meta: "41% remembered" },
        ].map((o) => (
          <li key={o.text} className={review.objective}>
            <ObjectiveLeaf value={o.v} due={o.due} />
            <span>
              {o.text}
              <span className={review.objectiveMeta}>
                {o.meta}
                {o.due ? <span className={review.dueMark}>Due</span> : null}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <h3>Progress vine</h3>
      <ProgressVine
        label="Questions of this session"
        segments={[
          { id: "1", state: "first", label: "Question 1: right on the first try" },
          { id: "2", state: "second", label: "Question 2: right on the second try" },
          { id: "3", state: "revealed", label: "Question 3: answer shown" },
          { id: "4", state: "saved", label: "Question 4: answer saved" },
          { id: "5", state: "todo", current: true, label: "Question 5: this one" },
          { id: "6", state: "todo", label: "Question 6: to come" },
          { id: "7", state: "todo", reask: true, label: "Question 7: asked again, to come" },
          { id: "8", state: "first", reask: true, label: "Question 8: asked again, right on the first try" },
        ]}
      />
      <p className={ui.muted}>
        First try (moss, check), second try (pollen, 2), answer shown (clay, cross), saved without feedback (dot),
        the current question (outline), to come, and two re-asks (striped, with a loop until answered).
      </p>
      <h3>Answer options</h3>
      <div className={review.options}>
        <OptionButton letter="A" text="Idle: every row of the left table, matched or not" state="idle" />
        <OptionButton letter="B" text="Selected: only the rows that match in both tables" state="selected" />
        <OptionButton
          letter="C"
          text="Tried on the first try: every pair of rows"
          state="tried"
          disabled
          markLabel="Tried"
          note="That is a cross join: it has no join condition at all."
        />
        <OptionButton
          letter="D"
          text="Right, once resolved"
          state="right"
          disabled
          markLabel="Right answer"
          note="An inner join keeps a row only when the condition holds on both sides."
        />
        <OptionButton
          letter="E"
          text="Chosen and wrong, once resolved"
          state="wrong"
          disabled
          markLabel="Your answer"
          note="A left join would keep unmatched rows of the left table."
        />
        <OptionButton letter="F" text="Another option, once resolved" state="other" disabled />
      </div>

      <h2>Subscription program</h2>
      <p className={ui.muted}>
        The program a subscription works through (Claude Code, Codex): one state line, one next step. Static samples.
      </p>
      <div className={styles.grid} id="cli-samples">
        {CLI_SAMPLES.map(([label, sample]) => (
          <div key={label} className={ui.stack} data-sample={label}>
            <span className={ui.eyebrow}>{label}</span>
            <CliAccessView cli={sample} {...CLI_NOOP} />
          </div>
        ))}
      </div>

      <h2>Surfaces</h2>
      <div className={styles.grid}>
        <div className={ui.card}>
          <span className={ui.eyebrow}>Card</span>
          <p>Cards hold one thing: a skill, a lesson, a setting.</p>
        </div>
        <div className={ui.panel}>
          <span className={ui.eyebrow}>Panel</span>
          <p>Quiet panels hold side information: an estimate, a hint.</p>
        </div>
      </div>
    </section>
  );
}
