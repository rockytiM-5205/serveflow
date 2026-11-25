/* If a page's script can't start (a file missing, an out-of-date copy, a script error), say so instead of leaving a blank page.
 * A plain script with no imports, so it still runs when the module scripts fail. */
(function () {
  var shown = false;
  function stillLoading() {
    var content = document.getElementById("content");
    return content && content.querySelector(".skeleton") ? content : null;
  }
  function explain(detail) {
    var content = stillLoading();
    if (shown || !content) return;
    shown = true;
    var box = document.createElement("div");
    box.className = "card card__pad stack";
    box.setAttribute("role", "alert");
    var title = document.createElement("h2");
    title.textContent = "This page couldn't start";
    var text = document.createElement("p");
    text.textContent = "Please refresh the page. If it keeps happening, the site's files may be out of date: tell whoever looks after this site.";
    var small = document.createElement("p");
    small.className = "muted";
    small.textContent = detail ? "Technical detail: " + detail : "";
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--secondary";
    button.textContent = "Refresh";
    button.addEventListener("click", function () { location.reload(); });
    box.append(title, text, small, button);
    content.replaceChildren(box);
  }
  // A script that fails to load or throws while starting.
  window.addEventListener("error", function (event) {
    var target = event.target;
    if (target && target.tagName === "SCRIPT") explain("could not load " + (target.getAttribute("src") || "a script"));
    else if (event.message) explain(event.message);
  }, true);
  window.addEventListener("unhandledrejection", function (event) {
    explain(event.reason && event.reason.message ? event.reason.message : "");
  });
  // Nothing replaced the placeholder after a long wait: don't leave a blank page.
  setTimeout(function () { explain("the page did not finish loading"); }, 15000);
})();
