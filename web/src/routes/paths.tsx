import { Trans, useLingui } from "@lingui/react/macro";
import { createRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  Button as AriaButton,
  Dialog as AriaDialog,
  Form,
  Heading,
  Menu,
  MenuItem,
  MenuTrigger,
  Modal,
  ModalOverlay,
  Popover,
  Separator,
} from "react-aria-components";
import type { PathSummary } from "../api/client";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { useDeletePath, usePaths, useProgress, useUpdatePath } from "../api/hooks";
import { ErrorNotice } from "../components/ErrorNotice";
import { BookmarkIcon, CloseIcon, MoreIcon, PencilIcon, PlusIcon, SproutIcon, UploadIcon } from "../components/icons";
import { LeafWatermark } from "../components/Grove";
import { Seedling } from "../components/illustrations";
import { Badge, Button, ButtonLink, Field, Notice, Progress, ui, Waiting } from "../components/ui";
import { AiReadyWarning } from "../onboarding/AiReady";
import { useOnboarding } from "../onboarding/api";
import { DifficultyLabel, PathStatusLabel } from "../components/labels";
import { rootRoute } from "./root";
import styles from "./paths.module.css";
import { useTutorRefs } from "../tutor/context";

export const pathsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/paths",
  component: PathsPage,
});

/** Skills mastered of all skills, from the path's progress (nothing while it loads or has no tree yet). */
function PathProgress({ pathId, title }: { pathId: string; title: string }) {
  const { t } = useLingui();
  const progress = useProgress(pathId);
  const skills = Object.values(progress.data?.skills ?? {});
  if (skills.length === 0) return null;
  const mastered = skills.filter((s) => s.state === "mastered").length;
  const total = skills.length;
  return (
    <span className={styles.progress}>
      <Progress
        value={mastered}
        max={total}
        showValue={false}
        label={t({ id: "home.path.progress.label", message: `Skills mastered: ${title}` })}
      />
      <span className={styles.progressText}>
        <Trans id="home.path.progress">
          {mastered} of {total} skills mastered
        </Trans>
      </span>
    </span>
  );
}

function PathCard({ path }: { path: PathSummary }) {
  const { i18n } = useLinguiRuntime();
  const created = i18n.date(new Date(path.created_at), { dateStyle: "medium" });
  return (
    <div className={styles.pathItem}>
      <Link to="/paths/$pathId" params={{ pathId: path.id }} className={styles.pathCard} data-status={path.status}>
        <span className={styles.pathIcon}>
          <SproutIcon size={24} />
        </span>
        <span className={styles.pathBody}>
          <span className={styles.pathTitle}>{path.title}</span>
          <span className={styles.meta}>
            {path.subject && path.subject !== path.title ? <>{path.subject} · </> : null}
            <DifficultyLabel value={path.difficulty} /> · <Trans id="home.path.created">started {created}</Trans>
          </span>
          <PathProgress pathId={path.id} title={path.title} />
        </span>
        <span className={styles.pathSide}>
          <Badge tone={path.status === "active" ? "success" : undefined}>
            <PathStatusLabel value={path.status} />
          </Badge>
        </span>
      </Link>
      <PathMenu path={path} />
    </div>
  );
}

type Dialog = "edit" | "delete" | null;

/** What can be done to a path from the list: edit its name and goal, archive or restore it, delete it. */
function PathMenu({ path }: { path: PathSummary }) {
  const { t } = useLingui();
  const [open, setOpen] = useState<Dialog>(null);
  const update = useUpdatePath();
  const archived = path.status === "archived";
  return (
    <>
      <MenuTrigger>
        <AriaButton
          className={styles.menuButton}
          aria-label={t({ id: "paths.menu", message: `Actions for ${path.title}` })}
        >
          <MoreIcon />
        </AriaButton>
        <Popover className={styles.menuPopover} placement="bottom end">
          <Menu
            className={styles.menu}
            aria-label={t({ id: "paths.menu", message: `Actions for ${path.title}` })}
            disabledKeys={path.status === "draft" ? ["archive"] : []}
            onAction={(key) => {
              if (key === "edit") setOpen("edit");
              else if (key === "delete") setOpen("delete");
              else if (key === "archive")
                update.mutate({ pathId: path.id, body: { status: archived ? "active" : "archived" } });
            }}
          >
            <MenuItem id="edit" className={styles.menuItem} textValue={t({ id: "paths.edit", message: "Rename or edit" })}>
              <PencilIcon />
              <Trans id="paths.edit">Rename or edit</Trans>
            </MenuItem>
            <MenuItem
              id="archive"
              className={styles.menuItem}
              textValue={
                archived
                  ? t({ id: "paths.restore", message: "Bring back" })
                  : t({ id: "paths.archive", message: "Archive" })
              }
            >
              <BookmarkIcon />
              {archived ? <Trans id="paths.restore">Bring back</Trans> : <Trans id="paths.archive">Archive</Trans>}
            </MenuItem>
            <Separator className={styles.menuSeparator} />
            <MenuItem
              id="delete"
              className={`${styles.menuItem} ${styles.menuDanger}`}
              textValue={t({ id: "paths.delete", message: "Delete" })}
            >
              <CloseIcon />
              <Trans id="paths.delete">Delete</Trans>
            </MenuItem>
          </Menu>
        </Popover>
      </MenuTrigger>
      <ModalOverlay
        className={styles.overlay}
        isDismissable
        isOpen={open !== null}
        onOpenChange={(o) => (o ? null : setOpen(null))}
      >
        <Modal className={styles.modal}>
          <AriaDialog className={styles.dialog}>
            {open === "edit" ? (
              <EditPath path={path} onClose={() => setOpen(null)} />
            ) : open === "delete" ? (
              <DeletePath path={path} onClose={() => setOpen(null)} />
            ) : null}
          </AriaDialog>
        </Modal>
      </ModalOverlay>
      {update.isError ? <ErrorNotice error={update.error} /> : null}
    </>
  );
}

function EditPath({ path, onClose }: { path: PathSummary; onClose: () => void }) {
  const { t } = useLingui();
  const update = useUpdatePath();
  const [title, setTitle] = useState(path.title);
  const [goal, setGoal] = useState(path.goal ?? "");
  return (
    <Form
      className={ui.stack}
      onSubmit={(e) => {
        e.preventDefault();
        const body: { title?: string; goal?: string } = {};
        if (title.trim() && title.trim() !== path.title) body.title = title.trim();
        if (goal.trim() && goal.trim() !== path.goal) body.goal = goal.trim();
        if (!body.title && !body.goal) return onClose();
        update.mutate({ pathId: path.id, body }, { onSuccess: onClose });
      }}
    >
      <Heading slot="title" className={styles.dialogTitle}>
        <Trans id="paths.edit.title">Edit the path</Trans>
      </Heading>
      <Field
        label={t({ id: "paths.edit.name", message: "Name" })}
        value={title}
        onChange={setTitle}
        isRequired
        maxLength={200}
        name="title"
      />
      <Field
        label={t({ id: "paths.edit.goal", message: "Goal" })}
        description={t({
          id: "paths.edit.goal.description",
          message: "What you want to be able to do. Lessons written from now on follow it.",
        })}
        value={goal}
        onChange={setGoal}
        multiline
        maxLength={2000}
        name="goal"
      />
      {update.isError ? <ErrorNotice error={update.error} /> : null}
      <div className={styles.dialogActions}>
        <Button variant="secondary" onPress={onClose}>
          <Trans id="confirm.cancel">Cancel</Trans>
        </Button>
        <Button type="submit" isDisabled={update.isPending || !title.trim()}>
          <Trans id="paths.edit.save">Save</Trans>
        </Button>
      </div>
    </Form>
  );
}

function DeletePath({ path, onClose }: { path: PathSummary; onClose: () => void }) {
  const remove = useDeletePath();
  const title = path.title;
  return (
    <div className={ui.stack}>
      <Heading slot="title" className={styles.dialogTitle}>
        <Trans id="paths.delete.title">Delete “{title}”?</Trans>
      </Heading>
      <p>
        <Trans id="paths.delete.body">
          Its lessons, questions, files and courses go, with everything you answered and wrote in it. This cannot
          be undone. To keep it out of sight instead, archive it.
        </Trans>
      </p>
      {remove.isError ? <ErrorNotice error={remove.error} /> : null}
      <div className={styles.dialogActions}>
        <Button variant="secondary" onPress={onClose} isDisabled={remove.isPending}>
          <Trans id="confirm.cancel">Cancel</Trans>
        </Button>
        <Button autoFocus isDisabled={remove.isPending} onPress={() => remove.mutate(path.id, { onSuccess: onClose })}>
          {remove.isPending ? (
            <Trans id="paths.delete.pending">Deleting…</Trans>
          ) : (
            <Trans id="paths.delete.confirm">Delete the path</Trans>
          )}
        </Button>
      </div>
    </div>
  );
}

/** Every path, with how far along it is; also what Home shows before the first path. */
export function PathsPage() {
  useTutorRefs({ screen: "home" });
  const paths = usePaths();
  const onboarding = useOnboarding();
  const unfinished = onboarding.data !== undefined && !onboarding.data.done && onboarding.data.has_path;
  // the actions sit in the header once there are paths (or the list failed); an empty list has its own
  const headerActions = paths.isError || (paths.data?.length ?? 0) > 0;

  return (
    <section className={ui.stack}>
      <div className={styles.titleRow}>
        <h1 className={ui.pageTitle}>
          <Trans id="home.title">Your paths</Trans>
        </h1>
        {headerActions ? (
          <div className={styles.actions}>
            <ButtonLink to="/import" variant="secondary">
              <UploadIcon size="1.1em" />
              <Trans id="home.import">Import a path</Trans>
            </ButtonLink>
            <ButtonLink to="/paths/new">
              <PlusIcon size="1.1em" />
              <Trans id="home.new-path">New path</Trans>
            </ButtonLink>
          </div>
        ) : null}
      </div>

      {unfinished ? (
        <Notice>
          <Trans id="home.finish-setup">Yuo is not fully set up yet.</Trans>{" "}
          <Link to="/setup">
            <Trans id="home.finish-setup.link">Finish setting up</Trans>
          </Link>
        </Notice>
      ) : null}

      <AiReadyWarning enabled={(paths.data?.length ?? 0) > 0} />

      {paths.isPending ? (
        <Waiting>
          <Trans id="common.loading">Loading…</Trans>
        </Waiting>
      ) : paths.isError ? (
        <ErrorNotice error={paths.error} />
      ) : paths.data.length === 0 ? (
        <div className={`${ui.card} ${styles.empty}`}>
          <LeafWatermark />
          <span className={styles.emptyMark}>
            <Seedling width={72} />
          </span>
          <p className={styles.emptyTitle}>
            <Trans id="home.empty.title">Plant your first path</Trans>
          </p>
          <p className={ui.muted}>
            <Trans id="home.empty">
              No paths yet. Tell Yuo what you want to learn and it plans the lessons for you.
            </Trans>
          </p>
          <div className={styles.emptyActions}>
            <ButtonLink to="/paths/new">
              <PlusIcon size="1.1em" />
              <Trans id="home.new-path">New path</Trans>
            </ButtonLink>
            <ButtonLink to="/import" variant="ghost">
              <UploadIcon size="1.1em" />
              <Trans id="home.import">Import a path</Trans>
            </ButtonLink>
          </div>
        </div>
      ) : (
        <>
          <ul className={styles.list}>
            {paths.data
              .filter((p) => p.status !== "archived")
              .map((p) => (
                <li key={p.id}>
                  <PathCard path={p} />
                </li>
              ))}
          </ul>
          {paths.data.some((p) => p.status === "archived") ? (
            <section className={ui.stack} aria-labelledby="paths-archived">
              <h2 id="paths-archived" className={styles.sectionTitle}>
                <Trans id="paths.archived">Archived</Trans>
              </h2>
              <ul className={styles.list}>
                {paths.data
                  .filter((p) => p.status === "archived")
                  .map((p) => (
                    <li key={p.id}>
                      <PathCard path={p} />
                    </li>
                  ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </section>
  );
}
