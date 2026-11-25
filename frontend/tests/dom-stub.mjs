/* A very small fake browser, just enough to run our page scripts in Node and click their buttons.
 * It is a smoke-test helper (it catches "the button does nothing" bugs such as a variable used outside its scope),
 * not a faithful browser. Install it BEFORE importing a page script. */

class Text {
  constructor(data) { this.data = String(data); this.parentNode = null; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}

const REFLECT = new Set(["id", "href", "name", "type", "for", "src", "title", "placeholder", "lang"]);
const BOOLEAN = new Set(["hidden", "disabled", "required", "open", "readonly"]);

function matchesSimple(node, part) {
  if (!(node instanceof Elem)) return false;
  const checked = part.endsWith(":checked");
  if (checked) { if (!node.checked) return false; part = part.slice(0, -":checked".length); }
  const m = part.match(/^([a-zA-Z][a-zA-Z0-9-]*)?((?:[#.][\w-]+|\[[^\]]+\])*)$/);
  if (!m) return false;
  if (m[1] && node.tagName.toLowerCase() !== m[1].toLowerCase()) return false;
  for (const token of m[2].match(/[#.][\w-]+|\[[^\]]+\]/g) ?? []) {
    if (token[0] === "#" && node.getAttribute("id") !== token.slice(1)) return false;
    if (token[0] === "." && !node.className.split(/\s+/).includes(token.slice(1))) return false;
    if (token[0] === "[") {
      const [name, value] = token.slice(1, -1).split("=");
      const have = node.getAttribute(name);
      if (have === null) return false;
      if (value !== undefined && have !== value.replace(/^["']|["']$/g, "")) return false;
    }
  }
  return true;
}

export class Elem {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.attrs = {};
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.style = { setProperty(name, value) { this[name] = value; } };
    this.listeners = new Map();
    this.value = "";
    this.checked = false;
    this.isElem = true;
    for (const name of REFLECT) Object.defineProperty(this, name, { get: () => this.getAttribute(name) ?? "", set: (v) => this.setAttribute(name, v), configurable: true });
    for (const name of BOOLEAN) Object.defineProperty(this, name, { get: () => this.hasAttribute(name), set: (v) => this.toggleAttribute(name, !!v), configurable: true });
  }
  get className() { return this.attrs.class ?? ""; }
  set className(v) { this.attrs.class = String(v); }
  get classList() {
    const self = this;
    const list = () => self.className.split(/\s+/).filter(Boolean);
    return { add: (...c) => { self.className = [...new Set([...list(), ...c])].join(" "); }, remove: (...c) => { self.className = list().filter((x) => !c.includes(x)).join(" "); },
      contains: (c) => list().includes(c), toggle: (c, force) => { const has = list().includes(c); const want = force ?? !has; self.classList[want ? "add" : "remove"](c); return want; } };
  }
  setAttribute(name, value) { this.attrs[name] = String(value); if (name === "value") this.value = String(value); if (name === "checked") this.checked = true; }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  hasAttribute(name) { return name in this.attrs; }
  removeAttribute(name) { delete this.attrs[name]; }
  toggleAttribute(name, force) { const want = force ?? !this.hasAttribute(name); if (want) this.attrs[name] = ""; else delete this.attrs[name]; return want; }
  adopt(items) {
    // Like a real browser: anything that is not a node becomes text, so a stray null shows up as the word "null".
    return items.map((c) => { const node = c instanceof Elem || c instanceof Text ? c : new Text(c); if (node.parentNode) node.remove(); node.parentNode = this; return node; });
  }
  append(...items) { this.children.push(...this.adopt(items)); }
  prepend(...items) { this.children.unshift(...this.adopt(items)); }
  replaceChildren(...items) { this.children.forEach((c) => { c.parentNode = null; }); this.children = this.adopt(items); }
  after(...items) { const p = this.parentNode; if (!p) return; const i = p.children.indexOf(this); p.children.splice(i + 1, 0, ...p.adopt(items)); }
  before(...items) { const p = this.parentNode; if (!p) return; const i = p.children.indexOf(this); p.children.splice(i, 0, ...p.adopt(items)); }
  replaceWith(...nodes) { const parent = this.parentNode; if (!parent) return; const at = parent.children.indexOf(this); this.remove(); for (const n of nodes) { const node = n instanceof Elem || n instanceof Text ? n : new Text(n); if (node.parentNode) node.remove(); node.parentNode = parent; parent.children.splice(at, 0, node); } }
  remove() { if (this.parentNode) { this.parentNode.children = this.parentNode.children.filter((c) => c !== this); this.parentNode = null; } }
  get firstElementChild() { return this.children.find((c) => c instanceof Elem) ?? null; }
  get lastElementChild() { return [...this.children].reverse().find((c) => c instanceof Elem) ?? null; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === globalThis.document?.documentElement; }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(String(v)); }
  descendants() { return this.children.flatMap((c) => (c instanceof Elem ? [c, ...c.descendants()] : [])); }
  matches(selector) {
    const parts = selector.trim().split(/\s+/);
    if (!matchesSimple(this, parts.at(-1))) return false;
    let node = this.parentNode; let i = parts.length - 2;
    while (i >= 0 && node) { if (matchesSimple(node, parts[i])) i -= 1; node = node.parentNode; }
    return i < 0;
  }
  querySelectorAll(selector) { return this.descendants().filter((n) => n.matches(selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  closest(selector) { for (let n = this; n; n = n.parentNode) if (n instanceof Elem && n.matches(selector)) return n; return null; }
  addEventListener(type, fn) { if (!this.listeners.has(type)) this.listeners.set(type, []); this.listeners.get(type).push(fn); }
  removeEventListener(type, fn) { this.listeners.set(type, (this.listeners.get(type) ?? []).filter((f) => f !== fn)); }
  dispatchEvent(event) {
    event.target ??= this;
    event.defaultPrevented ??= false;
    event.preventDefault ??= () => { event.defaultPrevented = true; };
    for (let n = this; n; n = n.parentNode) {
      event.currentTarget = n;
      for (const fn of n.listeners?.get(event.type) ?? []) fn(event);
    }
    return !event.defaultPrevented;
  }
  click() { this.dispatchEvent({ type: "click" }); }
  focus() { globalThis.document.activeElement = this; }
  blur() {}
  reset() {}
  scrollIntoView() {}
  showModal() { this.attrs.open = ""; }
  close(value) { if (value !== undefined) this.returnValue = value; delete this.attrs.open; this.dispatchEvent({ type: "close" }); }
  getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; }
}

const realSetTimeout = globalThis.setTimeout;

/** Set up globals. Returns helpers. Page timers (polling, timeouts) are unref'd so they never keep the test process alive. */
export function installDom({ search = "", hash = "", pathname = "/customer/checkout.html" } = {}) {
  const body = new Elem("body");
  const root = new Elem("html");
  root.append(body);
  const store = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), clear: () => m.clear() }; };
  const navigations = [];
  const location = {
    search, hash, pathname, origin: "http://localhost",
    get href() { return `http://localhost${this.pathname}${this.search}${this.hash}`; },
    set href(v) { navigations.push(v); },
    replace: (v) => navigations.push(v), assign: (v) => navigations.push(v), reload: () => navigations.push("reload"),
  };
  const doc = {
    body, documentElement: root, head: new Elem("head"), title: "", cookie: "", activeElement: null,
    createElement: (tag) => new Elem(tag), createElementNS: (_ns, tag) => new Elem(tag), createTextNode: (t) => new Text(t),
    getElementById: (id) => root.descendants().find((n) => n.getAttribute("id") === id) ?? null,
    querySelector: (s) => root.querySelector(s), querySelectorAll: (s) => root.querySelectorAll(s),
    addEventListener() {}, removeEventListener() {},
  };
  const events = new EventTarget();
  Object.assign(globalThis, {
    document: doc, location, localStorage: store(), sessionStorage: store(), history: { replaceState() {}, pushState() {} },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener: (...a) => events.addEventListener(...a), removeEventListener: (...a) => events.removeEventListener(...a),
    dispatchEvent: (e) => events.dispatchEvent(e), scrollTo() {}, requestAnimationFrame: (fn) => setTimeout(fn, 0),
    Element: Elem, HTMLElement: Elem, Node: Elem,
  });
  globalThis.window = globalThis;
  globalThis.setTimeout = (...args) => { const t = realSetTimeout(...args); t.unref?.(); return t; };
  const realSetInterval = globalThis.setInterval;
  globalThis.setInterval = (...args) => { const t = realSetInterval(...args); t.unref?.(); return t; };
  // FormData over our fake form: the named inputs, as a browser would collect them.
  globalThis.FormData = class FormData {
    constructor(form) { this.map = new Map(); for (const i of form?.querySelectorAll?.("input") ?? []) if (i.getAttribute("name")) this.map.set(i.getAttribute("name"), i.value); }
    get(name) { return this.map.get(name) ?? null; }
    has(name) { return this.map.has(name); }
  };
  return { body, navigations, doc, location };
}

/** Make fetch answer from a table: routes[`${METHOD} ${path}`] = (body) => [status, json]. Returns the log of calls. */
export function fakeApi(routes) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const path = String(url).replace(/^\/api\/v1/, "").split("?")[0];
    const method = init.method ?? "GET";
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body, headers: init.headers });
    const handler = routes[`${method} ${path}`];
    if (!handler) return new Response(JSON.stringify({ error: { code: "not_found", message: `No stub for ${method} ${path}`, details: {} } }), { status: 404 });
    const [status, json] = typeof handler === "function" ? handler(body) : handler;
    return new Response(json === null ? null : JSON.stringify(json), { status });
  };
  return calls;
}

export const tick = (ms = 0) => new Promise((resolve) => realSetTimeout(resolve, ms));

/** Wait until `check()` is truthy (a page script finishing its async setup). */
export async function until(check, what = "the page", tries = 200) {
  for (let i = 0; i < tries; i += 1) { const value = check(); if (value) return value; await tick(5); }
  throw new Error(`Timed out waiting for ${what}`);
}
