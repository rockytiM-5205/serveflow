/* What the app shows when the backend says a restaurant's ServeFlow subscription has ended
 * (HTTP 402, code "subscription_inactive"). The backend decides; this only explains it. */
import { ApiError } from "./api.js";
import { el, emptyState, icon } from "./ui.js";

export const SUBSCRIPTION_ENDED_EVENT = "serveflow:subscription-ended";

export const isSubscriptionEnded = (err) => err instanceof ApiError && err.status === 402 && err.code === "subscription_inactive";

/** For diners: no blame, no billing talk, and a way forward. */
export const orderingPausedState = () => emptyState({
  iconName: "store",
  title: "Ordering is paused",
  text: "This restaurant isn't taking orders online right now. Please ask the restaurant directly.",
});

/** For restaurant staff: a banner at the top of every dashboard page. */
export function subscriptionEndedBanner() {
  return el("div", { class: "alert alert--warning", id: "subscription-ended", role: "status" },
    icon("alert"),
    el("div", {},
      el("strong", {}, "Your ServeFlow subscription has ended."),
      el("p", {}, "You can still view your orders, menu and settings, but changes are switched off and customers can't order until it's renewed. Open Billing to pay and renew.", " ", el("a", { href: "billing.html" }, "Go to Billing"))));
}
