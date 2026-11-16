// Shared by stills.mjs and render.mjs. A job workspace (written by yuo/adapters/renderer) holds src/ (the kit and
// the generated src/gen/scene.tsx), public/ (timeline.json, narration.wav) and a node_modules link to this package.
// The bundle goes into the workspace, never /tmp: Remotion copies publicDir into every bundle and keeps it.
import {bundle} from '@remotion/bundler';
import {openBrowser} from '@remotion/renderer';
import fs from 'node:fs';
import path from 'node:path';

// The page may load nothing from the network; with self-hosted fonts every render still works.
const CSP =
	"default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; connect-src 'self'; img-src 'self' data: blob:; " +
	"media-src 'self' data: blob:; font-src 'self' data:; frame-src 'none'; object-src 'none'";

/**
 * Remotion keeps every frame of a render in the system temp folder before it encodes them, and Chrome keeps its
 * profile there. In the container /tmp is a 512 MB in-memory disk, which a few minutes of video outgrow
 * (ENOSPC at the final render). Both go into the job's workspace on the data disk instead,
 * removed with it. Call before anything starts the bundler or the browser.
 */
export function workspaceTmp(ws) {
	const dir = path.join(ws, 'tmp');
	fs.mkdirSync(dir, {recursive: true});
	process.env.TMPDIR = dir;
	return dir;
}

export async function makeBundle(ws) {
	const outDir = path.join(ws, 'bundle');
	fs.rmSync(outDir, {recursive: true, force: true});
	const serveUrl = await bundle({
		entryPoint: path.join(ws, 'src', 'index.ts'),
		publicDir: path.join(ws, 'public'),
		outDir,
		enableCaching: false,
	});
	const index = path.join(outDir, 'index.html');
	const html = fs.readFileSync(index, 'utf8');
	fs.writeFileSync(index, html.replace('<head>', `<head><meta http-equiv="Content-Security-Policy" content="${CSP}">`));
	return serveUrl;
}

export async function browser() {
	const browserExecutable = process.env.YUO_CHROME || null;
	return openBrowser('chrome', {browserExecutable, chromiumOptions: {gl: 'swiftshader'}});
}

export const timeoutMs = Number(process.env.YUO_RENDER_TIMEOUT_MS || 60000);
