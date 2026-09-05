const CACHE_NAME = "wfd-shopping-pwa-v11";
const APP_FALLBACK_PATH = "/app";
const APP_SHELL = [
  "/app",
  "/static/js/shopping.js",
  "/static/shop_editor.js",
  "/static/meal_plans.js",
  "/static/home_tab.js",
  "/static/settings_tab.js",
  "/static/user_shell.js",
  "/static/js/state.js",
  "/static/js/api.js",
  "/static/js/contracts.js",
  "/static/js/render.js",
  "/static/js/gestures.js",
  "/static/js/sync.js",
  "/static/js/commands/connectivity.js",
  "/static/js/commands/home.js",
  "/static/js/commands/meal-plans.js",
  "/static/js/commands/settings.js",
  "/static/js/commands/shopping-ui.js",
  "/static/js/commands/shopping.js",
  "/static/js/selectors/connectivity.js",
  "/static/js/selectors/shopping.js",
  "/static/js/store/meal-plan-model.js",
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
    // Cache-first for navigate: serve shell immediately offline, update cache in background.
    event.respondWith(
      (async () => {
        const fallbackPath = APP_FALLBACK_PATH;
        const cachedShell = await caches.match(fallbackPath);
        const networkFetch = fetch(request)
          .then(async (response) => {
            if (response && response.ok) {
              const cache = await caches.open(CACHE_NAME);
              await cache.put(fallbackPath, response.clone());
            }
            return response;
          })
          .catch(() => null);
        if (cachedShell) {
          networkFetch.catch(() => {});
          return cachedShell;
        }
        const networkResponse = await networkFetch;
        return networkResponse || Response.error();
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
