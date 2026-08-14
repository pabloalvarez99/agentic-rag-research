# Case study — proving an agent loop before paying for one

<p align="center">
  <a href="https://github.com/pabloalvarez99/production-rag"><img src="https://img.shields.io/badge/P1-production--rag-0ea5e9" alt="P1 production-rag" /></a>
  <a href="https://github.com/pabloalvarez99/agentic-rag-research"><img src="https://img.shields.io/badge/P2-agentic--rag-a78bfa" alt="P2 agentic-rag" /></a>
  <a href="https://github.com/pabloalvarez99/multi-agent-orchestration"><img src="https://img.shields.io/badge/P3-multi--agent-22c55e" alt="P3 multi-agent" /></a>
  <a href="https://github.com/pabloalvarez99/repomind"><img src="https://img.shields.io/badge/P4-repomind-f59e0b" alt="P4 repomind" /></a>
  <a href="https://github.com/pabloalvarez99/ai-platform"><img src="https://img.shields.io/badge/P5-ai--platform-6b7280" alt="P5 ai-platform" /></a>
</p>

## Problem

A single RAG pass can retrieve and answer, but a research question may contain several
sub-questions, miss on its first wording, or need another retrieval after critique. Adding an
"agent" is easy; proving that the extra loop adds value without hiding cost or failure is the
hard part.

The design goal for P2 is therefore narrower than autonomous research: produce an end-to-end
research JSON result with citations, bounded tool use, explicit stop reasons, and a trace a
reviewer can audit — from a clean clone and without an API key.

## Options considered

| Option | Advantage | Cost / risk |
| --- | --- | --- |
| Hosted model and live retrieval from day one | Real model behavior immediately | Paid, flaky, hard to reproduce, inaccessible to reviewers without keys |
| A tutorial-style unbounded agent | Small amount of code | No defensible termination or cost ceiling; failures become timeouts |
| Copy P1 retrieval into P2 | One repository appears self-contained | Duplicates the baseline and invalidates agent-vs-single-pass comparisons |
| Deterministic loop behind protocols | Offline, replayable, tests exact decisions | Proves mechanism only; quality remains unmeasured |

## Decision

Build fake-first, with one read-only `retrieve` tool and the retrieval service behind a second
protocol. Enforce the step budget inside the run state, never retrieve the same sub-question
twice, and decide terminal outcomes through one pure function. Keep HTTP to production-rag
opt-in and fail closed when it was explicitly requested but unavailable.

The three architectural decisions are recorded separately:

- [ADR-0001](adr/0001-fake-first.md): free path first and the boundary of fake evidence.
- [ADR-0002](adr/0002-step-budget.md): termination and honest stop reasons.
- [ADR-0003](adr/0003-tool-boundary.md): one read-only tool and two protocol seams.

## Result at M3

The same loop is reachable as a Python library, `POST /v1/research`, and a machine-readable
CLI. It can finish with grounded findings, explicitly refuse, or return a partial grounded
report when the budget ends. Every run records plan creation, tool calls/results, critique,
synthesis, and stop.

The default backend reads committed Markdown and contacts nothing. The optional HTTP adapter
maps production-rag citations into the same `Passage` contract, so the loop does not change
when the retrieval substrate changes. HTTP failures become typed transport errors at the API
and CLI boundary, not fake refusals.

## Evidence and limitations

The offline suite verifies contracts, state transitions, refusal, budget enforcement, API/CLI
parity, and the HTTP adapter through a mock transport. M5 adds a synchronized 17-case
golden dataset and a deterministic JSON scorecard across five behavior slices.

There is intentionally no quality claim here. Lexical fake retrieval cannot establish that
planning improves retrieval or that the report is useful. M5 measures terminal behavior,
steps, citations, source diversity, and gaps against curated fixture expectations; a quality
claim still requires an HTTP-backed run on a real corpus, a one-pass answer baseline, named
providers, paired results, sample size, and uncertainty. The defensible result is: **the
mechanism is runnable, bounded, inspectable, and its evaluation contract is executable.**

## What the UI proves

The argument above is about mechanism, and mechanism is invisible in a JSON blob nobody
runs. Three committed captures, rebuilt from a live server by
[`scripts/capture_ui.py`](../scripts/capture_ui.py), show it:

- [`ui-done.png`](assets/ui-done.png) — a run that finished. The status, the retrieval
  steps it spent, and every citation marker resolving to a passage that was retrieved.
  The claim "no marker without a passage" is a thing you can read off the page.
- [`ui-trace.png`](assets/ui-trace.png) — the same UI with the trace expanded, on a
  two-hop question whose first sub-question retrieves nothing. `plan_created`, both
  retrieval steps, the `critique` arithmetic that chose to continue, `synthesize`, and
  the terminal `stop`. The plan, not a retry, is what reached the evidence.
- [`ui-budget.png`](assets/ui-budget.png) — the budget ending a run. Status
  `budget_exhausted` with reason `budget_spent`, a partial grounded report, and the terms
  no retrieved passage covered. The step budget lives in the run state, so the ceiling is
  visible in the trace instead of being an implicit property of the loop's condition.

They also re-state the boundary rather than blurring it: the captures are produced on the
deterministic fake retriever with `PRODUCTION_RAG_URL` cleared, the form pins
`retriever=fake`, and the optional P1 HTTP path stays opt-in and fail-closed. They are
evidence of contract, budget, and traceability — **not** of retrieval or answer quality.

Reproducibility is part of the point: the viewport and questions are pinned and the
correlation id is supplied per capture, so a rebuild is byte-identical and
`python scripts/capture_ui.py --verify` fails on drift rather than quietly publishing a
different run.

## What I would test next

1. Add a one-pass answer baseline over the same fixed goldens.
2. Publish per-case paired deltas before aggregates.
3. Exercise the HTTP adapter against P1's free stack, including refusal and dependency-down.
4. Add wall-clock and spend ceilings only when a hosted path creates those costs.
5. Revisit a graph framework only when checkpoint/resume or parallel fan-out is required.

