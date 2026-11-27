# Deploying ServeFlow: Neon (database), Render (backend), Vercel (frontend)

```
Browser --> Vercel (static pages) --/api/v1, /static (rewrite)--> Render (Django) --> Neon (PostgreSQL)
                                                                  \--> Cloudinary (pictures)
```
The browser only ever talks to your Vercel address. Vercel forwards `/api/v1/` and `/static/` to Render (uploaded pictures come straight from Cloudinary), so the site stays
**one origin**: session cookies and CSRF work exactly as they do on your computer, and no CORS setup is needed.

## 1. Neon (database)
1. Create a project. Pick the region closest to your Render region.
2. Open **Connect** and copy **two** connection strings (turn "Connection pooling" on and off):
   - **Pooled** (host contains `-pooler`) -> becomes `DATABASE_URL`. The app uses this.
   - **Direct** (no `-pooler`) -> becomes `DIRECT_DATABASE_URL`. Only migrations use this.
3. Keep `?sslmode=require` on both. The code detects the pooled address and switches off server-side cursors and prepared statements by itself.

## 2. Render (backend)
1. Push the repo to GitHub, then **New > Blueprint** and pick it. Render reads `render.yaml` (a web service on the Starter plan).
2. Fill in the variables Render asks for:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(64))"` (must be 50+ characters) |
| `DATABASE_URL` / `DIRECT_DATABASE_URL` | the two Neon strings |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://your-app.vercel.app` (add your own domain later, comma separated) |
| `DJANGO_ADMIN_URL` | something non-obvious, e.g. `manage-7f3k/` (only matters if you switch the Django admin on, see below) |
| `CLOUDINARY_URL` | from Cloudinary: Dashboard > API Keys, copy the "API environment variable": `cloudinary://API_KEY:API_SECRET@CLOUD_NAME` |
| `PAYMENT_WEBHOOK_SECRET`, `VAPID_*` | optional (see `.env.example`) |

   Already set by the blueprint: `DJANGO_ENV=production`, `DJANGO_TRUST_PROXY_SSL_HEADER=True`, `DJANGO_NUM_PROXIES=2`,
   The Render host name is allowed automatically.
3. Deploy. The build installs packages and runs `collectstatic`; each start runs `migrate` (on the direct Neon address) and then gunicorn.
4. Check `https://YOUR-SERVICE.onrender.com/healthz` answers `ok`.
5. Create your owner account from your own computer, pointed at Neon:
   ```
   cd backend
   DJANGO_ENV=development DJANGO_SECRET_KEY=x DATABASE_URL="<direct Neon string>" python manage.py createsuperuser
   ```
   (On Windows PowerShell set the variables first with `$env:DATABASE_URL="..."`.)

## 3. Vercel (frontend)
1. **Add New > Project**, pick the repo, set **Root Directory** to `frontend`, Framework Preset **Other**, leave build and output empty.
2. Before deploying, open `frontend/vercel.json` and replace `YOUR-SERVICE.onrender.com` (three places) with your Render host name. Commit.
3. Deploy, then put the resulting `https://....vercel.app` address into Render's `DJANGO_CSRF_TRUSTED_ORIGINS` and redeploy the backend.
4. `frontend/shared/js/config.js` needs no change: `apiBaseUrl` is already `/api/v1` (same origin).

## 4. Check it works
- Landing page loads and the pricing section shows your plans (that proves Vercel -> Render -> Neon).
- Sign up, create a restaurant, upload a logo, place a guest order, confirm it on the dashboard.
- Redeploy the backend and confirm the logo is still there. In Cloudinary, Media Library, you should see `restaurants/<id>/logo/...`.
- Try 6 wrong logins in a row: you should be throttled. If you never are, `DJANGO_NUM_PROXIES` is wrong for your setup.

## Things to know
- **Uploaded pictures live on Cloudinary** (folder `restaurants/<id>/...`), so redeploys never lose them and the browser loads them from Cloudinary's CDN. Every upload is already resized and re-encoded as WebP by ServeFlow before it is sent. Check your Cloudinary plan's storage and bandwidth limits as you grow. Pictures uploaded on your computer during testing are not copied over: upload them again on the live site.
- Without `CLOUDINARY_URL` the backend falls back to local disk (`DJANGO_MEDIA_ROOT` + `DJANGO_SERVE_MEDIA=True`), which on Render needs a paid persistent disk.
- **One gunicorn worker (with 8 threads).** Throttle counters live in memory, so more workers would each keep their own and weaken the limits. Move to a shared cache (Redis or the database cache) before scaling out.
- **Free-tier sleep.** A free Render service sleeps when idle and the first request after can take about a minute (people will see "can't connect to the server"). Use a paid plan for real users, or ping `/healthz` every few minutes.
- **Neon** pauses an idle free database; the first query after a pause is slower. Check Neon's backup/restore window for your plan.
- **Platform owner dashboard:** open `https://your-app.vercel.app/owner-control-centre/`. The Django admin is at `https://YOUR-SERVICE.onrender.com/<DJANGO_ADMIN_URL>`.
- HSTS starts at one hour (`DJANGO_SECURE_HSTS_SECONDS`). Raise it once everything is confirmed on HTTPS.

## Security settings added after the audit
- **Django admin is OFF in production.** The Owner Control Centre covers daily work. To use the admin, set `DJANGO_ADMIN_ENABLED=True` (and a custom `DJANGO_ADMIN_URL`). When on, 5 wrong passwords for one email, or 20 from one address, lock the admin login for 15 minutes.
- **`DJANGO_NUM_PROXIES` is now required** whenever `DJANGO_TRUST_PROXY_SSL_HEADER=True` (the app refuses to start without it). It is how many proxies of yours sit in front of Django, counted from the right of `X-Forwarded-For`: Render alone = 1, Vercel then Render = 2. Anything a visitor writes in that header is ignored. **Limit:** with Vercel in front, someone who calls the Render address directly can still choose their own address. The sign-up and per-restaurant order limits do not depend on addresses, but for strong per-address limits give Render its own domain (for example `api.yourdomain.com` next to `app.yourdomain.com`) and set the count to 1.
- **Marketplace needs your approval.** A restaurant that switches the marketplace on waits until you press "Approve for marketplace" in the Owner Control Centre (you also get a notification). After upgrading, run once, on the live database: `python manage.py approve_marketplace --already-listed` so restaurants that were already listed stay listed. You are also notified when a restaurant changes its bank details.
- **Order capacity:** an order counts against the allowance when it is marked paid (not only when it completes). Marking a payment as received is refused with `ORDER_LIMIT_REACHED` once paid orders would exceed what is left.
- **Order alerts** accept only real browser push services (Google, Mozilla, Apple, Microsoft), at most 10 devices per person per restaurant. Add another service with `DJANGO_PUSH_EXTRA_HOSTS=host1,host2`.
- **Database change:** `marketplace_approved` is a new column on Restaurant. Run `python manage.py makemigrations restaurants`, review it, then `migrate`.
