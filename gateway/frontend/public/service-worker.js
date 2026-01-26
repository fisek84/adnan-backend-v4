/* eslint-disable no-restricted-globals */

const CACHE_VERSION = "v1";
const STATIC_CACHE = `static-${CACHE_VERSION}`;
const OFFLINE_CACHE = `offline-${CACHE_VERSION}`;

const OFFLINE_URL = "/offline.html";

const PRECACHE_URLS = [
  OFFLINE_URL,
  "/manifest.webmanifest",
  "/apple-touch-icon.png",
  "/favicon-16.png",
  "/favicon-32.png",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-192-maskable.png",
  "/icon-512-maskable.png",
];

function isNetworkOnlyPath(pathname) {
  return (
    pathname.startsWith("/api/") ||
    pathname === "/api" ||
    pathname.startsWith("/auth") ||
    pathname.startsWith("/login") ||
    pathname.startsWith("/logout") ||
    pathname.startsWith("/callback") ||
    pathname.startsWith("/oauth") ||
    pathname.startsWith("/ws") ||
    pathname.startsWith("/socket") ||
    pathname.startsWith("/sse") ||
    pathname.startsWith("/stream")
  );
}

function isStaticAssetRequest(request, url) {
  if (request.method !== "GET") return false;
  if (url.origin !== self.location.origin) return false;

  if (url.pathname.startsWith("/assets/")) return true; // Vite build output

  const dest = request.destination;
  if (dest === "script" || dest === "style" || dest === "image" || dest === "font") return true;

  return (
    url.pathname.endsWith(".js") ||
    url.pathname.endsWith(".css") ||
    url.pathname.endsWith(".png") ||
    url.pathname.endsWith(".ico") ||
    url.pathname.endsWith(".svg") ||
    url.pathname.endsWith(".webmanifest")
  );
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request)
    .then((response) => {
      // Only cache successful same-origin basic responses.
      if (response && response.ok && response.type === "basic") {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => undefined);

  return cached || (await fetchPromise);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const offlineCache = await caches.open(OFFLINE_CACHE);
      await offlineCache.addAll(PRECACHE_URLS);
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if (key !== STATIC_CACHE && key !== OFFLINE_CACHE) return caches.delete(key);
          return Promise.resolve();
        })
      );
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  // Required for Chrome when request.cache === 'only-if-cached' and mode !== 'same-origin'
  if (request.cache === "only-if-cached" && request.mode !== "same-origin") return;

  const url = new URL(request.url);

  // Never cache API/auth/dynamic endpoints.
  if (url.origin === self.location.origin && isNetworkOnlyPath(url.pathname)) {
    event.respondWith(fetch(request));
    return;
  }

  // Offline fallback ONLY for navigations.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        const offlineCache = await caches.open(OFFLINE_CACHE);
        const cached = await offlineCache.match(OFFLINE_URL);
        return (
          cached ||
          new Response("Offline", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          })
        );
      })
    );
    return;
  }

  // Static assets: stale-while-revalidate.
  if (isStaticAssetRequest(request, url)) {
    event.respondWith(
      (async () => {
        const response = await staleWhileRevalidate(request);
        return response || fetch(request);
      })()
    );
  }
});
