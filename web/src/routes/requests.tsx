// "Ask for a lesson" on the path view: a prompt plus optional links; the request list polls
// while a request is open, and the path refreshes when one is done so the new lesson appears.
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Form } from "react-aria-components";
import { hasOpenRequest, keys, useCreateRequest, useRequests } from "../api/hooks";
import { GenerationError } from "../onboarding/AiReady";
import { jobErrorMessage } from "../components/jobError";
import { RequestStatusLabel } from "../components/labels";
import { Button, Field, MoreOptions, Notice, ui } from "../components/ui";
import styles from "./pathView.module.css";

const MAX_LINKS = 10;

/** One link per line; blank lines dropped. */
function parseLinks(text: string): string[] {
  return text
    .split(/\s*\n\s*/)
    .map((l) => l.trim())
    .filter(Boolean);
}

export function LessonRequests({ pathId }: { pathId: string }) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const qc = useQueryClient();
  const requests = useRequests(pathId);
  const create = useCreateRequest(pathId);
  const [prompt, setPrompt] = useState("");
  const [links, setLinks] = useState("");
  const [sent, setSent] = useState(false);
  const linkList = parseLinks(links);
  const tooManyLinks = linkList.length > MAX_LINKS;

  // a request finished: its lesson is now in the tree
  const open = hasOpenRequest(requests.data);
  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) void qc.invalidateQueries({ queryKey: keys.path(pathId) });
    wasOpen.current = open;
  }, [open, pathId, qc]);

  const rows = requests.data ?? [];
  const max = MAX_LINKS;

  return (
    <section className={`${ui.card} ${ui.stack}`} aria-labelledby="requests-title">
      <h2 id="requests-title" className={styles.branchTitle}>
        <Trans id="request.title">Ask for a lesson</Trans>
      </h2>
      <p className={ui.muted}>
        <Trans id="request.intro">
          Missing something? Describe it and Yuo writes a lesson for it and puts it in the right skill.
        </Trans>
      </p>
      <MoreOptions title={t({ id: "request.open", message: "Describe the lesson you need" })}>
        <Form
          className={ui.stack}
          onSubmit={(e) => {
            e.preventDefault();
            if (tooManyLinks) return;
            create.mutate(
              { prompt: prompt.trim(), links: linkList },
              {
                onSuccess: () => {
                  setPrompt("");
                  setLinks("");
                  setSent(true);
                },
              },
            );
          }}
        >
          <Field
            label={t({ id: "request.field.prompt", message: "What should the lesson cover?" })}
            value={prompt}
            onChange={(v) => {
              setPrompt(v);
              setSent(false);
            }}
            isRequired
            maxLength={2000}
            multiline
            name="prompt"
          />
          <Field
            label={t({ id: "request.field.links", message: "Links (optional)" })}
            description={t({ id: "request.field.links.description", message: `One per line, at most ${max}.` })}
            value={links}
            onChange={setLinks}
            multiline
            name="links"
          />
          {tooManyLinks ? (
            <Notice tone="error">
              <Trans id="request.links.too-many">Please give at most {max} links.</Trans>
            </Notice>
          ) : null}
          {create.isError ? <GenerationError error={create.error} /> : null}
          {sent ? (
            <Notice tone="success" role="status">
              <Trans id="request.sent">Request sent. The lesson appears in the path when it is ready.</Trans>
            </Notice>
          ) : null}
          <div className={ui.row}>
            <Button type="submit" isDisabled={create.isPending || prompt.trim().length < 3 || tooManyLinks}>
              <Trans id="request.submit">Ask for this lesson</Trans>
            </Button>
          </div>
        </Form>
      </MoreOptions>

      {rows.length > 0 ? (
        <div className={ui.stack}>
          <h3 className={styles.skillTitle}>
            <Trans id="request.list.title">Your requests</Trans>
          </h3>
          <ul className={styles.lessons}>
            {rows.map((r) => (
              <li key={r.id} className={styles.lesson}>
                <span className={styles.lessonTitle}>{r.prompt}</span>
                <span className={styles.state} data-state={r.status === "done" ? "ready" : r.status}>
                  <RequestStatusLabel value={r.status} />
                </span>
                {r.status === "failed" ? (
                  <span className={`${styles.lessonError} ${ui.muted}`}>{i18n._(jobErrorMessage(r.error))}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
