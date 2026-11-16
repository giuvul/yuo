// What one browser remembers between visits (localStorage), in one place. Storage can
// be closed (private mode, a blocked site): every read falls back and every write is silently skipped, so a
// preference is then kept for this visit only. Values are kept as they always were: plain text for the keys that
// index.html reads before the first paint, JSON for structured ones.

export function readText(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeText(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // storage closed: remembered for this visit only
  }
}

export function forget(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // storage closed: nothing was kept
  }
}

/** A JSON value, or `fallback` when it is missing, unreadable, or fails `valid`. */
export function readJson<T>(key: string, fallback: T, valid?: (v: unknown) => v is T): T {
  const text = readText(key);
  if (text == null) return fallback;
  try {
    const v: unknown = JSON.parse(text);
    return valid ? (valid(v) ? v : fallback) : (v as T);
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): void {
  writeText(key, JSON.stringify(value));
}
