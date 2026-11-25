/* Reviews as a gently moving row of cards. The row drifts sideways on its own; pressing on it (or hovering with a mouse) stops it so a
 * review can be read, and letting go sets it moving again. Every review is its own card with the same design; only the name,
 * the stars, the date and the words change. Fewer than three reviews don't move (there would be gaps); people who ask their device for
 * less motion get a plain row they can swipe. */
import { el, icon } from "../../shared/js/ui.js";
import { reviewDate } from "../../shared/js/review-helpers.js";

export const MIN_TO_MOVE = 3;

/** The first letter shown in the round badge. */
export const initialOf = (name) => (String(name ?? "").trim()[0] ?? "C").toUpperCase();

/** Seconds for one full pass: slower with more cards, so each one stays readable. */
export const loopSeconds = (count) => Math.max(24, count * 7);

const stars = (rating) => {
  const n = Number.isInteger(rating) && rating >= 1 && rating <= 5 ? rating : 0;
  return el("span", { class: "review-card__stars", role: "img", "aria-label": `${n} out of 5` },
    ...Array.from({ length: 5 }, (_, i) => el("span", { class: i < n ? "star star--on" : "star" }, icon("star"))));
};

export function reviewCard(review) {
  return el("article", { class: "review-card" },
    el("header", { class: "review-card__head" },
      el("span", { class: "review-card__avatar", "aria-hidden": "true" }, initialOf(review.display_name)),
      el("div", { class: "review-card__who" }, el("strong", {}, review.display_name), el("small", {}, reviewDate(review.created_at))),
      stars(review.rating)),
    review.comment ? el("p", { class: "review-card__text" }, review.comment) : el("p", { class: "review-card__text review-card__text--quiet" }, "Left a rating without a comment."));
}

/** The moving (or, for a few reviews, still) row. */
export function reviewMarquee(reviews) {
  const moving = reviews.length >= MIN_TO_MOVE;
  const group = (hidden) => el("div", { class: "review-marquee__group", "aria-hidden": hidden ? "true" : null }, ...reviews.map(reviewCard));
  const track = el("div", { class: "review-marquee__track", style: `--loop:${loopSeconds(reviews.length)}s` }, group(false), ...(moving ? [group(true)] : []));
  const root = el("div", { class: "review-marquee", "data-moving": String(moving), "data-paused": "false", role: "region", "aria-label": "Customer reviews" }, track);
  if (moving) {
    const pause = () => root.setAttribute("data-paused", "true");
    const resume = () => root.setAttribute("data-paused", "false");
    root.addEventListener("pointerdown", pause);   // a finger or a mouse button is down on it: hold still
    root.addEventListener("pointerup", resume);    // let go: move on
    root.addEventListener("pointercancel", resume);
    root.addEventListener("pointerleave", resume);
    root.addEventListener("focusin", pause);       // keyboard users reading a card
    root.addEventListener("focusout", resume);
  }
  return root;
}
