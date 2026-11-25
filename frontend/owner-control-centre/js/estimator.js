/* Helps the owner pick a plan's request numbers. It only does arithmetic on the assumptions typed in; nothing here is data.
 * What counts as a request is explained in docs/api-guide.md: a call with a key to a restaurant route (menu reads, checkouts). */
const finite = (n, fallback) => (Number.isFinite(n) && n >= 0 ? n : fallback);
const niceUp = (n, step) => Math.max(step, Math.ceil(n / step) * step);
const MINUTE_STEPS = [30, 60, 120, 300, 600, 1200, 3000]; // never suggest fewer than 30 a minute

export function estimateLimits({ ordersPerDay, openHours = 12, daysPerMonth = 30, cacheSeconds = 60, menuViewsPerOrder = 10, peakShare = 0.2, headroom = 2.5 }) {
  const orders = finite(ordersPerDay, 0), hours = finite(openHours, 12), days = finite(daysPerMonth, 30);
  const cache = finite(cacheSeconds, 0), views = finite(menuViewsPerOrder, 10), peak = finite(peakShare, 0.2), room = finite(headroom, 2.5);
  const menuReadsPerDay = cache > 0 ? Math.ceil((hours * 3600) / cache) : orders * views; // cached: a read every `cache` seconds; uncached: every diner view
  const perDay = menuReadsPerDay + orders; // plus one checkout per order
  const perMonth = Math.round(perDay * days);
  const peakOrdersPerHour = orders * peak;
  const perMinutePeak = (cache > 0 ? 60 / cache : (peakOrdersPerHour * views) / 60) + peakOrdersPerHour / 60;
  const burst = perMinutePeak * 3;
  return {
    perDay, perMonth, perMinutePeak: Math.round(perMinutePeak * 10) / 10,
    suggestedMonthly: niceUp(perMonth * room, 1000),
    suggestedPerMinute: MINUTE_STEPS.find((step) => step >= burst) ?? niceUp(burst, 1000),
  };
}
