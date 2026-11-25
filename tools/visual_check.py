"""Open ServeFlow's real pages in a headless browser with the API replaced by sample data, at phone and desktop sizes.

    pip install playwright && playwright install chromium
    python tools/visual_check.py            # writes screenshots to tools/visual_out/ and reports any horizontal overflow
    python tools/visual_check.py customer   # only one experience: customer, workspace or owner

The sample data lives only in this file. It is used to see layouts (long names, empty lists, many orders); it is never shipped.
"""
import http.server
import json
import re
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent / "frontend"
OUT = Path(__file__).resolve().parent / "visual_out"
VIEWPORTS = {"phone": (390, 844), "small": (320, 640), "tablet": (768, 1024), "desktop": (1280, 800)}

# Until the real fonts are fetched (tools/fetch_fonts.py), stand in Inter (a near twin of Geist) so screenshots look like the product.
FONT_STANDIN = """
@font-face { font-family: "Geist"; src: local("Inter"), local("Inter Variable"); font-weight: 100 900; }
@font-face { font-family: "Plus Jakarta Sans"; src: local("Inter"), local("Inter Variable"); font-weight: 100 900; }
"""

NOW = "2026-11-17T12:30:00Z"


def _sample_photo():
    """A stand-in food photo (a plate of rice and tomatoes) so the photo path can be seen."""
    import io
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (240, 240), "#7c4a1e")
    d = ImageDraw.Draw(im)
    d.ellipse([20, 20, 220, 220], fill="#f4e9d8")
    d.ellipse([50, 60, 190, 190], fill="#e0541b")
    for x, y in [(80, 90), (120, 80), (150, 120), (100, 140), (140, 160), (90, 120)]:
        d.ellipse([x - 9, y - 6, x + 9, y + 6], fill="#ffd9a0")
    d.ellipse([140, 50, 190, 100], fill="#2f8f3a")
    buf = io.BytesIO(); im.save(buf, "PNG"); return buf.getvalue()


SAMPLE_PHOTO = _sample_photo()
CARD = lambda i, name, area, cat, avail="OPEN", rating=None, count=0: {
    "slug": f"place-{i}", "name": name, "description": "Home-style rice, stews and grills cooked to order.", "category": {"value": cat.upper(), "label": cat},
    "area": area, "address": "12 Market Road", "logo_url": None, "cover_url": None, "distance_km": None, "availability": avail,
    "is_open_now": None, "rating_average": rating, "rating_count": count, "pickup_enabled": True, "dine_in_enabled": True}
RESTAURANTS = [CARD(1, "Mama Put Kitchen", "Akungba", "African", "OPEN", 4.6, 23), CARD(2, "The Very Long Restaurant Name And Grill Ltd", "Oba Ile", "Grills", "PAUSED"),
               CARD(3, "Green Bowl", "Akungba", "Healthy", "OPEN", 4.2, 8), CARD(4, "Suya Spot", "Ikare", "Grills", "CLOSED")]
ITEMS = [("Jollof rice", "2500.00", "spoon"), ("Pounded yam and egusi soup", "3500.00", "portion"), ("Grilled chicken", "4200.00", "piece"), ("Fried plantain", "800.00", "portion"),
         ("Pepper soup with assorted meat", "3000.00", "bowl"), ("Zobo drink", "600.00", "bottle")]
MENU = {"restaurant": {"currency": "NGN", "name": "Mama Put Kitchen"}, "categories": [
    {"id": 1, "name": "Mains", "items": [{"id": i + 1, "name": n, "description": "Freshly prepared and served hot.", "price": p, "unit_name": u, "is_available": i != 3, "image_url": None} for i, (n, p, u) in enumerate(ITEMS[:4])]},
    {"id": 2, "name": "Soups and drinks", "items": [{"id": i + 11, "name": n, "description": "", "price": p, "unit_name": u, "is_available": True, "image_url": None} for i, (n, p, u) in enumerate(ITEMS[4:])]}]}
RESTAURANT = {"slug": "mama-put", "name": "Mama Put Kitchen", "description": "Home-style rice, stews and grills cooked to order.", "category": {"value": "AFRICAN", "label": "African"}, "area": "Akungba",
              "address": "12 Market Road, Akungba-Akoko", "contact_phone": "+2348012345678", "logo_url": None, "cover_url": None, "currency": "NGN", "timezone": "Africa/Lagos",
              "availability": "OPEN", "accepting_orders": True, "pickup_enabled": True, "dine_in_enabled": True, "requires_table_number": False, "pickup_fee": "150.00",
              "rating_average": 4.6, "rating_count": 23, "hours": [], "is_open_now": True, "reviews": []}
ME = {"user": {"email": "owner@example.com", "first_name": "Ada", "last_name": "Obi"}, "can_create_restaurant": True,
      "memberships": [{"role": "OWNER", "restaurant": {"slug": "mama-put", "name": "Mama Put Kitchen", "is_active": True}}]}


def order(i, status, pay, name, total, items):
    return {"public_id": f"00000000-0000-4000-8000-{i:012d}", "reference": f"PRM-{['8K29P','3M7TZ','W4N6D','9XQ2B','H5T8C','A2J7K'][i % 6]}", "code": f"PRM-{i}", "status": status, "payment_status": pay,
            "customer_name": name, "fulfilment_type": "PICKUP" if i % 2 else "DINE_IN", "table_number": None if i % 2 else "4", "pickup_at": None, "currency": "NGN", "total": total,
            "created_at": NOW, "late_fee": None, "late_fee_status": None, "late_free_until": None, "refund_due": False,
            "items": [{"item_name": n, "quantity": q, "unit_name": "", "unit_price": "1000.00", "line_total": f"{q * 1000}.00"} for n, q in items]}
ORDERS = [order(0, "PENDING", "CLAIMED", "Ada Okafor", "6000.00", [("Jollof rice", 2), ("Zobo drink", 1)]), order(1, "CONFIRMED", "PAID", "Tunde", "2500.00", [("Jollof rice", 1)]),
          order(2, "SERVING", "PAID", "Ngozi Adeyemi", "7500.00", [("Grilled chicken", 2), ("Fried plantain", 3)]), order(3, "READY_FOR_PICKUP", "PAID", "Ibrahim", "4200.00", [("Grilled chicken", 1)]),
          order(4, "PENDING", "UNPAID", "Chioma", "3500.00", [("Pounded yam and egusi soup", 1)])]

# (page, route-regex -> payload). First match wins; anything else under /api/v1/ gets an empty 200 so pages still draw.
SCENARIOS = {
    "customer": [
        ("marketplace", "/customer/marketplace.html", {r"/marketplace/restaurants/": {"count": 4, "page": 1, "page_size": 12, "has_next": False, "results": RESTAURANTS},
                                                       r"/marketplace/categories/": {"results": [{"value": "AFRICAN", "label": "African", "count": 1}, {"value": "GRILLS", "label": "Grills", "count": 2}]},
                                                       r"/marketplace/areas/": {"results": [{"area": "Akungba", "count": 2}]}}),
        ("restaurant", "/customer/index.html?r=mama-put", {r"/restaurants/mama-put/menu/": MENU, r"/restaurants/mama-put/": RESTAURANT}),
        ("menu", "/customer/menu.html?r=mama-put", {r"/restaurants/mama-put/menu/": MENU, r"/restaurants/mama-put/": RESTAURANT}),
    ],
    "workspace": [
        ("orders", "/restaurant-dashboard/orders.html", {r"/restaurants/mama-put/orders/": {"next": None, "previous": None, "results": ORDERS}, r"/restaurants/mama-put/$": RESTAURANT}),
        ("menu-manage", "/restaurant-dashboard/menu.html", {r"/menu/categories/": [{"id": 1, "name": "Mains", "position": 0, "is_active": True}, {"id": 2, "name": "Soups and drinks", "position": 1, "is_active": True}],
                                                          r"/menu/items/": [dict(it, category=1 if it["id"] < 10 else 2, image_url=None) for c in MENU["categories"] for it in c["items"]], r"/restaurants/mama-put/$": RESTAURANT}),
        ("team", "/restaurant-dashboard/team.html", {r"/members/": {"next": None, "previous": None, "results": [{"id": 1, "role": "OWNER", "user": {"email": "owner@example.com", "first_name": "Ada", "last_name": "Obi"}, "is_active": True},
                                                                   {"id": 2, "role": "STAFF", "user": {"email": "tunde.adeyemi.longemailaddress@example.com", "first_name": "Tunde", "last_name": "Adeyemi"}, "is_active": True}]}}),
    ],
}
def days(n, f):
    return [{"date": f"2026-11-{d:02d}", "total": f(d), "errors": d % 3} for d in range(4, 4 + n)]


OVERVIEW = {"totals": {"customers": 12, "active_subscriptions": 8, "trials_running": 3, "trials_ending_soon": 1, "mrr": {"amount": "60000.00", "currency": "NGN"}, "api_requests": 412000,
                       "completed_orders": 1840, "subscription_revenue": {"amount": "45000.00", "currency": "NGN"}, "order_pack_revenue": {"amount": "12000.00", "currency": "NGN"},
                       "failed_payments": 1, "payments_awaiting": 2, "expired_subscriptions": 1, "error_rate": 0.0042},
            "previous": {"customers": 9, "api_requests": 380000, "completed_orders": 1600},
            "series": {"completed_orders": days(14, lambda d: 40 + (d * 7) % 60), "requests": days(14, lambda d: 9000 + (d * 913) % 5000)},
            "subscription_status": {"ACTIVE": 8, "TRIAL": 3, "EXPIRED": 1},
            "attention": [{"type": "payment_awaiting", "name": "Mama Put Kitchen", "detail": "A transfer of ₦7,500 is waiting to be confirmed"}],
            "recent_activity": [{"type": "payment.confirmed", "summary": "Payment SF-8K29PQ2M confirmed", "occurred_at": NOW}],
            "recent_customers": [{"name": "Green Bowl", "account_id": "SF-100234", "plan_name": "Pro", "subscription_status": "ACTIVE", "registered_at": NOW},
                                 {"name": "The Very Long Restaurant Name And Grill Ltd", "account_id": "SF-100235", "plan_name": "Starter", "subscription_status": "TRIAL", "registered_at": NOW}]}
CUSTOMERS = {"count": 2, "next": None, "previous": None, "results": [
    {"name": "Green Bowl", "account_id": "SF-100234", "admin_email": "owner@greenbowl.example", "plan": {"name": "Pro"}, "subscription_status": "ACTIVE", "subscription_ends_at": NOW, "requests_30d": 18200, "status": "ACTIVE"},
    {"name": "The Very Long Restaurant Name And Grill Ltd", "account_id": "SF-100235", "admin_email": "a.very.long.email.address@restaurant-example.com", "plan": {"name": "Starter"}, "next_plan": {"name": "Pro"},
     "subscription_status": "TRIAL", "subscription_ends_at": NOW, "requests_30d": 410, "status": "ACTIVE"}]}
OWNER_ME = {"user": {"email": "owner@serveflow.example", "first_name": "Ada", "last_name": "Obi"}}
SCENARIOS["owner"] = [
    ("overview", "/owner-control-centre/index.html#/", {r"/platform/me/": OWNER_ME, r"/platform/overview/": OVERVIEW}),
    ("restaurants", "/owner-control-centre/index.html#/customers", {r"/platform/me/": OWNER_ME, r"/platform/customers/": CUSTOMERS, r"/platform/plans/": {"results": []}}),
]

TOKEN = "b" * 96
ORDER_PAGE = {"reference": "PRM-8K29P", "status": "PENDING", "payment_status": "UNPAID", "fulfilment_type": "PICKUP", "table_number": None, "pickup_at": "2026-11-17T14:00:00Z",
              "pickup_fee": "150.00", "currency": "NGN", "subtotal": "6000.00", "total": "6150.00", "restaurant": {"slug": "mama-put", "name": "Mama Put Kitchen"},
              "payment": {"amount": "6150.00", "currency": "NGN", "reference": "PRM-8K29P", "bank_name": "First Bank", "account_name": "Mama Put Kitchen Ltd", "account_number": "0123456789", "instructions": "Use the order ID as your reference."},
              "review": None, "can_review": False, "pickup_policy": None, "late_fee": None, "cancellable": True,
              "items": [{"name": "Jollof rice", "unit_name": "spoon", "unit_price": "2500.00", "quantity": 2, "line_total": "5000.00"}, {"name": "Zobo drink", "unit_name": "bottle", "unit_price": "1000.00", "quantity": 1, "line_total": "1000.00"}],
              "timeline": [{"status": "PENDING", "at": NOW}], "created_at": NOW, "updated_at": NOW}
def order_at(status):
    chain = ["PENDING", "CONFIRMED", "SERVING", "READY_FOR_PICKUP", "COMPLETED"]
    reached = chain[: chain.index(status) + 1] if status in chain else ["PENDING", status]
    big = dict(ORDER_PAGE, status=status, payment_status="UNPAID" if status == "PENDING" else "PAID", payment=None if status != "PENDING" else ORDER_PAGE["payment"], cancellable=False,
               timeline=[{"status": x, "at": NOW} for x in reached],
               items=[{"name": "Jollof rice", "unit_name": "spoon", "unit_price": "2500.00", "quantity": 2, "line_total": "5000.00", "image_url": "/media/menu/jollof.png", "dish_kind": "", "category": "Mains"},
                      {"name": "Mama's special", "unit_name": "", "unit_price": "4200.00", "quantity": 1, "line_total": "4200.00", "image_url": None, "dish_kind": "", "category": "Specials"},
                      {"name": "Chef's surprise", "unit_name": "", "unit_price": "800.00", "quantity": 1, "line_total": "800.00", "image_url": None, "dish_kind": "", "category": "Specials"},
                      {"name": "Local brew", "unit_name": "", "unit_price": "600.00", "quantity": 2, "line_total": "1200.00", "image_url": None, "dish_kind": "", "category": "Drinks"},
                      {"name": "House platter", "unit_name": "", "unit_price": "3000.00", "quantity": 1, "line_total": "3000.00", "image_url": None, "dish_kind": "fish", "category": "Specials"}])
    return big


# Frames of the order animation, taken at these times (ms after the page loads)
ANIM_FRAMES = [250, 700, 1300, 2000, 3000, 4500]
for _status in ("PENDING", "CONFIRMED", "SERVING", "READY_FOR_PICKUP", "COMPLETED", "CANCELLED"):
    SCENARIOS.setdefault("anim", []).append((f"{_status.lower()}", f"/customer/order.html?r=mama-put#{'b' * 96}", {rf"/orders/{'b' * 96}/": order_at(_status)}))
SIGNED_OUT = ({"error": {"code": "not_authenticated", "message": "Sign in."}}, 401)
CUSTOMER_ME = {"email": "peter@example.com", "first_name": "Peter", "last_name": "Obi", "phone": "+2348012345678"}
REVIEWS = {"count": 6, "page": 1, "page_size": 20, "has_next": False, "results": [
    {"display_name": "Peter", "rating": 4, "comment": "", "created_at": NOW}, {"display_name": "Peter", "rating": 4, "comment": "Great", "created_at": NOW},
    {"display_name": "samuel", "rating": 3, "comment": "", "created_at": NOW}, {"display_name": "Ajiloseda A.", "rating": 4, "comment": "fast and accurate", "created_at": NOW},
    {"display_name": "Peter", "rating": 4, "comment": "it has been so helpful, thanks for the quick service and the food was still hot when I got there", "created_at": NOW},
    {"display_name": "Ngozi O.", "rating": 5, "comment": "Best jollof in town. I come every Friday.", "created_at": NOW}]}
BROKEN_IMAGES = dict(RESTAURANT, logo_url="/media/missing-logo.png", cover_url="/media/missing-cover.png", rating_count=6, rating_average=3.8)
MY_ORDERS = {"count": 3, "next": None, "previous": None, "results": [
    {"public_id": "p1", "reference": "PRM-8K29P", "status": "SERVING", "payment_status": "PAID", "fulfilment_type": "DINE_IN", "pickup_at": None, "total": "750.00", "currency": "NGN", "created_at": NOW,
     "restaurant": {"slug": "mama-put", "name": "Ramzy"}, "items_count": 3, "item_names": ["Rice"], "active": True, "can_review": False, "reviewed": False, "track_token": "t" * 40},
    {"public_id": "p2", "reference": "PRM-3M7TZ", "status": "COMPLETED", "payment_status": "PAID", "fulfilment_type": "PICKUP", "pickup_at": None, "total": "250.00", "currency": "NGN", "created_at": NOW,
     "restaurant": {"slug": "mama-put", "name": "Golden Bowl"}, "items_count": 1, "item_names": ["Rice"], "active": False, "can_review": False, "reviewed": True, "track_token": "u" * 40}]}
SCENARIOS["customer"] += [
    ("restaurant-reviews", "/customer/index.html?r=mama-put", {r"/restaurants/mama-put/reviews/": REVIEWS, r"/restaurants/mama-put/menu/": MENU, r"/restaurants/mama-put/": BROKEN_IMAGES, r"/customers/me/": CUSTOMER_ME}),
    ("my-orders-signed-in", "/customer/my-orders.html", {r"/customers/me/": CUSTOMER_ME, r"/customers/orders/": MY_ORDERS}),
    ("account", "/customer/account.html", {}), ("my-orders", "/customer/my-orders.html", {})]
for _label, _state, _extra in (("review-signin", "sign_in", {"can_review": False}), ("review-form", "can_review", {"can_review": True}), ("review-none", "", {"can_review": False})):
    SCENARIOS["customer"].append((f"order-{_label}", f"/customer/order.html?r=mama-put#{'b' * 96}", {rf"/orders/{'b' * 96}/": dict(order_at("COMPLETED"), review_status=_state, **_extra), r"/customers/me/": CUSTOMER_ME if _state == "can_review" else SIGNED_OUT}))
SCENARIOS["customer"].append(("order", f"/customer/order.html?r=mama-put#{TOKEN}", {rf"/orders/{TOKEN}/": ORDER_PAGE}))
PLANS = {"plans": [{"id": 1, "name": "Starter", "price": "4000.00", "currency": "NGN", "interval": "MONTHLY", "included_orders": 150, "pack_orders": 100, "pack_price": "2000.00", "features": []},
                   {"id": 2, "name": "Pro", "price": "7500.00", "currency": "NGN", "interval": "MONTHLY", "included_orders": 400, "pack_orders": 100, "pack_price": "1800.00", "features": ["Priority support"]},
                   {"id": 3, "name": "Premium", "price": "10000.00", "currency": "NGN", "interval": "MONTHLY", "included_orders": 900, "pack_orders": 200, "pack_price": "3000.00", "features": []}],
         "payment": {"bank_name": "First Bank", "account_name": "ServeFlow Ltd", "account_number": "0123456789", "instructions": "Use your payment reference."}, "trial_days": 2}
SCENARIOS["marketing"] = [
    ("landing", "/index.html", {r"/billing/plans/": PLANS}),
    ("pricing", "/pricing/index.html", {r"/billing/plans/": PLANS}),
    ("gallery", "/shared/design-system.html", {}),
]
SCENARIOS["workspace"].append(("login", "/restaurant-dashboard/login.html", {r"/auth/me/": SIGNED_OUT, r"/auth/options/": {"signup_enabled": True}}))
SCENARIOS["owner"].append(("sign-in", "/owner-control-centre/index.html#/", {r"/platform/me/": SIGNED_OUT, r"/auth/me/": SIGNED_OUT}))

# Phone navigation: press this to open the menu, then take a second screenshot
OPEN_MENU = {("workspace", "orders"): ".nav__more", ("customer", "menu"): ".site-nav__toggle", ("customer", "marketplace"): ".site-nav__toggle", ("owner", "overview"): ".oc-menu-btn"}

COMMON = {r"/auth/me/": ME, r"/customers/me/": ({"error": {"code": "not_authenticated", "message": "x"}}, 401)}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(port):
    handler = lambda *a, **k: Quiet(*a, directory=str(ROOT), **k)
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(only=None, port=5311):
    OUT.mkdir(exist_ok=True)
    server = serve(port)
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for group, pages in SCENARIOS.items():
            if only and group != only:
                continue
            for name, path, routes in pages:
                for vp, (w, h) in VIEWPORTS.items():
                    ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1.5 if vp == "phone" else 1, has_touch=vp in ("phone", "small"), is_mobile=vp in ("phone", "small"))
                    page = ctx.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)[:160]))

                    def make_handler(routes):
                        def handle(route):
                            url = route.request.url.split("/api/v1", 1)[1].split("?")[0]
                            for pattern, payload in {**COMMON, **routes}.items():
                                if re.search(pattern, url):
                                    body, status = payload if isinstance(payload, tuple) else (payload, 200)
                                    return route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
                            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"results": [], "next": None, "previous": None}))
                        return handle

                    ctx.route("**/api/v1/**", make_handler(routes))
                    ctx.route("**/shared/fonts/**", lambda r: r.abort())
                    ctx.route("**/media/**", lambda r: r.fulfill(status=404, body="") if "missing" in r.request.url else r.fulfill(status=200, content_type="image/png", body=SAMPLE_PHOTO))
                    page.goto(f"http://127.0.0.1:{port}{path}", wait_until="load")
                    if group == "anim":
                        if vp != "phone":
                            ctx.close()
                            continue
                        start = 0
                        for k, t in enumerate(ANIM_FRAMES):
                            page.wait_for_timeout(max(0, t - start)); start = t
                            page.locator(".order-progress").screenshot(path=str(OUT / f"anim-{name}-{k}.png"))
                        ctx.close()
                        continue
                    page.add_style_tag(content=FONT_STANDIN)
                    page.wait_for_timeout(1200)
                    page.add_style_tag(content=".install-bar{display:none!important}")
                    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
                    wide = page.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.right > window.innerWidth + 1 && r.width > 0 && getComputedStyle(e).position !== 'fixed' && !e.closest('[hidden]') && !e.closest('.chip-nav') && !e.closest('.table-wrap'); }).slice(0, 3).map(e => e.tagName.toLowerCase() + '.' + String(e.className).split(' ')[0])""")
                    if over > 1:
                        problems.append(f"{group}/{name} @{vp}: page is {over}px wider than the screen (e.g. {wide})")
                    for e in errors:
                        problems.append(f"{group}/{name} @{vp}: script error: {e}")
                    if name == "restaurant-reviews" and vp in ("desktop", "phone"):
                        track = page.locator(".review-marquee__track").first
                        x1 = page.evaluate("new DOMMatrix(getComputedStyle(document.querySelector('.review-marquee__track')).transform).m41")
                        page.wait_for_timeout(1500)
                        x2 = page.evaluate("new DOMMatrix(getComputedStyle(document.querySelector('.review-marquee__track')).transform).m41")
                        if not x2 < x1:
                            problems.append(f"{group}/{name} @{vp}: the reviews are not moving ({x1} -> {x2})")
                        box = page.locator(".review-marquee").bounding_box()
                        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        page.mouse.down()
                        page.wait_for_timeout(300)
                        h1 = page.evaluate("new DOMMatrix(getComputedStyle(document.querySelector('.review-marquee__track')).transform).m41")
                        page.wait_for_timeout(900)
                        h2 = page.evaluate("new DOMMatrix(getComputedStyle(document.querySelector('.review-marquee__track')).transform).m41")
                        if abs(h2 - h1) > 0.5 or page.evaluate("document.querySelector('.review-marquee').dataset.paused") != "true":
                            problems.append(f"{group}/{name} @{vp}: pressing did not hold the reviews still ({h1} -> {h2})")
                        page.mouse.up()
                        page.mouse.move(5, 5)
                        page.wait_for_timeout(300)
                        r1 = page.evaluate("new DOMMatrix(getComputedStyle(document.querySelector('.review-marquee__track')).transform).m41")
                        page.wait_for_timeout(900)
                        r2 = page.evaluate("new DOMMatrix(getComputedStyle(document.querySelector('.review-marquee__track')).transform).m41")
                        if not r2 < r1:
                            problems.append(f"{group}/{name} @{vp}: letting go did not set the reviews moving again ({r1} -> {r2})")
                    page.screenshot(path=str(OUT / f"{group}-{name}-{vp}.png"), full_page=True)
                    if vp in ("phone", "small") and (group, name) in OPEN_MENU:
                        page.evaluate("window.scrollTo(0, 0)")
                        opener = page.locator(OPEN_MENU[(group, name)]).first
                        opener.click()
                        page.wait_for_timeout(500)
                        page.screenshot(path=str(OUT / f"{group}-{name}-{vp}-menu.png"))
                        if page.evaluate("document.documentElement.scrollWidth - window.innerWidth") > 1:
                            problems.append(f"{group}/{name} @{vp}: opening the menu made the page wider than the screen")
                    ctx.close()
        browser.close()
    server.shutdown()
    print("\n".join(problems) if problems else "No horizontal overflow and no script errors.")
    print(f"Screenshots in {OUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
