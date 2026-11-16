import React from 'react';
import {interpolate} from 'remotion';
import {C, monoFamily} from '../theme';
import {Card, Center, Mono, Pop, SceneDef, SceneProps, useBeats} from '../kit';


// ---------------------------------------------------------------- intro
const Intro: React.FC<SceneProps> = ({segs}) => {
	const {at} = useBeats(segs);
	const split = at(1);
	return (
		<Center>
			<div style={{fontSize: 140, fontWeight: 800, letterSpacing: -2, opacity: at(0), transform: `translateY(${-split * 120}px) scale(${1 - split * 0.35})`}}>
				Consistency
			</div>
			<div style={{display: 'flex', gap: 60, alignItems: 'center', marginTop: -40}}>
				<Pop p={at(1, 6)}>
					<Card color={C.violet} style={{width: 560}}>
						<div style={{fontSize: 30, color: C.violet, fontWeight: 600}}>ACID</div>
						<div style={{fontSize: 40, fontWeight: 600, marginTop: 8}}>Rules always hold</div>
					</Card>
				</Pop>
				<Pop p={at(1, 14)}>
					<div style={{fontSize: 90, color: C.bad, fontWeight: 800}}>≠</div>
				</Pop>
				<Pop p={at(1, 10)}>
					<Card color={C.read} style={{width: 560}}>
						<div style={{fontSize: 30, color: C.read, fontWeight: 600}}>Distributed systems</div>
						<div style={{fontSize: 40, fontWeight: 600, marginTop: 8}}>Behaves like one copy</div>
					</Card>
				</Pop>
			</div>
			<div style={{display: 'flex', gap: 28, marginTop: 70}}>
				{['CAP', 'PACELC', 'Quorums'].map((t, i) => (
					<Pop key={t} p={at(2, 10 + i * 12)}>
						<div style={{padding: '14px 34px', borderRadius: 999, border: `2px solid ${C.line}`, background: C.panel, fontSize: 34, fontWeight: 600}}>{t}</div>
					</Pop>
				))}
			</div>
		</Center>
	);
};

// ---------------------------------------------------------------- ACID
const Acid: React.FC<SceneProps> = ({segs}) => {
	const {at, seg, frame} = useBeats(segs);
	const rules = ['NOT NULL', 'UNIQUE', 'FOREIGN KEY', 'CHECK (balance >= 0)'];
	const debit = at(2, 30);
	const rolled = at(3);
	const shown = rolled > 0.5 ? 60 : Math.round(60 - 100 * debit);
	const balColor = rolled > 0.5 ? C.good : debit > 0.5 ? C.bad : C.text;
	const shake = debit > 0.5 && rolled < 0.5 ? Math.sin(frame * 1.3) * 6 : 0;
	return (
		<Center style={{flexDirection: 'row', gap: 90}}>
			<div style={{width: 640}}>
				<Pop p={at(0)}>
					<div style={{fontSize: 64, fontWeight: 800}}>
						The <span style={{color: C.violet}}>C</span> in ACID
					</div>
					<div style={{fontSize: 36, color: C.dim, marginTop: 10}}>Invariants must always hold</div>
				</Pop>
				<div style={{display: 'flex', flexDirection: 'column', gap: 16, marginTop: 40}}>
					{rules.map((r, i) => (
						<Pop key={r} p={at(1, i * 10)} dy={0} style={{transform: undefined}}>
							<div style={{display: 'inline-block', padding: '10px 24px', borderRadius: 12, background: C.panel, border: `2px solid ${i === 3 && seg >= 2 ? C.violet : C.line}`}}>
								<Mono size={32} color={i === 3 && seg >= 2 ? C.violet : C.text}>
									{r}
								</Mono>
							</div>
						</Pop>
					))}
				</div>
			</div>
			<div style={{width: 760, position: 'relative'}}>
				<Pop p={at(2)}>
					<Card style={{transform: `translateX(${shake}px)`}}>
						<div style={{fontSize: 30, color: C.dim}}>BEGIN; transfer €100</div>
						<div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 24}}>
							<div style={{fontSize: 40, fontWeight: 600}}>Account A</div>
							<Mono size={64} color={balColor}>
								€{shown}
							</Mono>
						</div>
						<div style={{height: 2, background: C.line, margin: '22px 0'}} />
						<div style={{fontSize: 32, minHeight: 44, color: rolled > 0.5 ? C.good : C.bad, opacity: debit}}>
							{rolled > 0.5 ? '✓ ROLLBACK: database still valid' : '✗ CHECK (balance >= 0) violated'}
						</div>
					</Card>
				</Pop>
				<Pop p={at(4)} style={{marginTop: 40}}>
					<div style={{fontSize: 34, color: C.dim, textAlign: 'center'}}>
						Scope: <span style={{color: C.text, fontWeight: 600}}>one database + its rules</span>. No replicas involved.
					</div>
				</Pop>
			</div>
		</Center>
	);
};

export const SCENES: Record<string, SceneDef> = {
	intro: {label: 'Consistency', component: Intro},
	acid: {label: 'ACID consistency', component: Acid},
};
