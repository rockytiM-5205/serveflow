/* Landing pricing section: shows whatever plans ServeFlow publishes. No plan or price is written in this page. */
import { api } from "../shared/js/api.js";
import { el, formatMoney } from "../shared/js/ui.js";
import { planFacts } from "../shared/js/plan-facts.js";
import { revealAll } from "./landing.js";

const box = document.getElementById("plans");
const per = (interval) => (interval === "YEARLY" ? "year" : "month");
export const PICKED_PLAN_KEY = "serveflow:plan";

function card(plan) {
  const facts = [...planFacts(plan), ...(plan.features ?? [])];
  const choose = el("a", { class: "btn-dark", href: `restaurant-dashboard/signup.html?plan=${encodeURIComponent(plan.id)}` }, `Choose ${plan.name}`);
  choose.addEventListener("click", () => { try { sessionStorage.setItem(PICKED_PLAN_KEY, String(plan.id)); } catch { /* storage blocked: the link still works */ } });
  return el("article", { class: "plan-card" },
    el("h3", {}, plan.name),
    plan.description ? el("p", { class: "plan-card__desc" }, plan.description) : null,
    el("p", { class: "plan-card__price" }, formatMoney(plan.price, plan.currency), el("small", {}, ` / ${per(plan.interval)}`)),
    facts.length ? el("ul", {}, ...facts.map((f) => el("li", {}, f))) : null,
    choose);
}

async function main() {
  try {
    const data = await api.get("/billing/plans/");
    if (Number.isFinite(data.trial_days) && data.trial_days > 0) {
      document.getElementById("pricing-note").textContent = `Your ${data.trial_days}-day free trial starts when you create your restaurant and ends by itself. Pay by bank transfer before then to keep taking orders. No card needed.`;
    }
    if (!data.plans.length) {
      box.replaceChildren(el("p", { class: "plans__status" }, "Pricing is being finalised. You can already "),
        el("a", { class: "btn-dark", href: "restaurant-dashboard/signup.html" }, "create your account"));
      return;
    }
    box.replaceChildren(...data.plans.map(card));
    revealAll();
  } catch {
    box.replaceChildren(el("p", { class: "plans__status" }, "We couldn't load the plans just now. Please refresh, or "),
      el("a", { class: "btn-dark", href: "restaurant-dashboard/signup.html" }, "create your account"));
  }
}

if (box) main();
