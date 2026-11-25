/* Settings card: where customers pay, and the pickup fee. Customers pay BEFORE an order is prepared, so a restaurant can't
 * take orders until the bank details are filled in. Only the owner edits the bank details. */
import { ApiError, api } from "../../shared/js/api.js";
import { el, emptyState, formatMoney, icon, toast } from "../../shared/js/ui.js";
import { lateFeeText } from "../../shared/js/late-policy.js";
import { formDialog } from "./form-dialog.js";

export function paymentCard({ slug, data, url, canEditFee, isOwner, reload, onError }) {
  const accountUrl = `/restaurants/${encodeURIComponent(slug)}/payment-account/`;
  const box = el("section", { class: "card card__pad stack", "aria-labelledby": "payments-h" });
  let account = null;

  function draw() {
    const ready = account?.ready;
    box.replaceChildren(...[
      el("div", { class: "section-head", style: "margin:0" },
        el("h2", { id: "payments-h" }, "Payments"),
        el("div", { class: "row" },
          isOwner ? el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: editAccount }, ready ? "Edit bank details" : "Add bank details") : null,
          canEditFee ? el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: editFee }, "Pickup fee") : null,
          canEditFee ? el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: editLate }, "Late pickup policy") : null)),
      el("p", { class: ready ? "muted" : "alert alert--warning", role: ready ? undefined : "status" }, ready
        ? "Customers see these details after they order and pay before you prepare anything. You confirm each payment on the Orders page."
        : "Add your bank details before you take orders. Customers pay into this account before you prepare their order."),
      el("dl", { class: "details" },
        el("dt", {}, "Bank"), el("dd", {}, account?.bank_name || "Not set"),
        el("dt", {}, "Account name"), el("dd", {}, account?.account_name || "Not set"),
        el("dt", {}, "Account number"), el("dd", {}, account?.account_number || "Not set"),
        el("dt", {}, "Note to customers"), el("dd", {}, account?.instructions || "None"),
        el("dt", {}, "Late pickup"), el("dd", {}, data.late_fee_enabled ? lateFeeText({ grace_minutes: data.late_grace_minutes, fee_amount: data.late_fee_amount, interval_minutes: data.late_fee_interval_minutes, max_fee: data.late_fee_max }, (v) => formatMoney(v, data.currency)) : "No late fee"),
        el("dt", {}, "Pickup fee"), el("dd", {}, Number(data.pickup_fee) > 0 ? `${formatMoney(data.pickup_fee, data.currency)} added to each pickup order` : "No fee")),
      isOwner ? null : el("p", { class: "muted" }, "Only the owner can change the bank details."),
    ].filter(Boolean)); // a native replaceChildren turns null into the word "null"
  }

  async function editAccount() {
    const saved = await formDialog({
      title: "Bank details for customer payments",
      description: "Customers transfer the exact amount here before you start preparing. Double-check the account number.",
      fields: [
        { name: "bank_name", label: "Bank", type: "text", required: true, maxlength: 80 },
        { name: "account_name", label: "Account name", type: "text", required: true, maxlength: 120 },
        { name: "account_number", label: "Account number", type: "text", required: true, maxlength: 34, inputmode: "text" },
        { name: "instructions", label: "Note to customers (optional)", type: "textarea", maxlength: 300, hint: "For example: put your order reference in the narration." },
      ],
      values: account ?? {},
      submit: (v) => api.put(accountUrl, v),
    });
    if (saved) {
      account = saved;
      toast("Bank details saved.", { type: "success" });
      draw();
    }
  }

  async function editFee() {
    const saved = await formDialog({
      title: "Pickup fee",
      description: `A small extra charge added to every pickup order, in ${data.currency}. Customers see it before they order. Use 0 for no fee.`,
      fields: [{
        name: "pickup_fee", label: "Fee per pickup order", type: "text", inputmode: "decimal", required: true,
        validate: (v) => (/^\d{1,6}(\.\d{1,2})?$/.test(String(v).trim()) ? null : "Enter an amount like 150 or 150.50."),
      }],
      values: { pickup_fee: data.pickup_fee ?? "0.00" },
      submit: (v) => api.patch(url, { pickup_fee: String(v.pickup_fee).trim() }),
    });
    if (saved) {
      toast("Pickup fee saved.", { type: "success" });
      await reload();
    }
  }

  async function editLate() {
    const money = (name, label, hint) => ({ name, label, type: "text", inputmode: "decimal", hint, validate: (v) => (/^\d{1,6}(\.\d{1,2})?$/.test(String(v).trim()) ? null : "Enter an amount like 100 or 100.50.") });
    const minutes = (name, label, min, hint) => ({ name, label, type: "text", inputmode: "numeric", hint, validate: (v) => (/^\d{1,3}$/.test(String(v).trim()) && Number(v) >= min && Number(v) <= 240 ? null : `Enter ${min} to 240 minutes.`) });
    const saved = await formDialog({
      title: "Late pickup policy",
      description: "Charge customers who collect late. Customers see these rules and must accept them before they order for pickup, and they can't change after an order is placed. The clock only starts when you mark an order ready, so customers are never charged for your own delay.",
      fields: [
        { name: "late_fee_enabled", label: "Charge a late pickup fee", type: "checkbox" },
        minutes("late_grace_minutes", "Free minutes after the order is ready", 0, "Counted from when you mark it ready, or from the customer's chosen time if that is later."),
        money("late_fee_amount", `Fee per interval (${data.currency})`, "Charged for every full or part interval after the free period."),
        minutes("late_fee_interval_minutes", "Interval (minutes)", 5, "For example 15: a fee for each 15 minutes late."),
        money("late_fee_max", `Most one order can be charged (${data.currency})`, "A cap, so a long delay never costs more than this."),
      ],
      values: {
        late_fee_enabled: data.late_fee_enabled, late_grace_minutes: String(data.late_grace_minutes ?? 15), late_fee_amount: String(data.late_fee_amount ?? "0.00"),
        late_fee_interval_minutes: String(data.late_fee_interval_minutes ?? 15), late_fee_max: String(data.late_fee_max ?? "0.00"),
      },
      validateForm: (v) => (v.late_fee_enabled && (Number(v.late_fee_amount) <= 0 ? { late_fee_amount: "Set a fee above zero, or switch the policy off." } : Number(v.late_fee_max) < Number(v.late_fee_amount) ? { late_fee_max: "The cap can't be less than one fee." } : {})) || {},
      submit: (v) => api.patch(url, {
        late_fee_enabled: v.late_fee_enabled, late_grace_minutes: Number(v.late_grace_minutes), late_fee_amount: String(v.late_fee_amount).trim(),
        late_fee_interval_minutes: Number(v.late_fee_interval_minutes), late_fee_max: String(v.late_fee_max).trim(),
      }),
    });
    if (saved) {
      toast("Late pickup policy saved.", { type: "success" });
      await reload();
    }
  }

  async function load() {
    box.replaceChildren(el("div", { class: "skeleton skeleton--line", style: "width:50%;height:1.25rem", "aria-hidden": "true" }));
    try {
      account = await api.get(accountUrl);
      draw();
    } catch (err) {
      if (onError?.(err)) return;
      box.replaceChildren(emptyState({
        iconName: "alert", title: "Couldn't load payment details", text: err instanceof ApiError ? err.message : "Something went wrong.",
        action: el("button", { class: "btn btn--secondary", type: "button", onclick: load }, icon("refresh"), "Try again"),
      }));
    }
  }

  load();
  return box;
}
