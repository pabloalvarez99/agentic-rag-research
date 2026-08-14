# Season plan — agentic-rag-research toward v1.0

**Status:** Month 1 · Week 1 design only (this file)  
**Baseline:** `main@dc80188` · release **v0.3.0** · hosted **https://pax-agentic-rag.vercel.app** (Vercel project **`pax-agentic-rag` only**)  
**Branch / worktree:** `a6/p2-v1-season` · `C:\dev\portfolio-workers\a6-p2-v1-season`  
**Horizon:** ~90 days · three months · **`REPORTE … OK` is illegal before the Month 3 gate**  
**Authority:** portfolio master plan §7 (P2), §12 (eval doctrine), §33 (failure taxonomy); dispatch `2026-08-14-v1-season`

This document is the lab ledger for the quarter. It freezes threat model, invariants, eval growth, tool-protocol shape, experiment metadata, pack contract, load honesty, and the v1.0 checklist. **Week 1 ships only this design.** Weeks 2–4 implement Month 1 surfaces; Months 2–3 follow only after the prior month’s quantitative doors close.

---

## 1. Mission for the quarter

v0.3.0 already proves a **bounded research loop**: plan → retrieve → note → critique under step budget, typed notes, payload compare (not server ids), critic-can-lose golden, 18/18 free-path control scorecard, hosted fixture-only demo on `pax-agentic-rag`.

A staff interviewer will still ask:

1. Is this a **lab** (reproducible experiments) or a one-off demo graph?
2. Can you grow **control evals** without weakening refusal discipline?
3. Are tools a **protocol with budgets**, or an unbounded “agent platform” slide?
4. After serverless recycle, what is still true?

**Season answer:** turn P2 into an **experiment lab** — every run is an experiment record; goldens grow to **n ≥ 40** with difficulty slices; three tools remain **fake-first** with per-tool budgets and typed exhaustion; an **experiment pack** round-trips two runs + compare diff + policy for UI and tests; load numbers are honest single-isolate notes; CASESTUDY ≥ 1500 words; release **v1.0.0** only when the checklist is green. No second Vercel project. No OpenAI requirement. No live-web research claim.

---

## 2. What is already LIVE (do not regress)

| Surface | Evidence on baseline |
| --- | --- |
| Fake-first free path | ADR-0001; CI empty keys |
| Step budget in state | ADR-0002; `ResearchState` + `budget_exhausted` / `budget_spent` |
| Tool boundary + retrieve | ADR-0003; optional HTTP P1 opt-in, CI skipped when unset |
| Typed notes store; critic on evidence quality | ADR-0004; notes present ≠ success |
| Compare on full payloads | ADR-0005; `/compare` UI; `POST /v1/runs/compare` |
| Run download | `GET /v1/runs/{id}/run.json` (id dies after recycle; file remains truth) |
| Goldens | `data/eval/golden_research.jsonl` **n = 18**, six categories, `billed=false` free path |
| Critic-can-lose | `critic-notes-exist-not-success` → `refused` + `insufficient_evidence` |
| Hosted | `pax-agentic-rag.vercel.app` health/UI/research/metrics; fixture retriever only |
| HTTP retriever | `PRODUCTION_RAG_URL` opt-in; never default; **never** `https://production-rag.vercel.app` (Ipsura) |

**Sibling project `agentic-rag-research` on Vercel is not prod.** Prod is **`pax-agentic-rag`**. Do not promote the sibling.

---

## 3. Threat model (lab, not product SaaS)

| Threat | Failure mode | Season control |
| --- | --- | --- |
| T1 Unbounded loop | Hang / bill / CI timeout | Budgets in state; typed stop (I1–I3, I10) |
| T2 Length-as-quality | Off-topic notes count as success | Critic scores grounded/on-topic claims (I4); never weaken `critic-notes-exist-not-success` |
| T3 Id-as-durability | Compare/GET after recycle 404 | Payloads/files are source of truth (I5–I6) |
| T4 Live-web fiction | “Agent researches the web” | Fixture corpus only on free path (I7–I8) |
| T5 Secret / paid default | Clone needs OpenAI | Free path default; billed=false control (I9, I15) |
| T6 Tool sprawl as platform | Infinite tools, no budgets | Exactly three tools in v1; each has `max_calls` (I10–I12); ADR Month 2 |
| T7 Silent tool hang | Exhausted tool blocks forever | Exhaust → typed stop reason, not retry forever (I11) |
| T8 Eval theater | n small / all easy rank-1 | n≥40; slices; difficulty predicates (I13–I14) |
| T9 Wrong host / URL | Demo on Ipsura or sibling Vercel | Host table fixed to `pax-agentic-rag` (I15) |
| T10 Trace amnesia | Tool call without record | Every tool call/result in trace (I12) |

---

## 4. Fifteen invariants

Each invariant is **normative**. Column **Test now** = enforced on baseline `dc80188`. **Season** = Month when the remaining proof lands if not already green.

| # | Invariant | Test now | Season proof |
| ---: | --- | --- | --- |
| **I1** | Step budget lives in `ResearchState`; steps never exceed `max_steps`. | Yes (unit + loop) | Month 1 characterization stays |
| **I2** | Every finished run has exactly one terminal status from `{done, refused, budget_exhausted, degraded}` and one closed-set `stop_reason`. | Yes | Month 1–2: new stop reasons for per-tool exhaust stay closed-set |
| **I3** | Duplicate sub-question retrieval is rejected; progress cannot burn the whole budget re-asking the same thing without a distinct stop story. | Yes (ADR-0002) | Keep; scorecard includes budget pairs |
| **I4** | **Critic can lose:** notes present but off-topic / insufficient ⇒ not `done`. Golden `critic-notes-exist-not-success` must remain `refused` + `insufficient_evidence`. | Yes | **Never weaken.** Month 1 grows siblings in `thin_evidence` / off-topic slice, same discipline |
| **I5** | Compare is payload-based: `POST /v1/runs/compare` never resolves server ids. | Yes (ADR-0005) | Month 3 pack embeds compare diff of payloads |
| **I6** | After serverless recycle, **downloaded JSON (or pack files) remain the source of truth**; in-memory run ids may vanish. | Partial (docs + download route) | Month 1 hosted compare + refuse **transcripts**; Month 3 pack UI load without ids |
| **I7** | Default retriever is the **fixture** (`fake`); no live web crawl. | Yes | Entire season free path |
| **I8** | HTTP P1 retriever is **opt-in** via `PRODUCTION_RAG_URL`; default CI **offline** / skips live slice; unset or wrong host fails closed (`capability_missing` / skip), never silent invent. | Yes | Month 2 OpenAPI + hosted_smoke stay opt-in |
| **I9** | Free-path scorecard reports **`billed=false`** (or equivalent zero billed cost); control metrics are not quality SOTA. | Yes | Month 1 n≥40 keeps billed 0 |
| **I10** | Each tool has a **per-tool `max_calls`** in state (global step budget remains). Exhausting a tool produces a **typed stop**, not a hang. | No (only global steps) | **Month 2** |
| **I11** | Tool set for v1 is exactly **three** fake-first tools: `retrieve`, notes (`search_notes` / note store ops as today), plus **one** fixture lexicon/lookup tool with its own budget. | Partial (retrieve + notes) | **Month 2** third tool + ADR |
| **I12** | Every tool call and tool result is a **trace event** (`tool_call` / `tool_result`); pack and compare can see call counts. | Yes for current tools | Month 2 extends to lexicon tool |
| **I13** | Control goldens **n ≥ 40** with named slices and a **mechanical difficulty predicate** per slice (a test fails if a slice is all trivial). | No (n=18) | **Month 1 weeks 2–4** |
| **I14** | Experiment record is first-class: `{id, seed, budget, note_ids, stop_reason, pack_hash}` (plus question / status / tool call counts as needed). | No | **Month 1** record schema + tests; Month 3 pack hash |
| **I15** | Production demo host is **only** `https://pax-agentic-rag.vercel.app` / project `pax-agentic-rag`. Never claim Ipsura; never create a new Vercel project; never set `PRODUCTION_RAG_URL=https://production-rag.vercel.app`. | Process + docs | Hosted smoke + SEASON + SHIP |

### Explicit non-invariants (do not “prove” these)

- Answer quality, faithfulness, or model uplift (Tier-2 judges are optional and out of free CI).
- Multi-tenant durable server storage, Redis, object stores for runs.
- Live web research, browser tools, or OpenAI-required demos.
- That three tools make this an “agent platform” (Month 2 ADR argues the opposite).
- Production capacity planning from a single Vercel isolate load test.

---

## 5. Eval plan — control goldens n ≥ 40

### 5.1 Doctrine (master plan §12)

| Tier | Season role |
| --- | --- |
| **0 Ops** | stop_reason distribution, tool errors, refuse rate, budget exhaust rate |
| **1 Control / task** | free CI every PR: status, stop_reason, steps, citation bounds, critic-can-lose, tool budgets |
| **2 Quality judge** | **out of scope** for free CI; never block clone |

Tier-1 never requires paid APIs. Metrics label **control**, not quality.

### 5.2 Baseline (n = 18)

| Category | n | Purpose |
| --- | ---: | --- |
| `answerable_single_hop` | 4 | Grounded done path |
| `answerable_multi_hop` | 3 | Plan + multi retrieve |
| `unanswerable` | 4 | Refuse, no invented citations |
| `thin_evidence` | 3 | Including **critic-can-lose** |
| `budget_stress` | 4 | Paired low budget vs full |

### 5.3 Target (n ≥ 40) — Month 1 weeks 2–4

Grow **without** deleting or softening existing cases. Target mix (minimums; total ≥ 40):

| Slice id | Min n | Expected discipline | Difficulty predicate (mechanical) |
| --- | ---: | --- | --- |
| `answerable` (single + multi) | ≥ 10 | `done` + citations from real chunk ids | At least 40% of slice requires **≥ 2** retrieve steps **or** multi-hop category; test fails if every case has `steps_used == 1` and single-hop only |
| `unanswerable` | ≥ 8 | `refused` + `no_evidence` or `insufficient_evidence`; **max_citations = 0** for pure no-evidence | Questions must **not** match high-overlap corpus terms for ≥ 50% of the slice (token overlap threshold documented in loader); test fails if any unanswerable expects `done` |
| `off_topic_notes` / thin + critic-lose | ≥ 6 | Notes may exist; status **≠ done**; includes `critic-notes-exist-not-success` and ≥ 2 variants | Predicate: fixture or harness injects / expects notes whose claim tokens fail question coverage; test fails if any case in slice expects `done` |
| `budget` | ≥ 8 | Low `max_steps` ⇒ `budget_exhausted` or early refuse; pairs share `pair_id` | ≥ 50% of slice has `max_steps ≤ 1` or paired high/low budget with **different** terminal status or stop_reason; test fails if all budget cases share one status |
| `tool_budget` (Month 2 fill) | ≥ 4 | Per-tool exhaust typed stop | Case sets `max_calls` for one tool below needed work; expects non-hang terminal + stop_reason in closed set |
| **Total** | **≥ 40** | `pass_rate` 1.0 on free path; `billed=false` | Loader rejects missing slices / duplicate ids |

**Required forever:** `critic-notes-exist-not-success` remains in the file and green. Adding goldens must not change its expect block to success.

### 5.4 What we do **not** measure (honesty)

- Semantic answer quality or human preference.
- Latency as a product SLA (load is a separate Month 3 artifact).
- HTTP-P1 retrieval quality when URL is unset (slice skipped).
- “Agent beats single-pass RAG” without a paired baseline study (optional later; not v1.0 gate).

### 5.5 Runner / scorecard

Keep `python -m agentic_rag.evals.run` as the free control harness. Month 1 extends dataset schema only as needed for `slice` / difficulty tags if categories alone are insufficient — prefer extending `category` + loader checks over a parallel format. Publish pass_rate, status_counts, stop_reason_counts, refused_unanswerable_rate, mean_steps_used. Label report: **control scorecard, fixture lexical corpus, not production research quality.**

---

## 6. Experiment record (Month 1 product surface)

### 6.1 Schema (normative)

Every finished research run that participates in the lab should be representable as:

```json
{
  "id": "exp_<stable or request_id>",
  "seed": 0,
  "question": "...",
  "budget": {
    "max_steps": 4,
    "max_calls": { "retrieve": 4, "search_notes": 2, "lexicon": 2 }
  },
  "note_ids": ["n_…", "n_…"],
  "status": "done|refused|budget_exhausted|degraded",
  "stop_reason": "evidence_sufficient|no_evidence|insufficient_evidence|budget_spent|tool_budget_spent|…",
  "tool_calls": { "retrieve": 2, "search_notes": 1, "lexicon": 0 },
  "pack_hash": null,
  "trace_event_count": 12,
  "retriever": "fake"
}
```

| Field | Rule |
| --- | --- |
| `id` | Stable for fixtures; may equal `request_id` for live runs |
| `seed` | Integer; free path remains deterministic for seed 0 / default planner |
| `budget` | Must match state bounds used for the run |
| `note_ids` | Ordered ids from the note store for that run |
| `stop_reason` | Closed set; new Month 2 reasons added by ADR + schema together |
| `pack_hash` | SHA-256 of experiment pack bytes when the run is part of a pack; else null |
| Serialization | JSON; byte-stable key order in tests where we already freeze compare |

### 6.2 Implementation order (not Week 1)

1. Pydantic model + round-trip tests from a finished `ResearchState` / run artifact.
2. Optional field on run JSON download (additive).
3. Eval harness can emit experiment records beside scorecard rows.
4. Month 3: pack embeds two records + compare + policy; `pack_hash` fills in.

---

## 7. Month plan

### Month 1 — Lab ledger (this design → records + n≥40)

| Week | Deliverable | Stop condition |
| --- | --- | --- |
| **1** | **`docs/SEASON.md` only** (this file). Commit. **No Month 2 implementation in that commit.** | Design committed |
| **2** | Experiment record type + tests; export on run artifact if additive | Model green in CI |
| **3** | Grow goldens toward n≥40; difficulty predicates; do not weaken critic-can-lose | Scorecard still 1.0 on free path |
| **4** | Hosted **compare + refuse** HTTP transcripts archived under `docs/assets/` or `work/` via vault cli-log pointer; finish n≥40; OpenAPI only if record field needs it | Month 1 door: n≥40, I1–I9 + I13–I15 progress, transcripts |

**Month 1 exit criteria (not OK for season):**

- [ ] SEASON.md merged or on branch with 15 invariants
- [ ] Experiment record schema implemented + tested
- [ ] Goldens **n ≥ 40**, slices + difficulty tests green
- [ ] `critic-notes-exist-not-success` still refuses
- [ ] Hosted transcripts: refuse path + compare payloads (files, not ids)
- [ ] Digest append for the month

### Month 2 — Tools as a protocol

1. **Tools:** `retrieve`, notes (`search_notes` / note store as today), **+ one** fake **lexicon/lookup** tool over the fixture (definitions / term → passage ids). No network.
2. **Per-tool `max_calls` in state.** Exhaust ⇒ typed stop (`tool_budget_spent` or equivalent closed-set reason), **not** a hang.
3. Trace every call (I12).
4. **OpenAPI complete** for research, stream, runs, compare, any new tool-budget fields.
5. **`scripts/hosted_smoke.ps1`** updated; default CI remains offline.
6. **ADR-0006 (name TBD):** why three tools is still **not** an agent platform (no planner marketplace, no plugin sandbox, no multi-tenant tool registry, budgets + fixture scope).

**Month 2 exit criteria:**

- [ ] Three tools live on free path
- [ ] Per-tool budgets tested (exhaust → typed stop)
- [ ] OpenAPI + hosted_smoke updated
- [ ] ADR accepted
- [ ] Goldens include `tool_budget` slice (≥ 4); total still ≥ 40
- [ ] Digest append

### Month 3 — Experiment pack + v1.0

1. **Pack format:** directory or archive with:
   - `policy.json` (budgets, tool max_calls, retriever=fake, season version)
   - `run_a.json` + `run_b.json` (full payloads)
   - `compare.json` (output of payload compare)
   - `manifest.json` (`pack_hash`, schema version, experiment ids)
2. **UI:** load pack (or the two runs + show embedded diff); still no server-id dependency.
3. **Round-trip tests:** pack → load → compare equals stored diff; billed 0.
4. **Load:** 50 fake researches local or against hosted free path; publish p50/p95, n, hardware/region, cold-start note; label **single isolate, not capacity planning**.
5. **CASESTUDY ≥ 1500 words** (expand existing): lab vs demo, critic-can-lose, compare-on-payloads, three-tool non-platform, what remains PLANNED.
6. **DEMO ~15 min** on **pax-agentic-rag only**: refuse, critic-lose story, compare files, pack load, budget exhaust.
7. **`gh release create v1.0.0`** only if checklist green. Do not retag v0.3.0. Release notes list PLANNED.

**Month 3 / season OK gate:** full checklist in §10.

---

## 8. Three-tool protocol (design; implement Month 2)

| Tool | Input | Output | Default max_calls | Must not |
| --- | --- | --- | --- | --- |
| `retrieve` | sub-question, top_k | passages + chunk ids | = `max_steps` unless lower | Plan, synthesize, call HTTP unless retriever=http |
| `search_notes` (notes) | query over run notes | ranked notes | small (e.g. 2–4) | Retrieve from corpus; invent notes |
| `lexicon` (new) | term / symbol | fixture definition + optional chunk ids | small (e.g. 2) | Live web; unpaid synonym APIs |

**Loop ownership:** planner / critic / synthesizer remain **not tools** (ADR-0003). Tools are read-only evidence surfaces with budgets.

**Stop interaction:**

- Global steps exhausted → existing `budget_exhausted` / `budget_spent`.
- Tool calls exhausted while steps remain → new typed reason; run must still terminate with report or refuse, never spin.
- Critic sufficiency still uses notes quality (I4), not tool call count.

---

## 9. Experiment pack (design; implement Month 3)

```
experiment-pack/
  manifest.json      # schema_version, pack_hash, created_with
  policy.json        # budgets, tools, retriever, season_tag
  run_a.json         # full RunArtifact / research response
  run_b.json
  compare.json       # POST /v1/runs/compare result for (a,b)
  experiments.jsonl  # optional: ExperimentRecord lines for a and b
```

**UI contract:** user loads pack (or selects pack folder / zip); UI shows policy summary, side-by-side status/stop/steps, and precomputed or recomputed diff. Recompute must match stored compare when inputs unchanged (byte-stable fields per ADR-0005).

**Tests:** identical runs → empty diffs; done vs refused → field diffs; pack round-trip; missing file → typed error.

---

## 10. v1.0.0 checklist (season OK requires all)

- [ ] This `docs/SEASON.md` lists 15 invariants and which have tests
- [ ] Control goldens **n ≥ 40**, slices + difficulty predicates, free path `billed=false`, pass_rate 1.0
- [ ] Critic-can-lose golden still refuses
- [ ] Experiment record schema LIVE
- [ ] Three tools + per-tool budgets + typed exhaust
- [ ] OpenAPI complete; CI green with empty keys; HTTP P1 opt-in skipped in CI
- [ ] Hosted smoke script; transcripts of refuse + compare
- [ ] Experiment pack + UI load + round-trip tests
- [ ] Load artifact: 50 fake researches, p50/p95, cold-start note, honesty label
- [ ] CASESTUDY ≥ 1500 words, real trade-offs, no invented SOTA
- [ ] DEMO 15 min script on **pax-agentic-rag only**
- [ ] Failure artifacts: refuse / budget / (tool budget) not only happy path
- [ ] Release notes v1.0.0 list what is still **PLANNED**
- [ ] No new Vercel project; prod remains `pax-agentic-rag`
- [ ] Tag **v1.0.0** only once checklist is green

---

## 11. Still PLANNED after v1.0 (honesty list)

- Durable multi-instance run storage (DB / object store)
- Live web tools, browsers, or paid LLM planner/critic as default
- Hosted HTTP-P1 retrieval without captain-configured URL
- Tier-2 faithfulness judges in CI
- Claiming multi-tenant SaaS readiness or production capacity from p50/p95 on one isolate
- Agent plugin marketplace / unrestricted tool registry
- Second Vercel project or domain migration

---

## 12. Failure taxonomy mapping (master plan §33)

| Code | P2 meaning this season |
| --- | --- |
| `no_evidence` | Empty / off-corpus → refuse |
| `insufficient_evidence` | Notes/gaps insufficient; critic-can-lose path |
| `budget_exhausted` / `budget_spent` | Global step budget |
| `tool_budget_spent` (new) | Per-tool max_calls exhausted |
| `capability_missing` | HTTP retriever requested without usable P1 |
| `backend_unavailable` | Opt-in HTTP backend down → typed degrade/error, not invent |
| `validation_error` | Bad request 422 |
| `provider_error` | Out of free-path default; if ever wired, fail closed or degrade typed |

---

## 13. Hosted and CI contracts

| Surface | Rule |
| --- | --- |
| Project | **`pax-agentic-rag`** |
| URL | **https://pax-agentic-rag.vercel.app** |
| Retriever on host | Fixture / fake only unless captain sets env (agents do not) |
| `PRODUCTION_RAG_URL` | Opt-in; **forbidden** value: `https://production-rag.vercel.app` |
| CI | Offline free path; live HTTP tests skip when URL unset |
| `hosted_smoke.ps1` | Script + vault digest; not flaky default CI network job |
| Recycle | Expect empty run ids; demos use downloaded JSON / packs |

---

## 14. Work hygiene

- Worktree: `C:\dev\portfolio-workers\a6-p2-v1-season` · branch `a6/p2-v1-season` (do not recycle `a6-p2-v03` for season commits).
- One engineer; **no subagents**; no force-push.
- Second brain: session digests under `C:\obsidian-mind\work\sessions\`; long logs via `fm log`, not chat paste.
- Secrets: never write credential **values** into the vault or the repo.
- Language: product docs in English (match repo); digests may be ES/EN as fleet practice.

---

## 15. Week 1 exit (this commit)

**In scope**

- [x] Create season worktree from `origin/main` @ `dc80188`
- [x] Author `docs/SEASON.md` with ≥15 invariants, eval plan n≥40, month plan, pack/tools design, PLANNED list
- [x] Commit design only

**Out of scope for Week 1**

- Implementing experiment records, third tool, n≥40 goldens, pack UI, load harness, v1.0 tag
- Reporting season **OK**
- Creating or promoting any Vercel project other than documenting `pax-agentic-rag`

**Next concrete step (Month 1 Week 2):** add `ExperimentRecord` model + tests mapping from current run artifacts; then grow goldens with difficulty predicates without touching critic-can-lose expects.
