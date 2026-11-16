import { I18nProvider } from "@lingui/react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { json, mockApi } from "../test/mockApi";
import type { Item } from "../api/client";
import { activateLocale, i18n } from "../i18n";
import { emptyDraft, toAnswer } from "./answers";
import { choiceMarks, ItemInput, itemPrompt } from "./ItemInput";

/** Renders an item like the runner does and prints the answer it would send. */
function Harness({ item }: { item: Item }) {
  const [draft, setDraft] = useState(() => emptyDraft(item));
  const answer = toAnswer(item, draft);
  return (
    <div>
      <h2>{itemPrompt(item)}</h2>
      <ItemInput item={item} draft={draft} onChange={setDraft} />
      <output data-testid="answer">{answer === null ? "incomplete" : JSON.stringify(answer)}</output>
    </div>
  );
}

function renderItem(item: Item) {
  const user = userEvent.setup();
  const view = render(
    <I18nProvider i18n={i18n}>
      <Harness item={item} />
    </I18nProvider>,
  );
  const answer = () => screen.getByTestId("answer").textContent;
  return { user, answer, ...view };
}

/** A key smuggled into a view must never show up (the API never sends one; this guards the renderer). */
const SECRET = "SECRET-KEY";
const smuggle = <T extends object>(view: T): T => ({ ...view, answer: SECRET, answers: [SECRET], back: SECRET });

const options = [
  { id: "a", text: "Paris" },
  { id: "b", text: "Lyon" },
  { id: "c", text: "Nice" },
  { id: "d", text: "Lille" },
];

describe("item renderers", () => {
  beforeAll(async () => {
    await activateLocale("en");
  });
  afterEach(() => vi.unstubAllGlobals());

  it("checked choices: the right one and a wrong pick are marked in words, not colour alone", () => {
    expect(choiceMarks(undefined, ["b"])).toBeUndefined();
    expect(choiceMarks("a", ["b"])).toEqual({ a: "right", b: "wrong" });
    expect(choiceMarks(["a", "c"], ["a"])).toEqual({ a: "right", c: "right" });
    const item: Item = { item_version_id: "1", type: "mcq", view: { prompt: "Capital of France?", options } };
    render(
      <I18nProvider i18n={i18n}>
        <ItemInput item={item} draft={{ type: "mcq", choice: "b" }} onChange={() => {}} disabled correct="a" />
      </I18nProvider>,
    );
    expect(screen.getByRole("radio", { name: /^a\. Paris.*Right answer/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^b\. Lyon.*Your answer/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^c\. Nice$/ })).toBeInTheDocument();
  });

  it("mcq: one option id", async () => {
    const { user, answer, container } = renderItem({
      item_version_id: "1",
      type: "mcq",
      view: smuggle({ prompt: "Capital of France?", options }),
    });
    expect(screen.getByRole("heading", { name: "Capital of France?" })).toBeInTheDocument();
    expect(answer()).toBe("incomplete");
    await user.click(screen.getByRole("radio", { name: "a. Paris" }));
    expect(answer()).toBe('"a"');
    expect(container.textContent).not.toContain(SECRET);
  });

  it("multi: all chosen ids in option order", async () => {
    const { user, answer, container } = renderItem({
      item_version_id: "2",
      type: "multi",
      view: smuggle({ prompt: "Cities in France?", options }),
    });
    expect(screen.getByRole("group", { name: "Select all that apply" })).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "c. Nice" }));
    await user.click(screen.getByRole("checkbox", { name: "a. Paris" }));
    expect(answer()).toBe('["a","c"]');
    await user.click(screen.getByRole("checkbox", { name: "c. Nice" }));
    expect(answer()).toBe('["a"]');
    expect(container.textContent).not.toContain(SECRET);
  });

  it("cloze: one text per gap, in order", async () => {
    const { user, answer, container } = renderItem({
      item_version_id: "3",
      type: "cloze",
      view: smuggle({ text: "Water boils at {{1}} degrees at sea {{2}}.", gaps: 2 }),
    });
    expect(container.textContent).toContain("Water boils at");
    await user.type(screen.getByRole("textbox", { name: "Gap 1" }), "100");
    expect(answer()).toBe("incomplete");
    await user.type(screen.getByRole("textbox", { name: "Gap 2" }), "level");
    expect(answer()).toBe('["100","level"]');
    expect(container.textContent).not.toContain(SECRET);
  });

  it("ordering: ids in the learner's order, by keyboard with move buttons", async () => {
    const { user, answer, container } = renderItem({
      item_version_id: "4",
      type: "ordering",
      view: smuggle({
        prompt: "Order the steps",
        steps: [
          { id: "c", text: "Serve" },
          { id: "a", text: "Boil water" },
          { id: "b", text: "Add pasta" },
        ],
      }),
    });
    expect(answer()).toBe('["c","a","b"]'); // as shown (shuffled by the server)
    expect(screen.getByRole("button", { name: "Move up: Serve" })).toBeDisabled();
    screen.getByRole("button", { name: "Move down: Serve" }).focus();
    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("button", { name: "Move down: Serve" }));
    expect(answer()).toBe('["a","b","c"]');
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items.map((li) => li.textContent?.replace(/[↑↓]/g, ""))).toEqual(["Boil water", "Add pasta", "Serve"]);
    expect(container.textContent).not.toContain(SECRET);
  });

  it("matching: a select menu per left entry, pairs of texts", async () => {
    const { user, answer, container } = renderItem({
      item_version_id: "5",
      type: "matching",
      view: smuggle({ prompt: "Match the animal to its sound", left: ["dog", "cat"], right: ["meow", "woof"] }),
    });
    await user.click(screen.getByRole("button", { name: /dog/ }));
    await user.click(await screen.findByRole("option", { name: "woof" }));
    expect(answer()).toBe("incomplete");
    await user.click(screen.getByRole("button", { name: /cat/ }));
    await user.click(await screen.findByRole("option", { name: "meow" }));
    expect(answer()).toBe('[{"left":"dog","right":"woof"},{"left":"cat","right":"meow"}]');
    expect(container.textContent).not.toContain(SECRET);
  });

  it("flashcard: front, then Show answer reveals the back, then a self-rating 1-4", async () => {
    const { calls } = mockApi({ "GET /api/items/6/reveal": () => json({ back: "56" }) });
    const { user, answer, container } = renderItem({
      item_version_id: "6",
      type: "flashcard",
      view: smuggle({ front: "What is 7 × 8?" }),
    });
    expect(screen.getByRole("heading", { name: "What is 7 × 8?" })).toBeInTheDocument();
    expect(screen.queryByRole("radio")).toBeNull(); // no rating before the flip
    expect(container.textContent).not.toContain("56");
    expect(answer()).toBe("incomplete");

    await user.click(screen.getByRole("button", { name: "Show answer" }));
    expect(await screen.findByText("56")).toBeInTheDocument();
    expect(calls.map((c) => c.path)).toEqual(["/api/items/6/reveal"]);
    expect(screen.getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([
      "Again",
      "Hard",
      "Good",
      "Easy",
    ]);
    await user.click(screen.getByRole("radio", { name: "Good" }));
    expect(answer()).toBe("3");
    expect(container.textContent).not.toContain(SECRET);
  });

  it("short answer: the trimmed free text", async () => {
    const { user, answer, container } = renderItem({
      item_version_id: "7",
      type: "short_answer",
      view: smuggle({ prompt: "Why do we index tables?" }),
    });
    expect(answer()).toBe("incomplete");
    await user.type(screen.getByRole("textbox", { name: /Your answer/ }), "  To find rows faster.  ");
    expect(answer()).toBe('"To find rows faster."');
    expect(container.textContent).not.toContain(SECRET);
  });
});
