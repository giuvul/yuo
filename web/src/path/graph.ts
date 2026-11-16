// What the path views ask of the prerequisite graph: a skill's node state, the links the graph view draws, the lit
// route to a selected skill, and where an arrow key leads. Pure functions over the path: no DOM, no layout library
// (the list view and the panel use this file too, and must not pull the graph library in).
import type { PathOut, ProgressOut } from "../api/client";

export type Skill = PathOut["branches"][number]["skills"][number];
/** A skill's node on the vine and on the graph: mastered, the one to learn now, open to learn, or locked. */
export type NodeState = "done" | "current" | "open" | "locked";

const OPEN = new Set<string>(["in_progress", "needs_review", "available"]);

/**
 * Each skill's node, in path order: mastered skills are done, the first open one is the one to learn now.
 * Without progress (not loaded, or no skills tracked yet) the first skill with lessons is current.
 */
export function skillNodes(path: PathOut, progress: ProgressOut | undefined): { nodes: Map<string, NodeState>; current: Skill | null } {
  const nodes = new Map<string, NodeState>();
  let current: Skill | null = null;
  const skills = path.branches.flatMap((b) => b.skills);
  for (const skill of skills) {
    const state = progress?.skills[skill.id]?.state;
    if (state === "mastered") nodes.set(skill.id, "done");
    else if (state === "locked") nodes.set(skill.id, "locked");
    else if (!current && (state ? OPEN.has(state) : skill.lessons.length > 0)) {
      current = skill;
      nodes.set(skill.id, "current");
    } else nodes.set(skill.id, "open");
  }
  return { nodes, current };
}

/** The skills that list `skillId` as a prerequisite, in path order. */
export function unlockedBy(path: PathOut, skillId: string): Skill[] {
  return path.branches.flatMap((b) => b.skills).filter((s) => s.requires.includes(skillId));
}

/** The longest prerequisite chain under each skill (0 = needs nothing). Unknown ids and cycles count as nothing. */
export function skillDepths(path: PathOut): Map<string, number> {
  const skills = new Map<string, Skill>(path.branches.flatMap((b) => b.skills).map((s) => [s.id, s]));
  const depth = new Map<string, number>();
  const open = new Set<string>();
  const visit = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    const skill = skills.get(id);
    if (!skill || open.has(id)) return 0;
    open.add(id);
    let d = 0;
    for (const req of skill.requires) if (skills.has(req) && !open.has(req)) d = Math.max(d, visit(req) + 1);
    open.delete(id);
    depth.set(id, d);
    return d;
  };
  for (const id of skills.keys()) visit(id);
  return depth;
}

/** The node in the centre of the graph: where the path starts. Not a skill. */
export const START = "@start";
/** The node of a branch: its hub on the ring around the start. */
export const hubId = (branchId: string) => `@hub:${branchId}`;

/**
 * A drawn link. "spoke": the start to a branch's hub. "stem": a hub to a skill that needs nothing else on its own
 * branch (where the branch begins). "requires": a prerequisite to the skill that needs it.
 */
export type Link = {
  id: string;
  source: string;
  target: string;
  kind: "spoke" | "stem" | "requires";
  /** the branch of the target */
  branchId: string;
  /** a prerequisite on another branch */
  cross: boolean;
};

/** Every link of the path's graph, in a stable order: per branch its spoke and stems, then the prerequisites. */
export function graphLinks(path: PathOut): Link[] {
  const branchOf = new Map(path.branches.flatMap((b) => b.skills.map((s) => [s.id, b.id] as const)));
  const links: Link[] = [];
  for (const b of path.branches) {
    if (b.skills.length === 0) continue;
    const hub = hubId(b.id);
    links.push({ id: `spoke:${b.id}`, source: START, target: hub, kind: "spoke", branchId: b.id, cross: false });
    for (const s of b.skills) {
      if (s.requires.some((r) => r !== s.id && branchOf.get(r) === b.id)) continue;
      links.push({ id: `stem:${s.id}`, source: hub, target: s.id, kind: "stem", branchId: b.id, cross: false });
    }
  }
  for (const b of path.branches) {
    for (const s of b.skills) {
      for (const r of new Set(s.requires)) {
        const from = branchOf.get(r);
        if (from === undefined || r === s.id) continue;
        const cross = from !== b.id;
        links.push({ id: `${r}>${s.id}`, source: r, target: s.id, kind: "requires", branchId: b.id, cross });
      }
    }
  }
  return links;
}

type Route = {
  /** the start, the branch's hub, the selected skill and the skills on the way */
  nodes: Set<string>;
  /** the lit link ids */
  links: Set<string>;
};

/**
 * The route to a skill: the start, its branch's hub, and every shortest prerequisite chain inside that branch that
 * ends in it (breadth first from the start, then back from the skill along the links that keep the distance
 * shortest: all of them). The route always passes through the skill's own hub, never through another branch.
 */
export function routeTo(links: Link[], skillId: string): Route | null {
  const own = links.find((l) => l.target === skillId && l.kind !== "spoke");
  if (!own) return null;
  const inside = links.filter((l) => l.branchId === own.branchId && !l.cross);
  const out = new Map<string, Link[]>();
  const into = new Map<string, Link[]>();
  for (const l of inside) {
    out.set(l.source, [...(out.get(l.source) ?? []), l]);
    into.set(l.target, [...(into.get(l.target) ?? []), l]);
  }
  const dist = new Map<string, number>([[START, 0]]);
  const queue = [START];
  for (let head = 0; head < queue.length; head++) {
    const at = queue[head]!;
    for (const l of out.get(at) ?? []) {
      if (dist.has(l.target)) continue;
      dist.set(l.target, dist.get(at)! + 1);
      queue.push(l.target);
    }
  }
  const route: Route = { nodes: new Set([skillId]), links: new Set() };
  if (!dist.has(skillId)) return route; // a cycle the planner should never produce: the skill alone
  const frontier = [skillId];
  while (frontier.length > 0) {
    const at = frontier.pop()!;
    for (const l of into.get(at) ?? []) {
      if (dist.get(l.source) !== dist.get(at)! - 1) continue;
      route.links.add(l.id);
      if (!route.nodes.has(l.source)) {
        route.nodes.add(l.source);
        frontier.push(l.source);
      }
    }
  }
  return route;
}

export type MoveKey = "ArrowUp" | "ArrowDown" | "ArrowLeft" | "ArrowRight" | "Home" | "End";
export const MOVE_KEYS: ReadonlySet<string> = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"]);

/**
 * Where an arrow key leads from a skill. `branches` lists each branch's skill ids from its hub outward, in ring
 * order. Right and Left move along the branch: away from the hub and back toward it. Down and Up move to the next
 * and the previous branch round the ring, keeping the place along the branch. Home and End: the branch's first
 * and last skill. The moves follow the path's structure, not the picture, so they stay the same after a node was
 * dragged aside.
 */
export function moveFrom(branches: readonly (readonly string[])[], skillId: string, key: MoveKey): string | null {
  const order = branches.findIndex((ids) => ids.includes(skillId));
  const ids = branches[order];
  if (!ids) return null;
  const rank = ids.indexOf(skillId);
  const other = (step: number): string | null => {
    const b = branches[(order + step + branches.length) % branches.length];
    return b && b !== ids ? (b[Math.min(rank, b.length - 1)] ?? null) : null;
  };
  switch (key) {
    case "Home":
      return ids[0] ?? null;
    case "End":
      return ids[ids.length - 1] ?? null;
    case "ArrowRight":
      return ids[rank + 1] ?? null;
    case "ArrowLeft":
      return ids[rank - 1] ?? null;
    case "ArrowDown":
      return other(1);
    case "ArrowUp":
      return other(-1);
  }
}

const TESTABLE = new Set(["available", "in_progress", "needs_review"]);

/** The skill test checks what was learned, so it is offered once the skill has been started (some mastery), not on
 * a skill still at 0%. */
export function skillTestOffered(p: { state: string; mastery: number; evidence: number } | undefined): boolean {
  return p !== undefined && TESTABLE.has(p.state) && (p.mastery > 0 || p.evidence > 0);
}
