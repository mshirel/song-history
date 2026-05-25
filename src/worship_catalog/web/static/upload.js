/**
 * Upload form handler — reads CSRF cookie and submits via fetch with the token header.
 * After a successful upload, polls the job status endpoint until complete (#276).
 * This must be an external file (not inline) to comply with CSP script-src 'self'.
 *
 * All server-provided strings (job.error_message, err.message, counts) are
 * rendered with textContent — never concatenated into innerHTML — so a crafted
 * error message cannot inject markup (DOM-XSS defence-in-depth, #401).
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

  /**
   * Replace the contents of `el` with a single styled <p> whose text is set
   * via textContent, so `text` is never interpreted as HTML.
   */
  function showMessage(el, color, text) {
    var p = document.createElement("p");
    p.style.color = color;
    p.textContent = text;
    el.replaceChildren(p);
  }

  /** Poll /jobs/{id} until status is complete or failed (#276). */
  function pollJobStatus(jobId, resultEl) {
    var pollInterval = 2000; // 2 seconds
    var maxPolls = 90; // 3 minutes max
    var polls = 0;

    function check() {
      polls++;
      if (polls > maxPolls) {
        showMessage(
          resultEl,
          "#856404",
          "Import is still running. Refresh the page later to check results."
        );
        return;
      }
      fetch("/jobs/" + jobId)
        .then(function (resp) {
          return resp.json();
        })
        .then(function (job) {
          if (job.status === "complete") {
            if (job.songs_imported === 0) {
              showMessage(
                resultEl,
                "#856404",
                "Import complete — no songs found. " +
                  "The file may not be a worship slide deck."
              );
            } else {
              showMessage(
                resultEl,
                "green",
                "Import complete — " +
                  job.songs_imported +
                  " song(s) imported."
              );
            }
          } else if (job.status === "failed") {
            showMessage(
              resultEl,
              "#c00",
              "Import failed: " + (job.error_message || "unknown error")
            );
          } else {
            showMessage(resultEl, "#495057", "Importing… processing");
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
    btn.textContent = "Uploading…";
    result.replaceChildren();

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
        showMessage(result, "#495057", "Upload accepted — importing…");
        pollJobStatus(j.job_id, result);
      })
      .catch(function (err) {
        showMessage(result, "#c00", "Upload failed: " + err.message);
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Upload";
      });
  });
})();
