/* A short message at the top of the page offering to install ServeFlow as an app, so nobody has to dig through the browser's menu.
 * It shows for a few seconds, can be dismissed, and then stays out of the way (see shouldShow for the rules). */
import { el, icon } from "./ui.js";
import { canInstall, isIos, isStandalone, onInstallChange, promptInstall } from "./pwa.js";

const KEY = "serveflow:install-banner";
export const SHOW_MS = 6500;                 // how long it stays up
export const NOT_NOW_DAYS = 7;               // after "Not now", leave the person alone this long
export const REMIND_HOURS = 20;              // after it has been shown, wait this long before showing it again
const HOUR = 3600 * 1000;

/** Whether to show the banner now. Pure, so the rules can be tested. `state` is what we remembered: {dismissedAt, shownAt} in ms. */
export function shouldShow({ now, state = {}, standalone, installable, ios }) {
  if (standalone) return false;                                              // already installed and running as the app
  if (!installable && !ios) return false;                                    // nothing to offer on this browser
  if (state.dismissedAt && now - state.dismissedAt < NOT_NOW_DAYS * 24 * HOUR) return false;
  if (state.shownAt && now - state.shownAt < REMIND_HOURS * HOUR) return false;
  return true;
}

const read = () => { try { return JSON.parse(localStorage.getItem(KEY) ?? "{}") ?? {}; } catch { return {}; } };
const write = (patch) => { try { localStorage.setItem(KEY, JSON.stringify({ ...read(), ...patch })); } catch { /* storage blocked: it just shows again next time */ } };

/** Offer the install. `message` is what the page wants to say, e.g. "Install ServeFlow for one-tap ordering." */
const forced = () => typeof location !== "undefined" && /[?&]showinstall\b/i.test(location.search ?? ""); // for testing: add ?showInstall=1

export function mountInstallBanner({ message, iosMessage = "Tap Share, then Add to Home Screen to install.", delayMs = 1200 } = {}) {
  if (typeof document === "undefined" || !document.body || !message) return;
  let shown = false;

  const hide = (bar) => { bar.setAttribute("data-leaving", "true"); setTimeout(() => bar.remove?.(), 300); };

  function show() {
    if (shown || !shouldShow({ now: Date.now(), state: forced() ? {} : read(), standalone: isStandalone(), installable: canInstall(), ios: isIos() })) return;
    shown = true;
    if (!forced()) write({ shownAt: Date.now() });
    const ios = !canInstall() && isIos();
    const dismiss = el("button", { class: "btn btn--ghost btn--sm install-bar__later", type: "button" }, ios ? "Got it" : "Not now");
    const actions = [dismiss];
    const bar = el("div", { class: "install-bar", role: "region", "aria-label": "Install the app", style: `--install-ms:${SHOW_MS}ms` },
      el("div", { class: "install-bar__inner" },
        el("span", { class: "install-bar__icon", "aria-hidden": "true" }, icon("phone")),
        el("p", { class: "install-bar__text" }, ios ? iosMessage : message),
        el("div", { class: "install-bar__actions" }, ...(ios ? [] : [el("button", { class: "btn btn--primary btn--sm", type: "button", "data-install": "true" }, "Install")]), ...actions)),
      el("span", { class: "install-bar__timer", "aria-hidden": "true" }));
    dismiss.addEventListener("click", () => { if (!forced()) write({ dismissedAt: ios ? Date.now() - (NOT_NOW_DAYS - 1) * 24 * HOUR : Date.now() });
      hide(bar); });
    bar.querySelector?.("[data-install]")?.addEventListener("click", async () => { await promptInstall(); hide(bar); });
    document.body.prepend(bar);
    setTimeout(() => hide(bar), SHOW_MS);
  }

  if (isIos()) setTimeout(show, delayMs);        // Safari can't be asked to install; we show how
  onInstallChange(() => setTimeout(show, 300));  // Chrome and others: as soon as the browser says it can install
  show();
}
