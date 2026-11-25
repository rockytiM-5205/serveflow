/* One tidy menu in the header of every customer page: this restaurant (Menu, About, Track order), All restaurants, and the
 * customer's account. On a wide screen the links sit in the header; on a phone they fold into one Menu button. */
import { el, icon } from "../../shared/js/ui.js";
import { currentCustomer } from "./account-link.js";
import { firstName, nameOf, signOut, userAvatar } from "./identity.js";
import { loadLastOrder } from "./cart.js";
import { parseSlug } from "./helpers.js";
import { mountInstallBanner } from "../../shared/js/install-banner.js";
import { canInstall, isIos, isStandalone, onInstallChange, promptInstall, registerServiceWorker, useRestaurantManifest, watchInstall } from "../../shared/js/pwa.js";

/** "/customer/menu.html" -> "menu"; the bare folder is the restaurant's About page. */
export function pageName(pathname) {
  const file = String(pathname ?? "").split("/").pop().replace(/\.html$/, "");
  return file || "index";
}

const CURRENT = { marketplace: "restaurants", index: "about", menu: "menu", checkout: "menu", order: "track", "my-orders": "orders", account: "signin" };

/** The links to show. Pure: no page, no network. */
export function navItems({ page, slug = null, trackToken = null, customer = null, here = "" } = {}) {
  const q = slug ? `?r=${encodeURIComponent(slug)}` : "";
  const items = [];
  if (slug) {
    items.push({ id: "menu", label: "Menu", href: `menu.html${q}`, icon: "utensils" });
    items.push({ id: "about", label: "About", href: `index.html${q}`, icon: "store" });
    if (trackToken) items.push({ id: "track", label: "Track order", href: `order.html${q}#${trackToken}`, icon: "clock" });
  }
  items.push({ id: "restaurants", label: "All restaurants", href: "marketplace.html", icon: "search" });
  items.push(customer
    ? { id: "orders", label: "My orders", href: "my-orders.html", icon: "list", title: customer.first_name ? `Signed in as ${customer.first_name}` : undefined }
    : { id: "signin", label: "Sign in", href: `account.html${here}`, icon: "user", account: true });
  const current = CURRENT[page];
  return items.map((item) => ({ ...item, current: item.id === current }));
}

/** Put the menu in the header. Safe to call more than once; does nothing on a page without a header. */
export function mountSiteNav({ slug = parseSlug(location.search) } = {}) {
  const bar = document.querySelector(".topbar__inner");
  if (!bar) return null;
  let host = document.getElementById("site-nav");
  if (!host) {
    host = el("div", { id: "site-nav" });
    bar.append(host);
  }
  if (host.getAttribute("data-mounted")) return host;
  host.setAttribute("data-mounted", "true");

  const page = pageName(location.pathname);
  // Never put an order link in an address: a page with a # (the order page) just offers the plain sign-in page.
  const here = location.hash ? "" : `?next=${encodeURIComponent(location.pathname.split("/").pop() + location.search)}`;
  const trackToken = slug ? loadLastOrder(slug) : null;

  // Installable like an app: on a restaurant's page "Add to Home Screen" installs that restaurant; elsewhere it installs ServeFlow.
  watchInstall();
  registerServiceWorker("sw.js", "./");
  if (slug) useRestaurantManifest(slug);
  mountInstallBanner({
    message: slug ? "Add this restaurant to your home screen for faster ordering." : "Install ServeFlow on your phone for faster ordering.",
  });

  const nav = el("nav", { class: "site-nav", "aria-label": "Site", "data-open": "false" });
  const list = el("ul", { class: "site-nav__list", id: "site-nav-list" });
  const toggle = el("button", {
    class: "btn btn--ghost btn--sm site-nav__toggle", type: "button", "aria-expanded": "false", "aria-controls": "site-nav-list",
  }, icon("menu"), el("span", {}, "Menu"));
  const account = el("div", { class: "site-nav__account" }); // the signed-in customer: a badge with their initial and name
  nav.append(account, toggle, list);
  host.append(nav);

  const setOpen = (open) => {
    nav.setAttribute("data-open", String(open));
    toggle.setAttribute("aria-expanded", String(open));
  };
  const isOpen = () => nav.getAttribute("data-open") === "true";
  toggle.addEventListener("click", () => setOpen(!isOpen()));
  let setPop = () => {};
  let popOpen = false;
  document.addEventListener("keydown", (event) => { if (event.key !== "Escape") return; if (isOpen()) { setOpen(false); toggle.focus?.(); } if (popOpen) setPop(false); });
  document.addEventListener("click", (event) => {
    if (isOpen() && !event.target?.closest?.(".site-nav")) setOpen(false);
    if (popOpen && !event.target?.closest?.(".site-nav__account")) setPop(false);
  });

  let signedIn = null;
  const installRow = () => {
    if (canInstall()) {
      const button = el("button", { class: "site-nav__link", type: "button" }, icon("phone"), slug ? "Install this restaurant's app" : "Install the app");
      button.addEventListener("click", () => { setOpen(false); promptInstall(); });
      return el("li", {}, button);
    }
    if (isIos() && !isStandalone()) return el("li", { class: "site-nav__hint" }, "To install: tap Share, then Add to Home Screen.");
    return null;
  };
  const drawAccount = () => {
    if (!signedIn) { account.replaceChildren(); return; }
    const chip = el("button", { class: "account-chip", type: "button", "aria-haspopup": "true", "aria-expanded": "false", "aria-label": `Signed in as ${nameOf(signedIn)}. Open account menu` },
      userAvatar(signedIn), el("span", { class: "account-chip__name" }, firstName(signedIn)), icon("chevron-down"));
    const out = el("button", { class: "account-pop__link", type: "button" }, icon("logout"), "Sign out");
    const pop = el("div", { class: "account-pop", role: "menu", hidden: true },
      el("div", { class: "account-pop__who" }, userAvatar(signedIn, true),
        el("div", {}, el("strong", {}, nameOf(signedIn)), el("small", {}, signedIn.email ? `Signed in · ${signedIn.email}` : "Signed in"))),
      el("a", { class: "account-pop__link", href: "my-orders.html", role: "menuitem" }, icon("list"), "My orders"),
      el("a", { class: "account-pop__link", href: "account.html", role: "menuitem" }, icon("user"), "Your account"),
      out);
    setPop = (open) => { popOpen = open; if (open) { pop.removeAttribute("hidden"); setOpen(false); } else pop.setAttribute("hidden", ""); chip.setAttribute("aria-expanded", String(open)); };
    chip.addEventListener("click", () => setPop(!popOpen));
    out.addEventListener("click", async () => { await signOut(); if (["my-orders", "account"].includes(page)) location.assign("marketplace.html"); else location.reload(); });
    account.replaceChildren(chip, pop);
  };
  const draw = () => {
    // "My orders" lives in the account menu once someone is signed in
    list.replaceChildren(...navItems({ page, slug, trackToken, customer: signedIn, here }).filter((item) => !(signedIn && item.id === "orders")).map((item) =>
      el("li", {}, el("a", {
        class: `site-nav__link${item.account ? " site-nav__link--account" : ""}`, href: item.href, title: item.title,
        "aria-current": item.current ? "page" : null,
      }, icon(item.icon), item.label))), ...[installRow()].filter(Boolean));
  };
  draw();
  onInstallChange(draw);
  currentCustomer().then((me) => { if (me) { signedIn = me; draw(); drawAccount(); } });
  return host;
}
