/* Boots every dashboard page: loads the session, redirects to sign-in when needed,
 * picks the active restaurant and renders the role-aware navigation. */
import { ApiError, api } from "../../shared/js/api.js";
import { getSession, logout } from "../../shared/js/auth.js";
import { closeOnBackdrop, el, emptyState, icon, setBusy, toast } from "../../shared/js/ui.js";
import { SUBSCRIPTION_ENDED_EVENT, subscriptionEndedBanner } from "../../shared/js/subscription.js";
import { formDialog } from "./form-dialog.js";
import { showPlanBanner } from "./plan-banner.js";
import { ROLE_LABEL, displayName, hasRole, pickMembership } from "./session.js";

const STORAGE_KEY = "serveflow.restaurant"; // the chosen restaurant slug only; never credentials
// `primary` items are the bottom tabs on a phone; everything else sits behind "More". On a desktop all of them are in the sidebar.
const NAV = [
  { label: "Overview", href: "index.html", icon: "layout-dashboard", minRole: "STAFF", primary: true },
  { label: "Orders", href: "orders.html", icon: "inbox", minRole: "STAFF", primary: true },
  { label: "Menu", href: "menu.html", icon: "book", minRole: "STAFF", primary: true },
  { label: "Reviews", href: "reviews.html", icon: "star", minRole: "STAFF" },
  { label: "Team", href: "team.html", icon: "users", minRole: "MANAGER" },
  { label: "Billing", href: "billing.html", icon: "credit-card", minRole: "OWNER" },
  { label: "Settings", href: "settings.html", icon: "settings", minRole: "STAFF" },
];

const initials = (name) => String(name ?? "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "SF";

const readStoredSlug = () => {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
};
const storeSlug = (slug) => {
  try {
    localStorage.setItem(STORAGE_KEY, slug);
  } catch {
    /* storage unavailable: the first restaurant is used */
  }
};

/** Remember which restaurant to open next (the slug only; never credentials). */
export const setActiveRestaurant = (slug) => storeSlug(slug);

export function loginUrl(next, { expired = false } = {}) {
  const params = new URLSearchParams();
  if (next) params.set("next", next);
  if (expired) params.set("expired", "1");
  const query = params.toString();
  return `login.html${query ? `?${query}` : ""}`;
}

/** Sends the user to sign-in when the API says the session is gone. Returns true if it did. */
export function handleSessionExpiry(err, href) {
  if (err instanceof ApiError && err.status === 401) {
    location.replace(loginUrl(href, { expired: true }));
    return true;
  }
  return false;
}

function showBootMessage(node) {
  const boot = document.getElementById("boot");
  boot.removeAttribute("role");
  boot.replaceChildren(node);
}

async function signOut(button) {
  setBusy(button, true);
  try {
    await logout();
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 401)) {
      setBusy(button, false);
      toast(err instanceof ApiError ? err.message : "Could not sign out.", { type: "error" });
      return;
    }
  }
  location.replace("login.html");
}

async function changePasswordFlow() {
  const saved = await formDialog({
    title: "Change password",
    submitLabel: "Change password",
    fields: [
      { name: "current_password", label: "Current password", type: "password", required: true, autocomplete: "current-password" },
      {
        name: "new_password", label: "New password", type: "password", required: true, autocomplete: "new-password",
        hint: "At least 8 characters. Avoid common passwords and all-number passwords.",
      },
      { name: "confirm", label: "Confirm new password", type: "password", required: true, autocomplete: "new-password" },
    ],
    validateForm: (v) => (v.confirm !== v.new_password ? { confirm: "The passwords don't match." } : {}),
    submit: (v) => api.post("/auth/password/", { current_password: v.current_password, new_password: v.new_password }),
  });
  if (saved) toast("Password changed.", { type: "success" });
}

function buildAccountSheet(session, memberships, active) {
  const form = el("form", { method: "dialog", class: "dialog__panel" },
    el("h2", { id: "account-title" }, "Account"),
    el("p", {}, el("strong", {}, displayName(session.user)), el("br"), el("span", { class: "muted" }, session.user.email)),
  );

  if (memberships.length > 1) {
    const group = el("fieldset", { class: "field", style: "border:0;padding:0;margin:0" },
      el("legend", { class: "label" }, "Restaurant"),
    );
    const choices = el("div", { class: "choice-group" });
    for (const m of memberships) {
      choices.append(
        el("label", { class: "choice" },
          el("input", {
            type: "radio",
            name: "restaurant",
            value: m.restaurant.slug,
            checked: m.restaurant.slug === active.restaurant.slug,
            onchange: () => {
              storeSlug(m.restaurant.slug);
              location.reload();
            },
          }),
          el("span", { class: "choice__body" },
            el("span", {}, el("strong", {}, m.restaurant.name), el("small", {}, ROLE_LABEL[m.role] ?? m.role)),
          ),
        ),
      );
    }
    group.append(choices);
    form.append(group);
  }

  if (session.can_create_restaurant) {
    form.append(el("a", { class: "btn btn--secondary btn--block", href: "create-restaurant.html" }, icon("plus"), "Create another restaurant"));
  }
  form.append(el("button", {
    class: "btn btn--secondary btn--block", type: "button",
    onclick: () => { dialog.close(); changePasswordFlow(); },
  }, icon("lock"), "Change password"));
  const out = el("button", { class: "btn btn--secondary btn--block", type: "button" }, icon("logout"), "Sign out");
  out.addEventListener("click", () => signOut(out));
  form.append(out, el("div", { class: "dialog__footer" }, el("button", { class: "btn btn--ghost", value: "cancel" }, "Close")));

  const dialog = el("dialog", { class: "dialog", "aria-labelledby": "account-title" }, form);
  closeOnBackdrop(dialog);
  document.body.append(dialog);
  return dialog;
}

function renderNav(nav, href, role, onAccount, restaurant) {
  const items = NAV.filter((item) => hasRole(role, item.minRole));
  const more = items.filter((item) => !item.primary);

  // Phones: a sheet with the less-used pages and the account. Desktops never see the button (CSS).
  const sheet = el("dialog", { class: "dialog", "aria-label": "More" },
    el("div", { class: "dialog__panel" },
      el("nav", { class: "sheet-links", "aria-label": "More pages" },
        ...more.map((item) => el("a", { class: "sheet-link", href: item.href, "aria-current": item.href === href ? "page" : null }, icon(item.icon), el("span", {}, item.label), icon("chevron-right"))),
        el("button", { class: "sheet-link", type: "button", onclick: () => { sheet.close(); onAccount(); } }, icon("user"), el("span", {}, "Account"), icon("chevron-right")))));
  closeOnBackdrop(sheet);
  const moreCurrent = more.some((item) => item.href === href);
  const moreButton = el("button", { class: "nav__item nav__more", type: "button", "aria-haspopup": "dialog", "aria-current": moreCurrent ? "page" : null, onclick: () => sheet.showModal() },
    icon("menu"), "More");

  nav.replaceChildren(
    el("a", { class: "brand nav__brand", href: "index.html" },
      el("span", { class: "brand__mark" }, icon("leaf")), "ServeFlow"),
    restaurant ? el("div", { class: "nav__workspace" },
      el("span", { class: "avatar" }, initials(restaurant.name)),
      el("span", { class: "nav__workspace-text" }, el("strong", {}, restaurant.name), el("small", {}, String(role ?? "").toLowerCase()))) : null,
    ...items.map((item) =>
      el("a", { class: `nav__item${item.primary ? "" : " nav__item--secondary"}`, href: item.href, "aria-current": item.href === href ? "page" : null },
        icon(item.icon), item.label),
    ),
    moreButton,
    el("span", { class: "nav__spacer" }),
    el("button", { class: "nav__item nav__item--secondary", type: "button", onclick: onAccount }, icon("user"), "Account"),
    sheet,
  );
}

/**
 * @param {{href: string, minRole?: string}} options  href is this page's file name.
 * @returns the page context, or null when the page is redirecting or showing an error.
 */
export async function bootDashboard({ href, minRole = "STAFF" }) {
  let session;
  try {
    session = await getSession();
  } catch (err) {
    const retry = el("button", { class: "btn btn--secondary", type: "button", onclick: () => location.reload() },
      icon("refresh"), "Try again");
    showBootMessage(emptyState({
      iconName: "alert",
      title: "Can't load your account",
      text: err instanceof ApiError ? err.message : "Something went wrong.",
      action: retry,
    }));
    return null;
  }
  if (!session) {
    location.replace(loginUrl(href));
    return null;
  }

  const { memberships } = session;
  if (memberships.length === 0) {
    const out = el("button", { class: "btn btn--secondary", type: "button" }, icon("logout"), "Sign out");
    out.addEventListener("click", () => signOut(out));
    const canCreate = session.can_create_restaurant;
    showBootMessage(emptyState({
      iconName: canCreate ? "store" : "lock",
      title: canCreate ? "Set up your restaurant" : "No restaurant access",
      text: canCreate
        ? "Create your restaurant to start building your menu and adding your team."
        : "Your account isn't linked to an active restaurant. Ask the restaurant owner to add you.",
      action: el("div", { class: "row" },
        canCreate ? el("a", { class: "btn btn--primary", href: "create-restaurant.html" }, icon("plus"), "Create your restaurant") : null,
        out),
    }));
    return null;
  }

  const membership = pickMembership(memberships, readStoredSlug());
  storeSlug(membership.restaurant.slug);

  const sheet = buildAccountSheet(session, memberships, membership);
  renderNav(document.getElementById("nav"), href, membership.role, () => sheet.showModal(), membership.restaurant);
  document.getElementById("restaurant-name").textContent = membership.restaurant.name;
  document.getElementById("boot").hidden = true;
  document.getElementById("app").hidden = false;
  if (href !== "billing.html") showPlanBanner(membership.restaurant.slug, membership.role);
  window.addEventListener(SUBSCRIPTION_ENDED_EVENT, () => {
    if (!document.getElementById("subscription-ended")) document.getElementById("main").prepend(subscriptionEndedBanner());
  });

  return {
    session,
    restaurant: membership.restaurant,
    role: membership.role,
    allowed: hasRole(membership.role, minRole),
  };
}
