/**
 * Report form CSRF handler — reads the csrftoken cookie and submits report
 * download forms via fetch with the X-CSRFToken header (#238).
 *
 * Also configures htmx globally to include the CSRF header on every request
 * so that hx-post forms (like the stats generate form) are not blocked.
 *
 * This must be an external file (not inline) to comply with CSP script-src 'self'.
 */
(function () {
  "use strict";

  /** Read the csrftoken cookie value set by starlette-csrf middleware. */
  function getCsrfToken() {
    var token = "";
    document.cookie.split(";").forEach(function (c) {
      var parts = c.trim().split("=");
      if (parts[0] === "csrftoken") token = parts[1];
    });
    return token;
  }

  /**
   * Configure htmx to include the CSRF header on every AJAX request.
   * This covers hx-post forms like the stats "Generate" button.
   */
  function configureHtmxCsrf() {
    var token = getCsrfToken();
    if (token) {
      document.body.setAttribute(
        "hx-headers",
        JSON.stringify({ "X-CSRFToken": token })
      );
    }
  }

  /**
   * Intercept a form submission: collect its FormData, POST via fetch with
   * the CSRF header, and trigger a file download from the response.
   */
  function interceptDownloadForm(formId) {
    var form = document.getElementById(formId);
    if (!form) return;

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = form.querySelector("button[type=submit]");
      var origText = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Downloading\u2026";

      var data = new URLSearchParams(new FormData(form));
      fetch(form.action, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: data,
      })
        .then(function (resp) {
          if (!resp.ok) {
            return resp.text().then(function (t) {
              throw new Error(t || resp.statusText);
            });
          }
          /* Extract filename from Content-Disposition header if present. */
          var filename = "download";
          var cd = resp.headers.get("content-disposition");
          if (cd) {
            var match = cd.match(/filename="?([^";\r\n]+)"?/);
            if (match) filename = match[1];
          }
          return resp.blob().then(function (blob) {
            var url = URL.createObjectURL(blob);
            var a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
          });
        })
        .catch(function (err) {
          alert("Download failed: " + err.message);
        })
        .finally(function () {
          btn.disabled = false;
          btn.textContent = origText;
        });
    });
  }

  /* Initialise on DOMContentLoaded (or immediately if already loaded). */
  function init() {
    configureHtmxCsrf();
    interceptDownloadForm("ccli-form");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
