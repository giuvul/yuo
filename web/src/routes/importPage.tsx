// Import a path package: pick or drop a `.yuo.zip`, upload it with progress, read what it
// holds (personal content marked), then import it as a new path or as an update of the path an
// earlier import made. Nothing is written before "Import"; Cancel removes the upload.
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { createRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { DropZone, FileTrigger, Text, type DropZoneProps } from "react-aria-components";
import { ApiError } from "../api/client";
import { ErrorNotice } from "../components/ErrorNotice";
import { BackLink, Button, Notice, PageHeader, ui } from "../components/ui";
import {
  dropUpload,
  uploadPackage,
  useImportPackage,
  UploadNetworkError,
  type ImportMode,
  type PackagePreview,
} from "../sharing/api";
import {
  contentsInWords,
  countsInWords,
  languageName,
  noticeInWords,
  personalInWords,
  PROFILE,
} from "../sharing/labels";
import styles from "../sharing/sharing.module.css";
import { useTutorRefs } from "../tutor/context";
import { rootRoute } from "./root";

export const importRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/import",
  component: ImportPage,
});

type DropEvent = Parameters<NonNullable<DropZoneProps["onDrop"]>>[0];

type Stage =
  | { kind: "pick" }
  | { kind: "uploading"; name: string; fraction: number | null; abort: () => void }
  | { kind: "refused"; name: string; reason: string }
  | { kind: "failed"; name: string; error: unknown }
  | { kind: "preview"; name: string; token: string; preview: PackagePreview };

function ImportPage() {
  useTutorRefs({ screen: "other" });
  const { t } = useLingui();
  const navigate = useNavigate();
  const [stage, setStage] = useState<Stage>({ kind: "pick" });
  const importer = useImportPackage();
  // an upload that is neither imported nor cancelled yet: removed from the server when the page goes
  const pending = useRef<string | null>(null);
  useEffect(
    () => () => {
      if (pending.current) void dropUpload(pending.current);
    },
    [],
  );

  const upload = async (file: File) => {
    const name = file.name;
    const { promise, abort } = uploadPackage(file, (fraction) =>
      setStage((s) => (s.kind === "uploading" ? { ...s, fraction } : s)),
    );
    setStage({ kind: "uploading", name, fraction: 0, abort });
    try {
      const result = await promise;
      if (result.error || !result.preview) {
        setStage({ kind: "refused", name, reason: result.error ?? "" });
      } else {
        pending.current = result.token;
        setStage({ kind: "preview", name, token: result.token, preview: result.preview });
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") setStage({ kind: "pick" });
      else setStage({ kind: "failed", name, error });
    }
  };

  const onDrop = async (e: DropEvent) => {
    for (const item of e.items) {
      if (item.kind === "file") {
        await upload(await item.getFile());
        return;
      }
    }
  };

  const cancel = async () => {
    if (stage.kind === "preview") {
      pending.current = null;
      await dropUpload(stage.token);
    }
    importer.reset();
    setStage({ kind: "pick" });
  };

  const doImport = (mode: ImportMode) => {
    if (stage.kind !== "preview") return;
    importer.mutate(
      { token: stage.token, mode },
      {
        onSuccess: ({ path_id }) => {
          pending.current = null;
          void navigate({ to: "/paths/$pathId", params: { pathId: path_id } });
        },
        onError: (error) => {
          // the server drops the upload after any import attempt: start again from the file
          pending.current = null;
          setStage({ kind: "failed", name: stage.name, error });
        },
      },
    );
  };

  return (
    <section className={ui.stack}>
      <PageHeader
        back={
          <BackLink to="/">
            <Trans id="nav.paths">Paths</Trans>
          </BackLink>
        }
        title={<Trans id="import.title">Import a path</Trans>}
        meta={
          <p>
            <Trans id="import.intro">
              Open a path package (.yuo.zip) that someone shared with you or that you exported. You see what it
              holds before anything is imported.
            </Trans>
          </p>
        }
      />

      {stage.kind === "pick" || stage.kind === "refused" || stage.kind === "failed" ? (
        <DropZone
          className={styles.dropZone}
          aria-label={t({ id: "import.drop.label", message: "Drop a package file here" })}
          getDropOperation={() => "copy"}
          onDrop={(e) => void onDrop(e)}
        >
          <Text slot="label">
            <Trans id="import.drop">Drop a .yuo.zip file here, or</Trans>
          </Text>
          <FileTrigger
            acceptedFileTypes={[".zip", "application/zip"]}
            onSelect={(files) => {
              const file = files?.[0];
              if (file) void upload(file);
            }}
          >
            <Button>
              <Trans id="import.choose">Choose a file</Trans>
            </Button>
          </FileTrigger>
        </DropZone>
      ) : null}

      {stage.kind === "refused" ? (
        <Notice tone="error">
          <p className={styles.fileName}>
            <strong>
              <Trans id="import.refused.title">Yuo cannot import {stage.name}.</Trans>
            </strong>
          </p>
          {stage.reason ? (
            <p className={styles.fileName}>
              <Trans id="import.refused.reason">Reason: {stage.reason}</Trans>
            </p>
          ) : null}
          <p>
            <Trans id="import.refused.nothing">Nothing was imported.</Trans>
          </p>
        </Notice>
      ) : null}

      {stage.kind === "failed" ? <UploadFailed error={stage.error} /> : null}

      {stage.kind === "uploading" ? (
        <div className={ui.card}>
          <div className={ui.stack}>
            <p className={styles.fileName}>
              <Trans id="import.uploading">Uploading {stage.name}…</Trans>
            </p>
            <progress
              className={styles.progress}
              max={1}
              value={stage.fraction ?? undefined}
              aria-label={t({ id: "import.uploading.label", message: "Upload progress" })}
            />
            <p className={ui.muted} role="status">
              {stage.fraction === null ? null : stage.fraction >= 1 ? (
                <Trans id="import.checking">Checking the package…</Trans>
              ) : (
                <Trans id="import.uploading.percent">{Math.round(stage.fraction * 100)} % sent</Trans>
              )}
            </p>
            <div>
              <Button variant="secondary" onPress={stage.abort}>
                <Trans id="import.cancel">Cancel</Trans>
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {stage.kind === "preview" ? (
        <PackageSummary
          preview={stage.preview}
          busy={importer.isPending}
          onImport={doImport}
          onCancel={() => void cancel()}
        />
      ) : null}
    </section>
  );
}

function UploadFailed({ error }: { error: unknown }) {
  if (error instanceof UploadNetworkError) {
    return (
      <Notice tone="error">
        <Trans id="import.upload.network">
          The upload did not reach Yuo's server. Check the connection, then try again. Nothing was imported.
        </Trans>
      </Notice>
    );
  }
  if (error instanceof ApiError && error.status === 413) {
    return (
      <Notice tone="error">
        <Trans id="import.upload.too-large">This file is larger than 10 GB. Nothing was imported.</Trans>
      </Notice>
    );
  }
  return <ErrorNotice error={error} />;
}

function PackageSummary({
  preview,
  busy,
  onImport,
  onCancel,
}: {
  preview: PackagePreview;
  busy: boolean;
  onImport: (mode: ImportMode) => void;
  onCancel: () => void;
}) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const contents = contentsInWords(i18n, preview.contents).join(", ");
  const counts = countsInWords(i18n, preview.counts).join(", ");
  const language = languageName(preview.content_lang, i18n.locale);
  const profile =
    preview.profile === "full" || preview.profile === "structure"
      ? i18n._(PROFILE[preview.profile].label)
      : preview.profile === "custom"
        ? t({ id: "import.profile.custom", message: "Some parts of a path" })
        : preview.profile;
  const version = preview.content_version;
  // installed_version also reflects this install's own exports; it only means "you have" for an earlier import
  const installed = preview.installed_version;
  const upgraded = preview.upgraded_from;
  const updateOf = preview.update_of;

  return (
    <article className={ui.card} aria-labelledby="import-preview-title">
      <div className={ui.stack}>
        <h2 id="import-preview-title" className={styles.dialogTitle}>
          {preview.title}
        </h2>
        <dl className={styles.facts}>
          <dt>
            <Trans id="import.preview.kind">Kind</Trans>
          </dt>
          <dd>{profile}</dd>
          <dt>
            <Trans id="import.preview.contents">What is inside</Trans>
          </dt>
          <dd>{contents}</dd>
          {counts ? (
            <>
              <dt>
                <Trans id="import.preview.counts">In numbers</Trans>
              </dt>
              <dd>{counts}</dd>
            </>
          ) : null}
          <dt>
            <Trans id="import.preview.language">Language</Trans>
          </dt>
          <dd>{language}</dd>
          <dt>
            <Trans id="import.preview.licence">Licence</Trans>
          </dt>
          <dd>{preview.licence}</dd>
          <dt>
            <Trans id="import.preview.version">Version</Trans>
          </dt>
          <dd>
            {installed && updateOf ? (
              <Trans id="import.preview.version-update">
                {version} (you have {installed})
              </Trans>
            ) : (
              version
            )}
          </dd>
        </dl>
        {preview.profile === "structure" ? (
          <p className={`${ui.muted} ${styles.small}`}>
            <Trans id="import.preview.structure">This package has no videos: your models make them after the import.</Trans>
          </p>
        ) : null}
        {upgraded ? (
          <p className={`${ui.muted} ${styles.small}`}>
            <Trans id="import.preview.upgraded">Upgraded from package format {upgraded}.</Trans>
          </p>
        ) : null}
        {preview.notices.map((n) => (
          <Notice key={n} tone="warning">
            {noticeInWords(i18n, n)}
          </Notice>
        ))}
        {preview.personal.length ? (
          <div className={styles.privacy}>
            <p className={styles.small}>
              <span className={styles.badge}>
                <Trans id="import.personal.badge">Personal content</Trans>
              </span>{" "}
              <Trans id="import.personal.intro">The person who shared this included their own content:</Trans>
            </p>
            <ul className={styles.personalList}>
              {preview.personal.map((entry) => {
                const { kind, code } = personalInWords(i18n, entry);
                return (
                  <li key={entry}>
                    {kind} <code>{code}</code>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

        {updateOf ? (
          <Notice role="status">
            <Trans id="import.update.found">
              You imported this package before.{" "}
              <Link to="/paths/$pathId" params={{ pathId: updateOf }}>
                See that path
              </Link>
              . Update it with this version, or import a separate copy.
            </Trans>
          </Notice>
        ) : !preview.can_create ? (
          <Notice tone="warning">
            <Trans id="import.cannot">
              This package holds only some parts of a path, and no earlier import of it was found here, so it
              cannot be imported.
            </Trans>
          </Notice>
        ) : null}

        {busy ? (
          <p className={ui.muted} role="status">
            <Trans id="import.importing">Importing…</Trans>
          </p>
        ) : null}

        <div className={ui.row}>
          {updateOf ? (
            <Button onPress={() => onImport("update")} isDisabled={busy}>
              <Trans id="import.update">Update that path</Trans>
            </Button>
          ) : null}
          {preview.can_create ? (
            <Button onPress={() => onImport("new")} isDisabled={busy} variant={updateOf ? "secondary" : "primary"}>
              {updateOf ? (
                <Trans id="import.new-copy">Import as a new copy</Trans>
              ) : (
                <Trans id="import.new">Import as a new path</Trans>
              )}
            </Button>
          ) : null}
          <Button variant="secondary" onPress={onCancel} isDisabled={busy}>
            <Trans id="import.cancel">Cancel</Trans>
          </Button>
        </div>
      </div>
    </article>
  );
}
