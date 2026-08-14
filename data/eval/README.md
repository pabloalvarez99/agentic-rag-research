# Golden research dataset

`golden_research.jsonl` contains 17 hand-written cases for the deterministic
research loop. The cases target the packaged 20-passage Markdown corpus and run
with the fake backend: no API key, network call, or billed provider is involved.

Run the complete scorecard from the repository root:

```bash
python -m agentic_rag.evals.run
```

Use `--pretty` for indented JSON or `--dataset PATH` to validate another JSONL
file. Exit code `0` means every expectation passed, `1` means at least one case
failed, and `2` means the dataset could not be loaded or validated.

## Coverage

| Category | Cases | Purpose |
| --- | ---: | --- |
| `answerable_single_hop` | 4 | One retrieval step should produce grounded evidence and a terminal answer. |
| `answerable_multi_hop` | 3 | Compound questions exercise planning and evidence gathered across concepts. |
| `unanswerable` | 4 | Off-corpus questions must refuse with no citations and named gaps. |
| `thin_evidence` | 2 | Some evidence exists, but it is insufficient for a completed answer. |
| `budget_stress` | 4 | Paired low/high-budget cases make step consumption and terminal policy observable. |

The 17-case set includes four explicit unanswerable cases and four budget-stress
cases. Required loader categories are `answerable_multi_hop`, `unanswerable`, and
`budget_stress`; the two additional slices keep ordinary and thin-evidence paths
visible in the scorecard.

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
| `expect.stop_reason` | Expected `evidence_sufficient`, `no_evidence`, `insufficient_evidence`, or `budget_spent`. |
| `expect.steps_used` | Exact retrieval steps expected from the deterministic loop. |
| `expect.min_citations`, `expect.max_citations` | Inclusive citation-count bounds. |
| `expect.cite_chunk_ids_any` | Acceptable corpus chunk ids; at least one must be cited when the list is non-empty. |
| `expect.min_distinct_sources` | Minimum number of distinct cited source paths. |
| `expect.gap_kinds_any` | Acceptable gap kinds; at least one must appear when the list is non-empty. |
| `why` | Human-readable reason the expectation belongs in the dataset. |

The loader also rejects duplicate ids, missing required categories, citation
bounds larger than `max_steps × top_k`, `no_evidence` cases that allow citations,
unknown chunk ids, and pairs whose questions differ.

## Scorecard metrics

The runner reports each case's observed status, stop reason, steps, citation
presence/count, pass/fail verdict, and exact failures. Aggregate metrics are:

- `total_cases`, `passed_cases`, and `pass_rate`;
- `mean_steps_used`;
- `has_citations_rate`; and
- `status_counts`.

These measure deterministic contract conformance on a committed lexical fixture.
They do not measure answer quality, retrieval quality, faithfulness, latency, or
production readiness, and they do not establish agent uplift over a single pass.

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
