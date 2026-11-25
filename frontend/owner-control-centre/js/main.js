/* Boot, authentication gate, application shell and hash router for the Owner Control Centre.
 * Authorization is the backend's job: GET /platform/me/ decides whether this session is a platform owner.
 * Nothing about roles is stored in the browser. */
import { ApiError } from "../../shared/js/api.js";
import { getSession, login, logout } from "../../shared/js/auth.js";
import { buildForm } from "../../shared/js/form-builder.js";
import { el, icon } from "../../shared/js/ui.js";
import { avatar, errorPanel } from "./components.js";
import * as pages from "./pages.js";
import { createBell } from "./notifications.js";
import { isNotAvailable, platform } from "./platform-api.js";

const ROUTES = [
  { id: "overview", group: "Operate", label: "Overview", icon: "chart", render: pages.overview },
  { id: "customers", group: "Operate", label: "Restaurants", icon: "store", render: pages.customers },
  { id: "reviews", group: "Operate", label: "Reviews", icon: "smile", render: pages.reviews },
  { id: "api", group: "API", label: "API Management", icon: "code", render: pages.apiManagement },
  { id: "usage", group: "API", label: "API Usage", icon: "bolt", render: pages.usage },
  { id: "plans", group: "Billing", label: "Plans & Pricing", icon: "layers", render: pages.plans },
  { id: "subscriptions", group: "Billing", label: "Subscriptions", icon: "refresh", render: pages.subscriptions },
  { id: "payments", group: "Billing", label: "Payments", icon: "bag", render: pages.payments },
  { id: "audit", group: "Admin", label: "Audit Logs", icon: "shield", render: pages.audit },
  { id: "settings", group: "Admin", label: "Platform Settings", icon: "settings", render: pages.settings },
];
const GROUPS = [...new Set(ROUTES.map((r) => r.group))];
const app = document.getElementById("app");
const brandMark = () => el("span", { class: "brand__mark" }, icon("leaf"));

export function parseHash(hash) {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const route = ROUTES.find((r) => r.id === path) ?? ROUTES[0];
  return { route, params: new URLSearchParams(query) };
}

/* ---------- screens before the shell ---------- */
function center(...children) { app.replaceChildren(el("main", { class: "oc-login" }, el("div", { class: "card" }, el("span", { class: "brand" }, brandMark(), "ServeFlow Owner Control Centre"), ...children))); }

function signIn() {
  const { form } = buildForm({
    idPrefix: "login", submitLabel: "Sign in", values: {},
    fields: [{ name: "email", label: "Email", type: "email", required: true, autocomplete: "username" }, { name: "password", label: "Password", type: "password", required: true, autocomplete: "current-password" }],
    submit: (v) => login(v.email.trim(), v.password), onSuccess: () => boot(),
  });
  center(el("h1", {}, "Sign in"), el("p", { class: "muted" }, "Platform owner only."), form);
}
function forbidden(user) {
  center(el("h1", {}, "No owner access"), el("p", { class: "muted" }, `${user?.email ?? "This account"} isn't a ServeFlow platform owner. Restaurant staff use the restaurant dashboard.`),
    el("button", { class: "btn btn--secondary", type: "button", onclick: async () => { await logout().catch(() => {}); signIn(); } }, "Sign out"));
}

/* ---------- boot ---------- */
async function boot() {
  app.replaceChildren(el("p", { class: "oc-boot muted", role: "status" }, "Loading…"));
  try {
    const me = await platform.me();
    return shell({ user: me.user, mode: "live" });
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return signIn();
    if (err instanceof ApiError && err.status === 403) return forbidden((await getSession().catch(() => null))?.user);
    if (isNotAvailable(err)) {
      // The owner API isn't installed. Identity comes from the existing session; no owner data can load.
      const session = await getSession().catch(() => null);
      return session ? shell({ user: session.user, mode: "no-owner-api" }) : signIn();
    }
    center(errorPanel(err, { retry: boot }));
  }
}
window.addEventListener("owner:unauthenticated", () => signIn());

/* ---------- shell ---------- */
let current = null;
function shell({ user, mode }) {
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email;
  const nav = el("nav", { "aria-label": "Owner navigation" }, ...GROUPS.flatMap((group) => [
    el("p", { class: "oc-group" }, group),
    ...ROUTES.filter((r) => r.group === group).map((r) => el("a", { class: "oc-link", href: `#/${r.id}`, "data-route": r.id }, icon(r.icon), r.label)),
  ]));
  const menu = el("div", { class: "oc-menu", hidden: true }, el("a", { href: "#/settings", onclick: () => toggleMenu(false) }, icon("settings"), "Account & security"),
    el("button", { type: "button", onclick: async () => { await logout().catch(() => {}); signIn(); } }, icon("logout"), "Sign out"));
  const meButton = el("button", { class: "btn btn--ghost", type: "button", "aria-haspopup": "true", "aria-expanded": "false", "aria-label": `Account menu for ${name}`, onclick: () => toggleMenu(menu.hidden) }, icon("chevron-down"));
  const me = el("div", { class: "oc-me" }, avatar(name), el("div", { class: "oc-me__text" }, el("strong", {}, name), el("span", {}, mode === "live" ? "Platform owner" : "Signed in")), meButton, menu);
  const side = el("aside", { class: "oc-side", id: "oc-side", "data-open": "false" },
    el("a", { class: "oc-brand", href: "#/overview" }, brandMark(), el("span", {}, "ServeFlow", el("small", {}, "Owner Control Centre"))), nav, el("div", { class: "oc-spacer" }), me);
  const scrim = el("div", { class: "oc-scrim", hidden: true });
  const crumbs = el("div", { class: "oc-crumbs", "aria-label": "Breadcrumb" });
  const menuBtn = el("button", { class: "btn btn--ghost oc-menu-btn", type: "button", "aria-label": "Open navigation", "aria-expanded": "false", "aria-controls": "oc-side" }, icon("menu"));
  const setDrawer = (open) => { side.dataset.open = String(open); scrim.hidden = !open; menuBtn.setAttribute("aria-expanded", String(open)); if (!open) menuBtn.focus({ preventScroll: true }); };
  menuBtn.addEventListener("click", () => setDrawer(true));
  scrim.addEventListener("click", () => setDrawer(false));
  const search = el("form", { class: "oc-search", role: "search", onsubmit: (e) => { e.preventDefault(); const q = new FormData(e.target).get("q").toString().trim(); location.hash = `#/customers${q ? `?search=${encodeURIComponent(q)}` : ""}`; } },
    icon("search"), el("input", { class: "input", type: "search", name: "q", "aria-label": "Search restaurants", placeholder: "Search restaurants, admins…" }));
  const bell = createBell({ onOpenLink: (link) => { if (link === location.hash) route(); else location.hash = link; } });
  const create = el("button", { class: "btn btn--primary", type: "button", "aria-label": "New restaurant" }, icon("plus"), el("span", { class: "oc-btn-label" }, "New restaurant"));
  create.addEventListener("click", async () => {
    if (!(await pages.newRestaurant())) return;
    if (location.hash.startsWith("#/customers")) route(); else location.hash = "#/customers";
  });
  function toggleMenu(open) { menu.hidden = !open; meButton.setAttribute("aria-expanded", String(open)); }
  document.addEventListener("click", (e) => { if (!menu.hidden && !me.contains(e.target)) toggleMenu(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if (!menu.hidden) { toggleMenu(false); meButton.focus(); } else if (side.dataset.open === "true") setDrawer(false); } });
  const banner = mode === "no-owner-api"
    ? el("div", { class: "alert alert--warning oc-mode", role: "status" }, icon("alert"), el("span", {}, "This server has no owner API yet (/api/v1/platform/). You're signed in, but no ServeFlow business data can load, and nothing here is sample data. Each page names the endpoint it is waiting for."))
    : null;
  const main = el("main", { class: "oc-main", id: "main", tabindex: "-1" });
  app.replaceChildren(el("div", { class: "oc-shell" }, side, scrim,
    el("div", {}, el("header", { class: "oc-top" }, menuBtn, crumbs, search, bell.node, create), banner, main)));

  function route() {
    const { route: r, params } = parseHash(location.hash);
    current?.stop?.();
    crumbs.replaceChildren(el("span", {}, r.group), el("span", { "aria-hidden": "true" }, "›"), el("strong", { "aria-current": "page" }, r.label));
    document.title = `${r.label} · ServeFlow Owner Control Centre`;
    bell.applyTitle();
    for (const a of nav.querySelectorAll("a")) {
      if (a.dataset.route === r.id) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    }
    current = r.render({ params, user, mode });
    main.replaceChildren(current.node);
    main.classList.remove("oc-enter");
    void main.offsetWidth; // restart the short page-in animation on every route change
    main.classList.add("oc-enter");
    if (side.dataset.open === "true") { side.dataset.open = "false"; scrim.hidden = true; menuBtn.setAttribute("aria-expanded", "false"); }
    main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
  window.removeEventListener("hashchange", window.__ocRoute ?? (() => {}));
  window.__ocRoute = route;
  window.addEventListener("hashchange", route);
  route();
}

if (typeof document !== "undefined" && app) boot();
