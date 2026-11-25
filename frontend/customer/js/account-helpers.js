/* Pure helpers for customer accounts and order history. */

const NEXT_OK = /^(index|menu|checkout|marketplace|my-orders|account)\.html(\?[A-Za-z0-9_=&%.\-]*)?$/;

/** An order page remembered in this tab (never in an address) so that signing in to review can bring the customer straight back to it. */
export const RETURN_KEY = "serveflow:return-to-order";
const ORDER_RETURN_OK = /^order\.html\?r=[a-z0-9-]{3,64}#[A-Za-z0-9_-]{20,200}$/;
export const isOrderReturn = (value) => typeof value === "string" && ORDER_RETURN_OK.test(value);
export const RETURN_MAX_AGE_MS = 30 * 60 * 1000;

/** Where to go after signing in. Only our own customer pages, never another site and never a page that carries an order link. */
export function safeNext(value) {
  return typeof value === "string" && NEXT_OK.test(value) ? value : "my-orders.html";
}

export function fullName(me) {
  return [me?.first_name, me?.last_name].filter(Boolean).join(" ").trim();
}

export const STATUS_WORDS = Object.freeze({
  PENDING: "Waiting", CONFIRMED: "Accepted", SERVING: "Preparing", READY_FOR_PICKUP: "Ready", COMPLETED: "Completed",
  REJECTED: "Rejected", CANCELLED: "Cancelled",
});

/** "2 items · Pickup" */
export function orderSummary(row) {
  const n = row.items_count ?? 0;
  return `${n} ${n === 1 ? "item" : "items"} \u00b7 ${row.fulfilment_type === "DINE_IN" ? "Dine in" : "Pickup"}`;
}

/** The address of the normal order page for one of the customer's own orders. The token goes in the part after #, which servers never see. */
export function trackHref(row) {
  return `order.html?r=${encodeURIComponent(row.restaurant.slug)}#${row.track_token}`;
}
