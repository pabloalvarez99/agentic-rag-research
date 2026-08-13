# A3 — the optional production-rag integration

The retrieval boundary has two implementations. One is a fixture over five
committed documents and needs nothing; the other talks HTTP to a running
production-rag instance and is what this workstream is about.

The fixture stays the default, unconditionally. Nothing in this lane makes the
hosted path automatic, and nothing in the default test suite opens a socket.
What follows is the contract that path speaks, the failures it is written for,
and the evidence that both are real rather than asserted.

## The upstream contract, and how it was established

Everything here was read out of one tagged checkout, not out of a summary of one:

| | |
|---|---|
| Repository | `https://github.com/pabloalvarez99/production-rag` |
| Tag | `v0.1.0` |
| Commit | `678c5543baf0f4a723dc823de1f19162ba54b4a9` |
| Working tree at inspection | clean |
| Access | read-only; nothing in that repository was modified by this lane |

The files that were read, and what each one settled:

| Upstream file | What it establishes |
|---|---|
| `api/schemas.py` | Request and response shapes; `extra="forbid"` on the request; which response fields are required |
| `api/routes/query.py` | The route, its status codes, `response_model_exclude_unset=True`, and that `llm`/`embedder`/`rerank` select providers **per request** |
| `api/middleware.py` | `X-Request-ID`, the shape it must have, and that a malformed one is silently replaced |
| `config.py` | `api_prefix` defaults to `/v1` and is deployment-configurable |
| `generation/guardrails.py` | The closed set of refusal reasons |
| `generation/citations.py` | Citations arrive in answer-mention order and markers are deliberately not renumbered |
| `docs/demo.md`, `scripts/demo_setup.*`, `docker-compose.yml` | The credential-free demo stack, its collection, and the two demo questions |

The machine-readable half is frozen in
[`tests/contracts/fixtures/p1-query-v0.1.0.openapi.json`](../../tests/contracts/fixtures/p1-query-v0.1.0.openapi.json):
an excerpt — one path, four schemas — carrying an `x-provenance` block that
records the tag, the commit, the date, the exact command that generated it, what
was left out, and the facts that are *not* visible in an OpenAPI document at all
(the refusal-reason set, the citation ordering, the unset-field projection).

A whole-document snapshot was deliberately not committed. A snapshot of four
paths and eight schemas fails on every additive upstream change, and a fixture
that cries wolf gets regenerated without being read. The excerpt plus
`verify_contract()` fails only when something this client actually reads changes.

## Four contract facts that changed the adapter

Each of these is a defect if it is assumed rather than checked, and each was
found by reading the tag.

1. **Citations arrive in mention order, `rank` is the retrieval position.**
   `citations[:top_k]` would therefore keep whatever the model cited in its
   opening sentence and throw away rank 1. The adapter sorts by rank before it
   caps, and preserves the upstream rank verbatim instead of renumbering — the
   first thing anyone debugging this path does is line the two rankings up.
2. **Omitting `rerank` selects the deployment's `auto`.** At the tag, the route
   calls `build_reranker(payload.rerank or RERANK_AUTO, …, api_key=os.environ[…])`.
   On a deployment with Cohere configured, a client that stays quiet spends
   somebody's money. The adapter pins `rerank="off"`, and `RerankMode` omits
   `cohere` entirely, so the billed value is not expressible from here.
3. **The route serialises with `response_model_exclude_unset=True`.** Only
   `answer` and `refused` are required, so `citations` and `refusal_reason` can
   be absent from a perfectly valid body. Every field the client reads has a
   default.
4. **`api_prefix` is deployment configuration.** `/v1/query` is built from the
   prefix rather than hard-coded, and normalised the way upstream normalises it.

## What the adapter guarantees

| Guarantee | The failure it exists to prevent |
|---|---|
| Free providers pinned per request | Opting into the service silently opting into a billed model or reranker |
| Citations only; `answer` is not even modelled | This agent becoming a paraphraser of another model's single pass |
| Rank-ordered, deduplicated, then capped | Dropping the best evidence; one chunk counting twice toward sufficiency |
| Separate connect (3s) and read (20s) budgets | A hung service consuming a run that has a step budget |
| `retries=0`, explicitly | A "transient" failure multiplied by every layer that decided to be helpful |
| Redirects refused, not followed | An address resolving somewhere the operator never configured |
| Body streamed and bounded at 4 MiB | One response exhausting the process |
| Typed `ToolError` with a stable slug | `httpx` exception types leaking into agent control flow |
| Errors name fields and rules, never values | The adapter being the component that wrote somebody's data into a trace |
| URL validated at wiring time | A misconfigured address surfacing later as a retrieval that "found nothing" |

### Error slugs

`ToolError` carries `error_type`, a stable slug a dashboard can group by while
the message stays free to be rewritten. Statuses map to
`validation_error` (400, 422), `unauthorized` (401, 403), `rate_limited` (429),
`backend_unavailable` (502/503/504 and every timeout or transport failure),
`provider_error` (other 5xx), and `contract_mismatch` (404, redirects, unexpected
statuses, unreadable bodies, oversized bodies).

`contract_mismatch` is the one slug with no entry in the portfolio-wide failure
taxonomy, because it names something only a *client* can observe: "the service is
broken" and "the service is fine and is no longer the service this code was
written against" are indistinguishable from the inside, and collapsing them into
`provider_error` sends whoever is on call to read the wrong logs.

### Refusal versus silence

Three upstream outcomes reach this client as zero passages, and two of them are
different problems:

* `GROUNDED` — the answer cited retrieved chunks.
* `UPSTREAM_REFUSED` — the guardrail declined. The corpus does not support this
  sub-question, which is a gap a critique can name.
* `ANSWERED_WITHOUT_CITATIONS` — an answer was served and nothing in it resolved
  to a chunk. The corpus may well contain the evidence and the grounding pipeline
  did not attach it.

A refusal yields no evidence even if citations arrive with it. Upstream cannot
produce that combination at the pinned tag, but a proxy, a cache or a later
release can, and the two readings are not equally safe: passing the citations
through would let the agent build a report on evidence the service itself said
does not support an answer. `citations_returned` still records that they arrived.

The distinction travels on `RemoteQueryOutcome.evidence_state`, reachable through
`HttpRetrievalBackend.query()`. It is deliberately **not** on the
`RetrievalBackend` protocol or on `RetrieveResult`: widening either would make
every backend answer a question only one of them can answer, and would change a
type the agent loop owns — another lane's file.

## The URL is configuration, never data

A research question is text to search for. There is no code path that turns one
into a request target: `build_retrieve_tool()` takes no URL, `RetrieveRequest`
has no field for one and rejects unknown fields, and the address is read once
from `PRODUCTION_RAG_URL` before any question is asked.

`ServiceUrl` is a whitelist rather than a sanitiser. It refuses what it does not
understand instead of repairing it, because a repaired URL is a URL nobody
audited: silently dropping a query string or coercing a scheme means the address
that was configured and the address that was dialled are different, and the
difference only surfaces during an incident. Refused: non-`http(s)` schemes,
embedded credentials, missing host, query strings and fragments, relative path
segments, whitespace and control characters, unparseable ports, anything over
2048 characters. A rejection never echoes a URL containing `@`.

A `PRODUCTION_RAG_URL` that fails validation raises at wiring time rather than
degrading to the fake. A run that silently answered from a five-document fixture
when the operator asked for a real corpus is a run whose results mean nothing,
and nothing in its output would say so.

## Test layout, and why it is split

| Directory | Runs | Needs |
|---|---|---|
| `tests/contracts/` | always, on every machine | nothing — no socket, no credential, no Docker |
| `tests/integration/` | only when opted into | a running production-rag instance |

`tests/contracts` (230 tests) covers the contract fixture and its drift
detection, the mock-transport matrix, and URL safety. These never skip. Included:
grounded 200, refusal, empty citations, additive fields, top-k caps, duplicate
and oversized citations, Unicode source paths, trailing slashes, 400/401/403/404/
418/422/429/500/502/503/504, redirects, connect/read/pool timeouts, connection
resets, non-JSON bodies, JSON that is not an object, thirteen wrong-type
responses, an endless stream, a body over the size bound, and every unsafe URL
form above.

Eighteen of those tests mutate one field of the frozen spec and assert the drift
report names it. A drift detector nobody has watched fail is a function that
returns `()` and a comment.

`tests/integration` requires **two** environment variables: `RUN_P1_INTEGRATION=1`
and `PRODUCTION_RAG_URL`. Two, because `PRODUCTION_RAG_URL` is also what switches
the agent onto the hosted backend — a developer who exports it to try a local
stack has not thereby volunteered their test suite for network access. Absent
either, the tests skip with the reason printed, which is what keeps CI green on a
machine with no Docker without anyone editing a config file.

The `integration` marker is registered from `tests/integration/conftest.py`
because `pyproject.toml` belongs to another lane.

## Live verification

`scripts/integration/verify_p1.ps1` and `verify_p1.sh` are the same script twice.
They use an instance already answering `/health`, and only otherwise start
production-rag's **own** documented demo stack by calling its
`scripts/demo_setup`. This repository does not know how to build, ingest or
configure that service, and a second copy of those steps here would be a copy
that rots.

Cleanup is bounded by what the script started. A stack it found is left running;
a stack it started is stopped with `docker compose down`, which keeps the named
Qdrant volume exactly as production-rag's docs describe. Either way the last
lines say what is still running, how to remove it, and whether the live E2E
actually ran.

### The run

```
.\scripts\integration\verify_p1.ps1 -P1Path <production-rag checkout> -KeepStack

target: http://127.0.0.1:8000
found an instance already answering /health; this script will not start or stop anything.
instance reports: production-rag 0.1.0 (local)
tests\integration\test_p1_live_query.py .........        [100%]
9 passed in 6.98s
live free-path E2E: PASSED against http://127.0.0.1:8000
live E2E actually ran: yes
```

What that run established, against production-rag `0.1.0` serving the documented
`prag_demo` collection:

* `verify_contract()` against the **live** `/openapi.json` returns `()`.
* The four schemas this client consumes — `QueryRequest`, `QueryResponse`,
  `CitationOut`, `QueryDebug` — are byte-identical to the frozen fixture. The
  `POST /v1/query` node differs only in what `x-provenance.not_captured` already
  declares was dropped: `summary`, `description`, `tags`, and the 422 body `$ref`.
* The documented grounded question returns ranked, distinct, non-empty evidence.
* The documented unanswerable question returns `refused: true` with a reason from
  the closed set and zero passages.
* Both recorded request bodies carried `llm=fake`, `embedder=fake`, `rerank=off`
  and nothing else.
* The API container had **no provider credential at all** (`OPENAI_API_KEY` and
  `COHERE_API_KEY` both absent), so a billed call was not merely unrequested but
  unreachable. The probe reports presence as `0`/`1` and never reads a value.

## Deviations, limitations and residual risk

**Layout.** The new modules live in `src/agentic_rag/tools/` rather than in a
sibling `retrievers/` package. A `retrievers/` package cannot import `ToolError`
from `agentic_rag.tools.base` while `agentic_rag.tools` re-exports
`HttpRetrievalBackend`: that is a cycle, and it raised on any import that reached
`retrievers` first. The alternatives were a lazy function-level import (a cycle
hidden rather than removed), dropping a public re-export (a break this lane is
not allowed to make), or a new top-level module outside this lane's files. The
modules moved instead. Nothing imports upward now, and every module was verified
to import cleanly on its own.

**The stack-start path was not exercised.** The live run found an instance
already listening — started eight hours earlier, same compose project, same
checkout, same collection — and the cleanup rule forbids tearing down what this
lane did not start. The "found an existing instance" branch ran end to end; the
"start one" branch delegates to production-rag's own tested script and was
reviewed, not executed. Running `verify_p1.ps1` on a machine with no stack up
exercises it.

**`top_k` is applied to the response, not to the query.** The route publishes no
`top_k`, so the cap trims what is transferred and not what the service computed.
Closing that needs a parameter upstream, which is outside this lane.

**The loop does not catch `ToolError`.** `run_research` lives in `agent/**` and
belongs to another lane; a tool failure currently unwinds the run rather than
consuming a step. This adapter's job ends at raising a typed, message-safe error,
and the A4 reliability lane is where that error gets handled.

**The refusal/uncited distinction is not on the tool's result.** It is reachable
only through `HttpRetrievalBackend.query()`. Surfacing it in a trace means
touching types the agent lane owns.

**`FakeLLM` is plumbing, not quality.** Every live assertion here is about shape,
grounding and refusal behaviour. None of it is a retrieval-quality result, and
the demo stack's providers are deterministic doubles by design.
