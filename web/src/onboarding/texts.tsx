// Words for the environment wizard: preset names, the recommendation's reasons (codes with values from
// yuo/setup/recommend.py), the cost estimate per option and the subscription consent texts.
import type { MessageDescriptor } from "@lingui/core";
import { msg } from "@lingui/core/macro";
import { Trans, useLingui } from "@lingui/react/macro";
import type { Preset, PresetEstimate, Reason } from "../api/client";
import { PlanUsageList } from "./PlanUsage";

export const PRESET_NAMES: Record<Preset, MessageDescriptor> = {
  claude: msg({ id: "wizard.preset.claude", message: "Claude (your Claude Code subscription)" }),
  codex: msg({ id: "wizard.preset.codex", message: "Codex (your ChatGPT subscription)" }),
  local: msg({ id: "wizard.preset.local", message: "Qwen 3.8 27B on this computer" }),
  open: msg({ id: "wizard.preset.open", message: "Qwen 3.8 27B through OpenRouter (pay per use)" }),
};

export const PRESET_SUMMARIES: Record<Preset, MessageDescriptor> = {
  claude: msg({
    id: "wizard.preset.claude.summary",
    message: "Yuo uses the Claude Code app on this computer, with the account you are signed in to there.",
  }),
  codex: msg({
    id: "wizard.preset.codex.summary",
    message: "Yuo uses the Codex app on this computer, with the account you are signed in to there.",
  }),
  local: msg({
    id: "wizard.preset.local.summary",
    message: "An open model runs on your own computer. Nothing you learn leaves it.",
  }),
  open: msg({
    id: "wizard.preset.open.summary",
    message: "The same open model, run by OpenRouter. You pay OpenRouter for what you use.",
  }),
};

/** The extra option after the server's: the learner's own key from a model vendor (never recommended). */
export const VENDOR_OPTION = "vendor";
export const VENDOR_OPTION_NAME = msg({ id: "wizard.option.vendor", message: "Your own API key from a model vendor" });
export const VENDOR_OPTION_SUMMARY = msg({
  id: "wizard.option.vendor.summary",
  message: "Anthropic, OpenAI, Google Gemini, Mistral, DeepSeek, xAI or Qwen; billed by the vendor.",
});

export const CLI_NAMES: Record<string, string> = { claude: "Claude Code", codex: "Codex" };

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** One reason in words; an unknown code (a newer server) is left out rather than shown raw. */
export function ReasonText({ reason }: { reason: Reason }) {
  const { i18n } = useLingui();
  const v = reason.values;
  const gbValue = num(v["gb"]);
  const gb = gbValue === null ? "?" : i18n.number(gbValue, { maximumFractionDigits: 0 });
  const min = i18n.number(num(v["min"]) ?? 0, { maximumFractionDigits: 0 });
  switch (reason.code) {
    case "no_subscription":
      return (
        <Trans id="wizard.reason.no-subscription">
          The Claude Code and Codex apps are not on this computer, so Yuo cannot use a subscription you already pay for.
        </Trans>
      );
    case "cli_found": {
      const app = CLI_NAMES[String(v["cli"])] ?? String(v["cli"]);
      return (
        <Trans id="wizard.reason.cli-found">
          The {app} app is on this computer, so Yuo can use your subscription instead of paying per use.
        </Trans>
      );
    }
    case "gpu_memory":
      return (
        <Trans id="wizard.reason.gpu-memory">
          Your graphics card has {gb} GB of memory. The model needs {min} GB, so it can run on this computer.
        </Trans>
      );
    case "unified_memory":
      return (
        <Trans id="wizard.reason.unified-memory">
          Your Mac has {gb} GB of memory shared with its graphics. The model needs {min} GB, so it can run on this
          computer.
        </Trans>
      );
    case "gpu_memory_short":
      return (
        <Trans id="wizard.reason.gpu-memory-short">
          Your graphics card has {gb} GB of memory. Running the model on this computer needs {min} GB.
        </Trans>
      );
    case "unified_memory_short":
      return (
        <Trans id="wizard.reason.unified-memory-short">
          Your Mac has {gb} GB of memory. Running the model on this computer needs {min} GB.
        </Trans>
      );
    case "no_gpu":
      return (
        <Trans id="wizard.reason.no-gpu">
          This computer has no graphics card that can run the model, so it runs elsewhere.
        </Trans>
      );
    case "local_free":
      return <Trans id="wizard.reason.local-free">Running the model on your computer costs nothing per use.</Trans>;
    case "api_billed":
      return (
        <Trans id="wizard.reason.api-billed">
          OpenRouter charges your OpenRouter account for each lesson and answer. You need an account with some credit.
        </Trans>
      );
    default:
      return null;
  }
}

/** What a typical path costs with this option, before it is chosen. */
export function OptionEstimate({ preset, estimate }: { preset: Preset; estimate: PresetEstimate }) {
  const { i18n } = useLingui();
  const usd = (v: number) => i18n.number(v, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const lessons = estimate.lessons;
  const low = usd(estimate.low_usd);
  const high = usd(estimate.high_usd);
  const subscription = preset === "claude" || preset === "codex";
  const billed = estimate.high_usd > 0;

  return (
    <span data-testid={`estimate-${preset}`}>
      {preset === "local" && !billed ? (
        <Trans id="wizard.estimate.local">For a typical {lessons}-lesson path: no cost per use.</Trans>
      ) : billed ? (
        <Trans id="wizard.estimate.billed">
          For a typical {lessons}-lesson path: about {low} to {high}, billed to you.
        </Trans>
      ) : subscription ? (
        <Trans id="wizard.estimate.plan">
          For a typical {lessons}-lesson path: no extra cost, it uses part of your plan's limits:
        </Trans>
      ) : (
        <Trans id="wizard.estimate.free">For a typical {lessons}-lesson path: no cost per use.</Trans>
      )}
      {subscription ? (
        <PlanUsageList rows={estimate.plan_usage} cli={preset === "claude" ? "claude-cli" : "codex-cli"} />
      ) : null}
      {estimate.missing.length > 0 ? (
        <>
          {" "}
          <Trans id="wizard.estimate.missing">Some steps have no known price yet, so it can cost more.</Trans>
        </>
      ) : null}
    </span>
  );
}

// The consent texts, the English original of yuo/setup/consent.py word for word. When the server
// has a newer version than the one translated here, the wizard shows the server's English text instead.
export const CONSENT_VERSION = 2;
export const CONSENT_TEXTS: Record<"claude" | "codex", MessageDescriptor> = {
  claude: msg({
    id: "wizard.consent.claude",
    message:
      "Yuo will run the Claude Code app installed on this computer, signed in with your own account, to write lessons and answer as your tutor. Yuo never reads or stores your Claude sign-in. This use counts against your subscription's limits, and Anthropic may bill use by third-party tools as extra usage; Yuo stops and tells you when it sees an extra-usage answer. You can switch to another model at any time in Settings.",
  }),
  codex: msg({
    id: "wizard.consent.codex",
    message:
      "Yuo will run the Codex app installed on this computer, signed in with your own account, to write lessons and answer as your tutor. Yuo never reads or stores your ChatGPT sign-in. This use counts against your plan's limits. You can switch to another model at any time in Settings.",
  }),
};

export const OS_NAMES: Record<string, string> = { windows: "Windows", macos: "macOS", linux: "Linux" };

export const SERVER_NAMES: Record<string, string> = {
  ollama: "Ollama",
  "lm-studio": "LM Studio",
  "llama.cpp": "llama.cpp",
};
