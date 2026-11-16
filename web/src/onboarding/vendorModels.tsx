// Choosing the models a vendor key or an OpenRouter key uses: the searchable lists, the estimate, the picker.
import { Trans, useLingui } from "@lingui/react/macro";
import { useId, useState, type ReactNode } from "react";
import {
  Button as AriaButton,
  ComboBox,
  Input,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Select,
  SelectValue,
  useFilter,
} from "react-aria-components";
import {
  ApiError,
  type ModelSource,
  type OpenRouterModel,
  type PresetEstimate,
  type ProviderOut,
  type SetupOut,
} from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { CoinsIcon } from "../components/icons";
import { Button, Notice, ui } from "../components/ui";
import itemStyles from "../items/items.module.css";
import {
  useChooseVendorModels,
  useOpenRouterModels,
  useVendorEstimate,
  useVendorModels,
} from "./api";
import styles from "./onboarding.module.css";

/** Warnings the server returned with the new bindings (untested models, the same model checking itself). */
export function SetupWarnings({ setup }: { setup: SetupOut }) {
  if (setup.warnings.length === 0) return null;
  return (
    <Notice tone="warning">
      <p>
        <strong>
          <Trans id="wizard.access.warnings">Please note</Trans>
        </strong>
      </p>
      <ul>
        {setup.warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </Notice>
  );
}

const VENDOR_ESTIMATE_LESSONS = 20;

// --- the models ------------------------------------------------------------------------------------

/** Whose models are chosen: a vendor (ProviderOut) or OpenRouter. */
export type Source = Pick<ProviderOut, "label" | "suggested_main" | "suggested_reviewer"> & { id: ModelSource };

/** A model in a long list: searchable by its name and id, with a line of detail (prices). */
type ModelOption = { id: string; name: string; detail?: string };

/** Lists longer than this get a search field instead of a plain list. */
const SEARCH_FROM = 40;

function ModelSearch({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: ModelOption[];
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useLingui();
  const { contains } = useFilter({ sensitivity: "base" });
  return (
    <ComboBox
      className={ui.field}
      defaultItems={options}
      selectedKey={value || null}
      onSelectionChange={(k) => k !== null && onChange(String(k))}
      defaultFilter={contains}
      menuTrigger="focus"
      isRequired
    >
      <Label className={ui.label}>{label}</Label>
      <div className={styles.comboRow}>
        <Input
          className={ui.input}
          placeholder={t({ id: "vendor.models.search", message: "Type to search, for example qwen or claude" })}
        />
        <AriaButton className={`${ui.button} ${ui.secondary} ${ui.small}`}>
          <span aria-hidden="true">▾</span>
        </AriaButton>
      </div>
      <Popover className={`${itemStyles.popover} ${styles.modelPopover}`}>
        <ListBox className={itemStyles.listbox}>
          {(o: ModelOption) => (
            <ListBoxItem id={o.id} className={`${itemStyles.option} ${styles.modelOption}`} textValue={`${o.name} ${o.id}`}>
              <span className={styles.modelName}>{o.name}</span>
              {o.detail ? <span className={styles.modelDetail}>{o.detail}</span> : null}
            </ListBoxItem>
          )}
        </ListBox>
      </Popover>
    </ComboBox>
  );
}

function ModelSelect({
  label,
  models,
  value,
  onChange,
}: {
  label: string;
  models: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useLingui();
  return (
    <Select
      className={ui.field}
      selectedKey={value || null}
      onSelectionChange={(k) => k !== null && onChange(String(k))}
      placeholder={t({ id: "vendor.models.placeholder", message: "Choose a model" })}
      isRequired
    >
      <Label className={ui.label}>{label}</Label>
      <AriaButton className={`${ui.input} ${itemStyles.selectButton} ${styles.modelButton}`}>
        <SelectValue className={styles.modelValue} />
        <span aria-hidden="true">▾</span>
      </AriaButton>
      <Popover className={`${itemStyles.popover} ${styles.modelPopover}`}>
        <ListBox className={itemStyles.listbox}>
          {models.map((m) => (
            <ListBoxItem key={m} id={m} className={`${itemStyles.option} ${styles.modelOption}`} textValue={m}>
              {m}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </Select>
  );
}

/** The billed range for a typical path with these models; a note when some prices are not known. */
function VendorEstimateText({ estimate, vendor }: { estimate: PresetEstimate; vendor: string }) {
  const { i18n } = useLingui();
  const usd = (v: number) => i18n.number(v, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const lessons = estimate.lessons;
  const low = usd(estimate.low_usd);
  const high = usd(estimate.high_usd);
  if (estimate.high_usd <= 0 && estimate.missing.length > 0) {
    return (
      <p>
        <Trans id="vendor.estimate.unknown">
          Yuo does not know the prices of these models yet, so it cannot estimate a typical path. {vendor} bills you
          for what you use.
        </Trans>
      </p>
    );
  }
  return (
    <>
      <p>
        <Trans id="vendor.estimate.billed">
          For a typical {lessons}-lesson path: about {low} to {high}, billed to you by {vendor}.
        </Trans>
      </p>
      {estimate.missing.length > 0 ? (
        <p className={ui.muted}>
          <Trans id="vendor.estimate.missing">Some steps have no known price yet, so it can cost more.</Trans>
        </p>
      ) : null}
    </>
  );
}

function VendorEstimate({ provider, main, reviewer }: { provider: Source; main: string; reviewer: string }) {
  const estimate = useVendorEstimate(provider.id, main, reviewer, VENDOR_ESTIMATE_LESSONS);
  return (
    <div role="status" data-testid="vendor-estimate" className={`${ui.panel} ${styles.estimatePanel}`}>
      <CoinsIcon className={styles.estimateIcon} />
      <div className={styles.estimateBody}>
        {estimate.isFetching && !estimate.data ? (
          <p className={ui.muted}>
            <Trans id="vendor.estimate.loading">Working out the cost…</Trans>
          </p>
        ) : estimate.isError ? (
          <p className={ui.muted}>
            <Trans id="vendor.estimate.unavailable">The cost estimate is not available right now.</Trans>
          </p>
        ) : estimate.data ? (
          <VendorEstimateText estimate={estimate.data} vendor={provider.label} />
        ) : null}
      </div>
    </div>
  );
}

const suggested = (model: string | null, models: string[]) => (model && models.includes(model) ? model : "");

/** The two models, the estimate for a typical path and "apply" (POST /api/setup/vendor-models). */
function VendorModelPicker({
  provider,
  models,
  options,
  applyLabel,
  once,
  onApplied,
}: {
  provider: Source;
  models: string[];
  /** names and details for a long list (OpenRouter); without them the ids are listed */
  options?: ModelOption[];
  applyLabel: ReactNode;
  /** hide the apply button after it worked (the wizard moves on with Next) */
  once?: boolean;
  onApplied?: (setup: SetupOut) => void;
}) {
  const { t } = useLingui();
  const choose = useChooseVendorModels();
  const sorted = [...models].sort((a, b) => a.localeCompare(b));
  const [main, setMain] = useState(() => suggested(provider.suggested_main, models));
  const [reviewer, setReviewer] = useState(() => suggested(provider.suggested_reviewer, models));
  const [applied, setApplied] = useState<SetupOut | null>(null);
  const explainId = useId();
  const vendor = provider.label;
  const change = (set: (v: string) => void) => (v: string) => {
    set(v);
    setApplied(null);
    choose.reset();
  };

  return (
    <div className={ui.stack} role="group" aria-describedby={explainId}>
      <p id={explainId}>
        <Trans id="vendor.models.explain">
          Choose the models from {vendor} that Yuo uses. A different model for checking catches more mistakes than
          the same model checking its own work.
        </Trans>
      </p>
      {[
        { label: t({ id: "vendor.models.main", message: "Model that writes lessons and answers" }), value: main, set: setMain },
        { label: t({ id: "vendor.models.reviewer", message: "Model that checks lessons" }), value: reviewer, set: setReviewer },
      ].map((f) =>
        options || sorted.length > SEARCH_FROM ? (
          <ModelSearch
            key={f.label}
            label={f.label}
            options={options ?? sorted.map((m) => ({ id: m, name: m }))}
            value={f.value}
            onChange={change(f.set)}
          />
        ) : (
          <ModelSelect key={f.label} label={f.label} models={sorted} value={f.value} onChange={change(f.set)} />
        ),
      )}
      {main && reviewer ? (
        <VendorEstimate provider={provider} main={main} reviewer={reviewer} />
      ) : (
        <p className={ui.muted}>
          <Trans id="vendor.models.choose-both">Choose both models to see what a typical path costs.</Trans>
        </p>
      )}
      {applied ? (
        <Notice tone="success" role="status">
          <Trans id="vendor.models.applied">Done. Yuo uses these models from {vendor} from now on.</Trans>
        </Notice>
      ) : null}
      {applied ? <SetupWarnings setup={applied} /> : null}
      {choose.isError ? <ErrorNotice error={choose.error} /> : null}
      {applied && once ? null : (
        <div className={ui.row}>
          <Button
            isDisabled={!main || !reviewer || choose.isPending}
            onPress={() =>
              choose.mutate(
                { provider: provider.id, main, reviewer },
                {
                  onSuccess: (setup) => {
                    setApplied(setup);
                    onApplied?.(setup);
                  },
                },
              )
            }
          >
            {choose.isPending ? <Trans id="vendor.models.applying">Saving…</Trans> : applyLabel}
          </Button>
        </div>
      )}
    </div>
  );
}

/** The models the saved key may use (asked again, or from the key check just made), then the picker. */
export function VendorModels(props: {
  provider: ProviderOut;
  applyLabel: ReactNode;
  once?: boolean;
  onApplied?: (setup: SetupOut) => void;
}) {
  const { provider } = props;
  const models = useVendorModels(provider.id);
  const vendor = provider.label;
  if (models.isPending) {
    return (
      <p className={ui.muted} role="status">
        <Trans id="vendor.models.loading">Asking {vendor} which models your key can use…</Trans>
      </p>
    );
  }
  if (models.isError) {
    const unreachable = models.error instanceof ApiError && models.error.status === 502;
    return unreachable ? (
      <Notice tone="error">
        <Trans id="vendor.models.unreachable">
          Yuo could not reach {vendor} to list the models. Check your internet connection, then try again.
        </Trans>
      </Notice>
    ) : (
      <ErrorNotice error={models.error} />
    );
  }
  if (models.data.models.length === 0) {
    return (
      <Notice tone="warning" role="status">
        <Trans id="vendor.models.none">
          {vendor} lists no models for this key. Check the key's permissions on the vendor's website, or use another
          key.
        </Trans>
      </Notice>
    );
  }
  return <VendorModelPicker key={models.data.models.join("\n")} {...props} models={models.data.models} />;
}

/** Settings > OpenRouter: any of OpenRouter's text models, searched by name, with their prices. Starts from
the models in use when they run through OpenRouter (the key alone left the model fixed). */
export function OpenRouterModels({ current }: { current: { main?: string; reviewer?: string } }) {
  const { i18n, t } = useLingui();
  const models = useOpenRouterModels();
  if (models.isPending) {
    return (
      <p className={ui.muted} role="status">
        <Trans id="openrouter.models.loading">Getting OpenRouter's list of models…</Trans>
      </p>
    );
  }
  if (models.isError) {
    return models.error instanceof ApiError && models.error.status === 502 ? (
      <Notice tone="error">
        <Trans id="openrouter.models.unreachable">
          Yuo could not reach OpenRouter to list its models. Check your internet connection, then try again.
        </Trans>
      </Notice>
    ) : (
      <ErrorNotice error={models.error} />
    );
  }
  const usd = (v: number | null | undefined) =>
    v == null ? "?" : i18n.number(v, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const list = [...models.data.models].sort((a, b) => a.name.localeCompare(b.name));
  const options: ModelOption[] = list.map((m: OpenRouterModel) => {
    const input = usd(m.in_usd_per_m);
    const output = usd(m.out_usd_per_m);
    const id = m.id;
    return {
      id,
      name: m.name,
      detail: t({
        id: "openrouter.models.detail",
        message: `${id} · ${input} in, ${output} out per million tokens`,
      }),
    };
  });
  const ids = list.map((m) => m.id);
  const source: Source = {
    id: "openrouter",
    label: "OpenRouter",
    suggested_main: current.main ?? null,
    suggested_reviewer: current.reviewer ?? null,
  };
  return (
    <VendorModelPicker
      key={ids.length}
      provider={source}
      models={ids}
      options={options}
      applyLabel={<Trans id="settings.ai.vendor.apply">Use these models</Trans>}
    />
  );
}
