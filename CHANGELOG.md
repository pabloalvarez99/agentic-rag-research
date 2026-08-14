# Changelog

All notable changes to this project will be documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and version tags will follow
semantic versioning once the first release is published.

## [Unreleased]

### Added

- A deterministic plan → retrieve → critique research loop with explicit step budgets,
  terminal statuses, stop reasons, grounded reports, refusals, and a complete typed trace.
- FastAPI `POST /v1/research`, `GET /health`, and a JSON CLI with request-id and transport
  parity.
- A credential-free retriever over 20 packaged Markdown passages.
- An opt-in HTTP adapter for `production-rag`, with a versioned response contract, bounded
  payloads, URL safety checks, and typed configuration/transport failures.
- A 17-case offline golden dataset and deterministic JSON scorecard covering single-hop,
  multi-hop, unanswerable, thin-evidence, and budget-stress behavior.
- Architecture documentation, three ADRs, ship notes, a case study, security guidance, and
  the draft [v0.1.0 release notes](docs/releases/v0.1.0.md).

### Release status

The package metadata currently reports `0.1.0`, but no `v0.1.0` Git tag or GitHub release
is claimed. The release remains an M6 action gated by CI on the exact release commit.

[Unreleased]: https://github.com/pabloalvarez99/agentic-rag-research/commits/main
