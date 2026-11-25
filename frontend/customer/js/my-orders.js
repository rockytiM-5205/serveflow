/* Your orders at every restaurant: what is happening now, and what you have had before. */
import { ApiError, api } from "../../shared/js/api.js";
import { el, emptyState, formatMoney, icon } from "../../shared/js/ui.js";
import { STATUS_WORDS, orderSummary, trackHref } from "./account-helpers.js";
import { nameOf, signOut, userAvatar } from "./identity.js";
import { pickupText } from "./order-view.js";
import { mountSiteNav } from "./site-nav.js";

mountSiteNav({ slug: null });

const content = document.getElementById("content");

const when = (iso) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

function card(row) {
  const note = row.can_review ? "Leave a review" : row.reviewed ? "Reviewed" : "";
  return el("a", { class: "card card__pad stack rest-card order-row", href: trackHref(row) },
    el("div", { class: "rest-card__title" }, el("h3", {}, row.restaurant.name), el("span", { class: "badge", "data-status": row.status }, STATUS_WORDS[row.status] ?? row.status)),
    el("div", { class: "rest-card__meta" },
      el("span", {}, row.reference), el("span", {}, orderSummary(row)),
      row.pickup_at && row.active ? el("span", {}, `Collect ${pickupText(row.pickup_at)}`) : null,
      el("span", {}, when(row.created_at))),
    el("div", { class: "row" }, el("strong", { class: "price" }, formatMoney(row.total, row.currency)),
      note ? el("span", { class: "muted" }, note) : null));
}

async function list(path) {
  const rows = [];
  let nextPath = path;
  while (nextPath) {
    const body = await api.get(nextPath);
    rows.push(...body.results);
    const link = body.next ? new URL(body.next, location.href) : null;
    nextPath = link ? link.pathname.replace(/^\/api\/v1/, "") + link.search : null;
    if (rows.length >= 50) break; // plenty for one screen; older orders load on request
  }
  return { rows, more: Boolean(nextPath) };
}

function signOutButton() {
  const button = el("button", { class: "btn btn--secondary btn--sm", type: "button" }, icon("logout"), "Sign out");
  button.addEventListener("click", async () => { await signOut(); location.assign("marketplace.html"); });
  return button;
}

async function main() {
  let me;
  try {
    me = await api.get("/customers/me/");
  } catch (err) {
    if (err instanceof ApiError && [401, 403].includes(err.status)) {
      content.replaceChildren(emptyState({
        iconName: "user", title: "Sign in to see your orders",
        text: "Your orders from every restaurant are kept in your account. You can still order as a guest any time.",
        action: el("a", { class: "btn btn--primary", href: "account.html?next=my-orders.html" }, "Sign in or create an account"),
      }));
      return;
    }
    content.replaceChildren(el("div", { class: "alert alert--danger", role: "alert" }, err instanceof ApiError ? err.message : "Something went wrong."));
    return;
  }
  const active = el("div", { class: "stack" });
  const past = el("div", { class: "stack" });
  content.replaceChildren(el("div", { class: "stack" },
    el("section", { class: "card profile-card", "aria-label": "Your account" },
      userAvatar(me, true),
      el("div", { class: "profile-card__who" }, el("strong", {}, nameOf(me)), el("span", { class: "signed-in-dot" }, "Signed in"), me.email ? el("span", { class: "profile-card__email" }, me.email) : null),
      signOutButton()),
    el("h1", {}, "My orders"),
    el("section", { class: "stack", "aria-labelledby": "act-h" }, el("h2", { id: "act-h" }, "In progress"), active),
    el("section", { class: "stack", "aria-labelledby": "past-h" }, el("h2", { id: "past-h" }, "Earlier orders"), past)));

  async function load() {
    active.replaceChildren(el("div", { class: "skeleton skeleton--line", style: "height:4rem", "aria-hidden": "true" }));
    past.replaceChildren(el("div", { class: "skeleton skeleton--line", style: "height:4rem", "aria-hidden": "true" }));
    try {
      const [now, all] = await Promise.all([list("/customers/orders/?active=1"), list("/customers/orders/")]);
      active.replaceChildren(...(now.rows.length ? now.rows.map(card) : [el("p", { class: "muted" }, "Nothing in progress.")]));
      const earlier = all.rows.filter((r) => !r.active);
      past.replaceChildren(...(earlier.length ? earlier.map(card) : [el("p", { class: "muted" }, "No earlier orders yet.")]),
        ...(all.more ? [el("p", { class: "muted" }, "Showing your most recent orders.")] : []));
    } catch (err) {
      const retry = el("button", { class: "btn btn--secondary", type: "button", onclick: load }, icon("refresh"), "Try again");
      active.replaceChildren(emptyState({ iconName: "alert", title: "Couldn't load your orders", text: err instanceof ApiError ? err.message : "Something went wrong.", action: retry }));
      past.replaceChildren();
    }
  }
  await load();
}

main();
