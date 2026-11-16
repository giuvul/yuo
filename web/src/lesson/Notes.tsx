// Learner notes on a lesson (class F, personal): anchored to a block (bid) or to the whole lesson.
import { Trans, useLingui } from "@lingui/react/macro";
import { useState } from "react";
import { Button as AriaButton } from "react-aria-components";
import type { NoteOut } from "../api/client";
import { useNoteMutations } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { NoteIcon } from "../components/icons";
import { Button, Field, ui } from "../components/ui";
import styles from "./notes.module.css";
import { mmss } from "../format";


export const NOTE_MAX = 5000;

type Mutations = ReturnType<typeof useNoteMutations>;

function NoteEditor({
  initial,
  label,
  onSave,
  onCancel,
  pending,
}: {
  initial: string;
  label: string;
  onSave: (text: string) => void;
  onCancel: () => void;
  pending: boolean;
}) {
  const { t } = useLingui();
  const [text, setText] = useState(initial);
  return (
    <form
      className={styles.editor}
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) onSave(text.trim());
      }}
    >
      <Field label={label} value={text} onChange={setText} maxLength={NOTE_MAX} multiline isRequired />
      <div className={ui.row}>
        <Button type="submit" small isDisabled={pending || !text.trim()}>
          <Trans id="notes.save">Save note</Trans>
        </Button>
        <Button type="button" small variant="secondary" onPress={onCancel}>
          {t({ id: "notes.cancel", message: "Cancel" })}
        </Button>
      </div>
    </form>
  );
}

function NoteItem({ note, m }: { note: NoteOut; m: Mutations }) {
  const { t } = useLingui();
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <li className={styles.note}>
        <NoteEditor
          initial={note.text}
          label={t({ id: "notes.edit.label", message: "Edit note" })}
          pending={m.edit.isPending}
          onCancel={() => setEditing(false)}
          onSave={(text) => m.edit.mutate({ id: note.id, text }, { onSuccess: () => setEditing(false) })}
        />
      </li>
    );
  }
  return (
    <li className={styles.note}>
      {note.t_s != null ? (
        <p className={styles.from}>
          <Trans id="notes.from-video">From the video at {mmss(note.t_s)}</Trans>
        </p>
      ) : null}
      <p className={styles.text}>{note.text}</p>
      <div className={ui.row}>
        <Button small variant="secondary" onPress={() => setEditing(true)}>
          <Trans id="notes.edit">Edit</Trans>
        </Button>
        <Button
          small
          variant="secondary"
          isDisabled={m.remove.isPending}
          onPress={() => m.remove.mutate(note.id)}
          aria-label={t({ id: "notes.delete.label", message: "Delete note" })}
        >
          <Trans id="notes.delete">Delete</Trans>
        </Button>
      </div>
    </li>
  );
}

/** Notes for one block (or the whole lesson when bid is null), with an "add" toggle. */
export function NotesFor({
  bid,
  notes,
  versionId,
  m,
  alwaysOpen,
}: {
  bid: string | null;
  notes: NoteOut[];
  versionId: string;
  m: Mutations;
  alwaysOpen?: boolean;
}) {
  const { t } = useLingui();
  const [adding, setAdding] = useState(false);
  const mine = notes.filter((n) => (n.bid ?? null) === bid);
  return (
    <div className={styles.notes} data-bid={bid ?? undefined}>
      {mine.length > 0 ? (
        <ul className={styles.list} aria-label={t({ id: "notes.list.label", message: "Your notes" })}>
          {mine.map((n) => (
            <NoteItem key={n.id} note={n} m={m} />
          ))}
        </ul>
      ) : null}
      {adding || alwaysOpen ? (
        <NoteEditor
          key={mine.length}
          initial=""
          label={
            bid
              ? t({ id: "notes.add.block.label", message: "Note on this part" })
              : t({ id: "notes.add.lesson.label", message: "Note on this lesson" })
          }
          pending={m.create.isPending}
          onCancel={() => setAdding(false)}
          onSave={(text) =>
            m.create.mutate({ text, bid, lesson_version_id: versionId }, { onSuccess: () => setAdding(false) })
          }
        />
      ) : (
        <div className={bid ? styles.addWrap : undefined}>
          <AriaButton className={`${styles.add} ${bid ? styles.addBlock : ""}`} onPress={() => setAdding(true)}>
            <NoteIcon size="1.05em" />
            {bid ? (
              <span className={styles.addText}>
                <Trans id="notes.add.block">Add a note here</Trans>
              </span>
            ) : (
              <Trans id="notes.add.lesson">Add a note</Trans>
            )}
          </AriaButton>
        </div>
      )}
    </div>
  );
}

export function NotesErrors({ m }: { m: Mutations }) {
  const error = m.create.error ?? m.edit.error ?? m.remove.error;
  return error ? <ErrorNotice error={error} /> : null;
}
