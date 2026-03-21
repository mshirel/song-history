/**
 * Upload form handler — reads CSRF cookie and submits via fetch with the token header.
 * After a successful upload, polls the job status endpoint until complete (#276).
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

  /** Poll /jobs/{id} until status is complete or failed (#276). */
  function pollJobStatus(jobId, resultEl) {
    var pollInterval = 2000; // 2 seconds
    var maxPolls = 90; // 3 minutes max
    var polls = 0;

    function check() {
      polls++;
      if (polls > maxPolls) {
        resultEl.innerHTML =
          '<p style="color:#856404;">Import is still running. ' +
          'Refresh the page later to check results.</p>';
        return;
      }
      fetch("/jobs/" + jobId)
        .then(function (resp) {
          return resp.json();
        })
        .then(function (job) {
          if (job.status === "complete") {
            if (job.songs_imported === 0) {
              resultEl.innerHTML =
                '<p style="color:#856404;">' +
                "Import complete \u2014 no songs found. " +
                "The file may not be a worship slide deck.</p>";
            } else {
              resultEl.innerHTML =
                '<p style="color:green;">' +
                "Import complete \u2014 " +
                job.songs_imported +
                " song(s) imported.</p>";
            }
          } else if (job.status === "failed") {
            resultEl.innerHTML =
              '<p style="color:#c00;">Import failed: ' +
              (job.error_message || "unknown error") +
              "</p>";
          } else {
            resultEl.innerHTML =
              '<p style="color:#495057;">Importing\u2026 ' +
              '<span class="htmx-indicator" style="opacity:1;">processing</span></p>';
            setTimeout(check, pollInterval);
          }
        })
        .catch(function () {
          setTimeout(check, pollInterval);
        });
    }

    check();
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
          '<p style="color:#495057;">Upload accepted \u2014 importing\u2026</p>';
        pollJobStatus(j.job_id, result);
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
