# ADR-0003 — One read-only tool, behind a protocol, with the retrieval service one seam further out

- **Status:** accepted
- **Date:** 2026-08-13
- **Scope:** the tool surface the agent may call, the shape of a tool, and where the
  boundary to the outside world sits

## Context

The capability an agent has is the list of tools it can call, and that list only ever
grows. Every tool is a permanent commitment: something a future model can invoke, in an
order nobody enumerated, with arguments it produced. The cheapest moment to refuse a
capability is before it has a call site — afterwards, removing it breaks a caller and
the argument becomes a negotiation.

This project has one job: run a bounded `plan → retrieve → critique` loop and show what
it adds over a single retrieval pass. Every tool beyond retrieval widens the surface
without touching that question. Meanwhile the retrieval service itself is the one thing
the loop genuinely cannot do without, and it has two forms — a deterministic fixture and
a real HTTP service — that must be interchangeable or the free path is a different
system than the paid one.

There is a second, quieter question. A tool that returns prose forces the next step to
parse it to discover whether anything was found, which means "found nothing" and "the
call failed" are separated by a string comparison. That distinction is the input to the
stop rule ([ADR-0002](0002-step-budget.md)), so it cannot live in a tone of voice.

## Decision

**One tool, `retrieve`. It reads and returns evidence, and it is the only outbound
surface. The retrieval service sits behind a second protocol one seam further out, so
the fake and the real service are interchangeable without the loop noticing.**

### The tool surface, in full

| Tool | Responsibility | Boundary it must not cross |
| --- | --- | --- |
| `retrieve` | Run one sub-question against the retrieval boundary and return ranked passages carrying the identity a citation needs. | It does not plan, it does not answer, and it does not re-rank what the backend returned. |

`plan`, `critique` and `synthesize` are **not tools**. They are pure functions the loop
calls; they take no arguments a model chose and reach nothing outside the process.
Calling them tools would suggest a model could invoke them in some other order, which is
exactly the property the bounded loop exists to deny.

### What is deliberately not a tool

Stated now, so each one is a decision with a reason rather than an absence:

- **No write tool.** The agent reads a corpus. It does not ingest, index, or mutate
  anything in the retrieval service. A research loop that can write to the thing it
  researches can corroborate itself.
- **No shell and no filesystem access.** Neither is needed to answer a question from a
  corpus, and both turn a prompt-injected passage into arbitrary code execution.
  Retrieved text is untrusted input: it comes from a corpus this process did not write.
- **No arbitrary HTTP.** The single outbound URL is the retrieval service, taken from
  `PRODUCTION_RAG_URL` and read once at construction. A general fetch tool would make
  every retrieved passage a potential redirect for the next request.
- **No sub-agent spawning.** One agent, one loop. Orchestration between agents is
  project #3 in the series and does not leak backwards into this one.
- **No answer-generation tool.** The synthesiser selects and marks passages; it does not
  write prose about them. When a model writes the report, that is a provider behind a
  protocol, not a tool the loop can decide to call twice.

### The two rules every tool obeys

1. **A tool call is a function of its arguments and the retrieval service.** No tool
   reads ambient configuration or global mutable state, so replaying a trace's arguments
   reproduces the step. `build_retrieve_tool()` reads the environment exactly once, at
   construction, and an explicitly supplied backend means the environment is not read at
   all — which is what every test does.
2. **Every tool returns evidence or an explicit absence.** `RetrieveResult.passages` is
   empty when nothing was found; `is_empty` is a property, not an interpretation. A
   failure is a raised `ToolError`. The difference between "found nothing" and "failed"
   is a field, not a tone.

### Two protocols, not one

```
loop ──calls──► Tool (protocol)          the loop-facing surface
                  └── RetrieveTool
                        └──uses──► RetrievalBackend (protocol)   the outbound surface
                                     ├── FakeRetrievalBackend    in-process, default
                                     └── HttpRetrievalBackend    opt-in, production-rag
```

The tool is what the loop calls; the backend is where the process ends. Splitting them
is what lets the fake and the real service be swapped without the loop, the tests, or
the trace changing shape — the tool records which backend served each call, so two runs
that differ can say why.

Both are `Protocol`s and structural, so a test supplies either with a small class and no
container, no key, and no patching of module globals.

### `Passage` is the currency

Every tool result carries `chunk_id`, `source_path` and `text` — the three fields a
citation needs to be checkable by someone who does not trust the agent — plus the `rank`
it arrived at. It is frozen: evidence that can be edited after the fact is evidence a
citation cannot be checked against.

This is also why the HTTP backend reads production-rag's `citations` array and ignores
its `answer`. Each citation is already a passage with an id and a path. The generated
answer is that service's single pass, and consuming it would make this agent a
paraphraser of another model's output rather than a retriever of evidence — which would
also destroy the comparison against the single-pass baseline, since the baseline would
then be inside the agent.

## Alternatives considered

**A tool registry with dynamic dispatch by name.** The standard agent shape: a dict of
name → callable, and the model picks. Rejected at one tool, because it buys indirection
and costs the ability to type the call site — `RetrieveTool.run` takes a validated
`RetrieveRequest` and returns a `RetrieveResult`, and a registry would collapse both to
`dict`. The registry is the right answer when a *model* chooses among several tools; at
that point it lands with the model, and `Tool` is the protocol it will dispatch over.

**Fold the backend into the tool: one class, a flag for fake or HTTP.** One fewer
protocol, and honestly one fewer file. Rejected because the flag would sit inside the
class the loop depends on, so every test would exercise the branch rather than the seam,
and the fake would be a mode of the real thing instead of an independent implementation
of a stated contract. The two-protocol version is what makes "the loop cannot tell them
apart" a checkable claim rather than an aspiration.

**Let the tool re-rank or filter what the backend returned.** Tempting: the tool sees the
sub-question and the passages together, so it could drop obvious misses. Rejected
because ranking is the retrieval service's job and the agent is being measured *against*
that service. A tool that quietly improves the ranking makes the comparison meaningless
and the service impossible to measure. The tool applies the caller's `top_k` cap and
nothing else.

**Give the agent a general HTTP fetch tool so it can follow sources.** It is what a human
researcher does. Rejected on the security boundary: retrieved text is untrusted, and a
fetch tool makes a passage able to direct the next request. It also breaks the free path,
since a reviewer with no network gets a different system than CI does.

**Expose `plan` and `critique` as tools a model may call.** The fully agentic version,
where the loop is emergent rather than written. Rejected at this milestone for the reason
in [ADR-0002](0002-step-budget.md): the loop is the thing under test, and a loop the model
can reorder cannot be tested for termination. It is a legitimate later design, and it
starts from a loop that is already proved.

## Consequences

**Bought.** The blast radius of a prompt injection in a retrieved passage is bounded by
what the loop can do with a passage, which is: score it, cite it, or ignore it. The whole
outbound surface is one method with one URL, so "what can this process reach?" has a
one-line answer for a reviewer. Tests need no container, no network and no key. And
swapping the fake for a real service is a construction-time decision that leaves the
loop, its trace and its assertions unchanged.

**Accepted costs.** Two protocols where a smaller project would have one. Capabilities a
real research agent would want — following a citation to its source, reading a file
named in a passage — are refused rather than deferred, and adding any of them means
reopening this record. The `Tool` protocol currently has one implementation, which is one
short of the number that justifies a protocol; it stays because the second one arrives
with the model, and because it is the surface the trace's `tool_call` event is written
against.

**Checkable.** `tests/test_retrieve_tool.py` asserts the tool does not reorder or
augment what a backend returned, that an empty result is a result rather than an error,
and that `build_retrieve_tool` reads the environment only when no backend is supplied.
The claim that the loop cannot tell the backends apart is testable because the loop's
tests supply their own backend and never name one.
