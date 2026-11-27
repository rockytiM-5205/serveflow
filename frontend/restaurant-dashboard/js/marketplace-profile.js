/* Settings cards for the marketplace: the public profile and location, and the opening hours. */
import { ApiError, api } from "../../shared/js/api.js";
import { CATEGORIES } from "../../shared/js/categories.js";
import { el, emptyState, icon, toast } from "../../shared/js/ui.js";
import { formDialog } from "./form-dialog.js";
import { buildPeriods, coordinateText, formatDay } from "./hours-format.js";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const latValid = (v) => (Number.isFinite(Number(v)) && Math.abs(Number(v)) <= 90 ? null : "Use a number between -90 and 90.");
const lngValid = (v) => (Number.isFinite(Number(v)) && Math.abs(Number(v)) <= 180 ? null : "Use a number between -180 and 180.");

/** The profile customers search by. `data` is the settings payload; `reload` refreshes the page after a save. */
export function marketplaceCard({ data, url, canEdit, reload }) {
  async function edit() {
    const fields = [
      { name: "listed_in_marketplace", label: "Show my restaurant in the ServeFlow marketplace", type: "checkbox" },
      { name: "category", label: "Category", type: "select", options: [{ value: "", label: "Not set" }, ...CATEGORIES.map((c) => ({ value: c.value, label: c.label }))] },
      { name: "area", label: "Area or town", type: "text", maxlength: 120, hint: "What customers search by, e.g. your town or neighbourhood." },
      { name: "latitude", label: "Latitude (optional)", type: "text", inputmode: "decimal", validate: latValid },
      { name: "longitude", label: "Longitude (optional)", type: "text", inputmode: "decimal", validate: lngValid },
    ];
    const values = { ...data, latitude: data.latitude ?? "", longitude: data.longitude ?? "" };
    const saved = await formDialog({
      title: "Marketplace profile",
      description: "Add your coordinates so customers can find you by distance. Without them you still appear in name, area and category searches. Your address is on the details card.",
      fields, values,
      validateForm: (v) => ((v.latitude === "") !== (v.longitude === "") ? { latitude: "Set both latitude and longitude, or leave both empty." } : {}),
      submit: (v) => api.patch(url, { ...v, latitude: coordinateText(v.latitude), longitude: coordinateText(v.longitude) }),
      onReady: (controls) => {
        if (!("geolocation" in navigator)) return;
        const here = el("button", { class: "btn btn--secondary btn--sm", type: "button" }, icon("search"), "Use my current location");
        here.addEventListener("click", () => {
          here.disabled = true;
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              controls.get("latitude").input.value = pos.coords.latitude.toFixed(6);
              controls.get("longitude").input.value = pos.coords.longitude.toFixed(6);
              here.disabled = false;
              toast("Location filled in. Check it is your restaurant, then save.", { type: "success" });
            },
            () => { here.disabled = false; toast("Couldn't get your location. You can type the coordinates instead.", { type: "error" }); },
            { timeout: 10000 },
          );
        });
        controls.get("longitude").wrap.append(here);
      },
    });
    if (saved) {
      toast("Marketplace profile saved.", { type: "success" });
      await reload();
    }
  }

  const category = CATEGORIES.find((c) => c.value === data.category)?.label ?? "Not set";
  const listed = data.listed_in_marketplace;
  const waiting = listed && !data.marketplace_approved;  // switched on, but ServeFlow hasn't approved it yet
  return el("section", { class: "card card__pad stack", "aria-labelledby": "market-h" },
    el("div", { class: "section-head", style: "margin:0" },
      el("h2", { id: "market-h" }, "Marketplace"),
      canEdit ? el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: edit }, "Edit") : null),
    el("p", { class: "muted" }, waiting
      ? "Waiting for ServeFlow to approve your restaurant. Customers can't find you in the marketplace until then, but your own link works."
      : listed
        ? "Customers can find you in the marketplace."
        : "You are not in the marketplace. Customers can still order from your own link."),
    el("dl", { class: "details" },
      el("dt", {}, "Listed"), el("dd", {}, waiting ? "Waiting for approval" : listed ? "Yes" : "No"),
      el("dt", {}, "Category"), el("dd", {}, category),
      el("dt", {}, "Area"), el("dd", {}, data.area || "Not set"),
      el("dt", {}, "Location"), el("dd", {}, data.latitude != null && data.longitude != null ? `${data.latitude}, ${data.longitude}` : "Not set (no distance search)")),
    canEdit ? null : el("p", { class: "muted" }, "Managers and owners can edit this."));
}

/** Opening hours: loaded on its own because they have their own endpoint. */
export function hoursCard({ slug, canEdit, onError }) {
  const url = `/restaurants/${encodeURIComponent(slug)}/hours/`;
  const box = el("section", { class: "card card__pad stack", "aria-labelledby": "hours-h" });
  let current = null;

  function draw() {
    const days = current.hours;
    const any = days.some((d) => d.periods.length);
    box.replaceChildren(
      el("div", { class: "section-head", style: "margin:0" },
        el("h2", { id: "hours-h" }, "Opening hours"),
        canEdit ? el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: edit }, "Edit") : null),
      el("p", { class: "muted" }, `Times are in your restaurant's timezone (${current.timezone}). With no hours set, customers see you as open whenever orders are switched on.`),
      any
        ? el("ul", { class: "hours-list" }, ...days.map((d) => el("li", {}, el("span", {}, d.day), el("span", {}, formatDay(d.periods).replaceAll("-", "\u2013") || "Closed"))))
        : el("p", {}, "No opening hours published."));
  }

  async function edit() {
    const fields = DAYS.map((day, i) => ({
      name: `d${i}`, label: day, type: "text", maxlength: 80,
      hint: i === 0 ? "Like 09:00-14:00, 17:00-22:00. Leave empty if closed." : undefined,
    }));
    const values = Object.fromEntries(current.hours.map((d) => [`d${d.weekday}`, formatDay(d.periods)]));
    const read = (v) => buildPeriods(DAYS.map((_, i) => v[`d${i}`]));
    const saved = await formDialog({
      title: "Opening hours", fields, values,
      validateForm: (v) => { const r = read(v); return r.error ? { [`d${r.day}`]: r.error } : {}; },
      submit: async (v) => { current = await api.put(url, { periods: read(v).periods }); },
    });
    if (saved) { toast("Opening hours saved.", { type: "success" }); draw(); }
  }

  async function load() {
    box.replaceChildren(el("div", { class: "skeleton skeleton--line", style: "width:50%;height:1.25rem", "aria-hidden": "true" }));
    try {
      current = await api.get(url);
      draw();
    } catch (err) {
      if (onError?.(err)) return;
      box.replaceChildren(emptyState({
        iconName: "alert", title: "Couldn't load opening hours", text: err instanceof ApiError ? err.message : "Something went wrong.",
        action: el("button", { class: "btn btn--secondary", type: "button", onclick: load }, icon("refresh"), "Try again"),
      }));
    }
  }

  load();
  return box;
}
