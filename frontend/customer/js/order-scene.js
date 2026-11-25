/* The order progress picture: what the customer ordered gathers onto a plate and the plate follows the order (confirmed, being prepared,
 * ready, completed), with a row of green ticks underneath that a little plate rides along from one tick to the next.
 *
 * Pure decisions (which food, where it sits, which step is current) are exported and tested; the rest only draws. Nothing here reads the
 * network. People who ask their device for less motion get the finished picture with no movement. */
import { DISH_KINDS } from "../../shared/js/dish-kinds.js";
import { el } from "../../shared/js/ui.js";

const NS = "http://www.w3.org/2000/svg";
export const STAGES = ["PENDING", "CONFIRMED", "SERVING", "READY_FOR_PICKUP", "COMPLETED"];
export const STAGE_LABELS = ["Order placed", "Confirmed", "Preparing", "Ready", "Completed"];
export const STEP_MS = 520; // how long the plate takes to travel from one tick to the next

export const isClosed = (status) => status === "REJECTED" || status === "CANCELLED";
export const stageOf = (status) => STAGES.indexOf(status);

/* ------------------------------------------------------------------ which food is it? */
const KINDS = [
  ["drink", /\b(zobo|drinks?|juices?|water|sodas?|coke|fanta|sprite|pepsi|smoothies?|tea|coffee|malt|beers?|wines?|kunu|shakes?|lemonade|cocktails?|chapman|fura|beverages?)\b/i],
  ["dessert", /\b(ice ?cream|desserts?|puddings?|waffles?|gelato|sundaes?|parfaits?|cakes?)\b/i],
  ["soup", /\b(soups?|stews?|egusi|efo|ogbono|okra|banga|afang|edikang|ewedu|gbegiri|sauces?|curry|riro|nkwobi)\b/i],
  ["swallow", /\b(pounded yam|amala|eba|fufu|semo|swallows?|garri|tuwo|iyan|oka|starch)\b/i],
  ["rice", /\b(rice|jollof|pilau|ofada|risotto|spaghetti|pasta|noodles?|indomie|couscous)\b/i],
  ["fish", /\b(fish|tilapia|catfish|croaker|mackerel|shrimps?|prawns?|crab|lobster|calamari|sardines?|seafood)\b/i],
  ["meat", /\b(chicken|beef|goat|turkey|suya|asun|meats?|ribs?|grill(ed|s)?|kebabs?|shawarma|steaks?|ponmo|sausages?|lamb|wings?|bbq|barbecue|kilishi|gizzard)\b/i],
  ["plantain", /\b(plantains?|dodo|boli|kelewele|yam|potatoes?|fries|chips)\b/i],
  ["egg", /\b(eggs?|omelettes?|omelets?|scrambled)\b/i],
  ["veg", /\b(salads?|vegetables?|veggies?|coleslaw|cabbage|greens)\b/i],
  ["bread", /\b(breads?|burgers?|pies?|puffs?|chin ?chin|buns?|sandwich(es)?|pizzas?|doughnuts?|donuts?|pastr(y|ies)|biscuits?|cookies?|akara|moi ?moi|toast|wraps?|snacks?|bakery)\b/i],
];

/** A kind of food drawn for this menu item name. Unknown names get a plain covered dish, so nothing is ever missing. */
export function foodKind(name) {
  const text = String(name ?? "");
  for (const [kind, pattern] of KINDS) if (pattern.test(text)) return kind;
  return "dish";
}

/** Only pictures from our own uploads or an https address are ever put on the plate. */
export const safePhoto = (src) => (typeof src === "string" && /^(https:\/\/|\/media\/)\S+$/.test(src) ? src : null);

/** How one ordered item is shown, most exact first: its own photo; the dish style the restaurant chose; what its name says;
 * what its menu category says ("Soups", "Drinks"); and finally a covered dish in a colour made from its name, so every unknown dish still looks
 * its own and always the same. No list to keep up to date: a new dish needs nothing from us. */
export function plateDish(item) {
  const chosen = DISH_KINDS.includes(item?.dish_kind) ? item.dish_kind : "";
  let kind = chosen || foodKind(item?.name);
  if (!chosen && kind === "dish") kind = foodKind(item?.category);
  return { kind, photo: safePhoto(item?.image_url), seed: String(item?.name ?? "") };
}

/** A hue (0 to 359) that is always the same for the same name. */
export function hueOf(text) {
  let h = 0;
  for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

/* ------------------------------------------------------------------ where does each dish sit on the plate? */
const SPOTS = {
  1: [[0, 4, 2]],
  2: [[-30, 6, 1.5], [30, -2, 1.5]],
  3: [[-31, 16, 1.3], [31, 16, 1.3], [0, -26, 1.3]],
  4: [[-32, -17, 1.18], [32, -17, 1.18], [-32, 29, 1.18], [32, 29, 1.18]],
  5: [[-41, -25, 0.95], [41, -25, 0.95], [-39, 34, 0.95], [39, 34, 0.95], [0, 5, 0.92]],
};
export const MAX_DISHES = 5;
// where each dish starts its trip from, so they arrive from different directions
const FROM_DEGREES = [-135, -45, 180, 0, 100];

/** Position, size and starting point of each dish for `count` dishes (1 to 5), in plate coordinates. */
export function dishLayout(count) {
  const n = Math.max(0, Math.min(count, MAX_DISHES));
  return (SPOTS[n] ?? []).map(([x, y, s], i) => {
    const a = (FROM_DEGREES[i] * Math.PI) / 180;
    return { x, y, s, fx: Math.round(x + Math.cos(a) * 150), fy: Math.round(y + Math.sin(a) * 105), fr: (i % 2 ? 1 : -1) * (40 + i * 12) };
  });
}

/* ------------------------------------------------------------------ the ticks */
/** The row of ticks for an order: each step done, current or still to come, and how far along the rail the plate has travelled. */
export function trackModel(order) {
  const closed = isClosed(order.status);
  const reached = new Set((order.timeline ?? []).map((entry) => entry.status));
  let stage = closed ? -1 : stageOf(order.status);
  if (closed) STAGES.forEach((status, i) => { if (reached.has(status)) stage = i; });
  const steps = STAGES.map((status, i) => {
    let state = "todo";
    if (closed) state = reached.has(status) ? "done" : "todo";
    else if (order.status === "COMPLETED" || i < stage) state = "done";
    else if (i === stage) state = "current";
    return { status, label: STAGE_LABELS[i], state };
  });
  return { stage: Math.max(stage, 0), closed, complete: order.status === "COMPLETED", steps };
}

/* ------------------------------------------------------------------ drawing */
function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) node.setAttribute(k, String(v));
  node.append(...children.filter(Boolean));
  return node;
}
const build = ([tag, attrs, ...kids]) => svg(tag, attrs, ...kids.map(build));
const BOWL = ["path", { d: "M-26 8H26Q24 24 0 26Q-24 24-26 8Z", fill: "#fff", stroke: "#cdd8d2", "stroke-width": 1.5 }];

// Each dish is drawn on a 64 x 64 grid centred on 0,0.
const ART = {
  rice: ["g", {}, BOWL, ["path", { d: "M-21 8Q-22 -14 0 -17Q22 -14 21 8Z", fill: "#f97316" }], ["ellipse", { cx: -8, cy: -4, rx: 3.2, ry: 1.7, fill: "#fdba74", transform: "rotate(-20 -8 -4)" }],
    ["ellipse", { cx: 6, cy: -8, rx: 3.2, ry: 1.7, fill: "#fdba74", transform: "rotate(25 6 -8)" }], ["ellipse", { cx: 11, cy: 1, rx: 3, ry: 1.6, fill: "#fdba74" }], ["ellipse", { cx: -13, cy: 3, rx: 3, ry: 1.6, fill: "#fdba74" }]],
  meat: ["g", {}, ["path", { d: "M6 8L21 23", stroke: "#fef3c7", "stroke-width": 7, "stroke-linecap": "round" }], ["circle", { cx: 23, cy: 22, r: 4.2, fill: "#fef3c7" }], ["circle", { cx: 19, cy: 26, r: 3.8, fill: "#fef3c7" }],
    ["path", { d: "M-16 -10C-4 -24 20 -16 15 3C11 15 -7 14 -13 5C-19 -3 -22 -4 -16 -10Z", fill: "#b45309" }], ["path", { d: "M-8 -9C0 -15 9 -12 11 -5", stroke: "#d97706", "stroke-width": 3, fill: "none", "stroke-linecap": "round" }]],
  fish: ["g", {}, ["path", { d: "M-24 0C-12 -18 10 -18 20 0C10 18 -12 18 -24 0Z", fill: "#d97706" }], ["path", { d: "M20 0L30 -11L30 11Z", fill: "#b45309" }], ["circle", { cx: -14, cy: -3, r: 2.4, fill: "#fff" }],
    ["circle", { cx: -14, cy: -3, r: 1.1, fill: "#451a03" }], ["path", { d: "M-4 -10Q2 0 -4 10M6 -9Q12 0 6 9", stroke: "#fbbf24", "stroke-width": 2, fill: "none", "stroke-linecap": "round" }]],
  plantain: ["g", {}, ["ellipse", { cx: -12, cy: -8, rx: 13, ry: 7, fill: "#facc15", stroke: "#a16207", "stroke-width": 2, transform: "rotate(-25 -12 -8)" }],
    ["ellipse", { cx: 10, cy: -4, rx: 13, ry: 7, fill: "#facc15", stroke: "#a16207", "stroke-width": 2, transform: "rotate(15 10 -4)" }], ["ellipse", { cx: -2, cy: 14, rx: 13, ry: 7, fill: "#fde047", stroke: "#a16207", "stroke-width": 2, transform: "rotate(-8 -2 14)" }]],
  swallow: ["g", {}, BOWL, ["circle", { cx: 0, cy: -4, r: 19, fill: "#fef3c7", stroke: "#eadba6", "stroke-width": 1.5 }], ["path", { d: "M-9 -12Q0 -18 9 -12", stroke: "#fffbeb", "stroke-width": 3, fill: "none", "stroke-linecap": "round" }]],
  soup: ["g", {}, ["path", { d: "M-27 -2H27Q25 20 0 24Q-25 20-27 -2Z", fill: "#fff", stroke: "#cdd8d2", "stroke-width": 1.5 }], ["ellipse", { cx: 0, cy: -2, rx: 27, ry: 8, fill: "#15803d" }],
    ["circle", { cx: -9, cy: -3, r: 2.6, fill: "#fde68a" }], ["circle", { cx: 6, cy: -1, r: 2.2, fill: "#fde68a" }], ["circle", { cx: 14, cy: -4, r: 1.8, fill: "#b45309" }], ["circle", { cx: -16, cy: 0, r: 1.8, fill: "#b45309" }]],
  drink: ["g", {}, ["path", { d: "M5 -14L12 -28", stroke: "#f59e0b", "stroke-width": 3.5, "stroke-linecap": "round" }], ["path", { d: "M-13 -14H13L10 22Q10 25 7 25H-7Q-10 25 -10 22Z", fill: "#b91c1c" }],
    ["path", { d: "M-13 -14H13L12.4 -8H-12.4Z", fill: "#fee2e2", opacity: 0.85 }], ["circle", { cx: -2, cy: 2, r: 2.4, fill: "#fecaca", opacity: 0.7 }], ["circle", { cx: 3, cy: 11, r: 2, fill: "#fecaca", opacity: 0.6 }]],
  dessert: ["g", {}, ["path", { d: "M-12 -2L0 28L12 -2Z", fill: "#f59e0b" }], ["path", { d: "M-8 5H8M-5 12H5", stroke: "#b45309", "stroke-width": 1.5 }], ["circle", { cx: 0, cy: -10, r: 15, fill: "#fda4af" }], ["circle", { cx: -5, cy: -14, r: 3, fill: "#fecdd3" }]],
  egg: ["g", {}, ["path", { d: "M-22 0C-26 -16 -6 -24 8 -20C26 -16 28 4 18 14C8 24 -14 20 -22 0Z", fill: "#fff", stroke: "#e2e8e4", "stroke-width": 1.5 }], ["circle", { cx: 0, cy: -1, r: 9, fill: "#fbbf24" }], ["circle", { cx: -3, cy: -4, r: 2.4, fill: "#fde68a" }]],
  veg: ["g", {}, ["ellipse", { cx: -9, cy: 0, rx: 9, ry: 17, fill: "#22c55e", transform: "rotate(-35 -9 0)" }], ["ellipse", { cx: 9, cy: 0, rx: 9, ry: 17, fill: "#16a34a", transform: "rotate(35 9 0)" }],
    ["ellipse", { cx: 0, cy: -6, rx: 8, ry: 16, fill: "#4ade80" }], ["path", { d: "M0 -18V14", stroke: "#15803d", "stroke-width": 1.5 }]],
  bread: ["g", {}, ["path", { d: "M-24 -2Q-24 -22 0 -22Q24 -22 24 -2Z", fill: "#f59e0b" }], ["path", { d: "M-22 2H22", stroke: "#7c2d12", "stroke-width": 5, "stroke-linecap": "round" }],
    ["path", { d: "M-22 8H22Q22 20 0 20Q-22 20 -22 8Z", fill: "#fbbf24" }], ["circle", { cx: -8, cy: -13, r: 1.4, fill: "#fef3c7" }], ["circle", { cx: 2, cy: -16, r: 1.4, fill: "#fef3c7" }], ["circle", { cx: 11, cy: -11, r: 1.4, fill: "#fef3c7" }]],
};
// A covered dish for anything we have no picture of, coloured from the name so different dishes look different.
const genericDish = (seed) => {
  const hue = hueOf(seed);
  const body = `hsl(${hue} 68% 52%)`;
  const light = `hsl(${hue} 78% 78%)`;
  return ["g", {}, BOWL, ["path", { d: "M-20 8Q-20 -12 0 -14Q20 -12 20 8Z", fill: body }], ["circle", { cx: -7, cy: -2, r: 2.4, fill: light }], ["circle", { cx: 6, cy: -6, r: 2, fill: light }], ["circle", { cx: 9, cy: 2, r: 1.8, fill: light }]];
};

const CONFETTI = ["#059669", "#86efac", "#fbbf24", "#34d399", "#f97316", "#a7f3d0"];
const SPARKS = [[-98, -34], [100, -44], [-88, 52], [92, 58], [0, -100]];
const STAR = "M0 -7L1.8 -1.8L7 0L1.8 1.8L0 7L-1.8 1.8L-7 0L-1.8 -1.8Z";

/** The plate, with one drawing per ordered item. */
function sceneSvg(items, name) {
  const shown = items.slice(0, MAX_DISHES);
  const spots = dishLayout(shown.length);
  const dishes = shown.map((item, i) => {
    const s = spots[i];
    const dish = plateDish(item);
    const art = svg("g", { class: "os-dish__art" }, build(dish.kind === "dish" ? genericDish(dish.seed) : ART[dish.kind]));
    const group = svg("g", { class: "os-dish", style: `--x:${s.x}px;--y:${s.y}px;--s:${s.s};--fx:${s.fx}px;--fy:${s.fy}px;--fr:${s.fr}deg;--i:${i}` }, art);
    if (dish.photo) { // the restaurant's own photo, in a round frame. The drawing stays underneath until the photo has loaded (and for good if it can't)
      const image = svg("image", { href: dish.photo, x: -27, y: -27, width: 54, height: 54, preserveAspectRatio: "xMidYMid slice", "clip-path": `url(#os-clip-${i})` });
      const photo = svg("g", { class: "os-photo" }, svg("clipPath", { id: `os-clip-${i}` }, svg("circle", { r: 27 })), svg("circle", { class: "os-photo__ring", r: 29.5 }), image);
      image.addEventListener("load", () => group.setAttribute("data-photo", "ready"));
      image.addEventListener("error", () => photo.remove());
      group.append(photo);
    }
    group.append(
      item.quantity > 1 ? svg("g", { class: "os-qty", transform: "translate(20 18)" }, svg("circle", { r: 9.5 }), svg("text", { y: 3.6 }, `×${item.quantity}`)) : null);
    return group;
  });
  const steam = [-26, 0, 26].map((x, i) => svg("path", { class: "os-steam__wisp", d: `M${x} 0Q${x - 9} -12 ${x} -24T${x} -48`, style: `--sd:${i * 420}ms` }));
  const confetti = Array.from({ length: 16 }, (_, i) => svg("rect", { class: "os-confetti__bit", x: -150 + i * 19, y: 0, width: 7, height: 10, rx: 1.5, fill: CONFETTI[i % CONFETTI.length],
    style: `--cx:${((i * 37) % 60) - 30}px;--cr:${(i * 83) % 360 + 180}deg;--cd:${(i * 97) % 700}ms` }));
  const sparks = SPARKS.map(([x, y], i) => svg("path", { class: "os-spark", d: STAR, transform: `translate(${x} ${y})`, style: `--sd:${i * 330}ms` }));

  return svg("svg", { viewBox: "0 0 320 220", role: "img", "aria-label": name, focusable: "false" },
    svg("ellipse", { class: "os-table", cx: 160, cy: 198, rx: 104, ry: 12 }),
    svg("g", { transform: "translate(160 118)" },
      svg("g", { class: "os-bob" },
        svg("circle", { class: "os-glow", r: 94 }),
        svg("circle", { class: "os-plate", r: 84 }),
        svg("circle", { class: "os-well", r: 62 }),
        svg("g", { class: "os-stir" }, svg("g", { class: "os-dishes", style: `--os-n:${shown.length}` }, ...dishes)),
        svg("g", { class: "os-cloche" },
          svg("path", { class: "os-cloche__dome", d: "M-82 6A82 82 0 0 1 82 6Z" }), svg("rect", { class: "os-cloche__rim", x: -90, y: 4, width: 180, height: 9, rx: 4.5 }),
          svg("circle", { class: "os-cloche__knob", cy: -84, r: 7 }), svg("path", { class: "os-cloche__shine", d: "M-60 -34A66 66 0 0 1 -26 -62" })))),
    svg("g", { transform: "translate(160 70)" }, svg("g", { class: "os-steam" }, ...steam)),
    ...sparks,
    svg("g", { transform: "translate(160 0)" }, svg("g", { class: "os-confetti" }, ...confetti)),
    svg("g", { transform: "translate(250 42)" }, svg("g", { class: "os-badge" }, svg("circle", { r: 25 }), svg("path", { d: "M-11 1L-3 9L11 -8", pathLength: 30 }))),
    svg("g", { transform: "translate(250 42)" }, svg("g", { class: "os-closed" }, svg("circle", { r: 25 }), svg("path", { d: "M-9 -9L9 9M9 -9L-9 9" }))));
}

const tickMark = () => svg("svg", { class: "order-track__tick", viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" }, svg("path", { d: "M5 12.5L9.8 17L19 7.5", pathLength: 24 }));
const afterPaint = (fn) => (typeof requestAnimationFrame === "function" ? requestAnimationFrame(() => requestAnimationFrame(fn)) : fn());

let shown = null; // the step the customer last saw on this page; null the first time

/** Forget what was shown (a different order is being opened). */
export function resetOrderScene() { shown = null; }

/** The picture and the ticks for one order. Call again with each update; only the first call plays the whole story. */
export function orderProgress(order) {
  const model = trackModel(order);
  const previous = shown;
  const stage = model.closed ? "closed" : String(model.stage);
  const motion = previous === null ? "intro" : !model.closed && model.stage > previous ? "advance" : "settled";
  const from = motion === "advance" ? previous : motion === "intro" ? 0 : model.stage;
  shown = model.closed ? (previous ?? model.stage) : model.stage;

  const items = order.items ?? [];
  const label = model.closed ? "This order is closed" : `${items.map((i) => `${i.quantity} ${i.name}`).join(", ")}: ${model.steps[model.stage].label.toLowerCase()}`;
  const scene = el("div", { class: "order-scene", "data-stage": stage, "data-anim": motion, "data-from": from, "aria-hidden": "false" }, sceneSvg(items, label));
  if (items.length > MAX_DISHES) scene.append(el("p", { class: "order-scene__more" }, `+ ${items.length - MAX_DISHES} more on this order`));

  const initial = motion === "settled" ? model.stage : from;
  const stateAt = (i, at) => (model.closed ? model.steps[i].state : model.complete && at === model.stage ? "done" : i < at ? "done" : i === at ? "current" : "todo");
  const dots = model.steps.map((step, i) => el("span", { class: "order-track__dot", style: `--delay:0ms` }, tickMark()));
  const items_ = model.steps.map((step, i) => el("li", { class: "order-track__step", "data-state": model.closed ? step.state : stateAt(i, initial), "aria-current": step.state === "current" ? "step" : null },
    dots[i], el("span", { class: "order-track__label" }, step.label)));
  const duration = Math.max(1, model.stage - from) * STEP_MS;
  const track = el("div", { class: "order-track", "data-anim": motion, "data-closed": String(model.closed), "data-complete": String(model.complete), style: `--stage:${initial};--os-dur:${motion === "settled" ? 0 : duration}ms` },
    el("span", { class: "order-track__rail", "aria-hidden": "true" }, el("span", { class: "order-track__fill" }), el("span", { class: "order-track__token" }, plateIcon())),
    el("ol", { class: "order-track__steps", "aria-label": "Order progress" }, ...items_));

  if (motion !== "settled" && !model.closed) {
    afterPaint(() => {
      track.style.setProperty("--stage", String(model.stage));
      items_.forEach((li, i) => {
        li.setAttribute("data-state", model.steps[i].state);
        if (i > from && i <= model.stage) dots[i].style.setProperty("--delay", `${Math.max(0, (i - from) * STEP_MS - 140)}ms`);
        if (model.steps[i].state === "current") li.setAttribute("aria-current", "step");
      });
    });
  }
  return { scene, track };
}

function plateIcon() {
  return svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" }, svg("circle", { cx: 12, cy: 12, r: 8.5 }), svg("circle", { cx: 12, cy: 12, r: 4.5 }));
}
