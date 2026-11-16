// "Share or export" on the path page: choose what goes into the package, see a live preview
// with the privacy review (the goal, personal content off by default and listed when on), then
// download the `.yuo.zip`.
import { plural } from "@lingui/core/macro";
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { useState } from "react";
import { Checkbox, CheckboxGroup, Dialog, DialogTrigger, Heading, Label, Modal, ModalOverlay } from "react-aria-components";
import { UploadIcon } from "../components/icons";
import { ErrorNotice } from "../components/ErrorNotice";
import { Button, ChoiceField, ui } from "../components/ui";
import {
  COMPONENTS,
  downloadPackage,
  FORMATS,
  useExportPreview,
  type DownloadProgress,
  type ExportComponent,
  type ExportFormat,
  type ExportIn,
  type ExportPreview,
  type ExportProfile,
} from "./api";
import { COMPONENT, contentsInWords, countsInWords, FORMAT, formatBytes, personalInWords, PROFILE } from "./labels";
import styles from "./sharing.module.css";

const PROFILES: ExportProfile[] = ["full", "structure", "custom"];

/** The button that opens the dialog. */
export function ShareButton({ pathId }: { pathId: string }) {
  return (
    <DialogTrigger>
      <Button variant="ghost" small>
        <UploadIcon size="1.05em" />
        <Trans id="share.open">Share or export</Trans>
      </Button>
      <ModalOverlay className={styles.overlay} isDismissable>
        <Modal className={styles.modal}>
          <Dialog className={styles.dialog}>
            {({ close }) => <ExportPanel pathId={pathId} onClose={close} />}
          </Dialog>
        </Modal>
      </ModalOverlay>
    </DialogTrigger>
  );
}

type Download =
  | { state: "idle" }
  | { state: "running"; progress: DownloadProgress | null }
  | { state: "done"; name: string }
  | { state: "error"; error: unknown };

function ExportPanel({ pathId, onClose }: { pathId: string; onClose: () => void }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const [profile, setProfile] = useState<ExportProfile>("full");
  const [components, setComponents] = useState<ExportComponent[]>([...COMPONENTS]);
  const [formats, setFormats] = useState<ExportFormat[]>([]);
  const [includePersonal, setIncludePersonal] = useState(false);
  const [download, setDownload] = useState<Download>({ state: "idle" });

  const body: ExportIn = {
    profile,
    components: profile === "custom" ? COMPONENTS.filter((c) => components.includes(c)) : [],
    include_personal: includePersonal,
    formats: FORMATS.filter((f) => formats.includes(f)),
  };
  const valid = profile !== "custom" || components.length > 0;
  const preview = useExportPreview(pathId, body, valid);
  const running = download.state === "running";

  const start = async () => {
    setDownload({ state: "running", progress: null });
    try {
      const name = await downloadPackage(pathId, body, (progress) => setDownload({ state: "running", progress }));
      setDownload({ state: "done", name });
    } catch (error) {
      setDownload({ state: "error", error });
    }
  };

  return (
    <div className={ui.stack}>
      <Heading slot="title" className={styles.dialogTitle}>
        <Trans id="share.title">Share or export this path</Trans>
      </Heading>
      <p className={ui.muted}>
        <Trans id="share.intro">
          Yuo makes a package file (.yuo.zip) that another Yuo can import. Nothing is uploaded anywhere: you
          decide where the file goes.
        </Trans>
      </p>

      <ChoiceField
        label={t({ id: "share.profile.label", message: "What to share" })}
        stacked
        value={profile}
        onChange={setProfile}
        choices={PROFILES.map((p) => ({
          value: p,
          label: i18n._(PROFILE[p].label),
          description: i18n._(PROFILE[p].description),
        }))}
      />

      {profile === "custom" ? (
        <CheckboxGroup
          className={ui.radioGroup}
          value={components}
          onChange={(v) => setComponents(v as ExportComponent[])}
        >
          <Label className={ui.label}>
            <Trans id="share.components.label">Parts to include</Trans>
          </Label>
          <div className={ui.radioListStacked}>
            {COMPONENTS.map((c) => (
              <Checkbox key={c} value={c} className={`${ui.radio} ${styles.checkbox}`}>
                {i18n._(COMPONENT[c]!)}
              </Checkbox>
            ))}
          </div>
          {components.length === 0 ? (
            <p className={ui.muted}>
              <Trans id="share.components.none">Choose at least one part.</Trans>
            </p>
          ) : null}
        </CheckboxGroup>
      ) : null}

      <CheckboxGroup className={ui.radioGroup} value={formats} onChange={(v) => setFormats(v as ExportFormat[])}>
        <Label className={ui.label}>
          <Trans id="share.formats.label">Also include standard files</Trans>
        </Label>
        <p className={`${ui.muted} ${styles.small}`}>
          <Trans id="share.formats.description">
            Copies for other apps, inside the package. Yuo itself reads only its own records.
          </Trans>
        </p>
        <div className={ui.radioListStacked}>
          {FORMATS.map((f) => (
            <Checkbox key={f} value={f} className={`${ui.radio} ${styles.checkbox}`}>
              {i18n._(FORMAT[f])}
            </Checkbox>
          ))}
        </div>
      </CheckboxGroup>

      <section className={styles.preview} aria-labelledby="share-preview-title">
        <h3 id="share-preview-title" className={styles.sectionTitle}>
          <Trans id="share.preview.title">What the package will hold</Trans>
        </h3>
        {!valid ? null : preview.isPending ? (
          <p className={ui.muted}>
            <Trans id="common.loading">Loading…</Trans>
          </p>
        ) : preview.isError && !preview.data ? (
          <ErrorNotice error={preview.error} />
        ) : preview.data ? (
          <PreviewBody
            data={preview.data}
            updating={preview.isFetching}
            includePersonal={includePersonal}
            onIncludePersonal={setIncludePersonal}
          />
        ) : null}
      </section>

      <p className={`${ui.muted} ${styles.small}`}>
        <Trans id="share.video-note">
          Videos are shared as finished videos. The code Yuo wrote to make them is never shared.
        </Trans>
      </p>

      <div aria-live="polite" role="status" className={styles.status}>
        {download.state === "running" ? (
          download.progress === null ? (
            <Trans id="share.download.preparing">Making the package…</Trans>
          ) : download.progress.total ? (
            <Trans id="share.download.progress">
              Downloading: {formatBytes(download.progress.received, i18n.locale)} of{" "}
              {formatBytes(download.progress.total, i18n.locale)}
            </Trans>
          ) : (
            <Trans id="share.download.progress-unknown">
              Downloading: {formatBytes(download.progress.received, i18n.locale)}
            </Trans>
          )
        ) : download.state === "done" ? (
          <Trans id="share.download.done">Saved as {download.name}. Check your downloads.</Trans>
        ) : null}
      </div>
      {download.state === "error" ? <ErrorNotice error={download.error} /> : null}

      <div className={ui.row}>
        <Button onPress={() => void start()} isDisabled={running || !valid}>
          {running ? (
            <Trans id="share.download.running">Downloading…</Trans>
          ) : (
            <Trans id="share.download">Download</Trans>
          )}
        </Button>
        <Button variant="secondary" onPress={onClose}>
          <Trans id="share.close">Close</Trans>
        </Button>
      </div>
    </div>
  );
}

function PreviewBody({
  data,
  updating,
  includePersonal,
  onIncludePersonal,
}: {
  data: ExportPreview;
  updating: boolean;
  includePersonal: boolean;
  onIncludePersonal: (on: boolean) => void;
}) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const contents = contentsInWords(i18n, data.contents).join(", ");
  const counts = countsInWords(i18n, data.counts).join(", ");
  const size = formatBytes(data.asset_bytes, i18n.locale);
  const personal = includePersonal && data.personal_included.length ? data.personal_included : data.personal_available;
  const n = data.personal_available.length || personal.length;
  return (
    <div className={ui.stack} aria-busy={updating}>
      <dl className={styles.facts}>
        <dt>
          <Trans id="share.preview.contents">Contents</Trans>
        </dt>
        <dd>{contents || <Trans id="share.preview.empty">Nothing yet</Trans>}</dd>
        {counts ? (
          <>
            <dt>
              <Trans id="share.preview.counts">In numbers</Trans>
            </dt>
            <dd>{counts}</dd>
          </>
        ) : null}
        {data.asset_bytes > 0 ? (
          <>
            <dt>
              <Trans id="share.preview.size">Videos and media</Trans>
            </dt>
            <dd>{size}</dd>
          </>
        ) : null}
      </dl>

      <div className={styles.privacy}>
        <h4 className={styles.sectionTitle}>
          <Trans id="share.privacy.title">Privacy</Trans>
        </h4>
        {data.goal ? (
          <>
            <p className={styles.small}>
              <Trans id="share.privacy.goal">The package includes the path's goal:</Trans>
            </p>
            <blockquote className={styles.goal}>{data.goal}</blockquote>
            <p className={styles.small}>
              <strong>
                <Trans id="share.privacy.goal-check">Check this before sharing: it often says something about you.</Trans>
              </strong>
            </p>
          </>
        ) : null}
        {n > 0 || includePersonal ? (
          <>
            <Checkbox
              isSelected={includePersonal}
              onChange={onIncludePersonal}
              className={`${ui.radio} ${styles.checkbox}`}
            >
              {t({
                id: "share.personal.include",
                message: plural(n, {
                  one: "Include my own content (# item: requested lessons, my edits, lessons made from my personal instructions)",
                  other:
                    "Include my own content (# items: requested lessons, my edits, lessons made from my personal instructions)",
                }),
              })}
            </Checkbox>
            {includePersonal && personal.length ? (
              <ul className={styles.personalList} aria-label={t({ id: "share.personal.list", message: "My own content in the package" })}>
                {personal.map((entry) => {
                  const { kind, code } = personalInWords(i18n, entry);
                  return (
                    <li key={entry}>
                      {kind} <code>{code}</code>
                    </li>
                  );
                })}
              </ul>
            ) : null}
          </>
        ) : (
          <p className={`${ui.muted} ${styles.small}`}>
            <Trans id="share.personal.none">No content of your own is in this path.</Trans>
          </p>
        )}
      </div>
    </div>
  );
}
