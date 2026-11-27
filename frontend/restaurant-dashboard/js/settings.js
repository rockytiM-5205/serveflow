import { ApiError, api } from "../../shared/js/api.js";
import { el, emptyState, icon, toast } from "../../shared/js/ui.js";
import { attachBadge, liveBadge, startLive } from "../../shared/js/live.js";
import { imagePicker, pictureForm } from "../../shared/js/image-picker.js";
import { formDialog } from "./form-dialog.js";
import { fulfilmentErrors, restaurantFields } from "./regional.js";
import { hoursCard, marketplaceCard } from "./marketplace-profile.js";
import { paymentCard } from "./payment-account.js";
import { hasRole } from "./session.js";
import { bootDashboard, handleSessionExpiry } from "./shell.js";
import { canInstall, isIos, isStandalone, onInstallChange, promptInstall } from "../../shared/js/pwa.js";
import { pushSupported, thisDevice, turnOff, turnOn } from "./push-client.js";

const HREF = "settings.html";
const content = document.getElementById("content");

const skeleton = () =>
  el("div", { class: "card card__pad stack", "aria-hidden": "true" },
    ...[60, 85, 70].map((w) => el("div", { class: "skeleton skeleton--line", style: `width:${w}%;height:1.25rem` })));

const fulfilmentText = (r) => {
  const parts = [];
  if (r.pickup_enabled) parts.push("Pickup");
  if (r.dine_in_enabled) parts.push(r.requires_table_number ? "Dine in (table number required)" : "Dine in");
  return parts.join(", ");
};

async function main() {
  const ctx = await bootDashboard({ href: HREF });
  if (!ctx) return;
  const canEdit = hasRole(ctx.role, "MANAGER");
  const url = `/restaurants/${encodeURIComponent(ctx.restaurant.slug)}/settings/`;
  const customerUrl = new URL(`../customer/index.html?r=${encodeURIComponent(ctx.restaurant.slug)}`, location.href).href;
  let data;
  let lastJson = "";

  const failure = (err) => {
    if (handleSessionExpiry(err, HREF)) return;
    toast(err instanceof ApiError ? err.message : "Something went wrong.", { type: "error" });
  };

  async function load() {
    content.replaceChildren(skeleton());
    try {
      data = await api.get(url);
      lastJson = JSON.stringify(data);
      render();
    } catch (err) {
      if (handleSessionExpiry(err, HREF)) return;
      content.replaceChildren(emptyState({
        iconName: "alert", title: "Couldn't load settings",
        text: err instanceof ApiError ? err.message : "Something went wrong.",
        action: el("button", { class: "btn btn--secondary", type: "button", onclick: load }, icon("refresh"), "Try again"),
      }));
    }
  }

  async function edit() {
    const fields = restaurantFields({ timezone: data.timezone, includePrefix: !data.order_prefix_locked });
    const saved = await formDialog({
      title: "Edit restaurant details", fields, values: data, validateForm: fulfilmentErrors,
      submit: (v) => api.patch(url, v),
    });
    if (saved) {
      toast("Settings saved.", { type: "success" });
      await load();
    }
  }

  function ordersCard() {
    const state = el("span", { class: "muted" }, data.accepting_orders ? "On" : "Off");
    const toggle = el("button", {
      class: "switch", type: "button", role: "switch", "aria-checked": String(data.accepting_orders),
      "aria-label": "Accepting orders",
    });
    toggle.addEventListener("click", async () => {
      toggle.disabled = true;
      try {
        data = await api.patch(url, { accepting_orders: !data.accepting_orders });
        toggle.setAttribute("aria-checked", String(data.accepting_orders));
        state.textContent = data.accepting_orders ? "On" : "Off";
        toast(data.accepting_orders ? "Orders switched on." : "Orders paused.", { type: "success" });
      } catch (err) {
        failure(err);
      } finally {
        toggle.disabled = false;
      }
    });
    return el("section", { class: "card card__pad stack", "aria-labelledby": "orders-h" },
      el("div", { class: "section-head", style: "margin:0" },
        el("h2", { id: "orders-h" }, "Accepting orders"),
        el("div", { class: "row" }, state, toggle)),
      el("p", { class: "muted" }, "Switch this off during a rush to pause new orders. Customers can still see your menu, and orders already placed are not affected. New restaurants start with orders off."),
    );
  }

  /** Install the dashboard like an app, and get a sound and a message on this device for every new order. */
  function appCard() {
    const pushBase = `/restaurants/${encodeURIComponent(ctx.restaurant.slug)}`;
    const body = el("div", { class: "stack" });
    let config = null;
    let on = false;
    const state = { busy: false };

    async function load() {
      try {
        config = await api.get(`${pushBase}/push/config/`);
        on = pushSupported() && config.enabled ? Boolean(await thisDevice()) : false;
      } catch { config = { enabled: false }; }
      draw();
    }

    const act = (button, work) => async () => {
      if (state.busy) return;
      state.busy = true;
      button.disabled = true;
      try { await work(); } catch (err) { failure(err); } finally { state.busy = false; await load(); }
    };

    function draw() {
      const rows = [];
      if (canInstall()) {
        const install = el("button", { class: "btn btn--primary", type: "button" }, icon("phone"), "Install the app on this device");
        install.addEventListener("click", () => promptInstall());
        rows.push(el("p", { class: "muted" }, "Open ServeFlow straight from your home screen, full-screen, like any other app."), install);
      } else if (isStandalone()) {
        rows.push(el("p", { class: "muted" }, "You are using the installed app."));
      } else if (isIos()) {
        rows.push(el("p", { class: "muted" }, "To install: tap Share in Safari, then Add to Home Screen. On iPhone, order alerts only work from the installed app."));
      } else {
        rows.push(el("p", { class: "muted" }, "To install, use your browser's menu and choose Install app (or Add to Home Screen)."));
      }

      rows.push(el("h3", {}, "Order alerts"));
      if (!config) {
        rows.push(el("p", { class: "muted" }, "Checking…"));
      } else if (!config.enabled) {
        rows.push(el("p", { class: "muted" }, "Order alerts aren't switched on for this ServeFlow yet. Ask whoever runs ServeFlow to set them up."));
      } else if (!pushSupported()) {
        rows.push(el("p", { class: "muted" }, "This browser can't show alerts. On iPhone, install the app first (Share, then Add to Home Screen), then come back here."));
      } else if (typeof Notification !== "undefined" && Notification.permission === "denied" && !on) {
        rows.push(el("p", { class: "muted" }, "Alerts are blocked for this site in your browser settings. Allow notifications for this site, then come back here."));
      } else if (on) {
        const test = el("button", { class: "btn btn--secondary btn--sm", type: "button" }, "Send a test alert");
        test.addEventListener("click", act(test, async () => {
          const r = await api.post(`${pushBase}/push/test/`, {});
          toast(r.sent ? "Test alert sent." : "Nothing was sent. Try turning alerts off and on again.", { type: r.sent ? "success" : "info" });
        }));
        const off = el("button", { class: "btn btn--ghost btn--sm", type: "button" }, "Turn off");
        off.addEventListener("click", act(off, async () => { await turnOff({ api, base: pushBase }); toast("Alerts are off on this device.", { type: "success" }); }));
        rows.push(el("p", {}, el("strong", {}, "On for this device. "), "You will get a message for every new order, even when ServeFlow isn't open."),
          el("p", { class: "muted" }, "If alerts stop after you close the app: in your phone's Settings, allow notifications for your browser (or the ServeFlow app) and set its battery use to Unrestricted. Some phones also need Autostart switched on."),
          el("div", { class: "row" }, test, off));
      } else {
        const turn = el("button", { class: "btn btn--primary", type: "button" }, icon("bell"), "Turn on alerts on this device");
        turn.addEventListener("click", act(turn, async () => {
          const result = await turnOn({ api, base: pushBase, publicKey: config.public_key });
          toast(result === "on" ? "Alerts are on." : "Alerts stay off. You said no in the browser prompt.", { type: result === "on" ? "success" : "info" });
        }));
        rows.push(el("p", { class: "muted" }, "Get a message on this phone or tablet for every new order, even when ServeFlow isn't open. Each device turns this on for itself."), turn);
      }
      body.replaceChildren(...rows);
    }

    onInstallChange(draw);
    draw();
    load();
    return el("section", { class: "card card__pad stack", "aria-labelledby": "app-h" }, el("h2", { id: "app-h" }, "Use ServeFlow as an app"), body);
  }

  function autoAcceptCard() {
    const state = el("span", { class: "muted" }, data.auto_accept_orders ? "On" : "Off");
    const toggle = el("button", { class: "switch", type: "button", role: "switch", "aria-checked": String(Boolean(data.auto_accept_orders)), "aria-label": "Accept new orders automatically" });
    toggle.addEventListener("click", async () => {
      toggle.disabled = true;
      try {
        data = await api.patch(url, { auto_accept_orders: !data.auto_accept_orders });
        toggle.setAttribute("aria-checked", String(Boolean(data.auto_accept_orders)));
        state.textContent = data.auto_accept_orders ? "On" : "Off";
        toast(data.auto_accept_orders ? "New orders will be accepted automatically." : "New orders will wait for you to accept them.", { type: "success" });
      } catch (err) {
        failure(err);
      } finally {
        toggle.disabled = false;
      }
    });
    return el("section", { class: "card card__pad stack", "aria-labelledby": "autoaccept-h" },
      el("div", { class: "section-head", style: "margin:0" },
        el("h2", { id: "autoaccept-h" }, "Accept new orders automatically"),
        el("div", { class: "row" }, state, toggle)),
      el("p", { class: "muted" }, "Good for busy hours: every new order is accepted the moment it arrives, so nobody has to press Accept. Nothing is prepared until you have confirmed the customer's payment."),
    );
  }

  function detailsCard() {
    const details = el("dl", { class: "details" },
      el("dt", {}, "Name"), el("dd", {}, data.name),
      el("dt", {}, "Web address"), el("dd", {}, data.slug),
      el("dt", {}, "Order ID prefix"), el("dd", {}, data.order_prefix ? `${data.order_prefix}${data.order_prefix_locked ? " (locked: you have orders)" : ""}` : "Not set"),
      el("dt", {}, "Currency"), el("dd", {}, data.currency),
      el("dt", {}, "Timezone"), el("dd", {}, data.timezone),
      el("dt", {}, "Ordering options"), el("dd", {}, fulfilmentText(data)),
      el("dt", {}, "Address"), el("dd", {}, data.address || "Not set"),
      el("dt", {}, "Phone"), el("dd", {}, data.contact_phone || "Not set"),
      el("dt", {}, "About"), el("dd", {}, data.description || "Not set"),
    );
    return el("section", { class: "card card__pad stack", "aria-labelledby": "details-h" },
      el("div", { class: "section-head", style: "margin:0" },
        el("h2", { id: "details-h" }, "Restaurant details"),
        canEdit ? el("button", { class: "btn btn--secondary btn--sm", type: "button", onclick: edit }, "Edit") : null),
      details,
      canEdit ? null : el("p", { class: "muted" }, "Managers and owners can edit these details."),
    );
  }

  function linkCard() {
    const copy = el("button", { class: "btn btn--secondary btn--sm", type: "button" }, "Copy");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(customerUrl);
        toast("Link copied.", { type: "success" });
      } catch {
        toast("Couldn't copy. Select the link and copy it.", { type: "error" });
      }
    });
    return el("section", { class: "card card__pad stack", "aria-labelledby": "link-h" },
      el("h2", { id: "link-h" }, "Your customer link"),
      el("p", { class: "muted" }, "Share this link or turn it into a QR code. Customers can browse your menu from it."),
      el("p", { class: "copy-row" }, el("code", { class: "copy-row__url" }, customerUrl)),
      el("div", { class: "row" }, copy,
        el("a", { class: "btn btn--secondary btn--sm", href: customerUrl, target: "_blank", rel: "noopener" }, "Open")),
    );
  }

  /** The logo and cover picture shown on the restaurant's public page. Uploaded from the device; checked and resized by the server. */
  function picturesCard() {
    const logo = imagePicker({ label: "Logo", currentUrl: data.logo_url, hint: "Saved as a 512 \u00d7 512 square. Your whole logo is kept; if it isn't square, empty space is added around it." });
    const cover = imagePicker({ label: "Cover picture", currentUrl: data.cover_url, wide: true, hint: "The banner at the top of your page. Saved at 588 \u00d7 312 (the same frame on the marketplace and your page); if your picture is a different shape, the edges are cropped to fit." });
    const save = el("button", { class: "btn btn--primary", type: "button" }, "Save pictures");
    save.addEventListener("click", async () => {
      save.disabled = true;
      let failed = false;
      for (const [kind, picker] of [["logo", logo], ["cover", cover]]) {
        try {
          if (picker.file()) await api.upload(`/restaurants/${encodeURIComponent(ctx.restaurant.slug)}/images/${kind}/`, pictureForm(picker.file()));
          else if (picker.removeRequested()) await api.delete(`/restaurants/${encodeURIComponent(ctx.restaurant.slug)}/images/${kind}/`);
        } catch (err) {
          failed = true;
          if (handleSessionExpiry(err, HREF)) return;
          toast(`${kind === "logo" ? "Logo" : "Cover picture"}: ${err instanceof ApiError ? err.message : "something went wrong."}`, { type: "error" });
        }
      }
      save.disabled = false;
      if (!failed) toast("Pictures saved. They show on your page now.", { type: "success" });
      await load();
    });
    return el("section", { class: "card card__pad stack", "aria-labelledby": "pictures-h" },
      el("h2", { id: "pictures-h" }, "Pictures on your page"),
      el("p", { class: "muted" }, "Add your logo and a cover picture. Customers see them at the top of your page. Choose JPEG, PNG or WebP files up to 3 MB."),
      el("div", { class: "pictures-grid" }, logo.node, cover.node), save);
  }

  function render() {
    content.replaceChildren(
      ordersCard(),
      autoAcceptCard(),
      appCard(),
      paymentCard({
        slug: ctx.restaurant.slug, data, url, canEditFee: canEdit, isOwner: hasRole(ctx.role, "OWNER"), reload: load,
        onError: (err) => handleSessionExpiry(err, HREF),
      }),
      detailsCard(), ...(canEdit ? [picturesCard()] : []),
      marketplaceCard({ data, url, canEdit, reload: load }),
      hoursCard({ slug: ctx.restaurant.slug, canEdit, onError: (err) => handleSessionExpiry(err, HREF) }),
      linkCard());
  }

  await load();

  const badge = liveBadge();
  attachBadge(badge);
  startLive({
    badge,
    intervalMs: 10000,
    shouldSkip: () => Boolean(document.querySelector('dialog[open], [aria-busy="true"], .switch:disabled')),
    refresh: async () => {
      try {
        const fresh = await api.get(url);
        const json = JSON.stringify(fresh);
        if (json === lastJson) return;
        data = fresh;
        lastJson = json;
        render();
      } catch (err) {
        if (handleSessionExpiry(err, HREF)) return;
        throw err;
      }
    },
  });
}

main();
