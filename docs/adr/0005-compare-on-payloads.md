# ADR-0005 — Compare finished runs by payload, never by server id

- **Status:** accepted
- **Date:** 2026-08-14
- **Scope:** how two finished research runs are placed next to each other for review,
  and why that operation does not resolve `GET /v1/runs/{id}`

## Context

v0.2.0 stored finished runs in process memory under their correlation id. That store is
the right answer for "fetch the run I just performed on this instance": it is keyed (no
shared "last trace" slot), bounded, and carries stop reason, notes, citations, and the
full trace.

It is the wrong answer for "put two runs next to each other after the host recycled."

Three properties of the store make id-keyed compare fail in the situations a hiring
manager actually hits:

1. **Serverless recycle.** On Vercel the function isolate that minted `request_id=abc`
   is not guaranteed to be the isolate that later serves `GET /v1/runs/abc`. A cold
   start is an empty store. The id is gone; the JSON the reviewer already downloaded is
   not.
2. **Bounded eviction.** Capacity is 32. The oldest finished run is dropped. A compare
   that waits until the end of a demo session can 404 a still-interesting id.
3. **No shared durable layer.** There is no disk and no shared cache between instances.
   Pointing compare at two ids is pointing at two slots that may never have lived in the
   same process.

An alternative that "fixed" this by writing runs to object storage would be a different
product: durability, retention, multi-tenant keys, and a cost story this free-path
portfolio piece does not own. The honest durable artifact is already in the client's
hands the moment they click **Download full run (JSON)**.

## Decision

**Compare accepts two complete run payloads in the request body and never looks up a
server id.**

1. **`POST /v1/runs/compare`** takes `{ "left": <RunArtifact>, "right": <RunArtifact> }`
   and returns a typed field-level diff (`identical`, ordered `diffs`, both request ids
   echoed for labels only).
2. **Compared fields** are fixed and ordered: `status`, `stop_reason`, `steps_used`,
   `max_steps`, `question`, `retriever`, `report`, `citations`, `notes`, `trace`. The
   response is byte-stable for a given pair of inputs.
3. **`GET /v1/runs/{id}/run.json`** downloads the full artifact as an attachment so a
   reviewer can keep the payload after the id dies. Trace-only download remains for the
   timeline use case.
4. **`/compare` UI** loads two local JSON files in the browser and posts those bodies to
   the compare route. It does not ask the server for either id.

## Consequences

- A recycle, eviction, or second instance cannot break a comparison the reviewer is
  prepared for: the files are enough.
- The server never becomes a second source of truth that can disagree with a download.
- Compare cannot invent a run that was never downloaded; the caller must supply both
  sides. That is intentional.
- OpenAPI documents the payload shape, so a client can validate without guessing which
  fields matter.

## Rejected alternatives

| Alternative | Why not |
| --- | --- |
| `POST /v1/runs/compare` with two ids | 404 after recycle; hiring demo dies on the second open |
| Compare "last two" server-side slots | Shared mutable state; concurrent callers race |
| Persist runs to disk / blob store | Scope expansion; free-path portfolio piece stays in-process |
| Generic JSON Patch of whole bodies | Noisy; reviewers care about stop reason / steps / notes / citations |

## Related

- [ADR-0004](0004-notes-are-a-store.md) — notes as the store the critic scores.
- `agentic_rag.api.runs` — why the store is bounded and in-memory.
- `agentic_rag.api.compare` — pure payload diff with no `RunStore` import on the hot path
  beyond the shared `RunArtifact` type.
