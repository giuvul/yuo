// Builds src/styles/tokens.css from the DTCG token files in tokens/ (Design Tokens Format Module 2025.10).
//
//   node scripts/tokens.mjs           write the CSS
//   node scripts/tokens.mjs --check   fail when the CSS is out of date or a contrast pair fails
//
// Tiers: color.tokens.json holds the primitives (OKLCH ramps) and is NOT emitted as CSS, so components cannot
// reach them; semantic.<theme>.tokens.json alias primitives by role and become --yuo-color-<role> per theme;
// base.tokens.json holds the scales (type, space, radius, elevation, motion) as --yuo-<group>-<name>.
// Every text/background pair in PAIRS must reach WCAG 2.x AA (4.5:1) in both themes.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const TOKENS = join(WEB, "tokens");
const OUT = join(WEB, "src", "styles", "tokens.css");
const read = (name) => JSON.parse(readFileSync(join(TOKENS, name), "utf8"));

const primitives = read("color.tokens.json");
const base = read("base.tokens.json");
const themes = { light: read("semantic.light.tokens.json"), dark: read("semantic.dark.tokens.json") };

/** [text, background, minimum ratio] by semantic colour name. */
const PAIRS = [
  ["fg", "bg", 4.5],
  ["fg", "surface", 4.5],
  ["fg", "surface-muted", 4.5],
  ["muted", "bg", 4.5],
  ["muted", "surface", 4.5],
  ["accent-fg", "accent", 4.5],
  ["accent-fg", "accent-hover", 4.5],
  ["link", "bg", 4.5],
  ["link", "surface", 4.5],
  ["highlight-fg", "highlight", 4.5],
  ["success", "success-bg", 4.5],
  ["warning", "warning-bg", 4.5],
  ["danger", "danger-bg", 4.5],
  ["fg", "info-bg", 4.5],
  ["fg", "code-bg", 4.5],
  ["focus", "bg", 3],
  ["border-strong", "bg", 1.8],
  ["media-fg", "media-bg", 4.5],
  ["media-fg", "media-bar", 4.5],
  // the path tree: lines and outlines that carry meaning (3:1, WCAG 1.4.11)
  ["twig", "bg", 3],
  ["leaf", "bg", 3],
  ["illus-clay", "bg", 3],
];

function lookup(root, path) {
  return path.split(".").reduce((node, key) => (node == null ? undefined : node[key]), root);
}

/** A token's value with aliases resolved against the primitives, then the file itself. */
function resolve(value, file, seen = new Set()) {
  if (typeof value === "string" && /^\{[^}]+\}$/.test(value)) {
    const path = value.slice(1, -1);
    if (seen.has(path)) throw new Error(`alias cycle at {${path}}`);
    const target = lookup(primitives, path) ?? lookup(base, path) ?? lookup(file, path);
    if (!target || !("$value" in target)) throw new Error(`unknown token {${path}}`);
    return resolve(target.$value, file, new Set([...seen, path]));
  }
  return value;
}

function color(v) {
  if (typeof v === "string") return v;
  if (v.hex) {
    return v.alpha !== undefined && v.alpha < 1 ? rgba(v) : v.hex.toUpperCase();
  }
  if (v.colorSpace === "srgb") return rgba(v);
  throw new Error(`colour without hex fallback: ${JSON.stringify(v)}`);
}

function rgba(v) {
  const [r, g, b] = v.components.map((c) => Math.round(c * 255));
  return `rgb(${r} ${g} ${b} / ${v.alpha ?? 1})`;
}

const dim = (v) => `${v.value}${v.unit}`;

function css(type, raw, file) {
  const v = resolve(raw, file);
  switch (type) {
    case "color":
      return color(v);
    case "dimension":
    case "duration":
      return dim(v);
    case "fontFamily":
      return (Array.isArray(v) ? v : [v]).map((f) => (/[\s-]/.test(f) && !f.includes("-apple") && !/^ui-|sans-serif|monospace|system-ui/.test(f) ? `"${f}"` : f)).join(", ");
    case "fontWeight":
    case "number":
      return String(v);
    case "cubicBezier":
      return `cubic-bezier(${v.join(", ")})`;
    case "shadow":
      return (Array.isArray(v) ? v : [v])
        .map((s) => `${dim(s.offsetX)} ${dim(s.offsetY)} ${dim(s.blur)} ${dim(s.spread)} ${color(s.color)}`)
        .join(", ");
    default:
      throw new Error(`unsupported token type ${type}`);
  }
}

/** Flattens a token tree into [css name, css value] (names join the path with "-"; "$type" inherits). */
function flatten(node, file, prefix = [], inherited) {
  const out = [];
  const type = node.$type ?? inherited;
  for (const [key, child] of Object.entries(node)) {
    if (key.startsWith("$")) continue;
    const childType = child.$type ?? type;
    if (child && typeof child === "object" && "$value" in child) {
      out.push([`--yuo-${[...prefix, key].join("-")}`, css(childType, child.$value, file)]);
    } else if (child && typeof child === "object") {
      out.push(...flatten(child, file, [...prefix, key], childType));
    }
  }
  return out;
}

function luminance(hex) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const block = (selector, vars, extra = "") =>
  `${selector} {\n${extra}${vars.map(([k, v]) => `  ${k}: ${v};`).join("\n")}\n}\n`;

/** Base groups only the themes publish (as their own tokens). */
const publicBase = Object.fromEntries(Object.entries(base).filter(([k]) => k !== "elevation"));

const problems = [];
const themeVars = {};
for (const [name, file] of Object.entries(themes)) {
  themeVars[name] = flatten(file, file);
  const colors = Object.fromEntries(themeVars[name].map(([k, v]) => [k.replace("--yuo-color-", ""), v]));
  for (const [fg, bg, min] of PAIRS) {
    if (!colors[fg] || !colors[bg]) {
      problems.push(`${name}: ${fg} on ${bg} is not defined`);
      continue;
    }
    const r = ratio(colors[fg], colors[bg]);
    if (r < min) problems.push(`${name}: ${fg} ${colors[fg]} on ${bg} ${colors[bg]} is ${r.toFixed(2)}:1, needs ${min}:1`);
  }
}
const light = Object.keys(Object.fromEntries(themeVars.light));
const dark = Object.keys(Object.fromEntries(themeVars.dark));
if (light.join() !== dark.join()) problems.push("the light and dark themes must define the same tokens");

const header = `/* Generated by scripts/tokens.mjs from tokens/*.tokens.json (DTCG 2025.10). Do not edit: change the tokens and
   run \`npm run tokens\`. Light by default, dark when the system asks for it, and an explicit choice
   (html[data-theme="light"|"dark"], set by src/theme.ts) wins both ways. */\n`;
const output =
  header +
  block(":root", [...flatten(publicBase, base), ...themeVars.light], "  color-scheme: light dark;\n") +
  "\n@media (prefers-color-scheme: dark) {\n" +
  block(':root:not([data-theme="light"])', themeVars.dark)
    .split("\n")
    .map((l) => (l ? `  ${l}` : l))
    .join("\n") +
  "}\n\n" +
  block(':root[data-theme="light"]', [], "  color-scheme: light;\n") +
  "\n" +
  block(':root[data-theme="dark"]', themeVars.dark, "  color-scheme: dark;\n");

if (problems.length) {
  for (const p of problems) console.error(`tokens: ${p}`);
  process.exit(1);
}
if (process.argv.includes("--check")) {
  let current = "";
  try {
    current = readFileSync(OUT, "utf8");
  } catch {
    // missing: out of date
  }
  if (current !== output) {
    console.error("tokens: src/styles/tokens.css is out of date, run `npm run tokens`");
    process.exit(1);
  }
  console.log("tokens: up to date, contrast pairs pass");
} else {
  writeFileSync(OUT, output);
  console.log(`tokens: wrote ${OUT}`);
}
