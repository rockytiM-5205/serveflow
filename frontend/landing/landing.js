/* Landing page behaviour: mobile menu, optional photos, a gentle "live" demo in the mockup, current-section link. */
const toggle = document.querySelector(".nav-toggle");
const nav = document.getElementById("site-nav");

function setMenu(open) {
  nav.dataset.open = String(open);
  toggle.setAttribute("aria-expanded", String(open));
}
toggle.addEventListener("click", () => setMenu(nav.dataset.open !== "true"));
nav.addEventListener("click", (event) => {
  if (event.target.closest("a")) setMenu(false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && nav.dataset.open === "true") {
    setMenu(false);
    toggle.focus();
  }
});

// Photos are optional: until a real image is added, the layout simply shows its colour block.
document.querySelectorAll("img[data-optional]").forEach((img) => {
  const missing = () => {
    img.hidden = true;
    img.parentElement.dataset.empty = "true";
  };
  img.addEventListener("error", missing, { once: true });
  if (img.complete && img.naturalWidth === 0) missing();
});

// Gentle reveal as sections scroll into view. Skipped for people who ask for reduced motion, and nothing is hidden without JS.
const REVEAL = ".how__intro, .step, .why__intro, .feature, .photo, .rush__intro, .facts li, .rush__api, .cta__inner, .pricing__intro, .plan-card";
const motionOk = !matchMedia("(prefers-reduced-motion: reduce)").matches && "IntersectionObserver" in window;
const revealer = motionOk ? new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    entry.target.classList.add("in");
    revealer.unobserve(entry.target);
  });
}, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }) : null;
if (motionOk) document.documentElement.classList.add("js-motion");
export function revealAll() {
  if (!revealer) return;
  const seen = new Map();
  document.querySelectorAll(REVEAL).forEach((node) => {
    if (node.classList.contains("reveal")) return;
    const parent = node.parentElement;
    const index = seen.get(parent) ?? 0;
    seen.set(parent, index + 1);
    node.style.setProperty("--reveal-delay", `${Math.min(index, 4) * 70}ms`);
    node.classList.add("reveal");
    revealer.observe(node);
  });
}
revealAll();

// Highlight the nav link of the section being read.
const links = new Map([...nav.querySelectorAll('a[href^="#"]')].map((a) => [a.getAttribute("href").slice(1), a]));
const spy = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    const current = entry.target.dataset.spyId;
    links.forEach((link, id) => link.setAttribute("aria-current", String(id === current)));
  });
}, { rootMargin: "-40% 0px -55% 0px" });
["top", "features", "how"].forEach((id) => {
  const target = id === "top" ? document.querySelector(".hero") : document.getElementById(id);
  if (target) {
    target.dataset.spyId = id;
    spy.observe(target);
  }
});

document.getElementById("year").textContent = new Date().getFullYear();
