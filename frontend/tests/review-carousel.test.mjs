// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";
import { Elem, installDom } from "./dom-stub.mjs";

const { MIN_TO_MOVE, initialOf, loopSeconds, reviewCard, reviewMarquee } = await import("../customer/js/review-carousel.js");
const all = (node, pred, out = []) => { if (node instanceof Elem) { if (pred(node)) out.push(node); node.children.forEach((c) => all(c, pred, out)); } return out; };
const withClass = (node, name) => all(node, (n) => n.className.split(/\s+/).includes(name));
const review = (name, rating = 5, comment = "Lovely") => ({ display_name: name, rating, comment, created_at: "2026-11-20T10:00:00Z" });
const fire = (node, type) => node.listeners.get(type)?.forEach((fn) => fn());

test("the badge shows the first letter of the name", () => {
  assert.equal(initialOf("peter"), "P");
  assert.equal(initialOf("  Ajiloseda A."), "A");
  assert.equal(initialOf(""), "C");
  assert.equal(initialOf(undefined), "C");
});

test("the row goes slower with more cards, never faster than a readable pace", () => {
  assert.equal(loopSeconds(3), 24);
  assert.equal(loopSeconds(10), 70);
  assert.ok(loopSeconds(20) > loopSeconds(10));
});

test("every review is a card of the same design, with its own name, stars and words", () => {
  installDom({ search: "", pathname: "/customer/index.html" });
  const a = reviewCard(review("Peter", 4, "Great jollof"));
  const b = reviewCard(review("samuel", 3, ""));
  for (const card of [a, b]) assert.deepEqual(["review-card__head", "review-card__text"].map((c) => withClass(card, c).length), [1, 1]);
  assert.match(a.textContent, /Peter/);
  assert.match(a.textContent, /Great jollof/);
  assert.equal(withClass(a, "star--on").length, 4);
  assert.equal(withClass(b, "star--on").length, 3);
  assert.match(b.textContent, /Left a rating without a comment/);
});

test("a few reviews stay still, enough reviews move, and the moving row is doubled for a seamless loop", () => {
  installDom({ search: "", pathname: "/customer/index.html" });
  const few = reviewMarquee([review("A"), review("B")]);
  assert.equal(few.getAttribute("data-moving"), "false");
  assert.equal(withClass(few, "review-card").length, 2);
  const many = reviewMarquee(Array.from({ length: MIN_TO_MOVE }, (_, i) => review(`Name${i}`)));
  assert.equal(many.getAttribute("data-moving"), "true");
  const groups = withClass(many, "review-marquee__group");
  assert.equal(groups.length, 2);
  assert.equal(groups[1].getAttribute("aria-hidden"), "true", "the copy is hidden from screen readers");
  assert.equal(withClass(many, "review-card").length, MIN_TO_MOVE * 2);
});

test("pressing on the row holds it still and letting go sets it moving again", () => {
  installDom({ search: "", pathname: "/customer/index.html" });
  const row = reviewMarquee(Array.from({ length: 5 }, (_, i) => review(`N${i}`)));
  assert.equal(row.getAttribute("data-paused"), "false");
  fire(row, "pointerdown");
  assert.equal(row.getAttribute("data-paused"), "true");
  fire(row, "pointerup");
  assert.equal(row.getAttribute("data-paused"), "false");
  fire(row, "pointerdown"); fire(row, "pointerleave");
  assert.equal(row.getAttribute("data-paused"), "false", "moving the finger off the row also lets it go");
  fire(row, "pointerdown"); fire(row, "pointercancel");
  assert.equal(row.getAttribute("data-paused"), "false", "a touch the browser takes over (a scroll) also lets it go");
  fire(row, "focusin");
  assert.equal(row.getAttribute("data-paused"), "true");
  fire(row, "focusout");
  assert.equal(row.getAttribute("data-paused"), "false");
});
