// The service worker (06 §1.2, vite-plugin-pwa injectManifest + Workbox): it precaches the app shell and
// the built static assets, and answers app navigations with the cached shell so the app opens offline.
// It never caches or answers `/api` (sign-in, sessions and learning data always go to the server; the
// outbox in IndexedDB keeps events while offline).
/// <reference lib="webworker" />
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: (string | { url: string; revision: string | null })[] };

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

registerRoute(new NavigationRoute(createHandlerBoundToURL("index.html"), { denylist: [/^\/api(\/|$)/] }));

// "Reload to update": the page asks the waiting worker to take over, then reloads.
self.addEventListener("message", (event) => {
  if ((event.data as { type?: string } | null)?.type === "SKIP_WAITING") void self.skipWaiting();
});
