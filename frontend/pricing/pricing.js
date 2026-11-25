/* Public pricing page: only what the backend publishes. No plan, price or payment detail is written in this file. */
import { ApiError, api } from "../shared/js/api.js";
import { el, emptyState, formatMoney, icon } from "../shared/js/ui.js";
import { planFacts } from "../shared/js/plan-facts.js";

export const intervalLabel = (interval) => (interval === "YEARLY" ? "year" : "month");

export function planCard(plan, { action, current = false, badge = "Your plan" } = {}) {
  const facts = planFacts(plan);
  return el("article", { class: `card plan${current ? " plan--current" : ""}` },
    el("h3", {}, plan.name, current ? el("span", { class: "badge", style: "margin-left:var(--s-2)" }, badge) : null),
    plan.description ? el("p", { class: "muted" }, plan.description) : null,
    el("p", { class: "plan__price" }, formatMoney(plan.price, plan.currency), el("small", {}, ` / ${intervalLabel(plan.interval)}`)),
    facts.length ? el("ul", { class: "plan__facts" }, ...facts.map((f) => el("li", {}, f))) : null,
    plan.features?.length ? el("ul", { class: "plan__features" }, ...plan.features.map((f) => el("li", {}, f))) : null,
    action ?? null);
}

export function paymentSteps(trialDays) {
  const trial = Number.isFinite(trialDays) && trialDays > 0 ? `Your ${trialDays}-day free trial starts straight away.` : "Your free trial starts straight away.";
  return el("ol", { class: "steps" },
    el("li", {}, `Create your account and restaurant. ${trial}`),
    el("li", {}, "Pick the plan that fits you in Billing. You can switch during the trial."),
    el("li", {}, "Before the trial ends, open Billing. It shows ServeFlow's bank details and a payment reference made for you."),
    el("li", {}, "Transfer the plan price from your bank and put that reference in the narration."),
    el("li", {}, "ServeFlow checks the transfer and confirms it. Your subscription becomes active once it's confirmed."),
    el("li", {}, "If the trial ends before you pay, your restaurant stops taking orders until the payment is confirmed."));
}

async function main() {
  const plansBox = document.getElementById("plans");
  const how = document.getElementById("how");
  try {
    const data = await api.get("/billing/plans/");
    if (!data.plans.length) {
      plansBox.replaceChildren(emptyState({ iconName: "list", title: "Pricing hasn't been published yet", text: "Plans will appear here as soon as they're ready. Check back soon." }));
    } else {
      const start = (plan) => el("a", { class: "btn btn--primary", href: "../restaurant-dashboard/signup.html" }, `Get started with ${plan.name}`);
      plansBox.replaceChildren(el("div", { class: "plan-grid" }, ...data.plans.map((plan) => planCard(plan, { action: start(plan) }))));
    }
    how.replaceChildren(paymentSteps(data.trial_days), el("p", { class: "muted" },
      data.payment.ready ? "Payments are made by bank transfer. You'll see the account details after you sign in." : "Bank transfer details will be shared in your dashboard once ServeFlow has published them.",
      data.payment.instructions ? ` ${data.payment.instructions}` : ""));
  } catch (err) {
    plansBox.replaceChildren(emptyState({
      iconName: "alert", title: "Couldn't load the plans", text: err instanceof ApiError ? err.message : "Something went wrong.",
      action: el("button", { class: "btn btn--secondary", type: "button", onclick: () => location.reload() }, icon("refresh"), "Try again"),
    }));
  }
}

if (typeof document !== "undefined" && document.getElementById("plans")) main();
