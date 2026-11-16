// UUID version 7 (RFC 9562 §5.7): 48-bit big-endian Unix milliseconds, 4-bit version (0111),
// 12-bit rand_a, 2-bit variant (10), 62-bit rand_b. Lowercase hex, 8-4-4-4-12.
// Monotonic within one millisecond (RFC 9562 §6.2 method 1): rand_a is used as a counter that
// starts from a random value with headroom, so ids made by this tab sort in creation order.

let lastMs = -1;
let seq = 0;

function randomBytes(n: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(n));
}

export function uuid7(now: number = Date.now(), random: Uint8Array = randomBytes(10)): string {
  let ms = Math.floor(now);
  if (ms > lastMs) {
    lastMs = ms;
    seq = (((random[0] ?? 0) << 8) | (random[1] ?? 0)) & 0x7ff; // headroom for 2048 more ids this ms
  } else {
    ms = lastMs; // clock went back or same millisecond: keep order
    seq += 1;
    if (seq > 0xfff) {
      lastMs += 1;
      ms = lastMs;
      seq = 0;
    }
  }

  const b = new Uint8Array(16);
  let t = ms;
  for (let i = 5; i >= 0; i--) {
    b[i] = t % 256;
    t = Math.floor(t / 256);
  }
  b[6] = 0x70 | ((seq >> 8) & 0x0f);
  b[7] = seq & 0xff;
  b[8] = 0x80 | ((random[2] ?? 0) & 0x3f);
  for (let i = 9; i < 16; i++) b[i] = random[i - 6] ?? 0;

  const hex = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export const UUID7_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** The millisecond timestamp encoded in a uuid7. */
export function uuid7Time(id: string): number {
  return parseInt(id.replace(/-/g, "").slice(0, 12), 16);
}
