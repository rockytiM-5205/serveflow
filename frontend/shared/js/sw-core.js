/* The part of the service worker that both ServeFlow apps share. Loaded with importScripts(), so this is a plain script.
 *
 * Rules, on purpose:
 *  - Live data is never kept. /api/, /admin/, /media/ and /static/ always go to the network, so an order, a payment or a
 *    menu price can never be shown from an old copy.
 *  - Pages and scripts are fetched fresh first and remembered only as a fallback, so a new version is never held back.
 *  - A new worker never takes over a page that is already loading, so installing it can't interrupt anything.
 *  - With no connection the app shows a clear "you're offline" page instead of the browser's error.
 */
function serveflowServiceWorker({ name, push = false }) {
  const CACHE = `serveflow-${name}-v1`;
  const OFFLINE = "/shared/offline.html";
  const LIVE = /^\/(api|admin|media|static)\//;

  self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE)).catch(() => {}).then(() => self.skipWaiting()));
  });

  self.addEventListener("activate", (event) => {
    event.waitUntil(
      caches.keys()
        .then((keys) => Promise.all(keys.filter((k) => k.startsWith(`serveflow-${name}-`) && k !== CACHE).map((k) => caches.delete(k)))));
  });

  self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin || LIVE.test(url.pathname)) return;
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (response.ok && response.type === "basic") {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
        }
        return response;
      } catch {
        const cached = await caches.match(request);
        if (cached) return cached;
        if (request.mode === "navigate") return (await caches.match(OFFLINE)) ?? Response.error();
        return Response.error();
      }
    })());
  });

  if (!push) return;

  self.addEventListener("push", (event) => {
    let data = {};
    try { data = event.data ? event.data.json() : {}; } catch { data = {}; }
    event.waitUntil(self.registration.showNotification(String(data.title || "ServeFlow").slice(0, 80), {
      body: String(data.body || "").slice(0, 160),
      icon: "/shared/assets/icons/icon-192.png",
      badge: "/shared/assets/icons/badge-96.png",
      tag: String(data.tag || "serveflow"),
      renotify: true,
      requireInteraction: true, // a new order stays on screen until someone taps it
      vibrate: [200, 100, 200],
      data: { url: typeof data.url === "string" && data.url.startsWith("/restaurant-dashboard/") ? data.url : "/restaurant-dashboard/orders.html" },
    }));
  });

  self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const target = new URL(event.notification.data?.url || "/restaurant-dashboard/orders.html", self.location.origin).href;
    event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url.startsWith(`${self.location.origin}/restaurant-dashboard/`));
      return open ? open.focus() : self.clients.openWindow(target);
    }));
  });
}
