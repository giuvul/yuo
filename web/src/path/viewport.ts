// The view of the path graph: framing a set of nodes, the first view, and where the panel goes.
import { useLayoutEffect, useState } from "react";
import type { Viewport } from "@xyflow/react";
import { START } from "./graph";
import type { GraphLayout } from "./radial";

/** The panel becomes a column beside the canvas when the area is at least this wide (CSS pixels at a 16 px root). */
const SIDE_MIN = 736;
/** The canvas a test environment without layout gets. */
export const FALLBACK_SIZE = { width: 720, height: 560 };
/**
 * Below this zoom the names under the nodes (16 px type) would be smaller than about 9 px: only then does the
 * first view show less than the whole graph.
 */
const READABLE_ZOOM = 0.54;
const MAX_FIT_ZOOM = 1.15;
export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 1.8;

export type Size = { width: number; height: number };

/**
 * The viewport that shows the given nodes, and the zoom it would take without the limits. `below` keeps a strip at
 * the bottom free: the view controls and the overview map sit there.
 */
export function frame(
  layout: GraphLayout,
  ids: Iterable<string>,
  size: Size,
  pad: number,
  below = 0,
  minZoom = MIN_ZOOM,
): Viewport & { natural: number } {
  let l = Infinity;
  let t = Infinity;
  let r = -Infinity;
  let b = -Infinity;
  for (const id of ids) {
    const s = layout.byId.get(id);
    if (!s) continue;
    l = Math.min(l, s.x + s.box.l);
    t = Math.min(t, s.y + s.box.t);
    r = Math.max(r, s.x + s.box.r);
    b = Math.max(b, s.y + s.box.b);
  }
  if (l === Infinity) return { x: size.width / 2, y: size.height / 2, zoom: 1, natural: 1 };
  const height = Math.max(120, size.height - below);
  const natural = Math.min((size.width - 2 * pad) / Math.max(1, r - l), (height - 2 * pad) / Math.max(1, b - t));
  const zoom = Math.max(minZoom, Math.min(MAX_FIT_ZOOM, natural));
  return { x: size.width / 2 - ((l + r) / 2) * zoom, y: height / 2 - ((t + b) / 2) * zoom, zoom, natural };
}

/** The strip at the bottom of the canvas that a framed view stays clear of: the view controls sit there. */
export const BELOW = 56;
export const padOf = (wide: boolean) => (wide ? 24 : 12);

/** The room a framed graph has on a canvas: what is left inside the padding and above the controls. */
export const roomOn = (size: Size, wide: boolean): Size => ({
  width: Math.max(120, size.width - 2 * padOf(wide)),
  height: Math.max(120, size.height - BELOW - 2 * padOf(wide)),
});

/**
 * The first view: the whole graph. Only a path so large that its names would be too small to read opens on the
 * start and the branch of the skill to learn now instead (`partial`; the canvas then says so).
 */
export function firstView(
  layout: GraphLayout,
  size: Size,
  currentId: string | null,
  wide: boolean,
  sample: boolean,
): Viewport & { partial: boolean } {
  const pad = padOf(wide);
  const all = frame(layout, layout.byId.keys(), size, pad, BELOW);
  // a sample on a page is there to be seen whole
  if (all.natural >= READABLE_ZOOM || sample) return { ...all, partial: false };
  const home = layout.hubs.find((h) => currentId !== null && h.skillIds.includes(currentId)) ?? layout.hubs[0];
  if (!home) return { ...all, partial: false };
  // a branch a little too long loses its two ends evenly rather than its names
  const branch = frame(layout, [START, home.id, ...home.skillIds], size, pad, BELOW, READABLE_ZOOM);
  if (branch.natural >= READABLE_ZOOM * 0.85) return { ...branch, partial: true };
  return { ...frame(layout, [START, home.id, currentId ?? home.id], size, pad, BELOW, READABLE_ZOOM), partial: true };
}

/** Where the panel goes (beside the canvas or as a sheet), and the canvas's size once it is known. */
export function useRoom(area: React.RefObject<HTMLElement | null>, canvas: React.RefObject<HTMLElement | null>) {
  const [room, setRoom] = useState<{ side: boolean; size: Size | null }>({ side: true, size: null });
  useLayoutEffect(() => {
    const measure = () => {
      const unit = (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16) / 16;
      const areaWidth = (area.current?.clientWidth ?? 0) / unit;
      const side = areaWidth <= 0 || areaWidth >= SIDE_MIN; // no layout (tests): the column
      // the canvas has its real size only once the page shows that mode: until then (one render) it is not known
      if (area.current?.dataset["mode"] !== (side ? "side" : "sheet")) {
        setRoom((r) => (r.side === side ? r : { side, size: null }));
        return;
      }
      const el = canvas.current;
      const laidOut = el && el.clientWidth > 0 && el.clientHeight > 0;
      const size = laidOut ? { width: el.clientWidth, height: el.clientHeight } : FALLBACK_SIZE;
      setRoom((r) =>
        r.side === side && r.size?.width === size.width && r.size.height === size.height ? r : { side, size },
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    if (area.current) observer.observe(area.current);
    if (canvas.current) observer.observe(canvas.current);
    return () => observer.disconnect();
  }, [area, canvas]);
  return room;
}
