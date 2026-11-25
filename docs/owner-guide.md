# Running ServeFlow as the platform owner

## Day to day
1. **Create a restaurant for a customer.** Owner Control Centre, **New restaurant**. Fill in the restaurant and its admin's email, pick the trial plan, and save. You get the admin's temporary password once; hand it to them. They sign in at the restaurant dashboard.
2. **Or let people sign themselves up.** The landing page's **Get started** goes to the prices, then sign-up, then "create your restaurant" (one per person). Their 2-day trial starts the moment it is created, on the built-in **Free trial** plan (edit its request limits in Plans & Pricing). They choose the paid plan they'll buy from Billing.
3. **When the trial ends** the restaurant stops working at once: customers can't order and staff can't change anything. The admin sees a banner and pays from **Billing** (bank details and their own payment reference).
4. **Confirm the payment.** When the transfer arrives, open **Payments**, find the reference, and **Confirm transfer**. The restaurant works again immediately.

## Managing a restaurant
Restaurants, then **Manage** on a row: edit details, change the admin's name or email, reset the admin's password, give more time, change plan, suspend or reactivate, or delete one that has no history. Everything you do is written to Audit Logs.

## Rules
- One admin per restaurant and one restaurant per admin. The admin can add managers and staff, not another owner.
- You can suspend a restaurant at any time. A restaurant that has taken orders can't be deleted, only suspended: its records are kept.

## Set up once
- `python manage.py makemigrations platform_admin` then `migrate`, then `createsuperuser` (that account is the platform owner).
- Payment details: Platform Settings, or `python manage.py set_payment_details --bank Opay --account-number <number> --account-name "<name>"`.
- Create your paid plans in Plans & Pricing before opening sign-ups, so people have something to choose. Use "Estimate the request numbers" inside the plan form to set the allowance and rate limit.
- Schedule `python manage.py sync_subscriptions` every 15 minutes.
- Pictures: restaurants upload their logo, cover and menu photos from their device. Run `pip install -r requirements/base.txt`, then `makemigrations menu restaurants` and `migrate`, and serve the `media/` folder in production. See `docs/media.md`.
- To close public sign-ups set `DJANGO_SELF_SERVICE=false`; you can still create restaurants yourself.

## Notifications
The bell (top right) tells you when a restaurant reports a transfer, signs up, has a trial ending within 24 hours, or gets locked. Click one to jump to the right page. It refreshes every minute while the tab is open.
