/* Words and steps for an order's status (pure, no DOM). */
export const TERMINAL = new Set(["COMPLETED", "REJECTED", "CANCELLED"]);

export const HEADLINE = {
  PENDING: "Waiting for your payment and the restaurant",
  CONFIRMED: "Your order is confirmed",
  SERVING: "Your order is being prepared",
  READY_FOR_PICKUP: "Your order is ready",
  COMPLETED: "Completed. Enjoy your meal!",
  REJECTED: "The restaurant couldn't take this order",
  CANCELLED: "This order was cancelled",
};

export const DETAIL = {
  PENDING: "Pay with the bank details below. The restaurant starts preparing once it confirms your payment. This page updates by itself.",
  CONFIRMED: "The restaurant has accepted your order. It starts preparing once your payment is confirmed.",
  SERVING: "The kitchen is working on it.",
  READY_FOR_PICKUP: "It is ready now. Please collect it from the restaurant.",
  COMPLETED: "",
  REJECTED: "You can place a new order or ask the restaurant. If you already paid, the restaurant will refund you.",
  CANCELLED: "",
};

const STEPS = [
  ["PENDING", "Order placed"],
  ["CONFIRMED", "Confirmed"],
  ["SERVING", "Preparing"],
  ["READY_FOR_PICKUP", "Ready"],
  ["COMPLETED", "Completed"],
];

/** The happy-path steps with done/current flags, from the order's timeline. */
export function timelineSteps(order) {
  const reached = new Set(order.timeline.map((entry) => entry.status));
  const closed = order.status === "REJECTED" || order.status === "CANCELLED";
  return STEPS.map(([status, label]) => ({
    status,
    label,
    done: reached.has(status),
    current: !closed && order.status === status,
  }));
}

export const isTerminal = (status) => TERMINAL.has(status);

export function tokenFromHash(hash) {
  const token = String(hash ?? "").replace(/^#/, "");
  return /^[0-9a-f]{96}$/.test(token) ? token : null;
}

/** What the customer sees about payment, in words. */
export function paymentWords(order) {
  if (order.payment_status === "PAID") return "Paid";
  if (order.payment_status === "CLAIMED") return "Waiting for the restaurant to confirm your payment";
  return "Not paid yet";
}

/** A pickup time like "Today 13:15" in the browser's language, or "" when there is none. */
export function pickupText(pickupAt, now = new Date()) {
  if (!pickupAt) return "";
  const when = new Date(pickupAt);
  if (Number.isNaN(when.getTime())) return "";
  const sameDay = (a, b) => a.toDateString() === b.toDateString();
  const tomorrow = new Date(now.getTime() + 86400000);
  const day = sameDay(when, now) ? "Today" : sameDay(when, tomorrow) ? "Tomorrow" : when.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return `${day} ${when.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}
