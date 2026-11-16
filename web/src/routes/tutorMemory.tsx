// Tutor memory: what the tutor remembers about the learner across
// conversations. Every entry shows where it came from (and the message it was noted in) and can be
// edited or deleted for good; the learner can add their own. The on/off switch is a setting.
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { createRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { Form } from "react-aria-components";
import type { MemoryKind, MemoryOut } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { SparkleIcon } from "../components/icons";
import { Button, ChoiceField, Field, Notice, PageHeader, ui } from "../components/ui";
import { useMemory, useMemoryMutations, useTutorName } from "../tutor/api";
import { useTutorActions, useTutorRefs } from "../tutor/context";
import { MEMORY_KINDS, MEMORY_SOURCES } from "../tutor/texts";
import { rootRoute } from "./root";
import styles from "./tutorMemory.module.css";

export const tutorMemoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tutor/memory",
  component: TutorMemoryPage,
});

const MEMORY_MAX = 300;
const KINDS: MemoryKind[] = ["goal", "preference", "misconception", "fact"];

type Mutations = ReturnType<typeof useMemoryMutations>;

function evidenceMessage(m: MemoryOut): string | null {
  const ref = m.evidence_ref;
  return ref && ref["kind"] === "message" && typeof ref["id"] === "string" ? (ref["id"] as string) : null;
}

function MemoryRow({ entry, m }: { entry: MemoryOut; m: Mutations }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const tutor = useTutorActions();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(entry.text);
  const [confirming, setConfirming] = useState(false);
  const kind = i18n._(MEMORY_KINDS[entry.kind]);
  const source = i18n._(MEMORY_SOURCES[entry.source]);
  const when = i18n.date(entry.updated_at, { dateStyle: "medium" });
  const evidence = evidenceMessage(entry);

  return (
    <li className={`${ui.card} ${styles.entry}`} data-kind={entry.kind}>
      <p className={styles.head}>
        <span className={styles.kind}>{kind}</span>
        <span className={ui.muted}>
          {source} · {when}
        </span>
      </p>
      {editing ? (
        <form
          className={ui.stack}
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) m.edit.mutate({ id: entry.id, text: text.trim() }, { onSuccess: () => setEditing(false) });
          }}
        >
          <Field
            label={t({ id: "tutor.memory.edit.label", message: "Change this entry" })}
            value={text}
            onChange={setText}
            maxLength={MEMORY_MAX}
            isRequired
          />
          <div className={ui.row}>
            <Button type="submit" small isDisabled={!text.trim() || m.edit.isPending}>
              <Trans id="tutor.memory.save">Save</Trans>
            </Button>
            <Button
              small
              variant="secondary"
              onPress={() => {
                setText(entry.text);
                setEditing(false);
              }}
            >
              <Trans id="tutor.memory.cancel">Cancel</Trans>
            </Button>
          </div>
        </form>
      ) : (
        <p className={styles.text}>{entry.text}</p>
      )}
      {!editing ? (
        <div className={ui.row}>
          {evidence ? (
            <Button small variant="secondary" onPress={() => tutor.open({ messageId: evidence, view: "all" })}>
              <Trans id="tutor.memory.evidence">Show where it was noted</Trans>
            </Button>
          ) : null}
          <Button
            small
            variant="secondary"
            onPress={() => setEditing(true)}
            aria-label={t({ id: "tutor.memory.edit.button.label", message: `Edit: ${entry.text}` })}
          >
            <Trans id="tutor.memory.edit">Edit</Trans>
          </Button>
          {confirming ? (
            <>
              <Button small isDisabled={m.remove.isPending} onPress={() => m.remove.mutate(entry.id)}>
                <Trans id="tutor.memory.delete.confirm">Delete for good</Trans>
              </Button>
              <Button small variant="secondary" onPress={() => setConfirming(false)}>
                <Trans id="tutor.memory.delete.keep">Keep it</Trans>
              </Button>
            </>
          ) : (
            <Button
              small
              variant="secondary"
              onPress={() => setConfirming(true)}
              aria-label={t({ id: "tutor.memory.delete.label", message: `Delete: ${entry.text}` })}
            >
              <Trans id="tutor.memory.delete">Delete</Trans>
            </Button>
          )}
        </div>
      ) : null}
    </li>
  );
}

function AddEntry({ m }: { m: Mutations }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const [kind, setKind] = useState<MemoryKind>("goal");
  const [text, setText] = useState("");
  return (
    <section className={`${ui.card} ${ui.stack}`} aria-labelledby="memory-add-title">
      <h2 id="memory-add-title" className={styles.sectionTitle}>
        <Trans id="tutor.memory.add.title">Tell the tutor something to remember</Trans>
      </h2>
      <Form
        className={ui.stack}
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          m.add.mutate({ kind, text: text.trim() }, { onSuccess: () => setText("") });
        }}
      >
        <ChoiceField
          label={t({ id: "tutor.memory.add.kind", message: "Kind" })}
          value={kind}
          onChange={setKind}
          choices={KINDS.map((k) => ({ value: k, label: i18n._(MEMORY_KINDS[k]) }))}
        />
        <Field
          label={t({ id: "tutor.memory.add.text", message: "What should it remember?" })}
          description={t({
            id: "tutor.memory.add.text.description",
            message: "For example: I am preparing for a job interview. At most 300 characters.",
          })}
          value={text}
          onChange={setText}
          maxLength={MEMORY_MAX}
          isRequired
          name="memory"
        />
        {m.add.isError ? <ErrorNotice error={m.add.error} /> : null}
        <div className={ui.row}>
          <Button type="submit" isDisabled={!text.trim() || m.add.isPending}>
            <Trans id="tutor.memory.add.submit">Add</Trans>
          </Button>
        </div>
      </Form>
    </section>
  );
}

function TutorMemoryPage() {
  useTutorRefs({ screen: "settings" });
  const memory = useMemory();
  const m = useMemoryMutations();
  const name = useTutorName(true);
  const { t } = useLingui();
  const tutorName = name ?? t({ id: "tutor.name.default", message: "Tutor" });
  const error = m.edit.error ?? m.remove.error;

  return (
    <section className={ui.stack}>
      <PageHeader title={<Trans id="tutor.memory.title">Tutor memory</Trans>} />
      <Notice icon={<SparkleIcon />}>
        <p>
          <Trans id="tutor.memory.intro">
            {tutorName} remembers lasting things about you, like your goals, how you like to learn and mistakes it
            noticed, so later answers fit you. Nothing else from your conversations is kept here. You can change or
            delete every entry; deleted entries are gone for good.
          </Trans>
        </p>
        <p>
          <Link to="/settings" hash="setting-tutor-memory">
            <Trans id="tutor.memory.setting.link">Turn tutor memory on or off in Settings</Trans>
          </Link>
        </p>
      </Notice>
      {error ? <ErrorNotice error={error} /> : null}
      {memory.isPending ? (
        <p className={ui.muted}>
          <Trans id="common.loading">Loading…</Trans>
        </p>
      ) : memory.isError ? (
        <ErrorNotice error={memory.error} />
      ) : memory.data.length === 0 ? (
        <p className={`${ui.panel} ${ui.muted}`}>
          <Trans id="tutor.memory.empty">Nothing remembered yet.</Trans>
        </p>
      ) : (
        <ul className={styles.list} aria-label={t({ id: "tutor.memory.list.label", message: "Remembered entries" })}>
          {memory.data.map((e) => (
            <MemoryRow key={`${e.id}:${e.updated_at}`} entry={e} m={m} />
          ))}
        </ul>
      )}
      <AddEntry m={m} />
    </section>
  );
}
