const CACHE_NAME = "wfd-shopping-pwa-v2";
const SHOPPING_FALLBACK_PATH = "/shopping";
const APP_SHELL = [
  "/shopping",
  "/shopping/",
  "/static/shopping_mode.js",
  "/shopping.webmanifest",
  "/static/pwa-icon-192.svg",
  "/static/pwa-icon-512.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await Promise.all(APP_SHELL.map(async (path) => {
        try {
          const response = await fetch(path, { cache: "no-store" });
          if (response && response.ok) {
            await cache.put(path, response.clone());
          }
        } catch {
          // Ignore individual precache failures.
        }
      }));
    })
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
    event.respondWith(
      fetch(request)
        .then(async (response) => {
          if (response && response.ok) {
            const cache = await caches.open(CACHE_NAME);
            await cache.put(SHOPPING_FALLBACK_PATH, response.clone());
          }
          return response;
        })
        .catch(async () => {
          const cachedRoute = await caches.match(url.pathname);
          if (cachedRoute) {
            return cachedRoute;
          }
          const fallback = await caches.match(SHOPPING_FALLBACK_PATH);
          return fallback || Response.error();
        })
    );
    return;
  }

  const isShoppingRoute = url.pathname === "/shopping" || url.pathname === "/shopping/";
  const isStaticAsset = url.pathname.startsWith("/static/") || url.pathname === "/shopping.webmanifest";

  if (isShoppingRoute) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("/shopping", copy));
          return response;
        })
        .catch(async () => {
          const cached = await caches.match("/shopping");
          return cached || Response.error();
        })
    );
    return;
  }

  if (isStaticAsset) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) {
          return cached;
        }
        return fetch(request).then((response) => {
          if (!response || response.status !== 200) {
            return response;
          }
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        });
      })
    );
  }
});
