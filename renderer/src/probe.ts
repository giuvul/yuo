// Layout probe: runs in the page at a still's frame and logs what is on screen and the
// layout defects a deterministic check can see. Works the same for engine-drawn (decl) and
// model-written (coded) scenes because it measures the DOM, not the source.
//
// Logged as one console line "YUO_PROBE <json>" per frame; stills.mjs collects it via onBrowserLog.

type Box = {x: number; y: number; w: number; h: number};
type Txt = Box & {t: string; fs: number; el: Element};

const MIN_FONT = 22; // CSS px at 1080p; the prompt asks for >= 26-28
const area = (b: Box) => Math.max(0, b.w) * Math.max(0, b.h);
const inter = (a: Box, b: Box): Box => {
	const x = Math.max(a.x, b.x), y = Math.max(a.y, b.y);
	return {x, y, w: Math.min(a.x + a.w, b.x + b.w) - x, h: Math.min(a.y + a.h, b.y + b.h) - y};
};
const fromRect = (r: DOMRect): Box => ({x: r.x, y: r.y, w: r.width, h: r.height});
const union = (bs: Box[]): Box => {
	const x = Math.min(...bs.map((b) => b.x)), y = Math.min(...bs.map((b) => b.y));
	return {x, y, w: Math.max(...bs.map((b) => b.x + b.w)) - x, h: Math.max(...bs.map((b) => b.y + b.h)) - y};
};
const r0 = (b: Box) => ({x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.w), h: Math.round(b.h)});

function opacity(el: Element | null): number {
	let o = 1;
	for (let e = el; e && e !== document.body; e = e.parentElement) {
		const cs = getComputedStyle(e);
		if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
		o *= parseFloat(cs.opacity || '1');
		const fo = e.getAttribute && e.getAttribute('fill-opacity');
		if (fo && e instanceof SVGElement && e.tagName === 'text') o *= parseFloat(fo);
	}
	return o;
}

function hasPaint(el: Element): boolean {
	const cs = getComputedStyle(el);
	if (el instanceof SVGElement) {
		const fill = cs.fill, stroke = cs.stroke;
		return (fill !== 'none' && fill !== 'transparent' && !/rgba\(.*,\s*0\)/.test(fill)) || (stroke !== 'none' && parseFloat(cs.strokeWidth) > 0);
	}
	const bg = cs.backgroundColor;
	const visBg = bg && bg !== 'transparent' && !/rgba\(.*,\s*0\)$/.test(bg);
	const border = parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none';
	return !!(visBg || border || cs.backgroundImage !== 'none');
}

export function runProbe(frame: number) {
	// Remotion keeps hidden zero-size copies off-screen: take the largest on-screen scene area.
	const candidates = Array.from(document.querySelectorAll('[data-scene-area]')).filter((e) => {
		const r = e.getBoundingClientRect();
		return r.width > 100 && r.height > 100 && r.y > -10 && r.y < window.innerHeight;
	});
	const sceneArea = candidates.sort((a, b) => area(fromRect(b.getBoundingClientRect())) - area(fromRect(a.getBoundingClientRect())))[0];
	if (!sceneArea) {
		const all = Array.from(document.querySelectorAll('[data-scene-area]'));
		const chain = all.slice(0, 1).flatMap((e0) => {
			const out: string[] = [];
			for (let e: Element | null = e0; e; e = e.parentElement) {
				const r = e.getBoundingClientRect();
				out.push(`${e.tagName}.${(e as HTMLElement).id || ''} ${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)} ${(e as HTMLElement).style?.cssText?.slice(0, 120) || ''}`);
			}
			return out;
		});
		console.log('YUO_PROBE ' + JSON.stringify({frame, n: all.length, chain, vw: window.innerWidth, vh: window.innerHeight}));
		return;
	}
	const A = fromRect(sceneArea.getBoundingClientRect());
	const issues: {kind: string; text: string; detail: string}[] = [];

	// 1. Text boxes, one per element with direct text.
	const byEl = new Map<Element, {parts: Box[]; text: string}>();
	const walker = document.createTreeWalker(sceneArea, NodeFilter.SHOW_TEXT);
	for (let n = walker.nextNode(); n; n = walker.nextNode()) {
		const s = (n.textContent || '').trim();
		const el = n.parentElement;
		if (!s || !el) continue;
		if (opacity(el) < 0.25) continue;
		const range = document.createRange();
		range.selectNodeContents(n);
		const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0).map(fromRect);
		if (el instanceof SVGElement) rects.splice(0, rects.length, fromRect(el.getBoundingClientRect()));
		if (!rects.length) continue;
		const cur = byEl.get(el) || {parts: [], text: ''};
		cur.parts.push(...rects);
		cur.text = (cur.text + ' ' + s).trim();
		byEl.set(el, cur);
	}
	const texts: Txt[] = [];
	byEl.forEach((v, el) => {
		const b = union(v.parts);
		if (b.w < 2 || b.h < 2) return;
		// font size on screen: computed size x the element's screen scale
		const cs = getComputedStyle(el);
		let fs = parseFloat(cs.fontSize);
		if (el instanceof SVGGraphicsElement) {
			const m = el.getScreenCTM();
			if (m) fs *= Math.sqrt(Math.abs(m.a * m.d - m.b * m.c));
		} else {
			const lineH = Math.min(...v.parts.map((p) => p.h));
			fs = Math.min(fs * 1.25, lineH / 1.15) || fs; // transforms (scale) show in the rect height
		}
		texts.push({...b, t: v.text.slice(0, 80), fs: Math.round(fs), el});
	});

	// 2. Shapes: painted boxes (HTML) and SVG shapes; very large panels are ignored for crossing.
	const shapes: (Box & {el: Element; tag: string})[] = [];
	sceneArea.querySelectorAll('*').forEach((el) => {
		if (el === sceneArea) return;
		const tag = el.tagName.toLowerCase();
		const svgShape = ['rect', 'circle', 'ellipse', 'polygon'].includes(tag);
		const html = !(el instanceof SVGElement) && hasPaint(el);
		if (!(svgShape && hasPaint(el)) && !html) return;
		if (opacity(el) < 0.25) return;
		const b = fromRect(el.getBoundingClientRect());
		if (b.w < 12 || b.h < 12) return;
		shapes.push({...b, el, tag});
	});

	// 3. Strokes (lines, arrows, curves), sampled in screen space.
	const strokes: {pts: [number, number][]; el: Element}[] = [];
	sceneArea.querySelectorAll('line, polyline, path').forEach((el) => {
		if (!(el instanceof SVGGeometryElement) || opacity(el) < 0.25) return;
		const cs = getComputedStyle(el);
		if (cs.stroke === 'none' || parseFloat(cs.strokeWidth) <= 0) return;
		if (cs.fill !== 'none' && el.tagName !== 'line') return; // filled paths are shapes (arrowheads, blobs)
		const m = el.getScreenCTM();
		if (!m) return;
		let len = 0;
		try { len = el.getTotalLength(); } catch { return; }
		const n = Math.min(60, Math.max(8, Math.round(len / 12)));
		const pts: [number, number][] = [];
		for (let i = 0; i <= n; i++) {
			const p = el.getPointAtLength((len * i) / n);
			pts.push([m.a * p.x + m.c * p.y + m.e, m.b * p.x + m.d * p.y + m.f]);
		}
		strokes.push({pts, el});
	});

	const label = (t: Txt) => `'${t.t.slice(0, 40)}'`;
	for (const t of texts) {
		// off-frame / clipped by the scene area
		const inA = area(inter(t, A)) / Math.max(1, area(t));
		if (inA < 0.98) issues.push({kind: 'clipped', text: t.t, detail: `${label(t)} is cut off at the edge of the frame`});
		if (t.fs < MIN_FONT) issues.push({kind: 'small_text', text: t.t, detail: `${label(t)} is ${t.fs}px, too small (min 26px)`});
		// overflow of its own painted container (nearest ancestor with background/border)
		for (let e = t.el as Element | null, d = 0; e && e !== sceneArea && d < 4; e = e.parentElement, d++) {
			if (e instanceof SVGElement || !hasPaint(e)) continue;
			const c = fromRect(e.getBoundingClientRect());
			const spill = Math.max(c.x - t.x, c.y - t.y, t.x + t.w - (c.x + c.w), t.y + t.h - (c.y + c.h));
			if (spill > 4) issues.push({kind: 'overflow', text: t.t, detail: `${label(t)} spills ${Math.round(spill)}px out of its box`});
			break;
		}
		// crossing the edge of another shape (text half in, half out); 1-2 character marks (atoms,
		// vertex names) sit on shapes on purpose
		for (const s of t.t.length > 2 ? shapes : []) {
			if (s.el.contains(t.el) || area(s) > 0.6 * area(A)) continue;
			const f = area(inter(t, s)) / Math.max(1, area(t));
			if (f > 0.15 && f < 0.85) {
				issues.push({kind: 'crosses_edge', text: t.t, detail: `${label(t)} crosses the edge of a ${s.tag === 'div' || s.tag === 'span' ? 'box' : s.tag}`});
				break;
			}
		}
		// a line or arrow runs through the label
		const core = {x: t.x + 3, y: t.y + 3, w: t.w - 6, h: t.h - 6};
		for (const s of t.t.length > 2 ? strokes : []) {
			if (s.pts.some(([x, y]) => x > core.x && x < core.x + core.w && y > core.y && y < core.y + core.h)) {
				issues.push({kind: 'line_through_text', text: t.t, detail: `a line or arrow runs through ${label(t)}`});
				break;
			}
		}
	}
	// text on text
	for (let i = 0; i < texts.length; i++)
		for (let j = i + 1; j < texts.length; j++) {
			const a = texts[i], b = texts[j];
			if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
			const f = area(inter(a, b)) / Math.max(1, Math.min(area(a), area(b)));
			if (f > 0.12) issues.push({kind: 'overlap', text: a.t, detail: `${label(a)} overlaps ${label(b)}`});
		}
	// how much is on screen
	const chars = texts.reduce((n, t) => n + t.t.length, 0);
	const ink = Math.min(1, (shapes.reduce((n, s) => n + area(inter(s, A)), 0) + texts.reduce((n, t) => n + area(t), 0)) / area(A));
	const graphic = shapes.length + strokes.length;
	if (!texts.length && !graphic) issues.push({kind: 'empty', text: '', detail: 'the frame is empty'});
	else if (graphic === 0 && chars < 60) issues.push({kind: 'text_only', text: '', detail: 'only a heading or a few words on screen, no visual'});
	else if (ink < 0.04) issues.push({kind: 'sparse', text: '', detail: 'the frame is mostly empty'});

	const out = {
		frame,
		area: r0(A),
		vw: window.innerWidth,
		vh: window.innerHeight,
		texts: texts.map((t) => ({t: t.t, fs: t.fs, ...r0({x: t.x - A.x, y: t.y - A.y, w: t.w, h: t.h})})),
		n_shapes: shapes.length,
		n_strokes: strokes.length,
		ink: Math.round(ink * 100) / 100,
		issues,
	};
	console.log('YUO_PROBE ' + JSON.stringify(out));
}
