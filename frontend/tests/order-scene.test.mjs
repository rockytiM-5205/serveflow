// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";
import { Elem } from "./dom-stub.mjs";
import { installDom } from "./dom-stub.mjs";

const { MAX_DISHES, dishLayout, foodKind, hueOf, orderProgress, plateDish, resetOrderScene, safePhoto, stageOf, trackModel } = await import("../customer/js/order-scene.js");

const all = (node, pred, out = []) => {
  if (node instanceof Elem) { if (pred(node)) out.push(node); node.children.forEach((c) => all(c, pred, out)); }
  return out;
};
const withClass = (node, name) => all(node, (n) => n.className.split(/\s+/).includes(name));
const order = (status, extra = {}) => {
  const chain = ["PENDING", "CONFIRMED", "SERVING", "READY_FOR_PICKUP", "COMPLETED"];
  const reached = chain.slice(0, chain.indexOf(status) + 1);
  return { status, timeline: reached.map((s) => ({ status: s })), items: [{ name: "Jollof rice", quantity: 2 }, { name: "Zobo drink", quantity: 1 }], ...extra };
};

test("each menu item gets a fitting dish, and unknown names still get one", () => {
  const cases = [["Jollof rice", "rice"], ["Fried rice and chicken", "rice"], ["Pounded yam and egusi soup", "soup"], ["Pepper soup with assorted meat", "soup"], ["Zobo drink", "drink"],
    ["Pure water", "drink"], ["Grilled chicken", "meat"], ["Chicken suya", "meat"], ["Fried plantain", "plantain"], ["Moi moi", "bread"], ["Ice cream", "dessert"], ["Grilled tilapia", "fish"],
    ["Amala", "swallow"], ["Fried egg", "egg"], ["Garden salad", "veg"], ["Chef's special", "dish"], ["", "dish"], [undefined, "dish"]];
  for (const [name, kind] of cases) assert.equal(foodKind(name), kind, String(name));
});

test("the dishes are spread on the plate, inside its rim, and arrive from outside it", () => {
  assert.deepEqual(dishLayout(0), []);
  for (let n = 1; n <= MAX_DISHES; n += 1) {
    const spots = dishLayout(n);
    assert.equal(spots.length, n);
    assert.equal(new Set(spots.map((s) => `${s.x},${s.y}`)).size, n, "no two dishes share a spot");
    for (const s of spots) {
      assert.ok(Math.hypot(s.x, s.y) <= 62, `dish at ${s.x},${s.y} is inside the plate`);
      assert.ok(Math.hypot(s.fx, s.fy) > 84, "it starts its trip outside the plate");
    }
  }
  assert.equal(dishLayout(9).length, MAX_DISHES, "a big order still shows a full plate");
});

test("the ticks follow the order's status", () => {
  const states = (m) => m.steps.map((s) => s.state);
  assert.deepEqual(states(trackModel(order("PENDING"))), ["current", "todo", "todo", "todo", "todo"]);
  assert.deepEqual(states(trackModel(order("SERVING"))), ["done", "done", "current", "todo", "todo"]);
  const finished = trackModel(order("COMPLETED"));
  assert.deepEqual(states(finished), ["done", "done", "done", "done", "done"]);
  assert.ok(finished.complete && finished.stage === 4);
  assert.equal(stageOf("READY_FOR_PICKUP"), 3);
});

test("a step the restaurant skipped still shows as done once the order has moved past it", () => {
  const skipped = order("COMPLETED", { timeline: [{ status: "PENDING" }, { status: "CONFIRMED" }, { status: "SERVING" }, { status: "COMPLETED" }] });
  assert.deepEqual(trackModel(skipped).steps.map((s) => s.state), ["done", "done", "done", "done", "done"]);
});

test("a cancelled or rejected order keeps the ticks it earned and shows no current step", () => {
  const m = trackModel({ status: "CANCELLED", timeline: [{ status: "PENDING" }, { status: "CONFIRMED" }, { status: "CANCELLED" }], items: [] });
  assert.ok(m.closed);
  assert.deepEqual(m.steps.map((s) => s.state), ["done", "done", "todo", "todo", "todo"]);
  assert.equal(m.stage, 1);
  assert.ok(!m.steps.some((s) => s.state === "current"));
});

test("the first view plays the whole story, repeats stay still, and a step forward plays only the new step", () => {
  installDom({ search: "", pathname: "/customer/order.html" });
  resetOrderScene();
  const first = orderProgress(order("SERVING"));
  assert.equal(first.scene.getAttribute("data-anim"), "intro");
  assert.equal(first.scene.getAttribute("data-stage"), "2");
  const again = orderProgress(order("SERVING"));
  assert.equal(again.scene.getAttribute("data-anim"), "settled");
  const next = orderProgress(order("READY_FOR_PICKUP"));
  assert.equal(next.scene.getAttribute("data-anim"), "advance");
  assert.equal(next.scene.getAttribute("data-from"), "2");
  resetOrderScene();
  assert.equal(orderProgress(order("SERVING")).scene.getAttribute("data-anim"), "intro");
});

test("every ordered item is drawn (up to five), with its quantity, and the rest are counted", () => {
  installDom({ search: "", pathname: "/customer/order.html" });
  resetOrderScene();
  const six = Array.from({ length: 6 }, (_, i) => ({ name: `Dish ${i}`, quantity: i === 0 ? 3 : 1 }));
  const { scene } = orderProgress(order("PENDING", { items: six }));
  assert.equal(withClass(scene, "os-dish").length, 5);
  assert.equal(withClass(scene, "os-qty").length, 1);
  assert.match(scene.textContent, /×3/);
  assert.match(scene.textContent, /\+ 1 more on this order/);
});

test("the ticks list exactly one current step, for screen readers, and closed orders are drawn grey", () => {
  installDom({ search: "", pathname: "/customer/order.html" });
  resetOrderScene();
  const { track } = orderProgress(order("CONFIRMED"));
  const current = all(track, (n) => n.getAttribute("aria-current") === "step");
  assert.equal(current.length, 1);
  assert.match(current[0].textContent, /Confirmed/);
  resetOrderScene();
  const closed = orderProgress({ status: "REJECTED", timeline: [{ status: "PENDING" }], items: [{ name: "Jollof rice", quantity: 1 }] });
  assert.equal(closed.scene.getAttribute("data-stage"), "closed");
  assert.equal(all(closed.track, (n) => n.getAttribute("aria-current") === "step").length, 0);
});

test("a dish is shown by its own photo first, then the style the restaurant chose, then its name, then its category", () => {
  assert.deepEqual(plateDish({ name: "Jollof rice", image_url: "https://img.example.com/j.jpg", dish_kind: "soup" }), { kind: "soup", photo: "https://img.example.com/j.jpg", seed: "Jollof rice" });
  assert.equal(plateDish({ name: "Jollof rice", dish_kind: "" }).kind, "rice", "automatic: from the name");
  assert.equal(plateDish({ name: "Jollof rice", dish_kind: "soup" }).kind, "soup", "the restaurant's choice wins over the name");
  assert.equal(plateDish({ name: "Mama's special", category: "Soups" }).kind, "soup", "an unknown name borrows its category");
  assert.equal(plateDish({ name: "Mama's special", category: "Drinks" }).kind, "drink");
  assert.equal(plateDish({ name: "Mama's special", category: "Specials" }).kind, "dish");
  assert.equal(plateDish({ name: "Jollof rice", dish_kind: "spaceship" }).kind, "rice", "an unknown style is ignored");
});

test("only our own uploads or https pictures are ever put on the plate", () => {
  assert.equal(safePhoto("https://img.example.com/a.webp"), "https://img.example.com/a.webp");
  assert.equal(safePhoto("/media/menu/1/a.webp"), "/media/menu/1/a.webp");
  for (const bad of ["http://x.test/a.png", "javascript:alert(1)", "data:image/svg+xml;base64,AAAA", "//evil.test/a.png", "", null, undefined, 42]) assert.equal(safePhoto(bad), null, String(bad));
});

test("a dish with no picture of its kind still looks its own: the same name always gets the same colour, different names differ", () => {
  assert.equal(hueOf("Mama's special"), hueOf("Mama's special"));
  assert.notEqual(hueOf("Mama's special"), hueOf("Chef's surprise"));
  assert.ok(hueOf("anything") >= 0 && hueOf("anything") < 360);
});

test("a photo goes on the plate over the drawing, and goes away again if it can't be loaded", () => {
  installDom({ search: "", pathname: "/customer/order.html" });
  resetOrderScene();
  const { scene } = orderProgress(order("PENDING", { items: [{ name: "Jollof rice", quantity: 1, image_url: "/media/menu/1/jollof.webp" }, { name: "Egusi", quantity: 1, image_url: "javascript:alert(1)" }] }));
  assert.equal(withClass(scene, "os-photo").length, 1, "the unsafe address is not used");
  assert.equal(withClass(scene, "os-dish__art").length, 2, "every dish keeps its drawing underneath");
  const image = all(scene, (n) => n.tagName === "IMAGE")[0];
  assert.equal(image.getAttribute("href"), "/media/menu/1/jollof.webp");
  image.listeners.get("error")?.forEach?.((fn) => fn());
  assert.equal(withClass(scene, "os-photo").length, 0, "a broken photo leaves the drawing");
});
