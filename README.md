# agentic-rag-research

An agentic RAG research agent: a bounded **plan → retrieve → critique** loop over a
retrieval service, built so the whole path runs on deterministic local providers.
No credential, no billed call, no signup.

Portfolio series #2. Series #1 is [production-rag](../production-rag), which builds the
retrieval substrate this agent reasons over — hybrid dense plus sparse retrieval fused
with reciprocal rank fusion, cross-encoder reranking, answers whose citation markers
resolve to real chunks, and refusal as a first-class outcome. This repository does not
re-litigate those decisions; it inherits them and asks the next question: what does an
agent add over a single retrieval pass, and how do you tell?

## Status: scaffold

`GET /health` is the only route that exists. The agent loop is described in
[docs/architecture.md](docs/architecture.md) and is **not implemented**. Nothing here
reads an API key, and no code path contacts a provider.

## Hello, free path (no keys)

Requires Python 3.12+.

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # macOS or Linux: .venv/bin/pip
.venv/Scripts/pytest
.venv/Scripts/uvicorn agentic_rag.main:app --port 8010
curl -s http://127.0.0.1:8010/health
```

```json
{"status": "ok", "service": "agentic-rag-research", "version": "0.1.0"}
```

The interactive API document is at <http://127.0.0.1:8010/docs>.

## Two rules this project keeps from series #1

- **Evidence or refusal.** A step that cannot cite does not answer. An agent that
  paraphrases its own plan back as a finding is worse than one that stops.
- **Free by default.** Deterministic local providers are the default, so every test and
  every demo runs in CI and on a laptop with no credential. A hosted provider is an
  opt-in override; `.env.example` carries the variable name and no value.

## Layout

| Path | What lives there |
| --- | --- |
| `src/agentic_rag/` | The package. Today: the app factory and the liveness probe. |
| `tests/` | Offline tests. No network, no credentials. |
| `docs/architecture.md` | The planned loop, its tool boundaries, and the milestones. |
| `.env.example` | Variable names for a future opt-in paid path. Never values. |

## License

MIT — see [LICENSE](LICENSE).
