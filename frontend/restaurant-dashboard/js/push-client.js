/* Order alerts on this device: ask permission, subscribe, and tell ServeFlow, or undo it. */

export const pushSupported = () =>
  typeof navigator !== "undefined" && "serviceWorker" in navigator && typeof window !== "undefined" && "PushManager" in window && "Notification" in window;

/** The browser wants the server's public key as bytes, not as base64url text. */
export function keyToBytes(base64url) {
  const padded = `${base64url}${"=".repeat((4 - (base64url.length % 4)) % 4)}`.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function thisDevice() {
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

/** True when this browser subscription was made with the server's current public key. After the server's alert keys change, an old
 *  subscription is refused by the push service, so it has to be replaced. */
export function sameKey(subscription, publicKey) {
  const stored = subscription?.options?.applicationServerKey;
  if (!stored) return true; // the browser doesn't say: don't throw a working subscription away
  const a = new Uint8Array(stored);
  const b = keyToBytes(publicKey);
  return a.length === b.length && a.every((value, i) => value === b[i]);
}

async function subscribeFresh(registration, publicKey) {
  const existing = await registration.pushManager.getSubscription();
  if (existing && sameKey(existing, publicKey)) return existing;
  if (existing) await existing.unsubscribe(); // made with an old key
  return registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(publicKey) });
}

async function tellServer(api, base, subscription) {
  const { endpoint, keys } = subscription.toJSON();
  await api.post(`${base}/push/subscribe/`, { endpoint, p256dh: keys.p256dh, auth: keys.auth });
}

/** Returns "on" when alerts are now on, or "denied" if the person said no. */
export async function turnOn({ api, base, publicKey }) {
  if ((await Notification.requestPermission()) !== "granted") return "denied";
  const registration = await navigator.serviceWorker.ready;
  await tellServer(api, base, await subscribeFresh(registration, publicKey));
  return "on";
}

/** Quiet housekeeping each time the dashboard opens on a device that already has alerts on: make sure ServeFlow still knows this
 *  device (it forgets devices a push service reports as gone), and replace a subscription made with an old key. Never shows an error,
 *  never asks for permission, and never switches alerts on by itself. */
export async function syncDevice({ api, base, storage = globalThis.localStorage, now = Date.now() }) {
  try {
    if (!pushSupported() || Notification.permission !== "granted") return;
    const key = "sf:push-sync";
    if (now - Number(storage?.getItem(key) ?? 0) < 6 * 60 * 60 * 1000) return; // at most every few hours
    const registration = await navigator.serviceWorker.ready;
    if (!(await registration.pushManager.getSubscription())) return; // alerts aren't on for this device: the person's choice
    const config = await api.get(`${base}/push/config/`);
    if (!config.enabled) return;
    await tellServer(api, base, await subscribeFresh(registration, config.public_key));
    storage?.setItem(key, String(now));
  } catch { /* housekeeping only */ }
}

export async function turnOff({ api, base }) {
  const subscription = await thisDevice();
  if (!subscription) return;
  await api.post(`${base}/push/unsubscribe/`, { endpoint: subscription.endpoint });
  await subscription.unsubscribe();
}
