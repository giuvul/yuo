import { createContext, useContext, useSyncExternalStore, type ReactNode } from "react";
import type { Outbox, OutboxStatus } from "./outbox";

const OutboxContext = createContext<Outbox | null>(null);

export function OutboxProvider({ outbox, children }: { outbox: Outbox; children: ReactNode }) {
  return <OutboxContext.Provider value={outbox}>{children}</OutboxContext.Provider>;
}

export function useOutbox(): Outbox {
  const outbox = useContext(OutboxContext);
  if (!outbox) throw new Error("useOutbox outside OutboxProvider");
  return outbox;
}

export function useOutboxStatus(): OutboxStatus {
  const outbox = useOutbox();
  return useSyncExternalStore(outbox.subscribe, outbox.getStatus, outbox.getStatus);
}
