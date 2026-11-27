/* One function per page. Each returns { node, stop? }. Data comes only from platform.* (proposed contract) or the
 * existing /auth endpoints; a missing endpoint renders an honest "not connected" panel, never sample numbers. */
import { buildForm } from "../../shared/js/form-builder.js";
import { confirmDialog, el, icon, setBusy, toast } from "../../shared/js/ui.js";
import { formDialog } from "../../restaurant-dashboard/js/form-dialog.js";
import { fulfilmentErrors, restaurantFields } from "../../restaurant-dashboard/js/regional.js";
import { starText } from "../../shared/js/review-helpers.js";
import { slugify } from "../../shared/js/validators.js";
import { estimateLimits } from "./estimator.js";
import { modalForm } from "./forms.js";
import { changePassword, platform } from "./platform-api.js";
import {
  avatar, barChart, chartPanel, confirmAction, deltaChip, dl, donut, errorPanel, secretDialog, segmented, fmtDate, fmtMoney, fmtNumber, fmtPercent, futureTag, kpi, label,
  listPage, notAvailablePanel, openDrawer, pageHead, section, skeleton, statusBadge,
} from "./components.js";

const list = (name) => (query, o) => platform.list(name, query, o);
const when = (key) => (r) => fmtDate(r[key], { time: true });
const day = (key) => (r) => fmtDate(r[key]);
const short = (v) => (v === null || v === undefined || v === "" ? "—" : String(v));

function miniTable(caption, columns, rows, emptyText) {
  if (!rows?.length) return el("p", { class: "muted" }, emptyText);
  return el("div", { class: "table-wrap" }, el("table", { class: "table" }, el("caption", { class: "sr-only" }, caption),
    el("thead", {}, el("tr", {}, ...columns.map((c) => el("th", { scope: "col" }, c.label)))),
    el("tbody", {}, ...rows.map((r) => el("tr", {}, ...columns.map((c) => el("td", {}, c.render ? c.render(r) : short(r[c.key]))))))));
}
/* ---------------- Overview ---------------- */
const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };
const firstName = (u) => u?.first_name || (u?.email ?? "").split("@")[0] || "there";
const STATUS_ORDER = ["ACTIVE", "TRIAL", "PAST_DUE", "EXPIRED", "CANCELLED"];
const ATTENTION = {
  payment_awaiting: { tag: "Confirm", href: "#/payments" }, trial_ending: { tag: "Trial", href: "#/customers" }, expired: { tag: "Locked", href: "#/customers" },
};

export function overview(ctx) {
  let range = "30d";
  const content = el("div");
  async function load() {
    content.replaceChildren(skeleton());
    try {
      const d = await platform.overview(range);
      const t = d.totals ?? {}, p = d.previous ?? {}, series = d.series ?? {};
      const mrr = t.mrr && t.mrr.amount !== undefined ? fmtMoney(t.mrr.amount, t.mrr.currency).replace(/\.00$/, "") : null;
      const num = (v) => (v === undefined ? null : fmtNumber(v));
      const money = (m) => (m && m.amount !== undefined ? fmtMoney(m.amount, m.currency).replace(/\.00$/, "") : null);
      const statuses = STATUS_ORDER.map((key) => ({ key, label: label(key), value: d.subscription_status?.[key] ?? 0 }));
      const total = statuses.reduce((sum, x) => sum + x.value, 0);
      content.replaceChildren(
        el("div", { class: "oc-kpis" },
          kpi("Restaurants", num(t.customers), { icon: "store", delta: deltaChip(t.customers, p.customers), hint: "registered" }),
          kpi("Active subscriptions", num(t.active_subscriptions), { icon: "layers", hint: t.trials_running ? `${fmtNumber(t.trials_running)} more on trial` : "paying" }),
          kpi("Monthly recurring revenue", mrr, { icon: "bag", hint: "from active plans" }),
          kpi("API requests", num(t.api_requests), { icon: "bolt", delta: deltaChip(t.api_requests, p.api_requests), hint: "this period" })),
        el("div", { class: "oc-kpis" },
          kpi("Completed orders", num(t.completed_orders), { icon: "check", delta: deltaChip(t.completed_orders, p.completed_orders), hint: "the billable metric, this period" }),
          kpi("Subscription revenue", money(t.subscription_revenue), { icon: "bag", hint: "renewals and upgrades confirmed" }),
          kpi("Order-pack revenue", money(t.order_pack_revenue), { icon: "layers", hint: "extra order packs confirmed" }),
          kpi("Failed payments", num(t.failed_payments), { icon: "alert", hint: "this period" })),
        el("div", { class: "card oc-strip" },
          el("div", {}, el("small", {}, "Subscriptions"),
            total ? el("div", { class: "oc-mix", role: "img", "aria-label": statuses.map((x) => `${x.label}: ${x.value}`).join(", ") }, ...statuses.filter((x) => x.value).map((x) => el("i", { class: `st-${x.key}`, style: `width:${(x.value / total) * 100}%` }))) : el("span", {}, "No subscriptions yet."),
            el("div", { class: "oc-legend" }, ...statuses.filter((x) => x.value).map((x) => el("span", {}, el("i", { class: `oc-dot st-${x.key}` }), `${x.label} ${x.value}`)))),
          el("div", {}, el("small", {}, "Trials running"), el("strong", {}, num(t.trials_running) ?? "—"), el("span", {}, `${fmtNumber(t.trials_ending_soon ?? 0)} ending within 24 hours`)),
          el("div", {}, el("small", {}, "Transfers to confirm"), el("strong", {}, num(t.payments_awaiting) ?? "—"), el("a", { href: "#/payments" }, "Open payments")),
          el("div", {}, el("small", {}, "Locked (expired)"), el("strong", {}, num(t.expired_subscriptions) ?? "—"), el("span", {}, "waiting to pay")),
          el("div", {}, el("small", {}, "Error rate"), el("strong", {}, t.error_rate === undefined ? "—" : fmtPercent(t.error_rate)), el("span", {}, "server errors"))),
        chartPanel("Completed orders per day (all restaurants)", barChart((series.completed_orders ?? []).map((r) => ({ x: r.date, y: r.total })), { name: "Completed orders per day" }), "No completed orders in this period yet."),
        el("div", { class: "oc-grid2" },
          chartPanel("API requests", barChart((series.requests ?? []).map((r) => ({ x: r.date, y: r.total, y2: r.errors })), { name: "API requests per day", errors: true }), "No API traffic in this period yet."),
          el("section", { class: "card oc-panel" }, el("div", { class: "oc-panel__head" }, el("h2", {}, "Subscriptions by status")),
            donut(statuses, "restaurants") ?? el("p", { class: "muted" }, "No subscriptions yet."))),
        el("div", { class: "oc-grid2" },
          el("section", { class: "card oc-panel" }, el("div", { class: "oc-panel__head" }, el("h2", {}, "Latest restaurants"), el("a", { href: "#/customers" }, "View all")),
            miniTable("Latest restaurants", [
              { label: "Restaurant", render: (r) => el("a", { class: "oc-cell", href: `#/customers?search=${encodeURIComponent(r.account_id)}` }, avatar(r.name, true), el("div", {}, el("strong", {}, r.name), el("small", {}, r.account_id))) },
              { label: "Plan", render: (r) => r.plan_name ?? "—" }, { label: "Status", render: (r) => (r.subscription_status ? statusBadge(r.subscription_status) : "—") }, { label: "Joined", render: day("registered_at") },
            ], d.recent_customers, "No restaurants yet. Create the first with New restaurant.")),
          el("div", { class: "stack" },
            el("section", { class: "card oc-panel" }, el("div", { class: "oc-panel__head" }, el("h2", {}, "Needs attention"), el("small", {}, d.attention?.length ? String(d.attention.length) : "")),
              d.attention?.length ? el("ul", { class: "oc-list" }, ...d.attention.map((a) => el("li", {}, avatar(a.name),
                el("div", { class: "oc-list__text" }, el("strong", {}, a.name), el("span", {}, a.detail)),
                el("a", { class: "badge oc-badge oc-badge--warn", href: ATTENTION[a.type]?.href ?? "#/customers" }, ATTENTION[a.type]?.tag ?? "Open")))) : el("p", { class: "muted" }, "Nothing needs you right now.")),
            el("section", { class: "card oc-panel" }, el("div", { class: "oc-panel__head" }, el("h2", {}, "Recent activity"), el("a", { href: "#/audit" }, "Audit log")),
              d.recent_activity?.length ? el("ul", { class: "oc-list" }, ...d.recent_activity.slice(0, 6).map((e) => el("li", {},
                el("div", { class: "oc-list__text" }, el("strong", {}, label(e.type.replace(".", " "))), el("span", {}, e.summary || fmtDate(e.occurred_at, { time: true }))),
                el("small", { class: "muted" }, fmtDate(e.occurred_at)))) ) : el("p", { class: "muted" }, "No recent events.")))));
    } catch (err) {
      content.replaceChildren(
        el("div", { class: "oc-kpis" }, ...["Restaurants", "Active subscriptions", "Monthly recurring revenue", "API requests"].map((n) => kpi(n, null))),
        errorPanel(err, { what: "The overview", endpoint: "GET /api/v1/platform/overview/?range=30d", retry: load }));
    }
  }
  load();
  const head = el("div", { class: "oc-head" },
    el("div", {}, el("h2", {}, `${greeting()}, ${firstName(ctx.user)}`), el("p", {}, new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }) + " · ServeFlow")),
    el("div", { class: "oc-head__actions" }, segmented("Period", [["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"]], range, (v) => { range = v; load(); })));
  return { node: el("div", {}, head, content) };
}

/* ---------------- Restaurants (customers) ---------------- */
/** Active plans, cheapest first (for the pickers). An unavailable API just means an empty list. */
function plansFor() {
  return platform.list("plans", "").then((r) => (r.results ?? []).filter((p) => p.status === "ACTIVE" && !p.is_trial).sort((a, b) => Number(a.price) - Number(b.price))).catch(() => []);
}

/** The "New restaurant" dialog: the restaurant AND its one admin, created together. Resolves true when created. */
export async function newRestaurant() {
  const plans = await plansFor();
  const fields = [
    ...restaurantFields({ includeSlug: true, timezone: "Africa/Lagos" }),
    { name: "admin_email", label: "Admin's email", type: "email", required: true, autocomplete: "off", hint: "This person runs the restaurant. Each restaurant has exactly one admin, and each admin has exactly one restaurant." },
    { name: "admin_first_name", label: "Admin's first name (optional)", type: "text", maxlength: 150 },
    { name: "admin_last_name", label: "Admin's last name (optional)", type: "text", maxlength: 150 },
    { name: "admin_password", label: "Starting password (optional)", type: "password", autocomplete: "new-password", hint: "Leave blank and a temporary password is generated for you to hand over, shown once." },
    { name: "plan_id", label: "Plan they intend to pay for (optional)", type: "select", options: [{ value: "none", label: "Not chosen yet" }, ...plans.map((p) => ({ value: String(p.id), label: `${p.name} (${fmtMoney(p.price, p.currency)} / ${p.interval === "YEARLY" ? "year" : "month"})` }))],
      hint: "They start on the Free trial plan either way and pay for this plan when the trial ends." },
    { name: "start_trial", label: "Start the free trial now", type: "checkbox" },
  ];
  let result = null;
  const saved = await modalForm({
    title: "New restaurant", description: "Create the restaurant and its admin in one step. The free trial starts straight away on the built-in Free trial plan.", submitLabel: "Create restaurant", fields,
    values: { currency: "NGN", timezone: "Africa/Lagos", pickup_enabled: true, dine_in_enabled: false, requires_table_number: false, plan_id: "none", start_trial: true },
    validateForm: fulfilmentErrors,
    onReady: (controls) => {
      const name = controls.get("name").input, slug = controls.get("slug").input, currency = controls.get("currency").input;
      let edited = false;
      slug.addEventListener("input", () => { edited = true; });
      name.addEventListener("input", () => { if (!edited) slug.value = slugify(name.value); });
      currency.addEventListener("input", () => { currency.value = currency.value.toUpperCase(); });
    },
    submit: async (v) => {
      const body = {
        name: v.name.trim(), slug: v.slug.trim(), description: v.description, address: v.address, contact_phone: v.contact_phone, currency: v.currency.toUpperCase(), timezone: v.timezone,
        pickup_enabled: v.pickup_enabled, dine_in_enabled: v.dine_in_enabled, requires_table_number: v.requires_table_number,
        admin_email: v.admin_email.trim(), admin_first_name: v.admin_first_name, admin_last_name: v.admin_last_name,
        plan_id: v.plan_id === "none" ? null : Number(v.plan_id), start_trial: v.start_trial,
      };
      if (v.admin_password) body.admin_password = v.admin_password;
      result = await platform.create("customers", body);
    },
  });
  if (!saved) return false;
  const c = result.customer;
  toast(`${c.name} created.`, { type: "success" });
  if (result.temporary_password) {
    secretDialog({ title: "Hand these login details to the admin", message: "The temporary password is shown once. ServeFlow can't show it again, but you can reset it any time from the restaurant's page.",
      lines: [["Restaurant", c.name], ["Sign in at", new URL("../restaurant-dashboard/login.html", location.href).href], ["Email", result.admin_email]], secret: result.temporary_password, secretLabel: "Temporary password" });
  }
  return true;
}

const csvCell = (v) => {
  let text = v === null || v === undefined ? "" : String(v);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`; // stop spreadsheets running a cell as a formula
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

async function exportRestaurants(button) {
  setBusy(button, true);
  try {
    const rows = [];
    let query = "";
    for (let i = 0; i < 40; i++) {
      const page = await platform.list("customers", query);
      rows.push(...(page.results ?? []));
      if (!page.next) break;
      query = new URL(page.next, location.href).search;
    }
    const header = ["Restaurant", "Account ID", "Admin email", "Plan", "Subscription", "Subscription ends", "Registered", "Requests (30 days)", "Account"];
    const lines = [header, ...rows.map((r) => [r.name, r.account_id, r.admin_email, r.plan?.name, r.subscription_status, r.subscription_ends_at, r.registered_at, r.requests_30d, r.status])];
    const url = URL.createObjectURL(new Blob([lines.map((l) => l.map(csvCell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const link = el("a", { href: url, download: `serveflow-restaurants-${new Date().toISOString().slice(0, 10)}.csv` });
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`Exported ${rows.length} restaurants.`, { type: "success" });
  } catch (err) {
    toast(isNotAvailable(err) ? "The owner API isn't available yet." : (err.message ?? "Export failed."), { type: "error" });
  } finally { setBusy(button, false); }
}

/** Completed-order usage for one restaurant: this period, earlier periods, packs and a waiting change. */
function billingBlock(b) {
  const u = b.usage;
  return el("div", { class: "stack" },
    u ? dl([["Plan this period", u.plan_name], ["Completed orders", `${fmtNumber(u.completed_orders)} of ${fmtNumber(u.included_orders + u.extra_capacity)}${u.extra_capacity ? ` (${fmtNumber(u.extra_capacity)} from packs)` : ""}`], ["Left", fmtNumber(u.remaining)], ["Used", `${u.percent_used}%${u.warning_level ? ` · warning at ${u.warning_level}%` : ""}`], ["Resets", fmtDate(u.period_end)]]) : el("p", { class: "muted" }, "No running billing period."),
    b.pending_plan_change ? el("p", { class: "alert", role: "status" }, `${label(b.pending_plan_change.kind)} to ${b.pending_plan_change.to_plan} waiting${b.pending_plan_change.effective_at ? `, starts ${fmtDate(b.pending_plan_change.effective_at)}` : ", waiting for payment"}.`) : null,
    el("h4", {}, "Order packs"),
    miniTable("Order packs", [{ label: "Reference", render: (r) => el("code", {}, r.reference) }, { label: "Orders", render: (r) => fmtNumber(r.orders) }, { label: "Source", render: (r) => (r.granted_by_owner ? "Granted by you" : `Bought (${fmtMoney(r.price, r.currency)})`) }, { label: "Status", render: (r) => statusBadge(r.status) }], b.order_packs, "No order packs."),
    el("h4", {}, "Recent billing periods"),
    miniTable("Billing periods", [{ label: "Period", render: (r) => `${fmtDate(r.starts_at)} – ${fmtDate(r.ends_at)}` }, { label: "Plan", key: "plan_name" }, { label: "Included", render: (r) => fmtNumber(r.included_orders) }, { label: "Completed", render: (r) => fmtNumber(r.completed_orders) }, { label: "From packs", render: (r) => fmtNumber(r.from_packs) }, { label: "Over allowance", render: (r) => fmtNumber(r.over_allowance) }], b.periods, "No billing periods yet."));
}

function customerDrawer(summary, reload) {
  const { dialog, body } = openDrawer(summary.name ?? "Restaurant");
  body.append(skeleton());
  const draw = async () => {
    try {
      const c = await platform.detail("customers", summary.id);
      const refresh = () => { reload(); draw(); };
      const act = (text, run, { danger = false, message, confirmLabel = text } = {}) => el("button", { class: `btn ${danger ? "btn--danger" : "btn--secondary"} btn--sm`, type: "button", onclick: async () => {
        if (!(await confirmDialog({ title: `${text}: ${c.name}?`, message, confirmLabel, danger }))) return;
        try { await run(); } catch (err) { toast(isNotAvailable(err) ? "The server doesn't support this yet." : (err.message ?? "That didn't work."), { type: "error" }); }
      } }, text);
      const suspendOrBack = c.status === "ACTIVE"
        ? act("Suspend", async () => { await platform.action("customers", c.id, "suspend"); toast(`${c.name} suspended.`, { type: "success" }); refresh(); }, { danger: true, message: "The restaurant loses access until you reactivate it. This is recorded in the audit log." })
        : act("Reactivate", async () => { await platform.action("customers", c.id, "reactivate"); toast(`${c.name} reactivated.`, { type: "success" }); refresh(); }, { danger: false, message: "Access will be restored." });
      const reset = act("Reset admin password", async () => {
        const r = await platform.action("customers", c.id, "reset-admin-password");
        secretDialog({ title: "New temporary password", message: "Shown once. The admin is signed out everywhere and uses this to sign in again.", lines: [["Restaurant", c.name], ["Email", c.admin?.email]], secret: r.temporary_password, secretLabel: "Temporary password" });
      }, { message: "The current password stops working immediately and you'll get a new temporary one to hand over.", confirmLabel: "Reset password" });
      const marketplace = c.marketplace_approved
        ? act("Remove from marketplace", async () => { await platform.action("customers", c.id, "marketplace", { approved: false }); toast(`${c.name} removed from the marketplace.`, { type: "success" }); refresh(); },
          { danger: true, confirmLabel: "Remove", message: "Customers stop seeing this restaurant in the marketplace. Its own ordering link keeps working." })
        : act("Approve for marketplace", async () => { await platform.action("customers", c.id, "marketplace", { approved: true }); toast(`${c.name} approved for the marketplace.`, { type: "success" }); refresh(); },
          { confirmLabel: "Approve", message: c.listed_in_marketplace ? "They have asked to be listed. Check their name, address and bank details first: customers pay into the account shown." : "They haven't switched the marketplace on yet. Approving lets them appear once they do. Check their name, address and bank details first." });
      const extend = el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
        const saved = await modalForm({ title: `Give ${c.name} more time`, description: "A trial or ended subscription becomes a trial again until the new date. It's recorded in the audit log.", submitLabel: "Extend",
          fields: [{ name: "days", label: "Days to add", type: "text", inputmode: "numeric", required: true, validate: (v) => (/^\d{1,3}$/.test(v.trim()) && Number(v) >= 1 && Number(v) <= 365 ? null : "Enter 1 to 365.") }, { name: "reason", label: "Reason (optional)", type: "text", maxlength: 120 }],
          values: { days: "2" }, submit: (v) => platform.action("customers", c.id, "extend", { days: Number(v.days), reason: v.reason }) });
        if (saved) { toast("Time added.", { type: "success" }); refresh(); }
      } }, "Extend access");
      const grantOrders = el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
        const saved = await modalForm({ title: `Add free orders for ${c.name}`, description: "Adds completed-order capacity to the running billing period, free of charge. It expires with the period like any order pack. A reason is required and is recorded with your name in the audit log.", submitLabel: "Add orders",
          fields: [{ name: "orders", label: "Orders to add", type: "text", inputmode: "numeric", required: true, validate: (v) => (/^\d{1,5}$/.test(v.trim()) && Number(v) >= 1 && Number(v) <= 10000 ? null : "Enter 1 to 10,000.") },
            { name: "reason", label: "Reason", type: "text", required: true, maxlength: 160, hint: "For example: outage on Friday, goodwill." }],
          values: {}, submit: (v) => platform.action("customers", c.id, "grant-orders", { orders: Number(v.orders), reason: v.reason.trim() }) });
        if (saved) { toast("Orders added.", { type: "success" }); refresh(); }
      } }, "Add free orders");
      const changePlan = el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
        const plans = await plansFor();
        if (!plans.length) { toast("Create a plan first in Plans & Pricing.", { type: "info" }); return; }
        const saved = await modalForm({ title: `Plan for ${c.name}`, description: "A paying restaurant moves onto the plan at once. One on the free trial (or locked) is marked as paying for it and moves onto it when its transfer is confirmed.", submitLabel: "Set plan",
          fields: [{ name: "plan_id", label: "Plan", type: "select", required: true, options: plans.map((p) => ({ value: String(p.id), label: `${p.name} (${fmtMoney(p.price, p.currency)})` })) }],
          values: { plan_id: String(c.subscription?.next_plan?.id ?? (c.subscription?.plan?.is_trial ? plans[0].id : c.subscription?.plan?.id ?? plans[0].id)) }, submit: (v) => platform.action("customers", c.id, "plan", { plan_id: Number(v.plan_id) }) });
        if (saved) { toast("Plan changed.", { type: "success" }); refresh(); }
      } }, "Set plan");
      const remove = act("Delete", async () => { await platform.remove("customers", c.id); toast(`${c.name} deleted.`, { type: "success" }); dialog.close(); reload(); },
        { danger: true, confirmLabel: "Delete", message: "Only a restaurant with no orders, menu or history can be deleted, and it can't be undone. Otherwise suspend it: its records are kept." });

      const details = buildForm({
        idPrefix: "cd", submitLabel: "Save details", validateForm: fulfilmentErrors,
        fields: [...restaurantFields({ timezone: c.timezone }), { name: "accepting_orders", label: "Currently taking orders", type: "checkbox" }],
        values: Object.fromEntries(["name", "description", "address", "contact_phone", "currency", "timezone", "pickup_enabled", "dine_in_enabled", "requires_table_number", "accepting_orders"].map((k) => [k, c[k] ?? ""])),
        submit: (v) => platform.update("customers", c.id, { ...v, currency: v.currency.toUpperCase() }), onSuccess: () => { toast("Details saved.", { type: "success" }); refresh(); },
      });
      const adminForm = buildForm({
        idPrefix: "ca", submitLabel: "Save admin", values: { first_name: c.admin?.first_name ?? "", last_name: c.admin?.last_name ?? "", email: c.admin?.email ?? "" },
        fields: [{ name: "first_name", label: "First name", type: "text", maxlength: 150 }, { name: "last_name", label: "Last name", type: "text", maxlength: 150 }, { name: "email", label: "Email (their sign-in)", type: "email", required: true }],
        submit: (v) => platform.update("customers", c.id, { admin: v }), onSuccess: () => { toast("Admin saved.", { type: "success" }); refresh(); },
      });
      body.replaceChildren(...[
        el("section", { class: "card oc-panel" },
          el("div", { class: "oc-cell" }, avatar(c.name, true), el("div", {}, el("strong", {}, c.name), el("small", {}, c.account_id)), statusBadge(c.status), c.subscription ? statusBadge(c.subscription.status) : null),
          el("div", { class: "oc-actions" }, suspendOrBack, marketplace, reset, extend, changePlan, ...(c.billing?.usage ? [grantOrders] : []), remove)),
        section("Subscription", dl([["On plan", c.subscription?.plan?.name], ["Will pay for", c.subscription?.next_plan?.name ?? "Not chosen yet"], ["Status", c.subscription ? statusBadge(c.subscription.status) : "No subscription yet"], ["Period", c.subscription ? `${fmtDate(c.subscription.current_period_start)} – ${fmtDate(c.subscription.current_period_end)}` : null], ["Trial ends", fmtDate(c.subscription?.trial_ends_at)]])),
        c.billing ? section("Orders this period", billingBlock(c.billing)) : null,
        section("Restaurant details", details.form),
        section("Admin (one per restaurant)", el("p", { class: "muted" }, "This person runs the restaurant and signs in with this email."), adminForm.form),
        section("API usage", dl([["Requests (30 days)", fmtNumber(c.usage?.requests_30d)], ["Error rate", fmtPercent(c.usage?.error_rate)]])),
        section("API credentials", miniTable("Credentials", [{ label: "Identifier", key: "prefix" }, { label: "Environment", render: (r) => label(r.environment) }, { label: "Status", render: (r) => statusBadge(r.status) }, { label: "Last used", render: when("last_used_at") }], c.credentials, "No credentials. Restaurants only need keys if they integrate directly.")),
        section("Activity", miniTable("Activity", [{ label: "When", render: when("occurred_at") }, { label: "Event", key: "summary" }], c.activity, "No activity recorded."))].filter(Boolean));
    } catch (err) { body.replaceChildren(errorPanel(err, { what: "Restaurant details", endpoint: "GET /api/v1/platform/customers/{id}/", retry: draw })); }
  };
  draw();
}

export function customers(ctx) {
  const page = listPage({
    fetch: list("customers"), what: "Restaurants", endpoint: "GET /api/v1/platform/customers/", search: "Search name, account ID or admin email", initialSearch: ctx.params.get("search") ?? "",
    emptyText: "No restaurants yet. Click New restaurant to create the first one with its admin.",
    filters: [{ name: "status", label: "Account", options: [["ACTIVE", "Active"], ["SUSPENDED", "Suspended"]] }, { name: "subscription_status", label: "Subscription", options: [["TRIAL", "Trial"], ["ACTIVE", "Active"], ["PAST_DUE", "Past due"], ["EXPIRED", "Expired"], ["CANCELLED", "Cancelled"]] }, { name: "plan", label: "Plan", options: [] }],
    columns: [{ label: "Restaurant", render: (r) => el("div", { class: "oc-cell" }, avatar(r.name, true), el("div", {}, el("strong", {}, r.name), el("small", {}, r.account_id))) }, { label: "Admin", render: (r) => r.admin_email ?? "—" },
      { label: "Plan", render: (r) => (r.plan ? el("div", {}, r.plan.name, r.next_plan ? el("small", { class: "muted", style: "display:block" }, `will pay for ${r.next_plan.name}`) : null) : "—") },
      { label: "Subscription", render: (r) => (r.subscription_status ? el("div", {}, statusBadge(r.subscription_status), el("small", { class: "muted", style: "display:block" }, `ends ${fmtDate(r.subscription_ends_at)}`)) : "—") },
      { label: "Requests (30d)", render: (r) => fmtNumber(r.requests_30d) }, { label: "Account", render: (r) => statusBadge(r.status) }],
    rowActions: (r, reload) => [el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: () => customerDrawer(r, reload) }, "Manage")],
  });
  page.load();
  platform.list("plans", "").then((r) => page.setFilterOptions("plan", (r.results ?? []).map((p) => [String(p.id), p.name]))).catch(() => {});
  const exportButton = el("button", { class: "btn btn--secondary", type: "button" }, "Export CSV");
  exportButton.addEventListener("click", () => exportRestaurants(exportButton));
  const create = el("button", { class: "btn btn--primary", type: "button", onclick: async () => { if (await newRestaurant()) page.load(); } }, icon("plus"), "New restaurant");
  return { stop: page.stop, node: el("div", { class: "stack" },
    el("div", { class: "oc-head" }, el("div", {}, el("h2", {}, "Restaurants"), el("p", {}, "Every restaurant on ServeFlow, its admin and its subscription.")), el("div", { class: "oc-head__actions" }, exportButton, create)),
    page.node) };
}

/* ---------------- API management ---------------- */
function showSecret(secret, name) {
  secretDialog({ title: "Copy this secret now", message: `"${name}" is shown once. ServeFlow can't show it again; if it's lost, revoke it and create a new one. It isn't stored in this browser.`, secret, secretLabel: "API secret" });
}
export function apiManagement() {
  const page = listPage({
    fetch: list("credentials"), what: "API credentials", endpoint: "GET /api/v1/platform/credentials/", search: "Search customer or identifier",
    filters: [{ name: "status", label: "Status", options: [["ACTIVE", "Active"], ["REVOKED", "Revoked"]] }, { name: "environment", label: "Environment", options: [["live", "Live"], ["test", "Test"]] }],
    columns: [{ label: "Identifier", render: (r) => el("code", {}, r.prefix ?? "—") }, { label: "Name", key: "name" }, { label: "Customer", key: "customer_name" }, { label: "Environment", render: (r) => statusBadge(r.environment) }, { label: "Status", render: (r) => statusBadge(r.status) },
      { label: "Last used", render: when("last_used_at") }, { label: "Rate limit", render: (r) => (r.rate_limit_per_minute ? `${fmtNumber(r.rate_limit_per_minute)}/min` : "—") }, { label: "Monthly allowance", render: (r) => fmtNumber(r.monthly_request_limit) }, { label: "Created", render: day("created_at") }],
    rowActions: (r, reload) => (r.allowed_actions ?? []).includes("revoke") ? [el("button", { class: "btn btn--danger btn--sm", type: "button", onclick: async () => {
      if (await confirmAction({ title: "Revoke this credential?", message: `${r.prefix ?? "This credential"} stops working immediately and can't be restored. The change is recorded in the audit log.`, confirmLabel: "Revoke", run: () => platform.action("credentials", r.id, "revoke"), success: "Credential revoked." })) reload();
    } }, "Revoke")] : [],
  });
  const create = () => formDialog({ title: "Create API credential", description: "The backend generates the secret and shows it once. Nothing is generated in this browser.", submitLabel: "Create",
    fields: [{ name: "customer", label: "Customer account ID", type: "text", required: true, hint: "The restaurant's account ID, as listed under Restaurants." }, { name: "name", label: "Name", type: "text", required: true, maxlength: 60 }, { name: "environment", label: "Environment", type: "select", required: true, options: [{ value: "live", label: "Live" }, { value: "test", label: "Test" }] }],
    values: { environment: "live" },
    submit: async (v) => { const r = await platform.create("credentials", { customer: v.customer.trim(), name: v.name.trim(), environment: v.environment }); if (r?.secret) await showSecret(r.secret, v.name.trim()); } }).then((saved) => saved && page.load());
  page.load();
  const docs = el("a", { class: "btn btn--secondary", href: "/api/v1/docs/", target: "_blank", rel: "noopener" }, icon("code"), "API documentation");
  return { stop: page.stop, node: el("div", { class: "stack stack--lg" },
    el("div", { class: "alert alert--warning" }, icon("shield"), el("span", {}, "Restaurant accounts and API integrations are separate. Only create a credential for a business that integrates directly. Secrets are generated and shown once by the backend.")),
    el("div", { class: "row" }, el("button", { class: "btn btn--primary", type: "button", onclick: create }, icon("plus"), "Create credential"), docs), page.node) };
}

/* ---------------- API usage ---------------- */
export function usage() {
  const iso = (d) => d.toISOString().slice(0, 10);
  const to = new Date(), from = new Date(Date.now() - 29 * 864e5);
  const range = { from: iso(from), to: iso(to) };
  const content = el("div", { class: "stack stack--lg" });
  async function load() {
    content.replaceChildren(skeleton());
    try {
      const d = await platform.usage(range), t = d.totals ?? {};
      content.replaceChildren(
        el("div", { class: "oc-kpis" }, kpi("Total requests", t.requests === undefined ? null : fmtNumber(t.requests)), kpi("Successful", t.success === undefined ? null : fmtNumber(t.success)), kpi("Failed", t.failed === undefined ? null : fmtNumber(t.failed)), kpi("Error rate", t.error_rate === undefined ? null : fmtPercent(t.error_rate))),
        chartPanel("Requests over time (red: failed)", barChart((d.series ?? []).map((r) => ({ x: r.date, y: r.total, y2: r.errors })), { name: "API requests per day", errors: true })),
        el("div", { class: "oc-grid2" },
          section("By customer or integration", miniTable("Usage by customer", [{ label: "Customer", key: "name" }, { label: "Requests", render: (r) => fmtNumber(r.requests) }, { label: "Errors", render: (r) => fmtNumber(r.errors) }], d.by_customer, "No usage grouped by customer.")),
          section("By endpoint", miniTable("Usage by endpoint", [{ label: "Endpoint", render: (r) => el("code", {}, `${r.method ?? ""} ${r.path ?? ""}`.trim()) }, { label: "Requests", render: (r) => fmtNumber(r.requests) }, { label: "Errors", render: (r) => fmtNumber(r.errors) }], d.by_endpoint, "No endpoint-level usage."))),
        section("Rate-limit events", miniTable("Rate-limit events", [{ label: "When", render: when("occurred_at") }, { label: "Customer", key: "customer_name" }, { label: "Endpoint", key: "endpoint" }, { label: "Limit", key: "limit" }], d.rate_limit_events, "No rate-limit events in this period.")));
    } catch (err) { content.replaceChildren(errorPanel(err, { what: "API usage", endpoint: "GET /api/v1/platform/usage/?from=&to=", retry: load })); }
  }
  const dateInput = (name, text) => el("label", { class: "row" }, el("span", { class: "muted" }, text), el("input", { class: "input", type: "date", value: range[name], max: iso(new Date()), onchange: (e) => { range[name] = e.target.value; if (range.from && range.to && range.from <= range.to) load(); else toast("Start date must be on or before the end date.", { type: "error" }); } }));
  load();
  return { node: el("div", { class: "stack stack--lg" }, el("div", { class: "oc-toolbar" }, dateInput("from", "From"), dateInput("to", "To")), content) };
}

/* ---------------- Plans & pricing ---------------- */
const planFields = [
  { name: "name", label: "Plan name", type: "text", required: true, maxlength: 60 },
  { name: "description", label: "Description", type: "textarea", maxlength: 300 },
  { name: "interval", label: "Billing interval", type: "select", required: true, options: [{ value: "MONTHLY", label: "Monthly" }, { value: "YEARLY", label: "Yearly" }] },
  { name: "price", label: "Price (NGN)", type: "text", required: true, inputmode: "decimal", hint: "Set by you. Nothing is preset.", validate: (v) => (/^\d{1,10}(\.\d{1,2})?$/.test(v.trim()) ? null : "Enter an amount such as 3000 or 3000.50.") },
  { name: "included_orders", label: "Completed orders included per billing period", type: "text", inputmode: "numeric", required: true, hint: "The billable metric. Only completed orders count, from the marketplace and the API together.", validate: (v) => (/^\d{1,9}$/.test(v.trim()) ? null : "Enter a whole number, 0 or more.") },
  { name: "pack_orders", label: "Order pack size (optional)", type: "text", inputmode: "numeric", hint: "Extra completed orders a restaurant on this plan can buy for one billing period. Leave empty for no packs.", validate: (v) => (!v.trim() || /^[1-9]\d{0,8}$/.test(v.trim()) ? null : "Enter a whole number, 1 or more.") },
  { name: "pack_price", label: "Order pack price (NGN)", type: "text", inputmode: "decimal", hint: "Set with the pack size, or leave both empty.", validate: (v) => (!v.trim() || (/^\d{1,10}(\.\d{1,2})?$/.test(v.trim()) && Number(v) > 0) ? null : "Enter an amount above zero, such as 500.") },
  { name: "included_requests", label: "API requests per month (technical cap per key)", type: "text", inputmode: "numeric", required: true, hint: "Abuse protection, not billing.", validate: (v) => (/^\d{1,12}$/.test(v.trim()) ? null : "Enter a whole number, 0 or more.") },
  { name: "rate_limit_per_minute", label: "Rate limit (requests per minute)", type: "text", inputmode: "numeric", required: true, validate: (v) => (/^[1-9]\d{0,6}$/.test(v.trim()) ? null : "Enter a whole number, 1 or more.") },
  { name: "features", label: "Feature entitlements", type: "textarea", hint: "One per line." },
];
const TRIAL_PLAN_FIELDS = ["description", "included_orders", "included_requests", "rate_limit_per_minute", "features"];

/** A small "how many requests will this plan need?" helper inside the plan form. Arithmetic on assumptions you type; see docs/api-guide.md. */
function requestCalculator(controls) {
  const num = (name, text, value, hint) => {
    const input = el("input", { class: "input", type: "number", min: "0", step: "any", value: String(value), id: `calc-${name}`, "aria-describedby": `calc-${name}-h` });
    return { name, input, node: el("label", { class: "field", for: `calc-${name}` }, el("span", { class: "field__label" }, text), input, el("small", { class: "field__hint", id: `calc-${name}-h` }, hint)) };
  };
  const inputs = [
    num("ordersPerDay", "Orders per day for a typical restaurant", 30, "Your guess for the restaurants this plan is for."),
    num("openHours", "Hours open per day", 12, ""),
    num("cacheSeconds", "Menu cached for (seconds, 0 = not cached)", 60, "An integration that caches the menu reads it once per period instead of for every diner."),
    num("menuViewsPerOrder", "Menu views per order if not cached", 10, "Includes people who look and don't buy."),
  ];
  const out = el("div", { class: "oc-calc__out", "aria-live": "polite" });
  let latest = null;
  const apply = el("button", { class: "btn btn--secondary btn--sm", type: "button" }, "Use these numbers");
  const read = () => Object.fromEntries(inputs.map((i) => [i.name, Number(i.input.value)]));
  const recalc = () => {
    latest = estimateLimits(read());
    out.replaceChildren(
      el("p", {}, el("strong", {}, `About ${fmtNumber(latest.perMonth)} counted requests a month`), ` (${fmtNumber(latest.perDay)} a day: menu reads plus one checkout per order).`),
      el("p", {}, `Busiest minute: about ${latest.perMinutePeak} requests. Suggested: `, el("strong", {}, `${fmtNumber(latest.suggestedMonthly)} a month`), " (2.5 times the estimate) and ", el("strong", {}, `${fmtNumber(latest.suggestedPerMinute)} a minute`), " (3 times the busiest minute)."));
  };
  inputs.forEach((i) => i.input.addEventListener("input", recalc));
  apply.addEventListener("click", () => {
    for (const [name, value] of [["included_requests", latest.suggestedMonthly], ["rate_limit_per_minute", latest.suggestedPerMinute]]) {
      const input = controls.get(name)?.input;
      if (input) { input.value = String(value); input.dispatchEvent(new Event("input", { bubbles: true })); }
    }
    toast("Filled in the request allowance and rate limit. Review them before saving.", { type: "info" });
  });
  recalc();
  return el("details", { class: "oc-calc" }, el("summary", {}, "Estimate the request numbers"),
    el("p", { class: "muted" }, "Only calls made with an API key to a restaurant's routes count against a plan (the menu and checkout). Type what you expect and the numbers below fill in."),
    ...inputs.map((i) => i.node), out, apply);
}

export function plans() {
  const page = listPage({
    fetch: list("plans"), what: "Plans", endpoint: "GET /api/v1/platform/plans/", emptyText: "No plans yet. Create the first one when you've decided on pricing.",
    columns: [{ label: "Plan", render: (r) => el("div", {}, el("strong", {}, r.name ?? "—"), r.is_trial ? el("span", { class: "badge oc-badge oc-badge--neutral", style: "margin-left:var(--s-2)" }, "Built in") : null, r.description ? el("div", { class: "muted" }, r.description) : null) },
      { label: "Interval", render: (r) => (r.is_trial ? "—" : label(r.interval)) }, { label: "Price", render: (r) => (r.is_trial ? "Free" : fmtMoney(r.price, r.currency ?? "NGN")) },
      { label: "Orders included", render: (r) => fmtNumber(r.included_orders) },
      { label: "Order pack", render: (r) => (r.pack_orders ? `${fmtNumber(r.pack_orders)} for ${fmtMoney(r.pack_price, r.currency ?? "NGN")}` : "None") },
      { label: "API requests", render: (r) => fmtNumber(r.included_requests) }, { label: "Rate limit", render: (r) => (r.rate_limit_per_minute ? `${fmtNumber(r.rate_limit_per_minute)}/min` : "—") }, { label: "Features", render: (r) => fmtNumber(r.features?.length) }, { label: "Status", render: (r) => (r.is_trial ? "Every new restaurant" : statusBadge(r.status)) }],
    rowActions: (r, reload) => r.status === "ARCHIVED" ? [] : [
      el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: () => edit(r) }, "Edit"),
      r.is_trial ? null : el("button", { class: "btn btn--danger btn--sm", type: "button", onclick: async () => { if (await confirmAction({ title: `Archive ${r.name}?`, message: "New subscriptions can't use an archived plan. Existing subscribers are handled by the backend rules.", confirmLabel: "Archive", run: () => platform.action("plans", r.id, "archive"), success: "Plan archived." })) reload(); } }, "Archive")],
  });
  const body = (v, trial) => {
    const all = { name: v.name?.trim(), description: v.description.trim(), interval: v.interval, price: v.price?.trim(), currency: "NGN", included_orders: Number(v.included_orders), pack_orders: v.pack_orders?.trim() ? Number(v.pack_orders) : null, pack_price: v.pack_price?.trim() ? v.pack_price.trim() : null, included_requests: Number(v.included_requests), rate_limit_per_minute: Number(v.rate_limit_per_minute), features: v.features.split("\n").map((x) => x.trim()).filter(Boolean) };
    return trial ? Object.fromEntries(TRIAL_PLAN_FIELDS.map((k) => [k, all[k]])) : all;
  };
  const edit = (plan) => modalForm({
    title: plan ? `Edit ${plan.name}` : "New plan", submitLabel: plan ? "Save changes" : "Create plan",
    description: plan?.is_trial ? "Every new restaurant starts on this plan. It's free and built in; you can change what it includes." : undefined,
    fields: plan?.is_trial ? planFields.filter((f) => TRIAL_PLAN_FIELDS.includes(f.name)) : planFields,
    values: plan ? { ...plan, price: String(plan.price), included_orders: String(plan.included_orders ?? ""), pack_orders: plan.pack_orders ? String(plan.pack_orders) : "", pack_price: plan.pack_price ? String(plan.pack_price) : "", included_requests: String(plan.included_requests), rate_limit_per_minute: String(plan.rate_limit_per_minute), features: (plan.features ?? []).join("\n") } : { interval: "MONTHLY" },
    validateForm: (v) => ((v.pack_orders?.trim() ? 1 : 0) !== (v.pack_price?.trim() ? 1 : 0) ? { pack_orders: "Set both the pack size and its price, or leave both empty." } : {}),
    onReady: (controls, form) => form.insertBefore(requestCalculator(controls), form.querySelector(".dialog__footer")),
    submit: (v) => (plan ? platform.update("plans", plan.id, body(v, plan.is_trial)) : platform.create("plans", body(v, false))),
  }).then((saved) => { if (saved) { toast("Plan saved by the server.", { type: "success" }); page.load(); } });
  page.load();
  return { stop: page.stop, node: el("div", { class: "stack" },
    el("div", { class: "oc-head" }, el("div", {}, el("h2", {}, "Plans & Pricing"), el("p", {}, "Set what each plan costs and how many completed orders it includes. API request numbers are technical limits only. A plan's terms are frozen into each billing period, so editing a plan never changes a period already running.")), el("div", { class: "oc-head__actions" }, el("button", { class: "btn btn--primary", type: "button", onclick: () => edit(null) }, icon("plus"), "New plan"))), page.node) };
}

/* ---------------- Subscriptions, payments, audit ---------------- */
export function subscriptions() {
  const page = listPage({
    fetch: list("subscriptions"), what: "Subscriptions", endpoint: "GET /api/v1/platform/subscriptions/", search: "Search customer",
    filters: [{ name: "status", label: "Status", options: [["ACTIVE", "Active"], ["TRIAL", "Trial"], ["PAST_DUE", "Past due"], ["EXPIRED", "Expired"], ["CANCELLED", "Cancelled"]] }],
    columns: [{ label: "Customer", key: "customer_name" }, { label: "Plan", key: "plan_name" }, { label: "Status", render: (r) => statusBadge(r.status) }, { label: "Started", render: day("started_at") },
      { label: "Current period", render: (r) => `${fmtDate(r.current_period_start)} – ${fmtDate(r.current_period_end)}` },
      { label: "Orders this period", render: (r) => (r.orders ? el("div", {}, `${fmtNumber(r.orders.used)} of ${fmtNumber(r.orders.capacity)}`, r.orders.extra ? el("small", { class: "muted", style: "display:block" }, `incl. ${fmtNumber(r.orders.extra)} from packs`) : null) : "—") },
      { label: "Next plan", render: (r) => r.pending_plan_name ?? r.next_plan_name ?? "—" }, { label: "Renews / expires", render: day("renews_at") }, { label: "Payment", render: (r) => (r.payment_status ? statusBadge(r.payment_status) : "—") }, { label: "Trial ends", render: day("trial_ends_at") }],
  });
  page.load();
  return { node: page.node, stop: page.stop };
}
export function payments() {
  const page = listPage({
    fetch: list("payments"), what: "ServeFlow payments", endpoint: "GET /api/v1/platform/payments/", search: "Search reference or customer",
    filters: [{ name: "kind", label: "For", options: [["SUBSCRIPTION", "Subscription"], ["ORDER_PACK", "Order pack"], ["UPGRADE", "Plan upgrade"]] }, { name: "status", label: "Status", options: [["AWAITING_CONFIRMATION", "Awaiting confirmation"], ["CONFIRMED", "Confirmed"], ["FAILED", "Failed"]] }],
    columns: [{ label: "Reference", render: (r) => el("code", {}, r.reference ?? "—") }, { label: "For", render: (r) => ({ SUBSCRIPTION: "Subscription", ORDER_PACK: "Order pack", UPGRADE: "Upgrade" }[r.kind] ?? label(r.kind)) }, { label: "Customer", key: "customer_name" }, { label: "Amount", render: (r) => fmtMoney(r.amount, r.currency) },
      { label: "Status", render: (r) => el("div", {}, statusBadge(r.status), r.failure_reason ? el("small", { class: "muted", style: "display:block" }, r.failure_reason) : null) },
      { label: "Provider", render: (r) => el("div", {}, label(r.provider), r.provider_reference ? el("small", { class: "muted", style: "display:block" }, r.provider_reference) : null) }, { label: "Date", render: when("transacted_at") }],
    rowActions: (r, reload) => (r.allowed_actions ?? []).includes("confirm") ? [el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: async () => {
      const saved = await modalForm({ title: `Mark ${r.reference} as failed`, description: "Use this when the money never arrived or was wrong. A waiting order pack or upgrade is cancelled. The reason and your name are kept in the audit log.", submitLabel: "Mark failed",
        fields: [{ name: "reason", label: "Reason", type: "text", required: true, maxlength: 200 }], values: {}, submit: (v) => platform.action("payments", r.id, "fail", { reason: v.reason.trim() }) });
      if (saved) { toast("Marked as failed.", { type: "success" }); reload(); }
    } }, "Mark failed"), el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
      if (await confirmAction({ title: "Confirm this transfer?", message: `Ask the backend to confirm ${fmtMoney(r.amount, r.currency)} from ${r.customer_name ?? "this customer"} (ref ${r.reference}). The backend checks it and records you in the audit log; this page does not mark anything paid itself.`, confirmLabel: "Confirm transfer", danger: false, run: () => platform.action("payments", r.id, "confirm"), success: "Confirmed by the server." })) reload();
    } }, "Confirm transfer")] : [],
  });
  page.load();
  return { stop: page.stop, node: el("div", { class: "stack" }, el("div", { class: "alert alert--warning" }, icon("info"), el("span", {}, "These are payments to ServeFlow only (subscriptions, upgrades and order packs), never what restaurant customers pay for food. Status always comes from the server; a payment is confirmed once.")), page.node) };
}
export function audit() {
  const page = listPage({
    fetch: list("audit"), what: "Platform audit log", endpoint: "GET /api/v1/platform/audit/", search: "Search actor, action or resource",
    columns: [{ label: "When", render: when("occurred_at") }, { label: "Actor", key: "actor" }, { label: "Action", render: (r) => label(r.action) }, { label: "Resource", render: (r) => [r.resource_type, r.resource_id].filter(Boolean).join(" ") || "—" }, { label: "Details", key: "summary" }],
  });
  page.load();
  return { node: page.node, stop: page.stop };
}

/* ---------------- Reviews (moderation) ---------------- */
export function reviews() {
  const page = listPage({
    fetch: list("reviews"), what: "Reviews", endpoint: "GET /api/v1/platform/reviews/", search: "Search restaurant, name or comment",
    emptyText: "No reviews yet. They appear here once customers review completed orders.",
    filters: [{ name: "status", label: "Status", options: [["PUBLISHED", "Published"], ["HIDDEN", "Hidden"]] }, { name: "reported", label: "Reports", options: [["1", "Reported only"]] }],
    columns: [
      { label: "Restaurant", key: "restaurant_name" },
      { label: "Rating", render: (r) => el("span", { class: "stars", role: "img", "aria-label": `${r.rating} out of 5` }, starText(r.rating)) },
      { label: "Review", render: (r) => el("div", {}, r.comment ? el("span", {}, r.comment.length > 140 ? `${r.comment.slice(0, 140)}…` : r.comment) : el("span", { class: "muted" }, "Rating only"), el("small", { class: "muted", style: "display:block" }, r.display_name)) },
      { label: "Status", render: (r) => el("div", {}, statusBadge(r.status), r.moderation_reason ? el("small", { class: "muted", style: "display:block" }, r.moderation_reason) : null) },
      { label: "Reports", render: (r) => (r.open_reports.length ? el("div", {}, ...r.open_reports.map((x) => el("small", { style: "display:block" }, `“${x.reason}”`))) : "—") },
      { label: "Posted", render: when("created_at") },
    ],
    rowActions: (r, reload) => {
      const buttons = [];
      if (r.status === "PUBLISHED") {
        buttons.push(el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
          const saved = await modalForm({ title: "Hide this review", description: "It disappears from the restaurant page and stops counting toward its rating. The reason and your name are kept in the audit log, and any open reports are closed.", submitLabel: "Hide review",
            fields: [{ name: "reason", label: "Reason", type: "text", required: true, maxlength: 200, hint: "For example: abusive language, not a real order." }], values: {},
            submit: (v) => platform.action("reviews", r.id, "hide", { reason: v.reason.trim() }) });
          if (saved) { toast("Review hidden.", { type: "success" }); reload(); }
        } }, "Hide"));
        if (r.open_reports.length) {
          buttons.push(el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: async () => {
            if (await confirmAction({ title: "Dismiss the reports?", message: "The review stays published and the reports are closed. This is recorded in the audit log.", confirmLabel: "Dismiss", danger: false, run: () => platform.action("reviews", r.id, "dismiss"), success: "Reports dismissed." })) reload();
          } }, "Dismiss reports"));
        }
      } else {
        buttons.push(el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
          if (await confirmAction({ title: "Restore this review?", message: "It appears again and counts toward the rating. This is recorded in the audit log.", confirmLabel: "Restore", danger: false, run: () => platform.action("reviews", r.id, "restore"), success: "Review restored." })) reload();
        } }, "Restore"));
      }
      return buttons;
    },
  });
  page.load();
  return { node: page.node, stop: page.stop };
}

/* ---------------- Settings ---------------- */
export function settings(ctx) {
  const info = el("div", {}, skeleton(2));
  (async () => {
    try {
      const s = await platform.settings();
      const pairs = (o) => Object.entries(o ?? {}).map(([k, v]) => [label(k), typeof v === "object" ? JSON.stringify(v) : v]);
      const pay = buildForm({
        idPrefix: "pay", submitLabel: "Save payment details", values: s.payment_details ?? {},
        fields: [{ name: "bank_name", label: "Bank name", type: "text", maxlength: 100 }, { name: "account_name", label: "Account name", type: "text", maxlength: 100 },
          { name: "account_number", label: "Account number", type: "text", inputmode: "numeric", maxlength: 20, hint: "Digits only. Restaurants see it after they sign in; the public pricing page never shows it.", validate: (v) => (!v.trim() || /^\d{6,20}$/.test(v.trim()) ? null : "Use digits only, 6 to 20 of them.") },
          { name: "instructions", label: "Note for payers (public)", type: "textarea", maxlength: 500, hint: "Shown on the pricing page. Don't put account details here." }],
        submit: (v) => platform.saveSettings(v), onSuccess: () => toast("Payment details saved by the server.", { type: "success" }),
      });
      info.replaceChildren(el("div", { class: "stack" }, section("Payment details (bank transfer)", pay.form), section("Platform information", pairs(s.platform).length ? dl(pairs(s.platform)) : el("p", { class: "muted" }, "Nothing reported.")), section("API defaults", pairs(s.api_defaults).length ? dl(pairs(s.api_defaults)) : el("p", { class: "muted" }, "Nothing reported."))));
    } catch (err) { info.replaceChildren(errorPanel(err, { what: "Platform settings", endpoint: "GET /api/v1/platform/settings/" })); }
  })();
  const u = ctx.user;
  const { form } = buildForm({
    idPrefix: "pw", submitLabel: "Change password", values: {},
    fields: [{ name: "current_password", label: "Current password", type: "password", required: true, autocomplete: "current-password" }, { name: "new_password", label: "New password", type: "password", required: true, autocomplete: "new-password" }, { name: "confirm", label: "Repeat new password", type: "password", required: true, autocomplete: "new-password" }],
    validateForm: (v) => (v.new_password !== v.confirm ? { confirm: "The passwords don't match." } : {}),
    submit: (v) => changePassword(v.current_password, v.new_password), onSuccess: () => toast("Password changed.", { type: "success" }),
  });
  return { node: el("div", { class: "stack stack--lg" },
    info,
    section("Administrator account", dl([["Name", [u?.first_name, u?.last_name].filter(Boolean).join(" ") || null], ["Email", u?.email]])),
    section("Security", el("p", { class: "muted" }, "Owner access is decided by the server on every request. This browser stores no role or credentials."), form),
    section("Notification preferences", el("p", {}, futureTag(), " Notifications aren't built yet."), el("label", { class: "check" }, el("input", { type: "checkbox", disabled: true }), "Email me about failed payments"), el("label", { class: "check" }, el("input", { type: "checkbox", disabled: true }), "Email me about overdue subscriptions"))) };
}
export { notAvailablePanel };
