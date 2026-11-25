/* Installing ServeFlow like an app: the service worker, the "Install app" prompt, and each restaurant's own manifest.
 * Nothing here runs at import time, so it is safe in tests and in browsers without these features. */

let deferred = null;
let watching = false;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => fn());

export const isStandalone = () => {
  try { return Boolean(globalThis.matchMedia?.("(display-mode: standalone)")?.matches) || globalThis.navigator?.standalone === true; } catch { return false; }
};
export const isIos = () => /iphone|ipad|ipod/i.test(globalThis.navigator?.userAgent ?? "");

/** Register the app's service worker. Resolves to null when the browser can't (or won't): the site then works as a normal website. */
export function registerServiceWorker(url, scope) {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return Promise.resolve(null);
  return navigator.serviceWorker.register(url, { scope }).catch(() => null);
}

/** Start listening for the browser saying "this can be installed". Call once, early. */
export function watchInstall() {
  if (watching || typeof window === "undefined" || !window.addEventListener) return;
  watching = true;
  window.addEventListener("beforeinstallprompt", (event) => { event.preventDefault(); deferred = event; notify(); });
  window.addEventListener("appinstalled", () => { deferred = null; notify(); });
}

export const canInstall = () => Boolean(deferred) && !isStandalone();
export const onInstallChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };

export async function promptInstall() {
  if (!deferred) return "unavailable";
  const event = deferred;
  deferred = null;
  event.prompt();
  const choice = await event.userChoice.catch(() => ({ outcome: "dismissed" }));
  notify();
  return choice.outcome;
}

/** Where a restaurant's own manifest lives (its name, logo and start page), so "Add to Home Screen" installs that restaurant. */
export const restaurantManifestHref = (slug) => `/api/v1/restaurants/${encodeURIComponent(slug)}/manifest.webmanifest`;

export function useRestaurantManifest(slug, { document: doc = globalThis.document } = {}) {
  const link = doc?.querySelector?.('link[rel="manifest"]');
  if (link && slug) link.setAttribute("href", restaurantManifestHref(slug));
}

/** The picture iPhones use for the home-screen icon. */
export function useHomeScreenIcon(src, { document: doc = globalThis.document } = {}) {
  const link = doc?.querySelector?.('link[rel="apple-touch-icon"]');
  if (link && src) link.setAttribute("href", src);
}
