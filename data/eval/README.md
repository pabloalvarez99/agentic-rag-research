# Golden research dataset

`golden_research.jsonl` contains **48** hand-written cases for the deterministic
research loop (season v1.0 floor n≥40). The cases target the packaged Markdown
corpus and run with the fake backend: no API key, network call, or billed
provider is involved.

Run the complete scorecard from the repository root:

```bash
python -m agentic_rag.evals.run
```

Use `--pretty` for indented JSON or `--dataset PATH` to validate another JSONL
file. Exit code `0` means every expectation passed, `1` means at least one case
failed, and `2` means the dataset could not be loaded or validated.

## Coverage

| Category | Purpose |
| --- | --- |
| `answerable_single_hop` | One retrieval step → grounded evidence and a terminal answer. |
| `answerable_multi_hop` | Compound questions; multi-step evidence. |
| `unanswerable` | Off-corpus questions must refuse; never invent. |
| `thin_evidence` | Notes may exist but insufficient/off-topic — includes **critic-can-lose**. |
| `budget_stress` | Low/high budgets and paired questions. |
| `tool_budget` | Per-tool `max_calls` exhaust → `tool_budget_spent`. |

Season v1.0 requires **n ≥ 40**, difficulty predicates, and permanent
`critic-notes-exist-not-success` → `refused`. Loader also requires
`tool_budget` and `thin_evidence` categories.

## Record schema

Each JSONL line is one strict `GoldenCase`; unknown fields are rejected.

| Field | Meaning |
| --- | --- |
| `id` | Stable unique case identifier. |
| `category` | Behavioral slice shown above. |
| `question` | Exact input to the research loop. |
| `max_steps` | Retrieval-step budget, from 1 through 20. |
| `top_k` | Maximum passages returned per retrieval, from 1 through 50. |
| `pair_id` | Optional link between cases that keep the question identical while changing a control such as budget. |
| `expect.status` | Expected `done`, `refused`, or `budget_exhausted` terminal state. |
| `expect.stop_reason` | Expected closed-set reason including `tool_budget_spent`. |
| `max_tool_calls` | Optional per-tool caps for the case. |
| `expect.steps_used` | Exact retrieval steps expected from the deterministic loop. |
| `expect.min_citations`, `expect.max_citations` | Inclusive citation-count bounds. |
| `expect.cite_chunk_ids_any` | Acceptable corpus chunk ids; at least one must be cited when the list is non-empty. |
| `expect.min_distinct_sources` | Minimum number of distinct cited source paths. |
| `expect.gap_kinds_any` | Acceptable gap kinds; at least one must appear when the list is non-empty. |
| `why` | Human-readable reason the expectation belongs in the dataset. |

The loader also rejects duplicate ids, missing required categories, citation
bounds larger than `max_steps × top_k`, `no_evidence` cases that allow citations,
unknown chunk ids, and pairs whose questions differ.

## Scorecard metrics (control only)

The runner reports each case's observed status, stop reason, steps, citation
presence/count, pass/fail verdict, and exact failures. Aggregate metrics are:

- `total_cases`, `passed_cases`, and `pass_rate`;
- `mean_steps_used` — retrieval steps spent under the budget;
- `has_citations_rate` / `citation_present_rate` — fraction of cases with ≥1 citation;
- `status_counts` — terminal status distribution;
- `stop_reason_counts` — closed-set stop reason distribution;
- `unanswerable_cases`, `refused_unanswerable`, `refused_unanswerable_rate` — whether
  off-corpus questions refuse rather than invent.

These measure **control**: budgets, stop reasons, citation presence, and honest
refusal on a committed lexical fixture. They do **not** measure answer quality,
retrieval quality, faithfulness, latency, production readiness, or agent uplift.
They never claim to beat another system.

## Curation and provenance

The questions and expectations were written for this repository and are released
under its MIT licence. No external benchmark, scraped content, personal data, or
generated system answer is copied into the file. Expectations come from the
documented planner, critic, budget, citation, and terminal-outcome rules plus the
committed corpus.

When changing a case:

1. Keep `why` specific enough for a reviewer to derive the expectation.
2. Confirm every named chunk exists in `DEFAULT_CORPUS`.
3. Run `python -m agentic_rag.evals.run --pretty`.
4. Run `python -m pytest -q tests/evals` and commit the JSONL with its docs.
