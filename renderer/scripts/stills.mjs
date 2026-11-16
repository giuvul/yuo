// One still per narration sentence (~2.3 s in, when its animation has landed), with the reviewers' caption
// overlay, tiled into 2x3 contact sheets, plus the layout probe of each still in <out>/probe.json.
//   node scripts/stills.mjs <workspace> <out>
import {renderStill, selectComposition} from '@remotion/renderer';
import {execFileSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {browser, makeBundle, timeoutMs, workspaceTmp} from './common.mjs';

const [ws, out] = process.argv.slice(2);
workspaceTmp(ws);
fs.rmSync(out, {recursive: true, force: true});
fs.mkdirSync(out, {recursive: true});
const timeline = JSON.parse(fs.readFileSync(path.join(ws, 'public', 'timeline.json'), 'utf8'));
const frames = [];
for (const s of timeline.scenes)
	s.segments.forEach((g, i) =>
		frames.push({name: `${s.id}-${i}`, scene: s.id, seg: i, text: g.text, frame: g.start + Math.min(70, g.end - g.start - 5)}),
	);
const serveUrl = await makeBundle(ws);
const chrome = await browser();
const inputProps = {timeline: null, probe: true, captions: true};
const composition = await selectComposition({serveUrl, id: 'Lesson', inputProps, puppeteerInstance: chrome, timeoutInMilliseconds: timeoutMs});
const probes = {};
const errors = [];
const onBrowserLog = (log) => {
	const m = /^YUO_PROBE (.*)$/s.exec(log.text || '');
	if (m) {
		try {
			const p = JSON.parse(m[1]);
			probes[p.frame] = p;
		} catch {}
	} else if (log.type === 'error') errors.push(String(log.text).slice(0, 300));
};
for (const f of frames)
	await renderStill({
		serveUrl, composition, inputProps, frame: f.frame, output: path.join(out, `${f.name}.jpg`), imageFormat: 'jpeg',
		scale: 0.5, puppeteerInstance: chrome, onBrowserLog, timeoutInMilliseconds: timeoutMs,
	});
await new Promise((r) => setTimeout(r, 300));
await chrome.close({silent: true});
fs.writeFileSync(path.join(out, 'probe.json'), JSON.stringify(frames.map((f) => ({...f, probe: probes[f.frame] || null})), null, 1));
for (let i = 0; i < frames.length; i += 6) {
	const group = frames.slice(i, i + 6);
	const inputs = [];
	for (const f of group) inputs.push('-i', path.join(out, `${f.name}.jpg`));
	for (let k = group.length; k < 6; k++) inputs.push('-f', 'lavfi', '-i', 'color=0x3a3f4a:s=960x540:d=1');
	execFileSync(process.env.YUO_FFMPEG || 'ffmpeg', ['-y', '-loglevel', 'error', ...inputs, '-filter_complex',
		'xstack=inputs=6:layout=0_0|w0_0|0_h0|w0_h0|0_h0+h0|w0_h0+h0', '-frames:v', '1', path.join(out, `sheet_${String(i / 6).padStart(2, '0')}.jpg`)]);
}
fs.rmSync(path.join(ws, 'bundle'), {recursive: true, force: true});
console.log(JSON.stringify({stills: frames.length, sheets: Math.ceil(frames.length / 6), probed: Object.keys(probes).length, errors: errors.slice(0, 5)}));
