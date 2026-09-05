(function () {
  const overlay = document.getElementById("page-loading-overlay");

  function show() {
    overlay.hidden = false;
  }

  // Full page navigations (this app has no client-side routing) give no
  // built-in feedback while the server is working - some routes (the
  // dashboard's several GW2 API calls in particular) can take a couple of
  // seconds, which otherwise looks like the click did nothing.
  document.querySelectorAll("a[href]").forEach((link) => {
    if (link.target === "_blank" || link.href.startsWith("mailto:")) return;
    link.addEventListener("click", show);
  });
  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", show);
  });

  // If the page is restored from the browser's back/forward cache, the
  // overlay from the click that navigated away would otherwise still be
  // showing.
  window.addEventListener("pageshow", () => {
    overlay.hidden = true;
  });
})();
