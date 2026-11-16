import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, monoFamily} from './theme';

export type SceneProps = {segs: number[]; ends: number[]};

// Beat timing: scenes key their animations to the narration segments, so
// visuals land on the sentence that talks about them whatever the voice speed.
export const useBeats = (segs: number[]) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	// i < 0 (e.g. `seg` before a scene's first sentence starts) counts as "not yet": 0, never NaN.
	const at = (i: number, delay = 0) =>
		i < 0 || i >= segs.length ? 0 : spring({frame: frame - segs[i] - delay, fps, config: {damping: 18, mass: 0.7}});
	let seg = -1;
	segs.forEach((s, i) => {
		if (frame >= s) seg = i;
	});
	// linear 0..1 over `dur` frames from segment i (for travelling packets etc.)
	const lin = (i: number, delay = 0, dur = 20) =>
		i < 0 || i >= segs.length ? 0 : interpolate(frame - segs[i] - delay, [0, dur], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	return {frame, at, seg, lin};
};

export const Pop: React.FC<{p: number; style?: React.CSSProperties; children: React.ReactNode; dy?: number}> = ({p, style, children, dy = 30}) => (
	<div style={{opacity: Math.min(1, p * 1.2), transform: `translateY(${(1 - p) * dy}px) scale(${0.92 + 0.08 * p})`, ...style}}>{children}</div>
);

export const Center: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
	<div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', ...style}}>{children}</div>
);

export const Card: React.FC<{children: React.ReactNode; color?: string; style?: React.CSSProperties}> = ({children, color = C.line, style}) => (
	<div style={{background: C.panel, border: `2px solid ${color}`, borderRadius: 22, padding: '28px 36px', ...style}}>{children}</div>
);

export const Mono: React.FC<{children: React.ReactNode; color?: string; size?: number; style?: React.CSSProperties}> = ({children, color = C.text, size = 36, style}) => (
	<span style={{fontFamily: monoFamily, color, fontSize: size, fontWeight: 700, ...style}}>{children}</span>
);

// A replica node: circle + name + current value badge.
export const ReplicaNode: React.FC<{
	x: number;
	y: number;
	name: string;
	value?: string;
	valueColor?: string;
	ring?: string; // highlight ring colour
	ring2?: string; // second ring (overlap)
	dead?: boolean;
	r?: number;
	glow?: number;
}> = ({x, y, name, value, valueColor = C.text, ring, ring2, dead, r = 78, glow = 0}) => (
	<g transform={`translate(${x},${y})`} opacity={dead ? 0.35 : 1}>
		{glow > 0 && <circle r={r + 30} fill={C.good} opacity={0.18 * glow} />}
		{ring2 && <circle r={r + 20} fill="none" stroke={ring2} strokeWidth={6} />}
		{ring && <circle r={r + 10} fill="none" stroke={ring} strokeWidth={6} />}
		<circle r={r} fill={C.panel} stroke={C.line} strokeWidth={4} />
		<text y={-8} textAnchor="middle" fill={C.text} fontSize={44} fontWeight={800}>
			{name}
		</text>
		{value !== undefined && (
			<text y={38} textAnchor="middle" fill={valueColor} fontSize={30} fontFamily={monoFamily} fontWeight={700}>
				{value}
			</text>
		)}
		{dead && (
			<g stroke={C.bad} strokeWidth={10} strokeLinecap="round">
				<line x1={-50} y1={-50} x2={50} y2={50} />
				<line x1={50} y1={-50} x2={-50} y2={50} />
			</g>
		)}
	</g>
);

// A message travelling from (x1,y1) to (x2,y2); t in 0..1. Drawn as a trail + dot.
export const Packet: React.FC<{
	x1: number; y1: number; x2: number; y2: number; t: number; color: string; label?: string; trail?: boolean;
	stay?: boolean; // keep the dot (and label) visible after arrival
	labelBelow?: boolean;
}> = ({x1, y1, x2, y2, t, color, label, trail = true, stay = false, labelBelow = false}) => {
	if (t <= 0 || (t >= 1 && !stay)) return null;
	const x = x1 + (x2 - x1) * t;
	const y = y1 + (y2 - y1) * t;
	return (
		<g>
			{trail && <line x1={x1} y1={y1} x2={x} y2={y} stroke={color} strokeWidth={5} strokeDasharray="10 10" opacity={0.7} />}
			<circle cx={x} cy={y} r={14} fill={color} />
			{label && t > 0.05 && (
				<text x={x} y={labelBelow ? y + 52 : y - 26} textAnchor="middle" fill={color} fontSize={28} fontFamily={monoFamily} fontWeight={700}>
					{label}
				</text>
			)}
		</g>
	);
};

// Small labelled client box.
export const Client: React.FC<{x: number; y: number; label: string; color?: string; o?: number}> = ({x, y, label, color = C.dim, o = 1}) => (
	<g transform={`translate(${x},${y})`} opacity={o}>
		<rect x={-110} y={-40} width={220} height={80} rx={18} fill={C.bg2} stroke={color} strokeWidth={4} />
		<text y={11} textAnchor="middle" fill={color} fontSize={30} fontWeight={600}>
			{label}
		</text>
	</g>
);

export const Stage: React.FC<{children: React.ReactNode}> = ({children}) => (
	<svg viewBox="0 0 1920 780" style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}}>
		{children}
	</svg>
);

// The scene definition every generated scene module exports (SCENES: Record<id, SceneDef>).
export type SceneDef = {label: string; component: React.FC<SceneProps>};
