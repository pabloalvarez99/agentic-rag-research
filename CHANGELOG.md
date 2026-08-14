# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/pabloalvarez99/agentic-rag-research/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/pabloalvarez99/agentic-rag-research/releases/tag/v0.1.0
