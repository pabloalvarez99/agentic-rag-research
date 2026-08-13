# Agentic research loop — fixture scorecard

> **Evidence class: fixture-contract.** Fixture-contract evidence. Every number below describes the agent's control plane — stop decisions, budgets, citation resolution, traces, determinism — measured against a deterministic in-process retrieval fixture over a small committed corpus. It is not a measurement of retrieval quality, answer quality, faithfulness, latency or production readiness, and no number here supports a comparison with any other system.

| Field | Value |
| --- | --- |
| Dataset | `data/eval/golden_research.jsonl` |
| Dataset digest | `sha256:03e6c070b2bbafb380710bbcd433e9c30d2d40d33072927b9de1b4e813f697da` |
| Cases | 66 |
| Retrieval backend | `fake` over 5 passages |
| Package version | 0.1.0 |
| Command | `python -m agentic_rag.evals.run --dataset data/eval/golden_research.jsonl --repeat 3 --out reports/evals/latest.json --markdown reports/evals/latest.md --reproducible` |
| Network | not used |
| Cost | $0 billed |
| Generated at | normalized |
| Results digest | `sha256:0e568d5e2a5a0c7faaabfec23730fecbe01e5d35841e14e00dbffe4903fddc6b` |

Volatile fields, excluded from the digest: `run.generated_at`, `run.python_version`, `run.platform`.

## Hard invariants

Properties every run must have, whatever the dataset expects. A violation fails the evaluation and exits nonzero.

| Invariant | Property | Runs checked | Result |
| --- | --- | --- | --- |
| `budget_respected` | Steps taken never exceed the budget the case set, and the trace agrees. | 66 | held |
| `terminal_outcome` | Every run ends terminal, with a closed-set reason and a report. | 66 | held |
| `trace_contract` | The trace opens with a plan, pairs calls with results, and ends with stop. | 66 | held |
| `plan_precedes_tools` | A capped, non-empty plan is recorded before any tool runs. | 66 | held |
| `citations_resolve` | Every printed marker resolves, in order, to a passage that was retrieved. | 66 | held |
| `provenance_is_real` | No cited chunk id or source path comes from outside the corpus. | 66 | held |
| `evidence_deduplicated` | A chunk returned by two steps is stored, and cited, once. | 66 | held |
| `cite_or_refuse` | An answer carries citations; a run with no evidence refuses. | 66 | held |
| `backend_is_the_bound_one` | Every retrieval was served by the backend the runner bound. | 66 | held |
| `gaps_are_reported` | Every gap the critic named appears in the report. | 66 | held |
| `deterministic_output` | Repeating the whole evaluation produces byte-identical case records. | 3 | held |
| `surface_form_invariance` | Cases differing only in surface form produce the same outcome and evidence. | 66 | held |

## Determinism

stable across 3 passes. The digest covers the per-case records only, so it is unaffected by when or where the evaluation ran.

| Pass | Digest of case records |
| --- | --- |
| 1 | `sha256:041797a5421aed721a37c683887a15192680348bc6e0f48310d5f920d561404a` |
| 2 | `sha256:041797a5421aed721a37c683887a15192680348bc6e0f48310d5f920d561404a` |
| 3 | `sha256:041797a5421aed721a37c683887a15192680348bc6e0f48310d5f920d561404a` |

## Descriptive metrics

Agreement between the curated expectations and what the loop did. These do not fail the run: a disagreement can mean the loop regressed or that the expectation was wrong, and only a reader can tell which.

| Metric | Measures | Denominator | Result |
| --- | --- | --- | --- |
| `terminal_status_agreement` | Runs whose terminal status was the one the case derived from the rules. | cases, all of which declare a terminal status | 100.0% (66/66) |
| `stop_reason_agreement` | Runs whose stop reason was the one the case derived from the rules. | cases, all of which declare a stop reason | 100.0% (66/66) |
| `budget_compliance` | Runs that spent no more steps than the case allowed. | cases, all of which set a budget | 100.0% (66/66) |
| `citation_marker_validity` | Printed markers that are numbered in order and resolve to a retrieved chunk. | citation markers printed across every report | 100.0% (60/60) |
| `expected_source_match` | Runs citing every source path the case derived as necessary. | cases that declare expected source paths | 100.0% (53/53) |
| `expected_chunk_match` | Runs gathering every chunk id the case derived as necessary. | cases that declare expected chunk ids | 100.0% (53/53) |
| `citation_bounds_agreement` | Runs whose citation count fell inside the bounds the case declared. | cases that bound the citation count non-trivially | 100.0% (66/66) |
| `plan_expansion_agreement` | Compound questions the planner split into at least the expected number. | cases expecting a plan of more than one sub-question | 100.0% (18/18) |
| `repeated_evidence_dedup` | Runs where one chunk came back from two steps and was stored and cited once. | cases that expect a chunk to be returned twice | 100.0% (6/6) |
| `refusal_recall` | Runs that refused where the rules say a refusal was the outcome. | cases expecting a refusal | 100.0% (16/16) |
| `unexpected_refusal_rate` | Runs that refused where the rules imply an answer or a partial. Lower is better. | cases not expecting a refusal | 0.0% (0/50) |
| `trace_contract_validity` | Runs whose trace satisfied the recorded contract in full. | cases, all of which record a trace | 100.0% (66/66) |
| `free_path_share` | Runs served exclusively by the bound in-process fixture backend. This is what a zero-cost claim rests on. | runs that spent at least one retrieval step | 100.0% (66/66) |
| `all_declared_expectations_met` | Runs that met every constraint their case declared. | cases, all of which declare at least one constraint | 100.0% (66/66) |
| `invariant_clean_runs` | Runs that violated no hard invariant. Any shortfall fails the run. | cases, all of which are checked against every invariant | 100.0% (66/66) |

## By behaviour slice

### `single_source_answerable`

| Metric | Result |
| --- | --- |
| `terminal_status_agreement` | 100.0% (14/14) |
| `stop_reason_agreement` | 100.0% (14/14) |
| `expected_source_match` | 100.0% (14/14) |
| `plan_expansion_agreement` | n/a (0 denominator) |
| `repeated_evidence_dedup` | n/a (0 denominator) |
| `all_declared_expectations_met` | 100.0% (14/14) |

### `multi_concept`

| Metric | Result |
| --- | --- |
| `terminal_status_agreement` | 100.0% (12/12) |
| `stop_reason_agreement` | 100.0% (12/12) |
| `expected_source_match` | 100.0% (12/12) |
| `plan_expansion_agreement` | 100.0% (12/12) |
| `repeated_evidence_dedup` | n/a (0 denominator) |
| `all_declared_expectations_met` | 100.0% (12/12) |

### `no_evidence_refusal`

| Metric | Result |
| --- | --- |
| `terminal_status_agreement` | 100.0% (14/14) |
| `stop_reason_agreement` | 100.0% (14/14) |
| `expected_source_match` | 100.0% (3/3) |
| `plan_expansion_agreement` | n/a (0 denominator) |
| `repeated_evidence_dedup` | n/a (0 denominator) |
| `all_declared_expectations_met` | 100.0% (14/14) |

### `budget_pressure_partial`

| Metric | Result |
| --- | --- |
| `terminal_status_agreement` | 100.0% (8/8) |
| `stop_reason_agreement` | 100.0% (8/8) |
| `expected_source_match` | 100.0% (8/8) |
| `plan_expansion_agreement` | n/a (0 denominator) |
| `repeated_evidence_dedup` | n/a (0 denominator) |
| `all_declared_expectations_met` | 100.0% (8/8) |

### `duplicate_evidence`

| Metric | Result |
| --- | --- |
| `terminal_status_agreement` | 100.0% (6/6) |
| `stop_reason_agreement` | 100.0% (6/6) |
| `expected_source_match` | 100.0% (6/6) |
| `plan_expansion_agreement` | 100.0% (6/6) |
| `repeated_evidence_dedup` | 100.0% (6/6) |
| `all_declared_expectations_met` | 100.0% (6/6) |

### `text_normalization`

| Metric | Result |
| --- | --- |
| `terminal_status_agreement` | 100.0% (12/12) |
| `stop_reason_agreement` | 100.0% (12/12) |
| `expected_source_match` | 100.0% (10/10) |
| `plan_expansion_agreement` | n/a (0 denominator) |
| `repeated_evidence_dedup` | n/a (0 denominator) |
| `all_declared_expectations_met` | 100.0% (12/12) |

## Steps spent

How many retrieval steps each run spent before it stopped.

| Steps | Runs | Share |
| --- | --- | --- |
| 1 | 39 | 59.1% |
| 2 | 21 | 31.8% |
| 3 | 6 | 9.1% |

## Single-pass reference

One retrieval call for the whole question, same fixture, same `top_k`, no plan and no critique. It is a **control-flow** reference: it produces no answer, so it supports no statement about answer quality, and both sides retrieve by lexical overlap over the same five passages.

| Comparison | Cases |
| --- | --- |
| Loop gathered more distinct passages | 0 |
| Loop gathered the same number | 65 |
| Loop gathered fewer | 1 |

## Cases

| Case | Slice | Status / reason | Steps | Citations | Met expectations | Invariants |
| --- | --- | --- | --- | --- | --- | --- |
| `single-source-reciprocal-rank-fusion` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-cross-encoder-reorder` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-marker-resolves-to-nothing` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-refusal-first-class` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-chunking-heading-structure` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-reranker-cost-per-pair` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-dense-vector-same-corpus` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-parametric-memory-padding` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-splitting-keeps-heading-path` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-citation-nobody-could-follow` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-shortlist-candidate-count` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-fusion-over-sparse-keyword` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-cross-encoder-reads-candidate` | single_source_answerable | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `single-source-first-class-outcome-budget-twenty` | single_source_answerable | done / evidence_sufficient | 1/20 | 1 | yes | clean |
| `multi-concept-fusion-then-rerank` | multi_concept | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `multi-concept-resolvable-marker-and-thin-evidence` | multi_concept | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `multi-concept-split-document-and-heading-path` | multi_concept | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `multi-concept-question-mark-split` | multi_concept | done / evidence_sufficient | 1/4 | 2 | yes | clean |
| `multi-concept-refusal-and-dropped-marker` | multi_concept | done / evidence_sufficient | 1/4 | 2 | yes | clean |
| `multi-concept-then-join` | multi_concept | done / evidence_sufficient | 1/4 | 2 | yes | clean |
| `multi-concept-ingest-and-answer-stage` | multi_concept | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `multi-concept-dense-versus-sparse` | multi_concept | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `multi-concept-shortlist-size-and-cost` | multi_concept | done / evidence_sufficient | 1/4 | 3 | yes | clean |
| `multi-concept-off-corpus-first-fragment` | multi_concept | done / evidence_sufficient | 2/4 | 1 | yes | clean |
| `multi-concept-off-corpus-then-reranker` | multi_concept | done / evidence_sufficient | 2/4 | 1 | yes | clean |
| `multi-concept-off-corpus-then-gap-naming` | multi_concept | done / evidence_sufficient | 2/4 | 1 | yes | clean |
| `no-evidence-patagonia-revenues` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-world-cup-final` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-brisket-rest` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-liquid-nitrogen` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-nonstop-to-ushuaia` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-violin-bow-weight` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-bronze-age` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-seasonal-allergies` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-marathon-distance` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-mountain-range` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `no-evidence-mendoza-grape` | no_evidence_refusal | refused / no_evidence | 2/3 | 0 | yes | clean |
| `insufficient-evidence-summarise-chunking` | no_evidence_refusal | refused / insufficient_evidence | 2/3 | 1 | yes | clean |
| `insufficient-evidence-outline-reranker` | no_evidence_refusal | refused / insufficient_evidence | 2/4 | 1 | yes | clean |
| `insufficient-evidence-what-is-a-citation` | no_evidence_refusal | refused / insufficient_evidence | 1/5 | 1 | yes | clean |
| `budget-one-step-chunking` | budget_pressure_partial | budget_exhausted / budget_spent | 1/1 | 1 | yes | clean |
| `budget-two-steps-reranker` | budget_pressure_partial | budget_exhausted / budget_spent | 2/2 | 1 | yes | clean |
| `budget-one-step-reranking` | budget_pressure_partial | budget_exhausted / budget_spent | 1/1 | 1 | yes | clean |
| `budget-one-step-refusal-passage` | budget_pressure_partial | budget_exhausted / budget_spent | 1/1 | 1 | yes | clean |
| `budget-one-step-marker` | budget_pressure_partial | budget_exhausted / budget_spent | 1/1 | 1 | yes | clean |
| `budget-two-steps-fusion` | budget_pressure_partial | budget_exhausted / budget_spent | 2/2 | 1 | yes | clean |
| `budget-two-steps-refusal-rule` | budget_pressure_partial | budget_exhausted / budget_spent | 2/2 | 1 | yes | clean |
| `budget-one-step-wide-top-k` | budget_pressure_partial | budget_exhausted / budget_spent | 1/1 | 1 | yes | clean |
| `duplicate-evidence-chunking-twice` | duplicate_evidence | budget_exhausted / budget_spent | 3/3 | 1 | yes | clean |
| `duplicate-evidence-shortlist-twice` | duplicate_evidence | budget_exhausted / budget_spent | 3/3 | 1 | yes | clean |
| `duplicate-evidence-refusal-twice` | duplicate_evidence | budget_exhausted / budget_spent | 3/3 | 1 | yes | clean |
| `duplicate-evidence-heading-twice` | duplicate_evidence | budget_exhausted / budget_spent | 3/3 | 1 | yes | clean |
| `duplicate-evidence-fusion-twice` | duplicate_evidence | budget_exhausted / budget_spent | 3/3 | 1 | yes | clean |
| `duplicate-evidence-marker-twice` | duplicate_evidence | budget_exhausted / budget_spent | 3/3 | 1 | yes | clean |
| `normalization-fusion-plain` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-fusion-uppercase` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-chunking-plain` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-chunking-extra-whitespace` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-dropped-marker-plain` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-dropped-marker-punctuation` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-cross-encoder-hyphen` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-cross-encoder-em-dash` | text_normalization | done / evidence_sufficient | 1/4 | 1 | yes | clean |
| `normalization-thin-evidence-plain` | text_normalization | done / evidence_sufficient | 1/4 | 2 | yes | clean |
| `normalization-thin-evidence-nbsp` | text_normalization | done / evidence_sufficient | 1/4 | 2 | yes | clean |
| `normalization-off-corpus-plain` | text_normalization | refused / no_evidence | 2/3 | 0 | yes | clean |
| `normalization-off-corpus-uppercase` | text_normalization | refused / no_evidence | 2/3 | 0 | yes | clean |

## What this scorecard does not measure

- **Retrieval quality.** The backend is a lexical-overlap fixture over five committed passages. It is a stand-in for a retrieval service, not a small one.
- **Answer quality or faithfulness.** The synthesiser selects and marks retrieved passages; it writes no prose, so there is nothing to be unfaithful to and nothing here measures whether an answer is good.
- **Latency or throughput.** No timing is recorded, deliberately.
- **Production readiness.** Every run is in-process against a fixture.
- **Any comparison with another system.** The only reference here is the single retrieval pass over the same fixture.

What it does measure: whether the loop stops for the reason its own rules imply, stays inside its budget, cites only what it retrieved, records a complete trace, deduplicates repeated evidence, refuses when it has nothing, and produces the same output twice.
