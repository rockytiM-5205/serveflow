# Testing ServeFlow on your phone (install, alerts, offline)

A phone only lets a website be **installed** or send **alerts** when the site is on **HTTPS** or is **`localhost`**. Your computer's Wi-Fi address
(`http://192.168...`) is neither, so installing won't work through it. Use one of these three ways.

Before you start: Django and the frontend are running as usual (`python manage.py runserver`, `py frontend\dev_server.py`) and your `.env` has
`DJANGO_ENV=development`. **Restart Django once** after updating, because the settings are read at start-up.

## Way 1: an HTTPS tunnel (any phone, Android or iPhone). Easiest.

1. Install Cloudflare's free tool once. Windows: `winget install --id Cloudflare.cloudflared`, then close and reopen the terminal.
2. In a third terminal: `cloudflared tunnel --url http://localhost:5173`
3. It prints an address like `https://random-words.trycloudflare.com`. Open it on your phone, for example:
   * `…/customer/marketplace.html` (the marketplace app)
   * `…/customer/index.html?r=<restaurant-slug>` (one restaurant's own app)
   * `…/restaurant-dashboard/login.html` (the dashboard app)
4. Nothing else to set up: development settings already accept tunnel addresses (`trycloudflare.com`, `ngrok-free.app`, `loca.lt`).

The address changes every time you start the tunnel, and each new address is a separate app to install. Close the tunnel when you're done; anyone with the address can open your local site while it runs.

## Way 2: USB cable (Android only, no internet tool needed)

1. On the phone: Settings, About phone, tap **Build number** 7 times, then Settings, Developer options, turn on **USB debugging**. Plug in the cable and allow the computer.
2. On the computer, open Chrome and go to `chrome://inspect/#devices`. Tick **Discover USB devices**, press **Port forwarding**, add port `5173` with address `localhost:5173`, and tick **Enable port forwarding**.
3. On the phone, open Chrome and go to `http://localhost:5173/customer/marketplace.html`. To the phone, `localhost` is your computer, and that counts as secure.

## Way 3: same Wi-Fi, Android only

1. Run the frontend with `py frontend\dev_server.py --host 0.0.0.0` and let it through the Windows firewall if asked.
2. Find your computer's address with `ipconfig` (the IPv4 line, say `192.168.1.23`) and add it to `DJANGO_ALLOWED_HOSTS` in `.env` (`localhost,127.0.0.1,192.168.1.23`), then restart Django.
3. On the phone's Chrome open `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, type `http://192.168.1.23:5173`, set it to **Enabled**, and relaunch Chrome.
4. Open `http://192.168.1.23:5173/customer/marketplace.html`. iPhones can't do this one: use Way 1.

## What to check

1. **The install message.** A bar drops in at the top for about 6.5 seconds with **Install** and **Not now**. Tap **Install**, then look for the ServeFlow icon on the home screen.
   To see it again without waiting, add `?showInstall=1` to the address (on a restaurant page: `…index.html?r=<slug>&showInstall=1`).
2. **The menu.** The header **Menu** button has an **Install** item too.
3. **One restaurant's own app.** Open `…/customer/index.html?r=<slug>` and install. The home-screen name should be that restaurant's name.
4. **Offline.** Open the installed app, switch on airplane mode, and reopen it. You should see "You're offline", never an old menu or order.
5. **Alerts.** On the installed dashboard app: Settings, **Use ServeFlow as an app**, **Turn on alerts**, then **Send a test alert**. This needs the one-time keys
   (see `docs/pwa-and-alerts.md`: `pip install -r requirements/base.txt`, `python manage.py generate_vapid_keys`, put the lines in `.env`, restart Django).
   Then place an order from a second phone or tab and the first should buzz.
6. **iPhone.** Safari, Share, **Add to Home Screen**. Alerts only work from the installed app, on iOS 16.4 or newer.

## If something doesn't work

| What you see | Why, and what to do |
|---|---|
| No install bar or install item | The address isn't `https://…` or `localhost`. Chrome and Edge only (and Safari's Share route). Not in a private tab. Try `?showInstall=1`. |
| Still nothing | On your computer's Chrome open the same tunnel address, press F12, then **Application**, then **Manifest**. It lists exactly what is missing. |
| "Bad Request (400)" | Django didn't accept the address. Restart Django, and check `DJANGO_ENV=development`. |
| "CSRF verification failed" when signing in | Same cause: restart Django on the development settings, and use the `https://` tunnel address, not `http://`. |
| The tunnel opens but the page won't load | Make sure `dev_server.py` is running on 5173 and the tunnel points to `http://localhost:5173`. |
| Alerts button says "not switched on yet" | The VAPID keys aren't set, or Django wasn't restarted after setting them. |
