/**
 * Delete-song controls on the service detail page (#323).
 *
 * This file exists because the obvious implementation — a plain
 * `<form method="post">` with an inline `onsubmit="return confirm(...)"` —
 * is broken twice over on this app, and both failures are silent:
 *
 *   1. CSRF. SelfHealingCSRFMiddleware reads the token ONLY from the
 *      `X-CSRFToken` request header, never from a form field. A native form
 *      submission sends no such header, so every real-browser click returned
 *      403 "CSRF token verification failed". Adding a hidden input would not
 *      help — the middleware does not look there. Every other POST surface in
 *      this app already goes through fetch or htmx for exactly this reason.
 *
 *   2. CSP. The app sends `script-src 'self'` with no `unsafe-inline` and no
 *      `unsafe-hashes`, so an inline event handler is refused outright by the
 *      browser. The confirm() never ran — meaning that once the CSRF problem
 *      was fixed, a single misclick would have destroyed a setlist row and its
 *      copy events with no prompt at all. The repo has paid for this defect
 *      class before (review #247, inline JavaScript in upload.html).
 *
 * Neither was visible from the test suite: the test client sets the CSRF header
 * on every POST, so it arranges a precondition a browser never supplies, and it
 * does not execute JavaScript or enforce CSP at all. Both were found in a real
 * browser, which is the only place they show up.
 */
(function () {
  "use strict";

  /**
   * Read the csrftoken cookie fresh on every use. The middleware can replace it
   * after a secret rotation, so a cached value would keep replaying a stale
   * token and start 403ing again after an app restart.
   */
  function getCsrfToken() {
    var token = "";
    document.cookie.split(";").forEach(function (c) {
      var parts = c.trim().split("=");
      if (parts[0] === "csrftoken") token = parts[1];
    });
    return token;
  }

  function bindDeleteForms() {
    var forms = document.querySelectorAll("form[data-song-title]");
    Array.prototype.forEach.call(forms, function (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();

        // The title comes from a data attribute, not from JavaScript that the
        // template generated: song titles arrive from OCR and PowerPoint decks
        // and are not trusted. Interpolating one into a JS string literal broke
        // on "I'll Fly Away" and executed on ');alert(1);//.
        var title = form.getAttribute("data-song-title") || "this song";
        var message =
          'Remove "' +
          title +
          '" from this service?\n\n' +
          "This also removes it from the CCLI report. It cannot be undone " +
          "without re-uploading the slide deck.";
        if (!window.confirm(message)) return;

        var btn = form.querySelector("button[type=submit]");
        if (btn) {
          btn.disabled = true;
          btn.textContent = "Removing…";
        }

        fetch(form.action, {
          method: "POST",
          headers: { "X-CSRFToken": getCsrfToken() },
          // Send the session cookie AND the Basic-auth credentials the browser
          // already holds — this route is behind the same upload auth as
          // /upload, and fetch omits credentials by default on some paths.
          credentials: "same-origin",
        })
          .then(function (resp) {
            if (!resp.ok) {
              return resp.text().then(function (t) {
                throw new Error(t || resp.statusText);
              });
            }
            // The route answers 303 to the service page; fetch follows it, so
            // reload rather than trying to swap the row out by hand. A reload
            // also re-renders every derived number on the page.
            window.location.reload();
          })
          .catch(function (err) {
            if (btn) {
              btn.disabled = false;
              btn.textContent = "Remove";
            }
            window.alert("Could not remove the song: " + err.message);
          });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindDeleteForms);
  } else {
    bindDeleteForms();
  }
})();
