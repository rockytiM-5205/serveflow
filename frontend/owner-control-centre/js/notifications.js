/* The owner's notification bell: an unread badge, a panel of the latest notifications, and a once-a-minute refresh while the
 * tab is visible. The server decides what is a notification; this only shows them and marks them read. */
import { el, icon } from "../../shared/js/ui.js";
import { timeAgo } from "./components.js";
import { isNotAvailable, platform } from "./platform-api.js";

const POLL_MS = 60 * 1000;

export function createBell({ onOpenLink }) {
  const badge = el("span", { class: "oc-bell__badge", hidden: true, "aria-hidden": "true" });
  const live = el("span", { class: "sr-only", role: "status", "aria-live": "polite" });
  const button = el("button", { class: "btn btn--ghost oc-bell__btn", type: "button", "aria-haspopup": "true", "aria-expanded": "false", "aria-label": "Notifications" }, icon("bell"), badge);
  const list = el("ul", { class: "oc-list oc-notes__list" });
  const empty = el("p", { class: "muted oc-notes__empty", hidden: true }, "You're all caught up.");
  const markAll = el("button", { class: "btn btn--ghost btn--sm", type: "button" }, "Mark all read");
  const panel = el("div", { class: "oc-notes card", hidden: true, role: "region", "aria-label": "Notifications" },
    el("div", { class: "oc-panel__head oc-notes__head" }, el("h2", {}, "Notifications"), markAll), list, empty);
  const node = el("div", { class: "oc-bell" }, button, panel, live);

  let unread = 0, timer = null, available = true;

  function applyTitle() {
    document.title = `${unread ? `(${unread > 99 ? "99+" : unread}) ` : ""}${document.title.replace(/^\(\d+\+?\)\s*/, "")}`;
  }
  function render(data) {
    const grew = data.unread > unread;
    unread = data.unread;
    badge.hidden = !unread;
    badge.textContent = unread > 99 ? "99+" : String(unread);
    button.setAttribute("aria-label", unread ? `Notifications, ${unread} unread` : "Notifications");
    markAll.hidden = !unread;
    empty.hidden = data.results.length > 0;
    list.replaceChildren(...data.results.map((n) => {
      const item = el("button", { class: `oc-note${n.read ? "" : " is-unread"}`, type: "button" },
        el("i", { class: "oc-note__dot", "aria-hidden": "true" }),
        el("span", { class: "oc-list__text" }, el("strong", {}, n.title), n.detail ? el("span", {}, n.detail) : null, el("small", { class: "muted" }, timeAgo(n.created_at))));
      item.addEventListener("click", async () => {
        close();
        if (!n.read) platform.markNotificationsRead([n.id]).then(render).catch(() => {});
        if (n.link) onOpenLink(n.link);
      });
      return el("li", {}, item);
    }));
    if (grew) live.textContent = `${data.unread} unread notification${data.unread === 1 ? "" : "s"}`;
    applyTitle();
  }
  async function refresh() {
    if (!available) return;
    try { render(await platform.notifications()); } catch (err) {
      if (isNotAvailable(err)) { available = false; button.disabled = true; button.title = "Notifications need the owner API"; stop(); }
    }
  }
  function open() { panel.hidden = false; button.setAttribute("aria-expanded", "true"); refresh(); }
  function close() { panel.hidden = true; button.setAttribute("aria-expanded", "false"); }
  button.addEventListener("click", () => (panel.hidden ? open() : close()));
  markAll.addEventListener("click", async () => { try { render(await platform.markNotificationsRead()); } catch { /* try again later */ } });
  document.addEventListener("click", (e) => { if (!panel.hidden && !node.contains(e.target)) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panel.hidden) { close(); button.focus(); } });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refresh(); start(); } else stop(); });

  function start() { if (!timer && available) timer = setInterval(refresh, POLL_MS); }
  function stop() { clearInterval(timer); timer = null; }
  refresh();
  start();
  return { node, applyTitle, refresh };
}
