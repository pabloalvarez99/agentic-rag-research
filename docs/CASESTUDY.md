# Case study — proving an agent loop before paying for one

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

## What I would test next

1. Add a one-pass answer baseline over the same fixed goldens.
2. Publish per-case paired deltas before aggregates.
3. Exercise the HTTP adapter against P1's free stack, including refusal and dependency-down.
4. Add wall-clock and spend ceilings only when a hosted path creates those costs.
5. Revisit a graph framework only when checkpoint/resume or parallel fan-out is required.

