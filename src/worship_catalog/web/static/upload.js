/**
 * Upload form handler — reads CSRF cookie and submits via fetch with the token header.
 * This must be an external file (not inline) to comply with CSP script-src 'self'.
 */
(function () {
  "use strict";

  function getCsrfToken() {
    var token = "";
    document.cookie.split(";").forEach(function (c) {
      var parts = c.trim().split("=");
      if (parts[0] === "csrftoken") token = parts[1];
    });
    return token;
  }

  var form = document.getElementById("upload-form");
  if (!form) return;

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = form.querySelector("button[type=submit]");
    var result = document.getElementById("upload-result");
    btn.disabled = true;
    btn.textContent = "Uploading\u2026";
    result.innerHTML = "";

    var data = new FormData(form);
    fetch("/upload", {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
      body: data,
    })
      .then(function (resp) {
        if (resp.ok) return resp.json();
        return resp.json().then(function (j) {
          throw new Error(j.detail || resp.statusText);
        });
      })
      .then(function (j) {
        result.innerHTML =
          '<p style="color:green;">Accepted &mdash; job ID: <code>' +
          j.job_id +
          "</code>. Import is running in the background.</p>";
      })
      .catch(function (err) {
        result.innerHTML =
          '<p style="color:#c00;">Upload failed: ' + err.message + "</p>";
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Upload";
      });
  });
})();
