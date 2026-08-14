# Portfolio series

> Production-shaped AI systems: free-path demos, real architecture, measurable behavior,
> honest scope.

This repository is project 2 in a five-system maturity ladder. Each project is independently
runnable; later projects consume earlier ones through optional boundaries rather than copying
their implementation.

| Project | Question it answers | State |
| --- | --- | --- |
| [P1 — production-rag](https://github.com/pabloalvarez99/production-rag) | Can retrieval answer with grounded citations, refuse unsupported questions, and be evaluated offline? | **v0.1.0 LIVE** |
| **P2 — agentic-rag-research** | What does a bounded plan/retrieve/critique loop add over one retrieval pass, and can every decision be audited? | **M5 LIVE; M6 planned** |
| P3 — multi-agent-orchestration | How should specialists hand work off under budgets and isolation? | **PLANNED** |
| [P4 — RepoMind](https://github.com/pabloalvarez99/repomind) | Can a codebase be queried with AST-aware chunks and `path:line` evidence? | **M3 LIVE; CLI/evals planned** |
| P5 — AI Platform | How are the services operated behind auth, rate limits, routing, and aggregate health? | **PLANNED** |

## The P1 → P2 boundary

P1 owns ingestion, dense/sparse retrieval, RRF, reranking, grounding, and single-pass
answers. P2 owns planning, tool calls, critique, budgets, stop reasons, and traces.

```text
P2 research loop ── RetrieveTool ──► FakeRetrievalBackend (default, offline)
                                  └─► HttpRetrievalBackend ──► P1 POST /v1/query
```

P2 consumes P1's citation passages and ignores P1's generated answer. Copying retrieval
logic into P2 would change the baseline and make the agent-versus-single-pass comparison
meaningless.

## What P2 contributes to the series

- A step budget enforced by state, plus a no-repeat progress bound.
- A small, read-only tool surface that limits prompt-injection blast radius.
- Explicit `done`, `refused`, and `budget_exhausted` outcomes.
- A deterministic trace that makes every tool call and stop decision inspectable.
- Paired golden questions designed to expose where additional steps help — or do not.

P3 does not begin by smuggling multiple roles into this repository. It starts only after
P2's single-agent contracts, failure handling, and evaluation are stable enough to become
handoff policy.

