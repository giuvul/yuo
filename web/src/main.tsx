// First import: global.css declares the cascade layer order, and a layer's place is fixed where it is
// first seen. Imported after the components, `components` would rank below `base` (browser tests).
import "./styles/global.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { activateLocale, browserLocale } from "./i18n";
import { Outbox } from "./outbox/outbox";
import { listenForInstall, registerServiceWorker } from "./pwa/pwa";
import { createQueryClient } from "./queryClient";
import { createAppRouter } from "./router";

// before anything is awaited: Chromium may offer installing as soon as the page loads, and a missed offer
// does not come again until the next load
listenForInstall();

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("#root element missing");

await activateLocale(browserLocale());

const outbox = new Outbox();
outbox.start(); // flush now, on `online`, and every 30 s
void registerServiceWorker(); // built mode only: the shell works offline; updates wait for "Reload to update"

createRoot(rootElement).render(
  <StrictMode>
    <App router={createAppRouter()} queryClient={createQueryClient()} outbox={outbox} />
  </StrictMode>,
);
