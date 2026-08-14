# Workstream A1 — the runtime surface: `POST /v1/research` and the CLI

Lane: `feat/p2-runtime-surface`. Branched from `origin/main` at
`0b86e962f2f8fdee7b2b40e2b109e0320a1f8c19`, which is the SHA the dispatch recorded.

This report is the lane's reasoning record. It is not an ADR and does not restate
`docs/architecture.md`; it says what the transport contract is, which alternatives were
rejected, and what a reviewer should distrust.

## What this milestone adds, and what it must not touch

The loop already runs as a library: `run_research()` plans, retrieves under a step
budget, critiques, synthesises a report whose markers resolve to retrieved passages, and
records a trace whichever way it ends. What is missing is the way in.

This lane adds exactly that: an HTTP route, a CLI, and the one application service they
both call. It adds **no** reasoning. Every decision about what a run does — how it
plans, when it stops, what it refuses — stays where it already lives, in
`agentic_rag.agent`. The retrieval implementations are untouched.

The consequence worth stating up front: if this lane had reimplemented any part of the
run, there would be two answers to "what does this agent do" and the tests would only
cover one of them. The service is an adapter, and the tests below check that it stayed
one.

## The transport contract

### Request

`POST /v1/research`, `application/json`.

| Field | Type | Bound | Default |
| --- | --- | --- | --- |
| `question` | string | trimmed, 1–8000 characters | required |
| `max_steps` | integer | 1–20 | `4` (`DEFAULT_MAX_STEPS`) |
| `top_k` | integer | 1–50 | `5` (`DEFAULT_TOP_K`) |
| `retriever` | `"fake"` \| `"http"` | closed set | `"fake"` |

Three properties of that table are load-bearing:

- **Unknown fields are rejected**, not ignored. A misspelled `max_step` that silently
  falls back to the default produces a run that looks fine and answers under a budget
  nobody asked for. This mirrors `RetrieveRequest`, which already forbids extras.
- **The bounds are the domain's bounds, not new ones.** `max_steps` is bounded by
  `ResearchState`, `top_k` by `RetrieveRequest`. The API restates them so a bad request
  fails at the edge with a readable message instead of deep inside a run — and a test
  asserts the two sets of numbers are equal, so the restatement cannot drift.
- **`retriever` is explicit and defaults to `fake`.** The free path is the default, and
  selecting `http` is a decision the caller makes in the request rather than one the
  server makes from the environment behind the caller's back.

### Response

`200 OK` carries exactly the six fields the canonical sketch names:

```json
{"status": "done", "report": "...", "citations": [], "steps_used": 1, "trace": [],
 "request_id": "..."}
```

`status` is `ResearchStatus`, `citations` is the shared citation object, `trace` is the
run's `TraceEvent` list. All three are the canonical models re-exported, not
transport-local copies — a second copy is a second place for the citation shape to
change.

`stop_reason` is deliberately **not** a top-level field: the sketch in the master plan
names six fields, and the reason is already in the terminal `stop` event of the trace
together with the status, the steps used and the budget. Adding a seventh field would be
a contract change made by a lane that was told not to make one.

### Errors

Every failure — validation, configuration, backend, and the unexpected — is the shared
error object and nothing else:

```json
{"error": "human sentence", "error_type": "stable_slug", "request_id": "..."}
```

| Slug | HTTP | Raised when |
| --- | --- | --- |
| `validation_error` | 422 | The body is malformed, out of bounds, or carries unknown fields. |
| `capability_missing` | 503 | `retriever: "http"` was selected and no retrieval service is configured. |
| `backend_unavailable` | 503 | The selected backend was reachable in configuration but failed the call. |
| `internal_error` | 500 | A defect in this service. Never used for a provider failure. |
| `not_found` / `method_not_allowed` / `http_error` | 4xx | Routing errors, so an unknown path answers in the same shape as a known one. |

The slugs come from the portfolio failure taxonomy rather than from this lane's
imagination, so an operator reading a log from a different project in the series reads
the same words.

Four rules the envelope enforces, each one a way an error message leaks:

1. **No traceback, ever.** An unexpected exception is logged server-side with its stack
   and answered with one sentence. A stack trace in a response body is a map of the
   installed dependency tree.
2. **No echoed input.** Validation messages are built from the field location and the
   validator's message. The offending *value* is never quoted back — that is the field
   most likely to hold something the caller should not see repeated, and the one most
   likely to be enormous.
3. **No raw provider payload.** A failing backend produces `backend_unavailable` with
   the call that failed, not the body the backend returned.
4. **`capability_missing` names the variable, never a value.** "Set `PRODUCTION_RAG_URL`"
   is a configuration instruction. Printing what it is currently set to is a credential
   leak whenever the URL carries one.

The distinction between `capability_missing` and `backend_unavailable` is the one an
operator acts on: the first means this deployment was never configured to serve what was
asked and retrying changes nothing; the second means it was configured and the call
failed. Collapsing them into one 503 would delete the only signal that separates "fix
the deployment" from "look at the other service".

`capability_missing` returning 503 rather than 501 is a judgement call: the request is
valid and the deployment is what cannot serve it, which is a service-availability
statement rather than a protocol one. 501 was considered and rejected because it is
conventionally read as "this method is not implemented anywhere", which would be untrue
of a deployment that has the variable set.

### Correlation

`X-Request-ID` is read from the request, validated, and echoed on the response — header
and body, always the same value.

- A caller value matching `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}` is kept, so a caller that
  already has a correlation id keeps it across the hop.
- Anything else — whitespace, control characters, angle brackets, 500 characters of
  padding — is **replaced**, not rejected. A 400 on a header is a hostile answer to a
  request whose body is perfectly good, and echoing the value unmodified is how a log
  file gets a forged line in it.
- Absent, one is minted (UUID4).

The id is per request, held in the request scope, and never in a module-level variable.
That is what makes the concurrency test meaningful rather than decorative: two requests
in flight cannot see each other's id because there is no place for a shared one to live.

### `/health`

Unchanged, and deliberately: liveness only, no dependency state. A liveness probe that
fails because a downstream is down makes an orchestrator restart a healthy process,
which does not fix the downstream.

## The CLI

```
python -m agentic_rag.research --question "..." [--max-steps N] [--top-k N]
                               [--retriever fake|http] [--quiet]
```

**One JSON object, on stdout, always.** Success prints the same six-field envelope the
HTTP route returns. A typed failure prints the same error envelope the HTTP route
returns. Nothing else is ever written to stdout, so `... | jq .status` works without a
filter and the "final stdout line is JSON" contract holds by construction rather than by
convention. The human-readable one-line summary goes to stderr, and can be silenced with
`--quiet`.

That summary carries the status, the steps used, the citation count, the backend and the
request id — and **not** the question. A CLI that echoes the prompt into the terminal
log is the same mistake as a service that logs prompts by default.

JSON is emitted with `ensure_ascii=True`. The output is then pure ASCII and encodes on
any console, which matters on Windows where stdout is not UTF-8 by default; a non-ASCII
question round-trips exactly through `json.loads`.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The run finished `done`. |
| `1` | The run finished without a grounded answer: `refused`, `budget_exhausted`, `degraded`. |
| `2` | Usage error — unknown flag, missing `--question`, non-integer bound. |
| `3` | `capability_missing`. |
| `4` | `backend_unavailable`. |
| `5` | `internal_error`. |

A refusal exits non-zero because the question a script asks is "did I get a grounded
answer?", and the answer is no. The status is still in the JSON for anything that needs
the distinction, and the refusal's report and gaps are printed in full — a refusal is an
outcome, not an error, and the exit code is the only place that distinction is
compressed.

Usage errors keep argparse's own exit code 2 rather than a `sysexits.h` number, because
fighting the standard library to renumber a code every Python CLI already shares would
make this CLI *less* predictable, not more.

## Injection, and why the tests cannot reach the network

`ResearchService` takes two collaborators and owns no state:

```
ResearchService(runner=run_research, retriever_factory=build_retriever)
```

The route resolves the service from application state through a FastAPI dependency; the
CLI constructs one directly. Both then call the same `run()`. There is no second path
through which a request can become a run.

A test supplies its own `runner` (to produce a status the free-path loop cannot reach,
such as `degraded`, or to raise a backend failure) or its own `retriever_factory`. The
default factory is the only code that reads `PRODUCTION_RAG_URL`, and it is exercised in
isolation with a patched environment: constructing the HTTP backend performs no I/O, so
the test asserts which backend was selected without a socket. No test starts a server, and
no test would pass differently because a shell had the variable set.

## Adversarial matrix

Every row is an automated test in `tests/api/` or `tests/cli/`.

| Case | Expected |
| --- | --- |
| Happy answer | 200, `done`, citations resolve to markers in the report |
| Refusal, no evidence | 200, `refused`, empty citations, gaps named in the report |
| Budget exhausted | 200, `budget_exhausted`, `steps_used == max_steps` |
| Maximum boundaries | `max_steps: 20`, `top_k: 50` accepted; 21 / 51 rejected |
| Blank question | whitespace-only trims to empty and is rejected |
| Oversized question | 8001 characters rejected |
| Unknown field | rejected, message names the field, value not echoed |
| Unknown retriever | rejected, closed set enforced |
| Missing HTTP config | `capability_missing`, names the variable, no fake fallback |
| Backend failure | `backend_unavailable`, no traceback, no provider payload |
| Programming defect | `internal_error`, never `backend_unavailable` |
| Unsafe `X-Request-ID` | replaced with a fresh id; junk not echoed anywhere |
| Caller `X-Request-ID` | echoed in header and body |
| Concurrent requests | each response carries its own id; no cross-talk |
| Deterministic repeat | two identical requests differ only in `request_id` |
| Every terminal status | each serialises through the response model |
| OpenAPI | success and failure shapes named on the route |
| `/health` | still liveness-only |
| CLI parity | CLI JSON equals the HTTP body for the same question |
| CLI quoting and Unicode | quotes, emoji, CJK round-trip |
| CLI stdout discipline | stdout is exactly one JSON line, summary on stderr |
| CLI exit codes | each documented code produced by the case that owns it |
| CLI as a module | `python -m agentic_rag.research` works from a foreign cwd |

Two rows are worth reading twice, because they are the ones a convenience shortcut would
have deleted:

- **Backend failure vs. programming defect.** Both are driven through the *real* service
  with a tool that raises where a real backend would. A `ToolError` is
  `backend_unavailable`; a `TypeError` from the same seam is `internal_error`. A bug
  reported as a provider failure sends whoever is on call to read the wrong service's
  logs.
- **Concurrency isolation.** Eight requests are held on a barrier inside the runner, so
  none may return until all are in flight. Any shared mutable state would have to be
  shared *at the same moment*, which is the only version of this test that proves
  anything.

## Gates

```powershell
python -m pip install -e ".[dev]"
python -m ruff check .
python -m mypy
python -m pytest -q
git diff --check
python -m pytest -q tests/api tests/cli tests/test_health.py
python -m agentic_rag.research --question "Why use citations in RAG?" --max-steps 3 --retriever fake
```

## What the brief's smoke command actually does

This is the first thing a reviewer will run, and it exits **1**:

```
python -m agentic_rag.research --question "Why use citations in RAG?" --max-steps 3 --retriever fake
```

```
status=refused steps_used=2 citations=1 retriever=fake request_id=...
```

That is the M2 loop behaving correctly, not a runtime-surface defect. The committed
corpus has one passage about citations; the critic scores it `1 passage + 1 covered term
= 2`, below the threshold of 3, so it proposes the follow-up `rag use`, retrieves nothing
for it, and refuses with `insufficient_evidence` rather than answering from one thin
passage. The full report, its two named gaps and the whole trace are printed. Exit 1 is
the documented code for "finished without a grounded answer".

A question the corpus can actually support exits 0:

```
python -m agentic_rag.research --question "What does hybrid retrieval buy over dense retrieval alone?"
# status=done steps_used=1 citations=2  → exit 0
```

Nothing in this lane changed the planner, the critic or the threshold; tuning the corpus
or the stop rule to make a demo question answerable would be hard-coding a golden answer
into production code, which the wave forbids and which would make the refusal path
untrustworthy everywhere else.

## Assumptions and residual risks

1. **`stop_reason` is not a top-level response field.** The canonical sketch names six
   fields and this lane was told not to change the public contract, so the reason stays
   in the trace's terminal `stop` event. If the integrator wants it promoted, that is a
   contract decision, not a lane decision.
2. **`capability_missing` answers 503, not 501.** The request is valid; the deployment is
   what cannot serve it. 501 reads as "not implemented anywhere", which would be untrue
   of a deployment that has the variable set.
3. **A refusal exits non-zero.** Documented in `--help` and above. If a caller wants
   "the process ran" semantics, `--quiet` plus reading `.status` from the JSON gives it
   without the exit code.
4. **The README and `docs/architecture.md` still say the route and CLI are planned.**
   Both are outside this lane's ownership and were deliberately not touched. The
   direction of the error is the safe one — the docs understate what is shipped rather
   than overstating it — but the integrator has to correct the milestone tables and the
   status line before this is released.
5. **No `X-Request-ID` is forwarded to production-rag.** `docs/architecture.md` describes
   the agent passing its run id on the outbound query so both services' logs join. The
   outbound client lives in `tools/retrieve.py`, which belongs to another lane, so the id
   stops at this service's boundary. The service already has the value; wiring it through
   is a one-line change in the owner's lane.
6. **Body size is bounded by the question length, not by the transport.** A request whose
   `question` is 8001 characters is rejected, but a multi-megabyte JSON body is parsed
   before that check runs. A body-size limit belongs to the server or the proxy in front
   of it, and adding one here would be a dependency and a deployment decision this lane
   was not asked to make.
7. **The `degraded` status is reachable through the transport but not through the free
   path.** The loop never produces it. The response model, the CLI's exit-code table and
   the tests all handle it, driven by a stub runner — so the day a tool failure produces
   it, the surface already reports it rather than crashing on an unexpected value.
8. **A backend failure will change shape once lane A4 lands, and this surface already
   handles both.** A4 makes `run_research` catch `ToolError` inside `retrieve_node` and
   finish the run as `degraded` rather than letting it escape. After that rebase, a
   failing retrieval reaches this service as a *finished run*, so it answers **200 with
   `status: "degraded"`** (CLI exit 1) instead of **503 `backend_unavailable`** (CLI exit
   4). No code change is needed here — the `ToolError` catch stays correct as the seam
   for anything A4 does not swallow, and `degraded` is already a first-class value in the
   response model, the OpenAPI enum, the CLI exit table and the tests. But the integrator
   has to choose which one the published contract promises, because both are defensible
   and only one can be documented: a transport-level failure the caller retries, or a
   completed run whose status says the world failed under it.
9. **Fake-provider claims stay plumbing-only.** Everything demonstrated here — the route,
   the CLI, the error envelope, the correlation id, the trace — is transport behaviour
   over a deterministic in-process fixture. None of it is evidence about retrieval or
   answer quality, and the OpenAPI description says so in the document a client author
   reads.

## Log

- **Checkpoint 1 — baseline inventory and contract.** Repository read end to end, gates
  run green on an untouched checkout (`ruff`, `mypy` on 17 files, 97 tests), branch cut
  from the dispatch SHA. Contract above written before any runtime code.
- **Checkpoint 2 — shared adapter and schemas.** `ResearchService`, the strict request
  and response models, the error envelope and the correlation-id rule, with unit tests
  for each. No transport yet.
- **Checkpoint 3 — HTTP.** Route, middleware and handlers. Refusals and exhausted budgets
  are 200s with honest statuses; only an unservable request is a non-2xx.
- **Checkpoint 4 — CLI and parity.** `python -m agentic_rag.research` over the same
  service, and the tests that compare its JSON to the route's body for the same question,
  success and failure alike.
- **Checkpoint 5 — adversarial sweep, OpenAPI review, packaging.** Failure cases moved
  onto the real service path; the schema checked to name every failure shape; a wheel
  built, installed into a clean virtual environment outside the repository, and driven
  both as a CLI and as a uvicorn process over a real socket.
- **Checkpoint 6 — fresh-environment validation.** Gates re-run from a clean checkout of
  the pushed branch in a new virtual environment.
</content>
</invoke>
