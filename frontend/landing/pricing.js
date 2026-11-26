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

const skeleton = () => [1, 2].map(() => el("div", { class: "plan-card plan-card--skeleton", "aria-hidden": "true" }, el("i"), el("i"), el("i"), el("i")));
const signup = (label) => el("a", { class: "btn-dark", href: "restaurant-dashboard/signup.html" }, label);

/* A calm message in place of the plans: used when nothing is published yet and when the plans can't be loaded. */
function stateBox({ title, text, actions, alert = false }) {
  return el("div", { class: `plans__state${alert ? " plans__state--error" : ""}`, role: alert ? "alert" : "status" },
    el("h3", {}, title), el("p", {}, text), el("div", { class: "plans__actions" }, ...actions));
}

async function main() {
  box.setAttribute("aria-busy", "true");
  box.replaceChildren(...skeleton(), el("p", { class: "sr-only" }, "Loading plans…"));
  try {
    const data = await api.get("/billing/plans/");
    if (Number.isFinite(data.trial_days) && data.trial_days > 0) {
      document.getElementById("pricing-note").textContent = `Your ${data.trial_days}-day free trial starts when you create your restaurant and ends by itself. Pay by bank transfer before then to keep taking orders. No card needed.`;
    }
    if (!data.plans.length) {
      box.replaceChildren(stateBox({
        title: "Plans are being finalised",
        text: "Prices aren't published yet. You can already create your account and set up your restaurant.",
        actions: [signup("Create your account")],
      }));
      return;
    }
    box.replaceChildren(...data.plans.map(card));
    revealAll();
  } catch {
    const retry = el("button", { class: "btn-outline btn-outline--dark", type: "button" }, "Try again");
    retry.addEventListener("click", main);
    box.replaceChildren(stateBox({
      title: "We couldn't load the plans",
      text: "Check your connection and try again. You can also create your account now and choose a plan afterwards.",
      actions: [retry, signup("Create your account")],
      alert: true,
    }));
  } finally {
    box.setAttribute("aria-busy", "false");
  }
}

if (box) main();
