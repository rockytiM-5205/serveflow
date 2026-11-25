/* Who is signed in, shown so nobody has to wonder: a round badge with their initial and their name. */
import { api } from "../../shared/js/api.js";
import { el } from "../../shared/js/ui.js";
import { fullName } from "./account-helpers.js";
import { forgetCustomer } from "./account-link.js";

/** The name to show in small spaces: the first name, or the start of the email address. */
export const firstName = (me) => String(me?.first_name || String(me?.email ?? "").split("@")[0] || "Account").trim();
export const nameOf = (me) => fullName(me) || firstName(me);

/** The round badge with the person's initial. */
export const userAvatar = (me, large = false) => el("span", { class: `user-avatar${large ? " user-avatar--lg" : ""}`, "aria-hidden": "true" }, (firstName(me)[0] ?? "A").toUpperCase());

export async function signOut() {
  try { await api.post("/customers/logout/"); } catch { /* already signed out */ }
  forgetCustomer();
}
