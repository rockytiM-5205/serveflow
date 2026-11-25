/* The marketplace: discover restaurants by name, area, category or distance. No account needed.
 * Location is optional and only requested when the customer taps the button. It is kept in memory for this page
 * view only: never stored, never put in the address bar. */
import { ApiError, api } from "../../shared/js/api.js";
import { CATEGORIES } from "../../shared/js/categories.js";
import { el, emptyState, icon, setBusy } from "../../shared/js/ui.js";
import { mountSiteNav } from "./site-nav.js";
import { robustImage } from "../../shared/js/images.js";
import { isImageSource } from "../../shared/js/validators.js";
import {
  AVAILABILITY, apiQuery, distanceLabel, locationProblem, ratingLabel, stateFromUrl, urlFromState,
} from "./marketplace-helpers.js";

const $ = (id) => document.getElementById(id);

if (globalThis.matchMedia?.("(min-width: 900px)").matches) { const more = document.getElementById("more-filters"); if (more) more.open = true; }
const form = $("search-form");
const results = $("results");
const more = $("more");
const title = $("results-title");
const note = $("location-note");

let state = stateFromUrl(location.search);
let where = null; // { lat, lng } while the customer has shared a location
let page = 1;
let loading = false;
let token = 0; // ignores answers to searches that have since been replaced

const RADIUS_CHOICES = [["", "Any distance"], ["2", "Within 2 km"], ["5", "Within 5 km"], ["10", "Within 10 km"], ["25", "Within 25 km"]];

function showNote(text) {
  note.textContent = text ?? "";
  note.hidden = !text;
}

function skeletons() {
  return Array.from({ length: 3 }, () => el("div", { class: "card card__pad stack", "aria-hidden": "true" },
    el("div", { class: "skeleton skeleton--line", style: "height:5rem" }),
    el("div", { class: "skeleton skeleton--line", style: "width:60%" }),
    el("div", { class: "skeleton skeleton--line", style: "width:40%" })));
}

function card(r) {
  const meta = [r.category?.label, r.area, distanceLabel(r.distance_km)].filter(Boolean);
  const fulfil = [r.pickup_enabled ? "Pickup" : null, r.dine_in_enabled ? "Dine in" : null].filter(Boolean).join(" \u00b7 ");
  const cover = isImageSource(r.cover_url)
    ? robustImage({ src: r.cover_url, attrs: { loading: "lazy" }, fallback: () => icon("utensils", { large: true }) })
    : icon("utensils", { large: true });
  const logo = isImageSource(r.logo_url) ? robustImage({ src: r.logo_url, attrs: { loading: "lazy" }, fallback: () => icon("store") }) : icon("store");
  return el("a", { class: "card rest-card", href: `index.html?r=${encodeURIComponent(r.slug)}` },
    el("div", { class: "rest-card__cover" }, cover),
    el("div", { class: "rest-card__body" },
      el("div", { class: "rest-card__title" }, el("span", { class: "rest-card__logo" }, logo), el("h3", {}, r.name)),
      el("div", { class: "row" },
        el("span", { class: "badge", "data-status": r.availability }, AVAILABILITY[r.availability] ?? r.availability),
        el("span", { class: "muted" }, ratingLabel(r.rating_average, r.rating_count))),
      meta.length ? el("div", { class: "rest-card__meta" }, ...meta.map((m) => el("span", {}, m))) : null,
      r.description ? el("p", { class: "rest-card__desc" }, r.description) : null,
      fulfil ? el("div", { class: "rest-card__meta" }, el("span", {}, fulfil)) : null));
}

function emptyResults() {
  const filtered = state.q || state.area || state.category || state.openNow || where;
  return emptyState({
    iconName: "search",
    title: filtered ? "No restaurants match" : "No restaurants yet",
    text: filtered
      ? "Try a different name or area, remove a filter, or widen the distance."
      : "No restaurant has joined the marketplace yet. Check back soon.",
    action: filtered ? el("button", { class: "btn btn--secondary", type: "button", onclick: reset }, "Clear filters") : null,
  });
}

async function run({ append = false } = {}) {
  if (loading && append) return;
  const mine = ++token;
  loading = true;
  if (!append) {
    page = 1;
    results.replaceChildren(...skeletons());
    more.hidden = true;
  } else {
    page += 1;
    setBusy(more, true);
  }
  try {
    const body = await api.get(`/marketplace/restaurants/?${apiQuery(state, where, page)}`);
    if (mine !== token) return;
    const cards = body.results.map(card);
    if (append) results.append(...cards);
    else results.replaceChildren(...(cards.length ? cards : [emptyResults()]));
    title.textContent = body.count === 1 ? "1 restaurant" : `${body.count} restaurants`;
    more.hidden = !body.has_next;
  } catch (err) {
    if (mine !== token) return;
    if (append) page -= 1;
    const retry = el("button", { class: "btn btn--secondary", type: "button", onclick: () => run({ append }) }, icon("refresh"), "Try again");
    const failure = emptyState({
      iconName: "alert", title: "Couldn't load restaurants",
      text: err instanceof ApiError ? err.message : "Something went wrong.", action: retry,
    });
    if (append) results.after(failure); else results.replaceChildren(failure);
  } finally {
    loading = false;
    setBusy(more, false);
  }
}

function readForm() {
  state = {
    ...state,
    q: $("q").value.trim(),
    area: $("area").value.trim(),
    openNow: $("open-now").checked,
    sort: $("sort").value,
  };
}

function remember() {
  history.replaceState(null, "", `${location.pathname}${urlFromState(state)}`);
}

function search() {
  readForm();
  remember();
  document.querySelectorAll(".chip-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === state.category)));
  return run();
}

function reset() {
  state = { q: "", area: "", category: "", openNow: false, sort: "", radius: 0 };
  where = null;
  $("q").value = "";
  $("area").value = "";
  $("open-now").checked = false;
  drawLocation();
  drawSort();
  showNote("");
  search();
}

function drawSort() {
  const options = [["", where ? "Nearest first" : "Name"], ["name", "Name"], ["rating", "Best rated"]];
  if (!where) options.splice(1, 1); // "Name" is already the default
  $("sort").replaceChildren(...options.map(([value, label]) => el("option", { value }, label)));
  $("sort").value = state.sort === "distance" ? "" : state.sort;
}

function drawLocation() {
  const box = $("location-controls");
  if (where) {
    const radius = el("select", { class: "select", "aria-label": "Distance", id: "radius" },
      ...RADIUS_CHOICES.map(([value, label]) => el("option", { value }, label)));
    radius.value = state.radius ? String(state.radius) : "";
    radius.addEventListener("change", () => { state.radius = Number(radius.value) || 0; search(); });
    box.replaceChildren(
      el("span", { class: "badge", "data-status": "OPEN" }, "Near you"), radius,
      el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: stopSharing }, "Stop using my location"));
    return;
  }
  if (!("geolocation" in navigator)) {
    box.replaceChildren(el("span", { class: "muted" }, "Your browser can't share location. Search by area instead."));
    return;
  }
  const button = el("button", { class: "btn btn--secondary", type: "button" }, icon("search"), "Restaurants near me");
  button.addEventListener("click", () => locate(button));
  box.replaceChildren(button);
}

function locate(button) {
  setBusy(button, true);
  showNote("Finding your location\u2026");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      where = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      showNote("Showing the nearest restaurants first. Your location stays on this page and is not saved.");
      drawLocation();
      drawSort();
      search();
    },
    (err) => {
      setBusy(button, false);
      showNote(locationProblem(err.code));
      $("area").focus();
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 },
  );
}

function stopSharing() {
  where = null;
  state.radius = 0;
  showNote("");
  drawLocation();
  drawSort();
  search();
}

async function loadFilters() {
  try {
    const [cats, areas] = await Promise.all([api.get("/marketplace/categories/"), api.get("/marketplace/areas/")]);
    const present = new Set(cats.results.map((c) => c.value));
    const shown = CATEGORIES.filter((c) => present.has(c.value));
    const label = (c) => `${c.label} (${cats.results.find((x) => x.value === c.value).count})`;
    $("categories").replaceChildren(
      el("button", { class: "chip-btn", type: "button", "data-value": "", "aria-pressed": String(!state.category), onclick: () => pick("") }, "All"),
      ...shown.map((c) => el("button", {
        class: "chip-btn", type: "button", "data-value": c.value, "aria-pressed": String(state.category === c.value), onclick: () => pick(c.value),
      }, label(c))));
    $("area-list").replaceChildren(...areas.results.map((a) => el("option", { value: a.area })));
  } catch {
    $("categories").replaceChildren(el("span", { class: "muted" }, "Categories are unavailable right now."));
  }
}

function pick(value) {
  state.category = value;
  search();
}

form.addEventListener("submit", (event) => { event.preventDefault(); search(); });
$("reset").addEventListener("click", reset);
$("open-now").addEventListener("change", search);
$("sort").addEventListener("change", search);
more.addEventListener("click", () => run({ append: true }));

$("q").value = state.q;
$("area").value = state.area;
$("open-now").checked = state.openNow;
mountSiteNav({ slug: null });
drawLocation();
drawSort();
await loadFilters();
await run();
