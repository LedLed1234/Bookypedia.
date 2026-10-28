const CACHE_NAME = "bookypedia-shell-v64";
const SHELL = [
  "/static/css/app.css?v=52",
  "/static/js/app.js?v=60",
  "/static/manifest.webmanifest",
  "/static/config.json",
  "/static/icons/epiloguehouse-logo-header.png",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const requestUrl = new URL(event.request.url);
  // Fremde Ressourcen wie Open-Library-Cover gehören nicht in unseren App-
  // Cache. Bei einem Fehler müsste respondWith sonst eine fehlende Response
  // zurückgeben und der Browser verwirft das Bild vollständig.
  if (
    event.request.method !== "GET" ||
    requestUrl.origin !== self.location.origin ||
    requestUrl.pathname.startsWith("/api/")
  ) return;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request));
    return;
  }
  event.respondWith(
    fetch(event.request)
      .then(async (response) => {
        if (response.ok && response.type === "basic") {
          const copy = response.clone();
          const cache = await caches.open(CACHE_NAME);
          await cache.put(event.request, copy);
        }
        return response;
      })
      .catch(async (error) => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        throw error;
      })
  );
});

