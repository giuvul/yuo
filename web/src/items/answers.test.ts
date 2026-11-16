import { describe, expect, it } from "vitest";
import type { Item } from "../api/client";
import { clozeParts, correctLines, emptyDraft, move, toAnswer } from "./answers";

const multi: Item = {
  item_version_id: "m",
  type: "multi",
  view: { prompt: "p", options: ["a", "b", "c", "d"].map((id) => ({ id, text: id.toUpperCase() })) },
};
const matching: Item = {
  item_version_id: "x",
  type: "matching",
  view: { prompt: "p", left: ["dog", "cat"], right: ["meow", "woof"] },
};

describe("answers", () => {
  it("splits cloze text at numbered markers", () => {
    expect(clozeParts("A {{1}} B {{2}}.")).toEqual(["A ", 1, " B ", 2, "."]);
    expect(clozeParts("{{1}}")).toEqual([1]);
    expect(clozeParts("no gaps")).toEqual(["no gaps"]);
  });

  it("moves list entries and ignores moves past the ends", () => {
    expect(move(["a", "b", "c"], 2, 0)).toEqual(["c", "a", "b"]);
    expect(move(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(move(["a", "b"], 1, 2)).toEqual(["a", "b"]);
  });

  it("is incomplete until every part is answered", () => {
    expect(toAnswer(multi, emptyDraft(multi))).toBeNull();
    expect(toAnswer(multi, { type: "multi", choices: ["c", "a"] })).toEqual(["a", "c"]);
    expect(toAnswer(matching, { type: "matching", pairs: { dog: "woof" } })).toBeNull();
    expect(toAnswer(matching, { type: "matching", pairs: { cat: "meow", dog: "woof" } })).toEqual([
      { left: "dog", right: "woof" },
      { left: "cat", right: "meow" },
    ]);
    const cloze: Item = { item_version_id: "c", type: "cloze", view: { text: "{{1}} {{2}}", gaps: 2 } };
    expect(toAnswer(cloze, { type: "cloze", gaps: ["x", " "] })).toBeNull();
    expect(toAnswer(cloze, { type: "cloze", gaps: [" x ", "y"] })).toEqual(["x", "y"]);
  });

  it("shows the right answer as text per type", () => {
    expect(correctLines(multi, ["a", "c"])).toEqual(["a. A", "c. C"]);
    expect(correctLines(matching, [{ left: "dog", right: "woof" }])).toEqual(["dog → woof"]);
    const ordering: Item = {
      item_version_id: "o",
      type: "ordering",
      view: { prompt: "p", steps: [{ id: "s2", text: "Second" }, { id: "s1", text: "First" }] },
    };
    expect(correctLines(ordering, ["s1", "s2"])).toEqual(["First", "Second"]);
    const card: Item = { item_version_id: "f", type: "flashcard", view: { front: "2+2" } };
    expect(correctLines(card, "4")).toEqual(["4"]);
  });
});
