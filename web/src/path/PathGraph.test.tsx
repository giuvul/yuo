import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { PathOut, ProgressOut } from "../api/client";
import { activateLocale } from "../i18n";
import { json, mockApi } from "../test/mockApi";
import { appRoutes, renderApp } from "../test/renderApp";

const path: PathOut = {
  id: "p1",
  title: "SQL for analysts",
  subject: "SQL",
  goal: "Reports",
  status: "active",
  difficulty: "foundational",
  content_lang: "en",
  level_check: "none",
  preview: "none",
  origin: "goal",
  jobs: [],
  branches: [
    {
      id: "b1",
      code: "basics",
      title: "Basics",
      skills: [
        {
          id: "s1",
          code: "basics.select",
          title: "Selecting rows",
          summary: "SELECT and WHERE",
          requires: [],
          objectives: [],
          lessons: [{ id: "l1", code: "l1", kind: "core", state: "ready", title: "What a table is", has_draft: false }],
        },
        {
          id: "s2",
          code: "basics.where",
          title: "Filtering",
          summary: "",
          requires: ["s1"],
          objectives: [],
          lessons: [
            { id: "l2", code: "l2", kind: "core", state: "ready", title: "WHERE in practice", has_draft: false },
            { id: "l3", code: "l3", kind: "core", state: "generating", title: "Combining conditions", has_draft: false },
          ],
        },
      ],
    },
    {
      id: "b2",
      code: "joins",
      title: "Joins",
      skills: [
        {
          id: "s3",
          code: "joins.inner",
          title: "SQL joins",
          summary: "",
          requires: ["s2"],
          objectives: [],
          lessons: [{ id: "l4", code: "l4", kind: "core", state: "planned", title: "Inner joins", has_draft: false }],
        },
        { id: "s4", code: "joins.outer", title: "Outer joins", summary: "", requires: ["s3"], objectives: [], lessons: [] },
      ],
    },
  ],
};

const progress: ProgressOut = {
  gamification: "full",
  skills: {
    s1: { state: "mastered", mastery: 0.85, evidence: 8 },
    s2: { state: "in_progress", mastery: 0.4, evidence: 3 },
    s3: { state: "locked", mastery: 0, evidence: 0 },
    s4: { state: "locked", mastery: 0, evidence: 0 },
  },
  branches: [
    { id: "b1", title: "Basics", xp: 120, level: 2 },
    { id: "b2", title: "Joins", xp: 0, level: 1 },
  ],
};

function open() {
  mockApi({
    ...appRoutes,
    "GET /api/paths/p1": () => json(path),
    "GET /api/paths/p1/progress": () => json(progress),
    "GET /api/paths/p1/requests": () => json([]),
  });
  return renderApp("/paths/p1");
}

// the graph's code is loaded on demand, and the canvas has its own buttons (zoom, fit, full screen): a skill is a
// button with `data-skill`
const node = (name: RegExp) => screen.findByRole("button", { name }, { timeout: 5000 });
// A mouse click on a node. Not `user.click`: its synthetic mousedown carries no `view`, which the library's drag
// handling reads; the click itself is all a skill's button listens to.
const click = (el: HTMLElement) => {
  el.focus();
  fireEvent.click(el);
};
const skillButtons = (graph: HTMLElement) => [...graph.querySelectorAll<HTMLButtonElement>("button[data-skill]")];

beforeAll(async () => {
  await activateLocale("en");
});
afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("path graph", () => {
  it("is the default view; every skill is a button whose name carries its state, mastery and prerequisites", async () => {
    open();
    await node(/^Filtering/);
    const graph = screen.getByRole("group", { name: "Skills" });
    expect(graph).toHaveAccessibleDescription(/A list view is available/);
    const names = skillButtons(graph).map((b) => b.getAttribute("aria-label"));
    expect(names.sort()).toEqual([
      "Filtering, in progress, learning now, mastery 40%, needs: Selecting rows, a lesson is being written",
      "Outer joins, locked, needs: SQL joins",
      "SQL joins, locked, needs: Filtering",
      "Selecting rows, mastered, mastery 85%",
    ]);
    expect(screen.getByRole("button", { name: /^Selecting rows/ })).toHaveAttribute("data-kind", "done");
    expect(screen.getByRole("button", { name: /^Filtering/ })).toHaveAttribute("data-kind", "current");
    expect(screen.getByRole("button", { name: /^SQL joins/ })).toHaveAttribute("data-kind", "locked");
    // every button in the canvas has a name: the skills, and the view controls
    const all = within(graph).getAllByRole("button");
    for (const b of all) expect(b).toHaveAccessibleName();
    expect(all.filter((b) => !b.dataset["skill"]).map((b) => b.getAttribute("aria-label"))).toEqual([
      "Zoom in",
      "Zoom out",
      "Fit the whole tree",
      "Full screen",
    ]);
    // the hubs and the start are drawn for the eye; the branch chips say the same for everyone
    expect(within(graph).getByText("Joins").closest("[aria-hidden='true']")).not.toBeNull();
    expect(within(graph).getByText("Start").closest("[aria-hidden='true']")).not.toBeNull();
    expect(screen.getByRole("radio", { name: /Basics.*Level 2.*1 of 2 mastered/ })).toBeInTheDocument();
    // the list's rows are not on the page
    expect(screen.queryByText("Unlocks after: Filtering")).toBeNull();
  });

  it("is one tab stop; arrow keys move along a branch and round the ring of branches", async () => {
    const user = userEvent.setup();
    open();
    const current = await node(/^Filtering/);
    const graph = screen.getByRole("group", { name: "Skills" });
    const stops = () => skillButtons(graph).filter((b) => b.tabIndex === 0);
    expect(stops()).toEqual([current]);

    current.focus();
    await user.keyboard("{ArrowLeft}"); // back toward the hub
    expect(screen.getByRole("button", { name: /^Selecting rows/ })).toHaveFocus();
    await user.keyboard("{ArrowLeft}"); // the branch's first skill: nowhere to go
    expect(screen.getByRole("button", { name: /^Selecting rows/ })).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(current).toHaveFocus();
    await user.keyboard("{ArrowDown}"); // the next branch, same place along it
    expect(screen.getByRole("button", { name: /^Outer joins/ })).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("button", { name: /^SQL joins/ })).toHaveFocus();
    await user.keyboard("{ArrowUp}"); // the previous branch
    expect(screen.getByRole("button", { name: /^Selecting rows/ })).toHaveFocus();
    await user.keyboard("{End}");
    expect(current).toHaveFocus();
    expect(stops()).toEqual([current]);
    // the arrow keys belong to the skills: on a view control they do nothing here
    screen.getByRole("button", { name: "Zoom in" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("button", { name: "Zoom in" })).toHaveFocus();
  });

  it("Enter opens the skill's panel and lights its route, Esc closes it and focus is back on the node", async () => {
    const user = userEvent.setup();
    open();
    const current = await node(/^Filtering/);
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument(); // no panel until a skill is chosen
    current.focus();
    await user.keyboard("{Enter}");
    expect(current).toHaveAttribute("aria-expanded", "true");
    const panel = screen.getByRole("complementary", { name: "Filtering" });
    expect(current).toHaveAttribute("aria-controls", panel.id);
    expect(within(panel).getByRole("progressbar", { name: "Mastery of Filtering" })).toHaveAttribute("aria-valuenow", "40");
    expect(within(panel).getByRole("link", { name: "WHERE in practice" })).toHaveAttribute("href", "/lessons/l2");
    expect(within(panel).getByText("Being written")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Continue with “WHERE in practice”" })).toHaveAttribute("href", "/lessons/l2");
    expect(within(panel).getByRole("link", { name: "Take the skill test: Filtering" })).toHaveAttribute(
      "href",
      "/paths/p1/skills/s2/test",
    );
    // lit: the skill, what it builds on (its route from the start) and what it unlocks (its own links); the rest
    // steps back
    expect(screen.getByRole("button", { name: /^Selecting rows/ })).not.toHaveAttribute("data-off");
    expect(screen.getByRole("button", { name: /^SQL joins/ })).not.toHaveAttribute("data-off");
    expect(screen.getByRole("button", { name: /^Outer joins/ })).toHaveAttribute("data-off");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Filtering" })).toBeNull();
    expect(current).toHaveFocus();
    expect(current).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: /^Outer joins/ })).not.toHaveAttribute("data-off");

    // Space opens it too
    await user.keyboard(" ");
    expect(screen.getByRole("complementary", { name: "Filtering" })).toBeInTheDocument();
  });

  it("builds on and unlocks select those skills; a locked skill says what unlocks it", async () => {
    const user = userEvent.setup();
    open();
    click(await node(/^Filtering/));
    let panel = screen.getByRole("complementary", { name: "Filtering" });
    expect(within(panel).getByRole("button", { name: "Show on the tree: Selecting rows" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Show on the tree: SQL joins" }));
    panel = screen.getByRole("complementary", { name: "SQL joins" });
    expect(screen.getByRole("button", { name: /^SQL joins/ })).toHaveFocus();
    expect(within(panel).getByText("Unlocks after: Filtering")).toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: /Take the skill test/ })).toBeNull();
    expect(within(panel).getByRole("button", { name: "Generate “Inner joins”" })).toBeInTheDocument();
    // its route runs through its own hub: the skill of the other branch it builds on is lit as its own link
    expect(screen.getByRole("button", { name: /^Filtering/ })).not.toHaveAttribute("data-off");
    expect(screen.getByRole("button", { name: /^Selecting rows/ })).toHaveAttribute("data-off");
  });

  it("frames a branch from its chip and shows the whole tree again", async () => {
    const user = userEvent.setup();
    open();
    await node(/^Filtering/);
    await user.click(screen.getByRole("radio", { name: /^Joins/ }));
    expect(screen.getByRole("button", { name: /^Filtering/ })).toHaveAttribute("data-dim");
    expect(screen.getByRole("button", { name: /^SQL joins/ })).not.toHaveAttribute("data-dim");
    // the frame follows the focus to a skill of another branch
    click(screen.getByRole("button", { name: /^Filtering/ }));
    expect(screen.getByRole("radio", { name: /^Basics/ })).toBeChecked();
    expect(screen.getByRole("button", { name: /^SQL joins/ })).toHaveAttribute("data-dim");
    expect(screen.getByRole("button", { name: /^Filtering/ })).not.toHaveAttribute("data-dim");
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Show the whole tree" }));
    expect(screen.getByRole("button", { name: /^Filtering/ })).not.toHaveAttribute("data-dim");
    expect(screen.queryByRole("button", { name: "Show the whole tree" })).toBeNull();
  });

  it("lets nodes be dragged aside, but not under reduced motion (no live physics)", async () => {
    const first = open();
    const graph = (await node(/^Filtering/)).closest<HTMLElement>("[role='group']")!;
    const wrappers = () => [...graph.querySelectorAll(".react-flow__node")].filter((n) => n.querySelector("[data-skill]"));
    expect(wrappers()).toHaveLength(4);
    for (const w of wrappers()) expect(w).toHaveClass("draggable");
    first.unmount();

    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    open();
    await node(/^Filtering/);
    const still = [...document.querySelectorAll(".react-flow__node")].filter((n) => n.querySelector("[data-skill]"));
    expect(still).toHaveLength(4);
    for (const w of still) expect(w).not.toHaveClass("draggable");
  });

  it("switches to the list and remembers it", async () => {
    const user = userEvent.setup();
    const first = open();
    await node(/^Filtering/);
    const views = screen.getByRole("radiogroup", { name: "Show the skills as" });
    expect(within(views).getByRole("radio", { name: "Tree" })).toBeChecked();
    await user.click(within(views).getByRole("radio", { name: "List" }));
    expect(await screen.findByText("Unlocks after: Filtering")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Skills" })).toBeNull();
    expect(localStorage.getItem("yuo.path.view")).toBe("list");
    first.unmount();

    open();
    expect(await screen.findByText("Unlocks after: Filtering")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "List" })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Tree" }));
    await waitFor(() => expect(screen.getByRole("group", { name: "Skills" })).toBeInTheDocument());
    expect(localStorage.getItem("yuo.path.view")).toBe("tree");
  });
});
