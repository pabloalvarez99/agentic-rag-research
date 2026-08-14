# ADR-0001 — The free path is the default; the paid path is opt-in and later

- **Status:** accepted
- **Date:** 2026-08-13
- **Scope:** provider defaults, the retrieval boundary, and the milestone order

> **Amendment, 2026-08-13.** Milestone names now follow the canonical portfolio
> plan: M3 is API/CLI, M4 is the optional production-rag HTTP adapter, M5 is evals,
> and M6 is release polish. HTTP does not itself mean paid — P1 also has a fake-provider
> path. The decision is unchanged: deterministic mechanism comes before any hosted,
> billed quality run.

## Context

This project is a bounded `plan → retrieve → critique` loop over a retrieval
service. Both of its expensive surfaces are optional in principle and default-on
in most agent codebases: a hosted model for planning and critique, and a live
retrieval service holding a real corpus.

An agent loop makes that cost structure worse than a single-pass system does.
One question is several planning calls, several retrievals, and several critique
calls, and the count is decided at runtime by the loop itself. During
development, a wrong stop rule is not a wrong answer — it is a wrong answer that
bills for every iteration it took to get there.

Two facts about the audience decide the rest. First, this is a portfolio
repository: a reviewer who has to create an account and attach a card before
seeing anything will see nothing. Second, the predecessor project
([production-rag](https://github.com/pabloalvarez99/production-rag)) already
established that a credential-free path is achievable end to end — deterministic
embedder, deterministic generator, CI green with every provider key set to the
empty string — so the question here is not whether it is possible but whether
this project keeps the property.

The scaffold at M0 reads no credential at all. This record fixes what happens as
the loop lands, before the first call site exists to argue about.

## Decision

**The deterministic free path is the default, and it stays the default. A hosted
provider is an opt-in override that a reviewer never has to exercise.**

Concretely:

1. **The retrieval boundary is one interface with two implementations.** The loop
   depends on `RetrievalBackend`, and cannot tell a fake from a real service.
   `FakeRetrievalBackend` — an in-process fixture over a small committed corpus,
   deterministic for a given sub-question — is what is constructed when nothing
   is configured.
2. **Planning and critique default to deterministic implementations.** No hosted
   model is contacted to run the loop, the tests, or the demo.
3. **The default construction path reads no credential.** Not "reads it and finds
   it empty" — a defaulted-to-free code path that still looks for a key
   eventually finds one in someone's shell and starts billing without a decision
   being made.
4. **CI runs with provider keys set to the empty string.** Same rule as the
   predecessor project: if a change makes any default path require a credential,
   CI goes red instead of a reviewer discovering it after cloning.
5. **The paid path lands after the loop is complete on the free path** — the
   milestone order in [architecture.md](../architecture.md), where M1 through M3
   (retrieve, loop, budget, trace, API and CLI) need no credential or running service.
   M4 introduces opt-in HTTP while preserving fake defaults; hosted providers remain
   outside the default path.
6. **Every billed run is explicit at the call site and labelled in its output.**
   A number produced by a hosted provider is published with its providers, its
   sample size, its date and its commit; a number produced by fakes is labelled
   as plumbing and carries no evidentiary weight.

## What the fake is allowed to prove, and what it is not

This is the boundary that keeps "fake first" from becoming self-deception. The
fake is a fixture, not a simulation of retrieval quality.

**It can prove:** the control flow terminates; the step budget is enforced; the
stop rule fires where it should; the refusal path is reachable and produces a
reason; a sub-question that narrows the topic retrieves different passages than
the original question did; the trace is complete enough to diagnose a run after
the fact; every citation resolves to a passage that exists.

**It cannot prove anything about quality:** not retrieval quality, not ranking
quality, not answer quality, and above all not the one claim this project exists
to make — that the agent finds better evidence than a single pass. Deciding that
needs the real retrieval service against a real corpus, a question set the single
pass provably cannot answer, and a paired comparison under the predecessor's
reporting boundary.

A loop that is green against the fake is a loop worth spending money on. It is
not a result.

## Alternatives considered

**Hosted providers from the first commit, with the free path added later.** The
loop would be judged against real model behaviour immediately, and planning
quality is exactly the part a deterministic stand-in cannot mimic. Rejected on
two grounds. It makes the repository unrunnable for its actual audience — a
reviewer with no key — and "added later" is where credential-free paths go to
die: once every test needs a key, making them not need one is a refactor nobody
schedules. The predecessor project demonstrated the opposite order works.

**Record and replay hosted responses (a cassette library).** Real model output,
replayed for free, no key needed after the first recording. Rejected as the
default, though it remains attractive for a later hosted-provider evaluation. Cassettes are recorded against a
prompt; the loop's prompts change during early milestones, so the
recordings would be stale continuously and a stale cassette fails in a way that
looks like a code bug. It also requires a key to record, which puts a credential
back on the contribution path. Revisit when the prompts stabilise.

**One provider, configured, with fakes only inside unit tests.** Simpler: no
second implementation of the retrieval boundary, no fixture corpus to maintain.
Rejected because it makes the demo and the evaluation harness the two things a
reviewer cannot run, which are the two things worth reading. It also removes the
seam that makes the loop's control flow testable at all — the interface exists
for the fake as much as for the service.

**No fake retrieval; run the real service in Docker for everything.** The
predecessor ships a Compose stack, so this is not unreasonable, and it tests
against real retrieval behaviour. Rejected as the default for the loop's own
tests: it makes the unit suite depend on a container, which turns a fast test
run into an integration run and Docker into a prerequisite. It stays the right
answer for opt-in M4 integration and M5 evaluation, where retrieval behaviour is
the subject rather than the substrate.

## Consequences

**Accepted costs.** Two implementations of the retrieval boundary to keep in
step, plus a small committed fixture corpus. Deterministic planning and critique
mean the loop's *reasoning* quality is unmeasured until the paid path opens — the
free path validates mechanism, not judgement, and this record says so rather than
letting a green suite imply otherwise. Some real failure modes (a model ignoring
the plan format, a critique that rationalises thin evidence) will not appear
until a hosted-provider path is exercised.

**Bought properties.** A reviewer runs the whole loop from a clone. The test
suite is offline, fast, and deterministic, so a flaky run is a real bug. Cost
regressions are structurally impossible on the default path, because it has no
billed call to regress. And when the paid path opens, the loop's mechanism is
already proved, so the first billed runs measure the thing they are supposed to
measure instead of debugging control flow at provider prices.

**The condition for opening the paid path**, stated so it is checkable rather
than a matter of readiness: M1 through M4 landed and green on the free path, the
retrieval boundary unchanged by the addition, and a question set with a
mechanical argument that the single pass cannot answer it. Until then, a hosted
call in this repository is a bug in the default path.
