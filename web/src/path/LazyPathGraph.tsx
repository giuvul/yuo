// The path graph, loaded when it is first shown: the node-graph library is its own chunk, so the list view and the
// other pages do not pay for it.
import { Trans } from "@lingui/react/macro";
import { lazy, Suspense } from "react";
import { Waiting } from "../components/ui";
import type { PathGraphProps } from "./PathGraph";
import styles from "./LazyPathGraph.module.css";

const PathGraph = lazy(() => import("./PathGraph"));

export function LazyPathGraph(props: PathGraphProps) {
  return (
    <Suspense
      fallback={
        <div className={styles.loading} data-contained={props.contained || undefined}>
          <Waiting>
            <Trans id="common.loading">Loading…</Trans>
          </Waiting>
        </div>
      }
    >
      <PathGraph {...props} />
    </Suspense>
  );
}
