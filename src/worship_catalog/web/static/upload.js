/**
 * Upload form handler — reads CSRF cookie and submits via fetch with the token header.
 * After a successful upload, polls the job status endpoint until complete (#276).
 * This must be an external file (not inline) to comply with CSP script-src 'self'.
 *
 * All server-provided strings are rendered with textContent — never concatenated
 * into innerHTML — so crafted values cannot inject markup (DOM-XSS defence, #401).
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

  /**
   * Render the success result: a heading with count, optional metadata block,
   * and a numbered song list.  All values go through textContent — no innerHTML.
   */
  function showImportSuccess(el, job) {
    var frag = document.createDocumentFragment();

    var heading = document.createElement("p");
    heading.style.color = "green";
    heading.style.fontWeight = "600";
    heading.style.marginBottom = "0.5rem";
    heading.textContent =
      "Import complete — " + job.songs_imported + " song(s) imported.";
    frag.appendChild(heading);

    // Metadata rows (only show present values)
    var metaRows = [
      ["Date", job.service_date],
      ["Service", job.service_name],
      ["Song Leader", job.song_leader],
      ["Preacher", job.preacher],
      ["Sermon", job.sermon_title],
    ];
    var hasAnyMeta = metaRows.some(function (r) { return r[1]; });
    if (hasAnyMeta) {
      var metaTable = document.createElement("table");
      metaTable.style.cssText =
        "border-collapse:collapse;font-size:0.85rem;margin-bottom:0.75rem;";
      metaRows.forEach(function (row) {
        if (!row[1]) return;
        var tr = document.createElement("tr");
        var th = document.createElement("th");
        th.style.cssText =
          "text-align:left;padding:1px 0.75rem 1px 0;color:#6c757d;font-weight:600;white-space:nowrap;";
        th.textContent = row[0];
        var td = document.createElement("td");
        td.style.cssText = "padding:1px 0;";
        td.textContent = row[1];
        tr.appendChild(th);
        tr.appendChild(td);
        metaTable.appendChild(tr);
      });
      frag.appendChild(metaTable);
    }

    // Song list
    if (job.songs_json) {
      var songs;
      try { songs = JSON.parse(job.songs_json); } catch (e) { songs = []; }
      if (songs.length > 0) {
        var label = document.createElement("p");
        label.style.cssText =
          "font-size:0.85rem;font-weight:600;color:#495057;margin:0 0 0.25rem;";
        label.textContent = "Songs:";
        frag.appendChild(label);
        var ol = document.createElement("ol");
        ol.style.cssText =
          "margin:0;padding-left:1.5rem;font-size:0.85rem;color:#212529;";
        songs.forEach(function (title) {
          var li = document.createElement("li");
          li.textContent = title;
          ol.appendChild(li);
        });
        frag.appendChild(ol);
      }
    }

    el.replaceChildren(frag);
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
              showImportSuccess(resultEl, job);
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
