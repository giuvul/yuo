import { describe, expect, it } from "vitest";
import { UUID7_PATTERN, uuid7, uuid7Time } from "./uuid7";

describe("uuid7", () => {
  it("has the RFC 9562 layout: version 7, variant 10, lowercase", () => {
    for (let i = 0; i < 200; i++) {
      const id = uuid7();
      expect(id).toMatch(UUID7_PATTERN);
      expect(id).toBe(id.toLowerCase());
      expect(id[14]).toBe("7");
    }
  });

  it("encodes the Unix milliseconds in the first 48 bits", () => {
    const at = Date.UTC(2099, 0, 1, 12, 34, 56, 789); // later than any id made so far in this file
    const id = uuid7(at);
    expect(uuid7Time(id)).toBe(at);
    expect(id.slice(0, 13)).toBe(
      at.toString(16).padStart(12, "0").replace(/^(.{8})/, "$1-"),
    );
  });

  it("is unique and sorts in creation order within one millisecond", () => {
    const at = Date.UTC(2099, 0, 2);
    const ids = Array.from({ length: 1000 }, () => uuid7(at));
    expect(new Set(ids).size).toBe(ids.length);
    expect([...ids].sort()).toEqual(ids);
    for (const id of ids) expect(id).toMatch(UUID7_PATTERN);
  });

  it("keeps order when the clock goes back", () => {
    const at = Date.UTC(2099, 0, 3);
    const a = uuid7(at);
    const b = uuid7(at - 5_000);
    expect(b > a).toBe(true);
  });
});
