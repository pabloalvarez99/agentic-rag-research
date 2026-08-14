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
