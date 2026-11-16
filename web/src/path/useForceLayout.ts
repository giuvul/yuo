// The path graph's live physics (d3-force): springs on the links, a little repulsion, boxes that give way, a weak
// pull home. Idle until a node is dragged; the simulation stops by itself once it has settled.
import type { Node, NodeChange } from "@xyflow/react";
import {
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
} from "d3-force";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Link } from "./graph";
import { forceBoxes, type Body, type GraphLayout, type Spot } from "./radial";

type LiveNode = Body & {
  /** the layout position: a weak pull keeps the graph's shape */
  tx: number;
  ty: number;
  /** from the node's top left corner to its centre */
  ox: number;
  oy: number;
};
type LiveLink = SimulationLinkDatum<LiveNode> & { rest: number; pull: number };
type Live = {
  s: Simulation<LiveNode, LiveLink>;
  byId: Map<string, LiveNode>;
  /** sets how hard every node is pulled to its layout position */
  home: (pull: number) => void;
};

/** How hard a node is pulled to its layout position: loosely while one is dragged, steadily once it is let go. */
const HOME_PULL = { dragging: 0.05, released: 0.1 };
/**
 * The way back after a drag (it snapped back too quickly). The simulation is held warm at
 * RETURN_HEAT until the nodes have stopped moving (or RETURN_MAX_MS), then cools down as usual. With the pull
 * above and d3's default damping, a node let go 150 px away is halfway home in 0.25 s, 90% in 0.8 s and back in
 * about 1.9 s, without overshooting; the former pull of 0.25 with a cooling start covered 90% in 0.08 s and
 * swung 13 px past its place.
 */
const RETURN_HEAT = 0.3;
const RETURN_MAX_MS = 4000;
const AT_REST = 0.05; // px per tick: every node slower than this has arrived
const RETURN_MIN_MS = 400; // right after the release the nodes have not started to move yet

/** A node's size, and the way from its top left corner to its centre (where its links meet). */
export const placeOf = (box: Spot["box"]) => ({ ox: -box.l, oy: -box.t, width: box.r - box.l, height: box.b - box.t });

/**
 * The live positions of a laid out graph. Each tick re-renders the caller; `centre` is where a node is now (its
 * layout position before the first tick), and the two handlers go to the flow's node changes and drag stop.
 * `measured` keeps the sizes the library measured: the nodes are controlled, and the library keeps a node's link
 * anchors only while its measured size is passed back.
 */
export function useForceLayout<N extends Node>(layout: GraphLayout, links: Link[]) {
  const sim = useRef<Live | null>(null);
  const [, setTick] = useState(0);
  const raf = useRef(0);
  const dragging = useRef(false);
  const returning = useRef(0); // when the way home after a drag started (0: not returning)
  // the nodes are controlled: the library keeps a node's link anchors only while its measured size is passed back
  const measured = useRef(new Map<string, { width?: number; height?: number }>());
  useEffect(() => {
    const before = sim.current?.byId;
    const live: LiveNode[] = layout.spots.map((s) => {
      // a data refresh keeps a node where it is on the screen, unless the layout itself has moved it
      const seen = before?.get(s.id);
      const old = seen && seen.tx === s.x && seen.ty === s.y ? seen : undefined;
      return { id: s.id, box: s.box, x: old?.x ?? s.x, y: old?.y ?? s.y, tx: s.x, ty: s.y, ...placeOf(s.box) };
    });
    const byId = new Map(live.map((n) => [n.id, n]));
    const springs: LiveLink[] = [];
    for (const l of links) {
      const a = byId.get(l.source);
      const b = byId.get(l.target);
      // at rest in the layout, elastic when pulled; a link across branches hardly pulls at all
      if (!a || !b) continue;
      springs.push({ source: a, target: b, rest: Math.hypot(a.tx - b.tx, a.ty - b.ty), pull: l.cross ? 0.012 : 0.3 });
    }
    const homeX = forceX<LiveNode>((n) => n.tx);
    const homeY = forceY<LiveNode>((n) => n.ty);
    const home = (pull: number) => {
      homeX.strength(pull);
      homeY.strength(pull);
    };
    home(HOME_PULL.dragging);
    const s = forceSimulation<LiveNode, LiveLink>(live)
      .force("link", forceLink<LiveNode, LiveLink>(springs).distance((l) => l.rest).strength((l) => l.pull))
      .force("charge", forceManyBody<LiveNode>().strength(-60).distanceMax(220))
      .force("boxes", forceBoxes<LiveNode>(layout.gap, 0.6))
      .force("x", homeX)
      .force("y", homeY)
      .alphaDecay(0.05)
      .stop();
    s.on("tick", () => {
      if (returning.current && !dragging.current) {
        // back home once nothing moves any more (or it took too long): let the simulation cool down and stop
        const still = live.every((n) => Math.abs(n.vx ?? 0) < AT_REST && Math.abs(n.vy ?? 0) < AT_REST);
        const took = performance.now() - returning.current;
        if ((still && took > RETURN_MIN_MS) || took > RETURN_MAX_MS) {
          returning.current = 0;
          s.alphaTarget(0);
        }
      }
      if (raf.current) return;
      raf.current = requestAnimationFrame(() => {
        raf.current = 0;
        setTick((n) => n + 1);
      });
    });
    sim.current = { s, byId, home };
    setTick((n) => n + 1);
    return () => {
      s.stop();
      cancelAnimationFrame(raf.current);
      raf.current = 0;
    };
  }, [layout, links]);

  const centre = useCallback(
    (id: string) => {
      const n = sim.current?.byId.get(id);
      if (n) return { x: n.x ?? n.tx, y: n.y ?? n.ty };
      const s = layout.byId.get(id);
      return s ? { x: s.x, y: s.y } : null;
    },
    [layout],
  );

  const onNodesChange = useCallback((changes: NodeChange<N>[]) => {
    const cur = sim.current;
    let changed = false;
    for (const ch of changes) {
      if (ch.type === "dimensions" && ch.dimensions) {
        measured.current.set(ch.id, ch.dimensions);
        changed = true;
      } else if (ch.type === "position" && ch.position) {
        // the dragged node is pinned under the pointer, the rest follows
        const n = cur?.byId.get(ch.id);
        if (!cur || !n) continue;
        n.fx = n.x = ch.position.x + n.ox;
        n.fy = n.y = ch.position.y + n.oy;
        changed = true;
        if (ch.dragging && !dragging.current) {
          dragging.current = true;
          returning.current = 0;
          cur.home(HOME_PULL.dragging);
          cur.s.alphaTarget(0.3).restart();
        }
      }
    }
    if (changed) setTick((n) => n + 1);
  }, []);
  const onNodeDragStop = useCallback(() => {
    const cur = sim.current;
    if (!cur) return;
    for (const n of cur.byId.values()) {
      n.fx = null;
      n.fy = null;
    }
    dragging.current = false;
    // everything is pulled home at a steady strength until it has arrived, then the simulation cools down
    cur.home(HOME_PULL.released);
    returning.current = performance.now();
    cur.s.alpha(RETURN_HEAT).alphaTarget(RETURN_HEAT).restart();
  }, []);

  return { centre, onNodesChange, onNodeDragStop, measured };
}
