/* Billing for the restaurant owner: choose a plan, see where to pay and the payment reference, follow the status.
 * The server decides everything (status, amounts, what counts as paid); this page only asks and shows. */
import { ApiError, api } from "../../shared/js/api.js";
import { el, emptyState, formatMoney, icon, setBusy, toast } from "../../shared/js/ui.js";
import { planCard } from "../../pricing/pricing.js";
import { bootDashboard, handleSessionExpiry } from "./shell.js";

const HREF = "billing.html";
const content = document.getElementById("content");
const STATUS_TEXT = {
  TRIAL: "Free trial", ACTIVE: "Active", PAST_DUE: "Payment overdue (grace period)", EXPIRED: "Expired", CANCELLED: "Cancelled",
};
const when = (v) => (v ? new Date(v).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—");

async function main() {
  const ctx = await bootDashboard({ href: HREF, minRole: "OWNER" });
  if (!ctx) return;
  if (!ctx.allowed) {
    content.replaceChildren(emptyState({ iconName: "lock", title: "Only the owner can manage billing", text: "Ask the restaurant owner to open this page." }));
    return;
  }
  const base = `/restaurants/${encodeURIComponent(ctx.restaurant.slug)}/billing/`;
  const failure = (err) => {
    if (handleSessionExpiry(err, HREF)) return;
    toast(err instanceof ApiError ? err.message : "Something went wrong.", { type: "error" });
  };

  async function act(button, run, message) {
    setBusy(button, true);
    try {
      await run();
      try { sessionStorage.removeItem("serveflow:plan"); } catch { /* ignore */ }
      if (message) toast(message, { type: "success" });
      await load();
    } catch (err) {
      failure(err);
      setBusy(button, false);
    }
  }

  function render(data) {
    const sub = data.subscription;
    const onFree = !!sub?.plan?.is_trial;
    const toPay = sub?.plan_to_pay;
    const nodes = [];
    if (sub) {
      nodes.push(el("section", { class: "card card__pad stack" },
        el("h2", {}, "Your subscription"),
        el("p", {}, el("strong", {}, sub.plan.name), " · ", STATUS_TEXT[sub.status] ?? sub.status),
        el("p", { class: "muted" }, sub.status === "TRIAL"
          ? `Your free trial ends ${when(sub.trial_ends_at)}. When it ends, your restaurant stops taking orders until you pay.`
          : `Current period ends ${when(sub.current_period_end)}.`),
        onFree ? el("p", {}, toPay ? `Plan you'll pay for: ` : "You haven't chosen a plan to pay for yet. ", toPay ? el("strong", {}, `${toPay.name} (${formatMoney(toPay.price, toPay.currency)} per ${toPay.interval === "YEARLY" ? "year" : "month"})`) : "Pick one below.") : null,
        ["EXPIRED", "CANCELLED"].includes(sub.status)
          ? el("p", { class: "alert alert--warning" }, "Your subscription has ended, so customers can't order and changes are off. Pay below to switch it back on.") : null));
    }
    const picked = (() => { try { return Number(sessionStorage.getItem("serveflow:plan")); } catch { return 0; } })();
    const pickedPlan = (!sub || (sub.status === "TRIAL" && sub.next_plan?.id !== picked)) && data.plans.find((p) => p.id === picked);
    if (pickedPlan) nodes.unshift(el("p", { class: "alert" }, sub ? `You picked ${pickedPlan.name} on the pricing page. Choose it below.` : `You picked ${pickedPlan.name} on the pricing page. Start your free trial and choose it below.`));
    const canSwitch = true; // a restaurant can ask to change plan at any time; the server decides when it takes effect
    const paying = sub && !onFree && ["ACTIVE", "PAST_DUE"].includes(sub.status);
    const pending = data.pending_plan_change;
    if (data.plans.length === 0) {
      nodes.push(emptyState({ iconName: "list", title: "No paid plans are available yet", text: "ServeFlow hasn't published its plans. Check back soon." }));
    } else {
      nodes.push(el("section", { class: "stack" }, el("h2", {}, sub ? "Choose the plan to pay for" : "Choose a plan"),
        sub ? null : el("p", { class: "muted" }, "Your free trial starts now. You pay for the plan you choose when the trial ends, by bank transfer."),
        el("div", { class: "plan-grid" }, ...data.plans.map((plan) => {
          const waiting = pending?.to_plan?.id === plan.id;
          const isPick = sub && (sub.next_plan?.id === plan.id || (!onFree && sub.plan.id === plan.id && !pending) || (paying && sub.plan.id === plan.id));
          let action = null;
          if (waiting) {
            action = el("p", { class: "muted" }, pending.kind === "UPGRADE" ? "Upgrade waiting for your payment." : `Starts ${when(pending.effective_at)}.`);
          } else if (!isPick && canSwitch) {
            const how = paying ? switchHow(sub, plan) : null;
            const label = !sub ? `Start free trial, choose ${plan.name}` : how?.label ?? `Choose ${plan.name}`;
            const button = el("button", { class: "btn btn--primary", type: "button" }, label);
            button.addEventListener("click", () => act(button, () => api.post(`${base}subscribe/`, { plan_id: plan.id }), how?.done ?? "Plan chosen."));
            action = el("div", { class: "stack" }, button, how ? el("p", { class: "muted" }, how.note) : null);
          } else if (isPick && paying && sub.plan.id === plan.id && pending) {
            const keep = el("button", { class: "btn btn--secondary", type: "button" }, "Stay on this plan");
            keep.addEventListener("click", () => act(keep, () => api.post(`${base}subscribe/`, { plan_id: plan.id }), "Change cancelled."));
            action = keep;
          }
          return planCard(plan, { current: !!isPick, badge: onFree ? "Your pick" : "Your plan", action });
        }))));
    }
    if (paying) nodes.splice(1, 0, ...usageSection(data, sub));
    if (sub) nodes.push(paySection(data));
    if (data.payments.length) nodes.push(history(data.payments));
    content.replaceChildren(...nodes);
  }

  /** What picking `plan` will do, for the button. The server makes the real decision. */
  function switchHow(sub, plan) {
    const same = plan.interval === sub.plan.interval && plan.currency === sub.plan.currency;
    if (same && Number(plan.price) > Number(sub.plan.price)) {
      const diff = formatMoney(String((Number(plan.price) - Number(sub.plan.price)).toFixed(2)), plan.currency);
      return { label: `Upgrade to ${plan.name}`, note: `Pay the ${diff} difference and it starts now.`, done: "Upgrade started. Pay below to switch on." };
    }
    return { label: `Switch to ${plan.name}`, note: `Takes effect on ${when(sub.current_period_end)}, when your current period ends.`, done: `Done. You'll move to ${plan.name} on ${when(sub.current_period_end)}.` };
  }

  const bankBox = (payment, details, title) => el("div", { class: "card pay-box" },
    el("p", {}, el("strong", {}, title)),
    el("p", { class: "muted" }, "Transfer the amount below and put the reference in the narration. It starts once ServeFlow confirms it."),
    detailList([["Amount", formatMoney(payment.amount, payment.currency)], ["Bank", details.bank_name], ...(details.account_name ? [["Account name", details.account_name]] : []), ["Account number", details.account_number], ["Reference", payment.reference]]),
    copyButton(payment.reference));

  /** Orders used this period, warnings, order packs, and a change that is waiting. */
  function usageSection(data, sub) {
    const out = [];
    const u = data.usage;
    if (u) {
      const warn = { 100: ["alert--danger", "You've reached your order limit. New orders are paused until you upgrade or buy more orders."],
        90: ["alert--warning", "You've used 90% of your orders this period."], 75: ["alert--warning", "You've used 75% of your orders this period."] }[u.warning_level];
      const bar = el("div", { class: "meter", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(u.percent_used), "aria-label": "Orders used" },
        el("span", { style: `width:${u.percent_used}%` }));
      out.push(el("section", { class: "card card__pad stack", "aria-labelledby": "usage-h" },
        el("h2", { id: "usage-h" }, "Orders this period"),
        el("p", {}, el("strong", {}, `${u.completed_orders} of ${u.included_orders + u.extra_capacity}`), ` completed orders used · ${u.remaining} left`),
        bar,
        el("p", { class: "muted" }, `${u.plan_name}: ${u.included_orders} included${u.extra_capacity ? ` + ${u.extra_capacity} from order packs` : ""}. Resets on ${when(u.period_end)}. Only completed orders count.`),
        warn ? el("p", { class: `alert ${warn[0]}`, role: "status" }, warn[1]) : null));
    }
    if (data.pack_offer) {
      const offer = data.pack_offer;
      const button = el("button", { class: "btn btn--secondary", type: "button" }, `Buy ${offer.orders} more orders for ${formatMoney(offer.price, offer.currency)}`);
      button.addEventListener("click", () => act(button, () => api.post(`${base}order-packs/`), "Order pack started. Pay below to switch it on."));
      out.push(el("section", { class: "card card__pad stack" }, el("h2", {}, "Need more orders?"),
        el("p", { class: "muted" }, `An order pack adds ${offer.orders} completed orders until ${when(offer.expires_at)}. Unused orders don't carry over.`), button));
    }
    if (pendingExtras(data).length && data.payment_details) {
      out.push(el("section", { class: "stack" }, ...pendingExtras(data).map((p) => bankBox(p, data.payment_details, p.kind === "ORDER_PACK" ? "Order pack: waiting for your transfer" : "Upgrade: waiting for your transfer"))));
    }
    if (data.pending_plan_change && data.pending_plan_change.kind === "DOWNGRADE") {
      const c = data.pending_plan_change;
      const cancel = el("button", { class: "btn btn--secondary btn--sm", type: "button" }, "Cancel this change");
      cancel.addEventListener("click", () => act(cancel, () => api.post(`${base}plan-change/cancel/`), "Change cancelled."));
      out.push(el("p", { class: "alert", role: "status" }, `You'll move to ${c.to_plan.name} on ${when(c.effective_at)}. `, cancel));
    }
    return out;
  }
  const pendingExtras = (data) => data.open_extra_payments ?? [];

  function paySection(data) {
    const sub = data.subscription;
    const toPay = sub.plan_to_pay;
    const section = el("section", { class: "stack" }, el("h2", {}, "Paying"));
    if (!data.payment_details) {
      section.append(el("p", { class: "alert alert--warning" }, "ServeFlow hasn't published its bank details yet, so you can't pay right now. Please check back soon."));
      return section;
    }
    const open = data.open_payment;
    if (open) {
      section.append(el("div", { class: "card pay-box" },
        el("p", {}, el("strong", {}, "Waiting for ServeFlow to confirm your transfer.")),
        el("p", { class: "muted" }, "Transfer the amount below and put the reference in the narration. Your subscription turns active once ServeFlow confirms it."),
        detailList([["Amount", formatMoney(open.amount, open.currency)], ["Bank", data.payment_details.bank_name], ...(data.payment_details.account_name ? [["Account name", data.payment_details.account_name]] : []), ["Account number", data.payment_details.account_number], ["Reference", open.reference]]),
        copyButton(open.reference),
        data.payment_details.instructions ? el("p", { class: "muted" }, data.payment_details.instructions) : null));
    } else if (!toPay) {
      section.append(el("p", { class: "muted" }, "Choose the plan you want to pay for above, then come back here for the bank details."));
    } else if (sub.status !== "CANCELLED") {
      const button = el("button", { class: "btn btn--primary", type: "button" }, `Get payment details for ${toPay.name}`);
      button.addEventListener("click", () => act(button, () => api.post(`${base}payments/`), null));
      section.append(el("p", { class: "muted" }, `${toPay.name}: ${formatMoney(toPay.price, toPay.currency)} per ${toPay.interval === "YEARLY" ? "year" : "month"}. Pay before your trial ends to keep taking orders without a break.`), button);
    }
    return section;
  }

  const detailList = (pairs) => el("dl", {}, ...pairs.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
  const copyButton = (text) => el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
    try { await navigator.clipboard.writeText(text); toast("Reference copied.", { type: "success" }); } catch { toast("Select the reference and copy it.", { type: "info" }); }
  } }, "Copy reference");
  const history = (payments) => el("section", { class: "stack" }, el("h2", {}, "Payment history"),
    el("div", { class: "card table-wrap" }, el("table", { class: "table" }, el("caption", { class: "sr-only" }, "Payment history"),
      el("thead", {}, el("tr", {}, ...["Reference", "For", "Amount", "Status", "Reported"].map((h) => el("th", { scope: "col" }, h)))),
      el("tbody", {}, ...payments.map((p) => el("tr", {}, el("td", {}, el("code", {}, p.reference)), el("td", {}, { SUBSCRIPTION: "Subscription", ORDER_PACK: "Order pack", UPGRADE: "Upgrade" }[p.kind] ?? p.kind), el("td", {}, formatMoney(p.amount, p.currency)),
        el("td", {}, { AWAITING_CONFIRMATION: "Awaiting confirmation", CONFIRMED: "Confirmed", FAILED: "Failed" }[p.status] ?? p.status), el("td", {}, when(p.created_at))))))));

  async function load() {
    content.replaceChildren(el("div", { class: "card card__pad stack", "aria-hidden": "true" }, ...[60, 85, 70].map((w) => el("div", { class: "skeleton skeleton--line", style: `width:${w}%;height:1.25rem` }))));
    try {
      render(await api.get(base));
    } catch (err) {
      if (handleSessionExpiry(err, HREF)) return;
      content.replaceChildren(emptyState({
        iconName: "alert", title: "Couldn't load billing", text: err instanceof ApiError ? err.message : "Something went wrong.",
        action: el("button", { class: "btn btn--secondary", type: "button", onclick: load }, icon("refresh"), "Try again"),
      }));
    }
  }
  load();
}

main();
