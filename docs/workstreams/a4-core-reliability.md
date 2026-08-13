# A4 — bounded-engine reliability, degradation and trace verification

Lane report for `feat/p2-core-reliability`. Branched from `origin/main` at
`0b86e962f2f8fdee7b2b40e2b109e0320a1f8c19`, which is the SHA the wave was dispatched against.

This document is the reasoning behind the diff: what was frozen before editing, which invariants
the engine is supposed to hold, what the degradation contract is, and which parts of the public
surface grew. It is a workstream report, not an ADR — the architecture decisions it depends on are
already recorded in `docs/architecture.md`.

## 1. Baseline

The tree at `0b86e96` passes `ruff`, `mypy --strict` and `pytest` unchanged. The agent is a bounded
loop over four nodes (`plan_node`, `retrieve_node`, `critique_node`, `finish_node`) whose budget and
terminal-status invariants live inside `ResearchState`, and whose trace is the only durable record
of what a run did.

### 1.1 What was frozen, and how

`tests/reliability/baseline_m2_runs.json` holds `ResearchState.model_dump(mode="json")` for nine
successful-path runs generated **before** any production edit: every terminal status M2 could
produce (`done`, `refused`, `budget_exhausted`), every stop reason it could produce
(`evidence_sufficient`, `no_evidence`, `insufficient_evidence`, `budget_spent`), budgets of 1, 3, 4,
5 and 20, `top_k` of 1 and 5, and a Unicode question. `tests/reliability/test_compatibility.py`
re-runs each case and compares the dump, the key order of every object in it, and the event-name
sequence of every trace.

No test regenerates that file. A fixture a test can rewrite records what the code does today; it
does not evidence that the code still does what it did yesterday.

## 2. Invariants

The contract the engine is expected to hold, and where each part of it is enforced or checked. The
verifier codes are the ones `agentic_rag.verification.verify_run` returns.

| # | Invariant | Enforced by | Verifier code |
|---|-----------|-------------|---------------|
| I1 | A run's trace starts with exactly one `plan_created`, and the plan is non-empty | `ResearchState.record_plan` | `plan_missing` |
| I2 | Events follow the loop's grammar: `plan_created (tool_call (tool_result critique \| tool_error))* synthesize stop` | the loop's shape | `event_out_of_order` |
| I3 | Every `tool_call` is followed by exactly one `tool_result` or one `tool_error` | `retrieve_node` | `tool_call_unresolved` |
| I4 | No `tool_result` or `tool_error` appears without a preceding unresolved `tool_call` | `retrieve_node` | `tool_outcome_unpaired` |
| I5 | A finished run has exactly one `stop` event | `ResearchState._require_running` | `stop_missing`, `stop_repeated` |
| I6 | `stop` is the last event; nothing is recorded after it | `ResearchState._require_running` | `stop_not_last` |
| I7 | A finished run carries a terminal status | `ResearchState.finish` | `status_not_terminal` |
| I8 | Steps taken never exceed `max_steps`, and every attempted tool step costs one | `ResearchState.record_retrieval`, `record_tool_failure` | `budget_exceeded` |
| I9 | Status and stop reason are a pair from the compatibility table in §3.3 | `decide_outcome` | `status_reason_mismatch` |
| I10 | A `synthesize` event precedes `stop`, and a finished run has a report | `finish_node` | `synthesis_missing`, `report_missing` |
| I11 | Every `[n]` printed in the report resolves to a citation, and every citation is printed | `synthesize` | `citation_marker_unresolved` |
| I12 | Markers are `1..n` in order | `synthesize` | `citation_out_of_order` |
| I13 | Every citation resolves to a passage that was actually retrieved, by chunk id, source path and text | `synthesize` | `citation_not_grounded` |
| I14 | Evidence holds each chunk id once, in first-seen order | `ResearchState.record_retrieval` | `evidence_duplicated` |
| I15 | The trace agrees with the state: plan, step count, evidence, failures, status and reason | the `record_*` methods | `trace_state_mismatch` |
| I16 | A trace event is one of the declared names | `TraceEvent` validation | `unknown_event` |

I1–I16 are checked by a pure function over a finished (or unfinished) state. Verification reads; it
never writes. The tamper tests in `tests/reliability/test_verifier.py` construct states that violate
each one and assert the specific code comes back.

## 3. Degradation contract

### 3.1 The defect

`retrieve_node` called `tool.run(request)` with no handler. `RetrieveTool` documents that it raises
`ToolError` when the backend cannot produce a result, and `HttpRetrievalBackend` raises it for an
unreachable service or an unreadable body — the ordinary case of a `PRODUCTION_RAG_URL` pointing at
a production-rag instance that is down. The exception unwound `run_research`, so the caller got a
traceback instead of a state: no status, no report, no trace, no record that a step was attempted.
`ResearchStatus.DEGRADED` was declared and unreachable.

### 3.2 The rule

A `ToolError` from a tool call is an **expected** outcome of calling something that talks to the
world, and is handled exactly once, in `retrieve_node`:

1. The attempt is recorded as a step. **A failed call spends one unit of `max_steps`**: a run that
   retried for free would be a run whose budget is not a bound.
2. A typed failure is recorded on the step and traced as `tool_error`. The exception object is
   discarded without being read — see §3.4.
3. The run stops. No retry, no fallback backend, no second call.
4. `finish_node` composes a report from whatever was grounded before the failure and closes the run
   as `degraded`.

Anything that is not a `ToolError` propagates untouched. A `KeyError` inside a backend is a bug, and
a bug that is turned into a `degraded` run is a bug nobody will find.

### 3.3 Status and reason after a failure

| Status | Stop reason | When |
|--------|-------------|------|
| `done` | `evidence_sufficient` | the critic found the evidence enough |
| `refused` | `no_evidence` | nothing was retrieved at all |
| `refused` | `insufficient_evidence` | evidence was gathered, never sufficed, budget left |
| `budget_exhausted` | `budget_spent` | evidence was gathered, never sufficed, budget spent |
| `degraded` | `tool_failed` | a tool call raised `ToolError` |

`degraded` outranks `budget_exhausted`: when the last affordable step is the one that failed, the
proximate cause is the failure, and reporting `budget_spent` would put a falsehood in the first
field an operator reads. It outranks `done` for the same reason — a run that answered despite a
failed tool did not have a clean run, and says so.

The report is honest in both directions. With evidence: a `Status: degraded` line, the findings the
run did ground with their citations, and the gaps the last critique named. Without evidence: an
explicit unavailable report that states no answer could be grounded. Neither reads like a complete
run.

### 3.4 Why the exception is discarded

`ToolError` messages are built from what the backend saw. `HttpRetrievalBackend` interpolates the
query URL and the `httpx` error, and a base URL is exactly the kind of string that carries a
credential (`https://user:token@host`). A response body it could not parse is untrusted text from
another service.

So the loop does not read the exception. `tool_failure()` takes a tool name and nothing else, and
the recorded `detail` is a template over that name. That is a structural guarantee rather than a
redaction pass: there is no code path by which provider text reaches the state, and
`test_degradation.py` asserts it by raising a `ToolError` whose message contains a secret-shaped
string and searching the whole serialised run for it.

The cost is real: the cause is not in the state. The cause belongs to the observability layer, which
binds a request id and masks what it logs — that layer arrives with the HTTP route, and this lane
does not own it.

## 4. Additive contract changes

Everything below is additive. No field was removed, renamed, retyped or reordered, and no
successful-path value changed.

| Change | Kind | Note |
|--------|------|------|
| `ToolFailure` model, `tool_failure()` factory (`agent/failures.py`) | new public symbols | `{tool, error_type, detail}`; `error_type` from a closed set |
| `StepRecord.failure: ToolFailure \| None = None` | new optional field | `null` on every successful step; the only key added to a successful dump |
| `StepRecord.failed` | new property | not serialised |
| `TraceEventName` gains `"tool_error"` | new member | emitted only when a tool fails |
| `StopReason` gains `"tool_failed"` | new member | pairs only with `degraded` |
| `ResearchState.record_tool_failure()` | new method | spends a step, traces `tool_error` |
| `ResearchState.failed_sub_questions`, `last_tool_failure`, `has_tool_failure` | new properties | not serialised |
| `decide_outcome(..., tool_failed=False)` | new keyword-only argument | defaulted; existing calls unchanged |
| `synthesize(..., failure=None)` | new keyword-only argument | defaulted; existing calls unchanged |
| `retrieve_node` returns `bool` | widened return | was `None`; callers that ignore it are unaffected |
| `agentic_rag.verification` | new package | pure, imports nothing from the loop's control flow |

`StepRecord.failure` is always present and `null` rather than omitted when absent. A key that
appears only sometimes forces every consumer to write the same defensive branch, and a schema that
says "optional" is easier to read than one that says "sometimes". The price is one new key in the
successful-path dump, which is why the compatibility test names it explicitly instead of diffing
loosely.

## 5. Corrected behaviour that was not a serialisation change

- `ResearchState.unanswered_sub_questions` reported a sub-question whose tool call *failed* as one
  that "returned nothing". The critic turns those into a gap reading `no passage was retrieved for
  the sub-question …`, which would state as fact that the corpus had nothing when the truth is that
  the tool never answered. Failed steps are now excluded from `unanswered_sub_questions` and
  reported by `failed_sub_questions`.
- `_snippet` copied retrieved text into the report verbatim. Retrieved text is untrusted
  (master plan §13.6), and the report is printed to a terminal by the CLI that arrives with M3, so a
  passage containing an ANSI escape could rewrite an operator's screen — and a passage containing a
  `\r` could hide the rest of the finding it belongs to. C0/C1 control characters are now dropped
  from a finding. The committed corpus contains none, so no baseline dump changed.

## 6. Bounds

Trace length is linear in the budget, and the constant is small enough to state exactly:

```
len(trace) <= 3 * max_steps + 3
```

`plan_created` + `synthesize` + `stop` are the three fixed events; each step contributes at most
`tool_call`, one of `tool_result`/`tool_error`, and a `critique`. A failed step contributes fewer,
because the run stops. `tests/reliability/test_bounds.py` asserts the bound for every budget from 1
to 20 against a backend built to force the maximum number of steps, and asserts that doubling the
budget does not more than double the trace. Nothing there measures wall-clock time: a bound proved
by a stopwatch is a bound that fails on a loaded machine.

## 7. Residual risks

- The `degraded` path is exercised by backends that raise on demand. No test contacts a real
  production-rag instance, so what is proved is that the *loop* degrades honestly, not that
  `HttpRetrievalBackend` raises `ToolError` for every real-world failure it can meet. That backend
  belongs to another lane.
- `error_type` has one member today (`tool_error`). A tool layer that later distinguishes a timeout
  from an unparseable body can add members without breaking the field, but until it does, the typed
  failure carries less information than the taxonomy in master plan §33 allows for.
- The cause of a failure is deliberately absent from the state (§3.4). Until the observability layer
  lands, diagnosing *why* a tool failed needs the caller's own logs.
- The verifier checks the contract the loop declares. It cannot detect a run that is internally
  consistent and wrong — a corpus that returns plausible passages for the wrong question passes
  every invariant here.
