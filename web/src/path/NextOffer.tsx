// The "What next?" checkpoint on the path page: an invitation once a branch is finished or few planned lessons
// are left, and a way back to a checkpoint in progress.
import { Trans } from "@lingui/react/macro";
import { useNext } from "../api/hooks";
import { SproutIcon } from "../components/icons";
import { ButtonLink, ui } from "../components/ui";
import styles from "../routes/nextSteps.module.css";

export const NEXT_OPEN = new Set(["preparing", "ready", "proposing", "proposed", "growing"]);

export function NextOffer({ pathId }: { pathId: string }) {
  const next = useNext(pathId);
  const data = next.data;
  if (!data) return null;
  const open = NEXT_OPEN.has(data.status);
  if (!open && !data.offer) return null;
  return (
    <section className={`${ui.card} ${styles.offer}`} aria-labelledby="next-offer-title" data-testid="next-offer">
      <div className={styles.heading}>
        <span className={styles.headingIcon} aria-hidden="true">
          <SproutIcon />
        </span>
        <div className={styles.offerText}>
          <h2 id="next-offer-title" className={styles.subtitle}>
            <Trans id="next.offer.title">What next?</Trans>
          </h2>
          <p className={ui.muted}>
            {open ? (
              <Trans id="next.offer.open">You started choosing where your path goes next.</Trans>
            ) : data.offer === "branch_done" ? (
              <Trans id="next.offer.branch">
                You finished a branch. Choose where your path goes next: deeper, wider, or putting it to use.
              </Trans>
            ) : (
              <Trans id="next.offer.low">
                Only a few planned lessons are left. Choose where your path goes next, so it keeps growing.
              </Trans>
            )}
          </p>
        </div>
      </div>
      <ButtonLink to="/paths/$pathId/next" params={{ pathId }} small>
        {open ? <Trans id="next.offer.continue">Continue</Trans> : <Trans id="next.offer.start">Choose what's next</Trans>}
      </ButtonLink>
    </section>
  );
}
