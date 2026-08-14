# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-08-14

### Added

- A typed note store. `Note` is `{id, claim, source, context?, citation?}`: the claim is
  the retrieved chunk verbatim, `context` carries heading ancestry when the backend
  supplies it, `citation` is the chunk id backing the claim, and `None` means nothing
  does. The state mints positional ids, refuses duplicates, and traces every write as a
  `note_added` event. Rationale: [ADR-0004](docs/adr/0004-notes-are-a-store.md).
- `search_notes` ranks the run's own note store rather than the raw passage buffer. It
  still cannot retrieve, generate, contact a provider, or spend a retrieval step.
- Bounded in-process run store. Finished runs are kept under their correlation id
  (default capacity 32, oldest evicted). `GET /v1/runs/{id}` returns report, citations,
  notes, steps used, stop reason, and full trace. `GET /v1/runs/{id}/trace.json` is the
  download contract the UI links to.
- `GET /v1/research/stream` — SSE of `trace` events (stable `offset`, no wall clock),
  then exactly one `done` or `error`. Terminal statuses stay
  `done | refused | budget_exhausted | degraded`.
- Live step UI: with JavaScript on, the form streams plan → retrieve → critique, then
  loads the stored artifact. Download hits `GET /v1/runs/{id}/trace.json`.
- Control scorecard fields: `stop_reason_counts`, `citation_present_rate`,
  `refused_unanswerable` / `refused_unanswerable_rate`. Never quality, never "beats GPT".
- Hosted free-path demo and 10-minute DEMO script in [CASESTUDY.md](docs/CASESTUDY.md).

### Changed

- The stop rule scores `question terms covered by grounded claims + grounded, on-topic
  notes` instead of `passage count + covered terms`. Volume alone no longer clears the
  threshold. The 17 goldens pass unchanged (`pass_rate` 1.0, `billed_usd` 0).
- Trace events carry a positional `offset` so two free-path runs of the same question
  remain byte-comparable.

## [0.1.0] - 2026-08-13

### Added

- A deterministic plan → retrieve → critique → synthesize loop with retrieval budgets,
  terminal statuses, stop reasons, grounded citations, refusal, and a complete trace.
- A typed retrieve tool over 20 packaged Markdown passages, plus an opt-in HTTP adapter
  for production-rag with bounded contracts, URL safety, and typed failures.
- `POST /v1/research`, `GET /health`, and a JSON CLI sharing one `ResearchService` and
  request-id policy.
- A 17-case offline golden dataset and deterministic JSON scorecard covering single-hop,
  multi-hop, unanswerable, thin-evidence, and budget-stress behavior.
- A server-rendered research UI at `/` showing report, citations, status, retrieval steps,
  request id, and an expandable trace timeline.
- A deterministic `search_notes` tool requested by the critic to inspect evidence already
  gathered; it never retrieves, generates, or contacts a provider.
- Architecture documentation, three ADRs, ship notes, a case study, security guidance,
  typed JSON/HTML failures, and CI free-path smokes.

### Security

- The default retriever, planner, critic, synthesizer, notes tool, UI, and evaluation path
  require no API key and make no provider call.
- The optional HTTP retriever must be selected explicitly and never silently substitutes
  fake evidence after a real backend was requested.

### Known limitations

- Fake-provider results validate determinism, contracts, budgets, traces, and refusal;
  they do not establish hosted retrieval, answer quality, or agent uplift.
- There is no hosted demo, streaming, authentication, rate limiting, model-based planning,
  arbitrary web/write tool, or multi-agent orchestration in this release.

[Unreleased]: https://github.com/pabloalvarez99/agentic-rag-research/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/pabloalvarez99/agentic-rag-research/releases/tag/v0.2.0
[0.1.0]: https://github.com/pabloalvarez99/agentic-rag-research/releases/tag/v0.1.0
