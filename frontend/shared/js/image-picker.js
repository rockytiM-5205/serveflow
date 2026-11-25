/* A small "choose a picture" control: a preview, a file button, and Remove. It checks the file before upload so people get
 * quick feedback; the server checks again (and re-encodes the picture) whatever this says. */
import { el, icon } from "./ui.js";

export const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const MAX_IMAGE_BYTES = 3 * 1024 * 1024;

/** null when the file looks fine, otherwise a message for the person. */
export function checkImageFile(file) {
  if (!file) return "Choose a picture.";
  if (!IMAGE_TYPES.includes(file.type)) return "Use a JPEG, PNG or WebP picture.";
  if (file.size > MAX_IMAGE_BYTES) return `That picture is too large. The limit is ${MAX_IMAGE_BYTES / (1024 * 1024)} MB.`;
  return null;
}

export function imagePicker({ label, currentUrl = null, hint = "JPEG, PNG or WebP, up to 3 MB.", wide = false }) {
  let chosen = null, removed = false, objectUrl = null;
  const id = `ip-${Math.random().toString(36).slice(2, 8)}`;
  const preview = el("div", { class: `picker__preview${wide ? " picker__preview--wide" : ""}` });
  const status = el("p", { class: "field__hint", id: `${id}-status`, role: "status" }, hint);
  const input = el("input", { class: "sr-only", type: "file", id, accept: IMAGE_TYPES.join(","), "aria-describedby": `${id}-status` });
  const choose = el("label", { class: "btn btn--secondary btn--sm", for: id }, icon("image"), "Choose picture");
  const remove = el("button", { class: "btn btn--ghost btn--sm", type: "button" }, "Remove");

  function paint() {
    const src = chosen ? objectUrl : (!removed ? currentUrl : null);
    preview.replaceChildren(src ? el("img", { src, alt: "" }) : el("span", { class: "picker__none", "aria-hidden": "true" }, icon("image", { large: true })));
    remove.hidden = !src;
    choose.lastChild.textContent = src ? "Change picture" : "Choose picture";
  }
  input.addEventListener("change", () => {
    const file = input.files?.[0] ?? null;
    if (!file) return;
    const problem = checkImageFile(file);
    if (problem) { status.textContent = problem; status.classList.add("field__error"); input.value = ""; return; }
    status.textContent = `${file.name} will be uploaded when you save.`;
    status.classList.remove("field__error");
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    chosen = file; objectUrl = URL.createObjectURL(file); removed = false;
    paint();
  });
  remove.addEventListener("click", () => {
    chosen = null; removed = true; input.value = "";
    if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
    status.textContent = currentUrl ? "The picture will be removed when you save." : hint;
    status.classList.remove("field__error");
    paint();
  });
  paint();
  return {
    node: el("div", { class: "picker" }, el("span", { class: "field__label" }, label), preview, el("div", { class: "row" }, choose, input, remove), status),
    /** The newly chosen file, or null. */
    file: () => chosen,
    /** True when there was a picture and the person asked to remove it (and didn't pick a new one). */
    removeRequested: () => removed && !chosen && Boolean(currentUrl),
  };
}

export function pictureForm(file) {
  const form = new FormData();
  form.append("file", file);
  return form;
}
