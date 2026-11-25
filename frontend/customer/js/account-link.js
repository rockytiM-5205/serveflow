/* A small "Sign in" / "My orders" link in the page header. Looks the customer up quietly; no account means a plain Sign in link. */
import { api } from "../../shared/js/api.js";
import { el } from "../../shared/js/ui.js";

let cached = null;

/** The signed-in customer, or null. One request per page. */
export function currentCustomer() {
  cached ??= api.get("/customers/me/").catch(() => null);
  return cached;
}

/** Forget the remembered answer (after signing in or out without leaving the page, and in tests). */
export function forgetCustomer() {
  cached = null;
}

export async function mountAccountLink() {
  const bar = document.querySelector(".topbar__inner");
  if (!bar) return;
  // Never put an order link in an address: a page with a # (the order page) just offers the plain sign-in page.
  const here = location.hash ? "" : `?next=${encodeURIComponent(location.pathname.split("/").pop() + location.search)}`;
  const link = el("a", { class: "btn btn--ghost btn--sm account-link", href: `account.html${here}` }, "Sign in");
  bar.append(link);
  const me = await currentCustomer();
  if (me) {
    link.textContent = `My orders \u00b7 ${me.first_name}`;
    link.href = "my-orders.html";
  }
}
