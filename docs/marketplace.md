# Marketplace

Customers discover restaurants, read their profile and order from the same menu and checkout as a restaurant's own link.
No account is needed to browse or to order. An order placed here follows the same rules as any other and counts toward the
same completed-order allowance (see [billing.md](billing.md)).

## Pages
* `frontend/customer/marketplace.html`: search by name, area or street; filter by category and "open now"; sort by nearest,
  name or rating; optional "Restaurants near me". Filters live in the address bar; **a location never does**.
* `frontend/customer/index.html?r=<slug>`: the restaurant profile: category, availability, rating, area, "Open in maps",
  opening hours (today highlighted, in the restaurant's timezone), reviews, and the menu/ordering links.
* Restaurant Settings (dashboard): a **Marketplace** card (listed on/off, category, area, coordinates with "Use my current
  location") and an **Opening hours** card (one box per day, like `09:00-14:00, 17:00-22:00`). Managers and owners edit; staff read.

## Location is optional
The browser only asks for location when the customer taps "Restaurants near me". It stays in memory for that page view: not
stored, not in the URL. If it is blocked, unavailable or times out, the page says why and the area search keeps working.
Restaurants without coordinates still appear in name, area and category searches (last when sorting by distance), and
are left out when a distance limit is set.

## API (public, no sign-in, throttled by the `marketplace` scope)
| Route | Purpose |
|---|---|
| `GET /api/v1/marketplace/restaurants/` | Search. Params: `q`, `area`, `category`, `lat`+`lng`, `radius_km`, `open_now`, `ordering` (`distance`, `name`, `rating`), `page`, `page_size` (max 48) |
| `GET /api/v1/marketplace/categories/` | Categories that have listed restaurants, with counts |
| `GET /api/v1/marketplace/areas/` | Areas that have listed restaurants (for the area suggestions) |
| `GET /api/v1/restaurants/<slug>/` | The restaurant profile (now includes category, area, coordinates, availability, hours, rating) |
| `GET/PUT /api/v1/restaurants/<slug>/hours/` | Opening hours; PUT replaces all periods (manager or owner) |
| `PATCH /api/v1/restaurants/<slug>/settings/` | Also sets `category`, `area`, `latitude`, `longitude`, `listed_in_marketplace` |

Bad input is a 400 with the usual error envelope (for example a latitude without a longitude, or sorting by distance with no location).

## Who is listed
A restaurant appears only when its owner switched "Show in the marketplace" on (off by default), it is not suspended, and its
subscription is not locked (the same rule the billing middleware uses). Listing needs an address or area.

## Hours and availability
Periods are per weekday in the restaurant's own timezone and cannot cross midnight (split a late night at midnight).
`availability` is `PAUSED` when the restaurant switched orders off, `CLOSED` outside published hours, otherwise `OPEN`. A
restaurant with no published hours is shown as open whenever orders are on. `open_now` uses the same rule.

## Ratings
`rating_average` and `rating_count` are read-only and stay empty ("No reviews yet") until the reviews feature fills them from
completed orders. Nothing is invented and no API can set them.

## Distance
Haversine in the database with a bounding-box prefilter on an indexed (latitude, longitude) pair: ordinary arithmetic, no extra
infrastructure. To move to PostGIS later, replace `distance_km` and `within` in `apps/marketplace/search.py`.

## Not yet built
Customer accounts and order history, reviews and moderation, the late-pickup policy, and a quota-aware "temporarily
unavailable" state in the list (a restaurant at its order limit still shows as open; checkout then explains).
