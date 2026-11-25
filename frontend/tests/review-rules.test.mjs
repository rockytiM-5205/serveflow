// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

import { RETURN_MAX_AGE_MS, isOrderReturn, safeNext } from "../customer/js/account-helpers.js";

const TOKEN = "Zk3Qm9_vT2xLpR8dYh4WbN6cJf1AaS5gUe7Ko0Ii";

test("only a real order page can be returned to after signing in", () => {
  assert.equal(isOrderReturn(`order.html?r=green-bowl#${TOKEN}`), true);
  for (const bad of ["order.html", "order.html?r=green-bowl", `order.html?r=green-bowl#short`, `https://evil.test/order.html?r=green-bowl#${TOKEN}`,
    `//evil.test/order.html?r=a-b-c#${TOKEN}`, `account.html?r=green-bowl#${TOKEN}`, `order.html?r=../x#${TOKEN}`, `javascript:alert(1)`, "", null, undefined, 7]) {
    assert.equal(isOrderReturn(bad), false, String(bad));
  }
});

test("the remembered order link is only good for a short while", () => {
  assert.ok(RETURN_MAX_AGE_MS >= 10 * 60 * 1000 && RETURN_MAX_AGE_MS <= 60 * 60 * 1000);
});

test("the normal 'next' page after signing in still refuses anything that carries an order link", () => {
  assert.equal(safeNext(`order.html?r=green-bowl#${TOKEN}`), "my-orders.html");
  assert.equal(safeNext("menu.html?r=green-bowl"), "menu.html?r=green-bowl");
});
