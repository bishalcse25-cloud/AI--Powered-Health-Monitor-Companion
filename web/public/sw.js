/* Health Companion service worker — minimal app-shell cache.
 *
 * Strategy:
 *   - API calls (/api/*) and cross-origin requests: never touched, always network.
 *   - Navigations: network-first, fall back to the cached shell when offline.
 *   - Other same-origin GETs (JS/CSS/icons): stale-while-revalidate.
 */

const CACHE = "hc-shell-v1";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("/index.html").then((r) => r || Response.error())),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((resp) => {
          if (resp.ok) caches.open(CACHE).then((c) => c.put(request, resp.clone()));
          return resp;
        })
        .catch(() => cached || Response.error());
      return cached || network;
    }),
  );
});
