# Ship notes — v0.1.0

**Status: public-ready free path.** A reviewer can clone this repository and run the
bounded research loop through the UI, API, CLI, or evaluation harness without a credential,
provider network call, or billed request. The synchronized 18-case golden set and JSON
scorecard are contract evidence, not an answer-quality claim.

This is the short operational truth. The [README](../README.md) is the hiring-facing tour,
[architecture.md](architecture.md) explains trade-offs, and the
[release notes](releases/v0.1.0.md) state the evidence boundary.

## Try it free, hosted

<https://pax-agentic-rag.vercel.app> — the same page, deployed on Vercel with no
configuration to supply. Submit a question and read the report, citations, terminal
status, steps used, request id, and trace.

The deployment sets **no `PRODUCTION_RAG_URL`**, so every hosted run uses the fixture
retriever: a deterministic in-process backend over the committed Markdown corpus. It is a
demonstration of the agent's contract — planning, budget accounting, citation resolution,
refusal, trace — and is **not evidence about retrieval or answer quality**. Asking for
`retriever: "http"` there returns `capability_missing` rather than silently falling back.

Vercel runs it as a serverless function, so the first request after an idle period pays a
cold start and the counters `GET /metrics` reports are per-instance and reset with it.
They are useful as a shape check, not as a traffic record.

## Try it free, locally

Requires Python 3.12+. On macOS/Linux replace `.venv/Scripts` with `.venv/bin`.

```bash
git clone https://github.com/pabloalvarez99/agentic-rag-research
cd agentic-rag-research
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/pytest -q
.venv/Scripts/uvicorn agentic_rag.main:app --port 8010
```

Open <http://127.0.0.1:8010/>. The form is pinned to the fake retriever. Its result shows
the report, resolved citations, terminal status, retrieval steps used, request id, and full
trace, and offers that trace as a JSON download. Backend failures render a typed page
rather than a partial or invented answer.

Two operational surfaces sit next to the demo, and neither says anything about answer
quality. `POST /v1/research/trace` takes the same body as `POST /v1/research` and answers
with only that run's trace, as an attachment — the export is a projection of the existing
response, not a second contract, and there is no stored "last run" for two callers to race
for. `GET /metrics` is the Prometheus text format: `process_up`, `requests_total` by
method/route/status, `research_total` by terminal status, and `research_steps_used_total`.
The route label is restricted to routes this service declares, so an unknown path cannot
grow the metric, and no question text or correlation id is ever a label.

What the three documented outcomes look like, captured from a running server and
committed so a reviewer can see them without starting one. Deterministic fake retriever:
a contract demo, not an answer-quality claim.

| Capture | Outcome |
| --- | --- |
| [`ui-done.png`](assets/ui-done.png) | `done` — report, five resolved citations, steps used, request id |
| [`ui-trace.png`](assets/ui-trace.png) | `done` after a missed first hop, trace expanded through `stop` |
| [`ui-budget.png`](assets/ui-budget.png) | `budget_exhausted` — partial grounded findings, uncovered terms, `budget_spent` |

Rebuild: `pip install -e ".[docs]"`, `playwright install chromium`,
`python scripts/capture_ui.py`. `--verify` compares SHA-256 digests against the committed
files instead of overwriting them.

The CLI remains a script-friendly path:

```bash
.venv/Scripts/python -m agentic_rag.research \
  --question "Why use reciprocal rank fusion?" --retriever fake
```

## What is LIVE

| Capability | State | Evidence |
| --- | --- | --- |
| Plan → retrieve → critique loop | **LIVE** | loop tests; ADR-0002 |
| Retrieval budget and no-repeat bound | **LIVE** | `ResearchState`; budget/golden tests |
| Grounded report or explicit refusal | **LIVE** | synthesizer and terminal-outcome tests |
| Complete deterministic trace | **LIVE** | six event types ending in `stop` |
| Fake retrieval over committed Markdown | **LIVE** | packaged corpus and corpus tests |
| `POST /v1/research`, CLI, health | **LIVE** | API/CLI parity and OpenAPI tests |
| Optional production-rag HTTP adapter | **LIVE (opt-in)** | mock transport; requires `PRODUCTION_RAG_URL` |
| Golden evaluation and scorecard | **LIVE** | 18 cases; critic-can-lose included |
| Payload compare (not server ids) | **LIVE** | `POST /v1/runs/compare` + `/compare` UI; ADR-0005 |
| Hosted smoke script | **LIVE** | `scripts/hosted_smoke.ps1` (network opt-in) |
| Research UI and typed failures | **LIVE** | UI route/tests and real-server CI smoke |
| Local `search_notes` | **LIVE (optional)** | critic request, tool/trace tests; no provider |
| Committed UI captures | **LIVE** | three PNGs in `docs/assets`; `scripts/capture_ui.py`, byte-identical on re-run |
| Trace export, API and browser | **LIVE** | `POST /v1/research/trace` and the result page's download button; the file is the same events as `trace` in the research response |
| `GET /metrics` | **LIVE** | Prometheus text: `process_up`, `requests_total{method,path,status}`, `research_total{status}`, `research_steps_used_total` |
| Hosted free-path demo | **LIVE** | <https://pax-agentic-rag.vercel.app>; `main.py` + `vercel.json`; fixture retriever only |

## What CI proves on the release commit

- `ruff check .`, `mypy --strict`, and `pytest -q` on Python 3.12;
- provider variables are empty for the free path;
- the CLI demo, `GET /health`, the HTML home page, and a submitted UI run complete;
- both trace exports return a timeline ending in `stop`, and `GET /metrics` reports
  `process_up 1` and a `done` run it counted; and
- the default fake backend needs no network or credential.

## Failure demos worth showing

- Off-corpus question → `refused` with `no_evidence` and named gaps.
- Thin evidence with one retrieval step → `budget_exhausted`, grounded partial findings,
  and the gaps it did not close.
- `retriever=http` without configuration → typed `capability_missing`, never fake fallback.
- Unavailable configured backend → typed `backend_unavailable`, never an evidence refusal.

## Honest boundary

- Lexical fake retrieval measures control-flow conformance, not retrieval, reasoning, or
  answer quality. There is no paired agent-uplift claim against a hosted baseline.
- The hosted demo is the free path and nothing more: fixture retrieval, no credential, no
  production-rag instance behind it. It is not a production deployment and carries no
  traffic.
- No model-based planner, auth, rate limiting, streaming, multi-tenancy, load figure,
  arbitrary web/write tool, or multi-agent orchestration is shipped.
- The optional HTTP adapter is mock-transport tested; this release does not claim a live
  cross-service measurement.

The next quality boundary is a paired run against production-rag on questions whose
single-pass failures are established mechanically. More agent machinery before that
measurement would increase complexity without producing stronger evidence.
