// The published MP4: no captions in the frame (they are a separate WebVTT track), no probe.
//   node scripts/render.mjs <workspace> <out.mp4>
import {renderMedia, selectComposition} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';
import {browser, makeBundle, timeoutMs, workspaceTmp} from './common.mjs';

// Speech needs far less than Remotion's 320 kbit/s default, which was about two thirds of every file: the
// vector scenes compress to 100-230 kbit/s (keep videos small).
const AUDIO_BITRATE = '64k';

const [ws, out] = process.argv.slice(2);
workspaceTmp(ws);
const serveUrl = await makeBundle(ws);
const chrome = await browser();
const inputProps = {timeline: null, probe: false, captions: false};
const composition = await selectComposition({serveUrl, id: 'Lesson', inputProps, puppeteerInstance: chrome, timeoutInMilliseconds: timeoutMs});
await renderMedia({
	serveUrl, composition, inputProps, codec: 'h264', crf: 23, audioBitrate: AUDIO_BITRATE, concurrency: Number(process.env.YUO_RENDER_CONCURRENCY || 2),
	outputLocation: out, puppeteerInstance: chrome, timeoutInMilliseconds: timeoutMs,
});
await chrome.close({silent: true});
fs.rmSync(path.join(ws, 'bundle'), {recursive: true, force: true});
console.log(JSON.stringify({frames: composition.durationInFrames, fps: composition.fps}));
