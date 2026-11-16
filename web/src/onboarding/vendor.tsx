// A learner's own API key from a model vendor (yuo/setup/providers.py): the key is checked by listing the vendor's
// models (free), then the learner picks the model that writes lessons and answers and the one that checks lessons,
// sees the cost of a typical path and applies them. Shared by the wizard's "AI access" step and Settings.
import { Trans, useLingui } from "@lingui/react/macro";
import { useId, useState } from "react";
import {
  FieldError,
  Input,
  Label,
  Text,
  TextField,
} from "react-aria-components";
import {
  ApiError,
  type ProviderOut,
  type SetupOut,
} from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { KeyIcon } from "../components/icons";
import { Button, ChoiceCards, Notice, ui } from "../components/ui";
import {
  useRemoveVendorKey,
  useSetVendorKey,
} from "./api";
import styles from "./onboarding.module.css";
import { VendorModels } from "./vendorModels";

// --- the key ---------------------------------------------------------------------------------------

/** Enter (or replace) a vendor key; it is checked with the vendor, then never shown again. */
function VendorKeyForm({
  provider,
  replacing,
  onSaved,
  onCancel,
}: {
  provider: ProviderOut;
  replacing?: boolean;
  onSaved?: (models: string[]) => void;
  onCancel?: () => void;
}) {
  const { t } = useLingui();
  const save = useSetVendorKey();
  const [key, setKey] = useState("");
  const vendor = provider.label;
  const prefix = provider.key_prefix;
  const error = save.error;
  const refused = error instanceof ApiError && error.status === 400;
  const malformed = error instanceof ApiError && error.status === 422;
  const unreachable = error instanceof ApiError && error.status === 502;
  const fieldError = refused
    ? t({
        id: "vendor.key.refused",
        message: `${vendor} did not accept this key. Check that you copied all of it and that it is still active.`,
      })
    : malformed
      ? prefix
        ? t({ id: "vendor.key.format", message: `That does not look like a key from ${vendor}. It starts with ${prefix}.` })
        : t({ id: "vendor.key.format.any", message: `That does not look like a key from ${vendor}.` })
      : undefined;

  return (
    <div className={ui.stack}>
      <form
        className={ui.stack}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          const value = key.trim();
          if (!value) return;
          save.mutate(
            { provider: provider.id, key: value },
            {
              onSuccess: (data) => {
                setKey("");
                onSaved?.(data.models);
              },
            },
          );
        }}
      >
        <p>
          <Trans id="vendor.key.intro">
            Create a key on the vendor's website, then paste it here. Yuo checks it by asking {vendor} for its list
            of models, which costs nothing, and keeps it on this computer.
          </Trans>{" "}
          <a href={provider.keys_url} target="_blank" rel="noopener noreferrer">
            <Trans id="vendor.key.link">Create a key on the {vendor} website (opens in a new tab)</Trans>
          </a>
        </p>
        <TextField
          type="password"
          value={key}
          onChange={(v) => {
            setKey(v);
            if (save.isError) save.reset();
          }}
          autoComplete="off"
          isInvalid={!!fieldError}
          isRequired
          className={ui.field}
          spellCheck="false"
        >
          <Label className={ui.label}>
            {replacing
              ? t({ id: "vendor.key.label.replace", message: `New ${vendor} key` })
              : t({ id: "vendor.key.label", message: `${vendor} key` })}
          </Label>
          <Input className={ui.input} autoCapitalize="none" autoCorrect="off" />
          {prefix ? (
            <Text slot="description" className={ui.description}>
              {t({ id: "vendor.key.hint", message: `It starts with ${prefix}.` })}
            </Text>
          ) : null}
          <FieldError className={ui.fieldError}>{fieldError}</FieldError>
        </TextField>
        <div className={ui.row}>
          <Button type="submit" isDisabled={!key.trim() || save.isPending}>
            {save.isPending ? (
              <Trans id="vendor.key.checking">Checking the key…</Trans>
            ) : (
              <Trans id="vendor.key.check">Check key</Trans>
            )}
          </Button>
          {onCancel ? (
            <Button variant="secondary" onPress={onCancel}>
              <Trans id="vendor.key.cancel">Cancel</Trans>
            </Button>
          ) : null}
        </div>
      </form>
      {unreachable ? (
        <Notice tone="error">
          <Trans id="vendor.key.unreachable">
            Yuo could not reach {vendor} to check the key. Check your internet connection, then try again.
          </Trans>
        </Notice>
      ) : error && !refused && !malformed ? (
        <ErrorNotice error={error} />
      ) : null}
    </div>
  );
}

// --- the wizard ------------------------------------------------------------------------------------

/** A key (unless one is saved), then the models: the wizard's flow for one vendor. */
function VendorSetup({
  provider,
  onApplied,
}: {
  provider: ProviderOut;
  onApplied: (setup: SetupOut) => void;
}) {
  const [checked, setChecked] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const vendor = provider.label;
  const needKey = replacing || (!provider.connected && !checked);
  if (needKey) {
    return (
      <VendorKeyForm
        provider={provider}
        replacing={replacing}
        onSaved={() => {
          setChecked(true);
          setReplacing(false);
        }}
        onCancel={replacing ? () => setReplacing(false) : undefined}
      />
    );
  }
  return (
    <div className={ui.stack}>
      {checked ? (
        <Notice tone="success" role="status">
          <Trans id="vendor.key.saved">{vendor} accepted the key. It is saved on this computer and is not shown again.</Trans>
        </Notice>
      ) : (
        <div className={ui.row}>
          <p>
            <Trans id="vendor.key.set">A key for {vendor} is saved on this computer.</Trans>
          </p>
          <Button variant="secondary" small onPress={() => setReplacing(true)}>
            <Trans id="vendor.key.other">Use a different key</Trans>
          </Button>
        </div>
      )}
      <VendorModels
        provider={provider}
        once
        applyLabel={<Trans id="wizard.access.apply">Use this and continue</Trans>}
        onApplied={onApplied}
      />
    </div>
  );
}

/** The wizard's "AI access" step for "your own API key": choose the vendor, then its key and models. */
export function VendorAccess({
  providers,
  onApplied,
}: {
  providers: ProviderOut[];
  onApplied: (setup: SetupOut) => void;
}) {
  const { t } = useLingui();
  const [chosen, setChosen] = useState<string | null>(() => providers.find((p) => p.connected)?.id ?? null);
  const provider = providers.find((p) => p.id === chosen) ?? null;
  const saved = t({ id: "vendor.choose.saved", message: "a key is saved" });
  return (
    <div className={ui.stack}>
      <ChoiceCards
        label={t({ id: "vendor.choose.label", message: "Model vendor" })}
        choices={providers.map((p) => ({
          value: p.id,
          label: p.label,
          description: p.connected ? saved : undefined,
          icon: p.connected ? <KeyIcon /> : undefined,
        }))}
        value={chosen}
        onChange={setChosen}
        compact
      />
      {provider ? <VendorSetup key={provider.id} provider={provider} onApplied={onApplied} /> : null}
    </div>
  );
}

// --- Settings --------------------------------------------------------------------------------------

type Open = { id: string; mode: "key" | "models" | "remove" } | null;

/** Settings > AI access: each vendor with its state; add, replace or remove a key, use its models. */
export function VendorKeys({ providers }: { providers: ProviderOut[] }) {
  const [open, setOpen] = useState<Open>(null);
  return (
    <div className={ui.stack}>
      <h4 className={styles.partTitle}>
        <Trans id="settings.ai.vendors.heading">Model vendors</Trans>
      </h4>
      <p>
        <Trans id="settings.ai.vendors.intro">
          Use a key from a model vendor. The vendor bills you for what you use. Keys are kept on this computer and
          never shown again.
        </Trans>
      </p>
      <ul className={`${styles.plainList} ${styles.vendorList}`}>
        {providers.map((p) => (
          <li key={p.id} className={styles.vendorItem}>
            <VendorRow
              provider={p}
              mode={open?.id === p.id ? open.mode : null}
              setMode={(mode) => setOpen(mode ? { id: p.id, mode } : null)}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

function VendorRow({
  provider,
  mode,
  setMode,
}: {
  provider: ProviderOut;
  mode: "key" | "models" | "remove" | null;
  setMode: (mode: "key" | "models" | "remove" | null) => void;
}) {
  const { t } = useLingui();
  const remove = useRemoveVendorKey();
  const confirmId = useId();
  const vendor = provider.label;
  const connected = provider.connected;
  return (
    <div className={ui.stack}>
      <p>
        <strong>{vendor}:</strong>{" "}
        {connected ? (
          <Trans id="settings.ai.vendor.connected">a key is saved</Trans>
        ) : (
          <span className={ui.muted}>
            <Trans id="settings.ai.vendor.none">no key</Trans>
          </span>
        )}
      </p>
      {mode === "key" ? (
        <VendorKeyForm
          provider={provider}
          replacing={connected}
          onSaved={() => setMode("models")}
          onCancel={() => setMode(null)}
        />
      ) : mode === "models" ? (
        <>
          <VendorModels
            provider={provider}
            applyLabel={<Trans id="settings.ai.vendor.apply">Use these models</Trans>}
          />
          <div className={ui.row}>
            <Button variant="secondary" onPress={() => setMode(null)}>
              <Trans id="settings.ai.vendor.close">Close</Trans>
            </Button>
          </div>
        </>
      ) : mode === "remove" ? (
        <div className={ui.stack} role="group" aria-labelledby={confirmId}>
          <p id={confirmId}>
            <Trans id="settings.ai.vendor.remove.confirm-text">
              Remove the {vendor} key? Models from {vendor} stop working until you add a key again.
            </Trans>
          </p>
          <div className={ui.row}>
            <Button
              isDisabled={remove.isPending}
              onPress={() => remove.mutate(provider.id, { onSuccess: () => setMode(null) })}
            >
              <Trans id="settings.ai.key.remove.confirm">Yes, remove the key</Trans>
            </Button>
            <Button variant="secondary" onPress={() => setMode(null)}>
              <Trans id="settings.ai.key.remove.cancel">Keep it</Trans>
            </Button>
          </div>
        </div>
      ) : (
        <div className={ui.row}>
          {connected ? (
            <>
              <Button
                variant="secondary"
                small
                aria-label={t({ id: "settings.ai.vendor.use.label", message: `Use this vendor's models: ${vendor}` })}
                onPress={() => setMode("models")}
              >
                <Trans id="settings.ai.vendor.use">Use this vendor's models</Trans>
              </Button>
              <Button
                variant="secondary"
                small
                aria-label={t({ id: "settings.ai.vendor.replace.label", message: `Replace the key: ${vendor}` })}
                onPress={() => setMode("key")}
              >
                <Trans id="settings.ai.key.replace">Replace the key</Trans>
              </Button>
              <Button
                variant="secondary"
                small
                aria-label={t({ id: "settings.ai.vendor.remove.label", message: `Remove the key: ${vendor}` })}
                onPress={() => setMode("remove")}
              >
                <Trans id="settings.ai.key.remove">Remove the key</Trans>
              </Button>
            </>
          ) : (
            <Button
              variant="secondary"
              small
              aria-label={t({ id: "settings.ai.vendor.add.label", message: `Add a key: ${vendor}` })}
              onPress={() => setMode("key")}
            >
              <Trans id="settings.ai.vendor.add">Add a key</Trans>
            </Button>
          )}
        </div>
      )}
      {remove.isError ? <ErrorNotice error={remove.error} /> : null}
    </div>
  );
}
