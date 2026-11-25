/* Pictures that never show a broken-image icon. A restaurant's logo, cover or a dish photo can fail to load for ordinary reasons (a slow
 * moment on the connection, a file that was moved, an address that expired). So: try once more, and if it still fails, quietly put a
 * fitting stand-in in its place (or nothing), so the page always looks finished. */
import { el } from "./ui.js";

/** The same address, asking the server again (adds a tiny marker for our own files; other sites' addresses are reused as they are). */
export function retryAddress(src, base = globalThis.location?.href) {
  try {
    const url = new URL(src, base);
    if (url.origin === new URL(base).origin) url.searchParams.set("_r", "1");
    return url.href;
  } catch {
    return src;
  }
}

/**
 * @param src       the picture's address
 * @param fallback  what to show instead if it can't be loaded: an element, a function that returns one (or null), or nothing
 * @param onFail    called once when the picture has been given up on (for example to remove a frame that only made sense with a picture)
 */
export function robustImage({ src, alt = "", className, fallback = null, onFail = null, retryMs = 1200, attrs = {} }) {
  const img = el("img", { class: className, src, alt, decoding: "async", ...attrs });
  let retried = false;
  img.addEventListener("error", () => {
    if (!retried) {
      retried = true;
      setTimeout(() => img.setAttribute("src", retryAddress(src)), retryMs);
      return;
    }
    const stand = typeof fallback === "function" ? fallback() : fallback;
    if (stand) img.replaceWith(stand); else img.remove();
    onFail?.();
  });
  return img;
}
