import { ApiError, api } from "../../shared/js/api.js";
import { closeOnBackdrop, confirmDialog, el, emptyState, formatMoney, icon, setBusy, toast } from "../../shared/js/ui.js";
import { formDialog } from "./form-dialog.js";
import { attachBadge, defaultShouldSkip, liveBadge, startLive } from "../../shared/js/live.js";
import { ROLE_LABEL, hasRole } from "./session.js";
import { bootDashboard, handleSessionExpiry } from "./shell.js";
import { formatClock, formatDateTime, timeAgo } from "./time.js";

const HREF = "orders.html";
const POLL_MS = 15000;
const FILTERS = [
  { id: "queue", label: "Needs attention", params: { queue: "1" }, empty: "Nothing needs attention right now." },
  { id: "payments", label: "Payments to check", params: { payment_status: "CLAIMED", status: "PENDING,CONFIRMED,SERVING,READY_FOR_PICKUP" }, empty: "No customer has said they've paid and is waiting for you to check." },
  { id: "pending", label: "Pending", params: { status: "PENDING" }, empty: "No orders are waiting for confirmation." },
  { id: "progress", label: "In progress", params: { status: "CONFIRMED,SERVING,READY_FOR_PICKUP" }, empty: "No orders are being prepared." },
  { id: "finished", label: "Finished", params: { status: "COMPLETED,REJECTED,CANCELLED" }, empty: "No finished orders yet." },
  { id: "all", label: "All", params: {}, empty: "No orders yet." },
];
const STATUS_LABEL = { PENDING: "Pending", CONFIRMED: "Confirmed", SERVING: "Preparing", READY_FOR_PICKUP: "Ready", COMPLETED: "Completed", REJECTED: "Rejected", CANCELLED: "Cancelled" };
const PAYMENT_LABEL = { UNPAID: "Unpaid", CLAIMED: "Customer says paid", PAID: "Paid" };
const ACTOR_LABEL = { CUSTOMER: "Customer", STAFF: "Staff", MANAGER: "Manager", OWNER: "Owner", SYSTEM: "System" };

const content = document.getElementById("content");
const SOUND_STORAGE_KEY = "serveflow.sound";
const soundWanted = () => {
  try { return localStorage.getItem(SOUND_STORAGE_KEY) === "on"; } catch { return false; }
};
let audio = null;
/** Two short beeps. The audio context is created from a click, which browsers require. */
function chime() {
  if (!audio) return;
  [0, 0.22].forEach((offset) => {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0001, audio.currentTime + offset);
    gain.gain.exponentialRampToValueAtTime(0.25, audio.currentTime + offset + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + offset + 0.18);
    osc.connect(gain).connect(audio.destination);
    osc.start(audio.currentTime + offset);
    osc.stop(audio.currentTime + offset + 0.2);
  });
}
const newKey = () => crypto.randomUUID().replaceAll("-", "");

async function main() {
  const ctx = await bootDashboard({ href: HREF });
  if (!ctx) return;
  const isManager = hasRole(ctx.role, "MANAGER");
  const base = `/restaurants/${encodeURIComponent(ctx.restaurant.slug)}`;
  let info = { currency: "USD", timezone: "UTC" };
  let filter = FILTERS[0];
  let search = ""; // an order reference, name or last digits of a phone number
  let orders = [];
  let nextQuery = null;
  let known = null; // ids seen so far, to spot new orders
  let loadedMore = false; // "Load more" pages are not live: refreshing would collapse them
  let selected = new Set(); // orders ticked on the "Payments to check" screen; kept across the live refresh
  const canConfirm = (o) => o.payment_status !== "PAID" && !["REJECTED", "CANCELLED"].includes(o.status);
  const actionable = (o) => !["COMPLETED", "REJECTED", "CANCELLED"].includes(o.status);

  const failure = (err) => {
    if (handleSessionExpiry(err, HREF)) return;
    if (err instanceof ApiError && err.code === "stale_status") {
      toast("Someone else just updated this order. Showing the latest.", { type: "info" });
      refresh();
      return;
    }
    toast(err instanceof ApiError ? err.message : "Something went wrong.", { type: "error" });
  };

  const query = (extra = {}) => `?${new URLSearchParams({ ...filter.params, ...(search ? { search } : {}), ...extra })}`;
  const pickupLine = (order) => (order.pickup_at ? `Collect ${formatDateTime(order.pickup_at, info.timezone)}` : "");

  /** Fetch and draw the newest orders. Throws on failure. `announce` flags new ones (toast, and a chime if switched on). */
  async function load({ announce = false } = {}) {
    const page = await api.get(`${base}/orders/${query({ page_size: 100 })}`);
    const fresh = page.results.filter((o) => known && !known.has(o.public_id) && (o.status === "PENDING" || (o.status === "CONFIRMED" && o.payment_status !== "PAID")));
    known = new Set([...(known ?? []), ...page.results.map((o) => o.public_id)]);
    orders = page.results;
    loadedMore = false;
    nextQuery = page.next ? new URL(page.next, location.href).search : null;
    render(new Set(fresh.map((o) => o.public_id)));
    if (announce && fresh.length) {
      toast(fresh.length === 1 ? `New order ${fresh[0].reference}` : `${fresh.length} new orders`, { type: "success" });
      if (soundWanted()) chime();
    }
  }

  /** After an action or a filter change: refresh now and report any error. */
  async function refresh() {
    try {
      await load();
    } catch (err) {
      failure(err);
    }
  }

  async function run(button, work) {
    setBusy(button, true);
    try {
      await work();
    } catch (err) {
      failure(err);
    } finally {
      if (button.isConnected) setBusy(button, false);
    }
  }

  const transition = (order, to_status, reason = "") =>
    api.post(`${base}/orders/${order.public_id}/transitions/`, { to_status, reason, expected_status: order.status });

  async function advance(order, to_status, message) {
    await transition(order, to_status);
    toast(message, { type: "success" });
    await refresh();
  }

  async function withReason(order, { title, description, label, submitLabel, request, done }) {
    const saved = await formDialog({
      title, description, submitLabel,
      fields: [{ name: "reason", label, type: "textarea", required: true, maxlength: 255 }],
      submit: (v) => request(v.reason),
    });
    if (saved) {
      toast(done, { type: "success" });
      await refresh();
    }
  }

  const reject = (order) => withReason(order, {
    title: `Reject order ${order.reference}`, description: "The customer will see that the restaurant couldn't take this order.",
    label: "Reason", submitLabel: "Reject order", done: "Order rejected.",
    request: (reason) => transition(order, "REJECTED", reason),
  });

  const cancel = (order) => withReason(order, {
    title: `Cancel order ${order.reference}`,
    description: order.payment_status === "PAID" ? "This order was already paid. Cancelling it means you must refund the customer." : ["SERVING", "READY_FOR_PICKUP"].includes(order.status) ? "This order is already being prepared. Cancelling it can't be undone." : "Cancelling can't be undone.",
    label: "Reason", submitLabel: "Cancel order", done: "Order cancelled.",
    request: (reason) => api.post(`${base}/orders/${order.public_id}/cancel/`, {
      reason, expected_status: order.status, acknowledge_serving: ["SERVING", "READY_FOR_PICKUP"].includes(order.status),
    }),
  });

  async function settleLateFee(order, action, reason = "") {
    await api.post(`${base}/orders/${order.public_id}/late-fee/`, { action, reason });
    toast(action === "paid" ? "Late fee marked as collected." : "Late fee waived.", { type: "success" });
    await refresh();
  }

  async function waiveLateFee(order) {
    const saved = await formDialog({
      title: `Waive the late fee for ${order.reference}`,
      description: `The ${formatMoney(order.late_fee, order.currency)} fee won't be charged. The reason and your name are kept in the audit log.`,
      submitLabel: "Waive fee",
      fields: [{ name: "reason", label: "Reason", type: "text", required: true, maxlength: 200 }],
      values: {},
      submit: (v) => api.post(`${base}/orders/${order.public_id}/late-fee/`, { action: "waive", reason: v.reason.trim() }),
    });
    if (saved) { toast("Late fee waived.", { type: "success" }); await refresh(); }
  }

  async function recordPayment(order) {
    const key = newKey(); // reused if the staff member retries from this dialog, so it can't be recorded twice
    const saved = await formDialog({
      title: `Confirm payment for ${order.reference}`,
      description: `Check your bank account for ${formatMoney(order.total, order.currency)} with the reference ${order.reference}. Only confirm when the money has arrived: preparing can't start until you do.`,
      submitLabel: "Payment received",
      fields: [
        { name: "method", label: "Paid by", type: "select", required: true, options: [{ value: "TRANSFER", label: "Bank transfer" }, { value: "CASH", label: "Cash" }] },
        { name: "reference", label: "Bank reference (optional)", type: "text", maxlength: 100, hint: "For example the transfer's own reference." },
      ],
      values: { method: "TRANSFER" },
      submit: (v) => api.post(`${base}/orders/${order.public_id}/payment/`,
        { method: v.method, amount: order.total, reference: v.reference }, { headers: { "Idempotency-Key": key } }),
    });
    if (saved) {
      toast("Payment confirmed. You can start preparing.", { type: "success" });
      await refresh();
    }
  }

  /** Send ids to the server 50 at a time (its limit) and add up the answers. */
  async function inBatches(path, ids, extra, headersFor) {
    const result = { done: [], skipped: [] };
    for (let i = 0; i < ids.length; i += 50) {
      const part = await api.post(`${base}/orders/${path}/`, { orders: ids.slice(i, i + 50), ...extra }, headersFor ? { headers: headersFor() } : undefined);
      result.done.push(...(part.confirmed ?? part.moved));
      result.skipped.push(...part.skipped);
    }
    return result;
  }

  const SKIP_WORDS = {
    payment_required: "still need their payment confirmed", already_paid: "were already paid", already_there: "were already at that step",
    not_payable: "were rejected or cancelled", invalid_transition: "can't move that way", not_found: "weren't found",
  };
  function reportBatch(result, verb) {
    const n = result.done.length;
    toast(n ? `${n} order${n === 1 ? "" : "s"} ${verb}.` : "Nothing changed.", { type: n ? "success" : "info" });
    const why = new Map();
    for (const s of result.skipped) why.set(s.reason, (why.get(s.reason) ?? 0) + 1);
    for (const [reason, count] of why) toast(`${count} ${SKIP_WORDS[reason] ?? "could not be changed"}.`, { type: "info" });
  }

  /** Confirm the payments of the ticked orders, optionally accepting them and starting preparing straight away. */
  async function confirmPayments(list, startPreparing) {
    const cents = list.reduce((sum, o) => sum + Math.round(Number(o.total) * 100), 0);
    const total = formatMoney((cents / 100).toFixed(2), list[0].currency);
    const many = list.length !== 1;
    const sure = await confirmDialog({
      title: `Confirm ${list.length} payment${many ? "s" : ""}?`,
      message: `Only do this once ${many ? `all ${list.length} transfers (${total} in all) have` : "the transfer has"} arrived in your bank account. Each order is marked paid for its full amount${startPreparing ? " and goes straight to preparing" : " and can then be prepared"}.`,
      confirmLabel: `Payment${many ? "s" : ""} received`,
    });
    if (!sure) return;
    const result = await inBatches("payments/confirm", list.map((o) => o.public_id), { method: "TRANSFER", start_preparing: startPreparing }, () => ({ "Idempotency-Key": newKey() }));
    selected = new Set();
    reportBatch(result, startPreparing ? "paid and being prepared" : "paid");
    await refresh();
  }

  async function moveMany(list, to_status, verb) {
    const result = await inBatches("transitions", list.map((o) => o.public_id), { to_status });
    selected = new Set();
    reportBatch(result, verb);
    await refresh();
  }

  /** The bar above the list: tick orders, then do the next step for all of them at once. */
  function selectionBar() {
    const rows = orders.filter(actionable);
    selected = new Set([...selected].filter((id) => rows.some((o) => o.public_id === id)));
    const chosen = rows.filter((o) => selected.has(o.public_id));
    const early = (o) => o.status === "PENDING" || o.status === "CONFIRMED";
    const groups = [
      { list: chosen.filter(canConfirm).filter(early), label: (n) => `Paid: confirm and start preparing (${n})`, cls: "btn--primary", work: (l) => confirmPayments(l, true) },
      { list: chosen.filter(canConfirm), label: (n) => `Confirm ${n} payment${n === 1 ? "" : "s"} only`, cls: "btn--secondary", work: (l) => confirmPayments(l, false) },
      { list: chosen.filter((o) => o.status === "PENDING"), label: (n) => `Accept (${n})`, cls: "btn--secondary", work: (l) => moveMany(l, "CONFIRMED", "accepted") },
      { list: chosen.filter((o) => early(o) && o.payment_status === "PAID"), label: (n) => `Start preparing (${n})`, cls: "btn--primary", work: (l) => moveMany(l, "SERVING", "being prepared") },
      { list: chosen.filter((o) => o.status === "SERVING"), label: (n) => `Mark ready (${n})`, cls: "btn--primary", work: (l) => moveMany(l, "READY_FOR_PICKUP", "marked ready") },
      { list: chosen.filter((o) => o.status === "SERVING" || o.status === "READY_FOR_PICKUP"), label: (n) => `Complete (${n})`, cls: "btn--secondary", work: (l) => moveMany(l, "COMPLETED", "completed") },
    ].filter((g) => g.list.length);
    const all = rows.length > 0 && rows.every((o) => selected.has(o.public_id));
    const toggleAll = el("button", { class: "btn btn--secondary btn--sm", type: "button" }, all ? "Clear selection" : `Select all (${rows.length})`);
    toggleAll.addEventListener("click", () => { selected = all ? new Set() : new Set(rows.map((o) => o.public_id)); render(); });
    const buttons = groups.map((g) => {
      const b = el("button", { class: `btn ${g.cls} btn--sm`, type: "button" }, g.label(g.list.length));
      b.addEventListener("click", () => run(b, () => g.work(g.list)));
      return b;
    });
    return el("div", { class: "row selection-bar", role: "group", "aria-label": "Act on several orders at once", "data-active": String(chosen.length > 0) },
      toggleAll, ...buttons,
      chosen.length ? el("span", { class: "muted" }, `${chosen.length} selected`) : el("span", { class: "muted" }, "Tick orders to move several at once."));
  }

  async function showDetails(order) {
    const body = el("div", { class: "stack" }, el("div", { class: "skeleton skeleton--line", style: "height:1.5rem" }));
    const dialog = el("dialog", { class: "dialog", "aria-labelledby": "detail-title" },
      el("div", { class: "dialog__panel" },
        el("div", { class: "section-head", style: "margin:0" }, el("h2", { id: "detail-title" }, `Order ${order.reference}`),
          el("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "Close", onclick: () => dialog.close() }, icon("x"))),
        body));
    closeOnBackdrop(dialog);
    dialog.addEventListener("close", () => dialog.remove());
    document.body.append(dialog);
    dialog.showModal();
    try {
      const d = await api.get(`${base}/orders/${order.public_id}/`);
      const when = (iso) => formatDateTime(iso, info.timezone);
      body.replaceChildren(...[
        el("div", { class: "row" },
          el("span", { class: "badge", "data-status": d.status }, STATUS_LABEL[d.status]),
          el("span", { class: "badge", "data-status": d.payment_status }, PAYMENT_LABEL[d.payment_status] ?? d.payment_status)),
        d.refund_due ? el("p", { class: "alert alert--warning", role: "status" }, `This order was paid and then ${d.status === "REJECTED" ? "rejected" : "cancelled"}. Refund the customer ${formatMoney(d.total, d.currency)}.`) : null,
        el("dl", { class: "details" },
          el("dt", {}, "Reference"), el("dd", {}, d.reference),
          el("dt", {}, "Staff number"), el("dd", {}, `#${d.code}`),
          el("dt", {}, "Customer"), el("dd", {}, d.customer_type === "GUEST" ? `${d.customer_name} (Guest)` : d.customer_name),
          el("dt", {}, "Phone"), el("dd", {}, el("a", { href: `tel:${d.customer_phone.replace(/[^\d+]/g, "")}` }, d.customer_phone)),
          el("dt", {}, "Ordering"), el("dd", {}, d.fulfilment_type === "DINE_IN" ? `Dine in${d.table_number ? `, table ${d.table_number}` : ""}` : "Pickup"),
          d.pickup_at ? el("dt", {}, "Collect at") : null, d.pickup_at ? el("dd", {}, when(d.pickup_at)) : null,
          el("dt", {}, "Placed"), el("dd", {}, when(d.created_at)),
          d.notes ? el("dt", {}, "Notes") : null, d.notes ? el("dd", {}, d.notes) : null),
        el("ul", { class: "summary-lines" }, ...d.items.map((i) =>
          el("li", {}, el("span", {}, `${i.quantity} × ${i.item_name}`), el("span", { class: "price" }, formatMoney(i.line_total, d.currency))))),
        d.late_fee_status !== "NONE" ? el("p", { class: "muted" }, `Late fee ${formatMoney(d.late_fee, d.currency)}: ${({ DUE: "to collect", PAID: "collected", WAIVED: "waived" })[d.late_fee_status]}.`) : null,
        Number(d.pickup_fee) > 0 ? el("p", { class: "muted" }, `Includes a ${formatMoney(d.pickup_fee, d.currency)} pickup fee.`) : null,
        el("div", { class: "total-row" }, el("span", {}, "Total"), el("strong", { class: "price" }, formatMoney(d.total, d.currency))),
        el("h3", {}, "History"),
        el("ul", { class: "history" }, ...d.events.map((e) =>
          el("li", {}, el("strong", {}, STATUS_LABEL[e.to_status]), ` · ${ACTOR_LABEL[e.actor_type] ?? e.actor_type}${e.actor_email ? ` (${e.actor_email})` : ""} · ${when(e.created_at)}`,
            e.reason ? el("span", { class: "muted history__reason" }, ` “${e.reason}”`) : null))),
        d.payments.length ? el("h3", {}, "Payment") : null,
        ...d.payments.map((p) => el("p", {}, `${formatMoney(p.amount, p.currency)} by ${p.method === "CASH" ? "cash" : "bank transfer"}${p.reference ? ` (${p.reference})` : ""}, recorded by ${p.recorded_by_email}`)),
      ].filter(Boolean));
    } catch (err) {
      dialog.close();
      failure(err);
    }
  }

  function actions(order) {
    const button = (label, cls, work, iconName) =>
      el("button", { class: `btn ${cls} btn--sm`, type: "button", onclick: (e) => run(e.currentTarget, work) }, iconName ? icon(iconName) : null, label);
    const list = [];
    const paid = order.payment_status === "PAID";
    const ref = order.reference;
    const confirmPayment = (primary) => button("Confirm payment", primary ? "btn--primary" : "btn--secondary", () => recordPayment(order), "check");
    if (order.status === "PENDING") {
      if (!paid) list.push(confirmPayment(order.payment_status === "CLAIMED"));
      list.push(button("Confirm order", paid ? "btn--primary" : "btn--secondary", () => advance(order, "CONFIRMED", `Order ${ref} confirmed.`), "check"));
      list.push(button("Reject", "btn--ghost", () => reject(order)));
    } else if (order.status === "CONFIRMED") {
      // Customers pay first: nothing is prepared until the restaurant has confirmed the money arrived.
      list.push(paid
        ? button("Start preparing", "btn--primary", () => advance(order, "SERVING", `Order ${ref} is being prepared.`))
        : confirmPayment(true));
      list.push(button("Cancel", "btn--ghost", () => cancel(order)));
    } else if (order.status === "SERVING") {
      list.push(button("Mark ready", "btn--primary", () => advance(order, "READY_FOR_PICKUP", `Order ${ref} is ready.`), "check"));
      list.push(button("Complete", "btn--secondary", () => advance(order, "COMPLETED", `Order ${ref} completed.`)));
      if (isManager) list.push(button("Cancel", "btn--ghost", () => cancel(order)));
    } else if (order.status === "READY_FOR_PICKUP") {
      list.push(button("Complete", "btn--primary", () => advance(order, "COMPLETED", `Order ${ref} completed.`), "check"));
      if (isManager) list.push(button("Cancel", "btn--ghost", () => cancel(order)));
    } else if (order.status === "COMPLETED" && !paid) {
      list.push(confirmPayment(true)); // older orders that were completed before payment was required
    }
    if (order.late_fee_status === "DUE") {
      list.push(button("Late fee collected", "btn--primary", () => settleLateFee(order, "paid"), "check"));
      if (isManager) list.push(button("Waive late fee", "btn--ghost", () => waiveLateFee(order)));
    }
    list.push(button("Details", "btn--ghost", () => showDetails(order)));
    return el("div", { class: "order-card__actions" }, ...list);
  }

  function card(order, isNew) {
    const where = order.fulfilment_type === "DINE_IN" ? (order.table_number ? `Dine in · Table ${order.table_number}` : "Dine in") : "Pickup";
    const closed = ["REJECTED", "CANCELLED"].includes(order.status);
    return el("article", { class: "card order-card", "data-status": order.status, "data-new": isNew ? "true" : null, "aria-labelledby": `o-${order.public_id}` },
      el("header", { class: "order-card__head" },
        actionable(order) ? el("input", {
          type: "checkbox", class: "order-card__select", "aria-label": `Select ${order.reference}`, checked: selected.has(order.public_id),
          onchange: (e) => { e.currentTarget.checked ? selected.add(order.public_id) : selected.delete(order.public_id); render(); },
        }) : null,
        el("h2", { id: `o-${order.public_id}`, class: "order-card__code" }, order.reference),
        el("span", { class: "badge", "data-status": order.status }, STATUS_LABEL[order.status]),
        order.customer_type === "GUEST" ? el("span", { class: "badge", title: "Ordered without an account" }, "Guest") : null,
        closed && order.payment_status !== "PAID" ? null : el("span", { class: "badge", "data-status": order.payment_status }, PAYMENT_LABEL[order.payment_status] ?? order.payment_status),
        el("span", { class: "muted order-card__time", title: formatDateTime(order.created_at, info.timezone) },
          `${formatClock(order.created_at, info.timezone)} · ${timeAgo(order.created_at)}`)),
      el("p", { class: "order-card__meta" }, `#${order.code} · ${where}${order.pickup_at ? ` · ${pickupLine(order)}` : ""} · ${order.customer_name}`),
      order.late_fee_status === "DUE" ? el("p", { class: "alert alert--warning", role: "status" }, `Late fee to collect: ${formatMoney(order.late_fee, order.currency)}.`) : null,
      order.late_free_until && order.status === "READY_FOR_PICKUP" ? el("p", { class: "muted" }, `Free collection until ${formatDateTime(order.late_free_until, info.timezone)}.`) : null,
      order.refund_due ? el("p", { class: "alert alert--warning", role: "status" }, `Paid, then ${order.status === "REJECTED" ? "rejected" : "cancelled"}: refund ${formatMoney(order.total, order.currency)}.`) : null,
      el("ul", { class: "order-card__items" }, ...order.items.map((i) => el("li", {}, `${i.quantity} × ${i.item_name}`))),
      el("div", { class: "order-card__foot" }, el("strong", { class: "price" }, formatMoney(order.total, order.currency)), actions(order)),
    );
  }

  function render(newIds = new Set()) {
    const pending = orders.filter((o) => o.status === "PENDING" || (o.status === "CONFIRMED" && o.payment_status !== "PAID")).length;
    document.title = `${pending ? `(${pending}) ` : ""}Orders · ServeFlow`;
    const chips = el("div", { class: "chip-nav", style: "padding-inline:0", role: "group", "aria-label": "Show orders" },
      ...FILTERS.map((f) => el("button", {
        class: "chip", type: "button", "aria-current": String(f.id === filter.id),
        onclick: () => { filter = f; known = null; selected = new Set(); content.replaceChildren(skeleton()); refresh(); },
      }, f.label)));
    const box = el("form", { class: "search-row", role: "search" },
      el("input", { class: "input", type: "search", name: "search", maxlength: "40", value: search, placeholder: "Find by reference, name or phone digits", "aria-label": "Find an order" }),
      el("button", { class: "btn btn--secondary btn--sm", type: "submit" }, "Find"));
    box.addEventListener("submit", (event) => {
      event.preventDefault();
      search = new FormData(box).get("search").trim();
      known = null;
      content.replaceChildren(skeleton());
      refresh();
    });
    const more = el("button", { class: "btn btn--secondary", type: "button", hidden: !nextQuery }, "Load more");
    more.addEventListener("click", () => run(more, async () => {
      const page = await api.get(`${base}/orders/${nextQuery}`);
      orders = [...orders, ...page.results];
      loadedMore = true;
      nextQuery = page.next ? new URL(page.next, location.href).search : null;
      render();
    }));
    content.replaceChildren(
      chips, box,
      orders.some(actionable) ? selectionBar() : null,
      orders.length
        ? el("div", { class: "order-list" }, ...orders.map((o) => card(o, newIds.has(o.public_id))))
        : emptyState({ iconName: "list", title: filter.empty, text: "New orders appear here by themselves." }),
      more,
    );
  }

  const skeleton = () =>
    el("div", { class: "card card__pad stack", "aria-hidden": "true" },
      ...[60, 85, 70].map((w) => el("div", { class: "skeleton skeleton--line", style: `width:${w}%;height:1.25rem` })));

  content.replaceChildren(skeleton());
  try {
    info = await api.get(`${base}/`);
  } catch (err) {
    failure(err);
  }
  await refresh();

  // Live: look for new and changed orders every 5 seconds.
  const badge = liveBadge();
  attachBadge(badge);
  const sound = el("button", { class: "btn btn--secondary btn--sm sound-toggle", type: "button", "aria-pressed": String(soundWanted()) },
    "Sound: ", el("span", {}, soundWanted() ? "on" : "off"));
  sound.addEventListener("click", () => {
    const on = !soundWanted();
    try { localStorage.setItem(SOUND_STORAGE_KEY, on ? "on" : "off"); } catch { /* ignore */ }
    if (on) {
      audio ??= new (window.AudioContext ?? window.webkitAudioContext)();
      audio.resume?.();
      chime();
    }
    sound.setAttribute("aria-pressed", String(on));
    sound.lastChild.textContent = on ? "on" : "off";
  });
  if (soundWanted()) {
    // Browsers only allow sound after a click, so a saved "on" starts at the next click anywhere.
    document.addEventListener("click", () => { audio ??= new (window.AudioContext ?? window.webkitAudioContext)(); }, { once: true });
  }
  document.querySelector(".page-head").append(sound);
  sound.style.marginTop = "var(--s-2)";
  sound.style.justifySelf = "start";

  startLive({
    badge,
    intervalMs: 5000,
    shouldSkip: () => loadedMore || defaultShouldSkip(),
    refresh: async () => {
      try {
        await load({ announce: true });
      } catch (err) {
        if (handleSessionExpiry(err, HREF)) return;
        throw err;
      }
    },
  });
}

main();
