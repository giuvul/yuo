import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { forget, readJson, readText, writeJson, writeText } from "./storage";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

const isStrings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

describe("storage", () => {
  it("keeps plain text and JSON as they were stored before", () => {
    writeText("yuo.theme", "dark");
    expect(localStorage.getItem("yuo.theme")).toBe("dark"); // index.html reads it as is
    writeJson("yuo.pos", { side: "left", y: 0.5 });
    expect(readJson("yuo.pos", null)).toEqual({ side: "left", y: 0.5 });
    forget("yuo.theme");
    expect(readText("yuo.theme")).toBeNull();
  });

  it("falls back on missing, broken or invalid values", () => {
    expect(readJson("nothing", 7)).toBe(7);
    localStorage.setItem("broken", "{not json");
    expect(readJson("broken", [])).toEqual([]);
    localStorage.setItem("wrong", JSON.stringify([1, 2]));
    expect(readJson<string[]>("wrong", [], isStrings)).toEqual([]);
  });

  it("does not throw when storage is closed", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(readText("k")).toBeNull();
    expect(readJson("k", "fallback")).toBe("fallback");
    expect(() => writeJson("k", 1)).not.toThrow();
  });
});
