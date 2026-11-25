# ServeFlow as an app, and order alerts

ServeFlow can be installed on a phone, tablet or computer like an app. There are three installable apps, all from the same website:

| App | Who | Installs from | Scope | Name on the home screen |
|---|---|---|---|---|
| Restaurant dashboard | Owners, managers, staff | `/restaurant-dashboard/` | `/restaurant-dashboard/` | ServeFlow |
| Marketplace | Customers | `/customer/marketplace.html` | `/customer/` | ServeFlow |
| One restaurant | That restaurant's customers | its own pages (`/customer/index.html?r=<slug>`) | `/customer/` | the restaurant's name and logo |

A restaurant owner can send customers a link or QR code; when a customer opens it and chooses **Add to Home Screen** (or the **Install** item in the
header menu), they get that restaurant's app, not the generic one. Each restaurant is a separate install (its manifest `id` is its own address).

## The install message

So nobody has to hunt through the Chrome or Safari menu, a short message slides in at the top of the page for about 6.5 seconds with **Install** and **Not now**
(on iPhone, where Safari can't be asked to install, it explains Share, then Add to Home Screen). It never shows inside the installed app. After **Not now** it stays
away for 7 days; after simply being shown it waits 20 hours. The rules live in `shared/js/install-banner.js` (`shouldShow`), the wording in `customer/js/site-nav.js`
and `restaurant-dashboard/js/pwa-boot.js`.

## Short connection blips

A page read (GET) that fails to connect, or gets a 502, 503 or 504, is tried again twice, quietly (after 0.3 s and 0.9 s), before the person sees "Can't reach the
server". Writes (placing an order, confirming a payment) are never repeated automatically. See `retryPolicy` in `shared/js/api.js`.

## What is and isn't kept offline

* **Never kept:** anything under `/api/`, `/admin/`, `/media/`, `/static/`. Orders, payments, prices and menus always come live from the server.
* Pages and scripts are fetched fresh first and only used from the phone's copy when there is no connection. So a new version is never held back.
* With no connection the app shows `/shared/offline.html` ("You're offline") instead of an error. Nothing can be ordered or confirmed offline.
* Changing the files? Nothing to bump: they are always fetched fresh. Changing the worker rules themselves means renaming the cache in `shared/js/sw-core.js`
  (`-v1`), which clears the old one.

## Order alerts on staff devices

Each device turns alerts on for itself in **Settings → Use ServeFlow as an app → Turn on alerts**. After that, every new order sends a message ("New order PRM-8K29P,
3 items") even when ServeFlow isn't open. Tapping it opens the Orders page. Alerts carry only the reference and the item count, never a customer's name or phone number.

### Switching alerts on (once, by whoever runs ServeFlow)

1. `pip install -r requirements/base.txt` (adds `pywebpush`).
2. `python manage.py generate_vapid_keys`, then put the three lines it prints in your environment (`.env`):
   `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (a secret) and `VAPID_SUBJECT` (a contact address such as `mailto:you@example.com`).
   Don't change the pair later: every device would have to turn alerts on again.
3. Restart the backend. Then in Settings press **Turn on alerts**, then **Send a test alert**.

Until the keys are set the card in Settings says alerts aren't switched on yet and nothing else changes.

### Good to know

* **HTTPS is required** for installing and alerts on a real server. `localhost` works for development without it.
* **iPhone:** alerts only work from the installed app (Share, then Add to Home Screen). The Settings card explains this on iPhone.
* **Android and computers:** alerts work from the browser too, installed or not.
* Alerts are sent from a background thread after the order is saved, so a slow push service can never delay a customer's checkout. A device the browser reports as
  gone is removed automatically. For very high volume, move `apps/restaurants/push.py::send_async` onto a proper job queue.

## API

| Route | Who | What |
|---|---|---|
| `GET /api/v1/restaurants/<slug>/manifest.webmanifest` | anyone | The restaurant's own app manifest. 404 for unknown or suspended restaurants |
| `GET /api/v1/restaurants/<slug>/push/config/` | staff | `{enabled, public_key, devices}` |
| `POST .../push/subscribe/` | staff | `{endpoint, p256dh, auth}`. Turns alerts on for that device (same device again just updates it) |
| `POST .../push/unsubscribe/` | staff | `{endpoint}`. Turns alerts off for the caller's own device |
| `POST .../push/test/` | staff | Sends a test alert to the caller's own devices. `{sent, enabled}` |
