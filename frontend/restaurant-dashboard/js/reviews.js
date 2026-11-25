/* What customers said about this restaurant. Reviews come only from completed orders and nobody here can edit or delete one.
 * A manager or owner can report a review to ServeFlow; the platform owner decides whether to hide it. */
import { ApiError, api } from "../../shared/js/api.js";
import { el, emptyState, icon, setBusy, toast } from "../../shared/js/ui.js";
import { reviewDate, reviewSummary, starText } from "../../shared/js/review-helpers.js";
import { formDialog } from "./form-dialog.js";
import { hasRole } from "./session.js";
import { bootDashboard, handleSessionExpiry } from "./shell.js";

const HREF = "reviews.html";
const content = document.getElementById("content");

const skeleton = () => el("div", { class: "card card__pad stack", "aria-hidden": "true" },
  ...[70, 55, 62].map((w) => el("div", { class: "skeleton skeleton--line", style: `width:${w}%;height:1.25rem` })));

async function main() {
  const ctx = await bootDashboard({ href: HREF, minRole: "STAFF" });
  if (!ctx) return;
  const slug = encodeURIComponent(ctx.restaurant.slug);
  const canReport = hasRole(ctx.role, "MANAGER");
  const rows = el("div", { class: "stack" });
  const more = el("button", { class: "btn btn--secondary", type: "button", hidden: true }, "Load more");
  const summary = el("p", { class: "muted" });
  let next = null;

  const fail = (err) => {
    if (handleSessionExpiry(err, HREF)) return;
    toast(err instanceof ApiError ? err.message : "Something went wrong.", { type: "error" });
  };

  async function report(review) {
    const saved = await formDialog({
      title: "Report this review",
      description: "Tell ServeFlow what is wrong, for example that it is abusive, not about your restaurant, or not from a real customer. You can't change or remove a review yourself; ServeFlow will look at it.",
      submitLabel: "Send report",
      fields: [{ name: "reason", label: "What is wrong?", type: "textarea", required: true, maxlength: 300, hint: "A few words are enough." }],
      values: {},
      submit: (v) => api.post(`/restaurants/${slug}/reviews/${review.id}/report/`, { reason: v.reason.trim() }),
    });
    if (saved) {
      toast("Reported. ServeFlow will take a look.", { type: "success" });
      await load();
    }
  }

  const card = (r) => el("article", { class: "card card__pad stack review-card" },
    el("div", { class: "review__head" },
      el("span", { class: "stars", role: "img", "aria-label": `${r.rating} out of 5` }, starText(r.rating)),
      el("strong", {}, r.display_name), el("small", { class: "muted" }, `${reviewDate(r.created_at)} · order ${r.order_reference}`),
      r.status === "HIDDEN" ? el("span", { class: "badge", "data-status": "CLOSED" }, "Hidden by ServeFlow") : null,
      r.open_reports > 0 ? el("span", { class: "badge", "data-status": "PAUSED" }, "Reported") : null),
    r.comment ? el("p", {}, r.comment) : el("p", { class: "muted" }, "No comment, rating only."),
    canReport && r.status === "PUBLISHED" && r.open_reports === 0
      ? el("div", {}, el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: () => report(r) }, "Report this review")) : null);

  async function load({ append = false } = {}) {
    if (append) setBusy(more, true); else { rows.replaceChildren(skeleton()); more.hidden = true; }
    try {
      const body = await api.get(append ? next : `/restaurants/${slug}/reviews/inbox/`);
      const link = body.next ? new URL(body.next, location.href) : null;
      next = link ? link.pathname.replace(/^\/api\/v1/, "") + link.search : null;
      const cards = body.results.map(card);
      if (append) rows.append(...cards);
      else rows.replaceChildren(...(cards.length ? cards : [emptyState({
        iconName: "smile", title: "No reviews yet",
        text: "After a customer's order is completed they can leave a rating here. Nothing is shown until a real customer writes it.",
      })]));
      more.hidden = !next;
    } catch (err) {
      if (!append) rows.replaceChildren(emptyState({
        iconName: "alert", title: "Couldn't load reviews", text: err instanceof ApiError ? err.message : "Something went wrong.",
        action: el("button", { class: "btn btn--secondary", type: "button", onclick: () => load() }, icon("refresh"), "Try again"),
      }));
      fail(err);
    } finally {
      setBusy(more, false);
    }
  }
  more.addEventListener("click", () => load({ append: true }));

  content.replaceChildren(summary, rows, el("div", { class: "row row--center" }, more));
  api.get(`/restaurants/${slug}/reviews/?page_size=1`)
    .then((b) => { summary.textContent = reviewSummary(b.average, b.count); })
    .catch(() => {});
  await load();
}

main();
