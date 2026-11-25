/* A small free-trial banner. It slides in after the visitor has been on the page for a couple of minutes, stays for a
 * short while, then slides away, once per visit. It only appears when there are real plans to point at.
 * Tune the two numbers below. Add ?promo=now to the address to preview it after 1.5 seconds. */
import { api } from "../shared/js/api.js";

const SHOW_AFTER_MS = 2 * 60 * 1000;
const VISIBLE_FOR_MS = 20 * 1000;
const SEEN_KEY = "serveflow:promo-seen";

const promo = document.getElementById("promo");
const preview = new URLSearchParams(location.search).get("promo") === "now";
const seen = () => { try { return sessionStorage.getItem(SEEN_KEY) === "1"; } catch { return false; } };
const remember = () => { try { sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* ignore */ } };

function hide() {
  if (promo.hidden) return;
  remember();
  promo.classList.remove("is-in");
  setTimeout(() => { promo.hidden = true; }, 600);
}

function show() {
  if (document.hidden) { document.addEventListener("visibilitychange", () => show(), { once: true }); return; }
  promo.hidden = false;
  requestAnimationFrame(() => requestAnimationFrame(() => promo.classList.add("is-in")));
  let timer = setTimeout(hide, VISIBLE_FOR_MS);
  const hold = () => clearTimeout(timer); // stay put while someone is reading or aiming at it
  const release = () => { clearTimeout(timer); timer = setTimeout(hide, 6000); };
  promo.addEventListener("mouseenter", hold);
  promo.addEventListener("focusin", hold);
  promo.addEventListener("mouseleave", release);
  promo.addEventListener("focusout", release);
}

async function main() {
  if (!promo || (seen() && !preview)) return;
  try {
    const data = await api.get("/billing/plans/");
    if (!data.plans.length) return; // nothing to promote yet
    const days = Number.isFinite(data.trial_days) && data.trial_days > 0 ? data.trial_days : null;
    document.getElementById("promo-title").textContent = days ? `Start your ${days}-day free trial` : "Start your free trial";
    document.getElementById("promo-sub").textContent = " No card needed. Pay by bank transfer when you're ready.";
  } catch { return; }
  promo.querySelector(".promo__close").addEventListener("click", hide);
  document.getElementById("promo-cta").addEventListener("click", hide);
  setTimeout(show, preview ? 1500 : SHOW_AFTER_MS);
}

main();
