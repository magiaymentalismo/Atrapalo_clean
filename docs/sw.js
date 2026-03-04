/* sw.js — sane PWA caching for iOS */
const VERSION = "v2026-03-04-01"; // subí esto cada vez que quieras forzar update
const CACHE = `cartelera-${VERSION}`;

const ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./sw.js",
  "./schedule.json", // <- opcional cachear como fallback, pero OJO: NO lo usamos como fuente principal
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k !== CACHE ? caches.delete(k) : Promise.resolve())))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // ✅ EXCEPCIÓN CLAVE: schedule.json SIEMPRE de red (y no lo “congelamos”)
  if (url.pathname.endsWith("/schedule.json")) {
    event.respondWith(
      fetch(req, { cache: "no-store" })
        .then((res) => res)
        .catch(() => caches.match("./schedule.json"))
    );
    return;
  }

  const isHTML =
    req.mode === "navigate" ||
    (req.headers.get("accept") || "").includes("text/html") ||
    url.pathname.endsWith("/") ||
    url.pathname.endsWith("/index.html");

  if (isHTML) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("./index.html", copy));
          return res;
        })
        .catch(() => caches.match("./index.html"))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) =>
      cached ||
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      })
    )
  );
});