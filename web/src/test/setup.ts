import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { closeApps } from "./renderApp";

// jsdom does not implement scrolling; TanStack Router calls it on navigation.
window.scrollTo = () => {};

afterEach(async () => {
  cleanup();
  await closeApps();
});

// jsdom has no layout: the node-graph library (the path graph) asks for these when it mounts. Nothing is ever
// measured here, so the observer never reports.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
