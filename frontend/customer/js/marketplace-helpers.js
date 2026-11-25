/* Pure helpers for the marketplace pages (no DOM). */

export const AVAILABILITY = Object.freeze({
  OPEN: "Open",
  CLOSED: "Closed now",
  PAUSED: "Not taking orders",
});

const SORTS = new Set(["distance", "name", "rating"]);
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** "180 m", "2.4 km", or "" when the distance is unknown. */
export function distanceLabel(km) {
  if (typeof km !== "number" || !Number.isFinite(km) || km < 0) return "";
  if (km < 1) return `${Math.max(10, Math.round((km * 1000) / 10) * 10)} m`;
  return `${km < 10 ? km.toFixed(1) : Math.round(km)} km`;
}

/** A rating only when real reviews exist; otherwise an honest "No reviews yet". */
export function ratingLabel(average, count) {
  if (!count || typeof average !== "number") return "No reviews yet";
  return `${average.toFixed(1)} (${count} ${count === 1 ? "review" : "reviews"})`;
}

/** The filters kept in the address bar. Coordinates are deliberately NOT here: a shared link must not carry someone's location. */
export function stateFromUrl(search) {
  const p = new URLSearchParams(search);
  const text = (key, max) => (p.get(key) ?? "").trim().slice(0, max);
  const radius = Number(p.get("radius"));
  return {
    q: text("q", 80),
    area: text("area", 120),
    category: text("category", 20).toUpperCase(),
    openNow: p.get("open") === "1",
    sort: SORTS.has(p.get("sort")) ? p.get("sort") : "",
    radius: Number.isFinite(radius) && radius > 0 && radius <= 200 ? radius : 0,
  };
}

export function urlFromState(state) {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.area) p.set("area", state.area);
  if (state.category) p.set("category", state.category);
  if (state.openNow) p.set("open", "1");
  if (state.sort) p.set("sort", state.sort);
  if (state.radius) p.set("radius", String(state.radius));
  const text = p.toString();
  return text ? `?${text}` : "";
}

/** The API query for the current state. `where` is { lat, lng } or null. */
export function apiQuery(state, where, page = 1) {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.area) p.set("area", state.area);
  if (state.category) p.set("category", state.category);
  if (state.openNow) p.set("open_now", "true");
  if (where) {
    p.set("lat", where.lat.toFixed(5)); // about a metre: no need to send more than we use
    p.set("lng", where.lng.toFixed(5));
    if (state.radius) p.set("radius_km", String(state.radius));
  }
  const sort = state.sort === "distance" && !where ? "" : state.sort;
  if (sort) p.set("ordering", sort);
  if (page > 1) p.set("page", String(page));
  return p.toString();
}

/** A readable reason when the browser can't give us a location. `code` is a GeolocationPositionError code. */
export function locationProblem(code) {
  if (code === 1) return "Location is blocked. You can still search by area, or allow location for this site in your browser settings.";
  if (code === 3) return "Finding your location took too long. Try again, or search by area.";
  return "We couldn't find your location. Search by area instead.";
}

/** "09:00-14:00, 17:00-22:00" or "Closed". */
export function periodsText(periods) {
  return periods && periods.length ? periods.map((p) => `${p.opens}\u2013${p.closes}`).join(", ") : "Closed";
}

/** Index (0 = Monday) of "today" in the restaurant's own timezone. */
export function todayIndex(timeZone, now = new Date()) {
  try {
    const name = new Intl.DateTimeFormat("en-GB", { weekday: "long", timeZone }).format(now);
    const index = DAYS.indexOf(name);
    if (index >= 0) return index;
  } catch {
    /* unknown timezone: fall through to the device's own day */
  }
  return (now.getDay() + 6) % 7;
}

/** A link that opens the restaurant's position in the device's maps app, or null without coordinates. */
export function mapsHref(latitude, longitude) {
  if (typeof latitude !== "number" || typeof longitude !== "number") return null;
  return `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`;
}
