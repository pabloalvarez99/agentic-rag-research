# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-08-14

### Added

- Season lab ledger: [docs/SEASON.md](docs/SEASON.md) (15 invariants, eval plan, pack/tools).
- **Experiment records** (`agentic_rag.experiment`): id, seed, budget, note ids, stop
  reason, pack hash, tool-call counts.
- Control goldens **n = 48** with slices and difficulty predicates; permanent
  `critic-notes-exist-not-success` still refuses.
- Third free-path tool **lexicon** + per-tool `max_calls`; typed stop
  `tool_budget_spent` ([ADR-0006](docs/adr/0006-three-tools-not-a-platform.md)).
- **Experiment packs**: `POST /v1/experiments/pack`, `/pack` UI, directory/zip round-trip.
- Load artifact [docs/assets/load.json](docs/assets/load.json) (50 fake researches, p50/p95).
- Optional `max_tool_calls` on research requests (OpenAPI).

### Changed

- Package version **1.0.0**. CASESTUDY expanded for the lab narrative and 15-min DEMO.

### PLANNED (not in this release)

- Durable multi-instance storage, live web tools, default paid LLM, capacity claims,
  plugin marketplace. See release notes.

## [0.3.0] - 2026-08-14

### Added

- **Payload compare.** `POST /v1/runs/compare` accepts two full run artifacts (not
  server ids) and returns a typed field-level diff (`status`, `stop_reason`,
  `steps_used`, notes, citations, …). Byte-stable empty diff for identical fixtures.
  Rationale: [ADR-0005](docs/adr/0005-compare-on-payloads.md).
- `GET /v1/runs/{id}/run.json` downloads the full finished-run artifact (attachment)
  so a reviewer can keep the payload after a serverless recycle forgets in-memory ids.
- `/compare` UI loads two local `run-*.json` files, shows stop reason / steps / notes /
  citations side by side, and posts the bodies to the compare route.
- Hosted contract smoke: `scripts/hosted_smoke.ps1` (health, done, refuse, SSE first
  event, compare). Default CI stays offline; prefer a local transcript over a flaky
  network job.
- OpenAPI coverage for `/v1/research`, `/v1/research/stream`, `/v1/runs/*`, and compare.
- Golden `critic-notes-exist-not-success` (18th case): grounded notes present but
  off-topic → refuse, not success. Does not weaken the existing 17 free-path cases.
- Multi-hop event-sequence test: critique after retrieve-1 must precede and justify
  retrieve-2.

### Changed

- Free-path golden set is **18/18** control cases (`pass_rate` 1.0, `billed_usd` 0).
- Hosted DEMO script documents download → compare of refused vs done runs.

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

[Unreleased]: https://github.com/pabloalvarez99/agentic-rag-research/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/pabloalvarez99/agentic-rag-research/releases/tag/v1.0.0
[0.3.0]: https://github.com/pabloalvarez99/agentic-rag-research/releases/tag/v0.3.0
[0.2.0]: https://github.com/pabloalvarez99/agentic-rag-research/releases/tag/v0.2.0
[0.1.0]: https://github.com/pabloalvarez99/agentic-rag-research/releases/tag/v0.1.0
