const CACHE_NAME = "wfd-shopping-pwa-__WFD_BUILD_ID__";
const APP_FALLBACK_PATH = "/app";
const NAVIGATION_TIMEOUT_MS = 3000;
const APP_SHELL = [
  "/app",
  ...__WFD_CLIENT_ASSETS__,
  "/shopping.webmanifest",
  "/static/pwa-icon-192.svg",
  "/static/pwa-icon-512.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  const isSameOrigin = url.origin === self.location.origin;
  if (!isSameOrigin) {
    return;
  }

  if (request.mode === "navigate") {
    // Network-first for navigate: use the current shell online and cached shell offline.
    event.respondWith(
      (async () => {
        const fallbackPath = APP_FALLBACK_PATH;
        try {
          const response = await fetch(request, { signal: AbortSignal.timeout(NAVIGATION_TIMEOUT_MS) });
          if (response.ok) {
            const cache = await caches.open(CACHE_NAME);
            await cache.put(fallbackPath, response.clone());
            return response;
          }
          const cachedShell = await caches.match(fallbackPath);
          if (cachedShell) {
            return cachedShell;
          }
          return response;
        } catch {
          const cachedShell = await caches.match(fallbackPath);
          return cachedShell || Response.error();
        }
      })()
    );
    return;
  }

  const isStaticAsset = url.pathname.startsWith("/static/") || url.pathname === "/shopping.webmanifest";

  if (isStaticAsset) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        const cacheKey = url.pathname;
        const cached = await cache.match(cacheKey);
        try {
          const response = await fetch(request);
          if (response && response.ok) {
            await cache.put(cacheKey, response.clone());
          }
          return response;
        } catch {
          return cached || Response.error();
        }
      })()
    );
  }
});
