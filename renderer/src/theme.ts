// Self-hosted fonts (a render without network needs them local); the CSS imports are bundled.
import '@fontsource/inter/400.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/800.css';
import '@fontsource/jetbrains-mono/500.css';
import '@fontsource/jetbrains-mono/700.css';

export const fontFamily = "'Inter', sans-serif";
export const monoFamily = "'JetBrains Mono', monospace";

// Video theme tokens: the palette is src/themes/<name>.ts, chosen per video. A job
// workspace points the line below at the chosen theme (yuo/adapters/renderer/remotion.py, THEME_LINE).
export {C} from './themes/dark';

/** A theme colour with transparency: alpha(C.read, 0.3). Scenes use it instead of rgba() literals. */
export const alpha = (hex: string, a: number): string =>
	hex + Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, '0');
