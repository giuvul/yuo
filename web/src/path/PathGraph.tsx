// The path as a node graph (the approach of the reference prototype, in Yuo's Grove look): a canvas that pans and
// zooms, the start in the centre, one hub per branch on a ring, the skills growing outward (radial.ts). Selecting
// a skill lights its own links and every shortest prerequisite chain from the start to it, and opens its panel: a
// column beside the canvas when there is room, a bottom sheet otherwise. Choosing a hub or a branch chip frames
// that branch. Nodes can be dragged aside: a small force simulation makes the neighbours give way and pulls
// everything back afterwards; positions are decoration and never saved.
//
// Built on @xyflow/react and d3-force; this file is loaded on demand (LazyPathGraph.tsx), so the list view and the
// other pages do not pay for the library. Skills are real buttons inside the library's nodes: they carry the full
// accessible name, one tab stop and the arrow keys. Under reduced motion nothing moves by itself: no dragging
// physics, no animated framing, no pulsing.
//
// Scrolling. The canvas has a fixed height, most of the screen but never all of it, so there is always page above
// and below it to scroll by. Inside it one finger (or a mouse drag) pans and two fingers pinch: a canvas that
// could not be panned by touch would be of no use. The mouse wheel over the canvas zooms it, like any map; the
// page scrolls by the wheel outside the canvas, which never fills the screen.
import { Trans, useLingui } from "@lingui/react/macro";
import { useLingui as useLinguiRuntime } from "@lingui/react";
import {
  ControlButton,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
  type Viewport,
} from "@xyflow/react";
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { ToggleButton, ToggleButtonGroup } from "react-aria-components";
import type { JobRef, PathOut, ProgressOut } from "../api/client";
import { LeafIcon } from "../components/icons";
import { Seedling } from "../components/illustrations";
import { SKILL_STATE } from "../components/labels";
import { Button } from "../components/ui";
import {
  graphLinks,
  hubId,
  MOVE_KEYS,
  moveFrom,
  routeTo,
  skillNodes,
  type Link,
  type MoveKey,
  type Skill,
} from "./graph";
import { layoutFor } from "./radial";
import { SkillPanel } from "./SkillPanel";
import { useForceLayout, placeOf } from "./useForceLayout";
import { BELOW, FALLBACK_SIZE, firstView, frame, MAX_ZOOM, MIN_ZOOM, padOf, roomOn, useRoom, type Size } from "./viewport";
import { useReducedMotion } from "../motion";
import { lessonBadge, NodeDisc, nodeKind, NodeSample, type Badge, type NodeKind } from "./TreeNode";
import "./flow.css";
import styles from "./PathGraph.module.css";

const FRAME_MS = 600;
const RINGS = "@rings";
/** Drawn for the eye only: the hubs, the start, the rings and the links say nothing a skill's name does not. */
const HIDDEN = { "aria-hidden": true } as const;

type Growth = "grown" | "alive" | "dormant";

type SkillData = {
  title: string;
  /** the accessible name: title, state, mastery, what it needs */
  name: string;
  kind: NodeKind;
  current: boolean;
  mastery: number | undefined;
  badge: Badge;
  selected: boolean;
  off: boolean;
  dim: boolean;
  tabStop: boolean;
  panelId: string;
};
type HubData = {
  title: string;
  level: number | undefined;
  /** undefined while progress is loading */
  mastered: number | undefined;
  total: number;
  framed: boolean;
  dim: boolean;
};
type StartData = { dim: boolean };
type RingsData = { size: number; radii: number[] };
type VineData = { kind: Link["kind"]; cross: boolean; growth: Growth; lit: "route" | "own" | null; faded: boolean };

type SkillFlowNode = Node<SkillData, "skill">;
type HubFlowNode = Node<HubData, "hub">;
type StartFlowNode = Node<StartData, "start">;
type RingsFlowNode = Node<RingsData, "rings">;
type FlowNode = SkillFlowNode | HubFlowNode | StartFlowNode | RingsFlowNode;
type VineFlowEdge = Edge<VineData, "vine">;

/** What a skill's button tells the graph. Stable for the life of the graph, so nodes do not redraw for it. */
type Actions = {
  register: (id: string, el: HTMLButtonElement | null) => void;
  select: (id: string) => void;
  focused: (id: string) => void;
};
const ActionsContext = createContext<Actions | null>(null);

/* ------------------------------------------------------------------------------------------------ nodes */

/** Both ends of every link meet in the middle of the node's round part; the handles themselves are not shown. */
function Anchors() {
  return (
    <>
      <Handle type="target" position={Position.Top} className={styles.anchor} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} className={styles.anchor} isConnectable={false} />
    </>
  );
}

const SkillNode = memo(function SkillNode({ id, data }: NodeProps<SkillFlowNode>) {
  const actions = useContext(ActionsContext);
  return (
    <>
      <Anchors />
      <button
        ref={(el) => actions?.register(id, el)}
        type="button"
        className={styles.skill}
        data-skill={id}
        data-kind={data.kind}
        data-selected={data.selected || undefined}
        data-off={data.off || undefined}
        data-dim={data.dim || undefined}
        tabIndex={data.tabStop ? 0 : -1}
        aria-label={data.name}
        aria-expanded={data.selected}
        aria-controls={data.selected ? data.panelId : undefined}
        onClick={() => actions?.select(id)}
        onFocus={() => actions?.focused(id)}
      >
        <NodeDisc kind={data.kind} current={data.current} mastery={data.mastery} badge={data.badge} />
        <span className={styles.label} aria-hidden="true">
          {data.title}
        </span>
      </button>
    </>
  );
});

/** A branch's hub. The branch chips above the canvas do the same for keyboards and screen readers. */
const HubNode = memo(function HubNode({ data }: NodeProps<HubFlowNode>) {
  const { level, mastered, total } = data;
  return (
    <div className={styles.hub} data-framed={data.framed || undefined} data-dim={data.dim || undefined}>
      <Anchors />
      <span className={styles.hubMark}>
        <LeafIcon size="1.25rem" />
      </span>
      <span className={styles.hubText}>
        <span className={styles.hubTitle}>{data.title}</span>
        <span className={styles.hubMeta}>
          {level !== undefined ? (
            <span className={styles.hubLevel}>
              <Trans id="path.branch.level">Level {level}</Trans>
            </span>
          ) : null}
          {mastered !== undefined ? (
            <span>
              <Trans id="path.tree.branch.mastered">
                {mastered} of {total} mastered
              </Trans>
            </span>
          ) : null}
        </span>
      </span>
    </div>
  );
});

const StartNode = memo(function StartNode({ data }: NodeProps<StartFlowNode>) {
  return (
    <div className={styles.start} data-dim={data.dim || undefined}>
      <Anchors />
      <Seedling width={46} />
      <span className={styles.startLabel}>
        <Trans id="path.tree.start">Start</Trans>
      </span>
    </div>
  );
});

/** Faint growth rings behind everything: the hubs' ring and the depths beyond it. */
const RingsNode = memo(function RingsNode({ data }: NodeProps<RingsFlowNode>) {
  const c = data.size / 2;
  return (
    <svg className={styles.rings} width={data.size} height={data.size} aria-hidden="true" focusable="false">
      {data.radii.map((r) => (
        <circle key={r} cx={c} cy={c} r={r} />
      ))}
    </svg>
  );
});

const nodeTypes = { skill: SkillNode, hub: HubNode, start: StartNode, rings: RingsNode };

/* ------------------------------------------------------------------------------------------------ links */

/**
 * A link as a living line between two node centres: a slight S inside a branch, one gentle arc across branches.
 * The lit route is drawn twice, pollen over a darker edge, so it reads on a light page too (3:1).
 */
function VineEdge({ sourceX, sourceY, targetX, targetY, data }: EdgeProps<VineFlowEdge>) {
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  let d: string;
  if (data?.cross) {
    const bend = 0.14;
    const c = `${(sourceX + targetX) / 2 - dy * bend} ${(sourceY + targetY) / 2 + dx * bend}`;
    d = `M${sourceX} ${sourceY}Q${c} ${targetX} ${targetY}`;
  } else {
    const sway = 0.09;
    const c1 = `${sourceX + dx / 3 - dy * sway} ${sourceY + dy / 3 + dx * sway}`;
    const c2 = `${sourceX + (2 * dx) / 3 + dy * sway} ${sourceY + (2 * dy) / 3 - dx * sway}`;
    d = `M${sourceX} ${sourceY}C${c1} ${c2} ${targetX} ${targetY}`;
  }
  return (
    <>
      {data?.lit === "route" ? <path className={styles.vineRim} d={d} /> : null}
      <path
        className={styles.vine}
        d={d}
        data-kind={data?.kind}
        data-cross={data?.cross || undefined}
        data-growth={data?.growth}
        data-lit={data?.lit ?? undefined}
        data-faded={data?.faded || undefined}
      />
    </>
  );
}

const edgeTypes = { vine: VineEdge };

/* ------------------------------------------------------------------------------------------------ view */

function Legend() {
  return (
    <ul className={styles.legend}>
      <li>
        <NodeSample kind="done" small>
          <Trans id="path.tree.legend.done">Mastered</Trans>
        </NodeSample>
      </li>
      <li>
        <NodeSample kind="current" small>
          <Trans id="path.tree.legend.current">Learning now</Trans>
        </NodeSample>
      </li>
      <li>
        <NodeSample kind="open" small>
          <Trans id="path.tree.legend.open">Open</Trans>
        </NodeSample>
      </li>
      <li>
        <NodeSample kind="locked" small>
          <Trans id="path.tree.legend.locked">Locked</Trans>
        </NodeSample>
      </li>
      <li>
        <NodeSample kind="review" small>
          <Trans id="path.tree.legend.review">Needs review</Trans>
        </NodeSample>
      </li>
    </ul>
  );
}

/** How a node looks on the overview map. */
const MAP_SKILL: Record<NodeKind, string> = {
  done: styles.mapDone!,
  review: styles.mapDone!,
  current: styles.mapCurrent!,
  open: styles.mapOpen!,
  locked: styles.mapLocked!,
};
const MAP_OTHER: Record<string, string> = { hub: styles.mapHub!, start: styles.mapHub!, rings: styles.mapHidden! };

const mapClass = (n: Node): string =>
  n.type === "skill" ? MAP_SKILL[(n.data as SkillData).kind] : (MAP_OTHER[n.type ?? "rings"] ?? "");

const FitIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
  </svg>
);
const ExpandIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7" />
  </svg>
);
const ShrinkIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M20 10h-6V4M14 10l7-7M4 14h6v6M10 14l-7 7" />
  </svg>
);

export type PathGraphProps = {
  path: PathOut;
  progress: ProgressOut | undefined;
  /** the latest job per `${kind}:${target id}`: a failed lesson's job shows under its row in the panel */
  latest?: Map<string, JobRef>;
  /** keeps the graph inside its parent's width (a sample on a page) instead of using the room beside the page */
  contained?: boolean;
  /**
   * Extra content at the end of a skill's panel: the path page puts the skill's memory and "Review this skill"
   * there (review/Hub.tsx).
   */
  renderExtra?: (skillId: string) => ReactNode;
};

export default function PathGraph(props: PathGraphProps) {
  if (!props.path.branches.some((b) => b.skills.length > 0)) return null;
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}

function Graph({ path, progress, latest, contained, renderExtra }: PathGraphProps) {
  const { t } = useLingui();
  const { i18n } = useLinguiRuntime();
  const flow = useReactFlow<FlowNode, VineFlowEdge>();
  const uid = useId();
  const hintId = `${uid}-hint`;
  const panelId = `${uid}-panel`;
  const areaRef = useRef<HTMLElement>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const panelTitle = useRef<HTMLHeadingElement>(null);
  const { side, size } = useRoom(areaRef, canvasRef);
  const reduced = useReducedMotion();
  const duration = reduced ? 0 : FRAME_MS;

  // laid out for the canvas as it is when the graph opens; a later resize does not shuffle the picture
  const shape = useRef<Size | null>(null);
  if (size && !shape.current) shape.current = size;
  const opened = shape.current;
  // a narrow canvas (the phone's) gets narrower nodes with the same type, so the whole graph stays readable
  const layout = useMemo(() => layoutFor(path, roomOn(opened ?? FALLBACK_SIZE, side), !side), [path, opened, side]);
  const links = useMemo(() => graphLinks(path), [path]);
  const { nodes: states, current } = useMemo(() => skillNodes(path, progress), [path, progress]);
  const skills = useMemo(() => new Map(path.branches.flatMap((b) => b.skills).map((s) => [s.id, s])), [path]);
  const branchOf = useMemo(
    () => new Map(path.branches.flatMap((b) => b.skills.map((s) => [s.id, b.id] as const))),
    [path],
  );
  const order = useMemo(() => layout.hubs.map((h) => h.skillIds), [layout]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [framedBranch, setFramedBranch] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const selected = selectedId !== null && skills.has(selectedId) ? selectedId : null;
  const framed = framedBranch !== null && layout.byId.has(hubId(framedBranch)) ? framedBranch : null;
  const framedNow = useRef(framed);
  useEffect(() => {
    framedNow.current = framed;
  }, [framed]);
  const active = activeId !== null && skills.has(activeId) ? activeId : (current?.id ?? order[0]?.[0] ?? null);

  const { centre, onNodesChange, onNodeDragStop, measured } = useForceLayout<FlowNode>(layout, links);

  // --- the view: framing, and keeping a node in sight
  const show = useCallback(
    (ids: Iterable<string>, pad: number, below: number) => {
      const el = canvasRef.current;
      const now = el && el.clientWidth > 0 ? { width: el.clientWidth, height: el.clientHeight } : FALLBACK_SIZE;
      void flow.setViewport(frame(layout, ids, now, pad, below), { duration });
    },
    [flow, layout, duration],
  );
  const showAll = useCallback(() => show(layout.byId.keys(), padOf(side), BELOW), [show, layout, side]);

  /** Moves the view only when the node is not comfortably inside the canvas, and then no further than needed. */
  const keepInSight = useCallback(
    (id: string) => {
      const el = canvasRef.current;
      const c = centre(id);
      if (!el || !c || el.clientWidth === 0) return;
      const { x, y, zoom } = flow.getViewport();
      if (zoom < 0.5) {
        void flow.setCenter(c.x, c.y + 30, { zoom: 0.8, duration });
        return;
      }
      // the node's box on the canvas, with some air; the bottom strip belongs to the controls and the map
      const air = 16;
      const box = layout.byId.get(id)?.box;
      if (!box) return;
      const left = (c.x + box.l) * zoom + x - air;
      const right = (c.x + box.r) * zoom + x + air;
      const top = (c.y + box.t) * zoom + y - air;
      const bottom = (c.y + box.b) * zoom + y + air;
      const floor = el.clientHeight - BELOW;
      const dx = left < 0 ? -left : right > el.clientWidth ? el.clientWidth - right : 0;
      const dy = top < 0 ? -top : bottom > floor ? floor - bottom : 0;
      if (dx !== 0 || dy !== 0) void flow.setViewport({ x: x + dx, y: y + dy, zoom }, { duration });
    },
    [flow, centre, duration, layout],
  );

  const select = useCallback(
    (id: string, how: "node" | "panel" = "node") => {
      setSelectedId(id);
      setActiveId(id);
      // a skill on another branch than the framed one: the frame goes, so its route can be seen
      setFramedBranch((b) => (b !== null && branchOf.get(id) !== b ? null : b));
      if (how === "panel" && side) buttons.current.get(id)?.focus({ preventScroll: true });
      if (side) keepInSight(id); // under the sheet the node is brought into the part that stays visible
    },
    [branchOf, side, keepInSight],
  );
  const close = useCallback(() => {
    if (selected) {
      buttons.current.get(selected)?.focus({ preventScroll: true });
      keepInSight(selected);
    }
    setSelectedId(null);
  }, [selected, keepInSight]);

  const frameBranch = useCallback(
    (branchId: string | null) => {
      setFramedBranch(branchId);
      const hub = layout.hubs.find((h) => h.branchId === branchId);
      if (hub) show([hub.id, ...hub.skillIds], side ? 36 : 18, BELOW);
      else showAll();
    },
    [layout, show, showAll, side],
  );

  const actions = useMemo<Actions>(
    () => ({
      register: (id, el) => {
        if (el) buttons.current.set(id, el);
        else buttons.current.delete(id);
      },
      select: (id) => select(id),
      focused: (id) => {
        setActiveId(id);
        const branch = branchOf.get(id) ?? null;
        // with a branch framed, the frame follows the focus to another branch
        if (framedNow.current !== null && branch !== null && framedNow.current !== branch) frameBranch(branch);
        // only a keyboard move can land on a node outside the view
        else if (buttons.current.get(id)?.matches(":focus-visible")) keepInSight(id);
      },
    }),
    [select, branchOf, keepInSight, frameBranch],
  );

  // beside the canvas, the panel takes room from it when it opens and gives it back when it closes: the picture
  // keeps its middle in the middle, and a chosen node stays in sight
  const lastWidth = useRef<number | null>(null);
  useEffect(() => {
    if (!size) return;
    const before = lastWidth.current;
    lastWidth.current = size.width;
    if (before === null || before === size.width || !side) return;
    const v = flow.getViewport();
    void flow.setViewport({ ...v, x: v.x + (size.width - before) / 2 });
    if (selected) keepInSight(selected);
  }, [size?.width]); // only a change of width moves the view

  // the sheet covers the lower part of the screen: focus moves into it, and the node is brought into the part of
  // the canvas that stays visible above it
  useEffect(() => {
    if (!selected || side) return;
    panelTitle.current?.focus({ preventScroll: true });
    const el = canvasRef.current;
    const sheet = document.getElementById(panelId)?.getBoundingClientRect();
    const c = centre(selected);
    if (!el || !sheet || !c) return;
    const HEADER = 76; // the sticky page header
    let box = el.getBoundingClientRect();
    if (sheet.top - Math.max(box.top, HEADER) < 200 && !document.fullscreenElement) {
      window.scrollBy({ top: box.top - HEADER - 8 });
      box = el.getBoundingClientRect();
    }
    const top = Math.max(box.top, document.fullscreenElement ? 0 : HEADER);
    // the sheet is still sliding up by its entry distance (1.5rem) when this runs
    const bottom = Math.min(box.bottom, sheet.top - 24);
    const zoom = Math.max(0.7, Math.min(1, flow.getZoom()));
    const middle = (top + bottom) / 2 - box.top - 30 * zoom;
    void flow.setViewport({ x: box.width / 2 - c.x * zoom, y: middle - c.y * zoom, zoom }, { duration });
  }, [selected, side, panelId, centre, flow, duration]);

  // --- full screen: the browser's own, or a fixed overlay where there is none
  const toggleFull = () => {
    if (full) {
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
      setFull(false);
      return;
    }
    setFull(true);
    const el = gridRef.current;
    if (el && typeof el.requestFullscreen === "function") void el.requestFullscreen().catch(() => undefined);
  };
  useEffect(() => {
    const onChange = () => {
      if (!document.fullscreenElement) setFull(false);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && !e.defaultPrevented) {
      if (selected) {
        e.preventDefault();
        close();
      } else if (full) {
        e.preventDefault();
        toggleFull();
      }
      return;
    }
    const onSkill = e.target instanceof HTMLElement && e.target.dataset["skill"] !== undefined;
    if (!onSkill || !MOVE_KEYS.has(e.key) || e.altKey || e.ctrlKey || e.metaKey || !active) return;
    e.preventDefault();
    const next = moveFrom(order, active, e.key as MoveKey);
    if (next) buttons.current.get(next)?.focus({ preventScroll: true });
  };

  const name = (skill: Skill): string => {
    const sp = progress?.skills[skill.id];
    const parts = [skill.title];
    const stateName = sp ? SKILL_STATE[sp.state] : undefined;
    if (stateName) parts.push(i18n._(stateName).toLowerCase());
    if (states.get(skill.id) === "current") parts.push(t({ id: "path.tree.node.current", message: "learning now" }));
    if (sp && sp.state !== "locked") {
      const percent = Math.round(sp.mastery * 100);
      parts.push(t({ id: "path.tree.node.mastery", message: `mastery ${percent}%` }));
    }
    if (skill.requires.length > 0) {
      const names = skill.requires.map((id) => skills.get(id)?.title ?? id).join(", ");
      parts.push(t({ id: "path.tree.node.needs", message: `needs: ${names}` }));
    }
    const badge = lessonBadge(skill);
    if (badge === "writing") parts.push(t({ id: "path.tree.node.writing", message: "a lesson is being written" }));
    if (badge === "failed") parts.push(t({ id: "path.tree.node.failed", message: "a lesson could not be written" }));
    return parts.join(", ");
  };

  // --- what is lit: the route to the selected skill, and its own links with the skills at their other ends
  const lit = useMemo(() => {
    const route = selected ? routeTo(links, selected) : null;
    if (!selected || !route) return null;
    const own = new Set<string>();
    const nodes = new Set(route.nodes);
    for (const l of links) {
      if (l.source !== selected && l.target !== selected) continue;
      own.add(l.id);
      nodes.add(l.source);
      nodes.add(l.target);
    }
    return { route: route.links, own, nodes };
  }, [links, selected]);

  const levels = new Map((progress?.branches ?? []).map((b) => [b.id, b.level]));
  // how alive a link is: it leads to a mastered skill, to one that is open, or to a locked one (a spoke: the best
  // of its branch)
  const growth = useMemo(() => {
    const of = new Map<string, Growth>();
    for (const b of path.branches) {
      const all = b.skills.map((s): Growth => {
        const state = progress?.skills[s.id]?.state;
        const g = state === "mastered" || state === "needs_review" ? "grown" : state === "locked" ? "dormant" : "alive";
        of.set(s.id, g);
        return g;
      });
      of.set(hubId(b.id), all.includes("grown") ? "grown" : all.includes("alive") ? "alive" : "dormant");
    }
    return of;
  }, [path, progress]);

  const ringSize = 2 * layout.radius;
  // three faint growth rings, for depth only
  const radii = [0.36, 0.68, 1].map((share) => Math.round(layout.radius * share));

  const nodes: FlowNode[] = [
    {
      id: RINGS,
      type: "rings",
      position: { x: -layout.radius, y: -layout.radius },
      data: { size: ringSize, radii },
      width: ringSize,
      height: ringSize,
      measured: measured.current.get(RINGS),
      draggable: false,
      selectable: false,
      focusable: false,
      zIndex: -1,
      style: { pointerEvents: "none" },
      domAttributes: HIDDEN,
    },
  ];
  for (const spot of layout.spots) {
    const c = centre(spot.id) ?? spot;
    const { ox, oy, width, height } = placeOf(spot.box);
    const base = {
      id: spot.id,
      position: { x: c.x - ox, y: c.y - oy },
      width,
      height,
      measured: measured.current.get(spot.id),
      selectable: false,
      focusable: false,
    };
    if (spot.kind === "start") {
      nodes.push({ ...base, type: "start", zIndex: 10, data: { dim: framed !== null }, domAttributes: HIDDEN });
    } else if (spot.kind === "hub") {
      const branch = path.branches.find((b) => b.id === spot.branchId)!;
      nodes.push({
        ...base,
        type: "hub",
        zIndex: 10,
        data: {
          title: branch.title,
          level: levels.get(branch.id),
          mastered: progress
            ? branch.skills.filter((s) => progress.skills[s.id]?.state === "mastered").length
            : undefined,
          total: branch.skills.length,
          framed: framed === branch.id,
          dim: (framed !== null && framed !== branch.id) || (lit !== null && !lit.nodes.has(spot.id)),
        },
        domAttributes: HIDDEN,
      });
    } else {
      const skill = skills.get(spot.id)!;
      const sp = progress?.skills[spot.id];
      const state = states.get(spot.id);
      nodes.push({
        ...base,
        type: "skill",
        zIndex: spot.id === selected ? 20 : 10,
        data: {
          title: skill.title,
          name: name(skill),
          kind: nodeKind(state, sp),
          current: state === "current",
          mastery: sp?.mastery,
          badge: lessonBadge(skill),
          selected: spot.id === selected,
          off: lit !== null && !lit.nodes.has(spot.id),
          dim: framed !== null && spot.branchId !== framed,
          tabStop: spot.id === active,
          panelId,
        },
      });
    }
  }

  const edges = useMemo<VineFlowEdge[]>(
    () =>
      links.map((l) => {
        const mark = lit?.route.has(l.id) ? "route" : lit?.own.has(l.id) ? "own" : null;
        const outside = framed !== null && l.branchId !== framed && branchOf.get(l.source) !== framed;
        return {
          id: l.id,
          source: l.source,
          target: l.target,
          type: "vine",
          zIndex: mark === "route" ? 2 : mark === "own" ? 1 : 0,
          focusable: false,
          selectable: false,
          ariaRole: "presentation",
          domAttributes: HIDDEN,
          data: {
            kind: l.kind,
            cross: l.cross,
            growth: growth.get(l.target) ?? "alive",
            lit: mark,
            faded: mark === null && (lit !== null || outside),
          },
        };
      }),
    [links, lit, framed, branchOf, growth],
  );

  // where the view starts: worked out once, when the canvas's size is first known
  const opening = useRef<(Viewport & { partial: boolean }) | null>(null);
  if (size && !opening.current) opening.current = firstView(layout, size, current?.id ?? null, side, !!contained);
  // the overview map is only worth its corner while part of the graph is out of sight
  const [whole, setWhole] = useState(true);
  const [moved, setMoved] = useState(false);
  const partialNow = opening.current?.partial ?? false;
  useEffect(() => {
    if (partialNow) setWhole(false);
  }, [partialNow]);
  const onMoveEnd = useCallback(
    (_e: unknown, view: Viewport) => {
      const el = canvasRef.current;
      if (!el || el.clientWidth === 0) return;
      const inside = layout.spots.every(
        (s) =>
          (s.x + s.box.l) * view.zoom + view.x >= -1 &&
          (s.x + s.box.r) * view.zoom + view.x <= el.clientWidth + 1 &&
          (s.y + s.box.t) * view.zoom + view.y >= -1 &&
          (s.y + s.box.b) * view.zoom + view.y <= el.clientHeight + 1,
      );
      setWhole(inside);
      setMoved(true);
    },
    [layout],
  );
  const chromeLabels = useMemo(
    () => ({
      "controls.ariaLabel": t({ id: "path.tree.controls.label", message: "View controls" }),
      "controls.zoomIn.ariaLabel": t({ id: "path.tree.controls.zoom-in", message: "Zoom in" }),
      "controls.zoomOut.ariaLabel": t({ id: "path.tree.controls.zoom-out", message: "Zoom out" }),
      "minimap.ariaLabel": t({ id: "path.tree.minimap.label", message: "Overview of the tree" }),
    }),
    [t],
  );
  const selectedSkill = selected ? (skills.get(selected) ?? null) : null;

  return (
    <section
      ref={areaRef}
      className={styles.area}
      data-mode={side ? "side" : "sheet"}
      data-contained={contained || undefined}
      aria-label={t({ id: "path.tree.label", message: "Skill tree" })}
    >
      <div className={styles.chips}>
        <ToggleButtonGroup
          className={styles.chipGroup}
          selectionMode="single"
          selectedKeys={framed ? [framed] : []}
          onSelectionChange={(keys) => frameBranch(([...keys][0] as string | undefined) ?? null)}
          aria-label={t({ id: "path.tree.branches.label", message: "Show one branch" })}
        >
          {path.branches
            .filter((b) => b.skills.length > 0)
            .map((b) => (
              <BranchChip key={b.id} branch={b} level={levels.get(b.id)} progress={progress} />
            ))}
        </ToggleButtonGroup>
        {framed ? (
          <Button small variant="ghost" onPress={() => frameBranch(null)}>
            <Trans id="path.tree.branches.all">Show the whole tree</Trans>
          </Button>
        ) : null}
      </div>

      {partialNow && !moved ? (
        <p className={styles.note}>
          <Trans id="path.tree.partial">Showing your current branch. The fit button shows the whole tree.</Trans>
        </p>
      ) : null}

      <div ref={gridRef} className={styles.grid} data-full={full || undefined} data-panel={selectedSkill ? "" : undefined}>
        <div className={styles.column}>
          <p id={hintId} className="visually-hidden">
            <Trans id="path.tree.hint">
              The path drawn as a graph: the start in the middle, one hub for each branch around it, the skills growing
              outward. Left and Right arrow keys move along a branch, Up and Down move between branches, Enter opens a
              skill. A list view is available: choose List above.
            </Trans>
          </p>
          <div
            ref={canvasRef}
            className={styles.canvas}
            data-compact={!side || undefined}
            role="group"
            aria-label={t({ id: "path.tree.skills.label", message: "Skills" })}
            aria-describedby={hintId}
            onKeyDown={onKeyDown}
          >
            {size ? (
              <ActionsContext.Provider value={actions}>
                <ReactFlow<FlowNode, VineFlowEdge>
                  className={styles.flow}
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  edgeTypes={edgeTypes}
                  defaultViewport={opening.current ?? undefined}
                  onMoveEnd={onMoveEnd}
                  attributionPosition="top-right"
                  onNodesChange={onNodesChange}
                  onNodeDragStop={onNodeDragStop}
                  onNodeClick={(_e, node) => {
                    if (node.type === "hub") {
                      const branchId = layout.byId.get(node.id)?.branchId ?? null;
                      setSelectedId(null);
                      frameBranch(framed === branchId ? null : branchId);
                    } else if (node.type === "start") {
                      frameBranch(null);
                    }
                  }}
                  onPaneClick={() => {
                    setSelectedId(null);
                    setFramedBranch(null);
                  }}
                  nodesDraggable={!reduced}
                  nodeDragThreshold={4}
                  nodeClickDistance={4}
                  nodesConnectable={false}
                  nodesFocusable={false}
                  edgesFocusable={false}
                  elementsSelectable={false}
                  disableKeyboardA11y
                  deleteKeyCode={null}
                  selectionKeyCode={null}
                  multiSelectionKeyCode={null}
                  panActivationKeyCode={null}
                  // the wheel over the canvas zooms it and does not scroll the page
                  preventScrolling
                  zoomOnScroll
                  minZoom={MIN_ZOOM}
                  maxZoom={MAX_ZOOM}
                  ariaLabelConfig={chromeLabels}
                >
                  <Controls
                    className={styles.controls}
                    position="bottom-left"
                    orientation="horizontal"
                    showInteractive={false}
                    showFitView={false}
                  >
                    <ControlButton
                      className={styles.own}
                      onClick={showAll}
                      aria-label={t({ id: "path.tree.controls.fit", message: "Fit the whole tree" })}
                      title={t({ id: "path.tree.controls.fit", message: "Fit the whole tree" })}
                    >
                      <FitIcon />
                    </ControlButton>
                    <ControlButton
                      className={styles.own}
                      onClick={toggleFull}
                      aria-pressed={full}
                      aria-label={t({ id: "path.tree.controls.full", message: "Full screen" })}
                      title={t({ id: "path.tree.controls.full", message: "Full screen" })}
                    >
                      {full ? <ShrinkIcon /> : <ExpandIcon />}
                    </ControlButton>
                  </Controls>
                  {side && !contained && !whole ? (
                    <MiniMap
                      className={styles.minimap}
                      position="bottom-right"
                      pannable
                      zoomable
                      style={{ width: 152, height: 104 }}
                      nodeBorderRadius={24}
                      nodeClassName={mapClass}
                    />
                  ) : null}
                </ReactFlow>
              </ActionsContext.Provider>
            ) : null}
          </div>
          <Legend />
        </div>

        {/* only for a chosen skill: with none, the canvas takes the room */}
        {selectedSkill ? (
          <SkillPanel
            id={panelId}
            mode={side ? "side" : "sheet"}
            titleRef={panelTitle}
            pathId={path.id}
            skill={selectedSkill}
            skills={skills}
            path={path}
            progress={progress}
            nodes={states}
            latest={latest}
            onSelect={(id) => select(id, "panel")}
            onClose={close}
            renderExtra={renderExtra}
          />
        ) : null}
      </div>
    </section>
  );
}

function BranchChip({
  branch,
  level,
  progress,
}: {
  branch: PathOut["branches"][number];
  level: number | undefined;
  progress: ProgressOut | undefined;
}) {
  const total = branch.skills.length;
  const mastered = branch.skills.filter((s) => progress?.skills[s.id]?.state === "mastered").length;
  return (
    <ToggleButton id={branch.id} className={styles.chip}>
      <span className={styles.chipName}>{branch.title}</span>
      <span className={styles.chipMeta}>
        {level !== undefined ? (
          <span className={styles.chipLevel}>
            <Trans id="path.branch.level">Level {level}</Trans>
          </span>
        ) : null}
        {progress ? (
          <span>
            <Trans id="path.tree.branch.mastered">
              {mastered} of {total} mastered
            </Trans>
          </span>
        ) : null}
      </span>
    </ToggleButton>
  );
}
