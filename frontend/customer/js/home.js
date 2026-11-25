import { api } from "../../shared/js/api.js";
import { el, icon } from "../../shared/js/ui.js";
import { robustImage } from "../../shared/js/images.js";
import { isImageSource } from "../../shared/js/validators.js";
import { loadLastOrder } from "./cart.js";
import { telHref } from "./helpers.js";
import { AVAILABILITY, mapsHref, periodsText, ratingLabel, todayIndex } from "./marketplace-helpers.js";
import { reviewSummary } from "../../shared/js/review-helpers.js";
import { reviewMarquee } from "./review-carousel.js";
import { bootCustomer, show } from "./restaurant.js";

const SHOWN = 20; // how many of the latest reviews move across the page

const ctx = await bootCustomer();
if (ctx) {
  const { slug, restaurant } = ctx;
  const facts = el("ul", { class: "facts" });
  if (restaurant.address) facts.append(el("li", {}, icon("store"), el("span", {}, restaurant.address)));
  if (restaurant.area && restaurant.area !== restaurant.address) facts.append(el("li", {}, icon("store"), el("span", {}, restaurant.area)));
  const map = mapsHref(restaurant.latitude, restaurant.longitude);
  if (map) facts.append(el("li", {}, icon("arrow-right"), el("a", { href: map, target: "_blank", rel: "noopener noreferrer" }, "Open in maps")));
  const tel = telHref(restaurant.contact_phone);
  if (restaurant.contact_phone) {
    const label = tel ? el("a", { href: tel }, restaurant.contact_phone) : el("span", {}, restaurant.contact_phone);
    facts.append(el("li", {}, icon("user"), label));
  }

  const cover = isImageSource(restaurant.cover_url)
    ? robustImage({ src: restaurant.cover_url, className: "hero__cover", attrs: { fetchpriority: "high" }, onFail: () => hero.classList.remove("hero--cover") }) : null; // no cover: no empty frame
  const hero = el("section", { class: `card hero${cover ? " hero--cover" : ""}`, "aria-labelledby": "restaurant-title" },
    cover,
    el("h1", { id: "restaurant-title" }, restaurant.name),
    el("div", { class: "profile-meta" },
      el("span", { class: "badge", "data-status": restaurant.availability }, AVAILABILITY[restaurant.availability] ?? restaurant.availability),
      restaurant.category ? el("span", { class: "muted" }, restaurant.category.label) : null,
      el("span", { class: "muted" }, ratingLabel(restaurant.rating_average, restaurant.rating_count))),
    restaurant.description ? el("p", { class: "hero__lead" }, restaurant.description) : null,
    facts.children.length ? facts : null,
    el("div", { class: "row" },
      el("a", { class: "btn btn--primary", href: `menu.html?r=${encodeURIComponent(slug)}` },
        icon("utensils"), "View menu"),
      loadLastOrder(slug)
        ? el("a", { class: "btn btn--secondary", href: `order.html?r=${encodeURIComponent(slug)}#${loadLastOrder(slug)}` }, icon("clock"), "Track your order")
        : null,
    ),
  );

  const today = todayIndex(restaurant.timezone);
  const days = Array.isArray(restaurant.hours) ? restaurant.hours : [];
  const published = days.some((d) => d.periods.length);
  const todayText = days[today] ? periodsText(days[today].periods) : "";
  const notice = restaurant.availability === "PAUSED"
    ? "This restaurant isn't taking orders right now. You can still look at the menu."
    : restaurant.availability === "CLOSED" ? `This restaurant is closed right now. Today: ${todayText}.` : null;
  const hoursCard = published
    ? el("details", { class: "card card__pad" },
      el("summary", {}, el("strong", {}, "Opening hours"), el("span", { class: "muted" }, ` \u00b7 Today ${todayText}`)),
      el("ul", { class: "hours-list" }, ...days.map((d) => el("li", { "data-today": String(d.weekday === today) },
        el("span", {}, d.day), el("span", {}, periodsText(d.periods))))))
    : el("p", { class: "muted" }, "This restaurant hasn't published its opening hours.");
  const reviews = reviewsSection(slug, restaurant);
  show(el("div", { class: "stack" },
    notice ? el("div", { class: "alert alert--warning", role: "status" }, icon("info"), el("span", {}, notice)) : null,
    hero, hoursCard, reviews));
}

/** The latest published reviews as a moving row of cards. Only signed-in customers whose order was completed can write one, so these are real. */
function reviewsSection(slug, restaurant) {
  const holder = el("div", { class: "review-holder", "aria-live": "polite" });
  const none = () => el("p", { class: "muted" }, "No reviews yet. Customers can review a restaurant after they complete an order.");
  if (restaurant.rating_count > 0) {
    holder.append(el("div", { class: "skeleton", style: "height:8.5rem;border-radius:var(--r-lg)", "aria-hidden": "true" }));
    api.get(`/restaurants/${encodeURIComponent(slug)}/reviews/?page_size=${SHOWN}`).then((body) => {
      holder.replaceChildren(body.results.length ? reviewMarquee(body.results) : none());
    }).catch(() => holder.replaceChildren(el("p", { class: "muted" }, "Reviews couldn't be loaded right now.")));
  } else {
    holder.append(none());
  }
  return el("section", { class: "card card__pad stack", "aria-labelledby": "reviews-title" },
    el("h2", { id: "reviews-title" }, "Reviews"),
    el("p", { class: "review-summary" }, reviewSummary(restaurant.rating_average, restaurant.rating_count)),
    holder,
    restaurant.rating_count > SHOWN ? el("p", { class: "muted" }, `Showing the ${SHOWN} most recent of ${restaurant.rating_count} reviews.`) : null);
}
