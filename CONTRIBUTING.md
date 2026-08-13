# Contributing

This is a portfolio repository, public so the engineering can be read and run. Bug reports,
correctness fixes, and documentation corrections are welcome. Before proposing a capability,
read [docs/architecture.md](docs/architecture.md): the loop is planned in milestones, and
most of what looks missing is assigned to a later one rather than absent by oversight.

Everything below runs on deterministic local providers. No credential, no billed call, no
signup.

## Prerequisites

- Python 3.12+
- Git

## Hello, free path

```bash
git clone https://github.com/pabloalvarez99/agentic-rag-research
cd agentic-rag-research
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # macOS or Linux: .venv/bin/pip
.venv/Scripts/uvicorn agentic_rag.main:app --port 8010
curl -s http://127.0.0.1:8010/health
```

```json
{"status": "ok", "service": "agentic-rag-research", "version": "0.1.0"}
```

The interactive API document is at <http://127.0.0.1:8010/docs>. Nothing in this path reads
an environment variable, so there is no `.env` to prepare.

## Run the checks

The same three commands CI runs, in the same order:

```bash
ruff check .
mypy --strict
pytest -q
```

CI runs them on Python 3.12 with `OPENAI_API_KEY` set to the empty string, and then starts
the app and calls `/health` with the same empty value. That is deliberate: if a change makes
any path require a credential, CI goes red instead of passing on a secret the workflow never
sets. Keep it that way — a new test must pass with no key, or be marked as an integration
test that does not run by default.

## No secrets, ever

- `.env` is gitignored. `.env.example` is the only committed template and carries variable
  names and no values.
- Do not paste a key, token, or connection string into code, tests, fixtures, commit
  messages, issues, or pull requests. A key that reaches the history stays in the history
  after the file is deleted; rotate it rather than hoping nobody read it.

## What the review looks for

1. **Claims match code.** The README and the architecture document describe what exists at
   the tip. An unimplemented surface is labelled as planned, not written in the present
   tense.
2. **Local-provider runs are not quality results.** The fake backend proves control flow,
   the step budget, the stop rule, the refusal path and the trace. It proves nothing about
   retrieval or answer quality, and a number produced by it is not published as one.
3. **Series #1 is consumed, not copied.** Retrieval, fusion, rerank and citation resolution
   live in [production-rag](https://github.com/pabloalvarez99/production-rag). A fork of
   that stack here would make the comparison against the single-pass baseline meaningless.
4. **Non-obvious trade-offs become records.** A decision with a rejected alternative belongs
   in `docs/adr/` alongside the change, not only in the commit body.
5. **Tests stay offline.** Prefer unit tests with no network. Anything that needs a running
   retrieval service is marked and opt-in.

## Commits and pull requests

Commit subjects use a conventional prefix — `feat:`, `fix:`, `docs:`, `ci:`, `chore:`. Keep
the history readable as a sequence of decisions rather than a list of file touches.

## Reporting a bug

Open an issue with the command you ran, the backend involved (fake unless you opted in), and
what you expected instead. A failing test is the most useful form of the report. Do not
include a credential value — not even a redacted-looking one.
