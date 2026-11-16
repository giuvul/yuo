import React from 'react';
import {AbsoluteFill, Audio, Sequence, continueRender, delayRender, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {C, fontFamily} from './theme';
import {SCENES} from './gen/scene';
import {runProbe} from './probe';

export type Timeline = {
	title: string;
	fps: number;
	durationInFrames: number;
	scenes: {id: string; label: string; start: number; end: number; segments: {text: string; start: number; end: number}[]}[];
};
// `captions` draws the sentence at the bottom for the reviewers' stills only: the published video has no
// captions in the frame; the player shows the WebVTT track over the free bottom area.
export type LessonProps = {timeline: Timeline | null; probe?: boolean; captions?: boolean};

const FADE = 12;
export const SAFE_BOTTOM = 190; // kept free for the player's caption overlay

export const Lesson: React.FC<LessonProps> = ({timeline, probe, captions}) => {
	if (!timeline) return null;
	return (
		<AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 35%, ${C.bg2} 0%, ${C.bg} 70%)`, fontFamily, color: C.text}}>
			<Audio src={staticFile('narration.wav')} />
			{timeline.scenes.map((s) => {
				const len = s.end - s.start;
				const segs = s.segments.map((g) => g.start - s.start);
				const ends = s.segments.map((g) => g.end - s.start);
				const Comp = SCENES[s.id]?.component;
				return (
					<Sequence key={s.id} from={s.start} durationInFrames={len} name={s.id}>
						<SceneFrame len={len} label={s.label}>{Comp ? <Comp segs={segs} ends={ends} /> : <Missing id={s.id} />}</SceneFrame>
					</Sequence>
				);
			})}
			{captions ? <ReviewCaptions timeline={timeline} /> : null}
			{probe ? <ProbeRunner /> : null}
			<Progress timeline={timeline} />
		</AbsoluteFill>
	);
};

const Missing: React.FC<{id: string}> = ({id}) => (
	<AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', color: C.bad, fontSize: 40}}>missing scene {id}</AbsoluteFill>
);

const SceneFrame: React.FC<{len: number; label: string; children: React.ReactNode}> = ({len, label, children}) => {
	const f = useCurrentFrame();
	const o = interpolate(f, [0, FADE, len - FADE, len], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	return (
		<AbsoluteFill style={{opacity: o}}>
			<div style={{position: 'absolute', top: 48, left: 72, fontSize: 26, fontWeight: 600, letterSpacing: 3, color: C.dim, textTransform: 'uppercase'}}>
				{label}
			</div>
			<div data-scene-area style={{position: 'absolute', left: 0, right: 0, top: 110, bottom: SAFE_BOTTOM, overflow: 'hidden'}}>{children}</div>
		</AbsoluteFill>
	);
};

const ReviewCaptions: React.FC<{timeline: Timeline}> = ({timeline}) => {
	const f = useCurrentFrame();
	const cur = timeline.scenes.flatMap((s) => s.segments).find((g) => f >= g.start - 4 && f <= g.end + 8);
	if (!cur) return null;
	return (
		<div data-review-caption style={{position: 'absolute', bottom: 56, left: 0, right: 0, display: 'flex', justifyContent: 'center'}}>
			<div style={{maxWidth: 1500, padding: '14px 28px', borderRadius: 14, background: 'rgba(8,12,26,0.78)', fontSize: 34, lineHeight: 1.35, textAlign: 'center', color: C.text}}>
				{cur.text}
			</div>
		</div>
	);
};

const Progress: React.FC<{timeline: Timeline}> = ({timeline}) => {
	const f = useCurrentFrame();
	return <div style={{position: 'absolute', bottom: 0, left: 0, height: 6, width: `${(f / timeline.durationInFrames) * 100}%`, background: C.read, opacity: 0.6}} />;
};

// Measure this frame's DOM once it is on screen (the probe waits for the scene area's real size).
const ProbeRunner: React.FC = () => {
	const f = useCurrentFrame();
	React.useEffect(() => {
		const handle = delayRender('yuo-probe');
		let tries = 0;
		const tick = () => {
			const ready = Array.from(document.querySelectorAll('[data-scene-area]')).some((e) => e.getBoundingClientRect().width > 100);
			if (!ready && tries++ < 100) {
				setTimeout(tick, 20);
				return;
			}
			try {
				runProbe(f);
			} catch (e) {
				console.log('YUO_PROBE ' + JSON.stringify({frame: f, error: String(e)}));
			}
			continueRender(handle);
		};
		tick();
	}, [f]);
	return null;
};
