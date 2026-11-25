import { ApiError, api } from "../../shared/js/api.js";
import { RETURN_KEY, isOrderReturn } from "./account-helpers.js";
import { confirmDialog, el, emptyState, formatMoney, icon, setBusy, toast } from "../../shared/js/ui.js";
import { liveBadge, startLive } from "../../shared/js/live.js";
import { loadLastOrder } from "./cart.js";
import { DETAIL, HEADLINE, isTerminal, paymentWords, pickupText, tokenFromHash } from "./order-view.js";
import { orderProgress } from "./order-scene.js";
import { freeUntilText, lateFeeStatusText, lateFeeText } from "../../shared/js/late-policy.js";
import { currentCustomer } from "./account-link.js";
import { mountSiteNav } from "./site-nav.js";
import { RATING_WORDS, readRating, starText } from "../../shared/js/review-helpers.js";
import { parseSlug } from "./helpers.js";

mountSiteNav(); // the one tidy menu in the header, once

const STATUS_WORDS = { SERVING: "Preparing", READY_FOR_PICKUP: "Ready" };

const content = document.getElementById("content");
const live = document.getElementById("live");
const POLL_MS = 5000;

const slugParam = parseSlug(location.search);
const token = tokenFromHash(location.hash) ?? (slugParam ? loadLastOrder(slugParam) : null);

const show = (node) => content.replaceChildren(node);
const notFound = () => show(emptyState({
  iconName: "list", title: "We can't find this order",
  text: "The link may be incomplete or no longer valid. Check it with the restaurant.",
  action: slugParam ? el("a", { class: "btn btn--secondary", href: `menu.html?r=${encodeURIComponent(slugParam)}` }, "Back to the menu") : null,
}));

let poller = null;
const badge = liveBadge();
let lastJson = "";
let lastStatus = null;

function render(order) {
  const menuUrl = `menu.html?r=${encodeURIComponent(order.restaurant.slug)}`;
  document.getElementById("brand-name").textContent = order.restaurant.name;
  document.getElementById("brand-link").href = menuUrl;
  document.title = `Order ${order.reference} · ${order.restaurant.name}`;

  const where = order.fulfilment_type === "DINE_IN"
    ? (order.table_number ? `Dine in · Table ${order.table_number}` : "Dine in")
    : `Pickup${order.pickup_at ? ` · ${pickupText(order.pickup_at)}` : ""}`;
  const header = el("section", { class: "card card__pad stack", "aria-labelledby": "order-code" },
    el("p", { class: "eyebrow" }, "Your order"),
    el("h1", { id: "order-code", class: "order-code", "aria-label": `Order reference ${order.reference}` }, order.reference),
    el("p", { class: "muted" }, "Quote this reference when you pay and when you collect."),
    el("h2", { class: "order-headline" }, HEADLINE[order.status] ?? order.status),
    DETAIL[order.status] ? el("p", { class: "muted" }, DETAIL[order.status]) : null,
    el("div", { class: "row" },
      el("span", { class: "badge", "data-status": order.status }, STATUS_WORDS[order.status] ?? order.status.charAt(0) + order.status.slice(1).toLowerCase()),
      el("span", { class: "badge", "data-status": order.payment_status }, paymentWords(order)),
      el("span", { class: "muted" }, where)),
  );

  header.style.position = "relative";
  header.append(badge.root);
  badge.root.classList.add("live--corner");
  badge.root.hidden = isTerminal(order.status);
  const progress = orderProgress(order); // the plate and the green ticks
  const progressCard = el("section", { class: "card card__pad order-progress", "aria-label": "Order progress" }, progress.scene, progress.track);

  const items = el("section", { class: "card card__pad stack", "aria-labelledby": "items-h" },
    el("h2", { id: "items-h" }, "What you ordered"),
    el("ul", { class: "summary-lines" }, ...order.items.map((item) =>
      el("li", {}, el("span", {}, `${item.quantity} × ${item.name}`), el("span", { class: "price" }, formatMoney(item.line_total, order.currency))))),
    Number(order.pickup_fee) > 0
      ? el("div", { class: "summary-lines" }, el("span", {}, "Pickup fee"), el("span", { class: "price" }, formatMoney(order.pickup_fee, order.currency))) : null,
    el("div", { class: "total-row" }, el("span", {}, "Total"), el("strong", { class: "price" }, formatMoney(order.total, order.currency))),
  );

  const actions = el("div", { class: "row" });
  if (order.cancellable) {
    actions.append(el("button", { class: "btn btn--secondary", type: "button", onclick: cancelOrder }, "Cancel order"));
  }
  actions.append(el("a", { class: "btn btn--ghost", href: menuUrl }, "Back to the menu"));

  show(el("div", { class: "stack" }, header, progressCard, order.payment ? paymentCard(order) : null, order.pickup_policy ? latePolicyCard(order) : null, order.can_review ? reviewForm() : order.review ? reviewDone(order.review) : order.review_status === "sign_in" ? reviewSignInPrompt() : null, items, actions, accountSlot()));
}

let savedToAccount = false;

/** Signed-in customers can keep this order in their history. Guests just get a quiet pointer to sign in. */
function accountSlot() {
  const slot = el("section", { class: "card card__pad stack", "aria-live": "polite" });
  currentCustomer().then((me) => {
    if (!me) {
      slot.replaceChildren(el("p", { class: "muted" }, "Want to keep this order in your history? ", el("a", { href: "account.html" }, "Sign in or create an account"), ", then come back to this page."));
      return;
    }
    if (savedToAccount) {
      slot.replaceChildren(el("p", {}, icon("check"), " Saved to your account. ", el("a", { href: "my-orders.html" }, "See all your orders")));
      return;
    }
    const button = el("button", { class: "btn btn--secondary", type: "button" }, "Add to my account");
    button.addEventListener("click", async () => {
      setBusy(button, true);
      try {
        await api.post("/customers/orders/claim/", { token });
        savedToAccount = true;
        toast("Saved to your account.", { type: "success" });
        slot.replaceChildren(el("p", {}, icon("check"), " Saved to your account. ", el("a", { href: "my-orders.html" }, "See all your orders")));
      } catch (err) {
        setBusy(button, false);
        toast(err instanceof ApiError ? err.message : "Couldn't save it. Try again.", { type: "error" });
      }
    });
    slot.replaceChildren(el("p", { class: "muted" }, `Signed in as ${me.first_name}.`), button);
  });
  return slot;
}

/** The late pickup rules this customer accepted, when the free period ends, and any late fee. Nothing here is a surprise. */
function latePolicyCard(order) {
  const policy = order.pickup_policy;
  const money = (v) => formatMoney(v, order.currency);
  const time = (iso) => new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const fee = order.late_fee;
  return el("section", { class: "card card__pad stack", "aria-labelledby": "late-h" },
    el("h2", { id: "late-h" }, "Late pickup policy"),
    fee ? el("p", { class: "alert alert--warning", role: "status" }, `Late fee: ${money(fee.amount)}. ${lateFeeStatusText(fee.status)}.`) : null,
    el("p", {}, freeUntilText(policy, time)),
    el("p", { class: "muted" }, lateFeeText(policy, money)));
}

function reviewDone(review) {
  return el("section", { class: "card card__pad stack", "aria-labelledby": "review-h" },
    el("h2", { id: "review-h" }, "Thanks for your review"),
    el("p", {}, el("span", { class: "stars", "aria-label": `${review.rating} out of 5` }, starText(review.rating)), ` ${RATING_WORDS[review.rating] ?? ""}`),
    review.comment ? el("p", {}, review.comment) : null);
}

/** Only shown for a completed order that hasn't been reviewed. The order's private link is the proof the customer ordered. */
/** Reviews come only from signed-in customers, so every review is from a real order. A visitor who isn't signed in is invited to sign in
 * and is brought back to this order afterwards (remembered in this tab only, never in an address). */
function reviewSignInPrompt() {
  const button = el("button", { class: "btn btn--primary", type: "button" }, icon("user"), "Sign in to review");
  button.addEventListener("click", () => {
    const here = `order.html${location.search}${location.hash}`;
    if (isOrderReturn(here)) { try { sessionStorage.setItem(RETURN_KEY, JSON.stringify({ url: here, at: Date.now() })); } catch { /* the page just won't come back by itself */ } }
    location.href = "account.html";
  });
  return el("section", { class: "card card__pad stack", "aria-labelledby": "review-h" },
    el("h2", { id: "review-h" }, "How was your order?"),
    el("p", { class: "muted" }, "Only signed-in customers can leave reviews, so everyone can trust them. Sign in or create a free account, then come back here to rate this restaurant. You can review each restaurant once."),
    button);
}

function reviewForm() {
  const group = el("div", { class: "star-input__row" });
  for (let n = 5; n >= 1; n -= 1) {
    group.append(el("input", { type: "radio", name: "rating", id: `star-${n}`, value: String(n) }),
      el("label", { for: `star-${n}`, title: `${n} ${n === 1 ? "star" : "stars"}: ${RATING_WORDS[n]}` }, "\u2605", el("span", { class: "sr-only" }, ` ${n} ${n === 1 ? "star" : "stars"}`)));
  }
  const error = el("p", { class: "field__error", role: "alert", hidden: true }, "Choose a rating from 1 to 5 stars.");
  const comment = el("textarea", { class: "textarea", id: "review-comment", name: "comment", rows: "3", maxlength: "1000", placeholder: "Tell others about the food and the service (optional)" });
  const button = el("button", { class: "btn btn--primary", type: "submit" }, "Send review");
  const form = el("form", { class: "stack", novalidate: true },
    el("fieldset", { class: "star-input" }, el("legend", { class: "label" }, "How was your order?"), group, error),
    el("div", { class: "field" }, el("label", { class: "label", for: "review-comment" }, "Your comments"), comment),
    el("p", { class: "hint" }, "Your review shows your first name and initial. You can review each restaurant once, and it can't be changed afterwards."),
    button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const rating = readRating(form.querySelector("input[name=rating]:checked")?.value);
    error.hidden = rating !== null;
    if (rating === null) return;
    setBusy(button, true);
    try {
      apply(await api.post(`/orders/${token}/review/`, { rating, comment: comment.value.trim() }));
      toast("Thanks for your review.", { type: "success" });
    } catch (err) {
      setBusy(button, false);
      toast(err instanceof ApiError ? err.message : "Couldn't send your review. Try again.", { type: "error" });
    }
  });
  return el("section", { class: "card card__pad stack", "aria-labelledby": "review-h" }, el("h2", { id: "review-h" }, "Leave a review"), form);
}

function paymentCard(order) {
  const p = order.payment;
  const copy = (text, label) => el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: async () => {
    try { await navigator.clipboard.writeText(text); toast(`${label} copied.`, { type: "success" }); } catch { toast("Select it and copy it.", { type: "info" }); }
  } }, "Copy");
  const row = (label, value, copyLabel) => [el("dt", {}, label), el("dd", {}, el("span", {}, value), copyLabel ? copy(value, copyLabel) : null)];
  const claimed = order.payment_status === "CLAIMED";
  const button = el("button", { class: "btn btn--primary", type: "button" }, "I've paid");
  button.addEventListener("click", async () => {
    setBusy(button, true);
    try {
      apply(await api.post(`/orders/${token}/paid/`));
      toast("Thanks. The restaurant will check and confirm.", { type: "success" });
    } catch (err) {
      setBusy(button, false);
      toast(err instanceof ApiError ? err.message : "Couldn't send that. Try again.", { type: "error" });
    }
  });
  return el("section", { class: "card card__pad stack", "aria-labelledby": "pay-h" },
    el("h2", { id: "pay-h" }, claimed ? "Payment sent" : "Pay now"),
    el("p", { class: "muted" }, claimed
      ? "Thanks. The restaurant is checking its bank account. It starts preparing your order as soon as it confirms your payment."
      : "Transfer the exact amount to the restaurant's account. Use the reference below as the narration so the restaurant can find your payment. Nothing is prepared until it arrives."),
    el("dl", { class: "pay-list" },
      ...row("Amount", formatMoney(p.amount, p.currency), "Amount"),
      ...row("Bank", p.bank_name),
      ...row("Account name", p.account_name),
      ...row("Account number", p.account_number, "Account number"),
      ...row("Reference", p.reference, "Reference")),
    p.instructions ? el("p", { class: "muted" }, p.instructions) : null,
    claimed ? null : button);
}

async function cancelOrder() {
  const ok = await confirmDialog({
    title: "Cancel this order?", message: "You haven't paid yet and the restaurant hasn't started, so you can still cancel.",
    confirmLabel: "Cancel order", cancelLabel: "Keep order", danger: true,
  });
  if (!ok) return;
  try {
    const order = await api.post(`/orders/${token}/cancel/`);
    toast("Order cancelled.", { type: "success" });
    apply(order);
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      toast("It's too late to cancel: the restaurant has already responded.", { type: "info" });
      await poll().catch(() => {});
    } else {
      toast(err instanceof ApiError ? err.message : "Couldn't cancel. Try again.", { type: "error" });
    }
  }
}

function apply(order) {
  const json = JSON.stringify(order);
  if (json !== lastJson) {
    lastJson = json;
    render(order);
    if (lastStatus !== null && lastStatus !== order.status) live.textContent = HEADLINE[order.status] ?? "";
    lastStatus = order.status;
  }
  if (isTerminal(order.status)) stop();
}

function stop() {
  poller?.stop();
  poller = null;
}

async function poll() {
  try {
    apply(await api.get(`/orders/${token}/`));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      stop();
      notFound();
      return;
    }
    throw err; // the Live badge shows "Reconnecting" after two failures in a row
  }
}

async function main() {
  if (!token) {
    notFound();
    return;
  }
  try {
    apply(await api.get(`/orders/${token}/`));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return notFound();
    show(emptyState({
      iconName: "alert", title: "Couldn't load your order", text: err instanceof ApiError ? err.message : "Something went wrong.",
      action: el("button", { class: "btn btn--secondary", type: "button", onclick: () => location.reload() }, icon("refresh"), "Try again"),
    }));
    return;
  }
  if (!isTerminal(lastStatus)) poller = startLive({ refresh: poll, intervalMs: POLL_MS, badge, shouldSkip: () => false });
}

main();
