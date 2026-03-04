<<<<<<< HEAD
/* sw.js — sane PWA caching for iOS */
const VERSION = "v2026-02-12-01"; // <- cambiá esto cuando quieras forzar update
const CACHE = `cartelera-${VERSION}`;

// Qué cachear (assets “estáticos”)
=======
/* sw.js — stable PWA caching for GitHub Pages */

const VERSION = "v2026-03-04-02";   // cambiar cuando quieras forzar actualización
const CACHE = `cartelera-${VERSION}`;

// Assets básicos de la app
>>>>>>> 9c4cbcb1 (Fix service worker cache strategy)
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
<<<<<<< HEAD
  "./sw.js",
];

// Install: cachea y activa rápido
=======
  "./sw.js"
];


// INSTALL
>>>>>>> 9c4cbcb1 (Fix service worker cache strategy)
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

<<<<<<< HEAD
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

// Activate: limpia cachés viejos y toma control ya
=======

// ACTIVATE
>>>>>>> 9c4cbcb1 (Fix service worker cache strategy)
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.map((key) => {
          if (key !== CACHE) {
            return caches.delete(key);
          }
        })
      )
    ).then(() => self.clients.claim())
  );
});

<<<<<<< HEAD
// Fetch strategy:
// - HTML: NetworkFirst (si hay red, trae lo nuevo)
// - Otros: CacheFirst (rápido)
=======

// permitir forzar actualización desde la página
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});


// FETCH
>>>>>>> 9c4cbcb1 (Fix service worker cache strategy)
self.addEventListener("fetch", (event) => {

  const req = event.request;

  if (req.method !== "GET") return;

  const url = new URL(req.url);
<<<<<<< HEAD

  // Solo tu misma origin
  if (url.origin !== self.location.origin) return;
=======

  if (url.origin !== self.location.origin) return;

>>>>>>> 9c4cbcb1 (Fix service worker cache strategy)

  const isHTML =
    req.mode === "navigate" ||
    (req.headers.get("accept") || "").includes("text/html") ||
    url.pathname.endsWith("/") ||
    url.pathname.endsWith("/index.html");


  const isSchedule =
    url.pathname.endsWith("/schedule.json");


  /*
  -------------------------
  HTML → Network First
  -------------------------
  */
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


  /*
  -------------------------
  schedule.json → Network First
  -------------------------
  */
  if (isSchedule) {

    event.respondWith(

      fetch(req, { cache: "no-store" })
        .then((res) => {

          const copy = res.clone();

          caches.open(CACHE).then((c) => c.put(req, copy));

          return res;

        })
        .catch(() => caches.match(req))

    );

    return;
  }


  /*
  -------------------------
  Otros assets → Cache First
  -------------------------
  */
  event.respondWith(
<<<<<<< HEAD
    caches.match(req).then((cached) => cached || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
      return res;
    }))
=======

    caches.match(req).then((cached) => {

      if (cached) return cached;

      return fetch(req).then((res) => {

        const copy = res.clone();

        caches.open(CACHE).then((c) => c.put(req, copy));

        return res;

      });

    })

>>>>>>> 9c4cbcb1 (Fix service worker cache strategy)
  );

});