/**
 * PWA service worker for complete shell precaching, network-first navigation,
 * and network-with-cache-fallback static assets. API requests are never cached.
 */
const CACHE_NAME = "wfd-shopping-pwa-v12";
const APP_FALLBACK_PATH = "/app";
const APP_SHELL = [
  "/app",
  "/app/",
  "/static/js/shopping.js",
  "/static/shop_editor.js",
  "/static/meal_plans.js",
  "/static/home_tab.js",
  "/static/settings_tab.js",
  "/static/user_shell.js",
  "/static/js/api.js",
  "/static/js/performance_metrics.js",
  "/static/js/contracts.js",
  "/static/js/render.js",
  "/static/js/render_scheduler.js",
  "/static/js/gestures.js",
  "/static/js/sync.js",
  "/static/js/sync_coordinator.js",
  "/static/js/store/index.js",
  "/static/js/store/schema.js",
  "/static/js/store/commands.js",
  "/static/js/store/selectors.js",
  "/static/js/ptr.js",
  "/static/js/sw-setup.js",
  "/static/js/utils.js",
  "/static/shopping_app.css",
  "/static/user_app.css",
  "/shopping.webmanifest",
  "/static/pwa-icon-192.svg",
  "/static/pwa-icon-512.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
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
    event.respondWith(
      (async () => {
        try {
          const response = await fetch(request);
          if (!response || !response.ok) {
            throw new Error(`Navigation failed with status ${response ? response.status : "unknown"}.`);
          }
          const cache = await caches.open(CACHE_NAME);
          await cache.put(request, response.clone());
          await cache.put(APP_FALLBACK_PATH, response.clone());
          return response;
        } catch {
          const cachedShell = await caches.match(request)
            || await caches.match(APP_FALLBACK_PATH)
            || await caches.match("/app/");
          return cachedShell || Response.error();
        }
      })()
    );
    return;
  }

  const isAppRoute = url.pathname === "/app" || url.pathname === "/app/";
  const isStaticAsset = url.pathname.startsWith("/static/") || url.pathname === "/shopping.webmanifest";

  if (isAppRoute) {
    const cachePath = "/app";
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(cachePath, copy));
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(cachePath);
          return cached || Response.error();
        })
    );
    return;
  }

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
