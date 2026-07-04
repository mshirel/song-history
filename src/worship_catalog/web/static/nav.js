/**
 * Keep the mobile nav checkbox's aria-expanded state synchronized with its
 * actual checked state. External file preserves CSP script-src 'self'.
 */
(function () {
  "use strict";

  function syncExpanded(toggle) {
    toggle.setAttribute("aria-expanded", toggle.checked ? "true" : "false");
  }

  function init() {
    var toggle = document.getElementById("nav-toggle");
    if (!toggle) return;
    syncExpanded(toggle);
    toggle.addEventListener("change", function () {
      syncExpanded(toggle);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
