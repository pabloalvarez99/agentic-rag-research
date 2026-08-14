# Case study — proving an agent loop before paying for one

<p align="center">
  <a href="https://github.com/pabloalvarez99/production-rag"><img src="https://img.shields.io/badge/P1-production--rag-0ea5e9" alt="P1 production-rag" /></a>
  <a href="https://github.com/pabloalvarez99/agentic-rag-research"><img src="https://img.shields.io/badge/P2-agentic--rag-a78bfa" alt="P2 agentic-rag" /></a>
  <a href="https://github.com/pabloalvarez99/multi-agent-orchestration"><img src="https://img.shields.io/badge/P3-multi--agent-22c55e" alt="P3 multi-agent" /></a>
  <a href="https://github.com/pabloalvarez99/repomind"><img src="https://img.shields.io/badge/P4-repomind-f59e0b" alt="P4 repomind" /></a>
  <a href="https://github.com/pabloalvarez99/ai-platform"><img src="https://img.shields.io/badge/P5-ai--platform-6b7280" alt="P5 ai-platform" /></a>
</p>

## Problem

A single RAG pass can retrieve and answer, but a research question may contain several
sub-questions, miss on its first wording, or need another retrieval after critique. Adding an
"agent" is easy; proving that the extra loop adds value without hiding cost or failure is the
hard part.

The design goal for P2 is therefore narrower than autonomous research: produce an end-to-end
research JSON result with citations, bounded tool use, explicit stop reasons, and a trace a
reviewer can audit — from a clean clone and without an API key.

## Options considered

| Option | Advantage | Cost / risk |
| --- | --- | --- |
| Hosted model and live retrieval from day one | Real model behavior immediately | Paid, flaky, hard to reproduce, inaccessible to reviewers without keys |
| A tutorial-style unbounded agent | Small amount of code | No defensible termination or cost ceiling; failures become timeouts |
| Copy P1 retrieval into P2 | One repository appears self-contained | Duplicates the baseline and invalidates agent-vs-single-pass comparisons |
| Deterministic loop behind protocols | Offline, replayable, tests exact decisions | Proves mechanism only; quality remains unmeasured |

## Decision

Build fake-first, with one read-only `retrieve` tool and the retrieval service behind a second
protocol. Enforce the step budget inside the run state, never retrieve the same sub-question
twice, and decide terminal outcomes through one pure function. Keep HTTP to production-rag
opt-in and fail closed when it was explicitly requested but unavailable.

The three architectural decisions are recorded separately:

- [ADR-0001](adr/0001-fake-first.md): free path first and the boundary of fake evidence.
- [ADR-0002](adr/0002-step-budget.md): termination and honest stop reasons.
- [ADR-0003](adr/0003-tool-boundary.md): one read-only tool and two protocol seams.

## Result at M3

The same loop is reachable as a Python library, `POST /v1/research`, and a machine-readable
CLI. It can finish with grounded findings, explicitly refuse, or return a partial grounded
report when the budget ends. Every run records plan creation, tool calls/results, critique,
synthesis, and stop.

The default backend reads committed Markdown and contacts nothing. The optional HTTP adapter
maps production-rag citations into the same `Passage` contract, so the loop does not change
when the retrieval substrate changes. HTTP failures become typed transport errors at the API
and CLI boundary, not fake refusals.

## Evidence and limitations

The offline suite verifies contracts, state transitions, refusal, budget enforcement, API/CLI
parity, and the HTTP adapter through a mock transport. M5 adds a synchronized 17-case
golden dataset and a deterministic JSON scorecard across five behavior slices.

There is intentionally no quality claim here. Lexical fake retrieval cannot establish that
planning improves retrieval or that the report is useful. M5 measures terminal behavior,
steps, citations, source diversity, and gaps against curated fixture expectations; a quality
claim still requires an HTTP-backed run on a real corpus, a one-pass answer baseline, named
providers, paired results, sample size, and uncertainty. The defensible result is: **the
mechanism is runnable, bounded, inspectable, and its evaluation contract is executable.**

## What the UI proves

The argument above is about mechanism, and mechanism is invisible in a JSON blob nobody
runs. Three committed captures, rebuilt from a live server by
[`scripts/capture_ui.py`](../scripts/capture_ui.py), show it:

- [`ui-done.png`](assets/ui-done.png) — a run that finished. The status, the retrieval
  steps it spent, and every citation marker resolving to a passage that was retrieved.
  The claim "no marker without a passage" is a thing you can read off the page.
- [`ui-trace.png`](assets/ui-trace.png) — the same UI with the trace expanded, on a
  two-hop question whose first sub-question retrieves nothing. `plan_created`, both
  retrieval steps, the `critique` arithmetic that chose to continue, `synthesize`, and
  the terminal `stop`. The plan, not a retry, is what reached the evidence.
- [`ui-budget.png`](assets/ui-budget.png) — the budget ending a run. Status
  `budget_exhausted` with reason `budget_spent`, a partial grounded report, and the terms
  no retrieved passage covered. The step budget lives in the run state, so the ceiling is
  visible in the trace instead of being an implicit property of the loop's condition.

They also re-state the boundary rather than blurring it: the captures are produced on the
deterministic fake retriever with `PRODUCTION_RAG_URL` cleared, the form pins
`retriever=fake`, and the optional P1 HTTP path stays opt-in and fail-closed. They are
evidence of contract, budget, and traceability — **not** of retrieval or answer quality.

Reproducibility is part of the point: the viewport and questions are pinned and the
correlation id is supplied per capture, so a rebuild is byte-identical and
`python scripts/capture_ui.py --verify` fails on drift rather than quietly publishing a
different run.

## v0.2 — notes store, run artifacts, streaming, control scorecard

Three weeks of depth turned the free path into something a reviewer can audit without
re-running anything and without a model key.

### Notes are a store (Week 1)

A run writes typed `Note` records `{id, claim, source, context?, citation?}` and traces
every write. The critic scores grounded, on-topic notes (overlap + presence), not
`len(passages)`. The free-path critic is deliberately not an LLM: the arithmetic is in
the trace, the same question under the same budget is byte-identical, and CI needs no
credential. Rationale: [ADR-0004](adr/0004-notes-are-a-store.md).

### A run is an artifact (Week 2)

Finished runs are stored in-process under their correlation id (last N, oldest evicted).
`GET /v1/runs/{id}` returns report, citations, notes, steps used, stop reason, and
trace. `GET /v1/runs/{id}/trace.json` is the download the UI links to. `GET
/v1/research/stream` emits SSE `trace` events with stable offsets (not wall clock), then
a terminal `done` or `error`. Final statuses remain `done | refused | budget_exhausted |
degraded`.

### Evals measure control (Week 3)

The golden scorecard reports steps used, stop-reason distribution, citation presence, and
`refused_unanswerable` — never answer quality and never "beats GPT". Optional HTTP
adapter tests stay gated on `RUN_P1_INTEGRATION=1` + `PRODUCTION_RAG_URL` pointing at a
local free stack; CI keeps them skipped and never points at a production-rag Vercel host.

### 10-minute hosted DEMO (v0.3)

Host: <https://pax-agentic-rag.vercel.app> — fixture retriever only; **control demo, zero
quality claim**. Project remains **`pax-agentic-rag`** (no second Vercel project).

1. Open `/` (or `/docs`). Confirm honesty copy: free / deterministic, no API key.
2. **Refused run.** Ask something off-corpus, e.g. `What were the quarterly revenues in
   Patagonia?`, budget 3. Expect status `refused`, stop reason `no_evidence` or
   `insufficient_evidence`, a report that names gaps, and no invented facts.
3. **Download the full run** immediately: `GET /v1/runs/{id}/run.json` (or the UI
   "Download full run" link). After a recycle the id is gone; the file is the source of
   truth.
4. **Answerable control.** Ask `Why do bounded research agents need explicit stop
   reasons?` (or the form default). Expect `done`, citations, and a trace that includes
   `plan_created` → `tool_*` → `note_added` → `critique` → `stop`. Download that run too.
5. **Compare.** Open `/compare`, load the two JSON files, read stop reason / steps /
   notes / citations side by side. The typed diff is `POST /v1/runs/compare` on payloads,
   not server ids ([ADR-0005](adr/0005-compare-on-payloads.md)).
6. **Stream.** With JS on, steps append live from `GET /v1/research/stream` (offsets, not
   timestamps). Without JS, `POST /ui/research` still renders the full page.
7. **curl the same contract** (or `pwsh scripts/hosted_smoke.ps1`).

```bash
# answerable (fixture path)
curl -sS -X POST https://pax-agentic-rag.vercel.app/v1/research \
  -H "content-type: application/json" \
  -H "x-request-id: demo-done" \
  -d "{\"question\":\"Why do bounded research agents need explicit stop reasons?\",\"max_steps\":4,\"retriever\":\"fake\"}"

# download full run (compare input)
curl -sS -OJ https://pax-agentic-rag.vercel.app/v1/runs/demo-done/run.json

# refused
curl -sS -X POST https://pax-agentic-rag.vercel.app/v1/research \
  -H "content-type: application/json" \
  -H "x-request-id: demo-refused" \
  -d "{\"question\":\"What were the quarterly revenues in Patagonia?\",\"max_steps\":3,\"retriever\":\"fake\"}"

curl -sS -OJ https://pax-agentic-rag.vercel.app/v1/runs/demo-refused/run.json

# compare payloads (not ids)
curl -sS -X POST https://pax-agentic-rag.vercel.app/v1/runs/compare \
  -H "content-type: application/json" \
  -d "{\"left\":$(cat run-demo-done.json),\"right\":$(cat run-demo-refused.json)}"

# stream (SSE)
curl -sSN "https://pax-agentic-rag.vercel.app/v1/research/stream?question=Why%20use%20citations%20in%20RAG%3F&max_steps=4&retriever=fake"
```

Honesty bound: serverless instances do not share the in-memory run store; fetch or
download immediately after the run. Prefer the downloaded JSON for compare — that is why
compare takes payloads, not ids.

## v1.0 — from demo loop to experiment lab

v0.3 proved the mechanism on a hosted free path. v1.0 answers a different interviewer
question: **is this a lab you can re-run, or a graph you demo once?** The season plan in
[SEASON.md](SEASON.md) froze fifteen invariants before code moved: budgets in state,
critic can lose, compare on payloads, fixture retriever, no live web, and a control
eval floor of **n ≥ 40**.

### Experiment records

A finished run is already a full artifact. An **experiment record** is the compact lab
line: `id`, `seed`, `budget` (global steps + per-tool `max_calls`), `note_ids`,
`stop_reason`, optional `pack_hash`, plus tool-call counts and status. Scorecards and
packs can cite the record without re-opening every passage. The free path stays
deterministic at seed 0; the field exists so later seeded planners do not rewrite the
schema.

### Control goldens at n ≥ 40

The committed set grew from 18 to **48** cases without softening
`critic-notes-exist-not-success`. Slices cover answerable single/multi hop, unanswerable,
thin/off-topic notes, budget stress, and **tool_budget**. Difficulty predicates in the
loader fail closed when a slice is all-trivial (for example, unanswerable never expects
`done`; thin never expects `done`; tool_budget must include `tool_budget_spent`). Metrics
remain **control**: pass rate, stop-reason distribution, citation presence, refused
unanswerable rate — with `billed_usd = 0`. They still do not claim answer quality or
uplift over a single pass.

### Three tools is not a platform

v1 free path exposes exactly three tools: `retrieve`, `search_notes`, and fixture
`lexicon`. Each has `max_calls` in state; exhaustion is `tool_budget_spent`, not a hang.
Planner, critic, and synthesizer remain pure functions. [ADR-0006](adr/0006-three-tools-not-a-platform.md)
records why this is not a plugin registry, multi-tenant sandbox, or live-web research
agent. The third tool exists to exercise budgets and traces, not to invent capabilities.

### Experiment packs

An experiment pack is a directory or zip of policy, two full run payloads, compare
diff, experiment lines, and a content `pack_hash`. UI `/pack` and `POST /v1/experiments/pack`
load payloads only — still no server-id lookup after recycle. Round-trip tests recompute
compare and refuse a hash mismatch. Files remain the source of truth; the pack is how
you hand a lawyer or hiring manager two runs and the policy that produced them.

### Load honesty

[`docs/assets/load.json`](assets/load.json) records **50** free-path researches in one
process: p50/p95 latency, cold-start ms, hardware, status counts, and an explicit label
that this is **not** production capacity planning. Fixture only, billed false. That is
the opposite of a vanity throughput claim on a multi-region fleet.

### What is still PLANNED

Durable multi-instance storage, live web tools, default paid LLM planner/critic, hosted
HTTP-P1 without a captain-configured URL, Tier-2 faithfulness judges in CI, and any
claim that three tools make an agent platform. v1.0 ships the lab, not the SaaS.

### 15-minute DEMO (v1.0)

Host remains **only** <https://pax-agentic-rag.vercel.app> / project `pax-agentic-rag`.

1. Health + honesty copy on `/`.
2. Refuse off-corpus (Patagonia / Antarctic chess). Download `run.json`.
3. Critic-can-lose story: notes exist is not success (scorecard golden).
4. Answerable control with citations; download second run.
5. `/compare` on the two files (payloads, not ids).
6. `/pack` — build pack, show `pack_hash` and compare.
7. Optional: curl tool-budget request or show load.json numbers and CASESTUDY trade-offs.
8. `pwsh scripts/hosted_smoke.ps1` as the transcriptable contract.

## What I would test next

1. Add a one-pass answer baseline over the same fixed goldens.
2. Publish per-case paired deltas before aggregates.
3. Exercise the HTTP adapter against P1's free stack, including refusal and dependency-down.
4. Add wall-clock and spend ceilings only when a hosted path creates those costs.
5. Revisit a graph framework only when checkpoint/resume or parallel fan-out is required.
6. Grow tool_budget goldens further once a planner can deliberately request lexicon under
   stress without changing critic-can-lose discipline.

