/* What a plan includes, in words a restaurant owner understands. Used by the landing page, the pricing page and Billing,
 * so all three always say the same thing. Technical limits (API requests, requests per minute) are deliberately not shown here. */
import { formatMoney } from "./ui.js";

const number = (n) => new Intl.NumberFormat().format(n);
const per = (interval) => (interval === "YEARLY" ? "year" : "month");

export function planFacts(plan) {
  const facts = [];
  if (plan.included_orders) facts.push(`${number(plan.included_orders)} orders each ${per(plan.interval)}`);
  if (plan.included_orders) facts.push("Only finished orders count");
  if (plan.pack_orders && plan.pack_price) facts.push(`Busy month? Add ${number(plan.pack_orders)} more orders for ${formatMoney(plan.pack_price, plan.currency)}`);
  return facts;
}
