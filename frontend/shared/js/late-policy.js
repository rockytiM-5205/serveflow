/* The late pickup policy, in plain words. One place so the checkout, the order page and the dashboard all say the same thing. */

/** policy: { grace_minutes, fee_amount, interval_minutes, max_fee } with money as strings. money: (amount) => "₦100". */
export function lateFeeText(policy, money) {
  if (!policy) return "";
  const every = Number(policy.interval_minutes) === 1 ? "minute" : `${policy.interval_minutes} minutes`;
  return `Please collect your order within ${policy.grace_minutes} minutes of when it is ready (or of your chosen time, if that is later). `
    + `After that, a late fee of ${money(policy.fee_amount)} applies for every ${every} (or part of it), up to ${money(policy.max_fee)} in total. `
    + "The clock only starts once the restaurant has marked your order ready.";
}

/** "Free until 14:25", "Free period starts when it's ready", or "" with no policy. `when` formats an ISO time. */
export function freeUntilText(policy, when) {
  if (!policy) return "";
  return policy.free_until ? `Collect by ${when(policy.free_until)} to avoid a late fee.` : "The free collection period starts when the restaurant marks your order ready.";
}

/** The status of a late fee in words. */
export function lateFeeStatusText(status) {
  return { DUE: "Due when you collect", PAID: "Paid", WAIVED: "Waived by the restaurant" }[status] ?? "";
}
