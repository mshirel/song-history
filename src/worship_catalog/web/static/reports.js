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

  /**
   * Bind download handlers for forms that appear after HTMX content swaps
   * (e.g. stats CSV/XLSX forms loaded inside #stats-result) (#288).
   */
  function bindDynamicDownloadForms() {
    interceptDownloadForm("stats-csv-form");
    interceptDownloadForm("stats-xlsx-form");
  }

  /**
   * Wire up the Reports tablist: clicking or arrow-keying a tab activates it
   * and shows its panel, following the ARIA tabs pattern. Keeps the page CSP
   * compliant (no inline JS).
   */
  function setupTabs() {
    var tablist = document.querySelector('[role="tablist"]');
    if (!tablist) return;
    var tabs = Array.prototype.slice.call(
      tablist.querySelectorAll('[role="tab"]')
    );
    if (!tabs.length) return;

    function activate(tab, setFocus) {
      tabs.forEach(function (t) {
        var selected = t === tab;
        t.setAttribute("aria-selected", selected ? "true" : "false");
        t.setAttribute("tabindex", selected ? "0" : "-1");
        t.classList.toggle("active", selected);
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !selected;
      });
      if (setFocus) tab.focus();
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () {
        activate(tab, false);
      });
      tab.addEventListener("keydown", function (e) {
        var idx = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          idx = (i + 1) % tabs.length;
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          idx = (i - 1 + tabs.length) % tabs.length;
        } else if (e.key === "Home") {
          idx = 0;
        } else if (e.key === "End") {
          idx = tabs.length - 1;
        }
        if (idx !== null) {
          e.preventDefault();
          activate(tabs[idx], true);
        }
      });
    });
  }

  /**
   * Surface HTMX error responses (e.g. a 422 from an inverted date range) in
   * the triggering form's result region (#496). htmx only swaps 2xx responses
   * by default, so without this a validation error produces no DOM change and
   * the user sees nothing happen. The server returns a small HTML fragment for
   * HTMX error responses; inject it into the request's target region.
   */
  function showHtmxError(evt) {
    var detail = evt.detail || {};
    var target = detail.target;
    /* Fall back to the triggering element's hx-target if htmx didn't resolve
       one (e.g. some error paths). */
    if (!target && detail.elt && detail.elt.closest) {
      var withTarget = detail.elt.closest("[hx-target]");
      if (withTarget) {
        target = document.querySelector(withTarget.getAttribute("hx-target"));
      }
    }
    if (!target) return;
    var xhr = detail.xhr;
    var body = xhr && xhr.responseText ? xhr.responseText.trim() : "";
    if (body) {
      /* Server-rendered fragment; `detail` is Jinja-autoescaped so this is
         safe to inject and matches how htmx swaps content. */
      target.innerHTML = body;
    } else {
      target.textContent =
        "Something went wrong — please check your input and try again.";
    }
  }

  /* Initialise on DOMContentLoaded (or immediately if already loaded). */
  function init() {
    configureHtmxCsrf();
    setupTabs();
    interceptDownloadForm("ccli-form");

    /* Re-bind download forms after each HTMX swap so dynamically loaded
       forms (stats CSV/XLSX) get the CSRF fetch handler (#288). */
    document.body.addEventListener("htmx:afterSwap", function () {
      bindDynamicDownloadForms();
    });

    /* Show a friendly message when an HTMX request errors (#496). */
    document.body.addEventListener("htmx:responseError", showHtmxError);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
