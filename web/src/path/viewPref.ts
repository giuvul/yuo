import { readText, writeText } from "../storage";

/** How the path page shows the skills: as the skill tree, a node graph (the default on every width), or as the list. */
export type PathViewMode = "tree" | "list";

const KEY = "yuo.path.view";

/** The viewer's last choice on this device; the tree when there is none or storage is closed. */
export function readPathView(): PathViewMode {
  return readText(KEY) === "list" ? "list" : "tree";
}

export function writePathView(view: PathViewMode): void {
  writeText(KEY, view);
}
