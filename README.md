# agentic-rag-research

An agentic RAG research agent: a bounded **plan → retrieve → critique** loop over a
retrieval service, built so the whole path runs on deterministic local providers.
No credential, no billed call, no signup.

Portfolio series #2. Series #1 is
[production-rag](https://github.com/pabloalvarez99/production-rag), which builds the
retrieval substrate this agent reasons over — hybrid dense plus sparse retrieval fused
with reciprocal rank fusion, cross-encoder reranking, answers whose citation markers
resolve to real chunks, and refusal as a first-class outcome. This repository does not
re-litigate those decisions and does not reimplement that retrieval stack; it consumes
it and asks the next question: **what does an agent add over a single retrieval pass,
and how do you tell?**

## Status: M2 — the loop runs

`GET /health` is still the only route, but the loop underneath it is complete as a
library: `plan → retrieve → critique`, bounded by a step budget, ending in a report
whose every marker resolves to a passage that was actually retrieved — or in an explicit
refusal. `POST /v1/research` and the CLI are **not implemented** and are the next
milestone ([docs/architecture.md](docs/architecture.md)). Nothing here reads an API key,
and the default path contacts nothing.

```python
from agentic_rag.agent import run_research

state = run_research("What does hybrid retrieval buy over dense retrieval alone?")

state.status         # <ResearchStatus.DONE: 'done'>
state.stop_reason    # 'evidence_sufficient'
state.steps_taken    # 1 of a budget of 4
state.evidence_ids   # ('hybrid-retrieval-1', 'reranking-1')
[c.marker for c in state.citations]     # [1, 2]
[e.event for e in state.trace]
# ['plan_created', 'tool_call', 'tool_result', 'critique', 'synthesize', 'stop']
```

```text
Question: What does hybrid retrieval buy over dense retrieval alone?

Findings, each one a retrieved passage:

- Hybrid retrieval runs a dense vector search and a sparse keyword search over the
  same corpus and fuses the two rankings with reciprocal rank fusion, so a query that
  only one of them understands still returns evidence. [1]
- A cross-encoder reranker reads the query and a candidate passage together and
  reorders the shortlist. [2]
```

Ask it something the corpus cannot answer and it says so, naming what it looked for:

```python
state = run_research("What were the quarterly revenues in Patagonia?", max_steps=3)

state.status                          # <ResearchStatus.REFUSED: 'refused'>
state.stop_reason                     # 'no_evidence'
state.citations                       # []
[gap.detail for gap in state.gaps]
# ["no passage was retrieved for the sub-question 'What were the quarterly revenues
#   in Patagonia?'", ..., 'no retrieved passage mentions: patagonia, quarterly, revenues']
```

Set `PRODUCTION_RAG_URL` to aim the same tool at a running production-rag instance
(`POST /v1/query`, free providers pinned on both sides). Unset — the default, and what
every test runs on — retrieval is in-process.

## The loop

```
question
   │
   ├─► plan ─────────► sub-questions, ordered, one retrieval each
   │      ▲                       │
   │      │                       ▼
   │      │              retrieve ──► passages + source ids  ──┐
   │      │                       (one sub-question per call)  │
   │      │                                                    ▼
   │      │                                              critique
   │      │                                                    │
   │      │  gap named, steps left                             │
   │      └────────────────────────────────────────────────────┤
   │                                                           │
   │                          evidence sufficient ─────────────┼──► answer + citations
   │                                                           │
   │                          budget spent, still thin ────────┴──► refusal + reason
   ▼
trace: every step, its tool, its evidence, its cost — written whichever way the loop ends
```

Only `critique` can end the loop, so there is one place to audit when a run ends
wrongly. The bound is the point: an agent without a step budget and a stop rule is a
way to spend money on tokens until something times out.

Every run reaches one of three terminal states, and the status field is not allowed to
flatter the run:

| Status | When | What the report contains |
| --- | --- | --- |
| `done` | The evidence was sufficient. | Findings, each a cited passage. |
| `budget_exhausted` | Evidence was gathered, never became sufficient, and the steps ran out. | The grounded findings **and** the gaps it never closed. |
| `refused` | Nothing was retrieved, or what was is too thin to answer from. | The refusal, its named gaps, and any passages gathered — still cited. |

Two independent bounds guarantee termination: the step budget, enforced inside the
state rather than by the loop's condition, and the rule that no sub-question is ever
retrieved for twice. The planner, the critic's score and the synthesiser are
deterministic and call no provider — a run is byte-identical when repeated, traces
included, which is what lets a test assert on one. Tool boundaries, the scoring rule,
the trace's event set, and why there is no graph library yet are in
[docs/architecture.md](docs/architecture.md).

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

## How it will use series #1

The loop depends on one interface with a single `search` method, and cannot tell its
two implementations apart:

| Backend | What it is | When |
| --- | --- | --- |
| Fake | In-process fixture over a small committed corpus, deterministic per sub-question | The default — every test, every CI run, every laptop demo |
| HTTP | Client for a running production-rag instance, `POST /v1/query` | Opt-in, when a real corpus and real retrieval quality matter |

The HTTP backend reads the `citations` array — each entry is already a passage with a
chunk id and a source path — rather than the inner service's generated answer, because
an agent that paraphrases another model's answer is not retrieving anything. A
`refused: true` response is information, not a failure: it means one sub-question found
no support, which is a gap `critique` can name.

**P1 is consumed, not copied.** No retrieval, fusion, rerank or citation-resolution code
is reimplemented here — a fork of that stack would make the comparison against the
single-pass baseline meaningless.

## Two rules this project keeps from series #1

- **Evidence or refusal.** A step that cannot cite does not answer. An agent that
  paraphrases its own plan back as a finding is worse than one that stops.
- **Free by default.** Deterministic local providers are the default, so every test and
  every demo runs in CI and on a laptop with no credential. A hosted provider is an
  opt-in override; `.env.example` carries the variable name and no value. The reasoning
  and its rejected alternatives: [ADR-0001](docs/adr/0001-fake-first.md).

The fake backend proves control flow, budget accounting, the stop rule, the refusal path
and the trace. It proves nothing about retrieval or answer quality, and this repository
will not publish a quality number produced by it.

## Layout

| Path | What lives there |
| --- | --- |
| `src/agentic_rag/` | The package. Today: the app factory, the liveness probe, and the tokeniser the fixture and the critic share. |
| `src/agentic_rag/tools/` | The tool protocol, the `retrieve` tool, and its two backends. |
| `src/agentic_rag/agent/` | The loop: `state` (budget, evidence, trace), `planner`, `critic`, `synthesizer`, `graph`. |
| `tests/` | Offline tests. No network, no credentials. |
| `docs/architecture.md` | The planned loop, its tool boundaries, the retrieval seam, and the milestones. |
| `docs/adr/` | Decision records. [ADR-0001](docs/adr/0001-fake-first.md): why the free path is the default. |
| `.env.example` | Variable names for the opt-in paths: a running retrieval service, a hosted provider. Never values. |

## License

MIT — see [LICENSE](LICENSE).
