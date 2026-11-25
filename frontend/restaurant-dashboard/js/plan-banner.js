/* A banner at the top of the dashboard that tells the restaurant's admin where their subscription stands, so the end of the
 * free trial never comes as a surprise. Display only: the server decides when anything locks. */
import { api } from "../../shared/js/api.js";
import { el, icon } from "../../shared/js/ui.js";
import { subscriptionEndedBanner } from "../../shared/js/subscription.js";

export function timeLeft(ms) {
  if (!(ms > 0)) return null;
  const minutes = Math.floor(ms / 60000), hours = Math.floor(minutes / 60), days = Math.floor(hours / 24);
  if (days >= 1) return `${days} day${days === 1 ? "" : "s"}${hours % 24 ? ` ${hours % 24} h` : ""}`;
  if (hours >= 1) return `${hours} h ${minutes % 60} min`;
  return `${Math.max(minutes, 1)} min`;
}

const banner = (tone, title, text) => el("div", { class: `alert alert--${tone}`, id: "plan-banner", role: "status" }, icon(tone === "warning" ? "alert" : "info"),
  el("div", { style: "flex:1" }, el("strong", {}, title), el("p", {}, text)),
  el("a", { class: "btn btn--primary btn--sm", href: "billing.html" }, "Open Billing"));

/** Only the restaurant's admin sees billing. Failures are ignored: the banner is a courtesy, not a gate. */
export async function showPlanBanner(slug, role, now = Date.now()) {
  if (role !== "OWNER") return;
  try {
    const { subscription: sub } = await api.get(`/restaurants/${encodeURIComponent(slug)}/billing/`);
    if (!sub) return;
    const main = document.getElementById("main");
    if (document.getElementById("plan-banner") || document.getElementById("subscription-ended")) return;
    if (sub.status === "TRIAL") {
      const left = timeLeft(new Date(sub.trial_ends_at).getTime() - now);
      if (left) main.prepend(banner("info", `Your free trial ends in ${left}`, "Pay before then to keep taking orders. When the trial ends, your restaurant stops working until the payment is confirmed."));
      else main.prepend(subscriptionEndedBanner());
    } else if (sub.status === "PAST_DUE") {
      main.prepend(banner("warning", "Your payment is overdue", "Pay now to avoid losing access. Your restaurant stops taking orders if it isn't confirmed soon."));
    } else if (sub.status === "EXPIRED" || sub.status === "CANCELLED") {
      main.prepend(subscriptionEndedBanner());
    }
  } catch { /* the banner is optional */ }
}
