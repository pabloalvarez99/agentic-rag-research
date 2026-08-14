# Research-loop golden dataset

[`golden_research.jsonl`](golden_research.jsonl) is a hand-written, offline set of
behavioral expectations for the bounded research loop. It contains 17 cases against the
committed fake corpus. The file is evidence for the evaluation design; an evaluation
runner is still M5 work and is not claimed as LIVE.

No case contains a generated answer. Goldens constrain terminal behavior, budget use,
citations, provenance, and named gaps. That keeps an implementation from passing merely
because its prose changed to resemble a stored answer.

## Coverage

| Category | Cases | What it exercises |
| --- | ---: | --- |
| `answerable_single_hop` | 4 | One retrieval should be enough; spending another step is waste. |
| `answerable_multi_hop` | 3 | The first planned hop misses and a later hop reaches answerable evidence. |
| `unanswerable` | 4 | Refusal when there is no evidence, plus refusal when retrieved evidence is too thin. |
| `budget_stress` | 4 | A deliberately small budget separates partial grounded work from a confident answer. |
| `thin_evidence` | 2 | Full-budget controls for paired budget-stress questions. |

Five `pair_id` groups hold the question constant while changing only a bound. These pairs
make budget effects observable instead of comparing unrelated prompts.

## JSONL schema

Each non-empty line is one JSON object. Unknown fields should be rejected by the future
loader so schema drift cannot pass silently.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable, unique case identifier. |
| `category` | string | Behavioral slice from the table above. |
| `question` | string | Input question sent to the research loop. |
| `max_steps` | integer | Maximum retrieval calls allowed for this run. |
| `top_k` | integer | Maximum passages returned by one retrieval call. |
| `pair_id` | string or null | Links cases that isolate one changed budget. |
| `expect` | object | Mechanical constraints on the finished run. |
| `why` | string | Human-checkable reason the case exists and what regression it catches. |

`expect` has this shape:

| Field | Type | Constraint |
| --- | --- | --- |
| `status` | string | `done`, `refused`, or `budget_exhausted`. |
| `stop_reason` | string | Expected reason from the loop's closed outcome set. |
| `steps_used` | integer | Exact number of retrieval calls expected. |
| `min_citations` / `max_citations` | integer | Inclusive bounds on distinct citations. |
| `cite_chunk_ids_any` | string[] | At least one listed chunk must be cited; empty means no required chunk. |
| `min_distinct_sources` | integer | Minimum distinct `source_path` values cited. |
| `gap_kinds_any` | string[] | At least one listed gap kind must appear; empty means none is required. |

## Integrity rules

A loader or test for this dataset should fail before running cases when:

- a line is not valid JSON, an id is duplicated, or a required field is absent;
- a status and stop reason are incompatible with the outcome table in
  [architecture.md](../../docs/architecture.md#how-a-run-ends-as-a-function-of-three-facts);
- citation bounds are negative, reversed, or exceed `max_steps * top_k`;
- a required chunk id does not exist in the committed fake corpus;
- a `no_evidence` expectation requires citations;
- a pair changes its question as well as its budget; or
- the required slices — answerable multi-hop, unanswerable, and budget stress — are empty.

## Adding a case

Derive the expectation from the documented planner, critic, budget, and outcome rules —
never by copying whatever the implementation happened to print. Add a narrow rationale,
run the complete offline suite, and inspect the trace when the expectation disagrees. A
disagreement means the rule changed, the implementation regressed, or the expectation is
wrong; decide which before editing the golden.

