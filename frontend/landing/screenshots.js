/* Real product screenshots, shown only when the image files exist. Drop PNG or JPG files named in index.html (data-shot) into
 * landing/assets/screens/ and the "Inside ServeFlow" section appears; until then it stays hidden and nothing is invented. */
const section = document.getElementById("product");
const figures = [...document.querySelectorAll("figure[data-shot]")];

function load(figure) {
  return new Promise((resolve) => {
    const img = new Image();
    img.alt = figure.dataset.alt || "";
    img.decoding = "async";
    img.loading = "lazy";
    img.addEventListener("load", () => { figure.prepend(img); figure.hidden = false; resolve(true); }, { once: true });
    img.addEventListener("error", () => resolve(false), { once: true });
    img.src = figure.dataset.shot;
  });
}

if (section && figures.length) {
  Promise.all(figures.map(load)).then((results) => {
    if (results.some(Boolean)) section.hidden = false;
  });
}
