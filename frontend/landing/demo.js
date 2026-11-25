/* A scripted product demo for the landing page: a diner orders on the phone, the order lands on the restaurant's screen
 * and moves along. Sample content only, and it says so. It pauses when hidden, off-screen or when the visitor asks, and
 * people who prefer reduced motion get a still picture. */
import { el } from "../shared/js/ui.js";

const MENU = [
  { name: "Jollof Rice", price: 1000, thumb: 1 }, { name: "Fried Rice", price: 1200, thumb: 2 },
  { name: "Beans & Plantain", price: 900, thumb: 3 }, { name: "Chicken", price: 1000, thumb: 4 },
];
const STATUS = ["Pending", "Confirmed", "Being served", "Served"];
const SEED = [
  { code: "042", items: "Rice + Chicken", total: 1500, status: 0, type: "Pickup" },
  { code: "043", items: "Beans + Plantain", total: 1200, status: 1, type: "Dine-in" },
  { code: "044", items: "Rice + Chicken + Drink", total: 2000, status: 2, type: "Dine-in" },
  { code: "045", items: "Spaghetti + Chicken", total: 1800, status: 1, type: "Pickup" },
  { code: "046", items: "Fried Rice + Beef", total: 2200, status: 0, type: "Pickup" },
];
const QUEUE_ORDERS = [
  { items: "Jollof Rice + Chicken", total: 2000, type: "Pickup" }, { items: "Fried Rice + Beef", total: 2200, type: "Dine-in" },
  { items: "Beans + Plantain + Drink", total: 1500, type: "Pickup" }, { items: "Rice + Chicken + Drink", total: 2000, type: "Dine-in" },
];
const naira = (n) => `₦${String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
const logo = () => { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("aria-hidden", "true"); s.innerHTML = '<use href="#logo"/>'; return s; };

/* ---------- pause / visibility handling shared by every demo ---------- */
class Runner {
  constructor(root) {
    this.paused = false; this.offscreen = false; this.waiters = [];
    document.addEventListener("visibilitychange", () => this.kick());
    new IntersectionObserver(([entry]) => { this.offscreen = !entry.isIntersecting; this.kick(); }, { threshold: 0.15 }).observe(root);
  }
  get idle() { return this.paused || this.offscreen || document.hidden; }
  kick() { this.waiters.splice(0).forEach((resolve) => resolve()); }
  async ready() { while (this.idle) await new Promise((resolve) => this.waiters.push(resolve)); }
  async sleep(ms) { await this.ready(); await new Promise((resolve) => setTimeout(resolve, ms)); await this.ready(); }
}

/* ---------- the restaurant's dashboard ---------- */
function dashboard({ wide }) {
  const rows = new Map();
  const body = el("div", { class: "dash__rows" });
  const counts = { attention: el("b", {}, "0"), progress: el("b", {}, "0"), finished: el("b", {}, "0") };
  const stats = wide ? { open: el("strong", {}, "0"), served: el("strong", {}, "0"), sales: el("strong", {}, "₦0") } : null;
  const head = el("div", { class: "d-row d-row--head" }, el("span", {}, "Order"), el("span", {}, "Items"), wide ? el("span", {}, "Type") : null, el("span", {}, "Total"), el("span", {}, "Status"));

  function refresh() {
    const all = [...rows.values()].map((r) => r.order);
    const n = (test) => all.filter(test).length;
    counts.attention.textContent = n((o) => o.status === 0);
    counts.progress.textContent = n((o) => o.status === 1 || o.status === 2);
    counts.finished.textContent = n((o) => o.status === 3);
    if (stats) {
      stats.open.textContent = n((o) => o.status < 3);
      stats.served.textContent = n((o) => o.status === 3);
      stats.sales.textContent = naira(all.filter((o) => o.status === 3).reduce((sum, o) => sum + o.total, 0));
    }
  }
  function add(order, { animate = false, max = 5 } = {}) {
    const pill = el("b", { class: "pill", "data-s": String(order.status) }, STATUS[order.status]);
    const row = el("div", { class: `d-row${animate ? " is-new" : ""}` }, el("span", {}, `#${order.code}`), el("span", {}, order.items), wide ? el("span", {}, order.type) : null, el("span", {}, naira(order.total)), el("span", {}, pill));
    rows.set(order.code, { order, row, pill });
    animate ? body.prepend(row) : body.append(row);
    while (rows.size > max) {
      const [code, old] = [...rows.entries()].at(-1);
      rows.delete(code);
      old.row.classList.add("is-leaving");
      setTimeout(() => old.row.remove(), 360);
    }
    refresh();
  }
  function setStatus(code, status) {
    const entry = rows.get(code);
    if (!entry) return;
    entry.order.status = status;
    entry.pill.dataset.s = String(status);
    entry.pill.textContent = STATUS[status];
    refresh();
  }
  const oldestOpen = () => [...rows.values()].map((r) => r.order).reverse().find((o) => o.status < 3);

  const node = el("div", { class: `dash${wide ? " dash--wide" : ""}` },
    el("aside", { class: "dash__side" }, el("div", { class: "dash__brand" }, logo(), "ServeFlow"),
      el("ul", {}, ...["Overview", "Orders", "Menu", "Settings", "Team"].map((t) => el("li", { class: t === "Orders" ? "on" : "" }, t)))),
    el("div", { class: "dash__main" },
      el("div", { class: "dash__head" }, el("strong", {}, "Incoming orders"), el("span", { class: "dash__live" }, el("i"), "Live")),
      stats ? el("div", { class: "dash__stats" }, el("div", { class: "dash__stat" }, el("small", {}, "Open orders"), stats.open), el("div", { class: "dash__stat" }, el("small", {}, "Served today"), stats.served), el("div", { class: "dash__stat" }, el("small", {}, "Sales so far"), stats.sales)) : null,
      el("div", { class: "dash__chips" }, el("span", { class: "on" }, "Needs attention", counts.attention), el("span", {}, "In progress", counts.progress), el("span", {}, "Finished", counts.finished)),
      head, body));
  return { node, add, setStatus, oldestOpen, seed: () => SEED.forEach((o) => add({ ...o })) };
}

/* ---------- the diner's phone ---------- */
function phone() {
  const cartLabel = el("span", {}, "View order (0)");
  const cartTotal = el("strong", {}, naira(0));
  const cart = el("div", { class: "m-cart hidden-cart" }, cartLabel, cartTotal);
  const buttons = MENU.map(() => el("b", { class: "add" }, "+"));
  const items = MENU.map((item, i) => el("div", { class: "m-item" }, el("i", { class: `thumb thumb--${item.thumb}` }), el("div", {}, el("strong", {}, item.name), el("small", {}, naira(item.price))), buttons[i]));
  const lines = [];
  const node = el("div", { class: "phone" }, el("div", { class: "screen" },
    el("div", { class: "phone__bar" }, el("span", {}, "9:41"), el("span", { class: "phone__island" }), el("span", {}, "●●●")),
    el("div", { class: "phone__body" },
      el("div", { class: "m-head" }, logo(), el("div", {}, el("strong", {}, "Pramos Restaurant"), el("small", {}, "Good food, faster"))),
      el("div", { class: "m-search" }, "Search menu items…"),
      el("div", { class: "m-chips" }, ...["All", "Rice", "Protein", "Drinks"].map((t, i) => el("span", { class: i ? "" : "on" }, t))),
      ...items, cart)));
  const pulse = (target) => { target.classList.add("tap"); setTimeout(() => target.classList.remove("tap"), 450); };
  function show() {
    const total = lines.reduce((sum, i) => sum + MENU[i].price, 0);
    cartLabel.textContent = `View order (${lines.length})`;
    cartTotal.textContent = naira(total);
    cart.classList.toggle("hidden-cart", !lines.length);
  }
  return {
    node, lines, total: () => lines.reduce((sum, i) => sum + MENU[i].price, 0), names: () => lines.map((i) => MENU[i].name.split(" ")[0]).join(" + "),
    tap(i) { lines.push(i); pulse(buttons[i]); show(); },
    pressCart() { pulse(cart); }, label(text, done = false) { cartLabel.textContent = text; cart.classList.toggle("done", done); },
    reset() { lines.length = 0; cart.classList.remove("done"); show(); },
    still() { lines.push(0, 3); show(); },
  };
}

/* ---------- frames ---------- */
const laptopFrame = (screen) => el("div", { class: "laptop" }, el("div", { class: "laptop__lid" }, el("span", { class: "laptop__cam" }), el("div", { class: "screen" }, screen)), el("div", { class: "laptop__base" }));
const monitorFrame = (screen) => el("div", { class: "monitor" }, el("div", { class: "monitor__panel" }, el("div", { class: "screen" }, screen), el("div", { class: "monitor__chin" }, el("i"))), el("div", { class: "monitor__neck" }), el("div", { class: "monitor__foot" }));

function pauseButton(runner) {
  const button = el("button", { class: "demo-toggle", type: "button", "aria-pressed": "false" }, "Pause demo");
  button.addEventListener("click", () => {
    runner.paused = !runner.paused;
    button.setAttribute("aria-pressed", String(runner.paused));
    button.textContent = runner.paused ? "Play demo" : "Pause demo";
    runner.kick();
  });
  return button;
}

export function mountHeroDemo(root, caption) {
  const dash = dashboard({ wide: false });
  const mobile = phone();
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  dash.seed();
  const stage = el("div", { class: "stage", role: "img", "aria-label": "Demo: a customer orders from a phone and the order appears on the restaurant's screen." },
    el("span", { class: "leaf leaf--a" }), el("span", { class: "leaf leaf--b" }), laptopFrame(dash.node), mobile.node);
  const food = root.querySelector("img[data-optional]");
  root.replaceChildren(stage);
  if (food) stage.append(food);
  if (still) { mobile.still(); return; }
  const runner = new Runner(root);
  caption.prepend(pauseButton(runner));
  let next = 47;
  (async function play() {
    for (;;) {
      await runner.sleep(900);
      mobile.tap(0); await runner.sleep(900);
      mobile.tap(3); await runner.sleep(1000);
      mobile.pressCart(); await runner.sleep(500);
      mobile.label("Placing order…"); await runner.sleep(900);
      const code = String(next++).padStart(3, "0");
      mobile.label("Order placed ✓", true);
      dash.add({ code, items: `${mobile.names()}`, total: mobile.total(), status: 0, type: "Pickup" }, { animate: true });
      const older = dash.oldestOpen(); if (older && older.code !== code) dash.setStatus(older.code, older.status + 1);
      await runner.sleep(1700); dash.setStatus(code, 1);
      await runner.sleep(1600); dash.setStatus(code, 2);
      await runner.sleep(1600); dash.setStatus(code, 3);
      await runner.sleep(1400); mobile.reset();
    }
  })();
}

export function mountScreenDemo(root, caption) {
  const dash = dashboard({ wide: true });
  dash.seed();
  root.replaceChildren(el("div", { class: "stage-pc", role: "img", "aria-label": "Demo: new orders arrive on a restaurant's desktop screen and move from pending to served." }, monitorFrame(dash.node)));
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const runner = new Runner(root);
  caption.prepend(pauseButton(runner));
  let next = 47, i = 0;
  (async function play() {
    for (;;) {
      await runner.sleep(2200);
      const sample = QUEUE_ORDERS[i++ % QUEUE_ORDERS.length];
      const code = String(next++).padStart(3, "0");
      dash.add({ ...sample, code, status: 0 }, { animate: true, max: 6 });
      const older = dash.oldestOpen(); if (older && older.code !== code) dash.setStatus(older.code, older.status + 1);
      await runner.sleep(1800); dash.setStatus(code, 1);
      await runner.sleep(1800); dash.setStatus(code, 2);
      await runner.sleep(1800); dash.setStatus(code, 3);
    }
  })();
}
