# ADR-0006 — Three tools is still not an agent platform

- **Status:** accepted
- **Date:** 2026-08-14
- **Scope:** tool surface size for v1.0, per-tool budgets, and what this repo refuses to claim

## Context

v0.3 shipped two loop-facing tools (`retrieve`, `search_notes`) plus plan/critique/synthesize as pure functions. The season plan adds a third free-path tool: fixture **lexicon/lookup**. That is enough surface for a hiring manager to ask whether this is now an "agent platform."

An agent platform usually means: a plugin registry, multi-tenant isolation, arbitrary tool sandboxes, a marketplace of skills, live web tools, and a model that chooses among them with open-ended side effects. This repository has none of those. Growing from one tool to three without a ceiling invites the next PR to add a browser, a shell, and a calendar "because the agent needs it."

## Decision

1. **v1 free path has exactly three tools:** `retrieve`, `search_notes`, and `lexicon`. Planner, critic, and synthesizer remain pure functions, not tools ([ADR-0003](0003-tool-boundary.md)).
2. **Every tool has `max_calls` in run state.** Exhaustion produces a typed stop (`tool_budget_spent`), never a hang. The global step budget remains for retrieval accounting.
3. **Lexicon is fixture-only.** No network, no synonym API, no OpenAI embeddings. It lifts definitional text from the committed corpus.
4. **This is not a platform claim.** README, CASESTUDY, and release notes must not describe a plugin system, multi-tenant tool registry, or live-web research agent.

## Consequences

- Goldens include a `tool_budget` slice that proves typed exhaustion.
- OpenAPI documents optional `max_tool_calls` on research requests.
- Adding a fourth tool requires a new ADR and a season-doc update, not a quiet PR.

## Alternatives rejected

| Option | Why not |
| --- | --- |
| Unbounded tool list behind a registry | Platform product; out of portfolio scope |
| Live web search tool | Breaks free-path default and honesty labels |
| LLM-chosen tool routes without budgets | Hang and bill risk; untestable free path |
