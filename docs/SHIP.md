# Ship notes — v0.1.0

**Status: public-ready free path.** A reviewer can clone this repository and run the
bounded research loop through the UI, API, CLI, or evaluation harness without a credential,
provider network call, or billed request. The synchronized 17-case golden set and JSON
scorecard are contract evidence, not an answer-quality claim.

This is the short operational truth. The [README](../README.md) is the hiring-facing tour,
[architecture.md](architecture.md) explains trade-offs, and the
[release notes](releases/v0.1.0.md) state the evidence boundary.

## Try it free

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
trace. Backend failures render a typed page rather than a partial or invented answer.

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
| Golden evaluation and scorecard | **LIVE** | 17 cases across five slices |
| Research UI and typed failures | **LIVE** | UI route/tests and real-server CI smoke |
| Local `search_notes` | **LIVE (optional)** | critic request, tool/trace tests; no provider |

## What CI proves on the release commit

- `ruff check .`, `mypy --strict`, and `pytest -q` on Python 3.12;
- provider variables are empty for the free path;
- the CLI demo, `GET /health`, the HTML home page, and a submitted UI run complete; and
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
- No hosted demo, model-based planner, auth, rate limiting, streaming, multi-tenancy, load
  figure, arbitrary web/write tool, or multi-agent orchestration is shipped.
- The optional HTTP adapter is mock-transport tested; this release does not claim a live
  cross-service measurement.

The next quality boundary is a paired run against production-rag on questions whose
single-pass failures are established mechanically. More agent machinery before that
measurement would increase complexity without producing stronger evidence.
