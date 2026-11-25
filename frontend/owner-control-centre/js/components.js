/* Reusable pieces for the Owner Control Centre. API data is only ever inserted as text. */
import { ApiError } from "../../shared/js/api.js";
import { closeOnBackdrop, confirmDialog, el, icon, setBusy, toast } from "../../shared/js/ui.js";
import { buildQuery, isNotAvailable } from "./platform-api.js";

const SVG_NS = "http://www.w3.org/2000/svg";
export const DOCS = "docs/owner-api-contract.md";

/* ---------- formatting ---------- */
export const fmtNumber = (n) => (typeof n === "number" && Number.isFinite(n) ? new Intl.NumberFormat().format(n) : "—");
export const fmtPercent = (f) => (typeof f === "number" && Number.isFinite(f) ? `${(f * 100).toFixed(2)}%` : "—");
export function fmtDate(value, { time = false } = {}) {
  const d = value ? new Date(value) : null;
  if (!d || Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, time ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}
export function fmtMoney(amount, currency) {
  const n = Number.parseFloat(amount);
  if (!Number.isFinite(n)) return "—";
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency: currency || "NGN", currencyDisplay: "narrowSymbol" }).format(n); } catch { return `${n.toFixed(2)} ${currency ?? ""}`.trim(); }
}
export const label = (v) => (v ? String(v).replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "—");

const TONES = {
  good: ["active", "paid", "succeeded", "success", "confirmed", "live", "ok"],
  warn: ["trial", "pending", "awaiting", "grace", "past_due", "test"],
  bad: ["suspended", "revoked", "failed", "expired", "cancelled", "overdue", "locked", "error", "archived"],
};
export function statusBadge(value) {
  const key = String(value ?? "").toLowerCase();
  const tone = Object.keys(TONES).find((t) => TONES[t].some((w) => key.includes(w))) ?? "neutral";
  return el("span", { class: `badge oc-badge oc-badge--${tone}` }, label(value));
}

/* ---------- states ---------- */
export function notAvailablePanel({ what, endpoint }) {
  return el("div", { class: "card oc-na", role: "status" }, icon("info"),
    el("div", { class: "stack" },
      el("h2", {}, "Not connected yet"),
      el("p", { class: "muted" }, `${what} needs a backend endpoint that this server doesn't provide yet. Nothing is shown here rather than invented numbers.`),
      endpoint ? el("p", {}, "Expected: ", el("code", {}, endpoint)) : null,
      el("p", { class: "muted" }, `Contract: ${DOCS}`)));
}
export function errorPanel(err, { what, endpoint, retry } = {}) {
  if (isNotAvailable(err)) return notAvailablePanel({ what, endpoint });
  const text = err instanceof ApiError && err.status === 403 ? "Your account isn't allowed to see this." : (err?.message ?? "Something went wrong.");
  const box = el("div", { class: "alert alert--danger", role: "alert" }, icon("alert"), el("span", {}, text));
  if (retry) box.append(el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: retry }, icon("refresh"), "Try again"));
  return box;
}
export const skeleton = (rows = 3) => el("div", { class: "card card__pad stack", "aria-hidden": "true" },
  ...Array.from({ length: rows }, (_, i) => el("div", { class: "skeleton skeleton--line", style: `width:${[70, 90, 55][i % 3]}%;height:1.1rem` })));

export function pageHead(title, text, extra) {
  return el("div", { class: "oc-head" }, el("div", { class: "row", style: "justify-content:space-between" }, el("h2", { style: "font-size:var(--fs-xl)" }, title), extra ?? null), text ? el("p", {}, text) : null);
}
export const futureTag = () => el("span", { class: "oc-future" }, "Future feature");

/* ---------- small building blocks ---------- */
export function timeAgo(value, now = Date.now()) {
  const then = value ? new Date(value).getTime() : NaN;
  if (Number.isNaN(then)) return "";
  const minutes = Math.floor((now - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days < 30 ? `${days} d ago` : fmtDate(value);
}

export const initials = (text) => String(text ?? "?").split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";
export const avatar = (text, square = false) => el("span", { class: `oc-avatar${square ? " oc-avatar--sq" : ""}`, "aria-hidden": "true" }, initials(text));

/** A green or red chip for the change against the previous period. Only when both numbers are real. */
export function deltaChip(current, previous) {
  if (typeof current !== "number" || typeof previous !== "number" || previous <= 0) return null;
  const pct = ((current - previous) / previous) * 100;
  return el("span", { class: `oc-delta${pct < 0 ? " oc-delta--down" : ""}` }, `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`);
}

/** KPI card. `value` null/undefined shows an honest dash. `extra` is {hint, icon, delta} or just a hint string. */
export function kpi(name, value, extra) {
  const { hint = "", icon: iconName, delta = null } = typeof extra === "string" ? { hint: extra } : (extra ?? {});
  const empty = value === null || value === undefined || value === "—";
  return el("div", { class: "card oc-kpi" },
    el("span", { class: "oc-kpi__label" }, iconName ? icon(iconName) : null, name),
    el("span", { class: `oc-kpi__value${empty ? " oc-kpi__value--empty" : ""}` }, empty ? "—" : String(value)),
    el("span", { class: "oc-kpi__hint" }, empty ? "Not reported by the backend" : null, ...(empty ? [] : [delta, hint].filter(Boolean))));
}

/** Segmented control (period picker). */
export function segmented(label, options, value, onChange) {
  const buttons = options.map(([key, text]) => el("button", { type: "button", "aria-pressed": String(key === value) }, text));
  const group = el("div", { class: "oc-seg", role: "group", "aria-label": label }, ...buttons);
  buttons.forEach((button, i) => button.addEventListener("click", () => {
    buttons.forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    onChange(options[i][0]);
  }));
  return group;
}

/** Donut from real counts: [{key, label, value}]. Returns null when everything is zero. */
export function donut(segments, centreLabel) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (!total) return null;
  const C = 2 * Math.PI * 40;
  let used = 0;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 100 100");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", segments.filter((s) => s.value).map((s) => `${s.label}: ${s.value}`).join(", "));
  for (const seg of segments.filter((x) => x.value)) {
    const length = (C * seg.value) / total;
    const ring = document.createElementNS(SVG_NS, "circle");
    ring.setAttribute("cx", "50"); ring.setAttribute("cy", "50"); ring.setAttribute("r", "40");
    ring.setAttribute("class", `oc-donut__ring st-${seg.key}`);
    ring.setAttribute("stroke", "var(--c)");
    ring.setAttribute("stroke-dasharray", `${Math.max(length - 1, 0)} ${C - Math.max(length - 1, 0)}`);
    ring.setAttribute("stroke-dashoffset", String(-used));
    ring.setAttribute("transform", "rotate(-90 50 50)");
    svg.append(ring);
    used += length;
  }
  const text = (y, size, weight, content, fill) => { const t = document.createElementNS(SVG_NS, "text"); t.setAttribute("x", "50"); t.setAttribute("y", y); t.setAttribute("text-anchor", "middle"); t.setAttribute("font-size", size); t.setAttribute("font-weight", weight); t.setAttribute("fill", fill); t.textContent = content; svg.append(t); };
  text("52", "17", "700", String(total), "var(--ink)");
  text("63", "7", "500", centreLabel, "var(--ink-3)");
  return el("div", { class: "oc-donut" }, svg, el("ul", { class: "oc-donut__legend" },
    ...segments.map((s) => el("li", {}, el("span", {}, el("i", { class: `oc-dot st-${s.key}` }), s.label), el("b", {}, fmtNumber(s.value))))));
}

/** Show something the server will never show again (a password, an API secret). Cleared from the page when closed. */
export function secretDialog({ title, message, lines = [], secret, secretLabel = "Secret" }) {
  const input = el("input", { class: "input oc-secret", readonly: true, value: secret, "aria-label": secretLabel });
  const dialog = el("dialog", { class: "dialog", "aria-label": title }, el("div", { class: "dialog__panel" },
    el("h2", {}, title), el("p", { class: "muted" }, message),
    lines.length ? dl(lines) : null, el("label", { class: "field__label" }, secretLabel), input,
    el("div", { class: "dialog__footer" },
      el("button", { class: "btn btn--secondary", type: "button", onclick: async () => { try { await navigator.clipboard.writeText(secret); toast("Copied.", { type: "success" }); } catch { input.select(); toast("Select it and copy it by hand.", { type: "info" }); } } }, "Copy"),
      el("button", { class: "btn btn--primary", type: "button", onclick: () => dialog.close() }, "I've saved it"))));
  dialog.addEventListener("close", () => { input.value = ""; dialog.remove(); });
  document.body.append(dialog);
  dialog.showModal();
}

/* ---------- SVG bar chart from real points [{x, y, y2?}] ---------- */
export function barChart(points, { name, format = fmtNumber, errors = false }) {
  if (!Array.isArray(points) || !points.length) return null;
  const W = 640, H = 190, padX = 8, padTop = 18, padBottom = 22;
  const max = Math.max(1, ...points.map((p) => p.y));
  const slot = (W - padX * 2) / points.length, bw = Math.max(2, slot * 0.7);
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "oc-chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${name}: ${points.length} points, highest ${format(max)}, from ${points[0].x} to ${points.at(-1).x}.`);
  const add = (tag, attrs, text) => { const n = document.createElementNS(SVG_NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); if (text) n.textContent = text; svg.append(n); return n; };
  add("text", { x: padX, y: 11, class: "oc-axis" }, format(max));
  points.forEach((p, i) => {
    const h = ((H - padTop - padBottom) * p.y) / max, x = padX + i * slot + (slot - bw) / 2, y = H - padBottom - h;
    add("rect", { x, y, width: bw, height: Math.max(h, p.y > 0 ? 1 : 0), rx: 2, class: "oc-bar" }).append(Object.assign(document.createElementNS(SVG_NS, "title"), { textContent: `${p.x}: ${format(p.y)}` }));
    if (errors && p.y2 > 0) add("rect", { x, y: H - padBottom - ((H - padTop - padBottom) * p.y2) / max, width: bw, height: ((H - padTop - padBottom) * p.y2) / max, rx: 2, class: "oc-bar oc-bar--err" });
  });
  add("text", { x: padX, y: H - 5, class: "oc-axis" }, String(points[0].x));
  add("text", { x: W - padX, y: H - 5, class: "oc-axis", "text-anchor": "end" }, String(points.at(-1).x));
  return svg;
}
export const chartPanel = (title, chart, emptyText) => el("section", { class: "card oc-panel" }, el("h2", {}, title),
  chart ?? el("p", { class: "muted" }, emptyText ?? "No data for this period."));

/* ---------- detail drawer + one-time dialogs ---------- */
export function openDrawer(title) {
  const body = el("div", { class: "oc-drawer__body" });
  const dialog = el("dialog", { class: "oc-drawer", "aria-label": title },
    el("div", { class: "oc-drawer__head" }, el("h2", { style: "font-size:var(--fs-lg)" }, title),
      el("button", { class: "btn btn--ghost btn--sm", type: "button", "aria-label": "Close", onclick: () => dialog.close() }, icon("x"))), body);
  closeOnBackdrop(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  return { dialog, body };
}
export const dl = (pairs) => el("dl", { class: "oc-dl" }, ...pairs.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v instanceof Node ? v : (v === null || v === undefined || v === "" ? "—" : String(v)))]));
export const section = (title, ...children) => el("section", { class: "card oc-panel" }, el("h2", {}, title), ...children);

/** Confirm, run the backend action, report the backend's answer. Returns true only when the server accepted it. */
export async function confirmAction({ title, message, confirmLabel, danger = true, run, success }) {
  if (!(await confirmDialog({ title, message, confirmLabel, danger }))) return false;
  try { await run(); toast(success, { type: "success" }); return true; } catch (err) {
    toast(isNotAvailable(err) ? "The server doesn't support this action yet. Nothing was changed." : (err.message ?? "That didn't work."), { type: "error" });
    return false;
  }
}

/* ---------- filtered, searchable, cursor-paginated table ---------- */
export function listPage({ fetch, columns, filters = [], search, initialSearch = "", what, endpoint, rowActions, emptyText = "Nothing to show yet." }) {
  const state = { q: initialSearch, values: {}, controller: null, rows: [], next: null };
  const body = el("div");
  const more = el("button", { class: "btn btn--secondary", type: "button", hidden: true }, "Load more");
  const toolbar = el("div", { class: "oc-toolbar", role: "search" });
  let timer;
  if (search) {
    toolbar.append(el("input", { class: "input grow", type: "search", "aria-label": search, placeholder: search, value: initialSearch, oninput: (e) => { clearTimeout(timer); timer = setTimeout(() => { state.q = e.target.value; load(); }, 300); } }));
  }
  const selects = new Map();
  for (const f of filters) {
    const select = el("select", { class: "select", "aria-label": f.label, onchange: (e) => { state.values[f.name] = e.target.value; load(); } },
      el("option", { value: "" }, `${f.label}: all`), ...f.options.map(([v, l]) => el("option", { value: v }, l)));
    selects.set(f.name, select);
    toolbar.append(select);
  }
  /** Fill a filter's options from backend data after the page is built (e.g. the plan list). */
  const setFilterOptions = (name, options) => selects.get(name)?.append(...options.map(([v, l]) => el("option", { value: v }, l)));
  async function load({ append = false } = {}) {
    state.controller?.abort();
    const controller = (state.controller = new AbortController());
    if (!append) { body.replaceChildren(skeleton()); state.rows = []; state.next = null; more.hidden = true; } else setBusy(more, true);
    try {
      const query = append ? state.next : buildQuery({ search: state.q, ...state.values });
      const page = await fetch(query, { signal: controller.signal });
      state.rows.push(...(page.results ?? []));
      state.next = page.next ? new URL(page.next, location.href).search : null;
      render();
    } catch (err) {
      if (err.name === "AbortError") return;
      body.replaceChildren(errorPanel(err, { what, endpoint, retry: () => load() }));
      more.hidden = true;
    } finally { setBusy(more, false); more.hidden = !state.next; }
  }
  function render() {
    if (!state.rows.length) { body.replaceChildren(el("div", { class: "card empty" }, el("span", { class: "empty__icon" }, icon("list", { large: true })), el("h2", {}, "No records"), el("p", {}, state.q || Object.values(state.values).some(Boolean) ? "No results match these filters." : emptyText))); return; }
    const head = el("tr", {}, ...columns.map((c) => el("th", { scope: "col" }, c.label)), rowActions ? el("th", { scope: "col" }, "Actions") : null);
    const rows = state.rows.map((row) => el("tr", {}, ...columns.map((c) => el("td", { "data-label": c.label }, c.render ? c.render(row) : (row[c.key] ?? "—"))), rowActions ? el("td", { "data-label": "Actions" }, el("div", { class: "oc-table-actions" }, ...rowActions(row, () => load()))) : null));
    body.replaceChildren(el("div", { class: "card table-wrap" }, el("table", { class: "table table--stack" }, el("caption", { class: "sr-only" }, what), el("thead", {}, head), el("tbody", {}, ...rows))));
  }
  more.addEventListener("click", () => load({ append: true }));
  const node = el("div", { class: "stack" }, toolbar, body, more);
  return { node, load, setFilterOptions, stop: () => state.controller?.abort() };
}
