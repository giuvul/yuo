import { forceSimulation } from "d3-force";
import { describe, expect, it } from "vitest";
import { LARGE_TREE, samplePath, SMALL_TREE } from "./fixtures";
import { hubId, START } from "./graph";
import {
  COMPACT,
  forceBoxes,
  hubBox,
  labelLines,
  layoutExtent,
  layoutFor,
  layoutGraph,
  ROOMY,
  skillBox,
  spotsOverlap,
  type Body,
  type GraphLayout,
  wrapWidths,
} from "./radial";

/** Eight branches, and one branch whose twelve skills all grow from its first: the collision pass has work to do. */
const CROWDED = samplePath(
  "sample-crowded",
  "Crowded",
  Array.from({ length: 8 }, (_, b) => ({
    title: `Branch ${b + 1}`,
    skills: Array.from({ length: b === 0 ? 12 : 4 }, (_, s) => ({
      title: `Skill ${b + 1}.${s + 1}`,
      needs: s === 0 ? [] : [b === 0 ? "Skill 1.1" : `Skill ${b + 1}.${s}`],
    })),
  })),
);

const samples = { small: SMALL_TREE.path, large: LARGE_TREE.path, crowded: CROWDED.path };

function overlaps(layout: GraphLayout): string[] {
  const found: string[] = [];
  layout.spots.forEach((a, i) => {
    for (const b of layout.spots.slice(i + 1)) if (spotsOverlap(a, b, layout.gap - 1)) found.push(`${a.id} / ${b.id}`);
  });
  return found;
}

describe("layoutGraph", () => {
  it.each(Object.entries(samples))("%s: places the start, a hub per branch and every skill once", (_name, path) => {
    const layout = layoutGraph(path);
    const skillIds = path.branches.flatMap((b) => b.skills.map((s) => s.id));
    expect(layout.spots.map((s) => s.id)).toEqual([START, ...path.branches.map((b) => hubId(b.id)), ...skillIds]);
    expect(layout.byId.size).toBe(layout.spots.length);
    expect(layout.byId.get(START)).toMatchObject({ kind: "start", x: 0, y: 0 });
    for (const b of path.branches) {
      const hub = layout.hubs.find((h) => h.branchId === b.id)!;
      expect([...hub.skillIds].sort()).toEqual(b.skills.map((s) => s.id).sort());
      for (const s of b.skills) expect(layout.byId.get(s.id)).toMatchObject({ kind: "skill", branchId: b.id });
    }
  });

  it.each(Object.entries(samples))("%s: is deterministic", (_name, path) => {
    expect(layoutGraph(path)).toEqual(layoutGraph(path));
  });

  it.each(Object.entries(samples))("%s: no two nodes touch after the collision pass", (_name, path) => {
    expect(overlaps(layoutGraph(path))).toEqual([]);
  });

  it("puts a hub per branch round the start, evenly spread, the first straight up, each as near as it fits", () => {
    const layout = layoutGraph(LARGE_TREE.path);
    expect(layout.hubs).toHaveLength(5);
    layout.hubs.forEach((hub, i) => {
      const spot = layout.byId.get(hub.id)!;
      expect(Math.hypot(spot.x, spot.y)).toBeCloseTo(hub.reach, 0);
      expect(hub.reach).toBeLessThanOrEqual(layout.hubRing);
      expect(hub.angle).toBeCloseTo(-Math.PI / 2 + (i * 2 * Math.PI) / 5);
      expect(Math.atan2(spot.y, spot.x)).toBeCloseTo(Math.atan2(Math.sin(hub.angle), Math.cos(hub.angle)), 1);
    });
    const top = layout.byId.get(layout.hubs[0]!.id)!;
    expect(top.x).toBeCloseTo(0, 0);
    expect(top.y).toBeLessThan(0);
    // a wide pill needs less room above the start than beside it
    expect(layout.hubs[0]!.reach).toBeLessThan(layout.hubs[1]!.reach);
  });

  it("grows each branch outward in its own direction, in prerequisite order", () => {
    const { path } = LARGE_TREE;
    const layout = layoutGraph(path);
    for (const hub of layout.hubs) {
      const dir = { x: Math.cos(hub.angle), y: Math.sin(hub.angle) };
      const along = (id: string) => layout.byId.get(id)!.x * dir.x + layout.byId.get(id)!.y * dir.y;
      const branch = path.branches.find((b) => b.id === hub.branchId)!;
      const ids = new Set(branch.skills.map((s) => s.id));
      for (const s of branch.skills) {
        // beyond its hub, and beyond what it builds on inside the branch
        expect(along(s.id)).toBeGreaterThan(hub.reach);
        for (const r of s.requires.filter((id) => ids.has(id))) {
          expect(along(s.id)).toBeGreaterThan(along(r));
          expect(hub.skillIds.indexOf(s.id)).toBeGreaterThan(hub.skillIds.indexOf(r));
        }
      }
    }
    for (const s of layout.spots) expect(Math.hypot(s.x, s.y)).toBeLessThanOrEqual(layout.radius);
  });

  it("skips a branch without skills and turns with the start angle", () => {
    const { path } = SMALL_TREE;
    const withEmpty = { ...path, branches: [...path.branches, { id: "empty", code: "E", title: "Empty", skills: [] }] };
    expect(layoutGraph(withEmpty)).toEqual(layoutGraph(path));
    const turned = layoutGraph(path, { startAngle: 0 });
    const first = turned.byId.get(turned.hubs[0]!.id)!;
    expect(first.x).toBeGreaterThan(0);
    expect(first.y).toBeCloseTo(0, 0);
    expect(overlaps(turned)).toEqual([]);
  });

  it("survives a prerequisite cycle and an unknown prerequisite", () => {
    const { path } = samplePath("odd", "Odd", [
      {
        title: "Loop",
        skills: [{ title: "A", needs: ["B"] }, { title: "B", needs: ["A"] }, { title: "C", needs: ["Nowhere"] }],
      },
    ]);
    const layout = layoutGraph(path);
    expect(layout.spots.filter((s) => s.kind === "skill")).toHaveLength(3);
    expect(overlaps(layout)).toEqual([]);
  });
});

describe("layoutFor", () => {
  const wide = { width: 900, height: 480 };
  const tall = { width: 360, height: 600 };
  const fit = (layout: GraphLayout, canvas: { width: number; height: number }) => {
    const extent = layoutExtent(layout);
    return Math.min(canvas.width / extent.width, canvas.height / extent.height);
  };

  it("lays two branches along the longer side of the canvas", () => {
    const { path } = SMALL_TREE;
    const level = layoutExtent(layoutFor(path, { width: 1200, height: 400 }));
    expect(level.width).toBeGreaterThan(level.height);
    const upright = layoutFor(path, tall);
    expect(layoutExtent(upright).height).toBeGreaterThan(layoutExtent(upright).width);
  });

  it("grows a single branch sideways on a wide canvas and up or down on a tall one", () => {
    const only = { title: "Only", skills: [{ title: "A" }, { title: "B", needs: ["A"] }] };
    const { path } = samplePath("one", "One", [only]);
    // a short branch is about as clear upright as sideways on 900 by 480 (the hub is as wide as two skills)
    expect(Math.abs(Math.cos(layoutFor(path, { width: 1200, height: 400 }).hubs[0]!.angle))).toBeCloseTo(1);
    expect(layoutFor(path, tall).hubs[0]!.angle).toBe(-Math.PI / 2); // straight up, the default
  });

  it.each(Object.entries(samples))("%s: never shows the graph smaller than the plain layout would", (_name, path) => {
    for (const canvas of [wide, tall]) {
      expect(fit(layoutFor(path, canvas), canvas)).toBeGreaterThanOrEqual(fit(layoutGraph(path), canvas));
    }
  });

  it("uses a wide canvas: a five-branch path is shown clearly larger than the upright ring would be", () => {
    const canvas = { width: 1000, height: 560 };
    expect(fit(layoutFor(LARGE_TREE.path, canvas), canvas)).toBeGreaterThan(fit(layoutGraph(LARGE_TREE.path), canvas) * 1.1);
  });

  it.each(Object.entries(samples))("%s: is deterministic and still free of overlaps", (_name, path) => {
    for (const canvas of [wide, tall]) {
      expect(layoutFor(path, canvas)).toEqual(layoutFor(path, canvas));
      expect(overlaps(layoutFor(path, canvas))).toEqual([]);
    }
    expect(overlaps(layoutFor(path, tall, true))).toEqual([]); // the narrow nodes of a phone canvas
  });
});

describe("labelLines", () => {
  it("counts the lines a name takes, four at most", () => {
    expect(labelLines("Arrays")).toBe(1);
    expect(labelLines("Sorting and limiting")).toBe(2);
    expect(labelLines("Filtering groups with HAVING")).toBe(3);
    expect(labelLines("Supercalifragilisticexpialidocious and more words still")).toBe(4);
    expect(skillBox("Sorting and limiting").b - skillBox("Arrays").b).toBe(19);
    // the narrow nodes of a phone canvas take more lines for the same name
    expect(labelLines("Sorting and limiting", COMPACT.skill.chars)).toBe(3);
    expect(skillBox("Arrays", COMPACT).r).toBeLessThan(skillBox("Arrays").r);
  });
});

describe("hubBox", () => {
  // one pixel per character at any size: easy to reason about
  const measure = (text: string) => text.length * 8;

  it("is as wide as the branch's name needs, and taller instead of cutting a long one", () => {
    const short = hubBox("SQL", ROOMY, measure);
    const name = hubBox("Keyboard and Rhythm", ROOMY, measure); // 19 characters: 152 px, one line
    const long = hubBox("Keyboard and Rhythm Foundations for Beginners", ROOMY, measure);
    const width = (b: { l: number; r: number }) => b.r - b.l;
    expect(width(short)).toBe(ROOMY.hub.chrome + ROOMY.hub.mark + ROOMY.hub.minText); // the meta line's room
    expect(width(name)).toBe(ROOMY.hub.chrome + ROOMY.hub.mark + 152);
    expect(name.b - name.t).toBe(ROOMY.hub.height);
    expect(width(long)).toBeLessThanOrEqual(ROOMY.hub.chrome + ROOMY.hub.mark + ROOMY.hub.maxText);
    expect(long.b - long.t).toBeGreaterThan(ROOMY.hub.height); // two lines
    expect(wrapWidths("Keyboard and Rhythm Foundations for Beginners", ROOMY.hub.maxText, 15.5, measure)).toHaveLength(2);
  });
});

describe("forceBoxes", () => {
  const box = { l: -50, t: -20, r: 50, b: 20 };

  it("pushes two overlapping boxes apart, and a pinned one stays where it is", () => {
    const pinned: Body = { id: "a", box, x: 0, y: 0, fx: 0, fy: 0 };
    const free: Body = { id: "b", box, x: 10, y: 30 };
    const simulation = forceSimulation([pinned, free]).force("boxes", forceBoxes<Body>(8, 0.7)).stop();
    for (let i = 0; i < 200; i++) simulation.tick();
    expect(pinned).toMatchObject({ x: 0, y: 0 });
    expect(free.y! - 20).toBeGreaterThanOrEqual(20 + 7); // below the pinned one, the gap between them
    expect(free.x).toBeCloseTo(10, 0); // moved along the axis of least overlap only
  });
});
