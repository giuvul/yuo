// Files chosen on the new-path form, before their path existed: the path is made when they are added, and its
// upload screen picks them up on opening and sends them (kept in memory only, for that one navigation).
const waiting = new Map<string, File[]>();

export function handOver(pathId: string, files: File[]): void {
  waiting.set(pathId, files);
}

/** The files waiting for this path, once: a second call (React's double mount) gets none. */
export function takeOver(pathId: string): File[] {
  const files = waiting.get(pathId) ?? [];
  waiting.delete(pathId);
  return files;
}
