// The layout of the path as a radial graph (the approach of the reference prototype). The start sits in the
// centre, one hub per branch on a ring around it, and each branch grows outward in its own direction: a skill sits
// further out the later it comes in the prerequisite order, and skills that grow side by side fork a little apart.
// A short d3-force pass (boxes that must not touch, pulled back to their target) removes what still overlaps.
//
// A pure function: the same path always gives the same picture. Positions are flow units (CSS pixels at zoom 1)
// and name the centre of a node's round part, where its links meet.
import { forceSimulation, forceX, forceY, type Force, type SimulationNodeDatum } from "d3-force";
import type { PathOut } from "../api/client";
import { hubId, skillDepths, START, type Skill } from "./graph";

/** What a node occupies around its centre: left, top, right, bottom. */
type Box = { l: number; t: number; r: number; b: number };

/**
 * Node sizes. A skill is a 48 px disc with one to four lines of its name under it (16 px type, 19 px lines);
 * a branch's hub is a pill with the branch's name and how far it is, as wide as its name needs (up to `maxText`,
 * then on more lines: never cut). On a narrow canvas (a phone) both are narrower, with the
 * same type: more of the screen is names, so the whole graph can be shown at a readable size.
 */
type Sizes = {
  skill: { width: number; chars: number };
  hub: {
    /** the least height (one line of name) */
    height: number;
    /** the leaf badge, and everything around the text sideways: padding, border, the gap after the badge */
    mark: number;
    chrome: number;
    /** the text column: at least room for "Level 1 · 0 of 3 mastered", at most this before the name wraps */
    minText: number;
    maxText: number;
    /** the name's type and line height, the meta line's height, the padding above and below */
    font: number;
    line: number;
    meta: number;
    padY: number;
  };
  /** the start's round badge */
  start: number;
  /** the least clear space between two nodes */
  gap: number;
};
export const ROOMY: Sizes = {
  skill: { width: 136, chars: 14 },
  hub: { height: 70, mark: 46, chrome: 4 + 14 + 22 + 9, minText: 150, maxText: 230, font: 15.5, line: 17, meta: 15, padY: 12 },
  start: 76,
  gap: 14,
};
export const COMPACT: Sizes = {
  skill: { width: 100, chars: 10 },
  hub: { height: 56, mark: 36, chrome: 4 + 10 + 16 + 7, minText: 112, maxText: 160, font: 14, line: 15, meta: 12, padY: 8 },
  start: 60,
  gap: 9,
};

/** How wide a text is in the hub's name type, in CSS pixels. */
type Measure = (text: string, px: number) => number;

let context: CanvasRenderingContext2D | null | undefined;
/** The browser's own measure of the name (the canvas), a cautious estimate where there is none (tests). */
const measureText: Measure = (text, px) => {
  if (context === undefined) {
    try {
      // jsdom (the tests) has no canvas and says so on every call
      context =
        typeof document === "undefined" || /jsdom/i.test(navigator.userAgent)
          ? null
          : document.createElement("canvas").getContext("2d");
    } catch {
      context = null;
    }
  }
  if (context) {
    context.font = `800 ${px}px "Nunito Variable", Nunito, ui-rounded, system-ui, sans-serif`;
    // a little slack: the web font may not be loaded yet, and a fallback face is narrower or wider
    return context.measureText(text).width * 1.06 + 2;
  }
  return text.length * px * 0.6;
};

/** The name's lines when the text column is at most `max` wide: word by word, a long word on its own lines. */
export function wrapWidths(title: string, max: number, px: number, measure: Measure = measureText): number[] {
  const lines: number[] = [];
  let line = "";
  for (const word of title.trim().split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    if (!line || measure(next, px) <= max) {
      line = next;
      continue;
    }
    lines.push(measure(line, px));
    line = word;
  }
  if (line) {
    const w = measure(line, px);
    // a single word wider than the column breaks inside itself
    for (let left = w; left > 0; left -= max) lines.push(Math.min(left, max));
  }
  return lines;
}
const DISC = 48;
const LABEL = { gap: 5, line: 19 };

/** How many lines a skill's name takes under its node: a cautious count by words, three at most. */
export function labelLines(title: string, chars = ROOMY.skill.chars): number {
  let lines = 1;
  let used = 0;
  for (const word of title.trim().split(/\s+/)) {
    const need = used === 0 ? word.length : used + 1 + word.length;
    if (need <= chars) used = need;
    else {
      // a word longer than a line breaks inside itself
      lines += used === 0 ? Math.ceil(word.length / chars) - 1 : Math.ceil(word.length / chars);
      used = word.length % chars || chars;
    }
  }
  return Math.min(4, lines);
}

/** A skill's box around the centre of its disc: the disc, and its name under it. */
export function skillBox(title: string, sizes: Sizes = ROOMY): Box {
  const height = DISC + LABEL.gap + LABEL.line * labelLines(title, sizes.skill.chars);
  return { l: -sizes.skill.width / 2, t: -DISC / 2, r: sizes.skill.width / 2, b: height - DISC / 2 };
}
/** A branch's hub around its centre: as wide as its name (or the meta line) needs, taller when the name wraps. */
export function hubBox(title: string, sizes: Sizes = ROOMY, measure: Measure = measureText): Box {
  const h = sizes.hub;
  const lines = wrapWidths(title, h.maxText, h.font, measure);
  const text = Math.min(h.maxText, Math.max(h.minText, ...lines));
  const width = Math.ceil(h.chrome + h.mark + text);
  const height = Math.max(h.height, Math.ceil(2 * h.padY + 4 + lines.length * h.line + h.meta));
  return { l: -width / 2, t: -height / 2, r: width / 2, b: height / 2 };
}


export type Spot = {
  id: string;
  kind: "start" | "hub" | "skill";
  /** null for the start */
  branchId: string | null;
  x: number;
  y: number;
  box: Box;
};

type HubSpot = {
  id: string;
  branchId: string;
  /** the direction the branch grows in, radians (0 = right, a quarter turn = down) */
  angle: number;
  /** how far the hub is from the start */
  reach: number;
  /** the branch's skills from the hub outward */
  skillIds: string[];
};

export type GraphLayout = {
  /** the start, the hubs in ring order, then the skills in path order */
  spots: Spot[];
  byId: Map<string, Spot>;
  hubs: HubSpot[];
  /** how far the farthest hub is from the start (a hub sits as close as its direction allows) */
  hubRing: number;
  /** the least clear space between two nodes in this layout */
  gap: number;
  /** everything lies inside this distance from the start */
  radius: number;
};

type Vec = { x: number; y: number };

/** The least distance along `dir` at which box `b` clears box `a` (both around their own centre) by `gap`. */
function clearance(dir: Vec, a: Box, b: Box, gap: number): number {
  const alongX = dir.x > 0 ? a.r - b.l : b.r - a.l;
  const alongY = dir.y > 0 ? a.b - b.t : b.b - a.t;
  const dx = Math.abs(dir.x) > 1e-6 ? (alongX + gap) / Math.abs(dir.x) : Infinity;
  const dy = Math.abs(dir.y) > 1e-6 ? (alongY + gap) / Math.abs(dir.y) : Infinity;
  return Math.min(dx, dy);
}

function overlap(a: Vec & { box: Box }, b: Vec & { box: Box }, gap: number): { x: number; y: number } | null {
  const x = Math.min(a.x + a.box.r, b.x + b.box.r) - Math.max(a.x + a.box.l, b.x + b.box.l) + gap;
  const y = Math.min(a.y + a.box.b, b.y + b.box.b) - Math.max(a.y + a.box.t, b.y + b.box.t) + gap;
  return x > 0 && y > 0 ? { x, y } : null;
}

/** True when two placed nodes are closer than `gap` (0: they touch or cover each other). */
export function spotsOverlap(a: Spot, b: Spot, gap = 0): boolean {
  return overlap(a, b, gap) !== null;
}

export type Body = SimulationNodeDatum & { id: string; box: Box };

const centreX = (n: Body, x: number) => x + (n.box.l + n.box.r) / 2;
const centreY = (n: Body, y: number) => y + (n.box.t + n.box.b) / 2;

/**
 * A d3-force force that keeps node boxes apart: two boxes closer than `gap` are pushed away from each other along
 * the axis on which they overlap least. A pinned node (fx, fy) stays and the other one makes all the room.
 */
export function forceBoxes<T extends Body>(gap: number, strength: number): Force<T, undefined> {
  let nodes: T[] = [];
  const force: Force<T, undefined> = () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]!;
        const b = nodes[j]!;
        const aPinned = a.fx != null;
        const bPinned = b.fx != null;
        if (aPinned && bPinned) continue;
        const at = { x: (a.x ?? 0) + (a.vx ?? 0), y: (a.y ?? 0) + (a.vy ?? 0), box: a.box };
        const bt = { x: (b.x ?? 0) + (b.vx ?? 0), y: (b.y ?? 0) + (b.vy ?? 0), box: b.box };
        const o = overlap(at, bt, gap);
        if (!o) continue;
        const share = aPinned || bPinned ? 1 : 0.5;
        if (o.x < o.y) {
          const sign = centreX(a, at.x) < centreX(b, bt.x) || (centreX(a, at.x) === centreX(b, bt.x) && i < j) ? -1 : 1;
          const push = o.x * strength * share * sign;
          if (!aPinned) a.vx = (a.vx ?? 0) + push;
          if (!bPinned) b.vx = (b.vx ?? 0) - push;
        } else {
          const sign = centreY(a, at.y) < centreY(b, bt.y) || (centreY(a, at.y) === centreY(b, bt.y) && i < j) ? -1 : 1;
          const push = o.y * strength * share * sign;
          if (!aPinned) a.vy = (a.vy ?? 0) + push;
          if (!bPinned) b.vy = (b.vy ?? 0) - push;
        }
      }
    }
  };
  force.initialize = (n) => {
    nodes = n;
  };
  return force;
}

type Target = Body & { tx: number; ty: number; kind: Spot["kind"]; branchId: string | null };

/** What is left after the force pass is moved apart directly, so no two nodes are closer than the gap. */
function separate(nodes: Target[], gap: number): void {
  for (let round = 0; round < 400; round++) {
    let moved = false;
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]!;
        const b = nodes[j]!;
        const aPinned = a.fx != null;
        const bPinned = b.fx != null;
        if (aPinned && bPinned) continue;
        const o = overlap({ x: a.x!, y: a.y!, box: a.box }, { x: b.x!, y: b.y!, box: b.box }, gap);
        if (!o) continue;
        moved = true;
        const share = aPinned || bPinned ? 1 : 0.5;
        if (o.x < o.y) {
          const sign = centreX(a, a.x!) <= centreX(b, b.x!) ? -1 : 1;
          if (!aPinned) a.x = a.x! + sign * (o.x + 0.5) * share;
          if (!bPinned) b.x = b.x! - sign * (o.x + 0.5) * share;
        } else {
          const sign = centreY(a, a.y!) <= centreY(b, b.y!) ? -1 : 1;
          if (!aPinned) a.y = a.y! + sign * (o.y + 0.5) * share;
          if (!bPinned) b.y = b.y! - sign * (o.y + 0.5) * share;
        }
      }
    }
    if (!moved) return;
  }
}

const round1 = (v: number) => Math.round(v * 10) / 10;

type LayoutOptions = {
  /** the direction of the first branch, radians; the others follow clockwise (default: straight up) */
  startAngle?: number;
  /**
   * Leans every branch toward the vertical (more than 1) or the horizontal (less than 1), for a canvas that is
   * much taller or wider than a circle (default 1: the branches are spread evenly)
   */
  lean?: number;
  /**
   * Lets a branch that is one plain chain grow like a vine, its skills alternating left and right of the stem:
   * half as long, twice as wide (default: straight)
   */
  vine?: boolean;
  /** the narrow node sizes of a phone canvas (default: the roomy ones) */
  compact?: boolean;
};

export function layoutGraph(path: PathOut, options: LayoutOptions = {}): GraphLayout {
  const branches = path.branches.filter((b) => b.skills.length > 0);
  const depth = skillDepths(path);
  const count = Math.max(1, branches.length);
  const sector = (2 * Math.PI) / count;
  const first = options.startAngle ?? -Math.PI / 2;
  const lean = options.lean ?? 1;
  const sizes = options.compact ? COMPACT : ROOMY;
  const hubBoxes = branches.map((b) => hubBox(b.title, sizes));
  const START_BOX: Box = { l: -sizes.start / 2, t: -sizes.start / 2, r: sizes.start / 2, b: sizes.start / 2 };
  const GAP = sizes.gap;
  const air = (extra: number) => GAP + Math.round((extra * GAP) / ROOMY.gap);
  const dirs = branches.map((_, i) => {
    const x = Math.cos(first + i * sector);
    const y = Math.sin(first + i * sector) * lean;
    const length = Math.hypot(x, y) || 1;
    return { x: x / length, y: y / length };
  });
  const angles = dirs.map((d) => (lean === 1 ? first + dirs.indexOf(d) * sector : Math.atan2(d.y, d.x)));

  // each hub sits as close to the start as its direction allows (a wide pill needs more room sideways than up
  // or down); all of them move out together until no two hubs touch
  const nearest = dirs.map((dir, i) => clearance(dir, START_BOX, hubBoxes[i]!, air(10)));
  const hubAt = (i: number, k: number) => ({ x: dirs[i]!.x * nearest[i]! * k, y: dirs[i]!.y * nearest[i]! * k, box: hubBoxes[i]! });
  const hubsTouch = (k: number) => dirs.some((_, i) => dirs.some((__, j) => j > i && overlap(hubAt(i, k), hubAt(j, k), GAP)));
  let spread = 1;
  while (hubsTouch(spread) && spread < 40) spread += 0.05;
  const reach = nearest.map((d) => d * spread);
  const hubRing = Math.max(0, ...reach);

  const bodies: Target[] = [
    { id: START, kind: "start", branchId: null, box: START_BOX, x: 0, y: 0, tx: 0, ty: 0, fx: 0, fy: 0 },
  ];
  const hubs: HubSpot[] = [];
  const skillBodies = new Map<string, Target>();

  branches.forEach((branch, order) => {
    const dir = dirs[order]!;
    const side = { x: -dir.y, y: dir.x };
    const hx = dir.x * reach[order]!;
    const hy = dir.y * reach[order]!;
    const hub = { id: hubId(branch.id), kind: "hub" as const, branchId: branch.id, box: hubBoxes[order]! };
    bodies.push({ ...hub, x: hx, y: hy, tx: hx, ty: hy, fx: hx, fy: hy });
    // the branch is spaced for its tallest name
    const boxes = new Map(branch.skills.map((s) => [s.id, skillBox(s.title, sizes)]));
    const tallest = [...boxes.values()].reduce((a, b) => (b.b > a.b ? b : a));

    // depth keeps its order along the branch, but empty levels are dropped: every branch grows straight out of its hub
    const inBranch = new Map<string, Skill>(branch.skills.map((s) => [s.id, s]));
    const index = new Map(branch.skills.map((s, i) => [s.id, i]));
    const depthOf = (id: string) => depth.get(id) ?? 0;
    const levels = [...new Set(branch.skills.map((s) => depthOf(s.id)))].sort((a, b) => a - b);
    const level = (id: string) => levels.indexOf(depthOf(id));

    // a skill hangs under the deepest thing it builds on inside its own branch; without one, under the hub
    const children = new Map<string, Skill[]>();
    const roots: Skill[] = [];
    for (const s of branch.skills) {
      const parent = s.requires
        .filter((r) => inBranch.has(r) && depthOf(r) < depthOf(s.id))
        .sort((a, b) => depthOf(b) - depthOf(a) || index.get(a)! - index.get(b)!)[0];
      if (parent === undefined) roots.push(s);
      else children.set(parent, [...(children.get(parent) ?? []), s]);
    }
    // sideways places: each twig end takes the next one, a skill sits in the middle of what grows from it
    const slot = new Map<string, number>();
    let ends = 0;
    const place = (s: Skill): number => {
      const kids = children.get(s.id) ?? [];
      const at = kids.length === 0 ? ends++ : kids.map(place).reduce((sum, v) => sum + v, 0) / kids.length;
      slot.set(s.id, at);
      return at;
    };
    roots.forEach(place);

    const sideways = Math.max(
      clearance(side, tallest, tallest, air(4)),
      clearance({ x: -side.x, y: -side.y }, tallest, tallest, air(4)),
    );
    // a plain chain may alternate sides: neighbours then clear each other sideways, and only every second
    // skill has to clear the one before it along the stem
    const vine = options.vine === true && ends === 1 && levels.length > 2;
    const step = clearance(dir, tallest, tallest, air(4)) * (vine ? 0.5 : 1);
    const radial = [reach[order]! + clearance(dir, hubBoxes[order]!, tallest, air(6))];
    for (let k = 1; k < levels.length; k++) radial.push(radial[k - 1]! + step);

    for (const s of branch.skills) {
      const r = radial[level(s.id)]!;
      const sway = vine ? (level(s.id) % 2 === 0 ? -0.5 : 0.5) : 0;
      const off = (slot.get(s.id)! - (ends - 1) / 2 + sway) * sideways;
      const tx = dir.x * r + side.x * off;
      const ty = dir.y * r + side.y * off;
      const box = boxes.get(s.id)!;
      const body: Target = { id: s.id, kind: "skill", branchId: branch.id, box, x: tx, y: ty, tx, ty };
      skillBodies.set(s.id, body);
    }
    hubs.push({
      id: hubId(branch.id),
      branchId: branch.id,
      angle: angles[order]!,
      reach: reach[order]!,
      skillIds: branch.skills
        .map((s) => s.id)
        .sort((a, b) => level(a) - level(b) || slot.get(a)! - slot.get(b)! || index.get(a)! - index.get(b)!),
    });
  });
  for (const b of path.branches) for (const s of b.skills) bodies.push(skillBodies.get(s.id)!);

  const simulation = forceSimulation(bodies)
    .force("x", forceX<Target>((d) => d.tx).strength(0.2))
    .force("y", forceY<Target>((d) => d.ty).strength(0.2))
    .force("boxes", forceBoxes<Target>(GAP, 0.7))
    .stop();
  for (let i = 0; i < 240; i++) simulation.tick();
  separate(bodies, GAP);

  const spots: Spot[] = bodies.map((b) => ({
    id: b.id,
    kind: b.kind,
    branchId: b.branchId,
    x: round1(b.x ?? b.tx),
    y: round1(b.y ?? b.ty),
    box: b.box,
  }));
  let radius = hubRing + Math.max(0, ...hubBoxes.map((b) => b.r));
  for (const s of spots) {
    const reach = Math.hypot(Math.max(-s.x - s.box.l, s.x + s.box.r), Math.max(-s.y - s.box.t, s.y + s.box.b));
    radius = Math.max(radius, reach);
  }
  return { spots, byId: new Map(spots.map((s) => [s.id, s])), hubs, hubRing, gap: GAP, radius: Math.ceil(radius) };
}

/** The size of the box around everything in a layout. */
export function layoutExtent(layout: GraphLayout): { width: number; height: number } {
  let l = Infinity;
  let t = Infinity;
  let r = -Infinity;
  let b = -Infinity;
  for (const s of layout.spots) {
    l = Math.min(l, s.x + s.box.l);
    t = Math.min(t, s.y + s.box.t);
    r = Math.max(r, s.x + s.box.r);
    b = Math.max(b, s.y + s.box.b);
  }
  return { width: Math.max(1, r - l), height: Math.max(1, b - t) };
}

/**
 * The layout that suits a canvas of the given shape: the one that lets the whole graph be shown largest. The ring
 * of branches is tried turned in small steps, leaned toward the canvas's longer side, and with plain chains grown
 * as vines, so a wide canvas gets a wide graph and a tall phone screen a tall one. Straight up and evenly spread
 * wins unless another way is clearly better.
 */
export function layoutFor(path: PathOut, canvas: { width: number; height: number }, compact = false): GraphLayout {
  const fit = (layout: GraphLayout) => {
    const extent = layoutExtent(layout);
    return Math.min(canvas.width / extent.width, canvas.height / extent.height);
  };
  let best = layoutGraph(path, { compact });
  let bestFit = fit(best);
  const count = best.hubs.length;
  if (count === 0) return best;
  const skills = best.spots.length;
  // fewer tries for a very large path: each one runs the collision pass
  const turns = skills > 60 ? 4 : count <= 4 ? 4 * count : 2 * count;
  const shape = canvas.height / canvas.width;
  const leans = skills > 60 ? [1, shape] : [1, 0.5, 1.5, 2, 3].map((power) => shape ** power).concat(1);
  for (const vine of [false, true]) {
    for (const lean of leans) {
      for (let k = 0; k < turns; k++) {
        if (!vine && lean === 1 && k === 0) continue; // the plain layout, tried first
        const layout = layoutGraph(path, { startAngle: -Math.PI / 2 + (k * 2 * Math.PI) / turns, lean, vine, compact });
        const f = fit(layout);
        if (f > bestFit * 1.03) {
          best = layout;
          bestFit = f;
        }
      }
    }
  }
  return best;
}
