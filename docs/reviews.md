# Reviews

## Who can review
Only a **signed-in customer** whose order is **COMPLETED**, **once per order** and **once per restaurant**: after someone has reviewed a restaurant, none of
their later orders from it offer a review (the page shows nothing about reviewing), and the server refuses another. The private order link (the same signed
token that lets them track the order) proves the order was theirs; the account proves who is writing. An order that isn't in anyone's account yet joins the
reviewer's account when they review it; an order that belongs to another account can't be reviewed. The public order reference is not a credential and
opens nothing. A restaurant can't write a review for itself: there is no route for it.

What the order page shows, from `review_status` on the order (also `can_review: true/false`):

| `review_status` | Meaning | The page shows |
|---|---|---|
| `can_review` | A signed-in customer, completed order, nothing reviewed yet for this order or this restaurant | The review form |
| `sign_in` | Completed and unreviewed, but the visitor isn't signed in as a customer | "Sign in to review" (it remembers the order in this tab and returns to it after signing in) |
| empty | Not completed, already reviewed, someone else's order, or this restaurant was already reviewed | Nothing (a written review is shown as it was) |

`POST /api/v1/orders/<token>/review/` with `{ "rating", "comment" }` (up to 1,000 characters) needs the customer's session and CSRF token; without a signed-in customer it
answers `401` or `403`. After a review the page shows it and it can't be changed (so a rating can't be manipulated). `409` codes: `not_reviewable` (order not completed),
`already_reviewed` (this order), `already_reviewed_restaurant` (this customer has reviewed this restaurant), `not_your_order`.
The database also enforces one review per customer per restaurant (`reviews_one_per_customer_restaurant`); reviews written before accounts were required keep no customer and are unaffected.

## What is shown
On the restaurant's page the latest published reviews (up to 20) move slowly across the page as cards; pressing on the row (or hovering with a mouse) holds it still and letting go starts it again. Every card has the same design with the reviewer's own name, stars, date and words; fewer than three reviews stay still; reduced-motion settings get a plain row to swipe.

A review shows the star rating, the comment, the date and the customer's **first name and an initial** (`Ada O.`); never a full name
or phone number. `GET /api/v1/restaurants/<slug>/reviews/` lists published reviews newest first (`page`, `page_size`, max 50).

## The rating
`rating_average` and `rating_count` on a restaurant are recomputed from its **published** reviews only, under a lock on the restaurant,
whenever a review is created, hidden or restored. Nothing else can set them (the settings API ignores them), a restaurant with no
published reviews has no rating at all, and the marketplace and restaurant page show "No reviews yet" until then.

## Moderation
* Restaurants **can't edit, hide or delete** a review. A manager or owner can **report** one (`POST .../reviews/<id>/report/`, a reason of
  5 to 300 characters, once per person). The platform owner is notified.
* The platform owner sees all reviews in the Control Centre (Reviews), filtered by status or "reported only", and can **Hide** (a reason
  is required; it leaves the page and the rating, open reports are closed, and the actor and reason go to the audit log), **Restore**, or
  **Dismiss reports**.
* Restaurant staff see their own reviews (with order references, so they can find the order) on the dashboard's Reviews page.

## Not built yet
Restaurant replies to reviews, editing a review within a short window, and photo reviews.
