# Ship notes

**Status: M5 is LIVE on `main`; this is not a release.** The bounded research loop,
deterministic fake retriever, FastAPI route, CLI, request ids, citations, refusal, and full
trace are runnable from a clean clone. The synchronized 17-case golden dataset and
deterministic JSON evaluation scorecard are also merged and runnable on the free path.

This page is the short operational truth. The [README](../README.md) is the hiring-facing
tour, and [architecture.md](architecture.md) explains the trade-offs.

## Try it free — no key, no network

Requires Python 3.12+. Commands below use the Windows venv layout; on macOS or
Linux replace `.venv/Scripts` with `.venv/bin`.

```bash
git clone https://github.com/pabloalvarez99/agentic-rag-research
cd agentic-rag-research
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/pytest -q
.venv/Scripts/python -m agentic_rag.research \
  --question "Why use reciprocal rank fusion?" --retriever fake
```

The CLI writes exactly one JSON object to stdout. Start the API with:

```bash
.venv/Scripts/uvicorn agentic_rag.main:app --port 8010
curl -s http://127.0.0.1:8010/health
```

Then open <http://127.0.0.1:8010/docs> or call `POST /v1/research`.

## What is LIVE

| Capability | State | Evidence |
| --- | --- | --- |
| Plan → retrieve → critique loop | **LIVE** | `agent/graph.py`; happy, refusal, and budget tests |
| Step and per-call evidence budgets | **LIVE** | `ResearchState.record_retrieval`; ADR-0002 |
| Grounded report or explicit refusal | **LIVE** | synthesizer and terminal outcome tests |
| Complete deterministic trace | **LIVE** | six event types ending in `stop` |
| Fake retrieval over committed Markdown | **LIVE** | packaged corpus and corpus tests |
| `POST /v1/research` and CLI | **LIVE** | API/CLI parity and OpenAPI tests |
| Optional production-rag HTTP adapter | **LIVE (opt-in)** | mock-transport tests; requires `PRODUCTION_RAG_URL` at runtime |
| Golden research questions | **LIVE** | 17 cases, five slices, documented schema |
| Evaluation runner and JSON scorecard | **LIVE** | exact expectations plus aggregate steps/citation/status metrics |
| Release artifact / public hosted demo | **PLANNED (M6)** | no tag or deployment claimed |

## What CI must prove

The free-path CI workflow is merged on `main`. Its release gate covers:

- `ruff check .`, `mypy --strict`, and `pytest -q` on Python 3.12;
- provider variables empty for the free-path run;
- a real CLI invocation and `GET /health` smoke check; and
- no network or credential needed by the default `fake` backend.

M6 still requires those checks to be green on the exact release commit; a historical
green run is evidence for that commit only.

## Failure demos worth showing

- Ask an off-corpus question: the run returns `refused` with `no_evidence` and named gaps.
- Give a thin-evidence question one step: it returns `budget_exhausted`, preserves grounded
  partial findings, and names the gaps it could not close.
- Request `retriever=http` without `PRODUCTION_RAG_URL`: API/CLI return the typed
  `capability_missing` error rather than silently substituting the fake.
- Point the HTTP backend at an unavailable service: the transport returns
  `backend_unavailable`; it is never misreported as an evidence-based refusal.

## Non-goals for this milestone

- No claim that lexical fake retrieval measures retrieval, reasoning, or answer quality.
- No hosted-model quality numbers and no billed path by default.
- No arbitrary web, shell, filesystem, write, or sub-agent tools.
- No authentication, rate limiting, multi-tenancy, streaming, or public deployment.
- No LangGraph dependency until branching/checkpointing makes it earn its weight.

## Release gate

M6 can be called shipped only after M5's runner passes all 17 fixed goldens on the exact
release commit, the LIVE table points to merged code, CI is green on that commit, links and
secret scans pass, and a release note states which measurements came from fakes.
