/* Sign in, create an account, and manage it. Ordering as a guest always still works: an account only keeps your order history. */
import { ApiError, api } from "../../shared/js/api.js";
import { buildForm } from "../../shared/js/form-builder.js";
import { el, toast } from "../../shared/js/ui.js";
import { RETURN_KEY, RETURN_MAX_AGE_MS, fullName, isOrderReturn, safeNext } from "./account-helpers.js";
import { mountSiteNav } from "./site-nav.js";

mountSiteNav({ slug: null });

const content = document.getElementById("content");
const next = safeNext(new URLSearchParams(location.search).get("next"));

/** After signing in: back to the order the customer was about to review (remembered in this tab for a short while), else the page asked for. */
function returnTarget() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(RETURN_KEY) ?? "null");
    sessionStorage.removeItem(RETURN_KEY);
    if (saved && isOrderReturn(saved.url) && Date.now() - saved.at < RETURN_MAX_AGE_MS) return saved.url;
  } catch { /* no remembered page */ }
  return null;
}
const done = () => { location.href = returnTarget() ?? next; };

function signedOut() {
  const login = buildForm({
    idPrefix: "login", submitLabel: "Sign in",
    fields: [
      { name: "email", label: "Email", type: "email", required: true, autocomplete: "email", maxlength: 254 },
      { name: "password", label: "Password", type: "password", required: true, autocomplete: "current-password" },
    ],
    submit: (v) => api.post("/customers/login/", { email: v.email.trim(), password: v.password }),
    onSuccess: done,
  });
  const create = buildForm({
    idPrefix: "reg", submitLabel: "Create account",
    fields: [
      { name: "first_name", label: "First name", type: "text", required: true, autocomplete: "given-name", maxlength: 60 },
      { name: "last_name", label: "Last name (optional)", type: "text", autocomplete: "family-name", maxlength: 60 },
      { name: "email", label: "Email", type: "email", required: true, autocomplete: "email", maxlength: 254 },
      { name: "phone", label: "Phone (optional)", type: "tel", autocomplete: "tel", maxlength: 20, hint: "Used to fill in your orders. Restaurants only see it on orders you place." },
      { name: "password", label: "Password", type: "password", required: true, autocomplete: "new-password", hint: "At least 8 characters. Not a common password." },
    ],
    submit: (v) => api.post("/customers/register/", { ...v, email: v.email.trim(), first_name: v.first_name.trim(), last_name: v.last_name.trim(), phone: v.phone.trim() }),
    onSuccess: done,
  });
  content.replaceChildren(
    el("div", { class: "stack" },
      el("h1", {}, "Your ServeFlow account"),
      el("p", { class: "muted" }, "One account works at every restaurant and keeps your order history. You never need one: you can always order as a guest."),
      el("section", { class: "card card__pad stack", "aria-labelledby": "in-h" }, el("h2", { id: "in-h" }, "Sign in"), login.form),
      el("section", { class: "card card__pad stack", "aria-labelledby": "up-h" }, el("h2", { id: "up-h" }, "Create an account"), create.form),
      el("p", {}, el("a", { href: "marketplace.html" }, "Browse restaurants"))));
}

function signedIn(me) {
  const profile = buildForm({
    idPrefix: "me", submitLabel: "Save",
    fields: [
      { name: "first_name", label: "First name", type: "text", required: true, maxlength: 60 },
      { name: "last_name", label: "Last name", type: "text", maxlength: 60 },
      { name: "phone", label: "Phone", type: "tel", maxlength: 20 },
    ],
    values: me,
    submit: (v) => api.patch("/customers/me/", { first_name: v.first_name.trim(), last_name: v.last_name.trim(), phone: v.phone.trim() }),
    onSuccess: () => toast("Saved.", { type: "success" }),
  });
  const password = buildForm({
    idPrefix: "pw", submitLabel: "Change password",
    fields: [
      { name: "current_password", label: "Current password", type: "password", required: true, autocomplete: "current-password" },
      { name: "new_password", label: "New password", type: "password", required: true, autocomplete: "new-password", hint: "At least 8 characters. Other devices are signed out." },
    ],
    submit: (v) => api.post("/customers/password/", v),
    onSuccess: () => { toast("Password changed.", { type: "success" }); password.form.reset(); },
  });
  const signOut = el("button", { class: "btn btn--secondary", type: "button" }, "Sign out");
  signOut.addEventListener("click", async () => {
    try { await api.post("/customers/logout/"); } catch { /* signed out already */ }
    location.href = "marketplace.html";
  });
  content.replaceChildren(
    el("div", { class: "stack" },
      el("h1", {}, fullName(me) || "Your account"),
      el("p", { class: "muted" }, me.email),
      el("div", { class: "row" }, el("a", { class: "btn btn--primary", href: "my-orders.html" }, "My orders"), el("a", { class: "btn btn--ghost", href: "marketplace.html" }, "Find restaurants"), signOut),
      el("section", { class: "card card__pad stack", "aria-labelledby": "pf-h" }, el("h2", { id: "pf-h" }, "Your details"), profile.form),
      el("section", { class: "card card__pad stack", "aria-labelledby": "pw-h" }, el("h2", { id: "pw-h" }, "Password"), password.form)));
}

async function main() {
  try { await api.get("/auth/csrf/"); } catch { /* the form will say if sign-in can't work */ }
  try {
    signedIn(await api.get("/customers/me/"));
  } catch (err) {
    if (err instanceof ApiError && [401, 403].includes(err.status)) signedOut();
    else content.replaceChildren(el("div", { class: "alert alert--danger", role: "alert" }, err instanceof ApiError ? err.message : "Something went wrong."));
  }
}

main();
