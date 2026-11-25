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

/** Returns "on" when alerts are now on, or "denied" if the person said no. */
export async function turnOn({ api, base, publicKey }) {
  if ((await Notification.requestPermission()) !== "granted") return "denied";
  const registration = await navigator.serviceWorker.ready;
  const subscription = (await registration.pushManager.getSubscription())
    ?? (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(publicKey) }));
  const { endpoint, keys } = subscription.toJSON();
  await api.post(`${base}/push/subscribe/`, { endpoint, p256dh: keys.p256dh, auth: keys.auth });
  return "on";
}

export async function turnOff({ api, base }) {
  const subscription = await thisDevice();
  if (!subscription) return;
  await api.post(`${base}/push/unsubscribe/`, { endpoint: subscription.endpoint });
  await subscription.unsubscribe();
}
