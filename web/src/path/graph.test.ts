import { describe, expect, it } from "vitest";
import { samplePath, SMALL_TREE } from "./fixtures";
import { graphLinks, hubId, moveFrom, routeTo, skillDepths, START } from "./graph";

const [linear, branching] = SMALL_TREE.path.branches.map((b) => b.id) as [string, string];

/** B and C both build on A, D on both, E on A and on D: two shortest chains to D, one to E. */
const DIAMOND = samplePath("diamond", "Diamond", [
  {
    title: "One",
    skills: [
      { title: "A" },
      { title: "B", needs: ["A"] },
      { title: "C", needs: ["A"] },
      { title: "D", needs: ["B", "C"] },
      { title: "E", needs: ["A", "D"] },
    ],
  },
  { title: "Two", skills: [{ title: "X", needs: ["D"] }] },
]).path;

describe("skillDepths", () => {
  it("is the longest prerequisite chain under each skill", () => {
    expect(Object.fromEntries(skillDepths(DIAMOND))).toEqual({ a: 0, b: 1, c: 1, d: 2, e: 3, x: 3 });
  });
});

describe("graphLinks", () => {
  it("draws a spoke per branch, a stem to each skill that starts its branch, and every prerequisite", () => {
    const links = graphLinks(SMALL_TREE.path);
    expect(links.map((l) => l.id)).toEqual([
      `spoke:${linear}`,
      "stem:arrays",
      `spoke:${branching}`,
      "stem:trees", // builds on a skill of the other branch only: it starts its own
      "arrays>linked-lists",
      "arrays>hash-tables",
      "linked-lists>trees",
      "trees>graphs",
      "hash-tables>graphs",
    ]);
    const link = (id: string) => links.find((l) => l.id === id);
    expect(link(`spoke:${linear}`)).toMatchObject({ source: START, target: hubId(linear), kind: "spoke" });
    expect(link("stem:trees")).toMatchObject({ source: hubId(branching), target: "trees", kind: "stem" });
    expect(links.filter((l) => l.cross).map((l) => l.id)).toEqual(["linked-lists>trees", "hash-tables>graphs"]);
  });

  it("leaves out a branch without skills, unknown prerequisites and a skill that names itself", () => {
    const { path } = samplePath("odd", "Odd", [
      { title: "One", skills: [{ title: "A", needs: ["A", "Nowhere"] }] },
      { title: "Empty", skills: [] },
    ]);
    expect(graphLinks(path).map((l) => l.id)).toEqual([`spoke:${path.branches[0]!.id}`, "stem:a"]);
  });
});

describe("routeTo", () => {
  it("runs from the start through the skill's own hub, never through another branch", () => {
    const route = routeTo(graphLinks(SMALL_TREE.path), "graphs")!;
    expect([...route.nodes].sort()).toEqual([START, hubId(branching), "graphs", "trees"].sort());
    expect([...route.links].sort()).toEqual([`spoke:${branching}`, "stem:trees", "trees>graphs"].sort());
  });

  it("lights every shortest chain and no longer one", () => {
    const links = graphLinks(DIAMOND);
    const toD = routeTo(links, "d")!;
    const spoke = `spoke:${DIAMOND.branches[0]!.id}`;
    expect([...toD.links].sort()).toEqual(["a>b", "a>c", "b>d", "c>d", spoke, "stem:a"].sort());
    const toE = routeTo(links, "e")!;
    expect([...toE.nodes].sort()).toEqual([START, hubId(DIAMOND.branches[0]!.id), "a", "e"].sort());
    expect(toE.links.has("d>e")).toBe(false);
  });

  it("is null for something that is not a skill", () => {
    const links = graphLinks(SMALL_TREE.path);
    expect(routeTo(links, "nowhere")).toBeNull();
    expect(routeTo(links, hubId(linear))).toBeNull();
  });
});

describe("moveFrom", () => {
  const branches = [["a1", "a2", "a3"], ["b1"], ["c1", "c2"]];

  it("moves along a branch with Right and Left, and stops at its ends", () => {
    expect(moveFrom(branches, "a1", "ArrowRight")).toBe("a2");
    expect(moveFrom(branches, "a2", "ArrowLeft")).toBe("a1");
    expect(moveFrom(branches, "a1", "ArrowLeft")).toBeNull();
    expect(moveFrom(branches, "a3", "ArrowRight")).toBeNull();
    expect(moveFrom(branches, "a2", "Home")).toBe("a1");
    expect(moveFrom(branches, "a2", "End")).toBe("a3");
  });

  it("moves round the ring of branches with Down and Up, keeping the place along the branch", () => {
    expect(moveFrom(branches, "a3", "ArrowDown")).toBe("b1");
    expect(moveFrom(branches, "b1", "ArrowDown")).toBe("c1");
    expect(moveFrom(branches, "c2", "ArrowDown")).toBe("a2");
    expect(moveFrom(branches, "a2", "ArrowUp")).toBe("c2");
    expect(moveFrom([["only"]], "only", "ArrowDown")).toBeNull();
    expect(moveFrom(branches, "nowhere", "ArrowDown")).toBeNull();
  });
});
