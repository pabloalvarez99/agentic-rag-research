/**
 * Free-path demo: stream plan → retrieve → critique, then fetch the stored run.
 *
 * No provider, no key. The form still posts to /ui/research when JS is off.
 */
(function () {
  "use strict";

  var form = document.getElementById("research-form");
  if (!form) return;

  var live = document.getElementById("live-run");
  var timeline = document.getElementById("live-timeline");
  var outcome = document.getElementById("live-outcome");
  var statusEl = document.getElementById("live-status");
  var reportEl = document.getElementById("live-report");
  var citationsEl = document.getElementById("live-citations");
  var downloadEl = document.getElementById("live-download");
  var downloadRunEl = document.getElementById("live-download-run");
  var requestIdEl = document.getElementById("live-request-id");
  var errorEl = document.getElementById("live-error");
  var submitBtn = form.querySelector('button[type="submit"]');

  function show(el) {
    if (el) el.hidden = false;
  }
  function hide(el) {
    if (el) el.hidden = true;
  }
  function clear(el) {
    if (el) el.textContent = "";
  }

  function appendEvent(payload) {
    if (!timeline) return;
    var li = document.createElement("li");
    var title = document.createElement("h3");
    var offset =
      typeof payload.offset === "number" ? "#" + payload.offset + " " : "";
    title.textContent =
      offset + String(payload.event || "event").replace(/_/g, " ");
    var pre = document.createElement("pre");
    pre.textContent = JSON.stringify(payload.payload || payload, null, 2);
    var wrap = document.createElement("div");
    wrap.appendChild(title);
    wrap.appendChild(pre);
    var dot = document.createElement("span");
    dot.className = "timeline-dot";
    dot.setAttribute("aria-hidden", "true");
    li.appendChild(dot);
    li.appendChild(wrap);
    timeline.appendChild(li);
  }

  function renderArtifact(run) {
    if (statusEl) {
      statusEl.textContent =
        run.status +
        " · stop: " +
        run.stop_reason +
        " · steps: " +
        run.steps_used +
        "/" +
        run.max_steps;
    }
    if (reportEl) reportEl.textContent = run.report || "";
    if (citationsEl) {
      citationsEl.textContent = "";
      if (run.citations && run.citations.length) {
        var ol = document.createElement("ol");
        ol.className = "citations";
        run.citations.forEach(function (c) {
          var li = document.createElement("li");
          var p = document.createElement("p");
          p.innerHTML =
            '<span class="citation-marker">[' +
            c.marker +
            "]</span> <strong></strong>";
          p.querySelector("strong").textContent = c.source_path || "";
          li.appendChild(p);
          if (c.snippet) {
            var sn = document.createElement("p");
            sn.textContent = c.snippet;
            li.appendChild(sn);
          }
          if (c.chunk_id) {
            var code = document.createElement("code");
            code.textContent = c.chunk_id;
            li.appendChild(code);
          }
          ol.appendChild(li);
        });
        citationsEl.appendChild(ol);
      } else {
        var empty = document.createElement("p");
        empty.className = "empty-copy";
        empty.textContent =
          "No citations were produced. The terminal status and stop event explain why.";
        citationsEl.appendChild(empty);
      }
    }
    if (downloadEl) {
      downloadEl.href = "/v1/runs/" + encodeURIComponent(run.request_id) + "/trace.json";
      downloadEl.hidden = false;
    }
    if (downloadRunEl) {
      downloadRunEl.href = "/v1/runs/" + encodeURIComponent(run.request_id) + "/run.json";
      downloadRunEl.hidden = false;
    }
    if (requestIdEl) requestIdEl.textContent = run.request_id;
    if (outcome) {
      outcome.className = "outcome outcome-" + run.status;
      show(outcome);
    }
  }

  function parseSseChunk(buffer, onEvent) {
    var parts = buffer.split("\n\n");
    var rest = parts.pop() || "";
    parts.forEach(function (block) {
      var name = "message";
      var dataLines = [];
      block.split("\n").forEach(function (line) {
        if (line.indexOf("event:") === 0) name = line.slice(6).trim();
        else if (line.indexOf("data:") === 0) dataLines.push(line.slice(5).trim());
      });
      if (!dataLines.length) return;
      try {
        onEvent(name, JSON.parse(dataLines.join("\n")));
      } catch (err) {
        /* ignore a partial frame; the next chunk may complete it */
      }
    });
    return rest;
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var question = form.question.value;
    var maxSteps = form.max_steps.value;
    var params = new URLSearchParams({
      question: question,
      max_steps: String(maxSteps),
      retriever: "fake",
    });

    show(live);
    hide(outcome);
    hide(errorEl);
    hide(downloadEl);
    hide(downloadRunEl);
    clear(timeline);
    clear(reportEl);
    clear(citationsEl);
    clear(requestIdEl);
    if (statusEl) statusEl.textContent = "streaming…";
    if (submitBtn) submitBtn.disabled = true;

    var buffer = "";
    var finished = false;

    fetch("/v1/research/stream?" + params.toString(), {
      method: "GET",
      headers: { Accept: "text/event-stream" },
    })
      .then(function (response) {
        if (!response.ok) {
          return response.json().then(function (body) {
            throw new Error(
              (body && body.error) || "stream failed with status " + response.status
            );
          });
        }
        if (!response.body || !response.body.getReader) {
          throw new Error("streaming is not available in this browser");
        }
        var reader = response.body.getReader();
        var decoder = new TextDecoder();

        function pump() {
          return reader.read().then(function (result) {
            if (result.done) return;
            buffer += decoder.decode(result.value, { stream: true });
            buffer = parseSseChunk(buffer, function (name, payload) {
              if (name === "trace") appendEvent(payload);
              if (name === "error") {
                finished = true;
                if (errorEl) {
                  errorEl.textContent =
                    (payload && payload.error) || "the stream reported an error";
                  show(errorEl);
                }
              }
              if (name === "done" && payload && payload.request_id) {
                finished = true;
                return fetch("/v1/runs/" + encodeURIComponent(payload.request_id))
                  .then(function (r) {
                    if (!r.ok) throw new Error("could not fetch stored run");
                    return r.json();
                  })
                  .then(renderArtifact);
              }
            });
            if (!finished) return pump();
          });
        }
        return pump();
      })
      .catch(function (err) {
        if (errorEl) {
          errorEl.textContent = err.message || String(err);
          show(errorEl);
        }
      })
      .finally(function () {
        if (submitBtn) submitBtn.disabled = false;
      });
  });
})();

/**
 * Compare page: two downloaded run JSON files → side-by-side + typed API diff.
 * Never resolves a server id; the files are the source of truth after recycle.
 */
(function () {
  "use strict";

  var form = document.getElementById("compare-form");
  if (!form) return;

  var errorEl = document.getElementById("compare-error");
  var summary = document.getElementById("compare-summary");
  var columns = document.getElementById("compare-columns");
  var identicalEl = document.getElementById("compare-identical");
  var idsEl = document.getElementById("compare-ids");
  var diffList = document.getElementById("compare-diff-list");
  var titleEl = document.getElementById("compare-result-title");

  function show(el) {
    if (el) el.hidden = false;
  }
  function hide(el) {
    if (el) el.hidden = true;
  }

  function readFile(input) {
    return new Promise(function (resolve, reject) {
      var file = input && input.files && input.files[0];
      if (!file) {
        reject(new Error("choose a JSON file for both sides"));
        return;
      }
      var reader = new FileReader();
      reader.onload = function () {
        try {
          resolve(JSON.parse(String(reader.result || "")));
        } catch (err) {
          reject(new Error("could not parse " + file.name + " as JSON"));
        }
      };
      reader.onerror = function () {
        reject(new Error("could not read " + file.name));
      };
      reader.readAsText(file);
    });
  }

  function fillSide(prefix, run) {
    var status = document.getElementById(prefix + "-status");
    var stop = document.getElementById(prefix + "-stop");
    var steps = document.getElementById(prefix + "-steps");
    var notesCount = document.getElementById(prefix + "-notes-count");
    var citesCount = document.getElementById(prefix + "-cites-count");
    var notes = document.getElementById(prefix + "-notes");
    var cites = document.getElementById(prefix + "-cites");
    var heading = document.getElementById(prefix + "-heading");
    if (heading) heading.textContent = run.request_id || prefix;
    if (status) status.textContent = run.status || "—";
    if (stop) stop.textContent = run.stop_reason || "—";
    if (steps) {
      steps.textContent =
        String(run.steps_used != null ? run.steps_used : "—") +
        "/" +
        String(run.max_steps != null ? run.max_steps : "—");
    }
    if (notesCount) notesCount.textContent = String((run.notes && run.notes.length) || 0);
    if (citesCount) citesCount.textContent = String((run.citations && run.citations.length) || 0);
    if (notes) notes.textContent = JSON.stringify(run.notes || [], null, 2);
    if (cites) cites.textContent = JSON.stringify(run.citations || [], null, 2);
  }

  function renderDiff(body) {
    if (!diffList) return;
    diffList.textContent = "";
    if (body.identical) {
      var ok = document.createElement("p");
      ok.className = "hint";
      ok.textContent = "No field differences. The payloads match on every compared field.";
      diffList.appendChild(ok);
      return;
    }
    var table = document.createElement("table");
    table.className = "diff-table";
    table.innerHTML =
      "<thead><tr><th>Field</th><th>Left</th><th>Right</th></tr></thead>";
    var tbody = document.createElement("tbody");
    (body.diffs || []).forEach(function (row) {
      var tr = document.createElement("tr");
      var f = document.createElement("td");
      f.textContent = row.field;
      var l = document.createElement("td");
      var lp = document.createElement("pre");
      lp.textContent = JSON.stringify(row.left, null, 2);
      l.appendChild(lp);
      var r = document.createElement("td");
      var rp = document.createElement("pre");
      rp.textContent = JSON.stringify(row.right, null, 2);
      r.appendChild(rp);
      tr.appendChild(f);
      tr.appendChild(l);
      tr.appendChild(r);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    diffList.appendChild(table);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    hide(errorEl);
    hide(summary);
    hide(columns);

    Promise.all([
      readFile(document.getElementById("left-file")),
      readFile(document.getElementById("right-file")),
    ])
      .then(function (pair) {
        var left = pair[0];
        var right = pair[1];
        fillSide("left", left);
        fillSide("right", right);
        show(columns);
        return fetch("/v1/runs/compare", {
          method: "POST",
          headers: { "content-type": "application/json", accept: "application/json" },
          body: JSON.stringify({ left: left, right: right }),
        }).then(function (response) {
          return response.json().then(function (body) {
            if (!response.ok) {
              throw new Error((body && body.error) || "compare failed");
            }
            return body;
          });
        });
      })
      .then(function (body) {
        if (identicalEl) {
          identicalEl.textContent = body.identical ? "identical" : body.diffs.length + " field diffs";
        }
        if (titleEl) {
          titleEl.textContent = body.identical ? "Payloads match" : "Field differences";
        }
        if (idsEl) {
          idsEl.textContent =
            "left=" +
            (body.left_request_id || "?") +
            " · right=" +
            (body.right_request_id || "?");
        }
        renderDiff(body);
        show(summary);
      })
      .catch(function (err) {
        if (errorEl) {
          errorEl.textContent = err.message || String(err);
          show(errorEl);
        }
      });
  });
})();

